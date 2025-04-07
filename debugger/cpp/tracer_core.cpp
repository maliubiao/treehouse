/*
以较快的速度过滤掉不关心的代码文件，有用的再交给python层处理
*/
#include <Python.h>
#include <bytesobject.h>
#include <ceval.h>
#include <cpython/code.h>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <mutex>
#include <object.h>
#include <opcode.h>
#include <pyframe.h>
#include <pythonrun.h>
#include <pytypedefs.h>
#include <stdexcept>
#include <string>
#include <tupleobject.h>
#include <unordered_map>
#include <unordered_set>

namespace fs = std::filesystem;

/*
python include里没有这个结构体的定义，下边的是非公开结构体，
可能随着版本不同而不同 这个结构是从python 3.11版本源代码那里copy过来的
不同的版本如果结构不同，访问指针可能会崩，需要适配
用这个结构主要为了实现损耗比较小的变量trace, bytecode级别, 工作在native层
*/
struct internal_frame {
  PyObject_HEAD PyFrameObject *f_back; /* previous frame, or NULL */
  struct _PyInterpreterFrame *f_frame; /* points to the frame data */
  PyObject *f_trace;                   /* Trace function */
  int f_lineno;          /* Current line number. Only valid if non-zero */
  char f_trace_lines;    /* Emit per-line trace events? */
  char f_trace_opcodes;  /* Emit per-opcode trace events? */
  char f_fast_as_locals; /* Have the fast locals of this frame been converted to
                            a dict? */
  /* The frame data, if this frame object owns the frame */
  PyObject *_f_frame_data[1];
};

struct CodeUnit {
  uint8_t code;
  uint8_t arg;
};

typedef struct _PyInterpreterFrame {
  PyCodeObject *f_code; /* Strong reference */
  struct _PyInterpreterFrame *previous;
  PyObject *f_funcobj;  /* Strong reference. Only valid if not on C stack */
  PyObject *f_globals;  /* Borrowed reference. Only valid if not on C stack */
  PyObject *f_builtins; /* Borrowed reference. Only valid if not on C stack */
  PyObject *f_locals;   /* Strong reference, may be NULL. Only valid if not on C
                           stack */
  PyFrameObject *frame_obj; /* Strong reference, may be NULL. Only valid if not
                               on C stack */
  // NOTE: This is not necessarily the last instruction started in the given
  // frame. Rather, it is the code unit *prior to* the *next* instruction. For
  // example, it may be an inline CACHE entry, an instruction we just jumped
  // over, or (in the case of a newly-created frame) a totally invalid value:
  struct CodeUnit *prev_instr;
  int stacktop; /* Offset of TOS from localsplus  */
  /* The return_offset determines where a `RETURN` should go in the caller,
   * relative to `prev_instr`.
   * It is only meaningful to the callee,
   * so it needs to be set in any CALL (to a Python function)
   * or SEND (to a coroutine or generator).
   * If there is no callee, then it is meaningless. */
  uint16_t return_offset;
  char owner;
  /* Locals and stack */
  PyObject *localsplus[1];
} internal_frame_PyInterpreterFrame;

class TraceDispatcher {
private:
  fs::path target_path;
  std::unordered_map<std::string, bool> path_cache;
  std::unordered_set<PyFrameObject *> active_frames;
  PyObject *trace_logic;
  PyObject *config;
  std::mutex cache_mutex;

  bool is_target_frame(PyFrameObject *frame) {
    if (!frame)
      return false;
    PyCodeObject *code = PyFrame_GetCode(frame);
    if (!code)
      return false;
    PyObject *filename = code->co_filename;
    if (!filename) {
      Py_DECREF(code);
      return false;
    }
    std::string filename_str(PyUnicode_AsUTF8AndSize(filename, nullptr));
    Py_DECREF(code);
    {
      std::lock_guard<std::mutex> lock(cache_mutex);
      auto it = path_cache.find(filename_str);
      if (it != path_cache.end()) {
        bool matched = it->second;
        struct internal_frame *frame_internal = (struct internal_frame *)frame;
        if (!matched) {
          frame_internal->f_trace_lines = 0;
        }
        return matched;
      }
    }

    try {
      PyObject *result = PyObject_CallMethod(config, "match_filename", "s",
                                             filename_str.c_str());
      if (result == NULL) {
        return false;
      }
      bool matched = PyObject_IsTrue(result);
      Py_DECREF(result);

      {
        std::lock_guard<std::mutex> lock(cache_mutex);
        path_cache[filename_str] = matched;
      }
      struct internal_frame *frame_internal = (struct internal_frame *)frame;
      if (!matched) {
        frame_internal->f_trace_lines = 0;
      }
      return matched;
    } catch (...) {
      PyErr_Clear();
      return false;
    }
  }

public:
  TraceDispatcher(const char *target_path, PyObject *tracer_logic,
                  PyObject *config)
      : target_path(fs::absolute(fs::path(target_path))), config(config),
        trace_logic(tracer_logic) {
    Py_INCREF(trace_logic);
    Py_INCREF(config);
    if (!fs::exists(this->target_path)) {
      throw std::runtime_error("Target path not found: " +
                               std::string(target_path));
    }
  }

  ~TraceDispatcher() {
    Py_XDECREF(trace_logic);
    Py_XDECREF(config);
  }

  static int trace_dispatch_thunk(PyObject *self, PyFrameObject *frame,
                                  int event, PyObject *arg) {
    TraceDispatcher *dispatcher = reinterpret_cast<TraceDispatcher *>(self);
    return dispatcher->trace_dispatch(frame, event, arg);
  }

  int trace_dispatch(PyFrameObject *frame, int event, PyObject *arg) {
    switch (event) {
    case PyTrace_CALL:
      return handle_call_event(frame, arg);
    case PyTrace_RETURN:
      return handle_return_event(frame, arg);
    case PyTrace_LINE:
      return handle_line_event(frame, arg);
    case PyTrace_EXCEPTION:
      return handle_exception_event(frame, arg);
    case PyTrace_OPCODE:
      return handle_opcode_event(frame, arg);
    default:
      return 0;
    }
  }

  int handle_opcode_event(PyFrameObject *frame, PyObject *arg) {
    {
      int lasti = PyFrame_GetLasti(frame);
      PyCodeObject *code = PyFrame_GetCode(frame);

      struct internal_frame *frame_internal = (struct internal_frame *)frame;
      internal_frame_PyInterpreterFrame *frame_interpreter =
          (internal_frame_PyInterpreterFrame *)frame_internal->f_frame;
      uint8_t last_opcode = frame_interpreter->prev_instr->code;
      PyObject *var_name = PyTuple_GET_ITEM(code->co_localsplusnames,
                                            frame_interpreter->prev_instr->arg);
      Py_DECREF(code);
      
      // access the co_code
    //   printf("\nopcode: %d, oparg: %d, lasti: %d\n", last_opcode,
    //          frame_interpreter->prev_instr->arg, lasti);
      if (last_opcode == STORE_FAST) {
        PyObject **sp =
        frame_interpreter->localsplus + frame_interpreter->stacktop;
        PyObject *stack_top_element = sp[-1];
        if(var_name == NULL || stack_top_element == NULL) {
          return 0;
        }
        Py_INCREF(var_name);
        Py_INCREF(stack_top_element);
        PyObject *ret = PyObject_CallMethod(trace_logic, "handle_opcode", "OOO",
                                            (PyObject *)frame, var_name, stack_top_element);
        Py_DECREF(var_name);
        Py_DECREF(stack_top_element);
        if (ret != NULL) {
          Py_DECREF(ret);
        } else {
          printf("Error in handle_opcode_event\n");
          PyErr_Print();
          PyErr_Clear();
        }
      }
    }
    return 0;
  }

  int handle_call_event(PyFrameObject *frame, PyObject *arg) {
    if (is_target_frame(frame)) {
      {
        std::lock_guard<std::mutex> lock(cache_mutex);
        active_frames.insert(frame);
      }
      PyObject *ret = PyObject_CallMethod(trace_logic, "handle_call", "O",
                                          (PyObject *)frame);
      if (ret != NULL) {
        Py_DECREF(ret);
      } else {
        printf("Error in handle_call_event\n");
        PyErr_Print();
        PyErr_Clear();
      }
    }
    return 0;
  }

  int handle_return_event(PyFrameObject *frame, PyObject *arg) {
    {
      std::lock_guard<std::mutex> lock(cache_mutex);
      if (active_frames.find(frame) != active_frames.end()) {
        if(arg == NULL) {
            arg = Py_None;
        }
        PyObject *ret = PyObject_CallMethod(trace_logic, "handle_return", "OO",
                                            (PyObject *)frame, arg);
        if (ret != NULL) {
          Py_DECREF(ret);
        } else {
          printf("Error in handle_return_event\n");
          PyErr_Print();
          PyErr_Clear();
        }
        active_frames.erase(frame);
      }
    }
    return 0;
  }

  int handle_line_event(PyFrameObject *frame, PyObject *arg) {
    {
      std::lock_guard<std::mutex> lock(cache_mutex);
      if (active_frames.find(frame) != active_frames.end()) {
        PyObject *ret = PyObject_CallMethod(trace_logic, "handle_line", "O",
                                            (PyObject *)frame);
        if (ret != NULL) {
          Py_DECREF(ret);
        } else {
          printf("Error in handle_line_event\n");
          PyErr_Print();
          PyErr_Clear();
        }
      }
    }
    return 0;
  }

  int handle_exception_event(PyFrameObject *frame, PyObject *arg) {
    {
      std::lock_guard<std::mutex> lock(cache_mutex);
      if (active_frames.find(frame) != active_frames.end()) {
        PyObject *type, *value, *traceback;
        if (!PyArg_UnpackTuple(arg, "exception", 3, 3, &type, &value,
                               &traceback)) {
          return -1;
        }
        PyObject *ret = PyObject_CallMethod(trace_logic, "handle_exception",
                                            "OOO", type, value, traceback);
        if (ret != NULL) {
          Py_DECREF(ret);
        } else {
          printf("Error in handle_exception_event\n");
          PyErr_Print();
          PyErr_Clear();
        }
      }
    }
    return 0;
  }

  void start() {
    PyEval_SetTrace(&trace_dispatch_thunk, reinterpret_cast<PyObject *>(this));
    PyObject *ret = PyObject_CallMethod(trace_logic, "start", nullptr);
    if (ret != NULL) {
      Py_DECREF(ret);
    }
  }

  void stop() {
    PyEval_SetTrace(nullptr, nullptr);
    PyObject *ret = PyObject_CallMethod(trace_logic, "stop", nullptr);
    if (ret != NULL) {
      Py_DECREF(ret);
    }
  }
};

typedef struct {
  PyObject_HEAD TraceDispatcher *dispatcher;
} TraceDispatcherObject;

static PyObject *TraceDispatcher_new(PyTypeObject *type, PyObject *args,
                                     PyObject *kwargs) {
  TraceDispatcherObject *self =
      (TraceDispatcherObject *)type->tp_alloc(type, 0);
  if (!self) {
    return nullptr;
  }
  self->dispatcher = nullptr;
  return (PyObject *)self;
}

static PyObject *TraceDispatcher_start(PyObject *self, PyObject *args) {
  TraceDispatcherObject *obj = (TraceDispatcherObject *)self;
  if (!obj->dispatcher) {
    PyErr_SetString(PyExc_RuntimeError, "Invalid dispatcher");
    return nullptr;
  }
  obj->dispatcher->start();
  Py_RETURN_NONE;
}

static PyObject *TraceDispatcher_stop(PyObject *self, PyObject *args) {
  TraceDispatcherObject *obj = (TraceDispatcherObject *)self;
  if (!obj->dispatcher) {
    PyErr_SetString(PyExc_RuntimeError, "Invalid dispatcher");
    return nullptr;
  }
  obj->dispatcher->stop();
  Py_RETURN_NONE;
}

static PyMethodDef TraceDispatcher_methods[] = {
    {"start", (PyCFunction)TraceDispatcher_start, METH_NOARGS, "Start tracing"},
    {"stop", (PyCFunction)TraceDispatcher_stop, METH_NOARGS, "Stop tracing"},
    {nullptr, nullptr, 0, nullptr}};

static void TraceDispatcher_dealloc(TraceDispatcherObject *self) {
  self->dispatcher->~TraceDispatcher();
  Py_TYPE(self)->tp_free((PyObject *)self);
}

static int TraceDispatcher_init(TraceDispatcherObject *self, PyObject *args,
                                PyObject *kwargs) {
  const char *target_path;
  PyObject *trace_logic;
  PyObject *config;
  static const char *kwlist[] = {"target_path", "trace_logic", "config",
                                 nullptr};

  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "sOO",
                                   const_cast<char **>(kwlist), &target_path,
                                   &trace_logic, &config)) {
    return -1;
  }

  try {
    self->dispatcher = new TraceDispatcher(target_path, trace_logic, config);
  } catch (const std::exception &e) {
    PyErr_SetString(PyExc_RuntimeError, e.what());
    return -1;
  }
  return 0;
}

static PyTypeObject TraceDispatcherType = {
    PyVarObject_HEAD_INIT(nullptr, 0).tp_name = "tracer_core.TraceDispatcher",
    .tp_basicsize = sizeof(TraceDispatcherObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,
    .tp_doc = "Trace dispatcher object",
    .tp_new = TraceDispatcher_new,
    .tp_init = (initproc)TraceDispatcher_init,
    .tp_dealloc = (destructor)TraceDispatcher_dealloc,
    .tp_methods = TraceDispatcher_methods,
};

static PyModuleDef tracer_core_module = {PyModuleDef_HEAD_INIT,
                                         .m_name = "tracer_core",
                                         .m_doc = "Python tracer core module",
                                         .m_size = -1,
                                         .m_methods = nullptr,
                                         .m_slots = nullptr,
                                         .m_traverse = nullptr,
                                         .m_clear = nullptr,
                                         .m_free = nullptr};

PyMODINIT_FUNC PyInit_tracer_core(void) {
  PyObject *module = PyModule_Create(&tracer_core_module);
  if (!module)
    return nullptr;

  if (PyType_Ready(&TraceDispatcherType) < 0)
    return nullptr;

  Py_INCREF(&TraceDispatcherType);
  if (PyModule_AddObject(module, "TraceDispatcher",
                         (PyObject *)&TraceDispatcherType) < 0) {
    Py_DECREF(&TraceDispatcherType);
    Py_DECREF(module);
    return nullptr;
  }

  return module;
}