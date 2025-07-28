import dis
import importlib.util
import inspect
import json
import os
import shutil
import site
import sys
import unittest
from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, mock_open, patch

import yaml  # Import yaml for test_from_yaml fix

# Add project root to path to allow importing debugger modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from debugger.tracer import (
    CallTreeHtmlRender,
    SysMonitoringTraceDispatcher,
    TraceConfig,
    TraceDispatcher,
    TraceLogExtractor,
    TraceLogic,
    start_trace,
    truncate_repr_value,
)
from debugger.tracer_common import _MAX_VALUE_LENGTH, TraceTypes

# A temporary directory for test artifacts
TEST_DIR = Path(__file__).parent / "test_artifacts"

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

    def _create_mock_frame(self, filename, lineno, func_name, f_locals=None, f_globals=None, f_back=None):
        """
        Creates a mock frame object with essential attributes for tracing.
        """
        mock_code = MagicMock()
        mock_code.co_filename = filename
        mock_code.co_name = func_name
        mock_frame = MagicMock()
        mock_frame.f_code = mock_code
        mock_frame.f_lineno = lineno
        mock_frame.f_locals = f_locals if f_locals is not None else {}
        mock_frame.f_globals = f_globals if f_globals is not None else {}
        mock_frame.f_back = f_back
        # Add a mock for f_trace_lines as it's set by TraceDispatcher
        mock_frame.f_trace_lines = True
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
        self.assertIn("TestObj.({'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6})", result)


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
        self.assertEqual(config.capture_vars, sample_config["capture_vars"])
        self.assertEqual(config.exclude_functions, sample_config["exclude_functions"])
        self.assertFalse(config.ignore_system_paths)
        self.assertEqual(config.source_base_dir, sample_config["source_base_dir"])
        self.assertTrue(config.disable_html)
        self.assertEqual(config.include_stdlibs, sample_config["include_stdlibs"])
        self.assertTrue(config.trace_c_calls)  # New assertion
        test_py_path.unlink()  # Clean up dummy file

    def test_match_filename(self):
        config = TraceConfig(target_files=["*/test_*.py", "*/debugger/*"])
        current_file = Path(__file__).resolve().as_posix()
        self.assertTrue(config.match_filename(current_file))
        self.assertTrue(config.match_filename("/fake/path/to/debugger/tracer.py"))
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


class TestTraceLogic(BaseTracerTest):
    """Tests for the core TraceLogic."""

    class _StopTracing(Exception):
        """Custom exception to stop tracing immediately after capturing a frame."""

        pass

    # Patch inspect.getargvalues for all tests in this class
    # The patch target is where inspect is used in tracer.py, not the global inspect module
    # @patch('debugger.tracer.inspect.getargvalues')
    def setUp(self):  # mock_getargvalues will be passed by the patch decorator
        super().setUp()
        self.test_filename = str(Path(__file__).resolve())
        self.config = TraceConfig(target_files=[self.test_filename])
        self.logic = TraceLogic(self.config)
        # Mock the internal _add_to_buffer for easier assertion
        self.logic._add_to_buffer = MagicMock()

        if hasattr(self.logic, "_local"):
            if hasattr(self.logic._local, "bad_frame"):
                del self.logic._local.bad_frame
            if hasattr(self.logic._local, "stack_depth"):
                del self.logic._local.stack_depth

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
            if f.f_code is not func.__code__:
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

    def test_handle_call(self):
        frame = self._get_frame_at(sample_function, 5, 3, event_type="call")

        self.logic.handle_call(frame)

        self.logic._add_to_buffer.assert_called_once()
        call_args = self.logic._add_to_buffer.call_args[0]
        log_data = call_args[0]

        # 格式化消息以进行断言，因为模板使用了 {prefix} 占位符
        formatted_message = log_data["template"].format(**log_data["data"])
        self.assertIn("↘ CALL", formatted_message)
        self.assertIn("sample_function(x=5, y=3)", formatted_message)
        self.assertEqual(self.logic._local.stack_depth, 1)

    def test_handle_return(self):
        frame = self._get_frame_at(sample_function, 5, 3, event_type="return")
        # Simulate being inside a call
        self.logic._local.stack_depth = 1
        self.logic.handle_return(frame, (16, "large"))

        self.logic._add_to_buffer.assert_called_once()
        call_args = self.logic._add_to_buffer.call_args[0]
        log_data = call_args[0]

        self.assertIn("↗ RETURN", log_data["template"])
        self.assertIn("→ (16, 'large')", log_data["template"].format(**log_data["data"]))
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
        # correct state but reports the original line number. We can't modify the real
        # frame's read-only attributes, so we create a mock that has the necessary state.
        mock_frame = MagicMock()
        mock_frame.f_code = frame.f_code
        mock_frame.f_locals = frame.f_locals
        mock_frame.f_globals = frame.f_globals
        mock_frame.f_lineno = comment_lineno  # Lie about the line number

        self.logic.handle_line(mock_frame)

        # Expect two calls: one for the line log, the second is for the trace comment.
        self.assertEqual(self.logic._add_to_buffer.call_count, 2)
        last_call_args = self.logic._add_to_buffer.call_args_list[1][0]
        log_data = last_call_args[0]
        self.assertIn("↳ Debug Statement c=small", log_data["template"].format(**log_data["data"]))
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
            self.logic._add_to_buffer.assert_not_called()  # Handled by py_unwind later
            log_data, _ = self.logic.exception_chain[0]
        else:
            self.logic._add_to_buffer.assert_called_once()
            self.assertEqual(len(self.logic.exception_chain), 0)
            log_data, _ = self.logic._add_to_buffer.call_args[0]

        self.assertIn("⚠ EXCEPTION", log_data["template"])
        self.assertIn("ValueError: x cannot be zero", log_data["template"].format(**log_data["data"]))
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
        test_msg = {"template": "test {value}", "data": {"value": 42}}

        with patch("builtins.print") as mock_print:
            self.logic._console_output(test_msg, "call")
            mock_print.assert_called_once()

        log_file = self.test_dir / "handler_test.log"
        self.logic.enable_output("file", filename=str(log_file))
        self.logic._file_output(test_msg, None)
        self.logic.disable_output("file")
        with open(log_file, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("test 42", content)

    def test_unwanted_frame_state_management(self):
        """
        Tests that TraceLogic correctly manages its internal 'unwanted frame' state
        (`_local.bad_frame`) when functions are marked for exclusion.
        This test does NOT verify if events are actually logged,
        as that's the Dispatcher's responsibility.
        """
        self.config.exclude_functions = ["excluded_main_func"]

        # 1. Simulate call to main_func_calling_excluded (not excluded itself)
        frame_main = self._create_mock_frame(self.test_filename, 10, "main_func_calling_excluded")
        # TraceLogic.handle_call would be called by dispatcher for this.
        self.logic.handle_call(frame_main)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_main))
        self.logic._add_to_buffer.assert_called_once()  # Main func should be logged
        self.logic._add_to_buffer.reset_mock()

        # 2. Simulate call to excluded_main_func from main_func_calling_excluded
        frame_excluded = self._create_mock_frame(self.test_filename, 5, "excluded_main_func", f_back=frame_main)
        # Dispatcher would call maybe_unwanted_frame, and then handle_call if not already unwanted
        self.logic.maybe_unwanted_frame(frame_excluded)

        # Verify that excluded_main_func's frame is now considered unwanted by TraceLogic's internal state
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded))
        self.assertEqual(self.logic._local.bad_frame, self.logic.get_or_reuse_frame_id(frame_excluded))

        # 3. Simulate line event within excluded_main_func - TraceLogic's handle_line *would* process it if called
        # (but Dispatcher prevents the call)
        self.logic.handle_line(frame_excluded)  # Directly call handle_line for testing TraceLogic's function
        self.logic._add_to_buffer.assert_called_once()  # It should be logged when called directly
        self.logic._add_to_buffer.reset_mock()

        # 4. Simulate call to excluded_helper_func_internal from excluded_main_func
        frame_nested_excluded = self._create_mock_frame(
            self.test_filename, 2, "excluded_helper_func_internal", f_back=frame_excluded
        )
        self.logic.maybe_unwanted_frame(frame_nested_excluded)  # Should NOT update bad_frame as it's already set
        self.assertTrue(self.logic.inside_unwanted_frame(frame_nested_excluded))  # Still inside unwanted context
        self.assertEqual(
            self.logic._local.bad_frame, self.logic.get_or_reuse_frame_id(frame_excluded)
        )  # Still the first excluded frame ID

        # 5. Simulate line event within excluded_helper_func_internal
        self.logic.handle_line(frame_nested_excluded)  # Directly call handle_line
        self.logic._add_to_buffer.assert_called_once()  # It should be logged when called directly
        self.logic._add_to_buffer.reset_mock()

        # 6. Simulate return from excluded_helper_func_internal
        self.logic.handle_return(frame_nested_excluded, 2)  # Directly call handle_return
        self.logic._add_to_buffer.assert_called_once()  # It should be logged when called directly
        self.logic._add_to_buffer.reset_mock()
        # bad_frame should still be set to frame_excluded's ID
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded))

        # 7. Simulate return from excluded_main_func
        self.logic.handle_return(frame_excluded, 7)  # Directly call handle_return
        self.logic._add_to_buffer.assert_called_once()  # It should be logged when called directly
        self.logic._add_to_buffer.reset_mock()
        # Explicitly call leave_unwanted_frame for the original excluded frame to clear the state
        self.logic.leave_unwanted_frame(frame_excluded)
        # After returning from the *original* bad frame, the state should be cleared
        self.assertFalse(self.logic.inside_unwanted_frame(frame_main))  # Now back in the main function

        # 8. Simulate line event back in main_func_calling_excluded - should be logged
        self.logic.handle_line(frame_main)
        self.logic._add_to_buffer.assert_called_once()

    def test_unwanted_frame_exception_state_management(self):
        """
        Tests that TraceLogic correctly manages its internal 'unwanted frame' state
        during exceptions within excluded functions.
        This test does NOT verify if events are actually logged by Dispatcher.
        """
        self.config.exclude_functions = ["excluded_raiser"]
        if hasattr(self.logic._local, "bad_frame"):
            del self.logic._local.bad_frame

        # 1. Simulate call to main_func_calling_raiser (not excluded)
        frame_main = self._create_mock_frame(self.test_filename, 1, "main_func_calling_raiser")
        self.logic.handle_call(frame_main)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_main))
        self.logic._add_to_buffer.assert_called_once()
        self.logic._add_to_buffer.reset_mock()

        # 2. Simulate call to excluded_raiser from main_func_calling_raiser
        frame_raiser = self._create_mock_frame(self.test_filename, 2, "excluded_raiser", f_back=frame_main)
        self.logic.maybe_unwanted_frame(frame_raiser)
        self.assertTrue(self.logic.inside_unwanted_frame(frame_raiser))
        self.assertEqual(self.logic._local.bad_frame, self.logic.get_or_reuse_frame_id(frame_raiser))

        # 3. Simulate exception within excluded_raiser
        mock_exc_type = RuntimeError
        mock_exc_value = RuntimeError("Excluded function error")
        # Directly call handle_exception on TraceLogic. It should process it.
        self.logic.handle_exception(mock_exc_type, mock_exc_value, frame_raiser)

        if sys.version_info >= (3, 12):
            self.assertEqual(len(self.logic.exception_chain), 1)
        else:
            self.logic._add_to_buffer.assert_called_once()
            self.logic._add_to_buffer.reset_mock()

        # 4. Simulate stack unwinding for the raiser frame (e.g., via PY_UNWIND or implicitly on exit)
        self.logic.decrement_stack_depth()
        self.logic.leave_unwanted_frame(frame_raiser)  # This clears bad_frame
        self.logic.frame_cleanup(frame_raiser)

        self.assertFalse(self.logic.inside_unwanted_frame(frame_main))  # Back in main, no longer unwanted

        # 5. Simulate line event back in main_func_calling_raiser (e.g., in the except block)
        self.logic.handle_line(frame_main)
        self.logic._add_to_buffer.assert_called_once()  # Should be logged
        self.logic._add_to_buffer.reset_mock()

    def test_exclude_none_effect_on_call(self):
        # Test that if a function is *not* excluded, maybe_unwanted_frame doesn't mark it
        self.config.exclude_functions = []
        if hasattr(self.logic._local, "bad_frame"):
            del self.logic._local.bad_frame
        frame_target = self._create_mock_frame(self.test_filename, 1, "simple_target_func")
        self.logic.maybe_unwanted_frame(frame_target)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_target))
        self.assertIsNone(self.logic._local.bad_frame)

    def test_no_effect_if_already_unwanted(self):
        self.config.exclude_functions = ["excluded_main_func", "excluded_helper_func_internal"]
        if hasattr(self.logic._local, "bad_frame"):
            del self.logic._local.bad_frame

        frame_excluded_main = self._create_mock_frame(self.test_filename, 5, "excluded_main_func")
        self.logic.maybe_unwanted_frame(frame_excluded_main)
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded_main))
        first_unwanted_id = self.logic._local.bad_frame

        frame_excluded_helper = self._create_mock_frame(
            self.test_filename, 2, "excluded_helper_func_internal", f_back=frame_excluded_main
        )
        self.logic.maybe_unwanted_frame(frame_excluded_helper)  # This should not overwrite the first one
        self.assertTrue(self.logic.inside_unwanted_frame(frame_excluded_helper))
        self.assertEqual(self.logic._local.bad_frame, first_unwanted_id)  # bad_frame remains the first excluded one

        # Ensure leave_unwanted_frame only clears if it's the *original* bad frame
        self.logic.leave_unwanted_frame(frame_excluded_helper)
        self.assertTrue(
            self.logic.inside_unwanted_frame(frame_excluded_main)
        )  # Still unwanted because helper is not the *original* bad frame
        self.assertEqual(self.logic._local.bad_frame, first_unwanted_id)

        self.logic.leave_unwanted_frame(frame_excluded_main)
        self.assertFalse(self.logic.inside_unwanted_frame(frame_excluded_main))  # Now truly not unwanted
        self.assertIsNone(self.logic._local.bad_frame)

    def test_stop_iteration_not_logged_on_send(self):
        """Test that StopIteration raised by SEND is not logged as an exception."""
        frame = self._create_mock_frame(self.test_filename, 10, "gen_func")
        frame.f_code.co_name = "gen_func"
        frame.f_code.co_filename = self.test_filename
        frame.f_lineno = 10
        frame.f_lasti = 42  # Offset of the SEND instruction

        # Mock dis.get_instructions to return a SEND instruction at offset 42
        original_get_instructions = dis.get_instructions

        def mock_get_instructions(code):
            instr = MagicMock()
            instr.offset = 42
            instr.opname = "SEND"
            return [instr]

        dis.get_instructions = mock_get_instructions
        try:
            self.logic.handle_exception(StopIteration, StopIteration(), frame)
            # Should not add anything to buffer or exception_chain
            self.assertEqual(len(self.logic.exception_chain), 0)
            if sys.version_info >= (3, 12):
                self.assertEqual(len(self.logic.exception_chain), 0)
        finally:
            dis.get_instructions = original_get_instructions

    def test_stop_async_iteration_not_logged_on_end_async_for(self):
        """Test that StopAsyncIteration raised by END_ASYNC_FOR is not logged."""
        frame = self._create_mock_frame(self.test_filename, 15, "async_gen_func")
        frame.f_code.co_name = "async_gen_func"
        frame.f_code.co_filename = self.test_filename
        frame.f_lineno = 15
        frame.f_lasti = 88  # Offset of the END_ASYNC_FOR instruction

        original_get_instructions = dis.get_instructions

        def mock_get_instructions(code):
            instr = MagicMock()
            instr.offset = 88
            instr.opname = "END_ASYNC_FOR"
            return [instr]

        dis.get_instructions = mock_get_instructions
        try:
            self.logic.handle_exception(StopAsyncIteration, StopAsyncIteration(), frame)
            self.assertEqual(len(self.logic.exception_chain), 0)
            if sys.version_info >= (3, 12):
                self.assertEqual(len(self.logic.exception_chain), 0)
        finally:
            dis.get_instructions = original_get_instructions

    def test_try_finally_reraise_exception_chain(self):
        """Test that exceptions in try/finally blocks are properly tracked."""
        frame = self._create_mock_frame(self.test_filename, 20, "try_finally_func")
        frame.f_code.co_name = "try_finally_func"
        frame.f_code.co_filename = self.test_filename
        frame.f_lineno = 20

        # Simulate exception in try block
        self.logic.handle_exception(ValueError, ValueError("test error"), frame)

        if sys.version_info >= (3, 12):
            self.assertEqual(len(self.logic.exception_chain), 1)
            logged = self.logic.exception_chain[0]
            self.assertEqual(logged[0]["data"]["exc_type"], "ValueError")
            self.assertEqual(logged[0]["data"]["exc_value"], "test error")
        else:
            self.assertEqual(len(self.logic._buffer), 1)
            logged = self.logic._buffer[0]
            self.assertEqual(logged[0]["data"]["exc_type"], "ValueError")
            self.assertEqual(logged[0]["data"]["exc_value"], "test error")

    def test_handle_c_call(self):
        """Test handling of C-function call events."""
        mock_callable_obj = MagicMock()
        mock_callable_obj.__name__ = "len"
        mock_arg0 = "test_string"

        # Simulate a Python frame calling the C function
        parent_frame = self._create_mock_frame(self.test_filename, 15, "my_python_func")
        self.logic._local.stack_depth = 0  # Start at base depth

        self.logic.handle_c_call(parent_frame, mock_callable_obj, mock_arg0)

        self.logic._add_to_buffer.assert_called_once()
        log_data = self.logic._add_to_buffer.call_args[0][0]
        color_type = self.logic._add_to_buffer.call_args[0][1]

        self.assertIn("↘ C-CALL len at", log_data["template"])
        self.assertEqual(log_data["data"]["func_name"], "len")
        self.assertEqual(log_data["data"]["filename"], self.logic._get_formatted_filename(self.test_filename))
        self.assertEqual(log_data["data"]["lineno"], 15)
        self.assertEqual(color_type, TraceTypes.COLOR_TRACE)
        self.assertEqual(self.logic._local.stack_depth, 1)  # Stack depth increases

    def test_handle_c_return(self):
        """Test handling of C-function return events."""
        mock_callable_obj = MagicMock()
        mock_callable_obj.__name__ = "len"
        mock_retval = 5

        # Simulate a Python frame receiving return from C function
        parent_frame = self._create_mock_frame(self.test_filename, 15, "my_python_func")
        self.logic._local.stack_depth = 1  # Simulate being inside C call

        self.logic.handle_c_return(parent_frame, mock_callable_obj, mock_retval)

        self.logic._add_to_buffer.assert_called_once()
        log_data = self.logic._add_to_buffer.call_args[0][0]
        color_type = self.logic._add_to_buffer.call_args[0][1]

        self.assertIn("↗ C-RETURN from len -> 5", log_data["template"])
        self.assertEqual(log_data["data"]["func_name"], "len")
        self.assertEqual(log_data["data"]["return_value"], "5")
        self.assertEqual(color_type, TraceTypes.COLOR_TRACE)
        self.assertEqual(self.logic._local.stack_depth, 0)  # Stack depth decreases

    def test_handle_c_raise(self):
        """Test handling of C-function raise events."""
        mock_callable_obj = MagicMock()
        mock_callable_obj.__name__ = "open"
        mock_exception = FileNotFoundError("file not found")

        # Simulate a Python frame receiving exception from C function
        parent_frame = self._create_mock_frame(self.test_filename, 20, "my_python_func")
        self.logic._local.stack_depth = 1  # Simulate being inside C call

        self.logic.handle_c_raise(parent_frame, mock_callable_obj, mock_exception)

        self.logic._add_to_buffer.assert_called_once()
        log_data = self.logic._add_to_buffer.call_args[0][0]
        color_type = self.logic._add_to_buffer.call_args[0][1]

        self.assertIn("⚠ C-RAISE from open -> FileNotFoundError: file not found", log_data["template"])
        self.assertEqual(log_data["data"]["func_name"], "open")
        self.assertEqual(log_data["data"]["exc_type"], "FileNotFoundError")
        self.assertEqual(log_data["data"]["exc_value"], "file not found")
        self.assertEqual(color_type, TraceTypes.COLOR_EXCEPTION)
        self.assertEqual(self.logic._local.stack_depth, 0)  # Stack depth decreases


@unittest.skipUnless(sys.version_info >= (3, 12), "sys.monitoring is only available in Python 3.12+")
class TestSysMonitoringTraceDispatcher(BaseTracerTest):
    """Tests for SysMonitoringTraceDispatcher using sys.monitoring mocks."""

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
        self.mock_monitoring.events.CALL = 1024  # C-call event
        self.mock_monitoring.events.C_RETURN = 2048  # C-return event
        self.mock_monitoring.events.C_RAISE = 4096  # C-raise event
        self.mock_monitoring.events.NO_EVENTS = 0
        self.mock_monitoring.DISABLE = "DISABLE"
        self.mock_monitoring.MISSING = MagicMock()  # Represents sys.monitoring.MISSING for arg0

        self.dispatcher.monitoring_module = self.mock_monitoring
        self.mock_logic = MagicMock(spec=TraceLogic)
        self.dispatcher._logic = self.mock_logic
        self.mock_logic.inside_unwanted_frame.return_value = False

    def test_register_tool(self):
        """Test that the tool is registered correctly with sys.monitoring."""
        self.mock_monitoring.get_tool.side_effect = [None, "ToolInUse", None]  # First available tool ID is 0, then 2
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
            | self.mock_monitoring.events.CALL  # C call
            | self.mock_monitoring.events.C_RETURN  # C return
            | self.mock_monitoring.events.C_RAISE  # C raise
        )
        self.mock_monitoring.set_events.assert_called_once_with(0, expected_events)

        # Check all expected callbacks are registered
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.PY_START, self.dispatcher.handle_py_start
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.PY_RETURN, self.dispatcher.handle_py_return
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.LINE, self.dispatcher.handle_line
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.RAISE, self.dispatcher.handle_raise
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.EXCEPTION_HANDLED, self.dispatcher.handle_exception_handled
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.PY_YIELD, self.dispatcher.handle_py_yield
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.PY_UNWIND, self.dispatcher.handle_py_unwind
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.PY_THROW, self.dispatcher.handle_py_throw
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.RERAISE, self.dispatcher._handle_reraise
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.PY_RESUME, self.dispatcher.handle_py_resume
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.CALL, self.dispatcher.handle_call
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.C_RETURN, self.dispatcher.handle_c_return
        )
        self.mock_monitoring.register_callback.assert_any_call(
            0, self.mock_monitoring.events.C_RAISE, self.dispatcher.handle_c_raise
        )

    def test_unregister_tool(self):
        """Test that the tool is unregistered correctly."""
        # First, register it so we can unregister
        self.dispatcher._tool_id = 1
        self.dispatcher._registered = True
        self.dispatcher._unregister_tool()

        self.mock_monitoring.set_events.assert_called_once_with(1, self.mock_monitoring.events.NO_EVENTS)
        self.mock_monitoring.free_tool_id.assert_called_once_with(1)
        self.assertFalse(self.dispatcher._registered)
        self.assertIsNone(self.dispatcher._tool_id)
        # Verify all callbacks are set to None
        self.mock_monitoring.register_callback.assert_any_call(1, self.mock_monitoring.events.PY_START, None)
        self.mock_monitoring.register_callback.assert_any_call(1, self.mock_monitoring.events.PY_RETURN, None)
        self.mock_monitoring.register_callback.assert_any_call(1, self.mock_monitoring.events.LINE, None)
        self.mock_monitoring.register_callback.assert_any_call(1, self.mock_monitoring.events.RAISE, None)
        self.mock_monitoring.register_callback.assert_any_call(1, self.mock_monitoring.events.EXCEPTION_HANDLED, None)
        self.mock_monitoring.register_callback.assert_any_call(1, self.mock_monitoring.events.CALL, None)
        self.mock_monitoring.register_callback.assert_any_call(1, self.mock_monitoring.events.C_RETURN, None)
        self.mock_monitoring.register_callback.assert_any_call(1, self.mock_monitoring.events.C_RAISE, None)

    @patch("sys._getframe")
    def test_handle_py_start_target_frame(self, mock_getframe):
        """Test PY_START for a target Python frame."""
        mock_frame = self._create_mock_frame(self.test_filename, 10, "target_func")
        mock_getframe.return_value = mock_frame

        # Simulate being outside an unwanted frame
        self.mock_logic.inside_unwanted_frame.return_value = False

        result = self.dispatcher.handle_py_start(MagicMock(), 0)

        self.mock_logic.maybe_unwanted_frame.assert_called_once_with(mock_frame)
        self.mock_logic.handle_call.assert_called_once_with(mock_frame)
        self.assertIn(mock_frame, self.dispatcher.active_frames)
        self.assertIsNone(result)  # Should return None to continue tracing

    @patch("sys._getframe")
    def test_handle_py_start_non_target_frame(self, mock_getframe):
        """Test PY_START for a non-target Python frame."""
        mock_frame = self._create_mock_frame("non_target.py", 10, "non_target_func")
        mock_getframe.return_value = mock_frame
        self.mock_logic.inside_unwanted_frame.return_value = False

        result = self.dispatcher.handle_py_start(MagicMock(), 0)

        self.mock_logic.maybe_unwanted_frame.assert_called_once_with(
            mock_frame
        )  # maybe_unwanted_frame is always called
        self.mock_logic.handle_call.assert_not_called()
        self.assertNotIn(mock_frame, self.dispatcher.active_frames)
        self.assertEqual(result, self.mock_monitoring.DISABLE)  # Should disable tracing for this frame

    @patch("sys._getframe")
    def test_handle_py_return(self, mock_getframe):
        """Test PY_RETURN for an active Python frame."""
        mock_frame = self._create_mock_frame(self.test_filename, 10, "target_func")
        mock_getframe.return_value = mock_frame
        self.dispatcher.active_frames.add(mock_frame)  # Make it an active frame
        self.mock_logic.inside_unwanted_frame.return_value = False

        self.dispatcher.handle_py_return(MagicMock(), 0, "retval")

        self.mock_logic.leave_unwanted_frame.assert_called_once_with(mock_frame)
        self.mock_logic.handle_return.assert_called_once_with(mock_frame, "retval")
        self.mock_logic.frame_cleanup.assert_called_once_with(mock_frame)
        self.assertNotIn(mock_frame, self.dispatcher.active_frames)

    @patch("sys._getframe")
    def test_handle_line(self, mock_getframe):
        """Test LINE for an active Python frame."""
        mock_frame = self._create_mock_frame(self.test_filename, 15, "target_func")
        mock_getframe.return_value = mock_frame
        self.dispatcher.active_frames.add(mock_frame)

        self.dispatcher.handle_line(MagicMock(), 15)

        self.mock_logic.handle_line.assert_called_once_with(mock_frame)

    @patch("sys._getframe")
    def test_handle_raise(self, mock_getframe):
        """Test RAISE for an active Python frame."""
        mock_frame = self._create_mock_frame(self.test_filename, 20, "target_func")
        mock_getframe.return_value = mock_frame
        self.dispatcher.active_frames.add(mock_frame)
        exc = ValueError("Test Error")

        self.dispatcher.handle_raise(MagicMock(), 0, exc)

        self.mock_logic.handle_exception.assert_called_once_with(type(exc), exc, mock_frame)

    @patch("sys._getframe")
    def test_handle_c_call_python_callable(self, mock_getframe):
        """Test CALL event for a Python callable (should be ignored by handle_call)."""
        mock_code = MagicMock()
        mock_callable = MagicMock(__code__=mock_code)  # Has __code__ -> is Python function
        mock_arg0 = self.mock_monitoring.MISSING  # Not relevant for this test
        mock_frame = self._create_mock_frame(self.test_filename, 5, "caller_func")
        mock_getframe.return_value = mock_frame

        result = self.dispatcher.handle_call(MagicMock(), 0, mock_callable, mock_arg0)

        self.mock_logic.handle_c_call.assert_not_called()
        self.assertIsNone(result)  # Should not disable, as PY_START will handle it

    @patch("sys._getframe")
    def test_handle_c_call_c_callable_target_frame(self, mock_getframe):
        """Test CALL event for a C callable when caller is a target frame."""
        mock_callable = MagicMock(__name__="len", __code__=None)  # No __code__ -> is C function
        mock_arg0 = "some_string"
        mock_frame = self._create_mock_frame(self.test_filename, 5, "caller_func")
        mock_getframe.return_value = mock_frame

        # Ensure the dispatcher considers this frame a target
        self.dispatcher.path_cache[mock_frame.f_code.co_filename] = True

        self.dispatcher.handle_call(MagicMock(), 0, mock_callable, mock_arg0)

        self.mock_logic.handle_c_call.assert_called_once_with(mock_frame, mock_callable, mock_arg0)

    @patch("sys._getframe")
    def test_handle_c_call_c_callable_non_target_frame(self, mock_getframe):
        """Test CALL event for a C callable when caller is NOT a target frame."""
        mock_callable = MagicMock(__name__="len", __code__=None)
        mock_arg0 = "some_string"
        mock_frame = self._create_mock_frame("non_target.py", 5, "caller_func")  # Non-target filename
        mock_getframe.return_value = mock_frame

        # Ensure the dispatcher considers this frame NOT a target
        self.dispatcher.path_cache[mock_frame.f_code.co_filename] = False

        self.dispatcher.handle_call(MagicMock(), 0, mock_callable, mock_arg0)

        self.mock_logic.handle_c_call.assert_not_called()

    @patch("sys._getframe")
    def test_handle_c_return(self, mock_getframe):
        """Test C_RETURN event."""
        mock_callable = MagicMock(spec=len, __name__="len")
        mock_retval = 5
        mock_frame = self._create_mock_frame(self.test_filename, 5, "caller_func")
        mock_getframe.return_value = mock_frame

        self.dispatcher.handle_c_return(MagicMock(), 0, mock_callable, mock_retval)

        self.mock_logic.handle_c_return.assert_called_once_with(mock_frame, mock_callable, mock_retval)

    @patch("sys._getframe")
    def test_handle_c_raise(self, mock_getframe):
        """Test C_RAISE event."""
        mock_callable = MagicMock(spec=open, __name__="open")
        mock_exception = FileNotFoundError("file not found")
        mock_frame = self._create_mock_frame(self.test_filename, 5, "caller_func")
        mock_getframe.return_value = mock_frame

        self.dispatcher.handle_c_raise(MagicMock(), 0, mock_callable, mock_exception)

        self.mock_logic.handle_c_raise.assert_called_once_with(mock_frame, mock_callable, mock_exception)


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
        report_path = self.test_dir / "render_test.html"
        self.renderer.add_raw_message({"template": "test message", "data": {}}, "call")
        self.renderer.save_to_file(str(report_path), False)

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
            tracer.stop()

        # Check if logs were produced by inspecting the tracer's internal state.
        self.assertGreater(len(tracer._logic._html_render._messages), 0)

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
                # Call a C function for success
                my_list = [1, 2, 3]
                list_len = len(my_list)
                print(f"Len: {list_len}") # This line will generate a C-CALL for len
            
                # Call a C function that raises an exception
                try:
                    with open("non_existent_file.txt", "r") as f:
                        f.read()
                except FileNotFoundError:
                    print("Caught FileNotFoundError")
            
                # Another successful C function call
                data = {'a': 1, 'b': 2}
                items = data.items()
                print(f"Items: {items}")

                # Call a C function with arg0 MISSING example
                # sys.getsizeof is a builtin, its arg0 will be MISSING
                size = sys.getsizeof(10)
                print(f"Size of 10: {size}")

            if __name__ == "__main__":
                call_c_functions()
            """
        )
        script_path = self.test_dir / "c_call_test_script.py"
        script_path.write_text(target_script_content, encoding="utf-8")

        # Define the log file path relative to the debugger.tracer_main execution
        log_file_path = self.test_dir.parent / "logs" / f"{script_path.stem}.log"
        if log_file_path.exists():
            log_file_path.unlink()  # Clear previous logs

        # Run the tracer_main.py as a subprocess with --trace-c-calls
        # Use python -m to ensure the correct module is found
        import subprocess

        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "debugger.tracer_main",
                "--trace-c-calls",
                "--report-name",
                f"{script_path.stem}.html",  # Ensure report name aligns with log_file_path derivation
                str(script_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        # Print subprocess output for debugging if test fails
        if process.returncode != 0:
            print(f"Subprocess stdout:\n{process.stdout}")
            print(f"Subprocess stderr:\n{process.stderr}")

        self.assertEqual(process.returncode, 0, f"Tracer process exited with error code {process.returncode}")
        self.assertTrue(log_file_path.exists(), f"Log file not found at {log_file_path}")

        # Read and verify log contents
        log_content = log_file_path.read_text(encoding="utf-8")

        # Expected C-CALL and C-RETURN for len()
        self.assertIn("↘ C-CALL len at", log_content)
        self.assertIn("↗ C-RETURN from len -> 3", log_content)

        # Expected C-RAISE for open()
        self.assertIn(
            "⚠ C-RAISE from open -> FileNotFoundError: [Errno 2] No such file or directory: 'non_existent_file.txt'",
            log_content,
        )

        # Expected C-CALL and C-RETURN for dict.items()
        self.assertIn("↘ C-CALL dict.items at", log_content)
        self.assertIn("↗ C-RETURN from dict.items -> dict_items", log_content)

        # Expected C-CALL for sys.getsizeof()
        self.assertIn("↘ C-CALL sys.getsizeof at", log_content)
        # The return value might vary slightly based on Python version, so just check call
        self.assertIn("↗ C-RETURN from sys.getsizeof ->", log_content)

        # Verify HTML report is generated
        html_report_path = self.test_dir.parent / "logs" / f"{script_path.stem}.html"
        self.assertTrue(html_report_path.exists(), f"HTML report not found at {html_report_path}")

    @unittest.skipUnless(sys.version_info >= (3, 12), "C function tracing requires Python 3.12+")
    def test_e2e_c_calls_tracing_disabled(self):
        """
        End-to-end test to ensure C function tracing is DISABLED when flag is not set.
        """
        target_script_content = dedent(
            """
            import os
            
            def call_c_functions():
                my_list = [1, 2, 3]
                list_len = len(my_list)
                
                try:
                    with open("non_existent_file.txt", "r") as f:
                        f.read()
                except FileNotFoundError:
                    pass

            if __name__ == "__main__":
                call_c_functions()
            """
        )
        script_path = self.test_dir / "no_c_call_test_script.py"
        script_path.write_text(target_script_content, encoding="utf-8")

        log_file_path = self.test_dir.parent / "logs" / f"{script_path.stem}.log"
        if log_file_path.exists():
            log_file_path.unlink()

        # Run the tracer_main.py as a subprocess WITHOUT --trace-c-calls
        import subprocess

        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "debugger.tracer_main",
                "--report-name",
                f"{script_path.stem}.html",
                str(script_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if process.returncode != 0:
            print(f"Subprocess stdout:\n{process.stdout}")
            print(f"Subprocess stderr:\n{process.stderr}")

        self.assertEqual(process.returncode, 0, f"Tracer process exited with error code {process.returncode}")
        self.assertTrue(log_file_path.exists(), f"Log file not found at {log_file_path}")

        log_content = log_file_path.read_text(encoding="utf-8")

        # Assert that no C-CALL, C-RETURN, C-RAISE logs are present
        self.assertNotIn("↘ C-CALL", log_content)
        self.assertNotIn("↗ C-RETURN", log_content)
        self.assertNotIn("⚠ C-RAISE", log_content)


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
