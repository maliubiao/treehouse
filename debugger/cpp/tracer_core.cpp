/*
以较快的速度过滤掉不关心的代码文件，有用的再交给python层处理
*/
#include <Python.h>
#include <cpython/code.h>
#include <filesystem>
#include <mutex>
#include <object.h>
#include <pyframe.h>
#include <pytypedefs.h>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>

namespace fs = std::filesystem;

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
        return it->second;
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
    default:
      return 0;
    }
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
        PyErr_Clear();
      }
    }
    return 0;
  }

  int handle_return_event(PyFrameObject *frame, PyObject *arg) {
    {
      std::lock_guard<std::mutex> lock(cache_mutex);
      if (active_frames.find(frame) != active_frames.end()) {

        PyObject *ret = PyObject_CallMethod(trace_logic, "handle_return", "OO",
                                            (PyObject *)frame, arg);
        if (ret != NULL) {
          Py_DECREF(ret);
        } else {
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
        PyObject *ret =
            PyObject_CallMethod(trace_logic, "handle_exception", "OOO", type,
                                value, traceback);
        if (ret != NULL) {
          Py_DECREF(ret);
        } else {
          PyErr_Clear();
        }
      }
    }
    return 0;
  }

  void start() {
    PyEval_SetTraceAllThreads(&trace_dispatch_thunk,
                              reinterpret_cast<PyObject *>(this));
    PyObject *ret = PyObject_CallMethod(trace_logic, "start", nullptr);
    if (ret != NULL) {
      Py_DECREF(ret);
    }
  }

  void stop() {
    PyEval_SetTraceAllThreads(nullptr, nullptr);
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