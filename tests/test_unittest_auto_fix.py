import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from colorama import Fore

import gpt_workflow.unittest_auto_fix
from gpt_workflow.unittest_auto_fix import TestAutoFix
from llm_query import CmdNode, PatchPromptBuilder, SearchSymbolNode


class TestTestAutoFix(unittest.TestCase):
    def setUp(self):
        os.chdir(Path(__file__).parent.parent)
        self.sample_results = {
            "total": 2,
            "success": 1,
            "failures": 1,
            "errors": 0,
            "results": {
                "failures": [
                    {
                        "test": "test_example",
                        "error_type": "AssertionError",
                        "error_message": "1 != 2",
                        "traceback": "Traceback...",
                        "file_path": "/path/to/test_file.py",
                        "line": 42,
                        "function": "test_example",
                    }
                ]
            },
        }
        self.raw_error_results = {
            "total": 1,
            "success": 0,
            "failures": 0,
            "errors": 1,
            "results": {
                "errors": [
                    {
                        "test": "test_module.TestClass.test_method",
                        "error_type": "RuntimeError",
                        "error_message": "Test error",
                        "traceback": "Traceback...",
                        "file_path": "test_module.py",
                        "line": 10,
                        "function": "test_method",
                    }
                ]
            },
        }
        self.raw_unittest_error = {
            "total": 1,
            "success": 0,
            "failures": 0,
            "errors": [
                (MagicMock(id=lambda: "test_module.TestClass.test_method", _testMethodName="test_method")),
                (None, "Test error", "Traceback..."),
            ],
        }

    def test_error_extraction(self):
        auto_fix = TestAutoFix(self.sample_results)
        errors = auto_fix.error_details
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_type"], "AssertionError")

    def test_raw_error_extraction(self):
        auto_fix = TestAutoFix(self.raw_error_results)
        errors = auto_fix.error_details
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_type"], "RuntimeError")

    def test_display_errors(self):
        auto_fix = TestAutoFix(self.sample_results)
        with patch("builtins.print") as mock_print:
            auto_fix.display_errors(references=[("test_file.py", 42)])
            print_calls = [
                call(Fore.CYAN + "\nTest Results Summary:"),
                call(Fore.CYAN + "=" * 50),
                call(Fore.GREEN + "Total: 2"),
                call(Fore.GREEN + "Passed: 1"),
                call(Fore.RED + "Failures: 1"),
                call(Fore.YELLOW + "Errors: 0"),
                call(Fore.BLUE + "Skipped: 0"),
                call(Fore.CYAN + "=" * 50),
                call(Fore.YELLOW + "\nTest Issues Details:"),
                call(Fore.YELLOW + "=" * 50),
                call(Fore.RED + "\nIssue #1 (failure):"),
                call(Fore.CYAN + "File: /path/to/test_file.py"),
                call(Fore.CYAN + "Line: 42"),
                call(Fore.CYAN + "Function: test_example"),
                call(Fore.MAGENTA + "Type: AssertionError"),
                call(Fore.MAGENTA + "Message: 1 != 2"),
                call(Fore.YELLOW + "\nTraceback:"),
                call(Fore.YELLOW + "-" * 30),
                call(Fore.RED + "Traceback..."),
                call(Fore.YELLOW + "-" * 30),
                call(Fore.BLUE + "\nRelated References:"),
                call(Fore.BLUE + "-" * 30),
                call(Fore.CYAN + "→ test_file.py:42"),
                call(Fore.YELLOW + "\nNo tracer logs found for this location, /path/to/test_file.py:42"),
            ]
            mock_print.assert_has_calls(print_calls, any_order=True)
            self.assertTrue(mock_print.call_count >= 10)

    def test_get_error_context(self):
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
            tmp.write("line1\nline2\nline3\nline4\nline5\n")
            tmp_path = tmp.name

        auto_fix = TestAutoFix({})
        context = auto_fix.get_error_context(tmp_path, 3, 1)
        self.assertEqual(context, ["line2", "line3", "line4"])

        os.unlink(tmp_path)

    def test_run_tests(self):
        with patch("tests.test_main.run_tests") as mock_run:
            mock_run.return_value = self.sample_results
            result = TestAutoFix.run_tests("TestCase.test_method")
            self.assertEqual(result, self.sample_results)
            mock_run.assert_called_once_with(test_name="TestCase.test_method", json_output=True)

    def test_run_all_tests(self):
        with patch("tests.test_main.run_tests") as mock_run:
            mock_run.return_value = self.sample_results
            result = TestAutoFix.run_tests(None)
            self.assertEqual(result, self.sample_results)
            mock_run.assert_called_once_with(test_name=None, json_output=True)

    def test_lookup_reference(self):
        auto_fix = TestAutoFix({})
        with patch.object(auto_fix, "_display_tracer_logs") as mock_display:
            auto_fix.lookup_reference("test.py", 10)
            mock_display.assert_called_once_with("test.py", 10)

    def test_display_tracer_logs(self):
        auto_fix = TestAutoFix({})
        auto_fix.uniq_references = set()
        with patch("debugger.tracer.TraceLogExtractor.lookup") as mock_lookup:
            mock_lookup.return_value = (
                [{"type": "call", "filename": "test.py", "lineno": 1, "frame_id": 1, "func": "func1"}],
                [
                    [
                        {"type": "call", "filename": "test.py", "lineno": 1, "func": "func1"},
                        {"type": "return", "filename": "test.py", "lineno": 2, "func": "func1"},
                        {"type": "exception", "filename": "test.py", "lineno": 3, "func": "func1"},
                    ]
                ],
            )
            with patch("builtins.print") as mock_print:
                auto_fix._display_tracer_logs("test.py", 1)
                self.assertIn(("test.py", 1), auto_fix.uniq_references)
                self.assertTrue(mock_print.call_count >= 5)

    def test_get_symbol_info_for_references(self):
        auto_fix = TestAutoFix({})
        auto_fix.uniq_references = set()
        test_refs = [
            ("test1.py", 10),
            ("test1.py", 20),
        ]

        # Store original function
        original_query_function = gpt_workflow.unittest_auto_fix.query_symbol_service

        # Replace with test function
        mock_result = {}
        gpt_workflow.unittest_auto_fix.query_symbol_service = lambda *args, **kwargs: mock_result

        try:
            result = auto_fix.get_symbol_info_for_references([], test_refs)

            self.assertEqual(result, {})
        finally:
            # Restore original function
            gpt_workflow.unittest_auto_fix.query_symbol_service = original_query_function


class TestPatchPromptBuilder(unittest.TestCase):
    def setUp(self):
        os.chdir(Path(__file__).parent.parent)
        self.symbol_nodes = [
            SearchSymbolNode(symbols=["test_symbol1"]),
            CmdNode(command="symbol", args=["test2.py/test_symbol2"]),
        ]
        self.builder = PatchPromptBuilder(use_patch=True, symbols=self.symbol_nodes)

    @patch("llm_query.perform_search")
    @patch("llm_query.get_symbol_detail")
    def test_collect_symbols(self, mock_get_symbol_detail, mock_perform_search):
        """测试符号收集功能"""
        # 模拟搜索结果
        mock_perform_search.return_value = {
            "test_symbol": {
                "name": "test.py/test_symbol1",
                "file_path": "test.py",
                "code": "def test_func(): pass",
                "start_line": 1,
                "start_col": 0,
                "end_line": 5,
                "end_col": 0,
                "block_range": "1-5",
            }
        }

        mock_get_symbol_detail.return_value = [
            {
                "symbol_name": "test2.py/test_symbol2",
                "file_path": "test2.py",
                "code": "class TestClass: pass",
                "start_line": 10,
                "start_col": 0,
                "end_line": 15,
                "end_col": 0,
                "block_range": "10-15",
            }
        ]

        self.builder._collect_symbols()

        # 验证符号是否被正确收集
        self.assertIn("test.py/test_symbol1", self.builder.symbol_map)
        self.assertIn("test2.py/test_symbol2", self.builder.symbol_map)

        # 验证symbol_map内容
        self.assertEqual(self.builder.symbol_map["test.py/test_symbol1"]["file_path"], "test.py")
        self.assertEqual(self.builder.symbol_map["test2.py/test_symbol2"]["file_path"], "test2.py")

    def test_build_symbol_prompt(self):
        """测试符号提示构建"""
        # 准备测试数据
        self.builder.symbol_map = {
            "test.py/test_symbol": {
                "file_path": "test.py",
                "block_content": b"def test_func():\n    pass",
                "code_range": ((1, 0), (5, 0)),
                "block_range": "1-5",
            }
        }
        self.builder.tokens_left = 102400
        prompt = self.builder._build_symbol_prompt()

        # 验证提示包含必要元素
        self.assertIn("[SYMBOL START]", prompt)
        self.assertIn("符号名称: test.py/test_symbol", prompt)
        self.assertIn("文件路径: test.py", prompt)
        self.assertIn("[start]", prompt)
        self.assertIn("def test_func():", prompt)
        self.assertIn("[end]", prompt)

    def test_process_search_results(self):
        """测试搜索结果处理"""
        search_results = {
            "symbol1": {
                "name": "symbol1",
                "file_path": "test.py",
                "code": "def func(): pass",
                "start_line": 1,
                "start_col": 0,
                "end_line": 5,
                "end_col": 0,
                "block_range": "1-5",
            }
        }

        self.builder.process_search_results(search_results)

        self.assertIn("symbol1", self.builder.symbol_map)
        self.assertEqual(self.builder.symbol_map["symbol1"]["file_path"], "test.py")
        self.assertEqual(self.builder.symbol_map["symbol1"]["block_content"], b"def func(): pass")


if __name__ == "__main__":
    unittest.main()
