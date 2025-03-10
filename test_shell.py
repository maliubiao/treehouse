#!/usr/bin/env python3
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from shell import handle_complete


class TestShellCompletion(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.mock_api = "http://mock-server/"
        os.environ["GPT_API_SERVER"] = self.mock_api

        # Setup complex test directory structure
        self.root = Path(self.test_dir.name)
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
        from io import StringIO

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
                f"symbol_{self.root}/lsp/",
                [
                    f"symbol_{self.root}/lsp/subdir/",
                    f"symbol_{self.root}/lsp/file1.txt",
                    f"symbol_{self.root}/lsp/.hidden_file",
                    f"symbol_{self.root}/lsp/special@file",
                ],
            ),
            (f"symbol_{self.root}/lsp/subdir/", [f"symbol_{self.root}/lsp/subdir/nested_file.md"]),
        ]

        for prefix, expected in test_cases:
            with self.subTest(prefix=prefix):
                result = self._capture_completion(prefix)
                self.assertCountEqual(expected, result)

    def test_partial_completion(self):
        test_cases = [
            (
                f"symbol_{self.root}/partial/mat",
                [f"symbol_{self.root}/partial/match_file", f"symbol_{self.root}/partial/match_file2"],
            ),
            (f"symbol_{self.root}/lsp/file", [f"symbol_{self.root}/lsp/file1.txt"]),
        ]

        for prefix, expected in test_cases:
            with self.subTest(prefix=prefix):
                result = self._capture_completion(prefix)
                self.assertCountEqual(expected, result)

    def test_special_cases(self):
        test_cases = [
            (f"symbol_{self.root}/lsp/.hid", [f"symbol_{self.root}/lsp/.hidden_file"]),
            (f"symbol_{self.root}/lsp/special@", [f"symbol_{self.root}/lsp/special@file"]),
            (f"symbol_{self.root}/multi/slash/path/", [f"symbol_{self.root}/multi/slash/path/test_file"]),
        ]

        for prefix, expected in test_cases:
            with self.subTest(prefix=prefix):
                result = self._capture_completion(prefix)
                self.assertCountEqual(expected, result)

    def test_api_fallback(self):
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.text = "symbol:api_result1\nsymbol:api_result2"
            mock_get.return_value = mock_response

            result = self._capture_completion("symbol_non/existent/path")
            self.assertEqual(["symbol_api_result1", "symbol_api_result2"], result)

    def test_error_handling(self):
        test_cases = [
            ("symbol_invalid_prefix", []),
            (f"symbol_{self.root}/empty_dir/", []),
            ("symbol_missing_dir/", []),
        ]

        for prefix, expected in test_cases:
            with self.subTest(prefix=prefix):
                result = self._capture_completion(prefix)
                self.assertEqual(expected, result)

    def test_api_error_logging(self):
        with self.assertLogs(level="ERROR") as cm:
            with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Connection error")):
                self._capture_completion("symbol_broken/path")
                self.assertTrue(any("API request failed" in log for log in cm.output))


if __name__ == "__main__":
    unittest.main()
