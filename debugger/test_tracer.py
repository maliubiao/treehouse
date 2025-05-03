import dis
import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from debugger.tracer import (
    _MAX_VALUE_LENGTH,
    CallTreeHtmlRender,
    TraceConfig,
    TraceDispatcher,
    TraceLogExtractor,
    TraceLogic,
    truncate_repr_value,
)

_COLORS = {}  # 添加缺失的_COLORS定义


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
        self.assertIn("TestObj.({'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5, 'f': 6})", result)


class TestTraceConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test_config.yml"
        self.sample_config = {
            "target_files": ["*.py", "test_*.py"],
            "line_ranges": {"test.py": [(1, 10), (20, 30)]},
            "capture_vars": ["x", "y.z"],
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
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

    def test_none_frame(self):
        self.assertFalse(self.dispatcher.is_target_frame(None))

    def test_wildcard_matching(self):
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test_tracer_core.py"
        self.assertTrue(self.dispatcher.is_target_frame(mock_frame))

        mock_frame.f_code.co_filename = "unrelated.py"
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

    def test_unknown_event(self):
        frame = inspect.currentframe()
        tracer = self.dispatcher.trace_dispatch(frame, "unknown", None)
        self.assertIsNone(tracer)

    def test_target_files_empty(self):
        empty_config = TraceConfig(target_files=[])
        dispatcher = TraceDispatcher(self.test_file, empty_config)
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "any_file.py"
        self.assertTrue(dispatcher.is_target_frame(mock_frame))

    def test_path_caching(self):
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test_cache.py"
        self.dispatcher.path_cache.clear()

        # First call should populate cache
        self.dispatcher.is_target_frame(mock_frame)
        self.assertIn(mock_frame.f_code.co_filename, self.dispatcher.path_cache)

        # Second call should use cached result
        prev_cache_size = len(self.dispatcher.path_cache)
        self.dispatcher.is_target_frame(mock_frame)
        self.assertEqual(len(self.dispatcher.path_cache), prev_cache_size)

    def test_invalid_co_filename(self):
        mock_frame = Mock()
        mock_frame.f_code.co_filename = None
        self.assertFalse(self.dispatcher.is_target_frame(mock_frame))

        mock_frame.f_code.co_filename = "12345"
        self.assertFalse(self.dispatcher.is_target_frame(mock_frame))

    def test_path_resolution_failure(self):
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "invalid/\x00path.py"
        with patch.object(Path, "resolve", side_effect=ValueError("Test error")):
            result = self.dispatcher.is_target_frame(mock_frame)
        self.assertFalse(result)

    @unittest.skipUnless(sys.platform.startswith("win"), "Requires Windows platform")
    def test_case_insensitive_matching(self):
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "TEST_CASE.PY"
        self.dispatcher.config.target_files = ["test_*.py"]
        self.assertTrue(self.dispatcher.is_target_frame(mock_frame))

    def test_multiple_frame_caching(self):
        mock_frame1 = Mock()
        mock_frame1.f_code.co_filename = "test_cache_a.py"
        mock_frame2 = Mock()
        mock_frame2.f_code.co_filename = "test_cache_b.py"

        for _ in range(3):
            self.dispatcher.is_target_frame(mock_frame1)
            self.dispatcher.is_target_frame(mock_frame2)

        self.assertEqual(self.dispatcher.path_cache.get("test_cache_a.py"), True)
        self.assertEqual(self.dispatcher.path_cache.get("test_cache_b.py"), True)
        self.assertEqual(len(self.dispatcher.path_cache), 2)

    def test_non_ascii_filename(self):
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "测试_文件.py"
        self.dispatcher.config.target_files = ["*测试_*.py"]
        self.assertTrue(self.dispatcher.is_target_frame(mock_frame))


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
            exc_type, exc_value, _ = sys.exc_info()
            self.logic.handle_exception(exc_type, exc_value, sys._getframe())

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
            with open(tmp.name, encoding="utf-8") as f:
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
        frame_id = 1
        opcode = dis.opmap["LOAD_NAME"]
        var_name = "x"
        value = 42
        self.render.add_stack_variable_create(frame_id, opcode, var_name, value)
        self.assertIn(1, self.render._stack_variables)

    def test_generate_html(self):
        self.render.add_message("test message", "call", {})
        generated_html = self.render.generate_html()
        self.assertIn("test&nbsp;message", generated_html)
        self.assertIn("Python Trace Report", generated_html)

    def test_save_to_file(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            tmp.close()
            self.render.add_message("test message", "call", {})
            self.render.save_to_file(str(Path(tmp.name)))
            with open(tmp.name, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("test&nbsp;message", content)
            os.unlink(tmp.name)


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

    def _test_call_events(self, logic):
        frame = inspect.currentframe()
        logic.handle_call(frame)
        self.assertEqual(logic.stack_depth, 1)
        logic.handle_line(frame)
        self.assertEqual(logic.stack_depth, 1)
        logic.handle_return(frame, "test")
        self.assertEqual(logic.stack_depth, 0)

    def _test_exception_handling(self, logic):
        try:
            raise ValueError("test error")
        except ValueError:
            exc_type, exc_value, _ = sys.exc_info()
            logic.handle_exception(exc_type, exc_value, sys._getframe())

    def _test_variable_capture(self, logic: TraceLogic, frame):
        config = logic.config
        config.capture_vars = ["x", "y['z']"]
        result = logic.capture_variables(frame)
        self.assertEqual(result["x"], "42")
        self.assertEqual(result["y['z']"], "'test'")

    def _test_output_handlers(self, logic):
        test_msg = {"template": "test {value}", "data": {"value": 42}}
        with patch("builtins.print") as mock_print:
            logic._console_output(test_msg, "call")
            mock_print.assert_called_once()

        with tempfile.NamedTemporaryFile() as tmp:
            logic.enable_output("file", filename=tmp.name)
            logic._file_output(test_msg, None)
            logic.disable_output("file")
            with open(tmp.name, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("test 42", content)

    def test_event_coverage(self):
        config = TraceConfig(target_files=["test_*.py"])
        logic = TraceLogic(config)
        frame = inspect.currentframe()

        x = 42
        y = {"z": "test"}
        self._test_call_events(logic)
        self._test_exception_handling(logic)
        self._test_variable_capture(logic, frame)
        self._test_output_handlers(logic)


class TestTraceLogExtractor(unittest.TestCase):
    """TraceLogExtractor 测试套件"""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.log_file = self.test_dir / "debug.log"
        self.index_file = self.log_file.with_suffix(".log.index")

        # 生成测试日志和索引
        self._generate_test_logs()

    def _generate_test_logs(self):
        """生成符合真实格式的日志和索引"""
        # 创建 TraceLogic 实例生成标准日志
        config = TraceConfig(target_files=["test_file.py"], report_name="test_report.html", enable_var_trace=True)
        self.trace_logic = TraceLogic(config)
        self.trace_logic.enable_output("file", filename=str(self.log_file))

        # 生成标准日志结构
        logs = [
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:00Z",
                "filename": "test_file.py",
                "lineno": 5,
                "frame_id": 100,
                "message": "CALL func1",
                "data": {},
            },
            {
                "type": "line",
                "timestamp": "2023-01-01T00:00:01Z",
                "filename": "test_file.py",
                "lineno": 10,
                "frame_id": 100,
                "message": "LINE 10",
                "data": {},
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:02Z",
                "filename": "test_file.py",
                "lineno": 5,
                "frame_id": 100,
                "message": "RETURN func1",
                "data": {},
            },
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:03Z",
                "filename": "test_file.py",
                "lineno": 20,
                "frame_id": 200,
                "message": "CALL func2",
                "data": {},
            },
            {
                "type": "line",
                "timestamp": "2023-01-01T00:00:04Z",
                "filename": "test_file.py",
                "lineno": 25,
                "frame_id": 200,
                "message": "LINE 25",
                "data": {},
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:05Z",
                "filename": "test_file.py",
                "lineno": 20,
                "frame_id": 200,
                "message": "RETURN func2",
                "data": {},
            },
            {
                "type": "call",
                "timestamp": "2023-01-01T00:00:06Z",
                "filename": "test_file.py",
                "lineno": 30,
                "frame_id": 300,
                "message": "CALL func3",
                "data": {},
            },
            {
                "type": "line",
                "timestamp": "2023-01-01T00:00:07Z",
                "filename": "test_file.py",
                "lineno": 35,
                "frame_id": 300,
                "message": "LINE 35",
                "data": {},
            },
            {
                "type": "return",
                "timestamp": "2023-01-01T00:00:08Z",
                "filename": "test_file.py",
                "lineno": 30,
                "frame_id": 300,
                "message": "RETURN func3",
                "data": {},
            },
        ]

        # 写入日志并记录位置
        with open(self.log_file, "w", encoding="utf-8") as log_f, open(self.index_file, "w", encoding="utf-8") as idx_f:
            idx_f.write("# 索引文件头\n")
            for log_entry in logs:
                # 记录日志位置
                end_pos = log_f.tell()
                log_entry["position"] = end_pos
                log_f.write(json.dumps(log_entry) + "\n")

                # 生成索引条目
                if log_entry["type"] in ("call", "return"):
                    idx_entry = {
                        "type": log_entry["type"],
                        "filename": log_entry["filename"],
                        "lineno": log_entry["lineno"],
                        "frame_id": log_entry["frame_id"],
                        "position": end_pos,
                    }
                    idx_f.write(json.dumps(idx_entry) + "\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_normal_lookup(self):
        """测试正常查找匹配条目"""
        extractor = TraceLogExtractor(str(self.log_file))
        results = extractor.lookup("test_file.py", 5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0]["message"], "CALL func1")
        self.assertEqual(results[0][-1]["message"], "RETURN func1")
        self._verify_log_positions(results[0], 5)

    def test_multiple_matches(self):
        """测试多条目匹配场景"""
        extractor = TraceLogExtractor(str(self.log_file))
        results = extractor.lookup("test_file.py", 20)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0]["message"], "CALL func2")
        self.assertEqual(results[0][-1]["message"], "RETURN func2")

    def test_cross_frame_extraction(self):
        """测试跨frame_id的日志提取"""
        extractor = TraceLogExtractor(str(self.log_file))
        results = extractor.lookup("test_file.py", 30)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0]["message"], "CALL func3")
        self.assertEqual(results[0][1]["message"], "LINE 35")
        self.assertEqual(results[0][-1]["message"], "RETURN func3")

    def test_index_consistency(self):
        """验证索引条目与日志位置一致性"""
        extractor = TraceLogExtractor(str(self.log_file))

        # 检查有效条目
        valid_entries = [
            (5, 100, "CALL func1", "RETURN func1"),
            (20, 200, "CALL func2", "RETURN func2"),
            (30, 300, "CALL func3", "RETURN func3"),
        ]

        for lineno, frame_id, call_msg, return_msg in valid_entries:
            with self.subTest(lineno=lineno):
                results = extractor.lookup("test_file.py", lineno)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0][0]["message"], call_msg)
                self.assertEqual(results[0][-1]["message"], return_msg)

    def _verify_log_positions(self, log_content, lineno):
        """验证日志位置正确性"""
        with open(self.log_file, "r", encoding="utf-8") as f:
            full_log = f.read()
            for entry in log_content:
                self.assertIn(json.dumps(entry), full_log)

    def test_index_parsing_edge_cases(self):
        """测试索引文件解析边界条件"""
        extractor = TraceLogExtractor(str(self.log_file))

        # 测试无效行号
        results = extractor.lookup("test_file.py", 999)
        self.assertEqual(len(results), 0)

        # 测试无效文件
        results = extractor.lookup("invalid.py", 5)
        self.assertEqual(len(results), 0)

    def test_partial_matches(self):
        """测试部分匹配条目"""
        # 添加部分匹配的日志条目
        with open(self.index_file, "a", encoding="utf-8") as f:
            f.write("test_file.py:5\t100\t5000\n")  # 不存在的位置

        extractor = TraceLogExtractor(str(self.log_file))
        results = extractor.lookup("test_file.py", 5)
        self.assertEqual(len(results), 1)  # 应忽略无效位置


if __name__ == "__main__":
    unittest.main()
