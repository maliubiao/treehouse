import dis
import importlib.util
import inspect
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

# Add project root to path to allow importing debugger modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from debugger.tracer import (
    _MAX_VALUE_LENGTH,
    CallTreeHtmlRender,
    SysMonitoringTraceDispatcher,
    TraceConfig,
    TraceDispatcher,
    TraceLogExtractor,
    TraceLogic,
    start_trace,
    truncate_repr_value,
)

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
            exec(code_string, ns)
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
            target_func(*args, **kwargs)
        finally:
            sys.settrace(None)

        if frame is None:
            self.fail(f"Failed to create frame for function '{func_name}'")

        return frame


class TestTruncateReprValue(unittest.TestCase):
    """Tests for the truncate_repr_value utility function."""

    def test_truncate_long_string(self):
        long_str = "a" * (_MAX_VALUE_LENGTH + 100)
        result = truncate_repr_value(long_str)
        # 修正断言：计算实际后缀长度
        suffix = f"... (total length: {len(long_str)})"
        self.assertTrue(len(result) <= _MAX_VALUE_LENGTH + len(suffix))
        self.assertTrue(result.endswith(suffix))  # 同步修正结尾检查

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
        self.assertEqual(config.target_files, [])
        self.assertTrue(config.ignore_system_paths)
        self.assertFalse(config.enable_var_trace)

    def test_initialization_with_params(self):
        config = TraceConfig(target_files=["*.py"], enable_var_trace=True, ignore_system_paths=False)
        self.assertEqual(config.target_files, ["*.py"])
        self.assertFalse(config.ignore_system_paths)
        self.assertTrue(config.enable_var_trace)

    def test_from_yaml(self):
        config_file = self.test_dir / "test_config.yml"
        sample_config = {
            "target_files": ["*.py", "test_*.py"],
            "line_ranges": {"test.py": [(1, 10), (20, 30)]},
            "capture_vars": ["x", "y.z"],
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(sample_config, f)

        config = TraceConfig.from_yaml(config_file)
        self.assertEqual(config.target_files, sample_config["target_files"])
        self.assertEqual(len(config.line_ranges), 1)
        self.assertEqual(config.capture_vars, sample_config["capture_vars"])

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
        line_ranges = {"test.py": [(1, 3), (5, 7)]}
        config = TraceConfig(line_ranges=line_ranges)
        parsed = config.line_ranges
        self.assertEqual(len(parsed), 1)
        self.assertIn(str(Path("test.py").resolve()), parsed)
        self.assertEqual(parsed[str(Path("test.py").resolve())], {1, 2, 3, 5, 6, 7})

    def test_validate_expressions(self):
        valid_exprs = ["x", "x.y", "x[0]"]
        invalid_exprs = ["x.", "1 + ", "x = y"]

        config = TraceConfig(capture_vars=valid_exprs)
        self.assertTrue(config.validate())

        t = TraceConfig(capture_vars=invalid_exprs)
        self.assertFalse(t.validate())


class TestTraceLogic(BaseTracerTest):
    """Tests for the core TraceLogic."""

    class _StopTracing(Exception):
        """Custom exception to stop tracing immediately after capturing a frame."""

        pass

    def setUp(self):
        super().setUp()
        self.config = TraceConfig(target_files=[__file__])
        self.logic = TraceLogic(self.config)
        # Mock the output buffer to inspect what's being logged
        self.logic._add_to_buffer = MagicMock()

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
        self.assertEqual(self.logic.stack_depth, 1)

    def test_handle_return(self):
        frame = self._get_frame_at(sample_function, 5, 3, event_type="return")
        self.logic.stack_depth = 1  # Simulate being inside a call
        self.logic.handle_return(frame, (16, "large"))

        self.logic._add_to_buffer.assert_called_once()
        call_args = self.logic._add_to_buffer.call_args[0]
        log_data = call_args[0]

        self.assertIn("↗ RETURN", log_data["template"])
        self.assertIn("→ (16, 'large')", log_data["template"].format(**log_data["data"]))
        self.assertEqual(self.logic.stack_depth, 0)

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

        # Expect two calls: one for the line itself, one for the debug statement.
        # The first call is for the line log, the second is for the trace comment.
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

        self.logic.stack_depth = 1
        self.logic.handle_exception(ValueError, exc_value, frame)

        self.assertEqual(len(self.logic.exception_chain), 1)
        log_data, _ = self.logic.exception_chain[0]

        self.assertIn("⚠ EXCEPTION", log_data["template"])
        self.assertIn("ValueError: x cannot be zero", log_data["template"].format(**log_data["data"]))
        self.assertEqual(self.logic.stack_depth, 0)

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


class TestTraceDispatcher(BaseTracerTest):
    """Tests for the TraceDispatcher."""

    def setUp(self):
        super().setUp()
        self.test_file = Path(__file__)
        self.config = TraceConfig(target_files=[f"*{self.test_file.name}"])
        self.dispatcher = TraceDispatcher(self.test_file, self.config)
        self.mock_logic = MagicMock(spec=TraceLogic)
        self.dispatcher._logic = self.mock_logic

    def test_dispatch_call_event_for_target_frame(self):
        frame = inspect.currentframe()
        self.dispatcher.trace_dispatch(frame, "call", None)
        self.mock_logic.handle_call.assert_called_once()

    def test_dispatch_call_event_for_non_target_frame(self):
        code = "def some_func(): pass"
        frame = self._create_frame_from_code(code, filename="other_file.py", func_name="some_func")
        self.dispatcher.trace_dispatch(frame, "call", None)
        self.mock_logic.handle_call.assert_not_called()

    def test_dispatch_line_event_for_active_frame(self):
        frame = inspect.currentframe()
        self.dispatcher.trace_dispatch(frame, "call", None)  # Activate the frame
        self.dispatcher.trace_dispatch(frame, "line", None)
        self.mock_logic.handle_line.assert_called_once()

    def test_dispatch_return_event_removes_active_frame(self):
        frame = inspect.currentframe()
        self.dispatcher.trace_dispatch(frame, "call", None)
        self.assertTrue(frame in self.dispatcher.active_frames)
        self.dispatcher.trace_dispatch(frame, "return", "some_value")
        self.assertFalse(frame in self.dispatcher.active_frames)
        self.mock_logic.handle_return.assert_called_once()

    def test_none_frame(self):
        self.assertFalse(self.dispatcher.is_target_frame(None))

    def test_path_caching(self):
        code = "def cache_test_func(): pass"
        filename = "test_cache.py"
        frame = self._create_frame_from_code(code, filename=filename, func_name="cache_test_func")

        self.dispatcher.path_cache.clear()
        self.dispatcher.is_target_frame(frame)
        self.assertIn(frame.f_code.co_filename, self.dispatcher.path_cache)

        prev_cache_size = len(self.dispatcher.path_cache)
        self.dispatcher.is_target_frame(frame)
        self.assertEqual(len(self.dispatcher.path_cache), prev_cache_size)

    def test_invalid_co_filename(self):
        # Instead of patching a real frame's read-only attribute, which raises
        # an AttributeError, we create a mock object to simulate the condition.
        mock_frame = MagicMock()

        # Case 1: f_code.co_filename is None
        mock_frame.f_code.co_filename = None
        self.assertFalse(self.dispatcher.is_target_frame(mock_frame))

        # Case 2: f_code itself is None
        mock_frame_no_code = MagicMock()
        mock_frame_no_code.f_code = None
        self.assertFalse(self.dispatcher.is_target_frame(mock_frame_no_code))

    def test_non_ascii_filename(self):
        code = "def non_ascii_func(): pass"
        filename = "测试_文件.py"
        frame = self._create_frame_from_code(code, filename=filename, func_name="non_ascii_func")

        self.dispatcher.config.target_files = ["*测试_*.py"]
        self.assertTrue(self.dispatcher.is_target_frame(frame))

    @patch("sys.settrace")
    def test_start_stop(self, mock_settrace):
        self.dispatcher.start()
        mock_settrace.assert_called_with(self.dispatcher.trace_dispatch)
        self.mock_logic.start.assert_called_once()

        self.dispatcher.stop()
        mock_settrace.assert_called_with(None)
        self.mock_logic.stop.assert_called_once()


@unittest.skipIf(sys.version_info < (3, 12), "sys.monitoring requires Python 3.12+")
class TestSysMonitoringDispatcher(BaseTracerTest):
    """Tests for the SysMonitoringTraceDispatcher."""

    def setUp(self):
        super().setUp()
        self.monitoring_patcher = patch.dict("sys.modules", {"sys.monitoring": MagicMock()})
        self.monitoring_patcher.start()
        self.mock_monitoring_module = sys.modules["sys.monitoring"]

        mock_events = MagicMock()
        mock_events.PY_START, mock_events.PY_RETURN, mock_events.LINE, mock_events.RAISE = 1, 2, 8, 16
        mock_events.NO_EVENTS = 0
        for event_name in [
            "PY_YIELD",
            "RERAISE",
            "EXCEPTION_HANDLED",
            "PY_UNWIND",
            "PY_RESUME",
            "PY_THROW",
            "STOP_ITERATION",
        ]:
            setattr(mock_events, event_name, 0)
        self.mock_monitoring_module.monitoring.events = mock_events
        self.mock_monitoring_module.monitoring.get_tool.side_effect = (
            lambda tool_id: None if tool_id == 0 else MagicMock()
        )

        self.config = TraceConfig(target_files=[__file__])
        self.mock_logic = MagicMock(spec=TraceLogic)
        self.dispatcher = SysMonitoringTraceDispatcher(Path(__file__), self.config)
        self.dispatcher.monitoring_module = self.mock_monitoring_module
        self.dispatcher._logic = self.mock_logic

    def tearDown(self):
        self.monitoring_patcher.stop()

    def test_register_tool(self):
        self.mock_monitoring_module.get_tool.side_effect = lambda tool_id: None if tool_id == 0 else MagicMock()
        self.dispatcher._register_tool()
        self.mock_monitoring_module.use_tool_id.assert_called_once_with(0, "PythonDebugger")
        self.mock_monitoring_module.set_events.assert_called_once()

        expected_events = (
            self.mock_monitoring_module.events.PY_START
            | self.mock_monitoring_module.events.PY_RETURN
            | self.mock_monitoring_module.events.PY_YIELD
            | self.mock_monitoring_module.events.LINE
            | self.mock_monitoring_module.events.RAISE
            | self.mock_monitoring_module.events.RERAISE
            | self.mock_monitoring_module.events.EXCEPTION_HANDLED
            | self.mock_monitoring_module.events.PY_UNWIND
            | self.mock_monitoring_module.events.PY_RESUME
            | self.mock_monitoring_module.events.PY_THROW
        )
        self.mock_monitoring_module.set_events.assert_called_with(0, expected_events)

        # 修正断言：实际注册了10个回调，而不是11个
        self.assertEqual(self.mock_monitoring_module.register_callback.call_count, 10)
        self.assertTrue(self.dispatcher._registered)


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
        # 修复: 使用元组索引[1]访问var_name
        self.assertEqual(self.renderer._stack_variables[1][0][1], "x")

    def test_save_to_file(self):
        report_path = self.test_dir / "render_test.html"
        self.renderer.add_raw_message({"template": "test message", "data": {}}, "call")
        self.renderer.save_to_file(str(report_path))

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
            },
            {
                "type": "line",
                "timestamp": "2023-01-01T00:00:01Z",
                "filename": "test_file.py",
                "lineno": 10,
                "frame_id": 100,
                "message": "LINE 10",
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:02Z",
                "filename": "test_file.py",
                "lineno": 5,
                "frame_id": 100,
                "message": "RETURN func1",
            },
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:03Z",
                "filename": "test_file.py",
                "lineno": 20,
                "frame_id": 200,
                "message": "CALL func2",
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:05Z",
                "filename": "test_file.py",
                "lineno": 20,
                "frame_id": 200,
                "message": "RETURN func2",
            },
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:09Z",
                "filename": "test_file.py",
                "lineno": 40,
                "frame_id": 400,
                "message": "CALL func4",
            },
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:10Z",
                "filename": "test_file.py",
                "lineno": 46,
                "frame_id": 400,
                "message": "CALL sub_func",
                "func": "abc",
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:11Z",
                "filename": "test_file.py",
                "lineno": 40,
                "frame_id": 400,
                "message": "RETURN func4",
            },
        ]
        with open(self.log_file, "w", encoding="utf-8") as log_f, open(self.index_file, "w", encoding="utf-8") as idx_f:
            pos = 0
            for log_entry in logs:
                line = json.dumps(log_entry) + "\n"
                log_f.write(line)
                if log_entry["type"] in ("call", "return"):
                    idx_entry = {
                        "type": log_entry["type"],
                        "filename": log_entry["filename"],
                        "lineno": log_entry["lineno"],
                        "frame_id": log_entry["frame_id"],
                        "position": pos,
                        "func": log_entry.get("func", ""),
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


if __name__ == "__main__":
    unittest.main(argv=["first-arg-is-ignored"], exit=False)
