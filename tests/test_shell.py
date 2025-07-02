#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from shell import (
    LLM_PROJECT_CONFIG,
    find_root_dir,
    handle_complete,
    relative_to_root_dir,
)

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from shell import (
    _complete_partial_path,
    _process_file_completion,
    handle_cmd_complete,
    main,
)


class TestShellCompletion(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.mock_api = "http://mock-server/"
        os.environ["GPT_API_SERVER"] = self.mock_api

        # Setup complex test directory structure
        self.root = Path(self.test_dir.name)
        self.root_posix = str(self.root).replace(os.sep, "/")  # 统一为Linux风格路径分隔符
        (self.root / LLM_PROJECT_CONFIG).touch()  # 确保根目录包含配置文件
        self._create_structure(
            {
                "lsp/": {
                    "subdir/": {"nested_file.md": None},
                    "file1.txt": None,
                    ".hidden_file": None,
                    "special@file": None,
                },
                "partial/": {"match_file": None, "match_file2": None},
                "empty_dir/": {},
                "multi//slash//path/": {"test_file": None},
            }
        )

    def _create_structure(self, structure: dict, parent: Path = None):
        parent = parent or self.root
        for name, content in structure.items():
            path = parent / name.rstrip("/")
            if name.endswith("/"):
                path.mkdir(parents=True, exist_ok=True)
                if content:
                    self._create_structure(content, path)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

    def tearDown(self):
        self.test_dir.cleanup()
        os.environ.pop("GPT_API_SERVER", None)

    def _capture_completion(self, prefix: str):
        """Helper to capture completion output"""

        saved_stdout = sys.stdout
        try:
            sys.stdout = StringIO()
            handle_complete(prefix)
            return sys.stdout.getvalue().splitlines()
        finally:
            sys.stdout = saved_stdout

    def test_directory_completion(self):
        test_cases = [
            (
                f"symbol_{self.root_posix}/lsp/",
                [
                    f"symbol_{self.root_posix}/lsp/subdir/",
                    f"symbol_{self.root_posix}/lsp/file1.txt",
                    f"symbol_{self.root_posix}/lsp/.hidden_file",
                    f"symbol_{self.root_posix}/lsp/special@file",
                ],
            ),
            (
                f"symbol_{self.root_posix}/lsp/subdir/",
                [f"symbol_{self.root_posix}/lsp/subdir/nested_file.md"],
            ),
        ]

        for prefix, expected in test_cases:
            with self.subTest(prefix=prefix):
                result = self._capture_completion(prefix)
                self.assertCountEqual(expected, result)

    def test_partial_completion(self):
        test_cases = [
            (
                f"symbol_{self.root_posix}/partial/mat",
                [
                    f"symbol_{self.root_posix}/partial/match_file",
                    f"symbol_{self.root_posix}/partial/match_file2",
                ],
            ),
            (
                f"symbol_{self.root_posix}/lsp/file",
                [f"symbol_{self.root_posix}/lsp/file1.txt"],
            ),
        ]

        for prefix, expected in test_cases:
            with self.subTest(prefix=prefix):
                result = self._capture_completion(prefix)
                self.assertCountEqual(expected, result)

    def test_special_cases(self):
        test_cases = [
            (
                f"symbol_{self.root_posix}/lsp/.hid",
                [f"symbol_{self.root_posix}/lsp/.hidden_file"],
            ),
            (
                f"symbol_{self.root_posix}/lsp/special@",
                [f"symbol_{self.root_posix}/lsp/special@file"],
            ),
            (
                f"symbol_{self.root_posix}/multi/slash/path/",
                [f"symbol_{self.root_posix}/multi/slash/path/test_file"],
            ),
        ]

        for prefix, expected in test_cases:
            with self.subTest(prefix=prefix):
                result = self._capture_completion(prefix)
                self.assertCountEqual(expected, result)

    def test_api_fallback(self):
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.text = "symbol:path/api_result1\nsymbol:path/api_result2"
            mock_get.return_value = mock_response

            result = self._capture_completion("symbol_existent/path/api")
            self.assertEqual(
                [
                    "symbol_existent/path/api_result1",
                    "symbol_existent/path/api_result2",
                ],
                result,
            )

    def test_error_handling(self):
        test_cases = [
            ("symbol_invalid_prefix", []),
            (f"symbol_{self.root_posix}/empty_dir/", []),
            ("symbol_missing_dir/", []),
        ]

        for prefix, expected in test_cases:
            with self.subTest(prefix=prefix):
                result = self._capture_completion(prefix)
                self.assertEqual(expected, result)

    def test_api_error_logging(self):
        with self.assertLogs(level="ERROR") as cm:
            with patch(
                "requests.get",
                side_effect=requests.exceptions.ConnectionError("Connection error"),
            ):
                self._capture_completion("symbol_broken/path")
                self.assertTrue(any("API request failed" in log for log in cm.output))

    def test_relative_to_root_dir(self):
        original_cwd = os.getcwd()
        try:
            # Create nested directory structure
            nested_dir = self.root / "nested" / "subdir"
            nested_dir.mkdir(parents=True)

            # Test from root directory
            os.chdir(self.root)
            result = relative_to_root_dir("lsp/file1.txt")
            self.assertEqual(Path("lsp/file1.txt"), result)

            # Test from nested directory
            os.chdir(nested_dir)
            result = relative_to_root_dir("lsp/file1.txt")
            self.assertEqual(Path("nested/subdir/lsp/file1.txt"), result)

            # Test outside root directory
            with tempfile.TemporaryDirectory() as tmp_dir:
                os.chdir(tmp_dir)
                result = relative_to_root_dir(str(self.root / "lsp/file1.txt"))
                self.assertEqual(self.root / "lsp/file1.txt", result)
        finally:
            os.chdir(original_cwd)

    def test_find_root_dir(self):
        original_cwd = os.getcwd()
        try:
            # Should find root directory when in subdirectory
            subdir = self.root / "lsp" / "subdir"
            subdir.mkdir(parents=True, exist_ok=True)
            os.chdir(subdir)
            self.assertEqual(self.root.resolve(), find_root_dir().resolve())

            # Should return None when outside root directory
            with tempfile.TemporaryDirectory() as tmp_dir:
                os.chdir(tmp_dir)
                self.assertIsNone(find_root_dir())
        finally:
            os.chdir(original_cwd)


class TestShellFunctions(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(__file__).parent / "test_dir"
        self.test_dir.mkdir(exist_ok=True)

        # Create test files and directories
        (self.test_dir / "llm_file1").touch()
        (self.test_dir / "llm_file2").touch()
        (self.test_dir / "llm_dir1").mkdir()
        (self.test_dir / "other_file").touch()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @patch("builtins.print")
    def test_complete_partial_path_with_matches(self, mock_print):
        """Test that _complete_partial_path prints matching items with correct format"""
        _complete_partial_path(self.test_dir, "llm")

        # Verify all matching items were printed with correct format
        expected_calls = [
            unittest.mock.call(f"symbol_{self.test_dir}/llm_file1"),
            unittest.mock.call(f"symbol_{self.test_dir}/llm_file2"),
            unittest.mock.call(f"symbol_{self.test_dir}/llm_dir1/"),
        ]

        # Check that all expected calls were made, regardless of order
        actual_calls = mock_print.call_args_list
        self.assertEqual(len(actual_calls), 3)
        for expected_call in expected_calls:
            self.assertIn(expected_call, actual_calls)

    @patch("builtins.print")
    def test_complete_partial_path_no_matches(self, mock_print):
        """Test that _complete_partial_path prints nothing when no matches"""
        _complete_partial_path(self.test_dir, "nonexistent")
        mock_print.assert_not_called()

    @patch("builtins.print")
    def test_complete_partial_path_current_directory(self, mock_print):
        """Test that _complete_partial_path handles current directory (.) correctly"""
        with patch.object(Path, "iterdir") as mock_iterdir:
            mock_iterdir.return_value = [
                MagicMock(name="llm_test", is_dir=lambda: False),
                MagicMock(name="llm_dir", is_dir=lambda: True),
            ]

            # Configure the mock items to return correct names
            mock_iterdir.return_value[0].name = "llm_test"
            mock_iterdir.return_value[1].name = "llm_dir"

            _complete_partial_path(Path("."), "llm")

            expected_calls = [unittest.mock.call("symbol_llm_test"), unittest.mock.call("symbol_llm_dir")]

            actual_calls = mock_print.call_args_list
            self.assertEqual(len(actual_calls), 2)
            for expected_call in expected_calls:
                self.assertIn(expected_call, actual_calls)

    @patch("logging.error")
    @patch("builtins.print")
    def test_complete_partial_path_os_error(self, mock_print, mock_log_error):
        """Test that _complete_partial_path handles OSError gracefully"""
        with patch.object(Path, "iterdir") as mock_iterdir:
            mock_iterdir.side_effect = OSError("Permission denied")

            _complete_partial_path(self.test_dir, "llm")

            mock_print.assert_not_called()
            mock_log_error.assert_called_once_with("Partial path completion failed: %s", "Permission denied")

    @patch("shell._complete_partial_path")
    def test_process_file_completion_with_existing_parent_dir(self, mock_complete_partial_path):
        """Test _process_file_completion when parent directory exists and is a directory."""
        path_obj = Path("llm")
        api_server = "http://127.0.0.1:57962/"
        prefix = "symbol_llm"

        # Configure the mock to return None as per the execution trace
        mock_complete_partial_path.return_value = None

        # Call the function under test
        result = _process_file_completion(path_obj, api_server, prefix)

        # Verify the mock was called correctly
        mock_complete_partial_path.assert_called_once_with(Path("."), "llm")

        # Verify the return value
        self.assertIsNone(result)

    @patch("shell._complete_partial_path")
    def test_process_file_completion_with_nonexistent_path(self, mock_complete_partial_path):
        """Test _process_file_completion when path does not exist and parent directory does not exist."""
        path_obj = Path("nonexistent/path")
        api_server = "http://127.0.0.1:57962/"
        prefix = "symbol_nonexistent"

        # Configure the mock to return None
        mock_complete_partial_path.return_value = None

        # Call the function under test
        result = _process_file_completion(path_obj, api_server, prefix)

        # Verify the mock was not called
        mock_complete_partial_path.assert_not_called()

        # Verify the return value
        self.assertIsNone(result)

    @patch("shell._request_api_completion")
    def test_process_file_completion_with_file(self, mock_request_api_completion):
        """Test _process_file_completion when path exists and is a file."""
        path_obj = Path("existing_file.txt")
        path_obj.touch()  # Create a temporary file
        api_server = "http://127.0.0.1:57962/"
        prefix = "symbol_existing_file.txt"

        # Configure the mock to return None
        mock_request_api_completion.return_value = None

        # Call the function under test
        result = _process_file_completion(path_obj, api_server, prefix)

        # Verify the mock was called correctly
        mock_request_api_completion.assert_called_once_with(api_server, prefix)

        # Verify the return value
        self.assertIsNone(result)

        # Clean up
        path_obj.unlink()

    @patch("shell._complete_local_directory")
    def test_process_file_completion_with_directory(self, mock_complete_local_directory):
        """Test _process_file_completion when path exists and is a directory."""
        path_obj = Path("existing_dir")
        path_obj.mkdir()  # Create a temporary directory
        api_server = "http://127.0.0.1:57962/"
        prefix = "symbol_existing_dir/"

        # Configure the mock to return None
        mock_complete_local_directory.return_value = None

        # Call the function under test
        result = _process_file_completion(path_obj, api_server, prefix)

        # Verify the mock was called correctly
        mock_complete_local_directory.assert_called_once_with(str(path_obj))

        # Verify the return value
        self.assertIsNone(result)

        # Clean up
        path_obj.rmdir()

    @patch("shell._process_file_completion")
    @patch("os.getenv")
    def test_handle_complete_with_valid_prefix_and_api_server(self, mock_getenv, mock_process_file_completion):
        # Setup
        mock_getenv.return_value = "http://127.0.0.1:57962/"
        mock_process_file_completion.return_value = None
        prefix = "symbol_llm"

        # Execute
        result = handle_complete(prefix)

        # Assert
        mock_getenv.assert_called_once_with("GPT_SYMBOL_API_URL")
        mock_process_file_completion.assert_called_once_with(Path("llm"), "http://127.0.0.1:57962/", "symbol_llm")
        self.assertIsNone(result)

    @patch("os.getenv")
    def test_handle_complete_with_missing_api_server(self, mock_getenv):
        # Setup
        mock_getenv.return_value = None
        prefix = "symbol_llm"

        # Execute
        result = handle_complete(prefix)

        # Assert
        mock_getenv.assert_called_once_with("GPT_SYMBOL_API_URL")
        self.assertIsNone(result)

    def test_handle_complete_with_invalid_prefix(self):
        # Setup
        prefix = "invalid_prefix"

        # Execute
        result = handle_complete(prefix)

        # Assert
        self.assertIsNone(result)

    @patch("shell._handle_directory_completion")
    @patch("os.getenv")
    def test_handle_complete_with_directory_path(self, mock_getenv, mock_handle_directory_completion):
        # Setup
        mock_getenv.return_value = "http://127.0.0.1:57962/"
        mock_handle_directory_completion.return_value = None
        prefix = "symbol_llm/"

        # Execute
        result = handle_complete(prefix)

        # Assert
        mock_getenv.assert_called_once_with("GPT_SYMBOL_API_URL")
        mock_handle_directory_completion.assert_called_once_with("llm/", "http://127.0.0.1:57962/")
        self.assertIsNone(result)

    @patch("shell.handle_complete")
    def test_handle_cmd_complete_with_symbol_prefix(self, mock_handle_complete):
        # Setup
        prefix = "@symbol_llm"
        mock_handle_complete.return_value = None

        # Execute
        result = handle_cmd_complete(prefix)

        # Verify
        mock_handle_complete.assert_called_once_with("symbol_llm")
        self.assertIsNone(result)

    @patch("os.path.isdir")
    @patch("os.listdir")
    @patch("os.getenv")
    def test_handle_cmd_complete_with_prompts_dir(self, mock_getenv, mock_listdir, mock_isdir):
        # Setup
        prefix = "@test"
        mock_getenv.return_value = "/fake/path"
        mock_isdir.side_effect = [True, False, True]  # 分别对应: prompts目录检查, test_file.txt检查, test_dir检查
        mock_listdir.return_value = ["test_file.txt", "test_dir"]

        # Execute
        with patch("builtins.print") as mock_print:
            handle_cmd_complete(prefix)

        # Verify
        mock_getenv.assert_called_once_with("GPT_PATH", "")
        mock_isdir.assert_has_calls(
            [
                unittest.mock.call("/fake/path/prompts"),
                unittest.mock.call("/fake/path/prompts/test_file.txt"),
                unittest.mock.call("/fake/path/prompts/test_dir"),
            ]
        )
        mock_listdir.assert_called_once_with("/fake/path/prompts")
        mock_print.assert_any_call("test_file.txt")
        mock_print.assert_any_call("test_dir/")

    @patch("os.path.isdir")
    @patch("os.getenv")
    def test_handle_cmd_complete_with_special_commands(self, mock_getenv, mock_isdir):
        # Setup
        prefix = "@clip"
        mock_getenv.return_value = "/fake/path"
        mock_isdir.return_value = False

        # Execute
        with patch("builtins.print") as mock_print:
            handle_cmd_complete(prefix)

        # Verify
        mock_print.assert_called_once_with("clipboard")

    @patch("logging.error")
    @patch("os.path.isdir")
    @patch("os.listdir")
    @patch("os.getenv")
    def test_handle_cmd_complete_with_prompts_dir_error(self, mock_getenv, mock_listdir, mock_isdir, mock_logging):
        """Test that handle_cmd_complete logs error when prompts directory listing fails"""
        # Setup
        prefix = "@test"
        mock_getenv.return_value = "/fake/path"
        mock_isdir.return_value = True
        mock_listdir.side_effect = OSError("Permission denied")

        # Execute
        handle_cmd_complete(prefix)

        # Verify
        mock_getenv.assert_called_once_with("GPT_PATH", "")
        mock_isdir.assert_called_once_with("/fake/path/prompts")
        mock_listdir.assert_called_once_with("/fake/path/prompts")
        # 修复点：改为检查mock_logging的调用参数而不是具体异常对象
        mock_logging.assert_called_once()
        args, kwargs = mock_logging.call_args
        self.assertEqual(args[0], "Failed to list prompts directory: %s")
        self.assertIsInstance(args[1], OSError)

    @patch("shell.handle_cmd_complete")
    def test_main_shell_complete_command(self, mock_handle_cmd_complete):
        # Setup test arguments
        test_args = ["shell.py", "shell-complete", "@symbol_llm"]

        with patch(
            "argparse.ArgumentParser.parse_args",
            return_value=argparse.Namespace(command="shell-complete", prefix="@symbol_llm"),
        ):
            # Execute the function under test
            main()

            # Verify the mock was called correctly
            mock_handle_cmd_complete.assert_called_once_with("@symbol_llm")

    @patch("shell.handle_complete")
    def test_main_complete_command(self, mock_handle_complete):
        # Setup test arguments
        test_args = ["shell.py", "complete", "symbol_llm"]

        with patch(
            "argparse.ArgumentParser.parse_args",
            return_value=argparse.Namespace(command="complete", prefix="symbol_llm"),
        ):
            # Execute the function under test
            main()

            # Verify the mock was called correctly
            mock_handle_complete.assert_called_once_with("symbol_llm")

    @patch("shell._handle_conversations")
    def test_main_conversations_command(self, mock_handle_conversations):
        # Setup test arguments
        test_args = ["shell.py", "conversations", "--limit", "10"]

        with patch(
            "argparse.ArgumentParser.parse_args", return_value=argparse.Namespace(command="conversations", limit=10)
        ):
            # Execute the function under test
            main()

            # Verify the mock was called correctly
            mock_handle_conversations.assert_called_once_with(10)

    @patch("shell.list_models")
    def test_main_list_models_command(self, mock_list_models):
        # Setup test arguments
        test_args = ["shell.py", "list-models", "config.json"]

        with patch(
            "argparse.ArgumentParser.parse_args",
            return_value=argparse.Namespace(command="list-models", config_file="config.json"),
        ):
            # Execute the function under test
            main()

            # Verify the mock was called correctly
            mock_list_models.assert_called_once_with("config.json")

    @patch("shell.list_model_names")
    def test_main_list_model_names_command(self, mock_list_model_names):
        # Setup test arguments
        test_args = ["shell.py", "list-model-names", "config.json"]

        with patch(
            "argparse.ArgumentParser.parse_args",
            return_value=argparse.Namespace(command="list-model-names", config_file="config.json"),
        ):
            # Execute the function under test
            main()

            # Verify the mock was called correctly
            mock_list_model_names.assert_called_once_with("config.json")

    @patch("shell.read_model_config")
    def test_main_read_model_config_command(self, mock_read_model_config):
        # Setup test arguments
        test_args = ["shell.py", "read-model-config", "model1", "config.json"]

        with patch(
            "argparse.ArgumentParser.parse_args",
            return_value=argparse.Namespace(
                command="read-model-config", model_name="model1", config_file="config.json"
            ),
        ):
            # Execute the function under test
            main()

            # Verify the mock was called correctly
            mock_read_model_config.assert_called_once_with("model1", "config.json")

    @patch("shell.format_conversation_menu")
    def test_main_format_conversation_menu_command(self, mock_format_conversation_menu):
        # Setup test arguments
        test_args = ["shell.py", "format-conversation-menu"]

        with patch(
            "argparse.ArgumentParser.parse_args", return_value=argparse.Namespace(command="format-conversation-menu")
        ):
            # Execute the function under test
            main()

            # Verify the mock was called correctly
            mock_format_conversation_menu.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
