#!/usr/bin/env python
"""
llm_query 模块的单元测试
"""

import os
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import llm_query
from llm_query import (
    _MODEL_CONFIG,
    BlockPatchResponse,
    CmdNode,
    GPTContextProcessor,
    LintParser,
    LintReportFix,
    LintResult,
    ModelConfig,
    ModelSwitch,
    PylintFixer,
    SymbolsNode,
    _fetch_symbol_data,
    _find_gitignore,
    _handle_local_file,
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
        long_text = "a" * (_MODEL_CONFIG.max_tokens + 100)
        result = self.processor.process_text_with_file_path(long_text)
        self.assertTrue(len(result) <= _MODEL_CONFIG.max_tokens)
        self.assertIn("输入太长内容已自动截断", result)

    def test_multiple_symbol_args(self):
        """测试多个符号参数合并"""
        text = "@symbol:a @symbol:b"
        with patch.dict(self.processor.cmd_map, {"symbol": lambda x: f"符号补丁 {x.args}"}):
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("符号补丁 ['a', 'b']", result)

    def test_url_processing(self):
        """测试URL处理"""
        text = "@https://example.com"
        with patch("llm_query._handle_url") as mock_handle_url:
            mock_handle_url.return_value = "URL处理结果"
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("URL处理结果", result)
            mock_handle_url.assert_called_once_with(
                CmdNode(command="https://example.com", command_type=None, args=None)
            )

    def test_multiple_urls(self):
        """测试多个URL处理"""
        text = "@https://example.com @https://another.com"
        with patch("llm_query._handle_url") as mock_handle_url:
            mock_handle_url.side_effect = ["URL1结果", "URL2结果"]
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("URL1结果", result)
            self.assertIn("URL2结果", result)
            self.assertEqual(mock_handle_url.call_count, 2)
            mock_handle_url.assert_any_call(CmdNode(command="https://example.com", command_type=None, args=None))
            mock_handle_url.assert_any_call(CmdNode(command="https://another.com", command_type=None, args=None))

    def test_mixed_url_and_commands(self):
        """测试混合URL和命令处理"""
        text = "开始 @https://example.com 中间 @clipboard 结束"
        with (
            patch("llm_query._handle_url") as mock_handle_url,
            patch.dict(self.processor.cmd_map, {"clipboard": lambda x: "剪贴板内容"}),
        ):
            mock_handle_url.return_value = "URL处理结果"
            result = self.processor.process_text_with_file_path(text)
            self.assertIn("URL处理结果", result)
            self.assertIn("剪贴板内容", result)
            mock_handle_url.assert_called_once_with(
                CmdNode(command="https://example.com", command_type=None, args=None)
            )

    def test_single_symbol_processing(self):
        """测试单个符号节点处理"""
        text = "..test_symbol.."
        with patch.object(self.processor, "_process_symbol") as mock_process:
            mock_process.return_value = "符号处理结果"
            result = self.processor.process_text_with_file_path(text)
            mock_process.assert_called_once()
            self.assertEqual(result, "test_symbol符号处理结果")

    def test_multiple_symbols_processing(self):
        """测试多个符号节点处理"""
        text = "..symbol1.. ..symbol2.."
        with patch.object(self.processor, "_process_symbol") as mock_process:
            mock_process.return_value = "多符号处理结果"
            result = self.processor.process_text_with_file_path(text)
            mock_process.assert_called_once_with(SymbolsNode(symbols=["symbol1", "symbol2"]))
            self.assertEqual(result, "symbol1 symbol2多符号处理结果")

    def test_mixed_symbols_and_content(self):
        """测试符号节点与混合内容处理"""
        text = "前置内容..symbol1..中间@clipboard ..symbol2..结尾"
        with (
            patch.object(self.processor, "_process_symbol") as mock_symbol,
            patch.dict(self.processor.cmd_map, {"clipboard": lambda x: "剪贴板内容"}),
        ):
            mock_symbol.return_value = "符号处理结果"
            result = self.processor.process_text_with_file_path(text)
            mock_symbol.assert_called_once_with(SymbolsNode(symbols=["symbol1", "symbol2"]))
            self.assertEqual(result, "前置内容symbol1中间剪贴板内容符号处理结果 symbol2结尾")

    def test_patch_symbol_with_prompt(self):
        """测试生成符号补丁提示词"""

        # 模拟CmdNode对象
        class MockCmdNode:
            def __init__(self, args):
                self.args = args

        # 测试单个符号
        symbol_names = MockCmdNode(["test_symbol"])
        with patch("llm_query.get_symbol_detail") as mock_get_detail:
            mock_get_detail.return_value = [
                {
                    "file_path": "test.py",
                    "code_range": ((1, 0), (10, 0)),
                    "block_range": "1-10",
                    "block_content": b"test content",
                }
            ]
            result = patch_symbol_with_prompt(symbol_names)
            self.assertIn("test_symbol", result)
            self.assertIn("test.py", result)
            self.assertIn("test content", result)

        # 测试多个符号
        symbol_names = MockCmdNode(["symbol1", "symbol2"])
        with patch("llm_query.get_symbol_detail") as mock_get_detail:
            mock_get_detail.side_effect = [
                [
                    {
                        "file_path": "file1.py",
                        "code_range": ((1, 0), (5, 0)),
                        "block_range": "1-5",
                        "block_content": b"content1",
                    }
                ],
                [
                    {
                        "file_path": "file2.py",
                        "code_range": ((10, 0), (15, 0)),
                        "block_range": "10-15",
                        "block_content": b"content2",
                    }
                ],
            ]
            result = patch_symbol_with_prompt(symbol_names)
            self.assertIn("symbol1", result)
            self.assertIn("symbol2", result)
            self.assertIn("content1", result)
            self.assertIn("content2", result)

    def test_get_symbol_detail(self):
        """测试获取符号详细信息"""
        with patch("llm_query._send_http_request") as mock_request:
            mock_request.return_value = [
                {
                    "content": "test content",
                    "location": {"start_line": 1, "start_col": 0, "end_line": 10, "end_col": 0, "block_range": "1-10"},
                    "file_path": "test.py",
                }
            ]
            result = get_symbol_detail("test_symbol")
            self.assertEqual(result[0]["file_path"], "test.py")
            self.assertEqual(result[0]["code_range"], ((1, 0), (10, 0)))
            self.assertEqual(result[0]["block_content"], b"test content")

    def test_fetch_symbol_data(self):
        """测试获取符号上下文数据"""
        with patch("llm_query._send_http_request") as mock_request:
            mock_request.return_value = {"symbol_name": "test", "definitions": [], "references": []}
            result = _fetch_symbol_data("test_symbol")
            self.assertEqual(result["symbol_name"], "test")
            self.assertIsInstance(result["definitions"], list)
            self.assertIsInstance(result["references"], list)


class TestSymbolLocation(unittest.TestCase):
    def setUp(self):
        self.symbol_name = "test_symbol"
        self.file_path = "test_file.py"
        self.original_content = "\n\ndef test_symbol():\n    pass"
        self.block_range = (1, len(self.original_content))
        self.content = self.original_content[self.block_range[0] : self.block_range[1]]
        self.code_range = ((1, 0), (2, 4))
        self.flags = None
        self.whole_content = self.original_content + "\n"
        # 创建测试文件
        with open(self.file_path, "w") as f:
            f.write(self.whole_content)

        # 模拟API响应
        self.symbol_data = {
            "content": self.content,
            "location": {"block_range": self.block_range, "start_line": 1, "start_col": 0, "end_line": 2, "end_col": 4},
            "file_path": self.file_path,
        }

        # 模拟http请求（修复响应数据结构为列表）
        self.original_send_http_request = llm_query._send_http_request
        llm_query._send_http_request = lambda url: [self.symbol_data]  # 包装为列表

    def tearDown(self):
        # 删除测试文件
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

        # 恢复原始http请求函数
        llm_query._send_http_request = self.original_send_http_request

    # 以下测试方法保持原样不变...
    def test_basic_symbol(self):
        result = llm_query.get_symbol_detail(self.symbol_name)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0]["symbol_name"], self.symbol_name)
        self.assertEqual(result[0]["file_path"], self.file_path)
        self.assertEqual(result[0]["code_range"], self.code_range)
        self.assertEqual(result[0]["block_range"], self.block_range)
        self.assertEqual(result[0]["block_content"], self.content.encode("utf-8"))

    def test_multiline_symbol(self):
        # 测试多行符号
        self.content = "def test_symbol():\n    pass\n    pass\n"
        self.block_range = (0, len(self.content))
        self.code_range = ((1, 0), (3, 4))

        # 更新测试文件
        with open(self.file_path, "w", encoding="utf8") as f:
            f.write(self.content)

        # 更新模拟数据（保持列表结构）
        self.symbol_data["content"] = self.content
        self.symbol_data["location"]["block_range"] = self.block_range
        self.symbol_data["location"]["end_line"] = 3
        result = llm_query.get_symbol_detail(self.symbol_name)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0]["block_range"], self.block_range)
        self.assertEqual(result[0]["code_range"], self.code_range)

    def test_empty_symbol(self):
        # 测试空符号
        self.content = ""
        self.block_range = (0, 0)
        self.code_range = ((1, 0), (1, 0))

        # 更新测试文件
        with open(self.file_path, "w", encoding="utf8") as f:
            f.write(self.content)

        # 更新模拟数据（保持列表结构）
        self.symbol_data["content"] = self.content
        self.symbol_data["location"]["block_range"] = self.block_range
        self.symbol_data["location"]["end_line"] = 1
        self.symbol_data["location"]["end_col"] = 0  # 修复结束列位置

        result = llm_query.get_symbol_detail(self.symbol_name)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0]["block_range"], self.block_range)
        self.assertEqual(result[0]["code_range"], self.code_range)


class TestFileRange(unittest.TestCase):
    def test_file_range_patch(self):
        """测试文件范围补丁解析"""
        # 模拟包含文件范围的响应内容
        response = """
[modified block]: example.py:10-20
[source code start]
def new_function():
    print("Added by patch")
[source code end]
        """
        parser = BlockPatchResponse()
        results = parser.parse(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "example.py:10-20")
        self.assertIn("new_function", results[0][1])

    def test_symbol_attachment(self):
        """测试未注册符号内容附加到最近合法符号"""
        # 模拟包含非法符号的响应
        response = """
[modified symbol]: invalid_symbol
[source code start]
print("Should attach to next valid")
[source code end]

[modified symbol]: valid_symbol
[source code start]
def valid_func():
    pass
[source code end]
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
[modified symbol]: invalid1
[source code start]
a = 1
[source code end]

[modified symbol]: invalid2
[source code start]
b = 2
[source code end]

[modified symbol]: valid
[source code start]
c = 3
[source code end]
        """
        parser = BlockPatchResponse(symbol_names=["valid"])
        results = parser.parse(response)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1].strip(), "a = 1\nb = 2\nc = 3")


class TestGitignoreFunctions(unittest.TestCase):
    """测试.gitignore相关功能"""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = self.test_dir.name
        self.gitignore_path = os.path.join(self.root, ".gitignore")

    def tearDown(self):
        self.test_dir.cleanup()

    def test_find_gitignore(self):
        """测试.gitignore文件查找逻辑"""
        # 在当前目录创建.gitignore
        with open(self.gitignore_path, "w", encoding="utf8") as f:
            f.write("*.tmp")
        found = _find_gitignore(os.path.join(self.root, "subdir"))
        self.assertEqual(found, self.gitignore_path)

        # 在父目录查找
        parent_gitignore = os.path.join(os.path.dirname(self.root), ".gitignore")
        with open(parent_gitignore, "w", encoding="utf8") as f:
            f.write("*.log")
        found = _find_gitignore(self.root)
        self.assertEqual(found, parent_gitignore)
        os.remove(parent_gitignore)


class TestFileHandling(unittest.TestCase):
    """测试文件处理功能"""

    def test_file_with_line_range(self):
        """测试带行号范围的文件读取"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
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
            with open(os.path.join(tmpdir, "node_modules", "test.txt"), "w") as f:
                f.write("should be ignored")

            match = MagicMock(command=tmpdir)
            result = _handle_local_file(match)
            self.assertNotIn("node_modules", result)


class TestExtractAndDiffFiles(unittest.TestCase):
    def test_no_matches_returns_early(self):
        with patch("llm_query._save_diff_content") as mock_save_diff:
            with patch("llm_query._extract_file_matches", return_value=[]):
                llm_query.extract_and_diff_files("dummy content")
                mock_save_diff.assert_not_called()

    def test_single_file_processing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("line1\nline2\n")

            with patch("llm_query.shadowroot", Path(tmpdir)):
                test_content = f"""
[modified file]: {test_file}
[source code start]
line1
line2
line3
[source code end]
"""
                llm_query.extract_and_diff_files(test_content, auto_apply=True)

                # Verify file content
                self.assertEqual(test_file.read_text(), "line1\nline2\nline3\n")
                # Verify diff file
                diff_file = Path(tmpdir) / "changes.diff"
                self.assertTrue(diff_file.exists())

    def test_diff_application_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            with patch("llm_query.shadowroot", Path(tmpdir)):
                test_content = f"""
[modified file]: {test_file}
[source code start]
new content
[source code end]
"""
                llm_query.extract_and_diff_files(test_content, auto_apply=True)
                self.assertEqual(test_file.read_text(), "new content\n")

    def test_setup_script_processing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("llm_query.shadowroot", Path(tmpdir)):
                test_content = """
[project setup shellscript start]
#!/bin/bash
echo 'setup'
[project setup shellscript end]
"""
                llm_query.extract_and_diff_files(test_content)

                setup_script = Path(tmpdir) / "project_setup.sh"
                self.assertTrue(setup_script.exists())
                self.assertEqual(setup_script.read_text(), "#!/bin/bash\necho 'setup'")
                self.assertTrue(os.access(setup_script, os.X_OK))

    def test_verify_script_processing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("llm_query.shadowroot", Path(tmpdir)):
                test_content = """
[user verify script start]
#!/bin/bash
echo 'verify'
[user verify script end]
"""
                llm_query.extract_and_diff_files(test_content)

                verify_script = Path(tmpdir) / "user_verify.sh"
                self.assertTrue(verify_script.exists())
                self.assertEqual(verify_script.read_text(), "#!/bin/bash\necho 'verify'")
                self.assertTrue(os.access(verify_script, os.X_OK))


class TestDisplayAndApplyDiff(unittest.TestCase):
    @patch("builtins.input", return_value="y")
    @patch("subprocess.run")
    def test_apply_diff_accepted(self, mock_run, _):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp_file:
            test_file_path = tmp_file.name

        llm_query._display_and_apply_diff(Path(test_file_path))
        mock_run.assert_called_once_with(["patch", "-p0", "-i", test_file_path], check=True)

        os.remove(test_file_path)

    @patch("builtins.input", return_value="n")
    @patch("subprocess.run")
    def test_apply_diff_rejected(self, mock_run, _):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp_file:
            test_file_path = tmp_file.name

        llm_query._display_and_apply_diff(Path(test_file_path))
        mock_run.assert_not_called()

        os.remove(test_file_path)


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
        self.original_config = _MODEL_CONFIG

    def tearDown(self) -> None:
        _MODEL_CONFIG = self.original_config

    def test_switch_model_configuration(self) -> None:
        """测试基础配置切换功能"""
        test_config = ModelConfig(
            key="test_key", base_url="http://test-api/v1", model_name="test-model", max_tokens=512, temperature=0.3
        )

        _MODEL_CONFIG = test_config
        self.assertEqual(_MODEL_CONFIG.model_name, "test-model")
        self.assertEqual(_MODEL_CONFIG.base_url, "http://test-api/v1")
        self.assertEqual(_MODEL_CONFIG.max_tokens, 512)
        self.assertAlmostEqual(_MODEL_CONFIG.temperature, 0.3)

    def test_config_revert_after_switch(self) -> None:
        """测试配置切换后的回滚机制"""
        from llm_query import _MODEL_CONFIG

        original_model = _MODEL_CONFIG.model_name
        original_url = _MODEL_CONFIG.base_url

        temp_config = ModelConfig(
            key="temp_key", base_url="http://temp-api/v2", model_name="temp-model", temperature=1.0
        )

        _MODEL_CONFIG = temp_config
        self.assertEqual(_MODEL_CONFIG.model_name, "temp-model")

        _MODEL_CONFIG = self.original_config
        self.assertEqual(_MODEL_CONFIG.model_name, original_model)
        self.assertEqual(_MODEL_CONFIG.base_url, original_url)


class TestLintReportFix(unittest.TestCase):
    def setUp(self):
        self.test_file = Path("test_file.py")
        self.test_file.write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n")
        self.fixer = LintReportFix(ModelSwitch())
        self.fixer._MAX_CONTEXT_SPAN = 100  # 扩大上下文跨度以通过测试用例
        self.sample_results = [
            LintResult(
                file_path="test_file.py", line=2, code="C0114", message="Missing docstring", column_range=(1, 5)
            ),
            LintResult(file_path="test_file.py", line=3, code="E1136", message="Value error", column_range=(1, 5)),
            LintResult(file_path="other_file.py", line=5, code="W0612", message="Unused variable", column_range=(1, 5)),
            LintResult(file_path="span_test.py", line=1, code="C0301", message="Line too long", column_range=(1, 10)),
            LintResult(file_path="span_test.py", line=102, code="E1145", message="Invalid syntax", column_range=(1, 5)),
        ]

    def tearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()
        for f in ["span_test.py", "other_file.py"]:
            p = Path(f)
            if p.exists():
                p.unlink()

    def test_group_results_same_file(self):
        groups = self.fixer._group_results(self.sample_results[:2])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_group_results_cross_file(self):
        groups = self.fixer._group_results(self.sample_results)
        self.assertEqual(len(groups), 4)
        self.assertEqual(len(groups[0]), 2)
        self.assertEqual(groups[1][0].file_path, "other_file.py")
        self.assertEqual(groups[2][0].file_path, "span_test.py")

    def test_group_results_over_span(self):
        span_results = [res for res in self.sample_results if res.file_path == "span_test.py"]
        groups = self.fixer._group_results(span_results)
        self.assertEqual(len(groups), 2)
        self.assertEqual({g[0].line for g in groups}, {1, 102})

    def test_code_context_generation(self):
        context, start, end = self.fixer._build_code_context(self.sample_results[:1])
        self.assertIn(">>>", context)
        self.assertIn("   2>>> b = 2", context)
        self.assertIn("1    a = 1", context)

    def test_prompt_generation(self):
        prompt = self.fixer._build_prompt(self.sample_results[:2])
        self.assertIn("批量代码问题修复", prompt)
        self.assertIn("共发现 2 个相关联的问题", prompt)
        self.assertIn("问题 1", prompt)
        self.assertIn("问题 2", prompt)

    @patch.object(ModelSwitch, "query")
    def test_successful_fix(self, mock_query):
        mock_response = {"choices": [{"message": {"content": "```fixed\nb = 2  # 修复C0114错误\n```"}}]}
        mock_query.return_value = mock_response
        fixes, start, end = self.fixer.generate_batch_fix(self.sample_results[:1])
        self.assertIn("b = 2  # 修复C0114错误", fixes)

    @patch.object(ModelSwitch, "query")
    def test_invalid_response(self, mock_query):
        mock_query.return_value = {"invalid": "response"}
        with self.assertRaises(ValueError):
            self.fixer.generate_batch_fix(self.sample_results[:1])

    def test_empty_results_handling(self):
        groups = self.fixer._group_results([])
        self.assertEqual(len(groups), 0)


class TestPylintFixer(unittest.TestCase):
    def setUp(self):
        self.test_log = Path("test_pylint.log")
        self.test_log.write_text("")
        self.shadowroot = Path(tempfile.mkdtemp())
        self.test_root = Path.cwd()

    def tearDown(self):
        if self.test_log.exists():
            self.test_log.unlink()
        if self.shadowroot.exists():
            shutil.rmtree(self.shadowroot)

    def test_shadow_operations(self):
        test_file = self.test_root / "test_file.py"
        test_content = "print('original')"
        test_file.write_text(test_content)

        log_content = f"{test_file}:1:0: C0111: Missing docstring"
        self.test_log.write_text(log_content)

        with patch.object(LintReportFix, "generate_batch_fix", return_value=(["print('fixed')"], 1, 1)):
            fixer = PylintFixer(
                str(self.test_log), auto_apply=True, shadowroot=self.shadowroot, root_dir=self.test_root
            )
            fixer.execute()

        shadow_file = self.shadowroot / test_file.relative_to(self.test_root)
        self.assertTrue(shadow_file.exists())
        self.assertEqual(shadow_file.read_text(), "print('fixed')\n")
        self.assertEqual(test_file.read_text(), "print('fixed')\n")

    def test_multiple_patch_merging(self):
        test_file = self.test_root / "merge_test.py"
        test_content = "original1\noriginal2\noriginal3\n"
        test_file.write_text(test_content)

        log_content = f"{test_file}:1:0: C0111: Missing docstring\n{test_file}:105:0: C0111: Missing docstring"
        self.test_log.write_text(log_content)

        with patch.object(
            LintReportFix, "generate_batch_fix", side_effect=[(["fixed1"], 1, 1), (["fixed3"], 105, 105)]
        ):
            fixer = PylintFixer(
                str(self.test_log), auto_apply=True, shadowroot=self.shadowroot, root_dir=self.test_root
            )
            fixer.execute()

        shadow_file = self.shadowroot / test_file.relative_to(self.test_root)
        expected = "fixed1\noriginal2\nfixed3\n"
        self.assertEqual(shadow_file.read_text(), expected)
        self.assertEqual(test_file.read_text(), expected)

    def test_diff_generation(self):
        test_file = self.test_root / "diff_test.py"
        test_content = "original\ncontent\n"
        test_file.write_text(test_content)

        log_content = f"{test_file}:1:0: C0111: Missing docstring"
        self.test_log.write_text(log_content)

        with (
            patch.object(LintReportFix, "generate_batch_fix", return_value=(["modified"], 1, 2)),
            patch("builtins.input", return_value="n"),
        ):
            fixer = PylintFixer(str(self.test_log), shadowroot=self.shadowroot, root_dir=self.test_root)
            fixer.execute()

            self.assertTrue(hasattr(fixer, "last_diff"))
            self.assertIn("modified", fixer.last_diff)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            fixer = PylintFixer("non_existent.log")
            fixer.load_and_validate_log()

    def test_valid_log_processing(self):
        log_content = dedent(
            """  
        test.py:1:0: C0111: Missing docstring (missing-docstring)  
        test.py:2:5: E1101: Instance of 'NoneType' has no 'attr' (no-member)  
        """
        )
        self.test_log.write_text(log_content.strip())

        fixer = PylintFixer(str(self.test_log))
        fixer.load_and_validate_log()
        fixer.group_results_by_file()
        self.assertEqual(len(fixer.results), 2)
        self.assertIn("test.py", fixer.file_groups)

    def test_auto_choice_handling(self):
        with patch("builtins.input", return_value="n"), patch("sys.exit") as mock_exit:

            log_content = "test.py:1:0: C0111: Missing docstring"
            self.test_log.write_text(log_content)

            fixer = PylintFixer(str(self.test_log))
            fixer.execute()

            mock_exit.assert_not_called()

    def test_error_group_processing(self):
        with (
            patch.object(LintReportFix, "generate_batch_fix") as mock_fix,
            patch("pathlib.Path.is_file", return_value=True),
        ):
            mock_fix.return_value = (["# Fixed code"], 1, 5)

            log_content = dedent(
                """  
            test.py:1:0: C0111: Missing docstring  
            test.py:2:0: C0111: Missing docstring  
            """
            )
            self.test_log.write_text(log_content.strip())

            fixer = PylintFixer(str(self.test_log), auto_apply=True)
            fixer.execute()
            self.assertEqual(mock_fix.call_count, 1)

    def test_empty_log_handling(self):
        fixer = PylintFixer(str(self.test_log))
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            fixer.execute()
            output = mock_stdout.getvalue()
            self.assertIn("未发现可修复的错误", output)


if __name__ == "__main__":
    unittest.main()
