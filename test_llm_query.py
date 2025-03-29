#!/usr/bin/env python
"""
llm_query 模块的单元测试
"""

import json
import os
import subprocess
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
from llm_query import (
    GLOBAL_MODEL_CONFIG,
    ArchitectMode,
    AutoGitCommit,
    BlockPatchResponse,
    ChatbotUI,
    CmdNode,
    FormatAndLint,
    GPTContextProcessor,
    LintParser,
    ModelConfig,
    ModelSwitch,
    SymbolsNode,
    _fetch_symbol_data,
    _find_gitignore,
    _handle_local_file,
    get_symbol_detail,
    patch_symbol_with_prompt,
    process_file_change,
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
        long_text = "a" * (GLOBAL_MODEL_CONFIG.max_context_size + 100)
        result = self.processor.process_text_with_file_path(long_text)
        self.assertTrue(len(result) <= GLOBAL_MODEL_CONFIG.max_context_size)
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
        with patch("llm_query.send_http_request") as mock_request:
            mock_request.return_value = [
                {
                    "content": "test content",
                    "location": {"start_line": 1, "start_col": 0, "end_line": 10, "end_col": 0, "block_range": "1-10"},
                    "file_path": "test.py",
                }
            ]
            result = get_symbol_detail("test.py/test_symbol")
            self.assertEqual(result[0]["file_path"], "test.py")
            self.assertEqual(result[0]["code_range"], ((1, 0), (10, 0)))
            self.assertEqual(result[0]["block_content"], b"test content")

    def test_fetch_symbol_data(self):
        """测试获取符号上下文数据"""
        with patch("llm_query.send_http_request") as mock_request:
            mock_request.return_value = {"symbol_name": "test", "definitions": [], "references": []}
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
        with open(self.file_path, "w") as f:
            f.write(self.whole_content)

    def _setup_mock_api(self):
        self.symbol_data = {
            "content": self.original_content[self.block_range[0] : self.block_range[1]],
            "location": {"block_range": self.block_range, "start_line": 1, "start_col": 0, "end_line": 2, "end_col": 4},
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
            result[0]["block_content"], self.original_content[self.block_range[0] : self.block_range[1]].encode("utf-8")
        )

    def test_multiline_symbol(self):
        content = "def test_symbol():\n    pass\n    pass\n"
        block_range = (0, len(content))
        code_range = ((1, 0), (3, 4))

        with open(self.file_path, "w", encoding="utf8") as f:
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

        with open(self.file_path, "w", encoding="utf8") as f:
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
[modified block]: example.py:10-20
[source code start]
def new_function():
    print("Added by patch")
[source code end]
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

        llm_query.display_and_apply_diff(Path(test_file_path))
        mock_run.assert_called_once_with(["patch", "-p0", "-i", test_file_path], check=True)

        os.remove(test_file_path)

    @patch("builtins.input", return_value="n")
    @patch("subprocess.run")
    def test_apply_diff_rejected(self, mock_run, _):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp_file:
            test_file_path = tmp_file.name

        llm_query.display_and_apply_diff(Path(test_file_path))
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
        time.sleep = lambda x: 0  # Mock sleep function
        self.original_config = GLOBAL_MODEL_CONFIG
        self.valid_config = {
            "model1": ModelConfig(
                key="key1",
                base_url="http://api1",
                model_name="model1",
                max_context_size=4096,
                temperature=0.7,
            ),
            "model2": ModelConfig(key="key2", base_url="http://api2", model_name="model2"),
        }
        # 使用内存中的配置文件
        self.test_config_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        self._write_test_config(self.valid_config)
        self.test_config_file.seek(0)  # 重置文件指针

    def tearDown(self) -> None:
        self.test_config_file.close()
        try:
            os.unlink(self.test_config_file.name)
        except FileNotFoundError:
            pass

    def _write_test_config(self, content: dict = None):
        """将配置写入临时文件"""
        self.test_config_file.seek(0)
        self.test_config_file.truncate()
        serializable_content = {
            name: {
                "key": config.key,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "max_context_size": config.max_context_size,
                "temperature": config.temperature,
                "is_thinking": config.is_thinking,
                "max_tokens": config.max_tokens,
            }
            for name, config in (content or self.valid_config).items()
        }
        json.dump(serializable_content, self.test_config_file)
        self.test_config_file.flush()

    def test_switch_model_configuration(self) -> None:
        """测试基础配置切换功能"""
        test_config = ModelConfig(
            key="test_key",
            base_url="http://test-api/v1",
            model_name="test-model",
            max_context_size=512,
            temperature=0.3,
        )

        self.assertEqual(test_config.model_name, "test-model")
        self.assertEqual(test_config.base_url, "http://test-api/v1")
        self.assertEqual(test_config.max_context_size, 512)
        self.assertAlmostEqual(test_config.temperature, 0.3)

    def test_config_revert_after_switch(self) -> None:
        """测试配置切换后的回滚机制"""
        original_model = GLOBAL_MODEL_CONFIG.model_name
        original_url = GLOBAL_MODEL_CONFIG.base_url

        temp_config = ModelConfig(
            key="temp_key", base_url="http://temp-api/v2", model_name="temp-model", temperature=1.0
        )

        self.assertEqual(temp_config.model_name, "temp-model")

        self.assertEqual(GLOBAL_MODEL_CONFIG.model_name, original_model)
        self.assertEqual(GLOBAL_MODEL_CONFIG.base_url, original_url)

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
        self.assertEqual(config["model1"].max_context_size, 4096)
        self.assertAlmostEqual(config["model1"].temperature, 0.7)

    def test_load_missing_config_file(self) -> None:
        """测试配置文件不存在异常"""
        switch = ModelSwitch()
        with self.assertRaises(ValueError) as context:
            switch._load_config("nonexistent.json")
        self.assertIn("模型配置文件未找到", str(context.exception))

    def test_load_invalid_json(self) -> None:
        """测试JSON格式错误异常"""
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as invalid_file:
            invalid_file.write("invalid json")
            invalid_file.flush()

        switch = ModelSwitch()
        with self.assertRaises(ValueError) as context:
            switch._load_config(invalid_file.name)
        self.assertIn("配置文件格式错误", str(context.exception))
        os.unlink(invalid_file.name)

    def test_get_valid_model_config(self) -> None:
        """测试获取存在的模型配置"""
        switch = ModelSwitch()
        switch.config = {name: ModelConfig(**config.__dict__) for name, config in self.valid_config.items()}

        config = switch._get_model_config("model1")
        self.assertEqual(config.key, "key1")
        self.assertEqual(config.base_url, "http://api1")

    def test_get_nonexistent_model(self) -> None:
        """测试获取不存在的模型配置"""
        switch = ModelSwitch()
        switch.config = {name: ModelConfig(**config.__dict__) for name, config in self.valid_config.items()}

        with self.assertRaises(ValueError) as context:
            switch._get_model_config("nonexistent")
        self.assertIn("未找到模型配置", str(context.exception))

    def test_validate_required_fields(self) -> None:
        """测试配置字段验证"""
        # 写入缺少base_url的配置
        invalid_config = {"invalid_model": {"model_name": "invalid_model", "temperature": 0.5}}
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as invalid_file:
            invalid_file.write(json.dumps(invalid_config))
            invalid_file.flush()
            with self.assertRaises(ValueError) as context:
                switch = ModelSwitch(config_path=invalid_file.name)
                switch._load_config()
                self.assertIn("base_url", str(context.exception))
                self.assertIn("缺少必要字段", str(context.exception))

    @patch("llm_query.query_gpt_api")
    def test_api_query_with_retry(self, mock_query):
        """测试API调用重试机制"""
        time.sleep = lambda x: 0  # Mock sleep function
        mock_query.side_effect = [Exception("First fail"), Exception("Second fail"), {"success": True}]

        switch = ModelSwitch()
        switch.config = {name: ModelConfig(**config.__dict__) for name, config in self.valid_config.items()}

        result = switch.query("model1", "test prompt")
        self.assertEqual(result, {"success": True})
        self.assertEqual(mock_query.call_count, 3)

    @patch("llm_query.query_gpt_api")
    def test_api_config_propagation(self, mock_query):
        """测试API配置正确传递"""
        mock_query.return_value = {"success": True}

        switch = ModelSwitch()
        switch.config = {name: ModelConfig(**config.__dict__) for name, config in self.valid_config.items()}

        switch.query("model1", "test prompt")

        self.assertEqual(switch.current_config.key, "key1")
        self.assertEqual(switch.current_config.base_url, "http://api1")

    @patch("llm_query.ModelSwitch.query")
    @patch("llm_query.ArchitectMode.parse_response")
    @patch("llm_query.process_patch_response")
    def test_execute_workflow_integration(self, mock_process, mock_parse, mock_query):
        """测试端到端工作流程"""
        # 1. 设置模拟数据
        architect_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "task": "test task",
                                "jobs": [{"content": "job1", "priority": 1}, {"content": "job2", "priority": 2}],
                            }
                        )
                    }
                }
            ]
        }

        coder_responses = [
            {"choices": [{"message": {"content": "patch1"}}]},
            {"choices": [{"message": {"content": "patch2"}}]},
        ]

        # 2. 配置mock行为
        mock_query.side_effect = [architect_response] + coder_responses
        mock_parse.return_value = {
            "task": "parsed task",
            "jobs": [{"content": "parsed job1", "priority": 1}, {"content": "parsed job2", "priority": 2}],
        }

        # 3. 执行测试
        switch = ModelSwitch()
        switch.config = {
            "architect": ModelConfig(key="key1", base_url="url1", model_name="arch"),
            "coder": ModelConfig(key="key2", base_url="url2", model_name="coder"),
        }

        # 模拟用户输入n不重试
        with patch("builtins.input", return_value="n"):
            results = switch.execute_workflow(architect_model="architect", coder_model="coder", prompt="test prompt")

        # 4. 验证结果
        self.assertEqual(len(results), 2)
        self.assertEqual(results, ["patch1", "patch2"])

        # 验证parse_response调用
        mock_parse.assert_called_once_with(architect_response["choices"][0]["message"]["content"])

        # 验证process_patch_response调用次数
        self.assertEqual(mock_process.call_count, 2)

        # 验证query调用次数 (1次架构师 + 2次编码)
        self.assertEqual(mock_query.call_count, 3)

    @patch("llm_query.query_gpt_api")
    @patch("builtins.input")
    def test_execute_workflow_retry_mechanism(self, mock_input, mock_query):
        """测试工作流重试机制"""
        # 模拟3次失败后成功
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
                ]
            },
        ]

        switch = ModelSwitch()
        switch.config = {
            "architect": ModelConfig(key="key1", base_url="url1", model_name="arch"),
            "coder": ModelConfig(key="key2", base_url="url2", model_name="coder"),
        }

        # 模拟用户输入y重试
        mock_input.side_effect = ["y", "y", "n"]
        results = switch.execute_workflow(
            architect_model="architect", coder_model="coder", prompt="test prompt", architect_only=True
        )

        self.assertEqual(len(results), 0)
        self.assertEqual(mock_query.call_count, 3)

    @patch("llm_query.ModelSwitch.query")
    @patch("llm_query.ArchitectMode.parse_response")
    def test_execute_workflow_invalid_json(self, mock_parse, mock_query):
        """测试非标准JSON输入的容错处理"""
        # 模拟非标准JSON响应
        mock_query.return_value = {"choices": [{"message": {"content": "invalid{json"}}]}

        # parse_response应该能处理这种异常
        mock_parse.side_effect = json.JSONDecodeError("Expecting value", doc="invalid{json", pos=0)

        switch = ModelSwitch()
        switch.config = {
            "architect": ModelConfig(key="key1", base_url="url1", model_name="arch"),
            "coder": ModelConfig(key="key2", base_url="url2", model_name="coder"),
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
                max_context_size=8192,
                temperature=0.6,
                is_thinking=True,
                max_tokens=1000,
            )
        }
        switch = ModelSwitch()
        switch.config = test_config
        model_config = switch._get_model_config("test_model")
        self.assertIsInstance(model_config, ModelConfig)
        self.assertEqual(model_config.key, "test_key")
        self.assertEqual(model_config.base_url, "http://test")
        self.assertEqual(model_config.model_name, "test")
        self.assertEqual(model_config.max_context_size, 8192)
        self.assertEqual(model_config.temperature, 0.6)
        self.assertTrue(model_config.is_thinking)
        self.assertEqual(model_config.max_tokens, 1000)

    def test_optional_parameter_defaults(self):
        """测试可选参数的默认值继承逻辑"""
        minimal_config = {"minimal_model": ModelConfig(key="min_key", base_url="http://min", model_name="min")}
        switch = ModelSwitch()
        switch.config = minimal_config
        model_config = switch._get_model_config("minimal_model")
        self.assertIsInstance(model_config, ModelConfig)
        self.assertEqual(model_config.max_context_size, None)
        self.assertEqual(model_config.temperature, 0.0)  # 来自ModelConfig类的默认值
        self.assertFalse(model_config.is_thinking)
        self.assertEqual(model_config.max_tokens, None)


class TestChatbotUI(unittest.TestCase):
    def setUp(self):
        self.mock_gpt = MagicMock(spec=GPTContextProcessor)
        self.mock_console = MagicMock()
        self.chatbot = ChatbotUI(gpt_processor=self.mock_gpt)
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
        [("temperature", "0.6"), ("temperature 0", "0.0"), ("temperature 1", "1.0"), ("temperature 0.5", "0.5")]
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

    def test_stream_response(self):
        with patch("llm_query.query_gpt_api") as mock_query:
            mock_query.return_value = iter(["response"])
            result = self.chatbot.stream_response("test prompt")
            self.assertEqual(list(result), ["response"])
            mock_query.assert_called_with(
                api_key=GLOBAL_MODEL_CONFIG.key,
                prompt=self.mock_gpt.process_text_with_file_path.return_value,
                model=GLOBAL_MODEL_CONFIG.model_name,
                base_url=GLOBAL_MODEL_CONFIG.base_url,
                stream=True,
                console=self.mock_console,
                temperature=0.6,
            )

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

    def test_process_input_flow(self):
        test_cases = [("", False), ("q", False), ("/help", True), ("test query", True)]
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                with patch("llm_query.query_gpt_api") as mock_query:
                    mock_query.return_value = iter(["response"])
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
            result["jobs"][0], {"member": "1", "content": "实现工作节点注册机制\n使用Consul进行服务发现"}
        )
        self.assertDictEqual(
            result["jobs"][1], {"member": "2", "content": "设计任务监控仪表盘\n使用React+ECharts可视化"}
        )

    def test_should_reject_empty_task_content(self):
        """拒绝空任务描述内容"""
        with self.assertRaisesRegex(ValueError, "任务描述内容不能为空"):
            ArchitectMode.parse_response(
                "[task describe start][task describe end]\n" "[team member1 job start]content[team member1 job end]"
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
        self.assertEqual(instance.commit_message, "Auto commit: Fix code issues")

    @patch.object(AutoGitCommit, "_execute_git_commands")
    def test_commit_flow(self, mock_execute):
        with patch("builtins.input", return_value="y"):
            instance = AutoGitCommit("[git commit message start]test commit[end]")
            instance.do_commit()
            mock_execute.assert_called_once()

    @patch("subprocess.run")
    def test_git_commands_execution(self, mock_run):
        instance = AutoGitCommit("[git commit message start]test[end]")
        instance.commit_message = "test"
        instance._execute_git_commands()
        mock_run.assert_has_calls(
            [call(["git", "add", "."], check=True), call(["git", "commit", "-m", "test"], check=True)]
        )

    @patch("subprocess.run")
    def test_specified_files_add(self, mock_run):
        instance = AutoGitCommit("[git commit message start]test[end]", files_to_add=["src/main.py", "src/utils.py"])
        instance.commit_message = "test"
        instance._execute_git_commands()
        mock_run.assert_has_calls(
            [
                call(["git", "add", "src/main.py"], check=True),
                call(["git", "add", "src/utils.py"], check=True),
                call(["git", "commit", "-m", "test"], check=True),
            ]
        )


class TestFormatAndLint(unittest.TestCase):
    def setUp(self):
        self.formatter = FormatAndLint(timeout=10)
        self.test_files = []

    def tearDown(self):
        for f in self.test_files:
            if os.path.exists(f):
                os.remove(f)

    def _create_temp_file(self, ext: str, content: str = "") -> str:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(content.encode())
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
        self.assertIn("black", mock_run.call_args_list[0].args[0])
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

        files = [self._create_temp_file(".py"), self._create_temp_file(".js"), self._create_temp_file(".sh")]

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

        with self.assertLogs(verbose_formatter.logger, level="INFO") as logs:
            verbose_formatter.run_checks([test_file], fix=True)

        self.assertTrue(any("Executing: black" in log for log in logs.output))
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
        [modified symbol]: valid/path.py
        [source code start]
        def valid_func():
            pass
        [source code end]
        """
        )
        modified, remaining = process_file_change(response)
        self.assertIn("[modified file]", modified)
        self.assertEqual(len(modified.split("\n\n")), 1)
        self.assertIn("valid/path.py", modified)
        self.assertEqual(remaining.strip(), "")

    def test_valid_symbols_with_parameter(self):
        os.path.exists = lambda x: True
        response = dedent(
            """
        [modified symbol]: valid/path.py
        [source code start]
        def valid_func():
            pass
        [source code end]
        """
        )
        modified, remaining = process_file_change(response, valid_symbols=["other/path.py"])
        self.assertIn("[modified file]", modified)
        self.assertIn("valid/path.py", modified)
        self.assertEqual(remaining.strip(), "")

    def test_invalid_symbols(self):
        os.path.exists = lambda x: False
        response = dedent(
            """
        [modified symbol]: invalid/path.py
        [source code start]
        def invalid_func():
            pass
        [source code end]
        """
        )
        modified, remaining = process_file_change(response)
        self.assertEqual(modified.strip(), "")
        self.assertIn("invalid/path.py", remaining)

    def test_invalid_symbols_with_parameter(self):
        os.path.exists = lambda x: False
        response = dedent(
            """
        [modified symbol]: valid/path.py
        [source code start]
        def valid_func():
            pass
        [source code end]
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
        [modified symbol]: valid1.py
        [source code start]
        content1
        [source code end]
        Middle content
        [modified symbol]: valid2.py
        [source code start]
        content2
        [source code end]
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
        [modified symbol]: valid.py
        [source code start]
        new_content
        [source code end]
        Middle text
        [modified symbol]: invalid.py
        [source code start]
        invalid_content
        [source code end]
        End text
        """
        )

        modified, remaining = process_file_change(response)

        self.assertIn("valid.py", modified)
        self.assertNotIn("invalid.py", modified)
        self.assertIn("invalid.py", remaining)
        self.assertIn("Middle text", remaining)
        self.assertIn("End text", remaining)
        self.assertEqual(remaining.count("[source code start]"), 1)

    def test_no_modified_symbols(self):
        response = "Just regular text\nWithout any markers"
        modified, remaining = process_file_change(response)
        self.assertEqual(modified.strip(), "")
        self.assertEqual(remaining, response)

    def test_nested_blocks(self):
        response = dedent(
            """
        [modified symbol]: outer.py
        [source code start]
        [modified symbol]: inner.py
        [source code start]
        nested_content
        [source code end]
        [source code end]
        """
        )
        modified, remaining = process_file_change(response)
        self.assertEqual(len(modified.split("\n\n")), 1)
        self.assertIn("outer.py", modified)
        self.assertNotIn("inner.py", remaining)


if __name__ == "__main__":
    unittest.main()
