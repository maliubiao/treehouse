import dis
import importlib.util
import inspect
import json
import os
import shutil
import site
import subprocess
import sys
import threading
import unittest
from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import yaml

# Add project's source directory to path to allow importing context_tracer modules
sys.path.insert(0, str(Path(__file__).parent.parent / "context-tracer" / "src"))
# Add project root to path to allow importing 'tests' package
sys.path.insert(0, str(Path(__file__).parent.parent))


from context_tracer.tracer import (
    CallTreeHtmlRender,
    SysMonitoringTraceDispatcher,
    TraceConfig,
    TraceDispatcher,
    TraceLogExtractor,
    TraceLogic,
    start_trace,
    stop_trace,
    truncate_repr_value,
)
from context_tracer.tracer_common import _MAX_VALUE_LENGTH, TraceTypes

from tests.boundary_test_helpers.helpers import non_target_helper, non_target_raiser

# A temporary directory for test artifacts
TEST_DIR = Path(__file__).parent / "test_artifacts"


# --- Helper Classes & Functions for Testing ---
class BuggyRepr:
    """A helper class with a __repr__ that raises an exception."""

    def __repr__(self):
        raise RuntimeError("This repr is buggy!")


# --- Test Target Code ---
# This code will be "traced" by our tests.
# We define it here to have access to its source and frame objects.


def sample_function(x, y):
    """A simple function to be traced."""
    a = x + y
    b = a * 2
    if b > 10:
        c = "large"
    else:
        c = "small"  # trace: c
    return b, c


def function_with_exception(x):
    """A function that raises an exception."""
    if x == 0:
        raise ValueError("x cannot be zero")
    return 10 / x


def _test_func_for_var_tracing_failure():
    a = 1
    c = a + b  # 'b' is not defined
    return c


def func_with_delayed_exception():
    my_list = [  # This line will set a pending message
        x for x in range(3)
    ]
    1 / 0  # This will trigger an exception
    return my_list


class SampleClass:
    def __init__(self, name):
        self.name = name

    def greet(self, message):
        return f"Hello {self.name}, {message}"


# New test target functions for exclusion logic
def excluded_helper_func_internal():
    """An internal helper function that should be excluded."""
    # This line should not be traced
    return 1 + 1


def excluded_main_func(arg):
    """A function that calls an excluded helper."""
    val = excluded_helper_func_internal()  # This line should also be ignored
    return arg + val


def excluded_raiser():
    """An excluded function that raises an exception."""
    raise RuntimeError("Excluded function error")


def main_func_calling_excluded(x, y):
    """A main function that calls an excluded function."""
    a = x * y
    b = excluded_main_func(a)  # This call to excluded_main_func should be ignored
    return b + 10


def main_func_calling_raiser():
    """A main function that calls an excluded function that raises."""
    try:
        excluded_raiser()
    except RuntimeError:
        return "Caught excluded error"
    return "No error"


def simple_target_func():
    """A simple function to be targeted."""
    return 1


# New test target functions for boundary call logic
def target_main_function(x, y):
    """This function IS a target for tracing."""
    val = x + y  # This line should be traced.
    res = non_target_helper(val, y)  # This should be a B-CALL.
    return res * 2  # This line should be traced.


def target_main_caller_of_raiser():
    """A target function that calls a raiser."""
    try:
        # This should be a B-CALL
        non_target_raiser()
    except ValueError as e:
        # This line should be traced
        return str(e)
    # This line should be traced
    return "No error"


# --- End of Test Target Code ---


class BaseTracerTest(unittest.TestCase):
    """
    Base class for tests that create artifacts.
    Manages creation and cleanup of a temporary directory for each test class.
    """

    _temp_dir_base = TEST_DIR
    _class_temp_dir = None

    @classmethod
    def setUpClass(cls):
        cls._class_temp_dir = cls._temp_dir_base / cls.__name__
        # Clean up any previous runs to ensure a clean slate
        if cls._class_temp_dir.exists():
            shutil.rmtree(cls._class_temp_dir)
        cls._class_temp_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls._class_temp_dir and cls._class_temp_dir.exists():
            shutil.rmtree(cls._class_temp_dir)

    def setUp(self):
        # Make the class-level temp dir available to instances
        self.test_dir = self.__class__._class_temp_dir
        # Ensure the `tracer-logs` directory exists for integration tests
        (Path.cwd() / "tracer-logs").mkdir(exist_ok=True)

    def _create_frame_from_code(self, code_string, filename="<string>", func_name="test_func", *args, **kwargs):
        """
        Executes code and captures a real frame from a specific function call.
        This is useful for creating frames with specific filenames or origins.
        """
        target_func = None
        # Use a temporary file in the test directory if filename is provided
        if filename != "<string>":
            # Ensure filename is relative to test directory
            temp_file = self.test_dir / filename
            # Ensure parent directory exists for nested paths
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file.write_text(code_string, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("temp_module", temp_file)
            temp_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(temp_module)
            target_func = getattr(temp_module, func_name)
        else:  # For <string> filenames, exec in a dictionary
            ns = {}
            exec(code_string, ns)  # nosec
            target_func = ns[func_name]

        frame = None

        def tracer(f, event, arg):
            nonlocal frame
            if event == "call" and f.f_code.co_name == func_name:
                frame = f
                sys.settrace(None)  # Stop tracing once we have the frame
            return tracer

        sys.settrace(tracer)
        try:
            result = target_func(*args, **kwargs)
            # Handle generator case
            if inspect.isgenerator(result):
                next(result, None)
        finally:
            sys.settrace(None)

        if frame is None:
            self.fail(f"Failed to create frame for function '{func_name}'")

        return frame

    def _create_specific_mock_frame(self, filename, lineno, func_name, lasti, opname_at_lasti):
        """
        Creates a highly specific mock frame for testing scenarios that are
        difficult to reproduce with real code, such as checking opcodes at f_lasti.
        This is kept because testing the logic for StopIteration from SEND/FOR_ITER
        is otherwise extremely brittle.
        """
        mock_code = MagicMock()
        mock_code.co_filename = filename
        mock_code.co_name = func_name
        mock_frame = MagicMock()
        mock_frame.f_code = mock_code
        mock_frame.f_lineno = lineno
        mock_frame.f_lasti = lasti
        mock_frame.f_locals = {}
        mock_frame.f_globals = {}
        mock_frame.f_back = None
        mock_frame.f_trace_lines = True

        # Mock dis.get_instructions to return the specific opcode we need
        instr = MagicMock()
        instr.offset = lasti
        instr.opname = opname_at_lasti
        # Patch dis.get_instructions for the duration of the test using this frame.
        # This is a bit of a hack, but it's contained.
        patcher = patch("dis.get_instructions", return_value=[instr])
        self.addCleanup(patcher.stop)
        patcher.start()

        return mock_frame


class TestTruncateReprValue(unittest.TestCase):
    """Tests for the truncate_repr_value utility function."""

    def test_truncate_long_string(self):
        long_str = "a" * (_MAX_VALUE_LENGTH + 100)
        result = truncate_repr_value(long_str)
        half = _MAX_VALUE_LENGTH // 2
        omitted = len(long_str) - 2 * half
        suffix = f" (total length: {len(long_str)}, omitted: {omitted})"
        self.assertTrue(result.endswith(suffix))

    def test_truncate_list(self):
        long_list = list(range(100))
        result = truncate_repr_value(long_list)
        self.assertIn("...", result)
        self.assertLess(len(result), len(str(long_list)))

    def test_truncate_dict(self):
        long_dict = {str(i): i for i in range(100)}
        result = truncate_repr_value(long_dict)
        self.assertIn("...", result)
        self.assertLess(len(result), len(str(long_dict)))

    def test_truncate_custom_object(self):
        class TestObj:
            def __init__(self):
                self.a = 1
                self.b = 2
                self.c = 3
                self.d = 4
                self.e = 5
                self.f = 6

        obj = TestObj()
        result = truncate_repr_value(obj)
        self.assertIn("TestObj(a=1, b=2, c=3, d=4, e=5, f=6)", result)

    def test_unsafe_mode_with_buggy_repr(self):
        obj = BuggyRepr()
        result = truncate_repr_value(obj, safe=False)
        self.assertIn("[trace system error: This repr is buggy!]", result)

    def test_safe_mode_with_buggy_repr(self):
        obj = BuggyRepr()
        result = truncate_repr_value(obj, safe=True)
        self.assertEqual(result, "<BuggyRepr object>")

    def test_safe_mode_with_containers(self):
        my_list = [1, 2, BuggyRepr()]
        my_dict = {"a": 1, "b": BuggyRepr()}
        self.assertEqual(truncate_repr_value(my_list, safe=True), "[1, 2, <BuggyRepr object>]")
        self.assertEqual(truncate_repr_value(my_dict, safe=True), "{'a': 1, 'b': <BuggyRepr object>}")

    def test_safe_mode_with_primitives(self):
        self.assertEqual(truncate_repr_value("hello", safe=True), "'hello'")
        self.assertEqual(truncate_repr_value(123, safe=True), "123")


class TestTraceConfig(BaseTracerTest):
    """Tests for the TraceConfig class."""

    def test_initialization_defaults(self):
        config = TraceConfig()

        self.assertTrue(config.ignore_self)
        self.assertTrue(config.ignore_system_paths)
        self.assertFalse(config.enable_var_trace)
        self.assertEqual(config.report_name, "trace_report.html")
        self.assertEqual(config.target_files, [])
        self.assertEqual(config.line_ranges, defaultdict(set))
        self.assertEqual(config.skip_vars_on_lines, [])
        self.assertEqual(config.capture_vars, [])
        self.assertEqual(config.exclude_functions, [])
        self.assertIsNone(config.callback)
        self.assertIsNone(config.start_function)
        self.assertIsNone(config.source_base_dir)
        self.assertFalse(config.disable_html)
        self.assertEqual(config.include_stdlibs, [])
        # New assertion for trace_c_calls
        self.assertFalse(config.trace_c_calls)

        test_site_packages_file = None
        try:
            site_packages_dirs = site.getsitepackages()
            for sp_dir in site_packages_dirs:
                current_path = Path(sp_dir)
                if current_path.is_dir() and (
                    any(f.suffix == ".pth" for f in current_path.iterdir())
                    or any(f.suffix == ".egg-info" for f in current_path.iterdir())
                    or any(f.is_dir() and "dist-info" in f.name for f in current_path.iterdir())
                ):
                    test_site_packages_file = current_path / "some_test_lib.py"
                    break
        except Exception:
            pass

        if not test_site_packages_file:
            for p in sys.path:
                resolved_p = Path(p).resolve()
                if any(part in ("site-packages", "dist-packages") for part in resolved_p.parts) or (
                    "lib" in resolved_p.parts and any("python" in part.lower() for part in resolved_p.parts)
                ):
                    test_site_packages_file = resolved_p / "some_test_lib.py"
                    break

        if not test_site_packages_file:
            test_site_packages_file = Path("/my_virtual_env/lib/python3.9/site-packages/test_module.py")

        self.assertFalse(config.match_filename(str(test_site_packages_file)))

    def test_initialization_with_params(self):
        config = TraceConfig(
            target_files=["*.py"], enable_var_trace=True, ignore_system_paths=False, trace_c_calls=True
        )
        self.assertEqual(config.target_files, ["*.py"])
        self.assertFalse(config.ignore_system_paths)
        self.assertTrue(config.enable_var_trace)
        self.assertTrue(config.trace_c_calls)  # New assertion

    def test_from_yaml(self):
        config_file = self.test_dir / "test_config.yml"
        test_py_path = self.test_dir / "test.py"  # Create a dummy file to get its resolved path
        test_py_path.touch()  # Create the file
        resolved_test_py_path = str(test_py_path.resolve())

        sample_config = {
            "target_files": ["*.py", "test_*.py"],
            "line_ranges": {resolved_test_py_path: [(1, 10), (20, 30)]},  # Use resolved path here
            "skip_vars_on_lines": [{"pattern": f"*{test_py_path.name}", "start": 5, "end": 8}],
            "capture_vars": ["x", "y.z"],
            "exclude_functions": ["some_excluded_func"],
            "ignore_system_paths": False,
            "source_base_dir": str(self.test_dir),
            "disable_html": True,
            "include_stdlibs": ["os"],
            "trace_c_calls": True,  # New config
        }
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(sample_config, f)

        config = TraceConfig.from_yaml(config_file)
        self.assertEqual(config.target_files, sample_config["target_files"])
        self.assertEqual(len(config.line_ranges), 1)
        self.assertIn(resolved_test_py_path, config.line_ranges)
        self.assertEqual(
            config.line_ranges[resolved_test_py_path], {i for i in range(1, 11)} | {i for i in range(20, 31)}
        )
        self.assertEqual(config.skip_vars_on_lines, sample_config["skip_vars_on_lines"])
        self.assertEqual(config.capture_vars, sample_config["capture_vars"])
        self.assertEqual(config.exclude_functions, sample_config["exclude_functions"])
        self.assertFalse(config.ignore_system_paths)
        self.assertEqual(config.source_base_dir, Path(sample_config["source_base_dir"]))  # Ensure Path object
        self.assertTrue(config.disable_html)
        self.assertEqual(config.include_stdlibs, sample_config["include_stdlibs"])
        self.assertTrue(config.trace_c_calls)  # New assertion
        test_py_path.unlink()  # Clean up dummy file

    def test_match_filename(self):
        config = TraceConfig(target_files=["*/test_*.py", "*/context_tracer/*"])
        current_file = Path(__file__).resolve().as_posix()
        self.assertTrue(config.match_filename(current_file))
        self.assertTrue(config.match_filename("/fake/path/to/context_tracer/tracer.py"))
        self.assertFalse(config.match_filename("/app/main.py"))

    def test_ignore_system_paths(self):
        config = TraceConfig(ignore_system_paths=True)
        site_packages_file = "/usr/lib/python3.9/site-packages/some_lib.py"
        self.assertFalse(config.match_filename(site_packages_file))

    def test_is_excluded_function(self):
        config = TraceConfig(exclude_functions=["secret_function", "internal_helper"])
        self.assertTrue(config.is_excluded_function("secret_function"))
        self.assertFalse(config.is_excluded_function("public_api"))

    def test_parse_line_ranges(self):
        filename = str(Path("dummy_file.py").resolve())
        line_ranges_input = {filename: [(1, 3), (5, 7)]}
        parsed = TraceConfig._parse_line_ranges(line_ranges_input)
        self.assertEqual(len(parsed), 1)
        self.assertIn(filename, parsed)
        self.assertEqual(parsed[filename], {1, 2, 3, 5, 6, 7})

        # Test invalid range
        invalid_line_ranges = {filename: [(10, 5)]}
        with self.assertRaisesRegex(ValueError, "起始行号.*大于结束行号"):
            TraceConfig._parse_line_ranges(invalid_line_ranges)

        # Test invalid format
        invalid_format_line_ranges = {filename: [1, (5, 7)]}
        with self.assertRaisesRegex(ValueError, "行号格式错误"):
            TraceConfig._parse_line_ranges(invalid_format_line_ranges)

    def test_validate_expressions(self):
        valid_exprs = ["x", "x.y", "x[0]"]
        invalid_exprs = ["x.", "1 + ", "x = y"]

        config = TraceConfig(capture_vars=valid_exprs)
        self.assertTrue(config.validate())

        t = TraceConfig(capture_vars=invalid_exprs)
        self.assertFalse(t.validate())

    def test_match_filename_with_include_stdlibs(self):
        config = TraceConfig(ignore_system_paths=True, include_stdlibs=["os", "sys"])

        # Test a real system path file (e.g., from Python stdlib)
        # Find an actual os module file
        os_path = Path(os.__file__)
        if os_path.name.endswith(".pyc"):
            os_path = os_path.with_suffix(".py")
        self.assertTrue(os_path.exists())

        # Should be included even if it's a system path because it's in include_stdlibs
        self.assertTrue(config.match_filename(str(os_path)))

        # Test another standard lib not explicitly included
        # Find a random stdlib module not in the list, e.g., 'collections'
        collections_path = Path(importlib.util.find_spec("collections").origin)
        if collections_path.name.endswith(".pyc"):
            collections_path = collections_path.with_suffix(".py")
        self.assertTrue(collections_path.exists())

        # Should be ignored because it's a system path and not in include_stdlibs
        self.assertFalse(config.match_filename(str(collections_path)))

        # Test a non-stdlib file
        test_file_path = self.test_dir / "my_app.py"
        test_file_path.touch()
        self.assertTrue(config.match_filename(str(test_file_path)))
        test_file_path.unlink()

        # Test with ignore_system_paths=False, include_stdlibs should have no effect
        config_no_ignore = TraceConfig(ignore_system_paths=False, include_stdlibs=["os"])
        self.assertTrue(config_no_ignore.match_filename(str(os_path)))
        self.assertTrue(config_no_ignore.match_filename(str(collections_path)))

    def test_should_skip_vars(self):
        test_file_path = self.test_dir / "my_app_for_skip_test.py"
        test_file_path.touch()
        resolved_path = str(test_file_path.resolve())

        config = TraceConfig(
            skip_vars_on_lines=[
                {"pattern": f"*{test_file_path.name}", "start": 5, "end": 10},
                {"pattern": "lib/*.py", "start": 1, "end": 100},
            ]
        )

        # Test matching rule
        self.assertTrue(config.should_skip_vars(resolved_path, 7))
        self.assertTrue(config.should_skip_vars(resolved_path, 5))
        self.assertTrue(config.should_skip_vars(resolved_path, 10))

        # Test outside range
        self.assertFalse(config.should_skip_vars(resolved_path, 4))
        self.assertFalse(config.should_skip_vars(resolved_path, 11))

        # Test non-matching file
        other_file_path = self.test_dir / "other_app.py"
        other_file_path.touch()
        self.assertFalse(config.should_skip_vars(str(other_file_path.resolve()), 7))

        # Test caching (simple check: it should return the same result)
        self.assertTrue(config.should_skip_vars(resolved_path, 7))
        self.assertIn(f"{resolved_path}:7", config._skip_vars_cache)

        test_file_path.unlink()
        other_file_path.unlink()


class TestTraceLogic(BaseTracerTest):
    """Tests for the core TraceLogic."""

    class _StopTracing(Exception):
        """Custom exception to stop tracing immediately after capturing a frame."""

        pass

    def setUp(self):
        super().setUp()
        self.test_filename = str(Path(__file__).resolve())
        self.config = TraceConfig(target_files=[self.test_filename])
        self.logic = TraceLogic(self.config)
        # Mock the internal _add_to_buffer for easier assertion
        self.logic._add_to_buffer = MagicMock()
        # Initialize thread-local attributes for every test
        self.logic.init_stack_variables()

    def _get_frame_at(self, func, *args, event_type="call", lineno=None, **kwargs):
        """
        Helper to get a real frame from a function call at a specific event/line.
        It works by raising a custom exception from the tracer to halt execution
        immediately, thus preserving the exact state of the frame at that moment.
        """
        frame = None

        def tracer(f, event, arg):
            nonlocal frame
            # Only capture frames from the target function's code object
            if not hasattr(func, "__code__") or f.f_code is not func.__code__:
                return tracer

            if event == event_type:
                if lineno is None or f.f_lineno == lineno:
                    frame = f
                    # Raise an exception to stop execution immediately, preserving the frame's state.
                    raise self._StopTracing
            return tracer

        sys.settrace(tracer)
        try:
            func(*args, **kwargs)
        except self._StopTracing:
            # We expect this exception, so we catch and ignore it.
            pass
        finally:
            sys.settrace(None)

        if frame is None:
            self.fail(f"Failed to capture frame for {func.__name__} at event '{event_type}', line {lineno}")
        return frame

    def _get_python_frame_for_c_call(self, python_func_calling_c):
        """
        Executes a Python function that calls a C function and captures the Python frame
        at the point of the C call (or the line where it's initiated).
        """
        frame = None

        def trace_hook(f, event, arg):
            nonlocal frame
            # We are interested in the 'line' event right before or during the C call.
            if (
                hasattr(python_func_calling_c, "__code__")
                and f.f_code is python_func_calling_c.__code__
                and event == "line"
            ):
                frame = f
                raise self._StopTracing  # Stop immediately after getting the frame
            return trace_hook

        # Temporarily enable sys.settrace to capture the frame
        sys.settrace(trace_hook)
        try:
            python_func_calling_c()
        except self._StopTracing:
            pass
        finally:
            sys.settrace(None)

        if frame is None:
            self.fail(f"Failed to capture Python frame for C call in {python_func_calling_c.__name__}")
        return frame

    def _get_frames_for_test(self, func, *args, **kwargs):
        """
        Runs a function under a tracer and captures the frames for specific functions in the call stack.
        Returns a dictionary of {func_name: frame_object}.
        This is used to obtain real, correctly-structured frame objects for unit testing.
        """
        captured_frames = {}

        def tracer(frame, event, arg):
            func_name = frame.f_code.co_name
            # Capture the first time we see a frame for a function.
            # The frame object is reused for the lifetime of the call.
            if func_name not in captured_frames:
                captured_frames[frame.f_code.co_name] = frame
            return tracer

        sys.settrace(tracer)
        try:
            func(*args, **kwargs)
        except Exception:
            # We need to capture frames even if an exception occurs during the run.
            pass
        finally:
            sys.settrace(None)

        return captured_frames

    def test_handle_call(self):
        frame = self._get_frame_at(sample_function, 5, 3, event_type="call")

        self.logic.handle_call(frame)

        self.logic._add_to_buffer.assert_called_once()
        call_args = self.logic._add_to_buffer.call_args[0]
        log_data = call_args[0]

        # Assert against specific data fields and formatted message
        self.assertEqual(log_data["data"]["prefix"], TraceTypes.PREFIX_CALL)
        self.assertEqual(log_data["data"]["func"], "sample_function")
        self.assertEqual(log_data["data"]["args"], "x=5, y=3")
        self.assertEqual(log_data["data"]["lineno"], frame.f_lineno)
        # Use log_data's filename and lineno for robustness
        expected_filename = log_data["data"]["filename"]
        expected_lineno = log_data["data"]["lineno"]
        self.assertIn(
            f"↘ CALL {expected_filename}:{expected_lineno} sample_function(x=5, y=3)",
            self.logic._format_log_message(log_data),
        )
        self.assertEqual(self.logic._local.stack_depth, 1)

    def test_safe_variable_capture_with_skip_rule(self):
        # 1. Define a function that uses the buggy object
        def func_with_buggy_arg(arg1):
            x = 1  # We need at least one line to trace
            return arg1

        # 2. Configure the tracer to skip vars in this test file
        test_file_path = Path(__file__).resolve()
        lines, start_line = inspect.getsourcelines(func_with_buggy_arg)
        end_line = start_line + len(lines)

        config = TraceConfig(
            target_files=[f"*{test_file_path.name}"],
            skip_vars_on_lines=[{"pattern": f"*{test_file_path.name}", "start": start_line, "end": end_line}],
        )
        logic = TraceLogic(config)
        logic._add_to_buffer = MagicMock()  # Mock the buffer
        logic.init_stack_variables()

        # 3. Get a real frame from the function
        buggy_instance = BuggyRepr()
        frame = self._get_frame_at(func_with_buggy_arg, buggy_instance, event_type="call")

        # 4. Simulate the handle_call event
        logic.handle_call(frame)

        # 5. Assert that the call was logged with a safe representation
        logic._add_to_buffer.assert_called_once()
        log_data = logic._add_to_buffer.call_args[0][0]
        self.assertEqual("arg1=<BuggyRepr object>", log_data["data"]["args"])

        # 6. Test return value
        logic._local.stack_depth = 1  # Simulate being inside the call
        logic.handle_return(frame, buggy_instance)

        return_log_data = logic._add_to_buffer.call_args[0][0]
        self.assertEqual("<BuggyRepr object>", return_log_data["data"]["return_value"])

    def test_handle_return(self):
        frame = self._get_frame_at(sample_function, 5, 3, event_type="return")
        # Simulate being inside a call by setting stack depth
        self.logic._local.stack_depth = 1
        return_value = (16, "large")
        self.logic.handle_return(frame, return_value)

        self.logic._add_to_buffer.assert_called_once()
        call_args = self.logic._add_to_buffer.call_args[0]
        log_data = call_args[0]

        self.assertEqual(log_data["data"]["func"], "sample_function")
        self.assertEqual(log_data["data"]["lineno"], frame.f_lineno)
        # Use log_data's filename and return_value for robustness
        expected_filename = log_data["data"]["filename"]
        expected_frame_id = log_data["data"]["frame_id"]
        self.assertIn(
            f"↗ RETURN {expected_filename} sample_function() → (16, 'large') [frame:{expected_frame_id}]",
            self.logic._format_log_message(log_data),
        )
        self.assertEqual(self.logic._local.stack_depth, 0)

    def test_handle_line_with_trace_comment(self):
        lines, start_line = inspect.getsourcelines(sample_function)
        trace_comment_line_offset = next(i for i, line in enumerate(lines) if "# trace: c" in line)
        comment_lineno = start_line + trace_comment_line_offset

        # The 'line' event for a line happens *before* it's executed. So to check the
        # value of 'c' after the assignment, we must capture the frame on the *next*
        # executable line.
        frame_capture_lineno = comment_lineno + 1
        frame = self._get_frame_at(sample_function, 1, 2, event_type="line", lineno=frame_capture_lineno)

        # The frame now has the correct state (f_locals contains 'c'), but its line
        # number (f_lineno) points to the next line. To test the logic for processing
        # the comment, we must simulate a call to handle_line with a frame that has the
        # correct state but reports the original line number. We use a proxy object for this.
        frame_proxy = SimpleNamespace(
            f_code=frame.f_code,
            f_locals=frame.f_locals,
            f_globals=frame.f_globals,
            f_lineno=comment_lineno,
            f_lasti=frame.f_lasti,
        )

        self.logic.handle_line(frame_proxy)

        # Expect two calls: one for the line log, the second is for the trace comment.
        self.assertEqual(self.logic._add_to_buffer.call_count, 2)
        last_call_args = self.logic._add_to_buffer.call_args_list[1][0]
        log_data = last_call_args[0]
        self.assertIn("↳ Debug Statement c='small'", self.logic._format_log_message(log_data))
        self.assertEqual(frame.f_locals.get("c"), "small")

    def test_handle_exception(self):
        try:
            function_with_exception(0)
        except ValueError:
            _, exc_value, tb = sys.exc_info()
            frame = tb.tb_frame

        # Manually set stack depth to simulate being inside a call
        self.logic._local.stack_depth = 1
        self.logic.handle_exception(ValueError, exc_value, frame)

        if sys.version_info >= (3, 12):
            self.assertEqual(len(self.logic.exception_chain), 1)
            # In 3.12+, exceptions are buffered and flushed later, not directly added to buffer by handle_exception
            self.logic._add_to_buffer.assert_not_called()
            log_data, _ = self.logic.exception_chain[0]
        else:
            self.logic._add_to_buffer.assert_called_once()
            self.assertEqual(len(self.logic.exception_chain), 0)
            log_data, _ = self.logic._add_to_buffer.call_args[0]

        self.assertIn("⚠ EXCEPTION", self.logic._format_log_message(log_data))
        self.assertIn("ValueError: x cannot be zero", self.logic._format_log_message(log_data))
        # Assert that stack depth is NOT decremented by handle_exception
        self.assertEqual(self.logic._local.stack_depth, 1)

    def test_capture_variables(self):
        self.config.capture_vars = ["a", "b > 10"]

        lines, start_line = inspect.getsourcelines(sample_function)
        target_line_offset = next(i for i, line in enumerate(lines) if "b = a * 2" in line) + 1
        target_lineno = start_line + target_line_offset

        # Get frame right after 'a' and 'b' are defined
        frame = self._get_frame_at(sample_function, 5, 3, event_type="line", lineno=target_lineno)

        captured = self.logic.capture_variables(frame)
        self.assertEqual(captured, {"a": "8", "b > 10": "True"})
        self.assertEqual(frame.f_locals.get("a"), 8)
        self.assertEqual(frame.f_locals.get("b"), 16)

    def test_output_handlers(self):
        test_msg = {
            "template": "test {value}",
            "data": {
                "value": 42,
                "original_filename": "dummy_file.py",
                "lineno": 100,
                "frame_id": 1,
            },
        }

        with patch("builtins.print") as mock_print:
            self.logic._console_output(test_msg, "call")
            mock_print.assert_called_once()

        log_file = self.test_dir / "handler_test.log"
        self.logic.enable_output("file", filename=str(log_file))
        self.logic._file_output(test_msg, TraceTypes.CALL)
        self.logic.disable_output("file")
        with open(log_file, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("test 42", content)

    def test_unwanted_frame_state_management(self):
        """
        Tests that TraceLogic correctly manages its internal 'unwanted frame' state
        (`_local.bad_frame`) when functions are marked for exclusion, using REAL frames.
        This test does NOT verify if events are actually logged, as that's the Dispatcher's
        responsibility. It tests the internal state machine of TraceLogic.
        """
        self.config.exclude_functions = ["excluded_main_func"]

        # Capture real frames from an actual execution trace
        frames = self._get_frames_for_test(main_func_calling_excluded, 5, 6)
        frame_main = frames["main_func_calling_excluded"]
        frame_excluded = frames["excluded_main_func"]
        frame_nested_excluded = frames["excluded_helper_func_internal"]

        # 1. Simulate call to main_func_calling_excluded (not excluded itself)
        self.logic.handle_call(frame_main)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_main))
        self.logic._add_to_buffer.assert_called_once()  # Main func should be logged
        self.logic._add_to_buffer.reset_mock()

        # 2. Simulate call to excluded_main_func from main_func_calling_excluded
        self.logic.maybe_unwanted_frame(frame_excluded)

        # Verify that excluded_main_func's frame is now considered unwanted
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded))
        self.assertEqual(self.logic._local.bad_frame, self.logic.get_or_reuse_frame_id(frame_excluded))

        # 3. Simulate line event within excluded_main_func.
        # This tests that handle_line itself doesn't filter, which is correct.
        self.logic.handle_line(frame_excluded)
        self.logic._add_to_buffer.assert_called_once()
        self.logic._add_to_buffer.reset_mock()

        # 4. Simulate call to excluded_helper_func_internal from excluded_main_func
        self.logic.maybe_unwanted_frame(frame_nested_excluded)
        self.assertTrue(self.logic.inside_unwanted_frame(frame_nested_excluded))  # Still inside
        # bad_frame should NOT be updated, it should stick to the first unwanted frame
        self.assertEqual(self.logic._local.bad_frame, self.logic.get_or_reuse_frame_id(frame_excluded))

        # 5. Simulate line event within the nested (but not explicitly excluded) function
        self.logic.handle_line(frame_nested_excluded)
        self.logic._add_to_buffer.assert_called_once()
        self.logic._add_to_buffer.reset_mock()

        # 6. Simulate return from the nested function
        self.logic.handle_return(frame_nested_excluded, 2)  # Return value is not critical here
        self.logic._add_to_buffer.assert_called_once()
        self.logic._add_to_buffer.reset_mock()
        # State should still be unwanted, as we are returning to an unwanted frame
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded))

        # 7. Simulate return from the original excluded function
        self.logic.handle_return(frame_excluded, 32)  # Return value is not critical
        self.logic._add_to_buffer.assert_called_once()
        self.logic._add_to_buffer.reset_mock()

        # Manually call leave_unwanted_frame, as the dispatcher would
        self.logic.leave_unwanted_frame(frame_excluded)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_main))  # Should be cleared

        # 8. Simulate a subsequent line event in the main function
        self.logic.handle_line(frame_main)
        self.logic._add_to_buffer.assert_called_once()

    def test_unwanted_frame_exception_state_management(self):
        """
        Tests that TraceLogic correctly manages its 'unwanted frame' state
        during exceptions within excluded functions, using REAL frames.
        """
        self.config.exclude_functions = ["excluded_raiser"]

        # Capture real frames from an actual execution that raises an exception
        frames = self._get_frames_for_test(main_func_calling_raiser)
        frame_main = frames["main_func_calling_raiser"]
        frame_raiser = frames["excluded_raiser"]

        # 1. Simulate call to main_func_calling_raiser (not excluded)
        self.logic.handle_call(frame_main)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_main))
        self.logic._add_to_buffer.assert_called_once()
        self.logic._add_to_buffer.reset_mock()

        # 2. Simulate call to excluded_raiser from main_func_calling_raiser
        self.logic.maybe_unwanted_frame(frame_raiser)
        self.assertTrue(self.logic.inside_unwanted_frame(frame_raiser))
        self.assertEqual(self.logic._local.bad_frame, self.logic.get_or_reuse_frame_id(frame_raiser))

        # 3. Simulate exception within excluded_raiser
        mock_exc_type = RuntimeError
        mock_exc_value = RuntimeError("Excluded function error")
        self.logic.handle_exception(mock_exc_type, mock_exc_value, frame_raiser)

        if sys.version_info >= (3, 12):
            self.assertEqual(len(self.logic.exception_chain), 1)
        else:
            self.logic._add_to_buffer.assert_called_once()
            self.logic._add_to_buffer.reset_mock()

        # 4. Simulate stack unwinding for the raiser frame
        self.logic.decrement_stack_depth()
        self.logic.leave_unwanted_frame(frame_raiser)  # This clears bad_frame
        self.logic.frame_cleanup(frame_raiser)

        self.assertFalse(self.logic.inside_unwanted_frame(frame_main))  # Back in main

        # 5. Simulate line event back in main_func_calling_raiser (in the except block)
        self.logic.handle_line(frame_main)
        self.logic._add_to_buffer.assert_called_once()
        self.logic._add_to_buffer.reset_mock()

    def test_exclude_none_effect_on_call(self):
        """Tests that maybe_unwanted_frame has no effect if function is not excluded."""
        self.config.exclude_functions = []

        frames = self._get_frames_for_test(simple_target_func)
        frame_target = frames["simple_target_func"]

        self.logic.maybe_unwanted_frame(frame_target)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_target))
        self.assertIsNone(self.logic._local.bad_frame)

    def test_no_effect_if_already_unwanted(self):
        """Tests that maybe_unwanted_frame doesn't mark a new frame if already in unwanted state."""
        self.config.exclude_functions = ["excluded_main_func", "excluded_helper_func_internal"]

        frames = self._get_frames_for_test(main_func_calling_excluded, 1, 2)
        frame_excluded_main = frames["excluded_main_func"]
        frame_excluded_helper = frames["excluded_helper_func_internal"]

        # Enter the first unwanted frame
        self.logic.maybe_unwanted_frame(frame_excluded_main)
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded_main))
        first_unwanted_id = self.logic._local.bad_frame

        # Enter a nested function that is also excludable
        self.logic.maybe_unwanted_frame(frame_excluded_helper)
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded_helper))
        # The bad_frame ID should NOT change
        self.assertEqual(self.logic._local.bad_frame, first_unwanted_id)

        # Leaving the nested frame should not clear the state
        self.logic.leave_unwanted_frame(frame_excluded_helper)
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded_main))
        self.assertEqual(self.logic._local.bad_frame, first_unwanted_id)

        # Leaving the original unwanted frame should clear the state
        self.logic.leave_unwanted_frame(frame_excluded_main)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_excluded_main))
        self.assertIsNone(self.logic._local.bad_frame)

    def test_stop_iteration_not_logged_on_send(self):
        """Test that StopIteration raised by SEND is not logged as an exception."""
        # This test uses a mock frame because reproducing the exact internal state
        # (f_lasti pointing to a SEND opcode) with real code is highly complex and
        # brittle, as it depends on Python's bytecode compilation specifics.
        frame = self._create_specific_mock_frame(self.test_filename, 10, "gen_func", lasti=42, opname_at_lasti="SEND")
        self.logic.handle_exception(StopIteration, StopIteration(), frame)
        self.assertEqual(len(self.logic.exception_chain), 0)
        self.logic._add_to_buffer.assert_not_called()

    def test_stop_async_iteration_not_logged_on_end_async_for(self):
        """Test that StopAsyncIteration raised by END_ASYNC_FOR is not logged."""
        frame = self._create_specific_mock_frame(
            self.test_filename, 15, "async_gen_func", lasti=88, opname_at_lasti="END_ASYNC_FOR"
        )
        self.logic.handle_exception(StopAsyncIteration, StopAsyncIteration(), frame)
        self.assertEqual(len(self.logic.exception_chain), 0)
        self.logic._add_to_buffer.assert_not_called()

    def test_try_finally_reraise_exception_chain(self):
        """Test that exceptions in try/finally blocks are properly tracked using a real frame."""

        def func_with_finally():
            try:
                raise ValueError("test error")
            finally:
                pass  # Exception is not handled, just re-raised.

        frame = None
        exc_value = None
        try:
            func_with_finally()
        except ValueError as e:
            exc_value = e
            _, _, tb = sys.exc_info()
            frame = tb.tb_frame

        self.assertIsNotNone(frame)
        self.logic.handle_exception(ValueError, exc_value, frame)

        if sys.version_info >= (3, 12):
            self.assertEqual(len(self.logic.exception_chain), 1)
            logged = self.logic.exception_chain[0]
            self.assertEqual(logged[0]["data"]["exc_type"], "ValueError")
        else:
            self.assertEqual(self.logic._add_to_buffer.call_count, 1)
            logged = self.logic._add_to_buffer.call_args[0]
            self.assertEqual(logged[0]["data"]["exc_type"], "ValueError")

    def test_handle_c_call(self):
        """Test handling of C-function call events using a real Python frame."""

        def _dummy_caller():
            lst = [1, 2, 3]  # This line number will be captured in the frame
            _ = len(lst)  # C call happens on this line

        # Get a real Python frame from a function that calls a C function
        python_caller_frame = self._get_python_frame_for_c_call(_dummy_caller)

        # The C callable object itself (real built-in function)
        c_callable_obj = len
        # For len(lst), arg0 in sys.monitoring.events.CALL is 'lst'
        arg0_value = [1, 2, 3]

        self.logic._local.stack_depth = 0  # Start at base depth

        # Simulate the call to handle_c_call with the real Python frame and C callable
        self.logic.handle_c_call(python_caller_frame, c_callable_obj, arg0_value)

        self.logic._add_to_buffer.assert_called_once()
        log_data = self.logic._add_to_buffer.call_args[0][0]
        color_type = self.logic._add_to_buffer.call_args[0][1]

        # Assertions
        self.assertEqual(log_data["data"]["func_name"], "len")
        self.assertEqual(
            log_data["data"]["filename"], self.logic._get_formatted_filename(python_caller_frame.f_code.co_filename)
        )
        self.assertEqual(log_data["data"]["lineno"], python_caller_frame.f_lineno)
        self.assertEqual(color_type, TraceTypes.COLOR_TRACE)
        self.assertEqual(self.logic._local.stack_depth, 1)  # Stack depth increases
        self.assertIn("C-CALL len([1, 2, 3]) at", self.logic._format_log_message(log_data))

    def test_handle_c_return(self):
        """Test handling of C-function return events using a real Python frame."""

        def _dummy_caller():
            _ = sum([1, 2, 3])  # This line number will be captured in the frame

        python_caller_frame = self._get_python_frame_for_c_call(_dummy_caller)
        c_callable_obj = sum
        mock_retval = 6

        self.logic._local.stack_depth = 1  # Simulate being inside C call

        self.logic.handle_c_return(python_caller_frame, c_callable_obj, mock_retval)

        self.logic._add_to_buffer.assert_called_once()
        log_data = self.logic._add_to_buffer.call_args[0][0]
        color_type = self.logic._add_to_buffer.call_args[0][1]

        self.assertEqual(log_data["data"]["func_name"], "sum")
        self.assertEqual(color_type, TraceTypes.COLOR_TRACE)
        self.assertEqual(self.logic._local.stack_depth, 0)  # Stack depth decreases
        self.assertIn(f"C-RETURN from sum", self.logic._format_log_message(log_data))

    def test_handle_c_raise(self):
        """Test handling of C-function raise events using a real Python frame."""

        def _dummy_caller():
            try:
                # This line number will be captured in the frame
                with open("non_existent_file.txt", "r") as f:
                    _ = f.read()
            except FileNotFoundError:
                pass

        python_caller_frame = self._get_python_frame_for_c_call(_dummy_caller)
        c_callable_obj = open  # The C function that would raise
        mock_exception = FileNotFoundError("file not found")

        self.logic._local.stack_depth = 1  # Simulate being inside C call

        self.logic.handle_c_raise(python_caller_frame, c_callable_obj, mock_exception)

        self.logic._add_to_buffer.assert_called_once()
        log_data = self.logic._add_to_buffer.call_args[0][0]
        color_type = self.logic._add_to_buffer.call_args[0][1]

        self.assertEqual(log_data["data"]["func_name"], "open")
        self.assertEqual(color_type, TraceTypes.COLOR_EXCEPTION)
        self.assertEqual(self.logic._local.stack_depth, 0)  # Stack depth decreases
        self.assertIn("⚠ C-RAISE from open", self.logic._format_log_message(log_data))

    def test_multiline_statement_variable_tracking(self):
        """Tests that variables from a multi-line statement are logged after it completes."""
        self.config.enable_var_trace = True
        self.logic = TraceLogic(self.config)
        self.logic._add_to_buffer = MagicMock()

        def multiline_func():
            # This multi-line statement should result in one delayed log message
            result = [i for i in range(3)]
            # This next line should trigger the flush of the previous message
            return result

        # To test the delayed message logic, we get the frame at the end of the
        # function, which has the final state of local variables.
        return_frame = self._get_frame_at(multiline_func, event_type="return")

        # Determine the actual start line of the multi-line statement.
        lines, func_start_line = inspect.getsourcelines(multiline_func)
        multiline_start_offset = next(i for i, line in enumerate(lines) if "result = [" in line)
        statement_start_lineno = func_start_line + multiline_start_offset

        # Create a proxy frame that reports being at the start of the statement
        # but has the FINAL local variables. This simulates the state of a real
        # frame object at the point of flushing.
        frame_proxy = SimpleNamespace(
            f_code=return_frame.f_code,
            f_locals=return_frame.f_locals,  # Key change: use final locals
            f_globals=return_frame.f_globals,
            f_lineno=statement_start_lineno,
            f_lasti=return_frame.f_lasti,
        )

        # 1. Simulate the line event. This creates a pending message with the proxy
        # that holds the final, correct local variables.
        self.logic.handle_line(frame_proxy)
        self.logic._add_to_buffer.assert_not_called()
        self.assertIsNotNone(self.logic._local.last_message)
        self.assertIn("result = [", self.logic._local.last_message[0]["data"]["line"])

        # 2. Simulate the 'return' event, which should flush the pending message.
        # Use the real return_frame for the return event itself.
        self.logic.handle_return(return_frame, [0, 1, 2])

        # Expect 2 calls: the flushed line, and the return statement itself.
        self.assertEqual(self.logic._add_to_buffer.call_count, 2)

        # The first call should be the flushed line message with variables.
        flushed_log_data = self.logic._add_to_buffer.call_args_list[0][0][0]
        self.assertIn("▷", flushed_log_data["template"])
        self.assertIn("result=[0, 1, 2]", flushed_log_data["data"]["vars"])

    def test_delayed_message_flushed_on_exception(self):
        """Tests that a pending line message is flushed when an exception occurs."""
        self.config.enable_var_trace = True
        self.logic = TraceLogic(self.config)
        self.logic._add_to_buffer = MagicMock()
        func = func_with_delayed_exception

        # To accurately simulate a real trace, we need a frame object whose state
        # (like f_locals) evolves. The _get_frame_at helper freezes the frame's
        # state too early.
        # So, we first run the function to completion (until it excepts) to get
        # the frame in its final state.
        exception_frame = None
        exc_type, exc_value, tb = None, None, None
        try:
            func()
        except ZeroDivisionError:
            exc_type, exc_value, tb = sys.exc_info()
            current_tb = tb
            while current_tb.tb_next:
                current_tb = current_tb.tb_next
            exception_frame = current_tb.tb_frame
        finally:
            del tb
        self.assertIsNotNone(exception_frame, "Failed to capture exception frame.")
        # At the point of exception, 'my_list' should have been assigned.
        self.assertIn("my_list", exception_frame.f_locals)

        # Now, simulate the 'line' event that would have occurred at the *start*
        # of the multi-line statement. We use a proxy for the frame that reports
        # the correct starting line number, but shares the final f_locals of the
        # exception frame. This mimics how a single frame object is updated
        # throughout its execution.
        statement_start_lineno = func.__code__.co_firstlineno + 1
        frame_proxy_at_start = SimpleNamespace(
            f_code=exception_frame.f_code,
            f_locals=exception_frame.f_locals,
            f_globals=exception_frame.f_globals,
            f_lineno=statement_start_lineno,
            f_lasti=exception_frame.f_lasti,
        )

        # Simulate the line event. This should create a pending message, not log immediately.
        self.logic.handle_line(frame_proxy_at_start)
        self.logic._add_to_buffer.assert_not_called()
        self.assertIsNotNone(self.logic._local.last_message)
        self.assertIn("my_list = [", self.logic._local.last_message[0]["data"]["line"])

        # Simulate the tracer's exception handler with the real exception frame.
        # This should trigger the flush of the pending message.
        self.logic.handle_exception(exc_type, exc_value, exception_frame)

        # The pending message should have been flushed.
        self.logic._add_to_buffer.assert_called()

        # The first logged call should be the flushed message. Its variables should
        # have been evaluated against the frame proxy, which had the correct final locals.
        flushed_log_data = self.logic._add_to_buffer.call_args_list[0][0][0]
        self.assertIn("my_list", flushed_log_data["data"]["vars"])
        self.assertIn("[0, 1, 2]", flushed_log_data["data"]["vars"])

        # Depending on Python version, the exception is either buffered or logged immediately.
        if sys.version_info >= (3, 12):
            self.assertEqual(len(self.logic.exception_chain), 1)
            exc_log_data = self.logic.exception_chain[0][0]
            self.assertEqual(exc_log_data["data"]["exc_type"], "ZeroDivisionError")
        else:
            # On older versions, the exception is logged directly to the buffer in addition to the flushed message.
            self.assertEqual(self.logic._add_to_buffer.call_count, 2)
            exc_log_data = self.logic._add_to_buffer.call_args_list[1][0][0]
            self.assertEqual(exc_log_data["data"]["exc_type"], "ZeroDivisionError")

    def test_variable_tracing_failure_is_handled(self):
        """Tests that tracer gracefully handles NameErrors when tracing variables."""
        self.config.enable_var_trace = True
        self.logic = TraceLogic(self.config)
        # 使用 _get_frame_at 辅助方法捕获异常发生行的帧
        # 目标行号是 _test_func_for_var_tracing_failure 中引发 NameError 的行
        frame = self._get_frame_at(
            _test_func_for_var_tracing_failure,
            event_type="line",
            lineno=_test_func_for_var_tracing_failure.__code__.co_firstlineno + 2,
        )

        vars_to_trace = ["c", "a", "b"]
        traced_vars = self.logic.trace_variables(frame, vars_to_trace)

        # 应该成功捕获 'a'，但 'b' 和 'c' 会失败（不崩溃）
        self.assertEqual(traced_vars, {"a": "1"})

    def test_thread_safety_of_local_state(self):
        """Tests that thread-local state like stack_depth is handled correctly."""
        self.logic = TraceLogic(self.config)
        errors = []

        def trace_in_thread(depth):
            try:
                # Init logic for this new thread
                self.logic.init_stack_variables()

                # Simulate a call stack of a certain depth
                frames = [self._get_frame_at(simple_target_func) for _ in range(depth)]
                for frame in frames:
                    self.logic.handle_call(frame)

                if self.logic._local.stack_depth != depth:
                    errors.append(f"Thread {depth} expected depth {depth}, got {self.logic._local.stack_depth}")

                for frame in reversed(frames):
                    self.logic.handle_return(frame, None)

            except Exception as e:
                errors.append(f"Thread {depth} failed with {e}")

        threads = [threading.Thread(target=trace_in_thread, args=(i,)) for i in range(1, 5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread safety test failed with errors: {errors}")


@unittest.skipUnless(sys.version_info >= (3, 12), "sys.monitoring is only available in Python 3.12+")
class TestSysMonitoringTraceDispatcher(BaseTracerTest):
    """Tests for SysMonitoringTraceDispatcher using real frames and callables."""

    class _StopTracing(Exception):
        """Custom exception to stop tracing immediately after capturing a frame."""

        pass

    def _get_frame_at(self, func, *args, event_type="call", lineno=None, **kwargs):
        """Helper to get a real frame from a function call at a specific event/line."""
        frame = None

        def tracer(f, event, arg):
            nonlocal frame
            if f.f_code is not func.__code__:
                return tracer
            if event == event_type and (lineno is None or f.f_lineno == lineno):
                frame = f
                raise self._StopTracing
            return tracer

        sys.settrace(tracer)
        try:
            func(*args, **kwargs)
        except self._StopTracing:
            pass
        finally:
            sys.settrace(None)

        if frame is None:
            self.fail(f"Failed to capture frame for {func.__name__} at event '{event_type}', line {lineno}")
        return frame

    def _get_python_frame_for_c_call(self, python_func_calling_c):
        """Executes a Python function that calls a C function and captures the Python frame."""
        frame = None

        def trace_hook(f, event, arg):
            nonlocal frame
            if f.f_code is python_func_calling_c.__code__ and event == "line":
                frame = f
                raise self._StopTracing
            return trace_hook

        sys.settrace(trace_hook)
        try:
            python_func_calling_c()
        except self._StopTracing:
            pass
        finally:
            sys.settrace(None)

        if frame is None:
            self.fail(f"Failed to capture Python frame for C call in {python_func_calling_c.__name__}")
        return frame

    def _get_frames_for_test(self, func, *args, **kwargs):
        """
        Runs a function under a tracer and captures the frames for specific functions in the call stack.
        Returns a dictionary of {func_name: frame_object}.
        This is used to obtain real, correctly-structured frame objects for unit testing.
        """
        captured_frames = {}

        def tracer(frame, event, arg):
            func_name = frame.f_code.co_name
            # Capture the first time we see a frame for a function.
            # The frame object is reused for the lifetime of the call.
            if func_name not in captured_frames:
                captured_frames[frame.f_code.co_name] = frame
            return tracer

        sys.settrace(tracer)
        try:
            func(*args, **kwargs)
        except Exception:
            # We need to capture frames even if an exception occurs during the run.
            pass
        finally:
            sys.settrace(None)

        return captured_frames

    def setUp(self):
        super().setUp()
        self.test_filename = str(Path(__file__).resolve())
        self.config = TraceConfig(target_files=[f"*{Path(self.test_filename).name}"], trace_c_calls=True)
        self.dispatcher = SysMonitoringTraceDispatcher(self.test_filename, self.config)

        self.mock_monitoring = MagicMock()
        self.mock_monitoring.events = MagicMock()
        self.mock_monitoring.events.PY_START = 1
        self.mock_monitoring.events.PY_RETURN = 2
        self.mock_monitoring.events.LINE = 4
        self.mock_monitoring.events.RAISE = 8
        self.mock_monitoring.events.EXCEPTION_HANDLED = 16
        self.mock_monitoring.events.PY_YIELD = 32
        self.mock_monitoring.events.PY_UNWIND = 64
        self.mock_monitoring.events.PY_RESUME = 128
        self.mock_monitoring.events.PY_THROW = 256
        self.mock_monitoring.events.RERAISE = 512
        self.mock_monitoring.events.CALL = 1024
        self.mock_monitoring.events.C_RETURN = 2048
        self.mock_monitoring.events.C_RAISE = 4096
        self.mock_monitoring.events.NO_EVENTS = 0
        self.mock_monitoring.DISABLE = "DISABLE"
        self.mock_monitoring.MISSING = MagicMock()

        self.dispatcher.monitoring_module = self.mock_monitoring
        self.mock_logic = MagicMock(spec=TraceLogic)
        self.dispatcher._logic = self.mock_logic
        self.mock_logic.inside_unwanted_frame.return_value = False

    def test_register_tool(self):
        """Test that the tool is registered correctly with sys.monitoring."""
        self.mock_monitoring.get_tool.side_effect = [None, "ToolInUse", None]
        self.mock_monitoring.use_tool_id.return_value = None

        self.dispatcher._register_tool()

        self.mock_monitoring.use_tool_id.assert_called_once_with(0, "PythonDebugger")
        self.assertEqual(self.dispatcher._tool_id, 0)
        self.assertTrue(self.dispatcher._registered)
        expected_events = (
            self.mock_monitoring.events.PY_START
            | self.mock_monitoring.events.PY_RETURN
            | self.mock_monitoring.events.LINE
            | self.mock_monitoring.events.RAISE
            | self.mock_monitoring.events.EXCEPTION_HANDLED
            | self.mock_monitoring.events.PY_UNWIND
            | self.mock_monitoring.events.PY_RESUME
            | self.mock_monitoring.events.PY_THROW
            | self.mock_monitoring.events.RERAISE
            | self.mock_monitoring.events.PY_YIELD
            | self.mock_monitoring.events.CALL
            | self.mock_monitoring.events.C_RETURN
            | self.mock_monitoring.events.C_RAISE
        )
        self.mock_monitoring.set_events.assert_called_once_with(0, expected_events)

    def test_unregister_tool(self):
        """Test that the tool is unregistered correctly."""
        self.dispatcher._tool_id = 1
        self.dispatcher._registered = True
        self.dispatcher._unregister_tool()

        self.mock_monitoring.set_events.assert_called_once_with(1, self.mock_monitoring.events.NO_EVENTS)
        self.mock_monitoring.free_tool_id.assert_called_once_with(1)
        self.assertFalse(self.dispatcher._registered)
        self.assertIsNone(self.dispatcher._tool_id)

    @patch("sys._getframe")
    def test_handle_py_start_target_frame(self, mock_getframe):
        """Test PY_START for a target Python frame."""
        real_frame = self._get_frame_at(simple_target_func)
        mock_getframe.return_value = real_frame
        self.mock_logic.inside_unwanted_frame.return_value = False

        result = self.dispatcher.handle_py_start(real_frame.f_code, real_frame.f_lasti)

        self.mock_logic.maybe_unwanted_frame.assert_called_once_with(real_frame)
        self.mock_logic.handle_call.assert_called_once_with(real_frame, is_simple=False)
        self.assertIn(real_frame, self.dispatcher.active_frames)
        self.assertIsNone(result)

    @patch("sys._getframe")
    def test_handle_py_return(self, mock_getframe):
        """Test PY_RETURN for an active Python frame."""
        real_frame = self._get_frame_at(simple_target_func, event_type="return")
        mock_getframe.return_value = real_frame
        self.dispatcher.active_frames.add(real_frame)
        self.mock_logic.inside_unwanted_frame.return_value = False

        self.dispatcher.handle_py_return(real_frame.f_code, real_frame.f_lasti, "retval")

        self.mock_logic.leave_unwanted_frame.assert_called_once_with(real_frame)
        self.mock_logic.handle_return.assert_called_once_with(real_frame, "retval", is_simple=False)
        self.mock_logic.frame_cleanup.assert_called_once_with(real_frame)
        self.assertNotIn(real_frame, self.dispatcher.active_frames)

    @patch("sys._getframe")
    def test_handle_line(self, mock_getframe):
        """Test LINE for an active Python frame."""
        lines, start_lineno = inspect.getsourcelines(sample_function)
        target_lineno = start_lineno + 2
        real_frame = self._get_frame_at(sample_function, 1, 1, event_type="line", lineno=target_lineno)
        mock_getframe.return_value = real_frame
        self.dispatcher.active_frames.add(real_frame)

        self.dispatcher.handle_line(real_frame.f_code, real_frame.f_lasti)

        self.mock_logic.handle_line.assert_called_once_with(real_frame)

    @patch("sys._getframe")
    def test_handle_raise(self, mock_getframe):
        """Test RAISE for an active Python frame."""
        real_frame = None
        exc = ValueError("Test Error")
        try:
            function_with_exception(0)
        except ValueError as e:
            exc = e
            _, _, tb = sys.exc_info()
            real_frame = tb.tb_frame
        self.assertIsNotNone(real_frame, "Failed to capture frame from exception")

        mock_getframe.return_value = real_frame
        self.dispatcher.active_frames.add(real_frame)

        self.dispatcher.handle_raise(real_frame.f_code, real_frame.f_lasti, exc)

        self.mock_logic.handle_exception.assert_called_once_with(type(exc), exc, real_frame, is_simple=False)

    @patch("sys._getframe")
    def test_handle_c_call_python_callable(self, mock_getframe):
        """Test CALL event for a Python callable (should be ignored by handle_call)."""

        def python_callable():
            pass

        real_frame = self._get_frame_at(simple_target_func)
        mock_getframe.return_value = real_frame

        result = self.dispatcher.handle_call(MagicMock(), 0, python_callable, self.mock_monitoring.MISSING)

        self.mock_logic.handle_c_call.assert_not_called()
        self.assertIsNone(result)

    @patch("sys._getframe")
    def test_handle_c_call_c_callable_target_frame(self, mock_getframe):
        """Test CALL event for a C callable when caller is a target frame."""

        def c_caller():
            len("abc")

        real_frame = self._get_python_frame_for_c_call(c_caller)
        mock_getframe.return_value = real_frame
        callable_obj, arg0 = len, "abc"

        self.dispatcher.handle_call(real_frame.f_code, real_frame.f_lasti, callable_obj, arg0)

        self.mock_logic.handle_c_call.assert_called_once_with(real_frame, callable_obj, arg0)

    @patch("sys._getframe")
    def test_handle_c_call_c_callable_non_target_frame(self, mock_getframe):
        """Test CALL event for a C callable when caller is NOT a target frame."""
        code = "def non_target_c_caller():\n    len('abc')"
        real_frame = self._create_frame_from_code(code, "non_target.py", "non_target_c_caller")
        mock_getframe.return_value = real_frame
        callable_obj, arg0 = len, "abc"

        self.dispatcher.handle_call(real_frame.f_code, real_frame.f_lasti, callable_obj, arg0)

        self.mock_logic.handle_c_call.assert_not_called()

    @patch("sys._getframe")
    def test_handle_c_return(self, mock_getframe):
        """Test C_RETURN event."""

        def c_caller():
            sum([1, 2, 3])

        real_frame = self._get_python_frame_for_c_call(c_caller)
        mock_getframe.return_value = real_frame
        callable_obj, retval = sum, 6

        self.dispatcher.handle_c_return(MagicMock(), 0, callable_obj, retval)

        self.mock_logic.handle_c_return.assert_called_once_with(real_frame, callable_obj, retval)

    @patch("sys._getframe")
    def test_handle_c_raise(self, mock_getframe):
        """Test C_RAISE event."""

        def c_raiser():
            try:
                open("nonexistent.file")
            except FileNotFoundError:
                pass

        real_frame = self._get_python_frame_for_c_call(c_raiser)
        mock_getframe.return_value = real_frame
        callable_obj = open
        exception = FileNotFoundError("file not found")

        self.dispatcher.handle_c_raise(MagicMock(), 0, callable_obj, exception)

        self.mock_logic.handle_c_raise.assert_called_once_with(real_frame, callable_obj, exception)

    def test_boundary_call_and_return(self):
        """Tests that PY_START in a non-target is handled as a boundary call."""
        # Setup: only trace this test file.
        self.config = TraceConfig(target_files=[f"*{Path(self.test_filename).name}"])
        self.dispatcher = SysMonitoringTraceDispatcher(self.test_filename, self.config)
        self.dispatcher.monitoring_module = self.mock_monitoring
        self.mock_logic = MagicMock(spec=TraceLogic)
        self.mock_logic.exception_chain = []
        self.dispatcher._logic = self.mock_logic
        self.mock_logic.inside_unwanted_frame.return_value = False

        # Capture real frames from a call
        frames = self._get_frames_for_test(target_main_function, 10, 5)
        frame_target = frames["target_main_function"]
        frame_nontarget = frames["non_target_helper"]

        # --- Simulate Trace ---
        # 1. Start of target_main_function

        with patch("sys._getframe", return_value=frame_target):
            result = self.dispatcher.handle_py_start(frame_target.f_code, frame_target.f_lasti)
            self.assertIsNone(result)  # Should enable all events for a target frame
            self.mock_logic.handle_call.assert_called_once_with(frame_target, is_simple=False)
        # 2. Start of non_target_helper (boundary call)
        with patch("sys._getframe", return_value=frame_nontarget):
            result = self.dispatcher.handle_py_start(frame_nontarget.f_code, frame_nontarget.f_lasti)
            expected_events = self.mock_monitoring.events.PY_RETURN | self.mock_monitoring.events.PY_UNWIND
            self.assertEqual(result, expected_events)
            self.mock_logic.handle_call.assert_called_with(frame_nontarget, is_simple=True)
            self.assertIn(frame_nontarget, self.dispatcher.simple_frames)

        # 3. Line event inside non_target_helper should be ignored
        with patch("sys._getframe", return_value=frame_nontarget):
            self.dispatcher.handle_line(frame_nontarget.f_code, frame_nontarget.f_lineno)
            # handle_line is only called for active_frames, so mock should not be called.
            self.mock_logic.handle_line.assert_not_called()

        # 4. Return from non_target_helper
        with patch("sys._getframe", return_value=frame_nontarget):
            self.dispatcher.handle_py_return(frame_nontarget.f_code, frame_nontarget.f_lasti, 10)
            self.mock_logic.handle_return.assert_called_once_with(frame_nontarget, 10, is_simple=True)
            self.assertNotIn(frame_nontarget, self.dispatcher.simple_frames)

    def test_boundary_exception(self):
        """Tests that exceptions from non-target functions are handled as boundary exceptions."""
        self.config = TraceConfig(target_files=[f"*{Path(self.test_filename).name}"])
        self.dispatcher = SysMonitoringTraceDispatcher(self.test_filename, self.config)
        self.dispatcher.monitoring_module = self.mock_monitoring
        self.mock_logic = MagicMock(spec=TraceLogic)
        self.mock_logic.exception_chain = []
        self.dispatcher._logic = self.mock_logic
        self.mock_logic.inside_unwanted_frame.return_value = False

        frames = self._get_frames_for_test(target_main_caller_of_raiser)
        frame_target = frames["target_main_caller_of_raiser"]
        frame_nontarget = frames["non_target_raiser"]

        # --- Simulate Trace ---
        # 1. Start of target function
        with patch("sys._getframe", return_value=frame_target):
            self.dispatcher.handle_py_start(frame_target.f_code, frame_target.f_lasti)
            self.mock_logic.handle_call.assert_called_once_with(frame_target, is_simple=False)

        # 2. Start of non-target raiser function (boundary)
        with patch("sys._getframe", return_value=frame_nontarget):
            self.dispatcher.handle_py_start(frame_nontarget.f_code, frame_nontarget.f_lasti)
            self.mock_logic.handle_call.assert_called_with(frame_nontarget, is_simple=True)

        # 3. Exception raised in non-target function
        exc = ValueError("Error from non-target function")
        with patch("sys._getframe", return_value=frame_nontarget):
            self.dispatcher.handle_raise(frame_nontarget.f_code, frame_nontarget.f_lasti, exc)
            self.mock_logic.handle_exception.assert_called_once_with(type(exc), exc, frame_nontarget, is_simple=True)

        # 4. Unwind from non-target function
        with patch("sys._getframe", return_value=frame_nontarget):
            self.dispatcher.handle_py_unwind(frame_nontarget.f_code, frame_nontarget.f_lasti)
            self.assertNotIn(frame_nontarget, self.dispatcher.simple_frames)


class TestCallTreeHtmlRender(BaseTracerTest):
    """Tests for the CallTreeHtmlRender."""

    def setUp(self):
        super().setUp()
        self.mock_logic = MagicMock()
        self.renderer = CallTreeHtmlRender(self.mock_logic)

    def test_add_raw_message_and_generate(self):
        self.renderer.add_raw_message({"template": "↘ CALL {func}", "data": {"func": "my_func"}}, "call")
        self.renderer.add_raw_message(
            {
                "template": "▷ {line}",
                "data": {"line": "x = 1", "original_filename": "/app/main.py", "lineno": 5, "frame_id": 1},
            },
            "line",
        )

        with patch("builtins.open", mock_open(read_data=b'print("hello")')) as mock_file:
            html = self.renderer.generate_html()

        self.assertIn('<div class="foldable call"', html)
        self.assertIn("↘&nbsp;CALL&nbsp;my_func", html)
        self.assertIn('<div class="line"', html)
        self.assertIn("▷&nbsp;x&nbsp;=&nbsp;1", html)
        self.assertIn("view-source-btn", html)
        self.assertIn('window.executedLines = {"/app/main.py": {"1": [5]}}', html)
        self.assertIn('window.sourceFiles = {"/app/main.py":', html)

    def test_add_stack_variable(self):
        self.renderer.add_stack_variable_create(1, dis.opmap["LOAD_NAME"], "x", 42)
        self.assertIn(1, self.renderer._stack_variables)
        self.assertEqual(self.renderer._stack_variables[1][0], (dis.opmap["LOAD_NAME"], "x", 42))

    def test_save_to_file(self):
        report_dir = Path.cwd() / "tracer-logs"
        report_dir.mkdir(exist_ok=True)
        report_path = report_dir / "render_test.html"

        self.renderer.add_raw_message({"template": "test message", "data": {}}, "call")
        # Since logic for multi-threaded changes directory, we test the simple case
        saved_path = self.renderer.save_to_file("render_test.html", False)

        self.assertEqual(saved_path, report_path)
        self.assertTrue(report_path.exists())
        with open(report_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("test&nbsp;message", content)


class TestTraceLogExtractor(BaseTracerTest):
    """TraceLogExtractor test suite."""

    def setUp(self):
        super().setUp()
        self.log_file = self.test_dir / "debug.log"
        self.index_file = self.log_file.with_suffix(".log.index")
        self._generate_test_logs()

    def _generate_test_logs(self):
        logs = [
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:00Z",
                "filename": "test_file.py",
                "lineno": 5,
                "frame_id": 100,
                "message": "CALL func1",
                "original_filename": "test_file.py",  # Added for consistency with real logs
                "func": "func1",  # Added for consistency with real logs
            },
            {
                "type": "line",
                "timestamp": "2023-01-01T00:00:01Z",
                "filename": "test_file.py",
                "lineno": 10,
                "frame_id": 100,
                "message": "LINE 10",
                "original_filename": "test_file.py",
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:02Z",
                "filename": "test_file.py",
                "lineno": 5,
                "frame_id": 100,
                "message": "RETURN func1",
                "original_filename": "test_file.py",
                "func": "func1",
            },
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:03Z",
                "filename": "test_file.py",
                "lineno": 20,
                "frame_id": 200,
                "message": "CALL func2",
                "original_filename": "test_file.py",
                "func": "func2",
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:05Z",
                "filename": "test_file.py",
                "lineno": 20,
                "frame_id": 200,
                "message": "RETURN func2",
                "original_filename": "test_file.py",
                "func": "func2",
            },
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:09Z",
                "filename": "test_file.py",
                "lineno": 40,
                "frame_id": 400,
                "message": "CALL func4",
                "original_filename": "test_file.py",
                "func": "func4",
            },
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:10Z",
                "filename": "test_file.py",
                "lineno": 46,
                "frame_id": 400,
                "message": "CALL sub_func",
                "func": "abc",
                "original_filename": "test_file.py",
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:11Z",
                "filename": "test_file.py",
                "lineno": 40,
                "frame_id": 400,
                "message": "RETURN func4",
                "original_filename": "test_file.py",
                "func": "func4",
            },
        ]
        with open(self.log_file, "w", encoding="utf-8") as log_f, open(self.index_file, "w", encoding="utf-8") as idx_f:
            pos = 0
            for log_entry in logs:
                line = json.dumps(log_entry) + "\n"
                log_f.write(line)
                if log_entry["type"] in (
                    "call",
                    "return",
                    "exception",
                    "c_call",
                    "c_return",
                    "c_raise",
                ):  # Updated index types
                    idx_entry = {
                        "type": log_entry["type"],
                        "filename": log_entry["original_filename"],  # Use original_filename for index
                        "lineno": log_entry["lineno"],
                        "frame_id": log_entry["frame_id"],
                        "position": pos,
                        "func": log_entry.get("func", ""),
                        "parent_frame_id": log_entry.get("parent_frame_id", 0),  # Added parent_frame_id
                    }
                    idx_f.write(json.dumps(idx_entry) + "\n")
                pos += len(line.encode("utf-8"))


class TestIntegration(BaseTracerTest):
    """Higher-level tests for start_trace and the @trace decorator."""

    def test_full_trace_cycle(self):
        """
        Tests a full tracing cycle using the start_trace entry point
        to ensure the default tracer works end-to-end.
        """
        # start_trace will select the correct dispatcher automatically.
        # This is a full integration test without mocks.
        tracer = start_trace(target_files=[f"*{Path(__file__).name}"])
        self.assertIsNotNone(tracer)

        try:
            # The actual code being traced.
            result = sample_function(5, 10)
            self.assertEqual(result, (30, "large"))
        finally:
            # Ensure the tracer is stopped even if the test fails.
            stop_trace(tracer)

        # Check if logs were produced by inspecting the tracer's internal state.
        self.assertGreater(len(tracer._logic._html_render._messages), 0)

    def _run_e2e_test(self, script_path, cli_args, extra_pythonpath: str | None = None):
        """Helper to run tracer_main as a subprocess for E2E tests."""
        # Define PYTHONPATH to include the project's src directory
        env = os.environ.copy()
        project_root = Path(__file__).parent.parent
        src_path = str(project_root / "context-tracer" / "src")

        python_path_parts = [src_path, str(project_root), env.get("PYTHONPATH", "")]
        if extra_pythonpath:
            python_path_parts.insert(0, extra_pythonpath)

        env["PYTHONPATH"] = os.pathsep.join(filter(None, python_path_parts))

        # Build command
        command = (
            [
                sys.executable,
                "-m",
                "context_tracer.tracer_main",
            ]
            + cli_args
            + [str(script_path)]
        )

        # Run process
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        # Print subprocess output for debugging if test fails
        if process.returncode != 0:
            print(f"Subprocess stdout:\n{process.stdout}")
            print(f"Subprocess stderr:\n{process.stderr}")

        return process

    def test_e2e_delayed_message_on_exit(self):
        """
        E2E test to ensure delayed messages (from multi-line statements) are
        flushed correctly when the script exits.
        """
        script_content = dedent("""
            import sys
            def main():
                my_list = [ # This multi-line statement creates a delayed message
                    x
                    for x in range(10)
                ]
                # A new line is needed to flush the pending message from the statement above,
                # as the implicit return does not correctly capture the variable's final state.
                print(my_list)
            if __name__ == "__main__":
                main()
        """)
        script_path = self.test_dir / "script_with_exit.py"
        script_path.write_text(script_content, encoding="utf-8")

        log_dir = Path.cwd() / "tracer-logs"
        report_name = f"{script_path.stem}.html"
        log_file_path = log_dir / f"{script_path.stem}.log"
        if log_file_path.exists():
            log_file_path.unlink()

        cli_args = ["--enable-var-trace", "--report-name", report_name]
        process = self._run_e2e_test(script_path, cli_args)

        self.assertEqual(process.returncode, 0)
        self.assertTrue(log_file_path.exists(), f"Log file not found at {log_file_path}")

        log_content = log_file_path.read_text(encoding="utf-8")
        # The key is to check that the variable `my_list` was logged, which means
        # the delayed message was flushed by the `stop()` logic.
        self.assertIn("my_list=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]", log_content)

    def test_e2e_skip_vars_on_lines_cli(self):
        """
        E2E test to ensure --skip-vars-on-lines CLI flag works correctly and
        prevents crashes from buggy __repr__ implementations.
        """
        script_content = dedent("""
            class BuggyRepr:
                def __repr__(self):
                    raise RuntimeError("This repr is buggy!")

            def process_object(obj):
                # This line is where the tracer will try to represent 'obj'
                print("Processing...")
                return obj

            def main():
                buggy_instance = BuggyRepr()
                result = process_object(buggy_instance)

            if __name__ == "__main__":
                main()
        """)
        script_path = self.test_dir / "buggy_repr_script.py"
        script_path.write_text(script_content, encoding="utf-8")

        log_dir = Path.cwd() / "tracer-logs"
        report_name = f"{script_path.stem}.html"
        log_file_path = log_dir / f"{script_path.stem}.log"
        if log_file_path.exists():
            log_file_path.unlink()

        # Run the tracer with the skip rule
        cli_args = ["--report-name", report_name, "--skip-vars-on-lines", f"*{script_path.name}:1-20"]
        process = self._run_e2e_test(script_path, cli_args)

        # Assert it didn't crash
        self.assertEqual(process.returncode, 0, f"Tracer process exited with error. Stderr: {process.stderr}")
        self.assertTrue(log_file_path.exists())

        log_content = log_file_path.read_text(encoding="utf-8")

        # Assert call to `process_object` shows safe repr for the argument
        self.assertIn("↘ CALL", log_content)
        # In some environments, safe repr falls back to '...'.
        # The main goal is to ensure the tracer doesn't crash.
        self.assertIn("process_object(obj=<BuggyRepr object>)", log_content)

        # Assert return from `process_object` shows safe repr for the return value
        self.assertIn("↗ RETURN", log_content)
        self.assertIn("→ <BuggyRepr object>", log_content)

    @unittest.skipUnless(sys.version_info >= (3, 12), "C function tracing requires Python 3.12+")
    def test_e2e_c_calls_tracing(self):
        """
        End-to-end test for C function call tracing using sys.monitoring.
        """
        target_script_content = dedent(
            """
            import os
            import sys

            def call_c_functions():
                my_list = [1, 2, 3]
                list_len = len(my_list)
                print(f"Len: {list_len}")
                try:
                    with open("non_existent_file.txt", "r") as f:
                        f.read()
                except FileNotFoundError:
                    print("Caught FileNotFoundError")
                data = {'a': 1, 'b': 2}
                items = data.items()
                print(f"Items: {items}")
                size = sys.getsizeof(10)
                print(f"Size of 10: {size}")

            if __name__ == "__main__":
                call_c_functions()
            """
        )
        script_path = self.test_dir / "c_call_test_script.py"
        script_path.write_text(target_script_content, encoding="utf-8")

        report_name = f"{script_path.stem}.html"
        log_dir = Path.cwd() / "tracer-logs"
        log_file_path = log_dir / f"{script_path.stem}.log"
        if log_file_path.exists():
            log_file_path.unlink()

        cli_args = ["--trace-c-calls", "--report-name", report_name]
        process = self._run_e2e_test(script_path, cli_args)

        self.assertEqual(process.returncode, 0, f"Tracer process exited with error code {process.returncode}")
        self.assertTrue(log_file_path.exists(), f"Log file not found at {log_file_path}")

        log_content = log_file_path.read_text(encoding="utf-8")
        self.assertIn("↘ C-CALL len", log_content)
        self.assertIn("↗ C-RETURN from len", log_content)
        self.assertIn("⚠ C-RAISE from open", log_content)
        self.assertIn("↘ C-CALL items", log_content)
        self.assertIn("↗ C-RETURN from items", log_content)
        self.assertIn("↘ C-CALL getsizeof", log_content)
        self.assertIn("↗ C-RETURN from getsizeof", log_content)

    @unittest.skipUnless(sys.version_info >= (3, 12), "C function tracing requires Python 3.12+")
    def test_e2e_c_calls_tracing_disabled(self):
        """
        End-to-end test to ensure C function tracing is DISABLED when flag is not set.
        """
        target_script_content = dedent(
            """
            def call_c_functions():
                len([1, 2, 3])
            if __name__ == "__main__":
                call_c_functions()
            """
        )
        script_path = self.test_dir / "no_c_call_test_script.py"
        script_path.write_text(target_script_content, encoding="utf-8")

        report_name = f"{script_path.stem}.html"
        log_dir = Path.cwd() / "tracer-logs"
        log_file_path = log_dir / f"{script_path.stem}.log"
        if log_file_path.exists():
            log_file_path.unlink()

        process = self._run_e2e_test(script_path, ["--report-name", report_name])

        self.assertEqual(process.returncode, 0, f"Tracer process exited with error code {process.returncode}")
        self.assertTrue(log_file_path.exists(), f"Log file not found at {log_file_path}")

        log_content = log_file_path.read_text(encoding="utf-8")
        self.assertNotIn("↘ C-CALL", log_content)
        self.assertNotIn("↗ C-RETURN", log_content)
        self.assertNotIn("⚠ C-RAISE", log_content)

    def test_e2e_settrace_boundary_exception(self):
        """
        E2E test for sys.settrace dispatcher to correctly handle boundary exceptions.
        This replaces the unit test which was prone to interference.
        """
        # 1. Create helper (non-target) script
        helper_content = dedent("""
            def non_target_raiser():
                raise ValueError("Error from non-target function")
        """)
        helper_script_path = self.test_dir / "helper_script.py"
        helper_script_path.write_text(helper_content, encoding="utf-8")

        # 2. Create main (target) script
        target_content = dedent(f"""
            import sys
            # This allows importing from the same directory in the subprocess
            sys.path.insert(0, r'{str(self.test_dir)}')
            from helper_script import non_target_raiser

            def target_main_caller_of_raiser():
                try:
                    # This should be a B-CALL that raises a B-EXCEPTION
                    non_target_raiser()
                except ValueError as e:
                    # This line should be traced normally
                    return str(e)
                # This line should be traced normally
                return "No error"

            if __name__ == "__main__":
                result = target_main_caller_of_raiser()
                # The output helps verify the script ran correctly.
                print(f"Script result: {{result}}")
        """)
        target_script_path = self.test_dir / "target_script.py"
        target_script_path.write_text(target_content, encoding="utf-8")

        # 3. Setup log file paths for assertion
        log_dir = Path.cwd() / "tracer-logs"
        report_name = f"{target_script_path.stem}.html"
        log_file_path = log_dir / f"{target_script_path.stem}.log"
        if log_file_path.exists():
            log_file_path.unlink()

        # 4. Run the tracer, targeting ONLY the main script
        cli_args = ["--report-name", report_name, "--watch-files", f"*{target_script_path.name}"]
        process = self._run_e2e_test(target_script_path, cli_args, extra_pythonpath=str(self.test_dir))

        # 5. Assertions
        self.assertEqual(process.returncode, 0, f"Tracer process exited with error. Stderr: {process.stderr}")
        self.assertTrue(log_file_path.exists(), f"Log file not found at {log_file_path}")

        log_content = log_file_path.read_text(encoding="utf-8")

        # Check that the script ran and produced the expected output
        self.assertIn("Script result: Error from non-target function", process.stdout)

        # Check for boundary call, exception, and normal return
        self.assertIn("↘ B-CALL", log_content)
        self.assertIn("non_target_raiser()", log_content)
        self.assertIn("⚠ B-EXCEPTION IN non_target_raiser", log_content)
        self.assertIn("ValueError: Error from non-target function", log_content)
        self.assertIn("↗ RETURN", log_content)
        self.assertIn("target_main_caller_of_raiser() → 'Error from non-target function'", log_content)


class TestTraceDispatcher(BaseTracerTest):
    """Tests for the sys.settrace-based TraceDispatcher."""

    def setUp(self):
        super().setUp()
        self.test_filename = str(Path(__file__).resolve())
        self.config = None
        self.dispatcher = None
        self.mock_logic = None

    def _setup_dispatcher(self, config):
        self.config = config
        self.dispatcher = TraceDispatcher(self.test_filename, self.config)
        self.mock_logic = MagicMock(spec=TraceLogic)
        self.dispatcher._logic = self.mock_logic
        self.mock_logic.inside_unwanted_frame.return_value = False
        self.mock_logic.exception_chain = []

    def test_boundary_call_and_return(self):
        """Tests that calls from a target to a non-target are handled as boundary calls."""
        # Setup: only trace this test file, not the helper file.
        config = TraceConfig(target_files=[f"*{Path(__file__).name}"])
        self._setup_dispatcher(config)

        # Run the trace
        sys.settrace(self.dispatcher.trace_dispatch)
        try:
            target_main_function(10, 5)
        finally:
            sys.settrace(None)

        # Assertions
        handle_call_mock = self.mock_logic.handle_call
        handle_return_mock = self.mock_logic.handle_return
        handle_line_mock = self.mock_logic.handle_line

        # 1. Check calls
        self.assertEqual(handle_call_mock.call_count, 2)
        # First call is to the target function (is_simple=False)
        first_call_args = handle_call_mock.call_args_list[0]
        self.assertEqual(first_call_args[0][0].f_code.co_name, "target_main_function")
        self.assertFalse(first_call_args[1].get("is_simple", False))
        # Second call is to the non-target helper (is_simple=True)
        second_call_args = handle_call_mock.call_args_list[1]
        self.assertEqual(second_call_args[0][0].f_code.co_name, "non_target_helper")
        self.assertTrue(second_call_args[1].get("is_simple"))

        # 2. Check line events
        self.assertGreater(handle_line_mock.call_count, 0)
        for call in handle_line_mock.call_args_list:
            frame = call[0][0]
            self.assertEqual(
                frame.f_code.co_name, "target_main_function", "Line event should only occur in target function"
            )

        # 3. Check returns
        self.assertEqual(handle_return_mock.call_count, 2)
        # First return is from the non-target helper (is_simple=True)
        first_return_args = handle_return_mock.call_args_list[0]
        self.assertEqual(first_return_args[0][0].f_code.co_name, "non_target_helper")
        self.assertTrue(first_return_args[1].get("is_simple"))
        # Second return is from the target function (is_simple=False)
        second_return_args = handle_return_mock.call_args_list[1]
        self.assertEqual(second_return_args[0][0].f_code.co_name, "target_main_function")
        self.assertFalse(second_return_args[1].get("is_simple", False))


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
