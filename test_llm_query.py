#!/usr/bin/env python
"""
llm_query 模块的单元测试
"""

import os
import pdb
import tempfile
import unittest
from unittest.mock import patch

from llm_query import (
    MAX_PROMPT_SIZE,
    GPTContextProcessor,
    _fetch_symbol_data,
    get_symbol_detail,
    patch_symbol_with_prompt,
)


class TestGPTContextProcessor(unittest.TestCase):
    """GPTContextProcessor 的单元测试类"""

    def setUp(self):
        """初始化测试环境"""
        self.processor = GPTContextProcessor()
        self.test_dir = tempfile.mkdtemp()
        os.chdir(self.test_dir)

    def tearDown(self):
        """清理测试环境"""
        os.chdir(os.path.dirname(self.test_dir))
        os.rmdir(self.test_dir)

    def test_basic_text_processing(self):
        """测试基本文本处理"""
        text = "这是一个普通文本"
        result = self.processor.process_text_with_file_path(text)
        self.assertEqual(result, text)

    def test_single_command_processing(self):
        """测试单个命令处理"""
        text = "@clipboard"
        with patch.dict(self.processor.cmd_map, {"clipboard": lambda x: "剪贴板内容"}):
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("剪贴板内容", result)

    def test_escaped_at_symbol(self):
        """测试转义的@符号"""
        text = "这是一个转义符号\\@test"
        result = self.processor.process_text_with_file_path(text)
        self.assertEqual(result, "这是一个转义符号@test")

    def test_mixed_escaped_and_commands(self):
        """测试混合转义符号和命令"""
        text = "开始\\@test 中间 @clipboard 结束"
        with patch.dict(self.processor.cmd_map, {"clipboard": lambda x: "剪贴板内容"}):
            result = self.processor.process_text_with_file_path(text)
            self.assertEqual(result, "开始@test 中间 剪贴板内容 结束")

    def test_multiple_commands_processing(self):
        """测试多个命令处理"""
        text = "开始 @clipboard 中间 @last 结束"
        with patch.dict(self.processor.cmd_map, {"clipboard": lambda x: "剪贴板内容", "last": lambda x: "上次查询"}):
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("剪贴板内容", result)
            self.assertIn("上次查询", result)

    def test_template_processing(self):
        """测试模板处理"""
        text = "{@clipboard @last}"
        with patch.dict(self.processor.cmd_map, {"clipboard": lambda x: "剪贴板内容 {}", "last": lambda x: "上次查询"}):
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("剪贴板内容 上次查询", result)

    def test_command_with_args(self):
        """测试带参数的命令"""
        text = "@symbol:test"
        with patch.dict(self.processor.cmd_map, {"symbol": lambda x: "符号补丁"}):
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("符号补丁", result)

    def test_mixed_content_processing(self):
        """测试混合内容处理"""
        text = "开始 {@clipboard @last} 中间 @symbol:test 结束"
        with patch.dict(
            self.processor.cmd_map,
            {"clipboard": lambda x: "剪贴板内容 {}", "last": lambda x: "上次查询", "symbol": lambda x: "符号补丁"},
        ):
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("剪贴板内容 上次查询", result)
            self.assertIn("符号补丁", result)

    def test_command_not_found(self):
        """测试未找到命令的情况"""
        text = "@unknown"
        result = self.processor.process_text_with_file_path(text)
        self.assertEqual(result, "")

    def test_max_length_truncation(self):
        """测试最大长度截断"""
        long_text = "a" * (MAX_PROMPT_SIZE + 100)
        result = self.processor.process_text_with_file_path(long_text)
        self.assertTrue(len(result) <= MAX_PROMPT_SIZE)
        self.assertIn("输入太长内容已自动截断", result)

    def test_multiple_symbol_args(self):
        """测试多个符号参数合并"""
        text = "@symbol:a @symbol:b"
        with patch.dict(self.processor.cmd_map, {"symbol": lambda x: f"符号补丁 {x.args}"}):
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("符号补丁 ['a', 'b']", result)

    def test_patch_symbol_with_prompt(self):
        """测试生成符号补丁提示词"""

        # 模拟CmdNode对象
        class MockCmdNode:
            def __init__(self, args):
                self.args = args

        # 测试单个符号
        symbol_names = MockCmdNode(["test_symbol"])
        with patch("llm_query.get_symbol_detail") as mock_get_detail:
            mock_get_detail.return_value = {
                "file_path": "test.py",
                "code_range": ((1, 0), (10, 0)),
                "block_range": "1-10",
                "block_content": b"test content",
            }
            result = patch_symbol_with_prompt(symbol_names)
            self.assertIn("test_symbol", result)
            self.assertIn("test.py", result)
            self.assertIn("test content", result)

        # 测试多个符号
        symbol_names = MockCmdNode(["symbol1", "symbol2"])
        with patch("llm_query.get_symbol_detail") as mock_get_detail:
            mock_get_detail.side_effect = [
                {
                    "file_path": "file1.py",
                    "code_range": ((1, 0), (5, 0)),
                    "block_range": "1-5",
                    "block_content": b"content1",
                },
                {
                    "file_path": "file2.py",
                    "code_range": ((10, 0), (15, 0)),
                    "block_range": "10-15",
                    "block_content": b"content2",
                },
            ]
            result = patch_symbol_with_prompt(symbol_names)
            self.assertIn("symbol1", result)
            self.assertIn("symbol2", result)
            self.assertIn("content1", result)
            self.assertIn("content2", result)

    def test_get_symbol_detail(self):
        """测试获取符号详细信息"""
        with patch("llm_query._send_http_request") as mock_request:
            mock_request.return_value = {
                "content": "test content",
                "location": {"start_line": 1, "start_col": 0, "end_line": 10, "end_col": 0, "block_range": "1-10"},
                "file_path": "test.py",
            }
            result = get_symbol_detail("test_symbol")
            self.assertEqual(result["file_path"], "test.py")
            self.assertEqual(result["code_range"], ((1, 0), (10, 0)))
            self.assertEqual(result["block_content"], b"test content")

    def test_fetch_symbol_data(self):
        """测试获取符号上下文数据"""
        with patch("llm_query._send_http_request") as mock_request:
            mock_request.return_value = {"symbol_name": "test", "definitions": [], "references": []}
            result = _fetch_symbol_data("test_symbol")
            self.assertEqual(result["symbol_name"], "test")
            self.assertIsInstance(result["definitions"], list)
            self.assertIsInstance(result["references"], list)


if __name__ == "__main__":
    unittest.main()
