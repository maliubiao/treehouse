import dis
import html
import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from debugger.tracer import (
    _COLORS,
    _INDENT,
    _MAX_VALUE_LENGTH,
    CallTreeHtmlRender,
    TraceConfig,
    TraceDispatcher,
    TraceLogic,
    color_wrap,
    truncate_repr_value,
)


class TestTruncateReprValue(unittest.TestCase):
    def test_truncate_long_string(self):
        long_str = "a" * (_MAX_VALUE_LENGTH + 100)
        result = truncate_repr_value(long_str)
        self.assertTrue(len(result) <= _MAX_VALUE_LENGTH + 3)
        self.assertTrue(result.endswith("..."))

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
        self.assertIn("...", result)
        self.assertIn("TestObj", result)


class TestTraceConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test_config.yml"
        self.sample_config = {
            "target_files": ["*.py", "test_*.py"],
            "line_ranges": {"test.py": [(1, 10), (20, 30)]},
            "capture_vars": ["x", "y.z"],
        }
        with open(self.config_file, "w") as f:
            json.dump(self.sample_config, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_from_yaml(self):
        config = TraceConfig.from_yaml(self.config_file)
        self.assertEqual(config.target_files, self.sample_config["target_files"])
        self.assertEqual(len(config.line_ranges), 1)
        self.assertEqual(config.capture_vars, self.sample_config["capture_vars"])

    def test_match_filename(self):
        config = TraceConfig(target_files=["*.py"])
        self.assertTrue(config.match_filename("test.py"))
        self.assertTrue(config.match_filename("/path/to/test.py"))
        self.assertFalse(config.match_filename("test.txt"))

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


class TestTraceDispatcher(unittest.TestCase):
    def setUp(self):
        self.test_file = Path(__file__)
        self.config = TraceConfig(target_files=["*test_*.py"])
        self.dispatcher = TraceDispatcher(self.test_file, self.config)

    def test_is_target_frame(self):
        frame = inspect.currentframe()
        self.assertTrue(self.dispatcher.is_target_frame(frame))

        mock_frame = Mock()
        mock_frame.f_code.co_filename = "not_target.py"
        self.assertFalse(self.dispatcher.is_target_frame(mock_frame))

    def test_trace_dispatch(self):
        frame = inspect.currentframe()

        # Test call event
        tracer = self.dispatcher.trace_dispatch(frame, "call", None)
        self.assertEqual(tracer, self.dispatcher.trace_dispatch)

        # Test line event
        tracer = self.dispatcher.trace_dispatch(frame, "line", None)
        self.assertEqual(tracer, self.dispatcher.trace_dispatch)

        # Test return event
        tracer = self.dispatcher.trace_dispatch(frame, "return", None)
        self.assertEqual(tracer, self.dispatcher.trace_dispatch)

        # Test exception event
        tracer = self.dispatcher.trace_dispatch(frame, "exception", None)
        self.assertEqual(tracer, self.dispatcher.trace_dispatch)


class TestTraceLogic(unittest.TestCase):
    def setUp(self):
        self.config = TraceConfig()
        self.logic = TraceLogic(self.config)
        self.frame = inspect.currentframe()

    def test_handle_call(self):
        self.logic.handle_call(self.frame)
        self.assertEqual(self.logic.stack_depth, 1)

    def test_handle_return(self):
        self.logic.stack_depth = 1
        self.logic.handle_return(self.frame, "test")
        self.assertEqual(self.logic.stack_depth, 0)

    def test_handle_line(self):
        self.logic.stack_depth = 1
        self.logic.handle_line(self.frame)

    def test_handle_exception(self):
        try:
            raise ValueError("test error")
        except ValueError as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.logic.handle_exception(exc_type, exc_value, exc_traceback)

    def test_capture_variables(self):
        frame = inspect.currentframe()
        x = 42
        y = {"z": "test"}
        self.config.capture_vars = ["x", "y['z']"]
        result = self.logic.capture_variables(frame)
        self.assertEqual(result["x"], "42")
        self.assertEqual(result["y['z']"], "'test'")

    def test_output_handlers(self):
        test_msg = {"template": "test {value}", "data": {"value": 42}}

        # Test console output
        with patch("builtins.print") as mock_print:
            self.logic._console_output(test_msg, "call")
            mock_print.assert_called_once()

        # Test file output
        with tempfile.NamedTemporaryFile() as tmp:
            self.logic.enable_output("file", filename=tmp.name)
            self.logic._file_output(test_msg, None)
            self.logic.disable_output("file")
            with open(tmp.name) as f:
                content = f.read()
            self.assertIn("test 42", content)


class TestCallTreeHtmlRender(unittest.TestCase):
    def setUp(self):
        self.config = TraceConfig()
        self.logic = TraceLogic(self.config)
        self.render = CallTreeHtmlRender(self.logic)

    def test_add_message(self):
        self.render.add_message("test message", "call")
        self.assertEqual(len(self.render._messages), 1)

    def test_add_stack_variable(self):
        frame = inspect.currentframe()
        frame_id = 1
        filename = "test.py"
        lineno = 42
        opcode = dis.opmap["LOAD_NAME"]
        var_name = "x"
        value = 42
        self.render.add_stack_variable_create(frame_id, filename, lineno, opcode, var_name, value)
        key = (frame_id, filename, lineno)
        self.assertIn(key, self.render._stack_variables)

    def test_generate_html(self):
        self.render.add_message("test message", "call")
        html = self.render.generate_html()
        self.assertIn("test&nbsp;message", html)
        self.assertIn("Python Trace Report", html)

    def test_save_to_file(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            tmp.close()
            self.render.add_message("test message", "call")
            self.render.save_to_file(str(Path(tmp.name)))
            with open(tmp.name) as f:
                content = f.read()
            self.assertIn("test&nbsp;message", content)
            os.unlink(tmp.name)


class TestColorWrap(unittest.TestCase):
    def test_color_wrap(self):
        colored = color_wrap("test", "call")
        self.assertTrue(colored.startswith(_COLORS["call"]))
        self.assertTrue(colored.endswith(_COLORS["reset"]))

    def test_color_wrap_no_tty(self):
        with patch("sys.stdout.isatty", return_value=False):
            colored = color_wrap("test", "call")
            self.assertEqual(colored, "test")


class TestIntegration(unittest.TestCase):
    def test_full_trace_cycle(self):
        config = TraceConfig(target_files=["test_*.py"])
        dispatcher = TraceDispatcher(__file__, config)

        # Start tracing
        dispatcher.start()

        # Execute some code
        def test_func(x):
            y = x + 1
            return y * 2

        result = test_func(5)
        self.assertEqual(result, 12)

        # Stop tracing
        dispatcher.stop()

    def test_event_coverage(self):
        config = TraceConfig(target_files=["test_*.py"])
        dispatcher = TraceDispatcher(__file__, config)
        logic = TraceLogic(config)

        # Test call event
        frame = inspect.currentframe()
        logic.handle_call(frame)
        self.assertEqual(logic.stack_depth, 1)

        # Test line event
        logic.handle_line(frame)
        self.assertEqual(logic.stack_depth, 1)

        # Test return event
        logic.handle_return(frame, "test")
        self.assertEqual(logic.stack_depth, 0)

        # Test exception event
        try:
            raise ValueError("test error")
        except ValueError as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            logic.handle_exception(exc_type, exc_value, exc_traceback)

        # Test variable capture
        x = 42
        y = {"z": "test"}
        config.capture_vars = ["x", "y['z']"]
        result = logic.capture_variables(frame)
        self.assertEqual(result["x"], "42")
        self.assertEqual(result["y['z']"], "'test'")

        # Test output handlers
        test_msg = {"template": "test {value}", "data": {"value": 42}}
        with patch("builtins.print") as mock_print:
            logic._console_output(test_msg, "call")
            mock_print.assert_called_once()

        with tempfile.NamedTemporaryFile() as tmp:
            logic.enable_output("file", filename=tmp.name)
            logic._file_output(test_msg, None)
            logic.disable_output("file")
            with open(tmp.name) as f:
                content = f.read()
            self.assertIn("test 42", content)


if __name__ == "__main__":
    unittest.main()
