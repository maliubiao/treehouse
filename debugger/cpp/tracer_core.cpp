/*
以较快的速度过滤掉不关心的代码文件，有用的再交给python层处理
*/
#include <Python.h>
#include <boolobject.h>
#include <bytesobject.h>
#include <ceval.h>
#include <cpython/code.h>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <longobject.h>
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

// Define the frame structure for Python 3.11.12
typedef struct _PyInterpreterFrame_3_11_12 {
  /* "Specials" section */
  PyFunctionObject *f_func; /* Strong reference */
  PyObject *f_globals;      /* Borrowed reference */
  PyObject *f_builtins;     /* Borrowed reference */
  PyObject *f_locals;       /* Strong reference, may be NULL */
  PyCodeObject *f_code;     /* Strong reference */
  PyFrameObject *frame_obj; /* Strong reference, may be NULL */
  /* Linkage section */
  struct _PyInterpreterFrame *previous;
  struct CodeUnit *prev_instr;
  int stacktop;  /* Offset of TOS from localsplus  */
  bool is_entry; // Whether this is the "root" frame for the current _PyCFrame.
  char owner;
  /* Locals and stack */
  PyObject *localsplus[1];
} internal_frame_PyInterpreterFrame_3_11_12;

// Define the default frame structure
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
  struct CodeUnit *prev_instr;
  int stacktop; /* Offset of TOS from localsplus  */
  uint16_t return_offset;
  char owner;
  /* Locals and stack */
  PyObject *localsplus[1];
} internal_frame_PyInterpreterFrame;

// Use compile-time checks to select the correct structure based on Python
// version
#if PY_MAJOR_VERSION == 3 && PY_MINOR_VERSION == 11 && PY_MICRO_VERSION == 12
#define internal_frame_PyInterpreterFrame                                      \
  internal_frame_PyInterpreterFrame_3_11_12
#endif

class TraceDispatcher {
private:
  fs::path target_path;
  std::unordered_map<std::string, bool> path_cache;
  std::unordered_set<PyFrameObject *> active_frames;
  PyFrameObject *bad_frame = nullptr;
  PyObject *trace_logic;
  PyObject *config;
  std::mutex cache_mutex;

  void print_stack_trace() { PyErr_PrintEx(1); }

  bool is_excluded_function(PyFrameObject *frame) {
    if (!frame || !config)
      return false;

    PyCodeObject *code = PyFrame_GetCode(frame);
    if (!code)
      return false;

    PyObject *func_name = code->co_name;
    if (!func_name) {
      Py_DECREF(code);
      return false;
    }

    PyObject *result =
        PyObject_CallMethod(config, "is_excluded_function", "O", func_name);
    Py_DECREF(code);

    if (result == NULL) {
      return false;
    }

    bool excluded = PyObject_IsTrue(result);
    Py_DECREF(result);
    return excluded;
  }

  bool is_target_frame(PyFrameObject *frame) {
    if (!frame)
      return false;

    if (bad_frame != nullptr && frame == bad_frame) {
      return false;
    }

    if (is_excluded_function(frame)) {
      bad_frame = frame;
      return false;
    }

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
  }

public:
  TraceDispatcher(const char *target_path, PyObject *tracer_logic,
                  PyObject *config)
      : target_path(fs::absolute(fs::path(target_path))), config(config),
        trace_logic(tracer_logic) {
    Py_INCREF(trace_logic);
    Py_INCREF(config);
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
    if (bad_frame != nullptr && frame == bad_frame &&
        (event == PyTrace_RETURN || event == PyTrace_EXCEPTION)) {
      bad_frame = nullptr;
      return 0;
    }

    if (bad_frame != nullptr && frame == bad_frame) {
      return 0;
    }

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

  void add_target_frame(PyFrameObject *frame) {
    std::lock_guard<std::mutex> lock(cache_mutex);
    active_frames.insert(frame);
    struct internal_frame *frame_internal = (struct internal_frame *)frame;
    frame_internal->f_trace_lines = 1;
  }

  int handle_opcode_event(PyFrameObject *frame, PyObject *arg) {
    if (bad_frame != nullptr && frame == bad_frame) {
      return 0;
    }

    int lasti = PyFrame_GetLasti(frame);
    PyCodeObject *code = PyFrame_GetCode(frame);

    struct internal_frame *frame_internal = (struct internal_frame *)frame;
    internal_frame_PyInterpreterFrame *frame_interpreter =
        (internal_frame_PyInterpreterFrame *)frame_internal->f_frame;
    uint8_t last_opcode = frame_interpreter->prev_instr->code;
    PyObject *var_name = NULL;
    /// 虚构机执行细节，参考Python/generated_cases.c.h, 或者dis模块的stack
    /// 操作说明
    if (last_opcode == STORE_GLOBAL || last_opcode == STORE_NAME ||
        last_opcode == STORE_ATTR) {
      var_name =
          PyTuple_GET_ITEM(code->co_names, frame_interpreter->prev_instr->arg);
    } else if (last_opcode == STORE_FAST) {
      var_name = PyTuple_GET_ITEM(code->co_localsplusnames,
                                  frame_interpreter->prev_instr->arg);
    } else if (last_opcode == STORE_SUBSCR) {
      PyObject **sp =
          frame_interpreter->localsplus + frame_interpreter->stacktop;
      var_name = sp[-1];
    }
    Py_DECREF(code);
    if (var_name != NULL) {
      PyObject **sp =
          frame_interpreter->localsplus + frame_interpreter->stacktop;
      PyObject *stack_top_element = sp[-1];
      if (last_opcode == STORE_ATTR) {
        stack_top_element = sp[-2];
      } else if (last_opcode == STORE_SUBSCR) {
        stack_top_element = sp[-3];
      }
      if (var_name == NULL || stack_top_element == NULL) {
        return 0;
      }
      Py_INCREF(var_name);
      Py_INCREF(stack_top_element);
      PyObject *opcode_object = PyLong_FromSize_t(last_opcode);
      PyObject *ret = PyObject_CallMethod(trace_logic, "handle_opcode", "OOOO",
                                          (PyObject *)frame, opcode_object,
                                          var_name, stack_top_element);
      Py_DECREF(var_name);
      Py_DECREF(stack_top_element);
      Py_DECREF(opcode_object);
      if (ret != NULL) {
        Py_DECREF(ret);
      } else {
        print_stack_trace();
      }
    } else if (last_opcode == CALL) {
      uint8_t arg_size = frame_interpreter->prev_instr->arg;
      PyObject **sp =
          frame_interpreter->localsplus + frame_interpreter->stacktop;
      PyObject *callable = sp[-(arg_size + 1)];
      PyObject *method = sp[-(arg_size + 2)];
      PyObject **args_base = sp - arg_size;
      int total_args = arg_size;
      PyObject *is_method = Py_True;
      if (method != NULL) {
        callable = method;
        args_base--;
        total_args++;
      } else {
        is_method = Py_False;
      }
      Py_INCREF(is_method);
      Py_INCREF(callable);
      PyObject *args = PyTuple_New(total_args + 1);
      for (int i = 0; i < total_args; i++) {
        PyObject *arg = args_base[i];
        Py_INCREF(arg);
        PyTuple_SET_ITEM(args, i, arg);
      }
      PyTuple_SET_ITEM(args, total_args, is_method);
      PyObject *opcode_object = PyLong_FromSize_t(last_opcode);
      PyObject *ret =
          PyObject_CallMethod(trace_logic, "handle_opcode", "OOOO",
                              (PyObject *)frame, opcode_object, callable, args);
      Py_DECREF(callable);
      Py_DECREF(args);
      Py_DECREF(opcode_object);
      if (ret != NULL) {
        Py_DECREF(ret);
      } else {
        print_stack_trace();
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
        print_stack_trace();
      }
    }
    return 0;
  }

  int handle_return_event(PyFrameObject *frame, PyObject *arg) {
    std::lock_guard<std::mutex> lock(cache_mutex);
    if (active_frames.find(frame) != active_frames.end()) {
      if (arg == NULL) {
        arg = Py_None;
      }
      PyObject *ret = PyObject_CallMethod(trace_logic, "handle_return", "OO",
                                          (PyObject *)frame, arg);
      if (ret != NULL) {
        Py_DECREF(ret);
      } else {
        print_stack_trace();
      }
      active_frames.erase(frame);
    }
    return 0;
  }

  int handle_line_event(PyFrameObject *frame, PyObject *arg) {
    std::lock_guard<std::mutex> lock(cache_mutex);
    if (active_frames.find(frame) != active_frames.end()) {
      PyObject *ret = PyObject_CallMethod(trace_logic, "handle_line", "O",
                                          (PyObject *)frame);
      if (ret != NULL) {
        Py_DECREF(ret);
      } else {
        print_stack_trace();
      }
    }
    return 0;
  }

  int handle_exception_event(PyFrameObject *frame, PyObject *arg) {
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
        print_stack_trace();
      }
    }
    return 0;
  }

  void start() {
    PyEval_SetTrace(&trace_dispatch_thunk, reinterpret_cast<PyObject *>(this));
    PyObject *ret = PyObject_CallMethod(trace_logic, "start", nullptr);
    if (ret != NULL) {
      Py_DECREF(ret);
    } else {
      print_stack_trace();
    }
  }

  void stop() {
    PyEval_SetTrace(nullptr, nullptr);
    PyObject *ret = PyObject_CallMethod(trace_logic, "stop", nullptr);
    if (ret != NULL) {
      Py_DECREF(ret);
    } else {
      print_stack_trace();
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

static PyObject *TraceDispatcher_add_target_frame(PyObject *self,
                                                  PyObject *args) {
  TraceDispatcherObject *obj = (TraceDispatcherObject *)self;
  if (!obj->dispatcher) {
    PyErr_SetString(PyExc_RuntimeError, "Invalid dispatcher");
    return nullptr;
  }

  if (!PyFrame_Check(args)) {
    PyErr_SetString(PyExc_TypeError, "Argument must be a frame object");
    return nullptr;
  }

  PyFrameObject *frame = (PyFrameObject *)args;
  obj->dispatcher->add_target_frame(frame);
  Py_RETURN_NONE;
}

static PyMethodDef TraceDispatcher_methods[] = {
    {"start", (PyCFunction)TraceDispatcher_start, METH_NOARGS, "Start tracing"},
    {"stop", (PyCFunction)TraceDispatcher_stop, METH_NOARGS, "Stop tracing"},
    {"add_target_frame", (PyCFunction)TraceDispatcher_add_target_frame, METH_O,
     "Manually add a frame to trace"},
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

  self->dispatcher = new TraceDispatcher(target_path, trace_logic, config);
  return 0;
}

static PyTypeObject TraceDispatcherType = {
    PyVarObject_HEAD_INIT(nullptr,
                          0) "tracer_core.TraceDispatcher", /* tp_name */
    sizeof(TraceDispatcherObject),                          /* tp_basicsize */
    0,                                                      /* tp_itemsize */
    (destructor)TraceDispatcher_dealloc,                    /* tp_dealloc */
    0,                                        /* tp_vectorcall_offset */
    0,                                        /* tp_getattr */
    0,                                        /* tp_setattr */
    0,                                        /* tp_as_async */
    0,                                        /* tp_repr */
    0,                                        /* tp_as_number */
    0,                                        /* tp_as_sequence */
    0,                                        /* tp_as_mapping */
    0,                                        /* tp_hash */
    0,                                        /* tp_call */
    0,                                        /* tp_str */
    0,                                        /* tp_getattro */
    0,                                        /* tp_setattro */
    0,                                        /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
    "Trace dispatcher object",                /* tp_doc */
    0,                                        /* tp_traverse */
    0,                                        /* tp_clear */
    0,                                        /* tp_richcompare */
    0,                                        /* tp_weaklistoffset */
    0,                                        /* tp_iter */
    0,                                        /* tp_iternext */
    TraceDispatcher_methods,                  /* tp_methods */
    0,                                        /* tp_members */
    0,                                        /* tp_getset */
    0,                                        /* tp_base */
    0,                                        /* tp_dict */
    0,                                        /* tp_descr_get */
    0,                                        /* tp_descr_set */
    0,                                        /* tp_dictoffset */
    (initproc)TraceDispatcher_init,           /* tp_init */
    0,                                        /* tp_alloc */
    TraceDispatcher_new,                      /* tp_new */
};

static PyModuleDef tracer_core_module = {
    PyModuleDef_HEAD_INIT,       /* m_base */
    "tracer_core",               /* m_name */
    "Python tracer core module", /* m_doc */
    -1,                          /* m_size */
    NULL,                        /* m_methods */
    NULL,                        /* m_slots */
    NULL,                        /* m_traverse */
    NULL,                        /* m_clear */
    NULL                         /* m_free */
};

PyMODINIT_FUNC PyInit_tracer_core(void) {
  PyObject *module = PyModule_Create(&tracer_core_module);
  if (!module) {
    printf("Failed to create module\n");
    return nullptr;
  }
  if (PyType_Ready(&TraceDispatcherType) < 0) {
    printf("PyType_Ready failed\n");
    return nullptr;
  }

  Py_INCREF(&TraceDispatcherType);
  if (PyModule_AddObject(module, "TraceDispatcher",
                         (PyObject *)&TraceDispatcherType) < 0) {
    printf("Failed to add TraceDispatcher to module\n");
    Py_DECREF(&TraceDispatcherType);
    Py_DECREF(module);
    return nullptr;
  }

  return module;
}