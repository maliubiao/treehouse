#!/usr/bin/env python
"""
llm_query 模块的单元测试
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from llm_query import (
    MAX_FILE_SIZE,
    detect_proxies,
    extract_and_diff_files,
    fetch_url_content,
    get_directory_context,
    load_conversation_history,
    new_conversation,
    parse_arguments,
    process_text_with_file_path,
    sanitize_proxy_url,
    save_conversation_history,
    split_code,
)


class TestLLMQuery(unittest.TestCase):
    """主测试类"""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.test_dir.cleanup)

    def test_parse_arguments(self):
        """测试参数解析"""
        # 测试--file参数
        sys.argv = ["llm_query.py", "--file", "test.py"]
        args = parse_arguments()
        self.assertEqual(args.file, "test.py")
        self.assertIsNone(args.ask)

        # 测试--ask参数
        sys.argv = ["llm_query.py", "--ask", "test question"]
        args = parse_arguments()
        self.assertEqual(args.ask, "test question")
        self.assertIsNone(args.file)

        # 测试默认值
        self.assertEqual(args.prompt_file, os.path.expanduser("~/.llm/source-query.txt"))
        self.assertEqual(args.chunk_size, MAX_FILE_SIZE)

    def test_detect_proxies(self):
        """测试代理检测"""
        # 测试无代理
        with patch.dict(os.environ, {}, clear=True):
            proxies, sources = detect_proxies()
            self.assertEqual(proxies, {})
        # 清除所有代理环境变量
        proxy_vars = ["http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]
        for var in proxy_vars:
            if var in os.environ:
                del os.environ[var]

        # 测试http代理
        with patch.dict(
            os.environ, {"http_proxy": "http://user:pass@proxy:8080", "HTTP_PROXY": "http://user:pass@proxy:8080"}
        ):
            proxies, sources = detect_proxies()
            self.assertEqual(proxies["http"], "http://user:pass@proxy:8080")
            self.assertEqual(sources["http"], "http_proxy")

        # 测试代理优先级
        with patch.dict(os.environ, {"all_proxy": "socks5://proxy2"}):
            proxies, sources = detect_proxies()
            self.assertEqual(proxies["http"], "socks5://proxy2")

    def test_split_code(self):
        """测试代码分块"""
        content = "a" * (MAX_FILE_SIZE * 2 + 100)
        chunks = split_code(content, MAX_FILE_SIZE)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), MAX_FILE_SIZE)
        self.assertEqual(len(chunks[1]), MAX_FILE_SIZE)
        self.assertEqual(len(chunks[2]), 100)

    def test_conversation_management(self):
        """测试对话管理"""
        # 测试新对话创建
        with patch("llm_query.datetime") as mock_datetime:
            mock_datetime.datetime.now.return_value.strftime.side_effect = [
                "2024-01-01",  # date_dir
                "12-00-00",  # time_str
            ]
            uuid = "test-uuid"
            path = new_conversation(uuid)
            self.assertIn("2024-01-01/12-00-00-test-uuid.json", path)

            # 验证索引更新
            index_path = Path(__file__).parent / "conversation" / "index.json"
            with open(index_path, "r") as f:
                index = json.load(f)
                self.assertEqual(index[uuid], path)

    def test_history_io(self):
        """测试对话历史读写"""
        test_data = [{"role": "user", "content": "test"}]
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
            save_conversation_history(tmp.name, test_data)
            loaded = load_conversation_history(tmp.name)
            self.assertEqual(loaded, test_data)

        # 测试无效文件
        self.assertEqual(load_conversation_history("nonexistent.json"), [])

    @patch("subprocess.run")
    def test_directory_context(self, mock_run):
        """测试目录上下文获取"""
        # 测试Linux/macOS tree命令
        mock_run.return_value.stdout = "mock tree output"
        context = get_directory_context()
        self.assertIn("mock tree output", context)

        # 测试命令失败回退
        mock_run.side_effect = [subprocess.CalledProcessError(1, "cmd"), MagicMock(stdout="mock fallback output")]
        context = get_directory_context()  # 第一次调用会抛出错误
        self.assertIn("mock fallback output", context)

    @patch("requests.Session.get")
    def test_fetch_url_content(self, mock_get):
        """测试URL内容获取"""
        mock_response = MagicMock()
        mock_response.text = "test content"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        content = fetch_url_content("http://example.com")
        self.assertIn("test content", content)

    def test_text_processing(self):
        """测试文本处理"""
        # 测试剪贴板替换
        with patch("llm_query.get_clipboard_content_real") as mock_clip:
            mock_clip.return_value = "clip content"
            processed = process_text_with_file_path("@clipboard")
            self.assertIn("clipboard content start", processed)

        # 测试文件嵌入
        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = True
            with patch("builtins.open", mock_open(read_data="file content")):
                processed = process_text_with_file_path("@test.txt")
                self.assertIn("file content", processed)

    def test_diff_processing(self):
        """测试差异处理"""
        # 创建测试文件
        test_file = Path(self.test_dir.name) / "test.txt"
        test_file.write_text("original content")

        # 模拟API响应
        response_content = f"""
[modified file]: {test_file}
[source code start]
modified content
[source code end]"""

        # 执行差异提取
        with patch("builtins.input", return_value="n"):
            extract_and_diff_files(response_content)

        # 验证shadow文件
        shadow_file = Path.home() / ".shadowroot" / test_file.relative_to(test_file.anchor)
        self.assertTrue(shadow_file.exists())
        self.assertEqual(shadow_file.read_text(), "modified content")

        # 验证diff生成
        diff_file = Path.home() / ".shadowroot" / "changes.diff"
        if diff_file.exists():
            diff_content = diff_file.read_text()
            self.assertIn("-original content", diff_content)
            self.assertIn("+modified content", diff_content)

    @patch("llm_query.OpenAI")
    def test_api_query(self, mock_openai):
        """测试API查询流程"""
        # 配置mock响应
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # 创建模拟的流式响应
        mock_response = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock(delta=MagicMock(content="test response", reasoning_content=None))]
        mock_client.chat.completions.create.return_value = [mock_chunk]

        # 执行查询
        from llm_query import query_gpt_api

        response = query_gpt_api("fake-key", "test prompt", conversation_file="")
        self.assertEqual(response["choices"][0]["message"]["content"], "test response")

    def test_security(self):
        """测试安全相关功能"""
        # 测试代理URL脱敏
        sanitized = sanitize_proxy_url("http://user:password@proxy:8080")
        self.assertIn("****", sanitized)
        self.assertNotIn("password", sanitized)


if __name__ == "__main__":
    unittest.main()
