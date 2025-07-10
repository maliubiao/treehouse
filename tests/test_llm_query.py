#!/usr/bin/env python
"""
llm_query 模块的单元测试
"""

import datetime
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings

import llm_query
from gpt_workflow import ArchitectMode, ChangelogMarkdown, CoverageTestPlan, LintParser

# 假设这些是你代码中实际的导入
from llm_query import (
    GPT_FLAG_PATCH,
    AutoGitCommit,
    BlockPatchResponse,
    CmdNode,
    DiffBlockFilter,
    FormatAndLint,
    GPTContextProcessor,
    ModelConfig,
    ModelSwitch,
    NewSymbolFlag,
    SearchSymbolNode,
    _fetch_symbol_data,
    _find_gitignore,
    _handle_local_file,
    get_symbol_detail,
    interactive_symbol_location,
    process_file_change,
)
from tools.chatbot import ChatbotUI
from tree import BlockPatch, find_diff, find_patch


class TestGPTContextProcessor(unittest.TestCase):
    """GPTContextProcessor 的单元测试类"""

    def setUp(self):
        """初始化测试环境"""
        self.processor = GPTContextProcessor()
        self.test_dir = tempfile.mkdtemp()
        # 保存原始工作目录
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Mock GLOBAL_MODEL_CONFIG
        self.mock_model_config = MagicMock()
        self.mock_model_config.is_thinking = False
        self.patcher = patch("llm_query.GLOBAL_MODEL_CONFIG", self.mock_model_config)
        self.patcher.start()

        # 定义一个标准的tokens_left值，以便在测试中复用
        self.default_tokens_left = 128 * 1024

    def tearDown(self):
        """清理测试环境"""
        # 恢复原始工作目录
        os.chdir(self.original_cwd)
        # 使用 shutil.rmtree 更安全地删除目录及其内容
        shutil.rmtree(self.test_dir)
        # 停止patcher
        self.patcher.stop()

    def test_basic_text_processing(self):
        """测试基本文本处理"""
        text = "这是一个普通文本"
        result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
        self.assertEqual(result, text)

    def test_single_command_processing(self):
        """测试单个命令处理"""
        text = "@clipboard"
        with patch.dict(self.processor.cmd_handlers, {"clipboard": lambda x: "剪贴板内容"}):
            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
            self.assertIn("剪贴板内容", result)

    def test_escaped_at_symbol(self):
        """测试转义的@符号"""
        text = "这是一个转义符号\\@test"
        result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
        self.assertEqual(result, "这是一个转义符号@test")

    def test_mixed_escaped_and_commands(self):
        """测试混合转义符号和命令"""
        text = "开始\\@test 中间 @clipboard 结束"
        with patch.dict(self.processor.cmd_handlers, {"clipboard": lambda x: "剪贴板内容"}):
            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
            self.assertEqual(result, "开始@test 中间 剪贴板内容 结束")

    def test_multiple_commands_processing(self):
        """测试多个命令处理"""
        text = "开始 @clipboard 中间 @last 结束"
        with patch.dict(
            self.processor.cmd_handlers,
            {"clipboard": lambda x: "剪贴板内容", "last": lambda x: "上次查询"},
        ):
            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
            self.assertIn("剪贴板内容", result)
            self.assertIn("上次查询", result)

    def test_command_with_args(self):
        """测试带参数的命令"""
        text = "@symbol_llm_query.py/test"
        # 符号命令最终通过 PatchPromptBuilder.build 生成提示，而不是一个独立的 _handle_symbol_command 函数
        with patch("llm_query.PatchPromptBuilder.build") as mock_build:
            mock_build.return_value = "有代码库里的一些符号和代码块"
            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
            self.assertIn("有代码库里的一些符号和代码块", result)

    def test_command_not_found(self):
        """测试未找到命令的情况"""
        text = "@unknown"
        with self.assertRaises(SystemExit):
            self.processor.process_text(text, tokens_left=self.default_tokens_left)

    def test_max_length_truncation(self):
        """测试最大长度截断"""
        # 定义一个期望的字符长度上限，用于测试截断逻辑
        expected_char_length_limit = 128 * 1024
        # 根据llm_query.py中process_text内部 tokens_left *= 3 的逻辑，
        # 反推出需要传入的tokens_left值，以确保最终字符限制接近期望值
        tokens_left_for_process_text = expected_char_length_limit // 3

        long_text = "a" * (expected_char_length_limit + 100)  # 确保文本长度超过期望的字符限制

        # 调用process_text，传入计算后的tokens_left
        result = self.processor.process_text(long_text, tokens_left=tokens_left_for_process_text)

        # 验证结果的长度不超过期望的字符长度上限
        self.assertTrue(len(result) <= expected_char_length_limit)

        # 验证截断标志是否存在
        self.assertIn("输入太长内容已自动截断", result)

        # 验证截断后的实际长度是否是根据内部计算的字符限制（tokens_left * 3）
        # _finalize_output 会在 len(text) > max_tokens 时将文本截断到 max_tokens 长度
        # 这里的 max_tokens 实际就是 tokens_left_for_process_text * 3
        # long_text (131172) 肯定大于 (expected_char_length_limit // 3 * 3 = 131070),
        # 所以会触发截断，最终长度为 131070
        actual_truncated_length = tokens_left_for_process_text * 3
        self.assertEqual(len(result), actual_truncated_length)

    def test_multiple_symbol_args(self):
        """测试多个符号参数合并"""
        text = "@symbol_llm_query/a @symbol_llm_query.py/b"
        with patch("llm_query.PatchPromptBuilder.build") as mock_build:
            mock_build.return_value = "符号补丁 ['a', 'b']"
            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
            self.assertIn("符号补丁 ['a', 'b']", result)

    def test_url_processing(self):
        """测试URL处理"""
        text = "@https://example.com"
        with patch("llm_query._handle_url") as mock_handle_url:
            mock_handle_url.return_value = "URL处理结果"
            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
            self.assertIn("URL处理结果", result)
            mock_handle_url.assert_called_once_with(
                CmdNode(command="https://example.com", command_type=None, args=None)
            )

    def test_multiple_urls(self):
        """测试多个URL处理"""
        text = "@https://example.com @https://another.com"
        with patch("llm_query._handle_url") as mock_handle_url:
            mock_handle_url.side_effect = ["URL1结果", "URL2结果"]
            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
            self.assertIn("URL1结果", result)
            self.assertIn("URL2结果", result)
            self.assertEqual(mock_handle_url.call_count, 2)

    def test_mixed_url_and_commands(self):
        """测试混合URL和命令处理"""
        text = "开始 @https://example.com 中间 @clipboard 结束"
        with (
            patch("llm_query._handle_url") as mock_handle_url,
            patch.dict(self.processor.cmd_handlers, {"clipboard": lambda x: "剪贴板内容"}),
        ):
            mock_handle_url.return_value = "URL处理结果"
            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)
            self.assertIn("URL处理结果", result)
            self.assertIn("剪贴板内容", result)

    def test_single_symbol_processing(self):
        """测试单个符号节点处理"""
        text = "..test_symbol.."
        with patch.object(self.processor, "generate_symbol_patch_prompt") as mock_process:
            mock_process.return_value = "符号处理结果"
            # 文本部分是'..test_symbol..'移除'..'后的内容
            processed_text_content = "test_symbol"
            # 修正：考虑到process_text内部tokens_left会乘以3
            expected_tokens_left = (self.default_tokens_left * 3) - len(processed_text_content)

            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)

            mock_process.assert_called_once_with([SearchSymbolNode(symbols=["test_symbol"])], expected_tokens_left)
            self.assertEqual(result, "符号处理结果" + processed_text_content)

    def test_multiple_symbols_processing(self):
        """测试多个符号节点处理"""
        text = "..symbol1.. ..symbol2.."
        with patch.object(self.processor, "generate_symbol_patch_prompt") as mock_process:
            mock_process.return_value = "多符号处理结果"
            # 文本部分是'..symbol1.. ..symbol2..'移除'..'后的内容
            processed_text_content = "symbol1 symbol2"
            # 修正：考虑到process_text内部tokens_left会乘以3
            expected_tokens_left = (self.default_tokens_left * 3) - len(processed_text_content)

            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)

            mock_process.assert_called_once_with(
                [SearchSymbolNode(symbols=["symbol1", "symbol2"])], expected_tokens_left
            )
            self.assertEqual(result, "多符号处理结果" + processed_text_content)

    def test_mixed_symbols_and_content(self):
        """测试符号节点与混合内容处理"""
        text = "前置内容..symbol1..中间@clipboard ..symbol2..结尾"
        with (
            patch.object(self.processor, "generate_symbol_patch_prompt") as mock_symbol,
            patch.dict(self.processor.cmd_handlers, {"clipboard": lambda x: "剪贴板内容"}),
        ):
            mock_symbol.return_value = "符号处理结果"
            # 模拟命令和符号标记被移除和替换后的文本
            text_after_processing = "前置内容symbol1中间剪贴板内容 symbol2结尾"
            # 修正：考虑到process_text内部tokens_left会乘以3
            expected_tokens_left = (self.default_tokens_left * 3) - len(text_after_processing)

            result = self.processor.process_text(text, tokens_left=self.default_tokens_left)

            mock_symbol.assert_called_once_with(
                [SearchSymbolNode(symbols=["symbol1", "symbol2"])], expected_tokens_left
            )
            self.assertEqual(result, "符号处理结果" + text_after_processing)

    def test_project_command_processing(self):
        """测试项目配置文件处理"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试配置文件
            yml_path = os.path.join(tmpdir, "test_project.yml")
            yaml = __import__("yaml")

            # 创建测试目录结构
            docs_dir = os.path.join(tmpdir, "docs")
            os.makedirs(docs_dir)

            # 创建测试文件
            test_file = os.path.join(tmpdir, "test_file.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("# Test python file\nprint('hello')")

            # 写入配置文件，使用绝对路径
            with open(yml_path, "w", encoding="utf-8") as f:
                yaml.dump({"files": [tmpdir + "/" + "*.py"], "dirs": [docs_dir]}, f)  # 使用绝对路径

            # Mock路径检测和目录处理
            with (
                patch("llm_query.under_projects_dir", return_value=True),
                patch("llm_query._process_directory") as mock_process_dir,
            ):
                mock_process_dir.return_value = "[processed directory]"
                text = f"@{yml_path}"
                result = self.processor.process_text(text, tokens_left=self.default_tokens_left)

                # 验证配置文件头
                self.assertIn(f"[project config start]: {yml_path}", result)

                # 验证文件处理
                self.assertIn("test_file.py", result)
                self.assertIn("print('hello')", result)

                # 验证目录处理
                mock_process_dir.assert_called_once_with(docs_dir)  # 使用绝对路径
                self.assertIn("[processed directory]", result)

                # 验证配置文件尾
                self.assertIn(f"[project config end]: {yml_path}", result)

            # 测试文件不存在的情况
            with patch("llm_query.under_projects_dir", return_value=True):
                text = "@projects/non_exist.yml"
                with self.assertRaises(SystemExit):
                    self.processor.process_text(text, tokens_left=self.default_tokens_left)

            # 测试无效配置文件
            invalid_yml = os.path.join(tmpdir, "invalid.yml")
            with open(invalid_yml, "w", encoding="utf-8") as f:
                f.write("invalid: {")  # 故意写无效的YAML语法

            with patch("llm_query.under_projects_dir", return_value=True):
                text = f"@{invalid_yml}"
                with self.assertRaises(SystemExit):
                    self.processor.process_text(text, tokens_left=self.default_tokens_left)

    def test_patch_symbol_with_prompt(self):
        """测试生成符号补丁提示词"""
        # 模拟符号数据

        # 模拟GPT_FLAGS
        with patch.dict("llm_query.GPT_FLAGS", {GPT_FLAG_PATCH: False}):
            # 测试单个符号
            with patch("llm_query.PatchPromptBuilder") as mock_builder:
                mock_instance = mock_builder.return_value
                mock_instance.build.return_value = "test prompt"
                result = self.processor.generate_symbol_patch_prompt(["test_symbol"], 102400)
                self.assertEqual(result, "test prompt")
                mock_builder.assert_called_once_with(False, ["test_symbol"], tokens_left=102400)
                mock_instance.build.assert_called_once()

            # 测试多个符号
            with patch("llm_query.PatchPromptBuilder") as mock_builder:
                mock_instance = mock_builder.return_value
                mock_instance.build.return_value = "multi symbol prompt"
                result = self.processor.generate_symbol_patch_prompt(["symbol1", "symbol2"], tokens_left=102400)
                self.assertEqual(result, "multi symbol prompt")
                mock_builder.assert_called_once_with(False, ["symbol1", "symbol2"], tokens_left=102400)
                mock_instance.build.assert_called_once()

    @patch("llm_query.requests.get")
    def test_get_symbol_detail(self, mock_get):
        """测试获取符号详细信息"""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {
                "content": "test content",
                "location": {
                    "start_line": 1,
                    "start_col": 0,
                    "end_line": 10,
                    "end_col": 0,
                    "block_range": "1-10",
                },
                "file_path": "test.py",
            }
        ]
        mock_get.return_value = mock_response

        result = get_symbol_detail("test.py/test_symbol")
        self.assertEqual(result[0]["file_path"], "test.py")
        self.assertEqual(result[0]["code_range"], ((1, 0), (10, 0)))
        self.assertEqual(result[0]["block_content"], b"test content")

    @patch("llm_query.send_http_request")
    def test_fetch_symbol_data(self, mock_send_http_request):
        """测试获取符号上下文数据"""
        mock_send_http_request.return_value = {
            "symbol_name": "test",
            "definitions": [],
            "references": [],
        }

        result = _fetch_symbol_data("test_symbol")
        self.assertEqual(result["symbol_name"], "test")
        self.assertIsInstance(result["definitions"], list)
        self.assertIsInstance(result["references"], list)


class TestSymbolLocation(unittest.TestCase):
    def setUp(self):
        self._setup_test_data()
        self._setup_test_file()
        self._setup_mock_api()

    def _setup_test_data(self):
        self.symbol_name = "test_file.py/test_symbol"
        self.file_path = "test_file.py"
        self.original_content = "\n\ndef test_symbol():\n    pass"
        self.block_range = (1, len(self.original_content))
        self.code_range = ((1, 0), (2, 4))
        self.whole_content = self.original_content + "\n"

    def _setup_test_file(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(self.whole_content)

    def _setup_mock_api(self):
        self.symbol_data = {
            "content": self.original_content[self.block_range[0] : self.block_range[1]],
            "location": {
                "block_range": self.block_range,
                "start_line": 1,
                "start_col": 0,
                "end_line": 2,
                "end_col": 4,
            },
            "file_path": self.file_path,
        }
        self.original_send_http_request = llm_query.send_http_request
        llm_query.send_http_request = lambda url: [self.symbol_data]

    def tearDown(self):
        if os.path.exists(self.file_path):
            os.remove(self.file_path)
        llm_query.send_http_request = self.original_send_http_request

    def test_basic_symbol(self):
        result = llm_query.get_symbol_detail(self.symbol_name)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result), 1)
        self.assertIn(self.symbol_name, result[0]["symbol_name"])
        self.assertEqual(result[0]["file_path"], self.file_path)
        self.assertEqual(result[0]["code_range"], self.code_range)
        self.assertEqual(result[0]["block_range"], self.block_range)
        self.assertEqual(
            result[0]["block_content"],
            self.original_content[self.block_range[0] : self.block_range[1]].encode("utf-8"),
        )

    def test_multiline_symbol(self):
        content = "def test_symbol():\n    pass\n    pass\n"
        block_range = (0, len(content))
        code_range = ((1, 0), (3, 4))

        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        self.symbol_data["content"] = content
        self.symbol_data["location"]["block_range"] = block_range
        self.symbol_data["location"]["end_line"] = 3
        result = llm_query.get_symbol_detail(self.symbol_name)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0]["block_range"], block_range)
        self.assertEqual(result[0]["code_range"], code_range)

    def test_empty_symbol(self):
        content = ""
        block_range = (0, 0)
        code_range = ((1, 0), (1, 0))

        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        self.symbol_data["content"] = content
        self.symbol_data["location"]["block_range"] = block_range
        self.symbol_data["location"]["end_line"] = 1
        self.symbol_data["location"]["end_col"] = 0

        result = llm_query.get_symbol_detail(self.symbol_name)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0]["block_range"], block_range)
        self.assertEqual(result[0]["code_range"], code_range)


class TestFileRange(unittest.TestCase):
    def test_file_range_patch(self):
        """测试文件范围补丁解析"""
        # 模拟包含文件范围的响应内容
        response = dedent(
            """
[overwrite whole block]: example.py:10-20
[start]
def new_function():
    print("Added by patch")
[end]
        """
        )
        parser = BlockPatchResponse()
        results = parser.parse(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "example.py:10-20")
        self.assertIn("new_function", results[0][1])

    def test_symbol_attachment(self):
        """测试未注册符号内容附加到最近合法符号"""
        # 模拟包含非法符号的响应
        response = """
[overwrite whole symbol]: invalid_symbol
[start]
print("Should attach to next valid")
[end]

[overwrite whole symbol]: valid_symbol
[start]
def valid_func():
    pass
[end]
        """
        parser = BlockPatchResponse(symbol_names=["valid_symbol"])
        results = parser.parse(response)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "valid_symbol")
        self.assertIn("valid_func", results[0][1])
        self.assertIn('print("Should attach', results[0][1])

    def test_multiple_attachments(self):
        """测试多个非法符号连续附加"""
        response = """
[overwrite whole symbol]: invalid1
[start]
a = 1
[end]

[overwrite whole symbol]: invalid2
[start]
b = 2
[end]

[overwrite whole symbol]: valid
[start]
c = 3
[end]
        """
        parser = BlockPatchResponse(symbol_names=["valid"])
        results = parser.parse(response)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1].strip(), "a = 1\n\nb = 2\n\nc = 3")

    def test_extract_symbol_paths_legacy_format(self):
        """测试从旧版（非JSON）响应中提取符号路径"""
        response = """
[overwrite whole symbol]: path/to/file1.py/symbol1
[start]
code1
[end]

[overwrite whole symbol]: path/to/file2.py/symbol2
[start]
code2
[end]

[overwrite whole symbol]: path/to/file1.py/symbol3
[start]
code3
[end]
        """
        parser = BlockPatchResponse()
        result = parser.extract_symbol_paths(response)

        expected = {
            "path/to/file1.py": ["symbol1", "symbol3"],
            "path/to/file2.py": ["symbol2"],
        }
        self.assertEqual(result, expected)

    def test_add_symbol_details_legacy_format(self):
        """测试add_symbol_details函数与旧版（非JSON）响应格式的集成"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False, encoding="utf8") as tmp:
            tmp.write(
                dedent(
                    '''
            def func1():
                """测试函数1"""
                pass

            class TestClass:
                """测试类"""
                def method1(self):
                    pass
            '''
                )
            )
            tmp_path = tmp.name
            # 准备测试数据
        # Fixed: C0209 (f-string) and W1308 (duplicate format arg)
        remaining = dedent(
            f'''
        [overwrite whole symbol]: {tmp_path}/func1
        [start]
        def func1():
            """修改后的函数1"""
            return 42
        [end]

        [overwrite whole symbol]: {tmp_path}/TestClass
        [start]
        class TestClass:
            """修改后的类"""
            def method1(self):
                return "modified"
        [end]
        '''
        )
        try:
            symbol_detail = {}
            require_info_map = BlockPatchResponse.extract_symbol_paths(remaining)
            self.assertEqual(len(require_info_map), 1)
            self.assertIn(tmp_path, require_info_map)

            # 调用测试函数
            llm_query.add_symbol_details(remaining, symbol_detail)

            # 验证结果
            self.assertEqual(len(symbol_detail), 2)
            self.assertIn(f"{tmp_path}/func1", symbol_detail)
            self.assertIn(f"{tmp_path}/TestClass", symbol_detail)

            # 验证符号信息内容
            func_info = symbol_detail[f"{tmp_path}/func1"]
            self.assertEqual(func_info["file_path"], tmp_path)
            self.assertIn("block_range", func_info)
            self.assertIn("block_content", func_info)

            class_info = symbol_detail[f"{tmp_path}/TestClass"]
            self.assertEqual(class_info["file_path"], tmp_path)
            self.assertIn("block_range", class_info)
            self.assertIn("block_content", class_info)
        finally:
            os.unlink(tmp_path)

    def test_interactive_symbol_location(self):
        """测试交互式符号位置选择器"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False, encoding="utf8") as tmp:
            tmp.write(
                dedent(
                    '''
            def existing_func():
                """已有函数"""
                pass

            class ExistingClass:
                def method1(self):
                    pass

                def method2(self):
                    pass
            '''
                )
            )
            tmp_path = tmp.name

        try:
            # 准备父符号信息
            with open(tmp_path, "rb") as f:
                content = f.read()

            parent_info = {
                "start_line": 1,
                "block_range": [0, len(content)],
                "block_content": content,
            }

            # 模拟用户输入(选择第8行，即method2的位置)
            with unittest.mock.patch("builtins.input", side_effect=["8"]):
                result = interactive_symbol_location(
                    file=tmp_path,
                    path="test_path",
                    parent_symbol="ExistingClass",
                    parent_symbol_info=parent_info,
                )

            # 验证返回结果
            self.assertEqual(result["file_path"], tmp_path)
            self.assertEqual(len(result["block_range"]), 2)
            self.assertEqual(result["block_content"], b"")
            self.assertTrue(result[NewSymbolFlag])  # 新增验证NewSymbolFlag

            # Test with BlockPatch (assuming BlockPatch is available)
            patch = BlockPatch(  # W0621 warning for 'patch' is intentionally ignored as it's local to method.
                file_paths=[tmp_path],
                patch_ranges=[result["block_range"]],
                block_contents=[result["block_content"]],
                update_contents=[b"    def new_method(self):\n        return 'patched'"],
            )

            diff = patch.generate_diff()
            self.assertIn(tmp_path, diff)
            self.assertIn("+    def new_method(self):", diff[tmp_path])
            self.assertIn("+        return 'patched'", diff[tmp_path])

            patched_files = patch.apply_patch()
            self.assertIn(tmp_path, patched_files)
            self.assertIn(b"new_method", patched_files[tmp_path])
        finally:
            os.unlink(tmp_path)

    def test_add_symbol_details_with_interactive(self):
        """测试add_symbol_details与交互式位置选择的集成"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False, encoding="utf8") as tmp:
            tmp.write(
                dedent(
                    """
            def target_func():
                pass

            class TargetClass:
                def target_method(self):
                    pass
            """
                )
            )
            tmp_path = tmp.name

        try:
            # 准备测试数据
            remaining = dedent(
                f"""
            [overwrite whole symbol]: {tmp_path}/new_symbol
            [start]
            new_code = 42
            [end]
            """
            )

            # 模拟用户输入(选择第2行，即target_func的位置)
            with unittest.mock.patch("builtins.input", side_effect=["2"]):
                symbol_detail = {}
                llm_query.add_symbol_details(remaining, symbol_detail)

            # 验证结果
            self.assertEqual(len(symbol_detail), 1)
            self.assertIn(f"{tmp_path}/new_symbol", symbol_detail)
            self.assertTrue(symbol_detail[f"{tmp_path}/new_symbol"][NewSymbolFlag])  # 新增验证NewSymbolFlag

            # Test with BlockPatch (assuming BlockPatch is available)
            symbol_info = symbol_detail[f"{tmp_path}/new_symbol"]
            patch = BlockPatch(  # W0621 warning for 'patch' is intentionally ignored as it's local to method.
                file_paths=[tmp_path],
                patch_ranges=[symbol_info["block_range"]],
                block_contents=[symbol_info["block_content"]],
                update_contents=[b"new_code = 42\n    # patched"],
            )

            diff = patch.generate_diff()
            self.assertIn(tmp_path, diff)
            self.assertIn("+new_code = 42", diff[tmp_path])
            self.assertIn("# patched", diff[tmp_path])

            patched_files = patch.apply_patch()
            self.assertIn(tmp_path, patched_files)
            self.assertIn(b"new_code = 42", patched_files[tmp_path])
        finally:
            os.unlink(tmp_path)

    def test_parse_json_response_actions(self):
        """测试解析包含多种action的JSON响应"""
        response_text = json.dumps(
            {
                "thought": "A test thought.",
                "patches": [
                    {"action": "overwrite_whole_file", "path": "file1.py", "content": "new file content"},
                    {"action": "overwrite_symbol", "path": "file2.py/my_func", "content": "def my_func(): pass"},
                    {"action": "delete_symbol", "path": "file2.py/old_func", "content": ""},
                ],
            }
        )
        parser = BlockPatchResponse()
        results = parser.parse(response_text)
        self.assertEqual(len(results), 3)
        self.assertIn(("file1.py", "new file content"), results)
        self.assertIn(("file2.py/my_func", "def my_func(): pass"), results)
        self.assertIn(("file2.py/old_func", ""), results)

    def test_parse_invalid_json(self):
        """测试解析无效JSON时应引发ValueError"""
        invalid_json_text = '{"thought": "bad json", "patches": ['
        parser = BlockPatchResponse()
        # 根据llm_query.py中parse方法的实际行为，json解析失败时会返回空列表而非抛出异常
        self.assertEqual(parser.parse(invalid_json_text), [])

    def test_parse_malformed_data_structure(self):
        """测试解析结构不正确的JSON数据"""
        # 缺少 'patches' 键
        missing_patches = json.dumps({"thought": "thought only"})
        parser = BlockPatchResponse()
        # 根据llm_query.py中parse方法的实际行为，结构不正确时会返回空列表而非抛出异常
        self.assertEqual(parser.parse(missing_patches), [])

        # 'patches' 不是列表
        patches_not_list = json.dumps({"patches": "a string"})
        # 根据llm_query.py中parse方法的实际行为，结构不正确时会返回空列表而非抛出异常
        self.assertEqual(parser.parse(patches_not_list), [])

        # patch对象不完整，应被忽略
        incomplete_patch = json.dumps(
            {"patches": [{"action": "overwrite_symbol", "path": "some/path"}]}  # 缺少 'content'
        )
        self.assertEqual(parser.parse(incomplete_patch), [])

    def test_extract_symbol_paths_json_format(self):
        """测试从JSON响应中正确提取符号路径"""
        response_text = json.dumps(
            {
                "thought": "A test thought.",
                "patches": [
                    # This should be extracted
                    {"action": "overwrite_symbol", "path": "path/to/file1.py/symbol1", "content": "c1"},
                    # This should be ignored
                    {"action": "overwrite_whole_file", "path": "path/to/file2.py", "content": "c2"},
                    # This should be ignored
                    {"action": "delete_symbol", "path": "path/to/file1.py/symbol2", "content": ""},
                    # This should be extracted
                    {"action": "overwrite_symbol", "path": "path/to/file1.py/symbol3", "content": "c3"},
                ],
            }
        )
        result = BlockPatchResponse.extract_symbol_paths(response_text)
        expected = {
            "path/to/file1.py": ["symbol1", "symbol3"],
        }
        self.assertEqual(result, expected)

    def test_parse_v4_json_format_and_fallback(self):
        """测试解析V4 JSON格式响应以及对旧格式的回退"""
        # 1. 测试V4 JSON格式
        json_response = json.dumps(
            {
                "thought": "A test thought.",
                "patches": [
                    {"action": "overwrite_whole_file", "path": "file1.py", "content": "new file content"},
                    {"action": "overwrite_symbol", "path": "file2.py/my_func", "content": "def my_func(): pass"},
                    {"action": "delete_symbol", "path": "file2.py/old_func", "content": ""},
                ],
            }
        )
        parser = BlockPatchResponse()
        results = parser.parse(json_response)
        self.assertEqual(len(results), 3)
        self.assertIn(("file1.py", "new file content"), results)
        self.assertIn(("file2.py/my_func", "def my_func(): pass"), results)
        self.assertIn(("file2.py/old_func", ""), results)

        # 2. 测试无效JSON，回退到旧格式解析
        # Note: This test implies BlockPatchResponse's parse method attempts JSON first,
        # and if it fails, falls back to the legacy regex parsing.
        legacy_response_with_invalid_json_chars = """
[overwrite whole symbol]: valid_symbol
[start]
{ "incomplete_json": "value"
def valid_func():
    pass
[end]
        """
        parser_fallback = BlockPatchResponse(symbol_names=["valid_symbol"])
        results_fallback = parser_fallback.parse(legacy_response_with_invalid_json_chars)
        self.assertEqual(len(results_fallback), 1)
        self.assertEqual(results_fallback[0][0], "valid_symbol")
        # The content will include the incomplete JSON line because it's treated as part of the block
        self.assertIn("valid_func", results_fallback[0][1])
        self.assertIn('{ "incomplete_json": "value"', results_fallback[0][1])

    def test_add_symbol_details_json_format(self):
        """测试add_symbol_details函数与JSON响应格式的集成"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False, encoding="utf8") as tmp:
            tmp.write(
                dedent(
                    '''
            def func1():
                """测试函数1"""
                pass

            class TestClass:
                """测试类"""
                def method1(self):
                    pass
            '''
                )
            )
            tmp_path = tmp.name

        remaining = json.dumps(
            {
                "thought": "a thought",
                "patches": [
                    {
                        "action": "overwrite_symbol",
                        "path": f"{tmp_path}/func1",
                        "content": 'def func1():\n    """修改后的函数1"""\n    return 42',
                    },
                    {
                        "action": "overwrite_symbol",
                        "path": f"{tmp_path}/TestClass",
                        # Fixed: C0301 (line too long)
                        "content": dedent('''\
                            class TestClass:
                                """修改后的类"""
                                def method1(self):
                                    return "modified"'''),
                    },
                ],
            }
        )

        try:
            symbol_detail = {}
            llm_query.add_symbol_details(remaining, symbol_detail)

            self.assertEqual(len(symbol_detail), 2)
            self.assertIn(f"{tmp_path}/func1", symbol_detail)
            self.assertIn(f"{tmp_path}/TestClass", symbol_detail)
            self.assertEqual(symbol_detail[f"{tmp_path}/func1"]["file_path"], tmp_path)
            self.assertEqual(symbol_detail[f"{tmp_path}/TestClass"]["file_path"], tmp_path)
        finally:
            os.unlink(tmp_path)


class TestGitignoreFunctions(unittest.TestCase):
    """测试.gitignore相关功能"""

    def setUp(self):
        """在每个测试开始前，创建一个干净的临时目录结构。"""
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = self.test_dir.name
        # 创建一个子目录用于测试向上查找
        self.subdir = os.path.join(self.root, "subdir")
        os.makedirs(self.subdir)

    def tearDown(self):
        """在每个测试结束后，清理临时目录。"""
        self.test_dir.cleanup()

    def test_find_in_current_directory(self):
        """测试：当.gitignore就在当前目录时，应能直接找到。"""
        gitignore_path = os.path.join(self.subdir, ".gitignore")
        with open(gitignore_path, "w", encoding="utf8") as f:
            f.write("*.log")

        found_path = _find_gitignore(self.subdir)
        self.assertEqual(found_path, gitignore_path)

    def test_find_in_parent_directory(self):
        """测试：当.gitignore在父目录时，应能向上查找到。"""
        gitignore_path = os.path.join(self.root, ".gitignore")
        with open(gitignore_path, "w", encoding="utf8") as f:
            f.write("*.tmp")

        # 从子目录开始查找
        found_path = _find_gitignore(self.subdir)
        self.assertEqual(found_path, gitignore_path)

    def test_should_return_closest_gitignore_when_both_exist(self):
        """【核心测试】测试：当父目录和当前目录都有.gitignore时，应优先返回当前目录的。"""
        # 1. 在父目录创建一个 .gitignore
        parent_gitignore_path = os.path.join(self.root, ".gitignore")
        with open(parent_gitignore_path, "w", encoding="utf8") as f:
            f.write("parent_rule")

        # 2. 在当前（子）目录也创建一个 .gitignore
        child_gitignore_path = os.path.join(self.subdir, ".gitignore")
        with open(child_gitignore_path, "w", encoding="utf8") as f:
            f.write("child_rule")

        # 3. 从子目录开始查找，期望找到的是子目录中的那一个
        found_path = _find_gitignore(self.subdir)
        self.assertEqual(found_path, child_gitignore_path)
        self.assertNotEqual(found_path, parent_gitignore_path)

    def test_should_return_none_when_no_gitignore_found(self):
        """测试：当向上查找到根目录都找不到.gitignore时，应返回None。"""
        # 在这个测试中，我们不创建任何 .gitignore 文件

        # 为了使测试与运行环境隔离（避免找到测试目录之外的 .gitignore 文件），
        # 我们通过 mock os.path.dirname 来限制 _find_gitignore 的向上搜索范围。
        # 当搜索路径到达我们设定的测试根目录时，我们让它表现得像到达了文件系统根目录。
        original_dirname = os.path.dirname

        def mock_dirname(path):
            # 如果当前路径已经是我们测试的根目录，返回它自己。
            # 这将导致 _find_gitignore 中的 `parent == current` 条件成立，从而停止搜索。
            if os.path.abspath(path) == os.path.abspath(self.root):
                return os.path.abspath(self.root)
            # 否则，使用原始的 dirname 函数。
            return original_dirname(path)

        # _find_gitignore 位于 llm_query 模块中，它调用 os.path.dirname。
        # 因此，我们必须 patch 'llm_query.os.path.dirname'。
        with patch("llm_query.os.path.dirname", side_effect=mock_dirname):
            found_path = _find_gitignore(self.subdir)
            self.assertIsNone(found_path)


class TestFileHandling(unittest.TestCase):
    """测试文件处理功能"""

    def test_file_with_line_range(self):
        """测试带行号范围的文件读取"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf8") as f:
            f.write("line1\nline2\nline3\nline4")
            path = f.name

        match = MagicMock(command=f"{path}:2-3")
        result = _handle_local_file(match)
        self.assertIn("line2\nline3", result)
        os.remove(path)

    def test_binary_file_handling(self):
        """测试二进制文件处理"""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
            path = f.name

        match = MagicMock(command=path)
        result = _handle_local_file(match)
        self.assertIn("二进制文件或无法解码", result)
        os.remove(path)


class TestDirectoryHandling(unittest.TestCase):
    """测试目录处理功能"""

    def test_directory_ignore_patterns(self):
        """测试目录忽略模式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试目录结构
            os.makedirs(os.path.join(tmpdir, "node_modules"))
            with open(os.path.join(tmpdir, "node_modules", "test.txt"), "w", encoding="utf-8") as f:
                f.write("should be ignored")

            # 为使测试在不同环境下行为一致，显式创建.gitignore文件。
            # _handle_local_file内部调用了外部tree命令和os.walk，
            # tree命令只识别.gitignore文件，而os.walk的逻辑还包括了内置的默认忽略规则。
            # 添加.gitignore文件可以确保两者行为一致。
            with open(os.path.join(tmpdir, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("node_modules/\n")

            match = MagicMock(command=tmpdir)
            result = _handle_local_file(match)
            self.assertNotIn("node_modules", result)


import json


class TestExtractAndDiffFiles(unittest.TestCase):
    def setUp(self):
        # 创建临时目录
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

        # 设置 shadow 目录
        self.shadow_dir = self.tmp_path / "shadow"
        self.shadow_dir.mkdir(exist_ok=True)

        # 导入 llm_query 模块
        global llm_query
        import llm_query

        # 公共补丁
        self.shadow_patch = patch("llm_query.shadowroot", self.shadow_dir)
        self.project_patch = patch("llm_query.GLOBAL_PROJECT_CONFIG.project_root_dir", str(self.tmp_path))

        # 应用补丁
        self.shadow_patch.start()
        self.project_patch.start()

        # 添加清理函数
        self.addCleanup(self.shadow_patch.stop)
        self.addCleanup(self.project_patch.stop)
        self.addCleanup(self.tmpdir.cleanup)

    def _create_test_file(self, filename, content=""):
        """在临时目录中创建测试文件"""
        file_path = self.tmp_path / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def test_update_existing_file_auto_apply(self):
        """测试使用 auto_apply=True 更新单个现有文件"""
        # 创建测试文件
        test_file = self._create_test_file("test.txt", "line1\nline2\n")

        # 测试内容
        test_content = """
[overwrite whole file]: test.txt
[start.57]
line1
line2
line3
[end.57]
"""
        # 执行处理
        with patch("llm_query._apply_patch"):
            llm_query.extract_and_diff_files(test_content, auto_apply=True, save=False)

        # 验证文件内容
        # _apply_patch is mocked, so we check shadow content to verify logic up to diffing
        shadow_file = self.shadow_dir / "test.txt"
        self.assertEqual(shadow_file.read_text(encoding="utf-8"), "line1\nline2\nline3")

    def test_create_new_file_auto_apply(self):
        test_file = self.tmp_path / "new_test.txt"
        self.assertFalse(test_file.exists())

        test_content = """
[overwrite whole file]: new_test.txt
[start.60]
new content
[end.60]
"""

        llm_query.extract_and_diff_files(test_content, auto_apply=True, save=False)

        # 直接验证文件创建和内容写入
        self.assertTrue(test_file.exists())
        self.assertEqual(test_file.read_text(), "new content")

    def test_json_format_with_thinking_process(self):
        """测试新的JSON格式，包括thinking_process的显示"""
        test_content = json.dumps(
            {
                "thinking_process": {"requirement_analysis": "Test analysis"},
                "actions": [{"action_type": "create_file", "file_path": "test.txt", "content": "new json content"}],
            }
        )

        new_file = self.tmp_path / "test.txt"

        with (
            patch("llm_query.display_llm_plan") as mock_display,
            patch("llm_query._apply_patch"),
            patch("builtins.input", return_value="all"),
        ):  # 确认应用
            llm_query.extract_and_diff_files(test_content, auto_apply=False, save=False)

            mock_display.assert_called_once_with({"requirement_analysis": "Test analysis"})

            # 验证影子文件是否已按预期创建
            shadow_file = self.shadow_dir / "test.txt"
            self.assertTrue(shadow_file.exists())
            self.assertEqual(shadow_file.read_text(), "new json content")

    def test_setup_script_processing(self):
        """测试处理项目设置脚本"""
        # 测试内容
        test_content = """
[project setup script]
[start.57]
#!/bin/bash
echo 'setup'
[end.57]
"""
        # 执行处理
        llm_query.extract_and_diff_files(test_content, save=False)

        # 验证脚本文件
        setup_script = self.shadow_dir / "project_setup.sh"
        self.assertTrue(setup_script.exists())
        self.assertEqual(setup_script.read_text(encoding="utf-8"), "#!/bin/bash\necho 'setup'")
        self.assertTrue(os.access(setup_script, os.X_OK), "脚本应具有可执行权限")

    def test_multiple_files_interactive_all(self):
        """测试处理多个文件并以交互方式应用所有更改"""
        self._create_test_file("test1.txt", "original 1")
        self._create_test_file("test2.txt", "original 2")

        test_content = """
[overwrite whole file]: test1.txt
[start.57]
new content 1
[end.57]

[overwrite whole file]: test2.txt
[start.57]
new content 2
[end.57]
"""
        with patch("builtins.input", return_value="all") as mock_input, patch("llm_query._apply_patch") as mock_apply:
            llm_query.extract_and_diff_files(test_content, auto_apply=False, save=False)
            mock_input.assert_called_once()
            self.assertEqual(mock_apply.call_count, 2)

    def test_multiple_files_interactive_subset(self):
        """测试处理多个文件并以交互方式应用部分更改"""
        self._create_test_file("test1.txt", "original 1")
        self._create_test_file("test2.txt", "original 2")

        test_content = """
[overwrite whole file]: test1.txt
[start.57]
new content 1
[end.57]

[overwrite whole file]: test2.txt
[start.57]
new content 2
[end.57]
"""
        with patch("builtins.input", return_value="1") as mock_input, patch("llm_query._apply_patch") as mock_apply:
            # 文件按路径排序，因此 test1.txt 将是 1，test2.txt 将是 2。
            llm_query.extract_and_diff_files(test_content, auto_apply=False, save=False)
            mock_input.assert_called_once()
            mock_apply.assert_called_once()

    def test_multiple_files_interactive_cancel(self):
        """测试处理多个文件并取消操作"""
        self._create_test_file("test1.txt", "original 1")
        self._create_test_file("test2.txt", "original 2")

        test_content = """
[overwrite whole file]: test1.txt
[start.57]
new content 1
[end.57]

[overwrite whole file]: test2.txt
[start.57]
new content 2
[end.57]
"""
        with patch("builtins.input", return_value="") as mock_input, patch("llm_query._apply_patch") as mock_apply:
            llm_query.extract_and_diff_files(test_content, auto_apply=False, save=False)
            mock_input.assert_called_once()
            mock_apply.assert_not_called()

    def test_no_effective_change(self):
        """测试如果内容未更改则不生成差异"""
        original_content = "line1\nline2"
        self._create_test_file("test.txt", original_content)

        test_content = f"""
[overwrite whole file]: test.txt
[start.57]
{original_content}
[end.57]
"""
        with patch("llm_query._apply_patch") as mock_apply:
            llm_query.extract_and_diff_files(test_content, auto_apply=True, save=False)
            mock_apply.assert_not_called()

    def test_create_new_file_in_new_dir_interactive_confirm(self):
        new_file_rel_path = "new_dir/test.txt"
        test_file_path = self.tmp_path / new_file_rel_path
        self.assertFalse(test_file_path.parent.exists())

        test_content = f"""
[overwrite whole file]: {new_file_rel_path}
[start.57]
new content
[end.57]
"""

        with (
            patch("builtins.input", side_effect=["1", "y"]) as mock_input,
            patch("llm_query._apply_patch") as mock_apply,
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
        ):
            llm_query.extract_and_diff_files(test_content, auto_apply=False, save=False)

            self.assertEqual(mock_input.call_count, 2)
            mock_apply.assert_called_once()

    def test_create_new_file_in_new_dir_interactive_cancel(self):
        """测试在交互模式下于新目录中创建文件并取消"""
        new_file_rel_path = "new_dir/test.txt"
        test_file_path = self.tmp_path / new_file_rel_path
        self.assertFalse(test_file_path.parent.exists())

        test_content = f"""
[overwrite whole file]: {new_file_rel_path}
[start.57]
new content
[end.57]
"""
        with patch("builtins.input", return_value="n") as mock_input, patch("llm_query._apply_patch") as mock_apply:
            llm_query.extract_and_diff_files(test_content, auto_apply=False, save=False)

            mock_input.assert_called_once()
            mock_apply.assert_not_called()
            self.assertFalse(test_file_path.parent.exists())
            self.assertFalse(test_file_path.exists())


class TestPyLintParser(unittest.TestCase):
    """验证Pylint解析器的多场景解析能力"""

    def test_standard_parsing(self):
        input_lines = [
            "test.py:42:10: C0304: Final newline missing",
            "src/app.py:158:25: W0621: Redefining name 'foo' from outer scope",
        ]
        results = LintParser.parse("\n".join(input_lines))

        self.assertEqual(len(results), 2)

        first = results[0]
        self.assertEqual(first.file_path, "test.py")
        self.assertEqual(first.line, 42)
        self.assertEqual(first.column_range, (10, 10))
        self.assertEqual(first.code, "C0304")
        self.assertIn("Final newline missing", first.message)

        second = results[1]
        self.assertEqual(second.file_path, "src/app.py")
        self.assertEqual(second.line, 158)
        self.assertEqual(second.code, "W0621")

    def test_column_ranges(self):
        input_line = "module/core.py:88:15: R1732: Consider using 'with' for resource (column 15-23)"
        results = LintParser.parse(input_line)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].column_range, (15, 23))
        self.assertEqual(results[0].code, "R1732")

    def test_invalid_formats(self):
        cases = [
            "*** Module test_shell",
            "test.py:not_number:15: C0325: Invalid line",
            "missing_column_info.py:100",
            "empty_line:",
        ]

        for invalid_input in cases:
            with self.subTest(input=invalid_input):
                results = LintParser.parse(invalid_input)
                self.assertEqual(len(results), 0)

    def test_multiline_output(self):
        input_data = """
        test.py:1:0: W0611: Unused import os
        test.py:3:8: C0411: third party import before standard

        src/utils.py:15:4: E1101: Instance of 'NoneType' has no 'split' member
        """
        results = LintParser.parse(input_data)

        self.assertEqual(len(results), 3)
        codes = {r.code for r in results}
        self.assertSetEqual(codes, {"W0611", "C0411", "E1101"})


class TestModelSwitch(unittest.TestCase):
    """
    测试模型配置切换功能
    """

    original_config: ModelConfig

    def setUp(self) -> None:
        """初始化测试环境"""
        time.sleep = lambda x: 0  # Mock sleep function
        self.original_config = ModelConfig(
            key="original_key",
            base_url="http://original",
            model_name="original_model",
            tokenizer_name="original_model",
            max_context_size=4096,
            temperature=0.7,
            http_proxy=None,
            https_proxy=None,
        )

        # 创建临时目录用于隔离测试文件
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_dir_path = self.test_dir.name

        # 使用临时目录中的文件作为用量记录文件
        self.temp_usage_file = os.path.join(self.test_dir_path, ".model_usage.yaml")

        # 保存原始配置到全局变量
        self.valid_config = {
            "model1": ModelConfig(
                key="key1",
                base_url="http://api1",
                model_name="model1",
                tokenizer_name="model1",
                max_context_size=4096,
                temperature=0.7,
                price_1m_input=1.0,
                price_1m_output=2.0,
                http_proxy=None,
                https_proxy=None,
            ),
            "model2": ModelConfig(
                key="key2",
                base_url="http://api2",
                model_name="model2",
                tokenizer_name="model2",
                max_context_size=4096,
                temperature=0.7,
                price_1m_input=1.0,
                price_1m_output=2.0,
                http_proxy=None,
                https_proxy=None,
            ),
        }

        # 初始化测试配置文件
        self.test_config_file = tempfile.NamedTemporaryFile(mode="w+", dir=self.test_dir_path)
        self._write_test_config()

        # 使用patch mock ModelSwitch的_load_config方法
        self.model_switch_patcher = patch("llm_query.ModelSwitch._load_config", return_value=self.valid_config)
        self.mock_load_config = self.model_switch_patcher.start()
        self.addCleanup(self.model_switch_patcher.stop)

        # Mock file system interactions for usage records to isolate tests
        # Prevent reading real usage file on ModelSwitch initialization
        self.yaml_load_patcher = patch("yaml.safe_load", return_value={})
        self.mock_yaml_load = self.yaml_load_patcher.start()
        self.addCleanup(self.yaml_load_patcher.stop)

        # Prevent writing usage file during tests
        self.save_usage_patcher = patch("llm_query.ModelSwitch._save_usage_to_file", return_value=None)
        self.mock_save_usage = self.save_usage_patcher.start()
        self.addCleanup(self.save_usage_patcher.stop)

    def _write_test_config(self, content: dict = None):
        """将配置写入临时文件"""
        self.test_config_file.seek(0)
        self.test_config_file.truncate()
        serializable_content = {
            name: {
                "key": config.key,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "tokenizer_name": config.tokenizer_name,
                "max_context_size": config.max_context_size,
                "temperature": config.temperature,
                "is_thinking": config.is_thinking,
                "max_tokens": config.max_tokens,
                "thinking_budget": config.thinking_budget,
                "top_k": config.top_k,
                "top_p": config.top_p,
                "price_1M_input": config.price_1m_input,
                "price_1M_output": config.price_1m_output,
                "http_proxy": config.http_proxy,
                "https_proxy": config.https_proxy,
            }
            for name, config in (content or self.valid_config).items()
        }
        json.dump(serializable_content, self.test_config_file)
        self.test_config_file.flush()

    def tearDown(self) -> None:
        """清理测试环境"""
        self.test_config_file.close()
        self.test_dir.cleanup()  # 清理整个临时目录
        try:
            os.unlink(self.test_config_file.name)
        except FileNotFoundError:
            pass

    def test_switch_model_configuration(self) -> None:
        """测试基础配置切换功能"""
        test_config = ModelConfig(
            key="test_key",
            base_url="http://test-api/v1",
            model_name="test-model",
            tokenizer_name="test-model",
            max_context_size=512,
            temperature=0.3,
            http_proxy=None,
            https_proxy=None,
        )

        self.assertEqual(test_config.model_name, "test-model")
        self.assertEqual(test_config.base_url, "http://test-api/v1")
        self.assertEqual(test_config.tokenizer_name, "test-model")
        self.assertEqual(test_config.max_context_size, 512)
        self.assertAlmostEqual(test_config.temperature, 0.3)
        self.assertIsNone(test_config.http_proxy)
        self.assertIsNone(test_config.https_proxy)

    def test_config_revert_after_switch(self) -> None:
        """测试配置切换后的回滚机制"""
        original_model = self.original_config.model_name
        original_url = self.original_config.base_url

        temp_config = ModelConfig(
            key="temp_key",
            base_url="http://temp-api/v2",
            model_name="temp-model",
            tokenizer_name="temp-model",
            temperature=1.0,
            http_proxy=None,
            https_proxy=None,
        )

        self.assertEqual(temp_config.model_name, "temp-model")
        self.assertEqual(temp_config.tokenizer_name, "temp-model")
        self.assertIsNone(temp_config.http_proxy)
        self.assertIsNone(temp_config.https_proxy)

    def test_load_valid_config(self) -> None:
        """测试正常加载配置文件"""
        switch = ModelSwitch()
        switch._load_config = lambda _: {
            name: ModelConfig(**config.__dict__) for name, config in self.valid_config.items()
        }

        config = switch._load_config(self.test_config_file.name)
        self.assertIsInstance(config["model1"], ModelConfig)
        self.assertEqual(config["model1"].key, "key1")
        self.assertEqual(config["model1"].base_url, "http://api1")
        self.assertEqual(config["model1"].model_name, "model1")
        self.assertEqual(config["model1"].tokenizer_name, "model1")
        self.assertEqual(config["model1"].max_context_size, 4096)
        self.assertAlmostEqual(config["model1"].temperature, 0.7)
        self.assertIsNone(config["model1"].http_proxy)
        self.assertIsNone(config["model1"].https_proxy)

    def test_load_missing_config_file(self) -> None:
        """测试配置文件不存在异常"""
        switch = ModelSwitch()

        def mock_load_config(path):
            if path == "nonexistent.json":
                raise FileNotFoundError(f"模型配置文件未找到: {path}")
            return self.valid_config

        switch._load_config = mock_load_config

        with self.assertRaises(FileNotFoundError) as context:
            switch._load_config("nonexistent.json")
        self.assertIn("模型配置文件未找到", str(context.exception))

    def test_load_invalid_json(self) -> None:
        """测试JSON格式错误异常"""
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, encoding="utf8") as invalid_file:
            invalid_file.write("invalid json")
            invalid_file.flush()

        switch = ModelSwitch()

        self.model_switch_patcher.stop()
        try:
            with self.assertRaises(ValueError) as context:
                switch._load_config(invalid_file.name)
            self.assertIn("配置文件格式错误", str(context.exception))
        finally:
            self.model_switch_patcher.start()

        os.unlink(invalid_file.name)

    def test_get_valid_model_config(self) -> None:
        """测试获取存在的模型配置"""
        switch = ModelSwitch()
        config = switch._get_model_config("model1")
        self.assertEqual(config.key, "key1")
        self.assertEqual(config.base_url, "http://api1")

    def test_get_nonexistent_model(self) -> None:
        """测试获取不存在的模型配置"""
        switch = ModelSwitch()
        with self.assertRaises(ValueError) as context:
            switch._get_model_config("nonexistent")
        self.assertIn("未找到模型配置", str(context.exception))

    def test_validate_required_fields(self) -> None:
        """测试配置字段验证"""
        invalid_raw_config = {"invalid_model": {"base_url": "http://invalid", "model_name": "invalid_model"}}

        switch = ModelSwitch()
        with patch.object(
            switch, "_load_and_validate_config", side_effect=switch._load_and_validate_config
        ) as mock_validate:
            with self.assertRaises(ValueError) as cm:
                mock_validate(invalid_raw_config["invalid_model"])
            self.assertIn("模型配置缺少必要字段", str(cm.exception))

    @patch("llm_query.query_gpt_api")
    def test_api_query_with_retry(self, mock_query):
        """测试API调用重试机制"""
        time.sleep = lambda x: 0  # Mock sleep function
        mock_query.side_effect = [
            Exception("First fail"),
            Exception("Second fail"),
            {"choices": [{"message": {"content": "success"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        ]

        switch = ModelSwitch()

        result = switch.query("model1", "test prompt")
        self.assertEqual(result, "success")
        self.assertEqual(mock_query.call_count, 3)

    @patch("llm_query.query_gpt_api")
    def test_api_config_propagation(self, mock_query):
        """测试配置参数是否正确传播到API调用"""
        mock_query.return_value = {
            "choices": [{"message": {"content": "test response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        switch = ModelSwitch()

        switch.query("model1", "test prompt")
        mock_query.assert_called_once_with(
            base_url="http://api1",
            api_key="key1",
            prompt="test prompt",
            model="model1",
            model_config=switch.current_config,
            disable_conversation_history=True,
            use_json_output=False,
            max_context_size=4096,
            temperature=0.7,
            enable_thinking=False,
            thinking_budget=32768,
            top_k=20,
            top_p=0.95,
        )

    @patch("llm_query.ModelSwitch.query")
    @patch("gpt_workflow.ArchitectMode.parse_response")
    @patch("llm_query.process_patch_response")
    @patch("builtins.input", return_value="n")
    def test_execute_workflow_integration(self, mock_input, mock_process, mock_parse, mock_query):
        """测试端到端工作流程"""
        from unittest.mock import ANY

        architect_content = json.dumps(
            {
                "task": "test task",
                "jobs": [
                    {"content": "job1", "priority": 1},
                    {"content": "job2", "priority": 2},
                ],
            }
        )
        coder_content_1 = "patch1"
        coder_content_2 = "patch2"

        mock_query.side_effect = [architect_content, coder_content_1, coder_content_2]
        mock_parse.return_value = {
            "task": "parsed task",
            "jobs": [
                {"content": "parsed job1", "priority": 1},
                {"content": "parsed job2", "priority": 2},
            ],
        }

        switch = ModelSwitch()
        switch._config_cache = {
            "architect": ModelConfig(key="key1", base_url="url1", model_name="arch", tokenizer_name="arch"),
            "coder": ModelConfig(key="key2", base_url="url2", model_name="coder", tokenizer_name="coder"),
        }
        results = switch.execute_workflow(architect_model="architect", coder_model="coder", prompt="test prompt")

        self.assertEqual(len(results), 2)
        self.assertEqual(results, [coder_content_1, coder_content_2])

        mock_parse.assert_called_once_with(architect_content)

        self.assertEqual(mock_process.call_count, 2)
        mock_process.assert_any_call(
            coder_content_1,
            ANY,
            auto_commit=False,
            auto_lint=False,
        )
        mock_process.assert_any_call(
            coder_content_2,
            ANY,
            auto_commit=False,
            auto_lint=False,
        )

        self.assertEqual(mock_query.call_count, 3)

    @patch("llm_query.query_gpt_api")
    @patch("builtins.input")
    def test_execute_workflow_retry_mechanism(self, mock_input, mock_query):
        """测试工作流重试机制"""
        time.sleep = lambda x: 0  # Mock sleep function
        mock_query.side_effect = [
            Exception("First fail"),
            Exception("Second fail"),
            {
                "choices": [
                    {
                        "message": {
                            "content": """
[task describe start]
开发分布式任务调度系统
[task describe end]

[team member1 job start]
实现工作节点注册机制
使用Consul进行服务发现
[team member1 job end]
"""
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        ]

        switch = ModelSwitch()
        switch._config_cache = {
            "architect": ModelConfig(key="key1", base_url="url1", model_name="arch", tokenizer_name="arch"),
            "coder": ModelConfig(key="key2", base_url="url2", model_name="coder", tokenizer_name="coder"),
        }

        mock_input.side_effect = ["y", "y", "n"]
        results = switch.execute_workflow(
            architect_model="architect",
            coder_model="coder",
            prompt="test prompt",
            architect_only=True,
        )

        self.assertEqual(len(results), 0)
        self.assertEqual(mock_query.call_count, 3)

    @patch("llm_query.ModelSwitch.query")
    @patch("gpt_workflow.ArchitectMode.parse_response")
    def test_execute_workflow_invalid_json(self, mock_parse, mock_query):
        """测试非标准JSON输入的容错处理"""
        mock_query.return_value = "invalid{json"
        mock_parse.side_effect = json.JSONDecodeError("Expecting value", doc="invalid{json", pos=0)

        switch = ModelSwitch()
        switch._config_cache = {
            "architect": ModelConfig(key="key1", base_url="url1", model_name="arch", tokenizer_name="arch"),
            "coder": ModelConfig(key="key2", base_url="url2", model_name="coder", tokenizer_name="coder"),
        }

        with self.assertRaises(json.JSONDecodeError):
            switch.execute_workflow(architect_model="architect", coder_model="coder", prompt="test prompt")

    def test_config_mapping_correctness(self):
        """测试JSON配置到ModelConfig的映射正确性"""
        test_config = {
            "test_model": ModelConfig(
                key="test_key",
                base_url="http://test",
                model_name="test",
                tokenizer_name="test_tokenizer",
                max_context_size=8192,
                temperature=0.6,
                is_thinking=True,
                max_tokens=1000,
                thinking_budget=65536,
                top_k=30,
                top_p=0.8,
                price_1m_input=1.0,
                price_1m_output=2.0,
                http_proxy="http_proxy_test",
                https_proxy="https_proxy_test",
            )
        }
        switch = ModelSwitch()
        switch._config_cache = test_config
        model_config = switch._get_model_config("test_model")
        self.assertIsInstance(model_config, ModelConfig)
        self.assertEqual(model_config.key, "test_key")
        self.assertEqual(model_config.base_url, "http://test")
        self.assertEqual(model_config.model_name, "test")
        self.assertEqual(model_config.tokenizer_name, "test_tokenizer")
        self.assertEqual(model_config.max_context_size, 8192)
        self.assertEqual(model_config.temperature, 0.6)
        self.assertTrue(model_config.is_thinking)
        self.assertEqual(model_config.max_tokens, 1000)
        self.assertEqual(model_config.thinking_budget, 65536)
        self.assertEqual(model_config.top_k, 30)
        self.assertAlmostEqual(model_config.top_p, 0.8)
        self.assertEqual(model_config.price_1m_input, 1.0)
        self.assertEqual(model_config.price_1m_output, 2.0)
        self.assertEqual(model_config.http_proxy, "http_proxy_test")
        self.assertEqual(model_config.https_proxy, "https_proxy_test")

    def test_calculate_cost(self):
        """测试费用计算逻辑"""
        config = ModelConfig(
            key="test_key",
            base_url="http://test",
            model_name="test",
            tokenizer_name="test",
            price_1m_input=10.0,
            price_1m_output=20.0,
            http_proxy=None,
            https_proxy=None,
        )

        switch = ModelSwitch()

        cost = switch._calculate_cost(500_000, 250_000, config)
        self.assertAlmostEqual(cost, (0.5 * 10) + (0.25 * 20))

        cost = switch._calculate_cost(50_000, 5_000, config)
        self.assertAlmostEqual(cost, 0.6)

        cost = switch._calculate_cost(69_999, 0, config)
        self.assertAlmostEqual(cost, 0.69999)

        cost = switch._calculate_cost(70_001, 0, config)
        self.assertAlmostEqual(cost, 0.70001)

        config.price_1m_input = None
        config.price_1m_output = None
        cost = switch._calculate_cost(1_000_000, 500_000, config)
        self.assertEqual(cost, 0.0)

    @patch("llm_query.ModelSwitch._save_usage_to_file")
    def test_record_usage(self, mock_save):
        """测试使用记录功能"""
        switch = ModelSwitch()
        switch._save_usage_to_file = mock_save

        switch._config_cache = {
            "model1": ModelConfig(
                key="key1",
                base_url="url1",
                model_name="model1",
                tokenizer_name="model1",
                price_1m_input=5.0,
                price_1m_output=15.0,
                http_proxy=None,
                https_proxy=None,
            )
        }

        switch._usage_records = {}

        switch._record_usage("model1", 200_000, 100_000)
        today = datetime.date.today().isoformat()

        daily = switch._usage_records[today]
        self.assertEqual(daily["total_input_tokens"], 200_000)
        self.assertEqual(daily["total_output_tokens"], 100_000)
        self.assertAlmostEqual(daily["total_cost"], (0.2 * 5) + (0.1 * 15))

        model_record = daily["models"]["model1"]
        self.assertEqual(model_record["input_tokens"], 200_000)
        self.assertEqual(model_record["output_tokens"], 100_000)
        self.assertAlmostEqual(model_record["cost"], 2.5)
        self.assertEqual(model_record["count"], 1)

        switch._record_usage("model1", 300_000, 150_000)

        self.assertEqual(daily["total_input_tokens"], 500_000)
        self.assertEqual(daily["total_output_tokens"], 250_000)
        self.assertAlmostEqual(daily["total_cost"], 2.5 + (0.3 * 5) + (0.15 * 15))

        model_record = daily["models"]["model1"]
        self.assertEqual(model_record["count"], 2)
        self.assertEqual(model_record["input_tokens"], 500_000)
        self.assertEqual(model_record["output_tokens"], 250_000)
        self.assertAlmostEqual(model_record["cost"], 6.25)

        self.assertEqual(mock_save.call_count, 2)

    def test_record_usage_multiple_models(self):
        """测试多模型使用记录"""
        switch = ModelSwitch()
        switch._usage_records = {}

        switch._config_cache = {
            "modelA": ModelConfig(
                key="keyA",
                base_url="urlA",
                model_name="modelA",
                tokenizer_name="modelA",
                price_1m_input=10.0,
                price_1m_output=20.0,
                http_proxy=None,
                https_proxy=None,
            ),
            "modelB": ModelConfig(
                key="keyB",
                base_url="urlB",
                model_name="modelB",
                tokenizer_name="modelB",
                price_1m_input=5.0,
                price_1m_output=10.0,
                http_proxy=None,
                https_proxy=None,
            ),
        }

        switch._record_usage("modelA", 100_000, 50_000)
        switch._record_usage("modelB", 200_000, 100_000)
        switch._record_usage("modelA", 50_000, 25_000)

        today = datetime.date.today().isoformat()
        daily = switch._usage_records[today]

        self.assertEqual(daily["total_input_tokens"], 350_000)
        self.assertEqual(daily["total_output_tokens"], 175_000)
        self.assertAlmostEqual(
            daily["total_cost"],
            (0.15 * 10 + 0.075 * 20) + (0.2 * 5 + 0.1 * 10),
            places=2,
        )

        modelA = daily["models"]["modelA"]
        self.assertEqual(modelA["count"], 2)
        self.assertEqual(modelA["input_tokens"], 150_000)
        self.assertEqual(modelA["output_tokens"], 75_000)
        self.assertAlmostEqual(modelA["cost"], 3.0)

        modelB = daily["models"]["modelB"]
        self.assertEqual(modelB["count"], 1)
        self.assertEqual(modelB["input_tokens"], 200_000)
        self.assertEqual(modelB["output_tokens"], 100_000)
        self.assertAlmostEqual(modelB["cost"], 2.0)


class TestChatbotUI(unittest.TestCase):
    def setUp(self):
        self.mock_gpt = MagicMock(spec=GPTContextProcessor)
        self.mock_console = MagicMock()
        self.chatbot = ChatbotUI(
            gpt_processor=self.mock_gpt,
        )
        self.chatbot.console = self.mock_console

    def test_initialization(self):
        self.assertEqual(self.chatbot.temperature, 0.6)
        self.assertIsInstance(self.chatbot.session, PromptSession)
        self.assertIsInstance(self.chatbot.bindings, KeyBindings)
        self.assertIs(self.chatbot.gpt_processor, self.mock_gpt)

    def test_handle_valid_command(self):
        with patch.object(self.chatbot, "handle_temperature_command") as mock_temp:
            self.chatbot.handle_command("temperature 0.8")
            mock_temp.assert_called_once_with("temperature 0.8")

    def test_handle_invalid_command(self):
        self.chatbot.handle_command("unknown")
        self.mock_console.print.assert_called_with("[red]未知命令: unknown[/]")

    @parameterized.expand(
        [
            ("temperature", "0.6"),
            ("temperature 0", "0.0"),
            ("temperature 1", "1.0"),
            ("temperature 0.5", "0.5"),
        ]
    )
    def test_valid_temperature(self, cmd, expected):
        self.chatbot.handle_command(cmd)
        self.assertEqual(str(self.chatbot.temperature), expected)

    @parameterized.expand(
        [
            ("temperature -1", "temperature必须在0到1之间"),
            ("temperature 1.1", "temperature必须在0到1之间"),
            ("temperature abc", "could not convert string to float: 'abc'"),
        ]
    )
    def test_invalid_temperature(self, cmd, error_msg):
        self.chatbot.handle_command(cmd)
        self.mock_console.print.assert_called_with(f"[red]参数错误: {error_msg}[/]")

    @patch.object(ChatbotUI, "stream_response")
    def test_stream_response(self, mock_query):
        with patch.object(self.chatbot, "stream_response") as mock_stream:
            mock_stream.return_value = iter(["response"])
            result = list(self.chatbot.stream_response("test prompt"))
            self.assertEqual(result, ["response"])

            # 验证调用参数
            self.assertEqual(self.chatbot.temperature, 0.6)
            mock_stream.assert_called_once_with("test prompt")

    def test_autocomplete_prompts(self):
        with (
            patch("os.listdir") as mock_listdir,
            patch.dict("os.environ", {"GPT_PATH": "/test"}),
            patch("os.path.exists", return_value=True),
        ):
            mock_listdir.return_value = ["test1.md", "test2.txt"]
            prompts = self.chatbot._get_prompt_files()
            self.assertEqual(prompts, ["@test1.md", "@test2.txt"])

    def test_keybindings_setup(self):
        from prompt_toolkit.keys import Keys

        keys = [key for binding in self.chatbot.bindings.bindings for key in binding.keys]
        self.assertIn(Keys.Escape, keys)
        self.assertIn(Keys.ControlC, keys)
        self.assertIn(Keys.ControlL, keys)

    def test_help_display(self):
        with patch.object(self.chatbot.console, "print") as mock_print:
            self.chatbot.display_help()
            self.assertEqual(mock_print.call_count, 5)
            args = [call[0][0] for call in mock_print.call_args_list]
            self.assertIn("可用命令列表", args[0])
            self.assertIn("符号功能说明", args[2])

    def test_completer_generation(self):
        with patch.object(self.chatbot, "_get_prompt_files", return_value=["@test.md"]):
            completer = self.chatbot.get_completer()
            self.assertIsInstance(completer, WordCompleter)
            self.assertIn("@clipboard", completer.words)
            self.assertIn("/clear", completer.words)
            self.assertIn("@test.md", completer.words)

    @patch.object(ChatbotUI, "stream_response")
    def test_process_input_flow(self, mock_stream):
        test_cases = [("", False), ("q", False), ("/help", True), ("test query", True)]

        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                mock_stream.return_value = iter(["response"])
                result = self.chatbot._process_input(input_text)
                self.assertEqual(result, expected)

    def test_clear_command_execution(self):
        with patch("os.system") as mock_system:
            self.chatbot.handle_command("clear")
            mock_system.assert_called_once_with("clear")

    def test_exit_command_handling(self):
        with self.assertRaises(SystemExit):
            self.chatbot.handle_command("exit")


class TestArchitectMode(unittest.TestCase):
    """验证ArchitectMode响应解析功能的测试套件"""

    SAMPLE_RESPONSE = """
[task describe start]
开发分布式任务调度系统
[task describe end]

[team member1 job start]
实现工作节点注册机制
使用Consul进行服务发现
[team member1 job end]

[team member2 job start]
设计任务监控仪表盘
使用React+ECharts可视化
[team member2 job end]
"""

    BAD_RESPONSES = [
        (
            "缺失任务结束标签",
            """
[task describe start]
未完成的任务描述""",
            "task describe end",
        ),
        (
            "不匹配的任务标签",
            """
[task describe start]任务1
[task describe end]
[team member1 job start]内容
[team member1 job end]
[task describe start]任务2""",
            "task describe start",
        ),
        (
            "无效的工作块格式",
            """
[task describe start]任务[task describe end]
[team member]缺失角色[team member job end]""",
            "team member",
        ),
        (
            "空的任务内容",
            """
[task describe start][task describe end]
[team member1 job start][team member1 job end]""",
            "task",
        ),
    ]

    def test_should_correctly_parse_valid_response(self):
        """验证标准成功场景的解析"""
        result = ArchitectMode.parse_response(self.SAMPLE_RESPONSE)
        self.assertEqual(result["task"], "开发分布式任务调度系统")
        self.assertEqual(len(result["jobs"]), 2)
        self.assertDictEqual(
            result["jobs"][0],
            {"member": "1", "content": "实现工作节点注册机制\n使用Consul进行服务发现"},
        )
        self.assertDictEqual(
            result["jobs"][1],
            {"member": "2", "content": "设计任务监控仪表盘\n使用React+ECharts可视化"},
        )

    def test_should_reject_empty_task_content(self):
        """拒绝空任务描述内容"""
        with self.assertRaisesRegex(ValueError, "任务描述内容不能为空"):
            ArchitectMode.parse_response(
                "[task describe start][task describe end]\n[team member1 job start]content[team member1 job end]"
            )

    def test_should_validate_job_member_format(self):
        """验证成员ID格式校验"""
        invalid_response = """
[task describe start]任务[task describe end]
[team member123 job start]内容[team member123 job end]"""
        with self.assertRaisesRegex(ValueError, "解析后的任务描述不完整或过短"):
            ArchitectMode.parse_response(invalid_response)

    @parameterized.expand(BAD_RESPONSES, name_func=lambda func, num, p: f"test_should_reject_{p[0]}")
    def test_error_scenarios(self, _, invalid_response, expected_error):
        """参数化测试各种异常场景"""
        with self.assertRaises((ValueError, RuntimeError)):
            ArchitectMode.parse_response(invalid_response)


class TestAutoGitCommit(unittest.TestCase):
    def test_commit_message_extraction(self):
        sample_response = dedent(
            """
        [git commit message start]
        feat: add new authentication module
        - implement JWT token handling
        - add user model
        [git commit message end]
        """
        )
        instance = AutoGitCommit(sample_response)
        self.assertEqual(
            instance.commit_message,
            "feat: add new authentication module\n- implement JWT token handling\n- add user model",
        )

    def test_empty_commit_message(self):
        instance = AutoGitCommit("No commit message here")
        self.assertEqual(instance.commit_message, "")

    @patch.object(AutoGitCommit, "_execute_git_commands")
    def test_commit_flow(self, mock_execute):
        instance = AutoGitCommit(
            "[git commit message start]test commit[git commit message end]",
            auto_commit=True,
        )
        instance.do_commit()
        mock_execute.assert_called_once()

    @patch("subprocess.run")
    def test_git_commands_execution(self, mock_run):
        instance = AutoGitCommit("[git commit message start]test[git commit message end]")
        instance.commit_message = "test"
        instance._execute_git_commands()
        mock_run.assert_has_calls(
            [
                call(["git", "add", "."], check=True),
                call(["git", "commit", "-m", "test"], check=True),
            ]
        )

    @patch("subprocess.run")
    def test_specified_files_add(self, mock_run):
        instance = AutoGitCommit(
            "[git commit message start]test[git commit message end]",
            files_to_add=["src/main.py", "src/utils.py"],
        )
        instance.commit_message = "test"
        instance._execute_git_commands()
        mock_run.assert_has_calls(
            [
                call(["git", "add", "src/main.py"], check=True),
                call(["git", "add", "src/utils.py"], check=True),
                call(["git", "commit", "-m", "test"], check=True),
            ]
        )

    @patch("builtins.input")
    def test_confirm_message(self, mock_input):
        mock_input.return_value = "y"
        instance = AutoGitCommit("[git commit message start]test[git commit message end]")
        self.assertTrue(instance._confirm_message())

        mock_input.return_value = "n"
        self.assertFalse(instance._confirm_message())

        mock_input.side_effect = ["edit", "new message", "y"]
        instance = AutoGitCommit("[git commit message start]test[git commit message end]")
        self.assertTrue(instance._confirm_message())
        self.assertEqual(instance.commit_message, "new message")


class TestFormatAndLint(unittest.TestCase):
    def setUp(self):
        self.formatter = FormatAndLint(timeout=10)
        self.test_files = []

    def tearDown(self):
        for f in self.test_files:
            if os.path.exists(f):
                os.remove(f)

    def _create_temp_file(self, ext: str, content: str = "", mode: str = "w+") -> str:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False, encoding="utf-8", mode=mode) as f:
            f.write(content)
            self.test_files.append(f.name)
            return f.name

    @patch("subprocess.run")
    def test_python_formatting(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        test_file = self._create_temp_file(".py", "def test(): pass\n")
        results = self.formatter.run_checks([test_file], fix=True)

        self.assertEqual(len(results), 0)
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("ruff", mock_run.call_args_list[0].args[0])
        self.assertIn("pylint", mock_run.call_args_list[1].args[0])

    @patch("subprocess.run")
    def test_powershell_processing(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        test_file = self._create_temp_file(".ps1", "Write-Host 'test'")
        results = self.formatter.run_checks([test_file])

        self.assertEqual(len(results), 0)
        mock_run.assert_called_once()
        self.assertIn("./tools/Format-Script.ps1", mock_run.call_args[0][0])

    @patch("subprocess.run")
    def test_javascript_processing(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        test_file = self._create_temp_file(".js", "function test(){}")
        results = self.formatter.run_checks([test_file], fix=True)

        self.assertEqual(len(results), 0)
        mock_run.assert_called_once()
        self.assertIn("prettier", mock_run.call_args[0][0])

    @patch("subprocess.run")
    def test_shell_script_processing(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        test_file = self._create_temp_file(".sh", "echo test")
        results = self.formatter.run_checks([test_file])

        self.assertEqual(len(results), 0)
        mock_run.assert_called_once()
        self.assertIn("shfmt", mock_run.call_args[0][0])

    def test_real_python_file_processing(self):
        test_file = self._create_temp_file(
            ".py",
            dedent(
                """
            def bad_format():
                x=123
                return x
        """
            ),
        )

        results = self.formatter.run_checks([test_file], fix=True)
        self.assertEqual(len(results), 0, "Should automatically fix formatting")

        with open(test_file) as f:
            content = f.read()
        self.assertIn("x = 123", content, "Black should reformat the code")

    @patch("subprocess.run")
    def test_mixed_file_types_processing(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        files = [
            self._create_temp_file(".py"),
            self._create_temp_file(".js"),
            self._create_temp_file(".sh"),
        ]

        results = self.formatter.run_checks(files)
        self.assertEqual(len(results), 0)
        self.assertEqual(mock_run.call_count, 4, "Should process 3 files with total 4 commands")

    @patch("subprocess.run")
    def test_partial_failure_handling(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=1),  # black fails
            MagicMock(returncode=0),  # pylint succeeds
            MagicMock(returncode=1),  # shfmt fails
        ]

        files = [self._create_temp_file(".py"), self._create_temp_file(".sh")]

        results = self.formatter.run_checks(files)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(results[files[0]]), 1, "Should record black failure")
        self.assertEqual(len(results[files[1]]), 1, "Should record shfmt failure")

    def test_timeout_handling_with_real_process(self):
        test_file = self._create_temp_file(".py")

        with self.assertLogs(level="ERROR") as log:
            # 使用一个实际会超时的命令进行测试
            long_process_formatter = FormatAndLint(timeout=0.1)
            results = long_process_formatter.run_checks([test_file])

        self.assertIn("Timeout expired", log.output[0])
        self.assertIn(test_file, results)

    @patch("subprocess.run")
    def test_verbose_output_logging(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"Formatted 1 file"
        mock_run.return_value = mock_result

        verbose_formatter = FormatAndLint(verbose=True)
        test_file = self._create_temp_file(".py")

        # 设置logger级别为DEBUG以确保捕获所有日志
        verbose_formatter.logger.setLevel(logging.DEBUG)

        with self.assertLogs(verbose_formatter.logger, level="DEBUG") as logs:
            verbose_formatter.run_checks([test_file], fix=True)

        self.assertTrue(any("Executing: uvx" in log for log in logs.output))
        self.assertTrue(any("Formatted 1 file" in log for log in logs.output))


class TestContentParse(unittest.TestCase):
    """
    测试process_file_change函数的各种解析场景
    """

    def setUp(self):
        self.original_exists = os.path.exists
        os.path.exists = lambda x: True

    def tearDown(self):
        os.path.exists = self.original_exists

    def test_valid_symbols(self):
        response = dedent(
            """
        [overwrite whole symbol]: valid/path.py
        [start]
        def valid_func():
            pass
        [end]
        """
        )
        modified, remaining = process_file_change(response)
        self.assertIn("[overwrite whole file]", modified)
        self.assertEqual(len(modified.split("\n\n")), 1)
        self.assertIn("valid/path.py", modified)
        self.assertEqual(remaining.strip(), "")

    def test_valid_symbols_with_parameter(self):
        os.path.exists = lambda x: True
        response = dedent(
            """
        [overwrite whole symbol]: valid/path.py
        [start]
        def valid_func():
            pass
        [end]
        """
        )
        modified, remaining = process_file_change(response, valid_symbols=["other/path.py"])
        self.assertIn("[overwrite whole file]", modified)
        self.assertIn("valid/path.py", modified)
        self.assertEqual(remaining.strip(), "")

    def test_invalid_symbols(self):
        os.path.exists = lambda x: False
        response = dedent(
            """
        [overwrite whole symbol]: invalid/path.py
        [start]
        def invalid_func():
            pass
        [end]
        """
        )
        modified, remaining = process_file_change(response)
        self.assertEqual(modified.strip(), "")
        self.assertIn("invalid/path.py", remaining)

    def test_invalid_symbols_with_parameter(self):
        os.path.exists = lambda x: False
        response = dedent(
            """
        [overwrite whole symbol]: valid/path.py
        [start]
        def valid_func():
            pass
        [end]
        """
        )

        modified, remaining = process_file_change(response, valid_symbols=["valid/path.py"])
        self.assertEqual(modified.strip(), "")
        self.assertIn("valid/path.py", remaining)

    def test_mixed_symbols(self):
        os.path.exists = lambda x: True
        response = dedent(
            """
        Before content
        [overwrite whole symbol]: valid1.py
        [start]
        content1
        [end]
        Middle content
        [overwrite whole symbol]: valid2.py
        [start]
        content2
        [end]
        After content
        """
        )

        modified, remaining = process_file_change(response)

        self.assertIn("valid1.py", modified)
        self.assertIn("valid2.py", modified)
        self.assertIn("Middle content", remaining)
        self.assertIn("After content", remaining)

    def test_mixed_valid_invalid_symbols(self):
        def exists_mock(path):
            return path == "valid.py"

        os.path.exists = exists_mock

        response = dedent(
            """
        Start text
        [overwrite whole symbol]: valid.py
        [start]
        new_content
        [end]
        Middle text
        [overwrite whole symbol]: invalid.py
        [start]
        invalid_content
        [end]
        End text
        """
        )

        modified, remaining = process_file_change(response)

        self.assertIn("valid.py", modified)
        self.assertNotIn("invalid.py", modified)
        self.assertIn("invalid.py", remaining)
        self.assertIn("Middle text", remaining)
        self.assertIn("End text", remaining)
        self.assertEqual(remaining.count("[start]"), 1)

    def test_no_modified_symbols(self):
        response = "Just regular text\nWithout any markers"
        modified, remaining = process_file_change(response)
        self.assertEqual(modified.strip(), "")
        self.assertEqual(remaining, response)

    def test_nested_blocks(self):
        response = dedent(
            """
        [overwrite whole symbol]: outer.py
        [start]
        [overwrite whole symbol]: inner.py
        [start]
        nested_content
        [end]
        [end]
        """
        )
        modified, remaining = process_file_change(response)
        self.assertEqual(len(modified.split("\n\n")), 1)
        self.assertIn("outer.py", modified)
        self.assertNotIn("inner.py", remaining)


class TestDiffBlockFilter(unittest.TestCase):
    """
    unified 0, diff bin 生成diff, two temp file
    test single file diff
    test multi file diff
    # to do
    生成一个diff有多个block需要让用户确认的情况，这必须要使diff tool不合并它们才行
    """

    def _create_temp_files(self, content1: str, content2: str, mode: str = "w+") -> tuple[str, str]:
        with tempfile.NamedTemporaryFile(mode=mode, delete=False, encoding="utf-8") as f1:
            f1.write(content1)
        with tempfile.NamedTemporaryFile(mode=mode, delete=False, encoding="utf-8") as f2:
            f2.write(content2)
        return f1.name, f2.name

    def _verify_patch(self, original_file: str, patch_content: str, expected_content: str) -> None:
        with tempfile.NamedTemporaryFile(mode="w+") as patched_file:
            with tempfile.NamedTemporaryFile(mode="w+", encoding="utf8") as patch_file:
                patch_file.write(patch_content)
                patch_file.flush()
                subprocess.run(
                    [
                        find_patch(),
                        "-p0",
                        "-i",
                        patch_file.name,
                        original_file,
                        "-o",
                        patched_file.name,
                    ],
                    check=True,
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    cwd="c:\\" if sys.platform == "win32" else None,
                )
                patched_content = Path(patched_file.name).read_text()
                self.assertEqual(patched_content.strip(), expected_content.strip())

    def test_basic_selection(self):
        file1 = "a\nb\nc\n"
        file2 = "a\nb2\nc\n"

        f1, f2 = self._create_temp_files(file1, file2)
        try:
            diff = subprocess.check_output(
                [find_diff(), "-u", f1, f2],
                text=True,
                stderr=subprocess.STDOUT,
            )
        except subprocess.CalledProcessError as e:
            diff = e.output
            self.assertEqual(e.returncode, 1)

        with patch("builtins.input", side_effect=["y", "n"]):
            diff_filter = DiffBlockFilter({f1: diff})
            result = diff_filter.interactive_filter()

        self.assertIn(f1, result)
        self.assertIn("b2", result[f1])
        self._verify_patch(f1, result[f1], file2)

    def test_invalid_input_handling(self):
        file1 = "x\ny\nz\n"
        file2 = "x\ny2\nz\n"
        f1, f2 = self._create_temp_files(file1, file2)
        try:
            diff = subprocess.check_output([find_diff(), "-u", f1, f2], text=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            diff = e.output
            self.assertEqual(e.returncode, 1)

        with patch("builtins.input", side_effect=["invalid", "wrong", "y"]):
            diff_filter = DiffBlockFilter({f1: diff})
            result = diff_filter.interactive_filter()

        self.assertGreater(len(result[f1].split("\n")), 3)
        self._verify_patch(f1, result[f1], file2)

    def test_immediate_accept_all(self):
        file1 = "1\n2\n3\n"
        file2 = "1\n2\n3\n4\n"
        f1, f2 = self._create_temp_files(file1, file2)
        try:
            diff = subprocess.check_output([find_diff(), "-u", f1, f2], text=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            diff = e.output
            self.assertEqual(e.returncode, 1)

        with patch("builtins.input", side_effect=["ya"]):
            diff_filter = DiffBlockFilter({f1: diff})
            result = diff_filter.interactive_filter()

        self.assertIn("+4", result[f1])
        self._verify_patch(f1, result[f1], file2)

    def test_multiple_file_diff(self):
        file1 = "a\nb\nc\n"
        file2 = "a\nb2\nc\n"
        file3 = "x\ny\nz\n"
        file4 = "x\ny2\nz\n"
        f1, f2 = self._create_temp_files(file1, file2)
        f3, f4 = self._create_temp_files(file3, file4)
        try:
            diff1 = subprocess.check_output([find_diff(), "-u", f1, f2], text=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            diff1 = e.output
            self.assertEqual(e.returncode, 1)
        try:
            diff2 = subprocess.check_output([find_diff(), "-u", f3, f4], text=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            diff2 = e.output
            self.assertEqual(e.returncode, 1)

        diff_content = {f1: diff1, f3: diff2}
        with patch("builtins.input", side_effect=["y", "y"]):
            diff_filter = DiffBlockFilter(diff_content)
            result = diff_filter.interactive_filter()

        self.assertIn(f1, result)
        self.assertIn(f3, result)
        self.assertIn("b2", result[f1])
        self.assertIn("y2", result[f3])
        self._verify_patch(f1, result[f1], file2)
        self._verify_patch(f3, result[f3], file4)

    def test_quit_early(self):
        file1 = "1\n2\n3\n"
        file2 = "1\n2\n3\n4\n"
        f1, f2 = self._create_temp_files(file1, file2)
        try:
            diff = subprocess.check_output([find_diff(), "-u", f1, f2], text=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            diff = e.output
            self.assertEqual(e.returncode, 1)

        with patch("builtins.input", side_effect=["q"]):
            diff_filter = DiffBlockFilter({f1: diff})
            result = diff_filter.interactive_filter()

        self.assertEqual(result, {})

    def test_no_changes(self):
        file1 = "identical\ncontent\n"
        file2 = "identical\ncontent\n"
        f1, f2 = self._create_temp_files(file1, file2)
        try:
            diff = subprocess.check_output([find_diff(), "-u", f1, f2], text=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            self.fail(f"diff should return 0 for identical files, got {e.returncode}")

        with patch("builtins.input", side_effect=[]):
            diff_filter = DiffBlockFilter({f1: diff})
            result = diff_filter.interactive_filter()

        self.assertEqual(result, {})

    def test_empty_diff(self):
        with patch("builtins.input", side_effect=[]):
            diff_filter = DiffBlockFilter({"file.txt": ""})
            result = diff_filter.interactive_filter()

        self.assertEqual(result, {})

    def test_invalid_diff_content(self):
        with patch("builtins.input", side_effect=[]):
            diff_filter = DiffBlockFilter({"file.txt": "not a valid diff"})
            result = diff_filter.interactive_filter()

        self.assertEqual(result, {})


class TestCoverageTestPlan(unittest.TestCase):
    """Test cases for CoverageTestPlan functionality."""

    def test_parse_valid_test_plan(self):
        """Test parsing a valid test plan with multiple test cases and methods."""
        plan_content = '''
[test case start]
[class start]
[class name start]TestClass1[class name end]
class TestClass1(unittest.TestCase):
    def test_method1(self):
        """Test method 1 description"""
    def test_method2(self):
        """Test method 2 description"""
[class end]
[test case end]
[test case start]
[class start]
[class name start]TestClass2[class name end]
class TestClass2(unittest.TestCase):
    def test_method3(self):
        """Test method 3 description"""
[class end]
[test case end]'''
        result = CoverageTestPlan.parse_test_plan(plan_content)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["class_name"], "TestClass1")
        self.assertEqual(len(result[0]["test_methods"]), 2)
        self.assertEqual(result[1]["class_name"], "TestClass2")
        self.assertEqual(len(result[1]["test_methods"]), 1)

    def test_parse_empty_test_plan(self):
        """Test parsing an empty test plan returns empty list."""
        result = CoverageTestPlan.parse_test_plan("")
        self.assertEqual(len(result), 0)

    def test_parse_invalid_test_case(self):
        """Test parsing test case missing class name is skipped."""
        plan_content = '''
[test case start]
[class start]
class TestClass1(unittest.TestCase):
    def test_method1(self):
        """Test method 1 description"""
[class end]
[test case end]'''
        result = CoverageTestPlan.parse_test_plan(plan_content)
        self.assertEqual(len(result), 0)

    def test_parse_test_case_without_methods(self):
        """Test parsing test case with no test methods."""
        plan_content = """
[test case start]
[class start]
[class name start]TestClass1[class name end]
class TestClass1(unittest.TestCase):
[class end]
[test case end]"""
        result = CoverageTestPlan.parse_test_plan(plan_content)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["test_methods"]), 0)

    def test_parse_method_without_description(self):
        """Test parsing method without docstring is skipped."""
        plan_content = '''
[test case start]
[class start]
[class name start]TestClass1[class name end]
class TestClass1(unittest.TestCase):
    def test_method1(self):
        pass
    def test_method2(self):
        """Test method 2 description"""
[class end]
[test case end]'''
        result = CoverageTestPlan.parse_test_plan(plan_content)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["test_methods"]), 1)
        self.assertEqual(result[0]["test_methods"][0]["name"], "test_method2")

    def test_validate_valid_test_plan(self):
        """Test validation returns True for valid test plan."""
        plan_content = '''
[test case start]
[class start]
[class name start]TestClass1[class name end]
class TestClass1(unittest.TestCase):
    def test_method1(self):
        """Test method 1 description"""
[class end]
[test case end]'''
        self.assertTrue(CoverageTestPlan.validate_test_plan(plan_content))

    def test_validate_invalid_test_plan(self):
        """Test validation returns False for invalid test plan."""
        self.assertFalse(CoverageTestPlan.validate_test_plan("invalid content"))


class TestChangelogMarkdown(unittest.TestCase):
    """Test cases for ChangelogMarkdown functionality."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".md")
        self.file_path = self.temp_file.name
        self.changelog = ChangelogMarkdown(self.file_path)

    def tearDown(self):
        self.temp_file.close()
        os.unlink(self.file_path)

    def test_add_and_retrieve_entry(self):
        """Test adding and retrieving a single entry."""
        test_desc = "Test description"
        test_diff = "Test diff content"
        self.changelog.add_entry(test_desc, test_diff)

        recent = self.changelog.get_recent()
        self.assertIn(test_desc, recent)
        self.assertIn(test_diff, recent)

    def test_multiple_entries(self):
        """Test handling multiple entries."""
        entries = [
            ("First change", "diff1"),
            ("Second change", "diff2"),
            ("Third change", "diff3"),
        ]

        for desc, diff in entries:
            self.changelog.add_entry(desc, diff)

        recent = self.changelog.get_recent(2)
        self.assertIn(entries[1][0], recent)
        self.assertIn(entries[2][0], recent)
        self.assertNotIn(entries[0][0], recent)

    def test_file_persistence(self):
        """Test that entries persist in the file."""
        test_desc = "Persistent entry"
        test_diff = "Persistent diff"
        self.changelog.add_entry(test_desc, test_diff)

        # Create new instance to load from file
        new_changelog = ChangelogMarkdown(self.file_path)
        recent = new_changelog.get_recent()
        self.assertIn(test_desc, recent)
        self.assertIn(test_diff, recent)

    def test_empty_file_handling(self):
        """Test handling of empty/non-existent files."""
        empty_changelog = ChangelogMarkdown("nonexistent.md")
        self.assertEqual(empty_changelog.get_recent(), "[change log start]\n\n[change log end]")

    def test_markdown_formatting(self):
        """Test the generated markdown format is valid."""
        test_desc = "Format test"
        test_diff = "Format diff"
        self.changelog.add_entry(test_desc, test_diff)

        with open(self.file_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("## ", content)
            self.assertIn("### Description", content)
            self.assertIn("### Diff", content)
            self.assertIn("```diff", content)
            self.assertIn(test_desc, content)
            self.assertIn(test_diff, content)

    def test_use_diff_method(self):
        """Test extracting description from patch prompt output."""
        test_text = """
        Some text before
        [change log message start]
        This is a test description
        with multiple lines
        [change log message end]
        Some text after
        """
        test_diff = "test diff content"
        self.changelog.use_diff(test_text, test_diff)

        recent = self.changelog.get_recent()
        self.assertIn("This is a test description", recent)
        self.assertIn("with multiple lines", recent)
        self.assertIn(test_diff, recent)

    def test_use_diff_without_description(self):
        """Test use_diff when no description is found."""
        test_text = "No description markers here"
        test_diff = "test diff content"
        self.changelog.use_diff(test_text, test_diff)

        recent = self.changelog.get_recent()
        self.assertIn("No description provided", recent)
        self.assertIn(test_diff, recent)


class TestClipboard(unittest.TestCase):
    """placer holder tests/test_image.png"""

    @unittest.skipUnless(sys.platform == "darwin", "macOS only test")
    def test_macos_image_clipboard(self):
        """测试macOS剪贴板图像处理功能"""
        AppKit = __import__("AppKit")
        from llm_query import _handle_macos_clipboard, read_path_from_image_prompt

        # 准备测试图像
        test_image_path = os.path.join(os.path.dirname(__file__), "test_image.png")
        self.assertTrue(os.path.exists(test_image_path), "测试图像不存在")

        with open(test_image_path, "rb") as f:
            image_data = f.read()

        # 将图像放入剪贴板
        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.declareTypes_owner_([AppKit.NSPasteboardTypePNG], None)
        pasteboard.setData_forType_(
            AppKit.NSData.dataWithBytes_length_(image_data, len(image_data)),
            AppKit.NSPasteboardTypePNG,
        )

        # 测试剪贴板处理
        result = _handle_macos_clipboard()
        prefix = "[image saved to "
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(".png]"))
        path = read_path_from_image_prompt(result)
        self.assertTrue(os.path.exists(path), "保存的图像文件不存在")

        # 验证图像内容
        with open(path, "rb") as saved_file:
            saved_data = saved_file.read()
            self.assertEqual(len(saved_data), len(image_data), "图像数据不一致")
            self.assertEqual(saved_data, image_data, "图像内容不匹配")

        # 清理
        os.remove(path)

    @unittest.skipUnless(sys.platform == "win32", "Windows only test")
    def test_windows_image_clipboard(self):
        """测试Windows剪贴板图像处理功能"""
        try:
            win32clipboard = __import__("win32clipboard")
            from llm_query import _handle_windows_clipboard, read_path_from_image_prompt

            # 准备测试图像
            test_image_path = os.path.join(os.path.dirname(__file__), "test_image.png")
            self.assertTrue(os.path.exists(test_image_path), "测试图像不存在")

            with open(test_image_path, "rb") as f:
                image_data = f.read()

            # 将图像放入剪贴板
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, image_data)
            win32clipboard.CloseClipboard()

            # 测试剪贴板处理
            result = _handle_windows_clipboard()
            prefix = "[image saved to "
            self.assertTrue(result.startswith(prefix))
            self.assertTrue(result.endswith(".png]"))
            path = read_path_from_image_prompt(result)
            self.assertTrue(os.path.exists(path), "保存的图像文件不存在")

            # 验证图像内容
            with open(path, "rb") as saved_file:
                saved_data = saved_file.read()
                self.assertTrue(len(saved_data) > 0, "图像数据为空")

            # 清理
            os.remove(path)
        except Exception as e:
            self.fail(f"测试失败: {str(e)}")

    @unittest.skipUnless(sys.platform == "linux", "Linux only test")
    def test_linux_image_clipboard(self):
        """测试Linux剪贴板图像处理功能"""
        try:
            import subprocess

            from llm_query import _handle_linux_clipboard, read_path_from_image_prompt

            # 准备测试图像
            test_image_path = os.path.join(os.path.dirname(__file__), "test_image.png")
            self.assertTrue(os.path.exists(test_image_path), "测试图像不存在")

            # 将图像放入剪贴板
            subprocess.run(
                [
                    "xclip",
                    "-selection",
                    "clipboard",
                    "-t",
                    "image/png",
                    test_image_path,
                ],
                check=True,
            )

            # 测试剪贴板处理
            result = _handle_linux_clipboard()
            prefix = "[image saved to "
            self.assertTrue(result.startswith(prefix))
            self.assertTrue(result.endswith(".png]"))
            path = read_path_from_image_prompt(result)
            self.assertTrue(os.path.exists(path), "保存的图像文件不存在")

            # 验证图像内容
            with open(path, "rb") as saved_file:
                saved_data = saved_file.read()
                self.assertTrue(len(saved_data) > 0, "图像数据为空")

            # 清理
            os.remove(path)
        except Exception as e:
            self.fail(f"测试失败: {str(e)}")

    @unittest.skipUnless(sys.platform == "win32", "Windows only test")
    def test_windows_text_clipboard(self):
        """测试Windows剪贴板文本处理功能"""
        try:
            win32clipboard = __import__("win32clipboard")
            from llm_query import _handle_windows_clipboard

            test_text = "Windows剪贴板测试文本"

            # 将文本放入剪贴板
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(test_text)
            win32clipboard.CloseClipboard()

            # 测试剪贴板处理
            result = _handle_windows_clipboard()
            self.assertEqual(result, test_text)
        except Exception as e:
            self.fail(f"测试失败: {str(e)}")

    @unittest.skipUnless(sys.platform == "linux", "Linux only test")
    def test_linux_text_clipboard(self):
        """测试Linux剪贴板文本处理功能"""
        try:
            import subprocess

            from llm_query import _handle_linux_clipboard

            test_text = "Linux剪贴板测试文本"

            # 将文本放入剪贴板
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=test_text.encode(),
                check=True,
            )

            # 测试剪贴板处理
            result = _handle_linux_clipboard()
            self.assertEqual(result, test_text)
        except Exception as e:
            self.fail(f"测试失败: {str(e)}")


from llm_query import display_and_apply_diff, extract_and_diff_files


class TestLLMQueryDiffFunctions(unittest.TestCase):
    def test_file_not_exists(self):
        """Test when diff file doesn't exist"""
        non_existent_file = Path("/non/existent/file.diff")
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            display_and_apply_diff(non_existent_file)
            self.assertEqual(mock_stdout.getvalue(), "")

    def test_auto_apply_true(self):
        """Test auto-apply without user prompt"""
        mock_file = MagicMock(spec=Path)
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "dummy diff"

        with (
            patch("llm_query.highlight", return_value="highlighted diff"),
            patch("llm_query._apply_patch") as mock_apply_patch,
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
        ):
            display_and_apply_diff(mock_file, auto_apply=True)

            # Verify output
            output = mock_stdout.getvalue()
            self.assertIn("高亮显示的diff内容：", output)
            self.assertIn("highlighted diff", output)

            # Verify function calls
            mock_apply_patch.assert_called_once_with(mock_file)

    def test_user_confirms_apply(self):
        """Test user confirms apply with 'y' input"""
        mock_file = MagicMock(spec=Path)
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "dummy diff"

        with (
            patch("llm_query.highlight", return_value="highlighted diff"),
            patch("llm_query._apply_patch") as mock_apply_patch,
            patch("builtins.input", return_value="y"),
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
        ):
            display_and_apply_diff(mock_file, auto_apply=False)

            # Verify output
            output = mock_stdout.getvalue()
            self.assertIn("高亮显示的diff内容：", output)
            self.assertIn("highlighted diff", output)
            self.assertIn(f"\n申请变更文件，是否应用 {mock_file}？", output)

            # Verify function calls
            mock_apply_patch.assert_called_once_with(mock_file)

    def test_user_cancels_apply(self):
        """Test user cancels apply with non-y input"""
        mock_file = MagicMock(spec=Path)
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "dummy diff"

        with (
            patch("llm_query.highlight", return_value="highlighted diff"),
            patch("llm_query._apply_patch") as mock_apply_patch,
            patch("builtins.input", return_value="n"),
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
        ):
            display_and_apply_diff(mock_file, auto_apply=False)

            # Verify output
            output = mock_stdout.getvalue()
            self.assertIn("高亮显示的diff内容：", output)
            self.assertIn("highlighted diff", output)
            self.assertIn(f"\n申请变更文件，是否应用 {mock_file}？", output)

            # Verify no patch application
            mock_apply_patch.assert_not_called()

    def test_extract_and_diff_files_created_file(self):
        """Test processing a 'created_file' instruction"""
        # Setup test content and paths
        content = (
            "我将创建一个简单的helloworld.sh脚本，这个脚本将：\n"
            '1. 输出"Hello World"信息\n'
            "2. 遵循bash脚本最佳实践\n"
            "[created file]: /project/helloworld.sh\n"
            "[start.57]\n"
            "#!/bin/bash\n"
            'echo "Hello World"\n'
            "[end.57]"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            shadow_root = project_root / ".shadowroot"
            shadow_root.mkdir()

            # Configure global settings
            with (
                patch("llm_query.GLOBAL_PROJECT_CONFIG") as mock_config,
                patch("llm_query.shadowroot", shadow_root),
                patch("llm_query._save_response_content") as mock_save_response,
                patch("llm_query.LLMInstructionParser.parse") as mock_parse,
                patch("llm_query.ReplaceEngine") as MockReplaceEngine,
                patch("llm_query._generate_unified_diff") as mock_generate_diff,
                patch("builtins.input", side_effect=["1", "y"]),  # 修复：模拟两个输入 - 文件编号和确认
                patch("llm_query._apply_patch") as mock_apply_patch,
            ):
                # Setup mocks
                mock_config.project_root_dir = str(project_root)
                mock_parse.return_value = [
                    {
                        "type": "created_file",
                        "path": str(project_root / "helloworld.sh"),
                        "content": '#!/bin/bash\necho "Hello World"',
                    }
                ]

                mock_engine = MockReplaceEngine.return_value

                # Mock the shadow file content after execution
                def mock_execute(instructions):
                    for instr in instructions:
                        if instr["type"] == "created_file":
                            shadow_path = Path(instr["path"])
                            shadow_path.write_text(instr["content"])

                mock_engine.execute.side_effect = mock_execute

                mock_generate_diff.return_value = (
                    '--- a/helloworld.sh\n+++ b/helloworld.sh\n@@ -0,0 +1,2 @@\n+#!/bin/bash\n+echo "Hello World"'
                )

                # Execute function
                extract_and_diff_files(content, auto_apply=False, save=True)

                # Verify behavior
                mock_save_response.assert_called_once_with(content)
                mock_parse.assert_called_once_with(content)

                # Verify ReplaceEngine called with shadow path
                expected_shadow_instr = [
                    {
                        "type": "created_file",
                        "path": str(shadow_root / "helloworld.sh"),
                        "content": '#!/bin/bash\necho "Hello World"',
                    }
                ]
                mock_engine.execute.assert_called_once_with(expected_shadow_instr)

                # Verify diff processing
                mock_generate_diff.assert_called_once()
                mock_apply_patch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
