import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from debugger.analyzable_tracer import AnalyzableTraceLogic, TraceTypes
from debugger.call_analyzer import CallAnalyzer
from debugger.tracer import TraceConfig, TraceLogic


class TestAnalyzableTraceLogic(unittest.TestCase):
    def setUp(self):
        """为每个测试设置AnalyzableTraceLogic和模拟的分析器。"""
        self.mock_analyzer = MagicMock(spec=CallAnalyzer)
        self.mock_analyzer.verbose = False
        self.config = TraceConfig(target_files=["/test.py"])
        # 在每个测试开始时，重置类级别的状态以确保隔离
        self.reset_class_state()
        self.logic = AnalyzableTraceLogic(self.config, self.mock_analyzer, import_map_file=None)

    def tearDown(self):
        """在每个测试后停止逻辑并清理资源。"""
        self.logic.stop()
        # 再次重置类级别状态，以防测试失败未清理
        self.reset_class_state()

    def reset_class_state(self):
        """重置AnalyzableTraceLogic的类级别状态。"""
        AnalyzableTraceLogic._resolved_imports.clear()
        AnalyzableTraceLogic._resolved_files.clear()
        AnalyzableTraceLogic._event_counter = 0
        if AnalyzableTraceLogic._event_log_file:
            AnalyzableTraceLogic._event_log_file.close()
            AnalyzableTraceLogic._event_log_file = None

    @patch("debugger.analyzable_tracer.AnalyzableTraceLogic._event_lock")
    def test_add_to_buffer_forwards_to_analyzer_with_event_id(self, mock_lock):
        """测试_add_to_buffer是否将带有event_id的事件正确转发给分析器。"""
        log_data = {
            "template": "CALL {func}",
            "data": {"frame_id": 1, "func": "test_func", "original_filename": "/test.py", "lineno": 10},
        }
        color_type = TraceTypes.COLOR_CALL
        event_type = "call"

        self.logic._add_to_buffer(log_data, color_type)

        # 验证 process_event 被调用
        self.mock_analyzer.process_event.assert_called_once()
        # 验证传递给 process_event 的 log_data 包含了 event_id
        processed_log_data, processed_event_type = self.mock_analyzer.process_event.call_args[0]
        self.assertIn("event_id", processed_log_data["data"])
        self.assertEqual(processed_log_data["data"]["event_id"], 1)
        self.assertEqual(processed_event_type, event_type)

    @patch("debugger.analyzable_tracer.super")
    def test_add_to_buffer_handles_analyzer_exception(self, mock_super):
        """测试当分析器抛出异常时，错误是否被记录。"""
        self.mock_analyzer.process_event.side_effect = ValueError("Analyzer failed")
        log_data = {
            "template": "CALL {func}",
            "data": {"frame_id": 1, "func": "test_func", "original_filename": "/test.py", "lineno": 10},
        }
        color_type = TraceTypes.COLOR_CALL

        # 调用被测试的方法
        self.logic._add_to_buffer(log_data, color_type)

        # 验证是否调用了父类的 _add_to_buffer 来记录分析器错误
        mock_super()._add_to_buffer.assert_any_call(unittest.mock.ANY, TraceTypes.ERROR)
        # 获取第一个调用（即错误日志的调用）
        error_call_args, _ = mock_super()._add_to_buffer.call_args_list[0]
        error_log_data = error_call_args[0]
        self.assertIn("ANALYZER ERROR", error_log_data["template"])
        self.assertIn("Analyzer failed", error_log_data["data"]["error"])

    @patch("debugger.analyzable_tracer.resolve_imports")
    @patch("inspect.getsourcefile", return_value="/path/to/real_file.py")
    def test_handle_call_resolves_imports_once(self, mock_getsourcefile, mock_resolve_imports):
        """测试handle_call只为每个文件在类级别解析一次导入。"""
        mock_resolve_imports.return_value = {"os": {"module": "os", "path": "os"}}
        mock_frame = MagicMock()
        mock_frame.f_code.co_filename = "/path/to/real_file.py"

        # 第一次调用
        self.logic.handle_call(mock_frame)
        mock_resolve_imports.assert_called_once_with(mock_frame)
        self.assertIn("/path/to/real_file.py", AnalyzableTraceLogic._resolved_files)
        self.assertIn("/path/to/real_file.py", AnalyzableTraceLogic._resolved_imports)

        # 第二次调用（可以是新的实例，因为状态是类级别的）
        logic2 = AnalyzableTraceLogic(self.config, self.mock_analyzer, import_map_file=None)
        logic2.handle_call(mock_frame)
        # 调用次数应保持不变
        mock_resolve_imports.assert_called_once()

    @patch("debugger.analyzable_tracer.resolve_imports")
    @patch("inspect.getsourcefile", return_value=None)
    def test_handle_call_skips_special_filenames(self, mock_getsourcefile, mock_resolve_imports):
        """测试handle_call跳过特殊文件名如<string>。"""
        mock_frame = MagicMock()
        mock_frame.f_code.co_filename = "<string>"
        self.logic.handle_call(mock_frame)
        mock_resolve_imports.assert_not_called()
        self.assertNotIn("<string>", AnalyzableTraceLogic._resolved_files)

    @patch("json.dump")
    @patch("debugger.analyzable_tracer.Path")
    def test_save_import_map_class_method(self, mock_tracer_path_cls, mock_json_dump):
        """测试类方法 save_import_map 是否能正确保存导入映射文件。"""
        # Prepare data
        AnalyzableTraceLogic._resolved_imports = {"/path/to/file.py": {"a": "b"}}

        # Create a mock Path instance that will be returned by the patched Path class
        # when it's called inside AnalyzableTraceLogic.save_import_map (i.e., path = Path(import_map_file))
        mock_path_instance_in_save_map = MagicMock(spec=Path)
        mock_tracer_path_cls.return_value = mock_path_instance_in_save_map

        # Configure the mock Path instance's .open() method to behave as a context manager
        # This replaces the functionality previously provided by mock_open
        mock_file_handle = MagicMock()
        mock_path_instance_in_save_map.open.return_value.__enter__.return_value = mock_file_handle

        # The original test passed a real Path object, so we simulate that here.
        # This ensures the patched Path class (mock_tracer_path_cls) is called with the correct argument type.
        real_path_arg_to_save_map = Path("/fake/import_map.json")

        # Call the class method
        AnalyzableTraceLogic.save_import_map(real_path_arg_to_save_map)

        # Assertions
        # 1. Verify that the patched Path class (constructor) was called correctly
        mock_tracer_path_cls.assert_called_once_with(real_path_arg_to_save_map)
        # 2. Verify that .parent.mkdir() was called on the mock Path instance inside save_import_map
        mock_path_instance_in_save_map.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        # 3. Verify that .open() was called on the mock Path instance inside save_import_map
        mock_path_instance_in_save_map.open.assert_called_once_with("w", encoding="utf-8")
        # 4. Verify that json.dump was called correctly with the mock file handle
        mock_json_dump.assert_called_once_with(
            {"/path/to/file.py": {"a": "b"}}, mock_file_handle, indent=2, ensure_ascii=False
        )

    def test_stop_finalizes_analyzer_and_super_stop(self):
        """测试stop方法调用analyzer.finalize和父类的stop。"""
        with patch.object(TraceLogic, "stop") as mock_super_stop:
            self.logic.stop()
            self.mock_analyzer.finalize.assert_called_once()
            mock_super_stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
