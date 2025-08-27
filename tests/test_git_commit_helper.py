#!/usr/bin/env python
"""
tools/git_commit_helper.py 的单元测试
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from typing import List, Optional
from unittest.mock import MagicMock, patch

from tools.git_commit_helper import GitCommitHelper, main


class TestGitCommitHelper(unittest.TestCase):
    """
    Test suite for the GitCommitHelper class.
    It uses a temporary git repository to test git commands.
    """

    def setUp(self):
        """Set up a temporary git repository for each test."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], check=True)
        # Create an initial commit to allow subsequent commits
        (Path(self.test_dir) / "initial_file.txt").write_text("initial content")
        subprocess.run(["git", "add", "initial_file.txt"], check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], check=True)

    def tearDown(self):
        """Clean up the temporary directory."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)

    def _get_last_commit_message(self) -> str:
        """Helper to get the message of the last commit."""
        return subprocess.check_output(["git", "log", "-1", "--pretty=%B"]).decode("utf-8").strip()

    def _get_commit_count(self) -> int:
        """Helper to get the total number of commits."""
        return int(subprocess.check_output(["git", "rev-list", "--count", "HEAD"]).decode("utf-8").strip())

    def test_extract_commit_message(self):
        """Test extraction of commit message from response text."""
        response_text = dedent(
            """
        Some text before.
        [git commit message]
        [start]
        feat(test): add new feature

        - More details about the feature.
        - And another line.
        [end]
        Some text after.
        """
        )
        helper = GitCommitHelper(response_text=response_text)
        expected_message = "feat(test): add new feature\n\n- More details about the feature.\n- And another line."
        self.assertEqual(helper.commit_message, expected_message)

    def test_extract_no_commit_message(self):
        """Test response text without a commit message."""
        helper = GitCommitHelper(response_text="No message here.")
        self.assertIsNone(helper.commit_message)

    def test_init_with_direct_commit_message(self):
        """Test initialization with a direct commit message, skipping extraction."""
        helper = GitCommitHelper(commit_message="Direct message", response_text="[git commit message]...[/end]")
        self.assertEqual(helper.commit_message, "Direct message")

    @patch("builtins.input", return_value="y")
    def test_confirm_and_edit_message_approve(self, mock_input):
        """Test user approving the message."""
        helper = GitCommitHelper(commit_message="test message")
        self.assertTrue(helper._confirm_and_edit_message())

    @patch("builtins.input", return_value="n")
    def test_confirm_and_edit_message_reject(self, mock_input):
        """Test user rejecting the message."""
        helper = GitCommitHelper(commit_message="test message")
        self.assertFalse(helper._confirm_and_edit_message())

    @patch("builtins.input", side_effect=["e", "new message", "END"])
    def test_confirm_and_edit_message_edit(self, mock_input):
        """Test user editing the message."""
        helper = GitCommitHelper(commit_message="old message")
        self.assertTrue(helper._confirm_and_edit_message())
        self.assertEqual(helper.commit_message, "new message")

    @patch("builtins.input", side_effect=["e", "new message with eof"])
    def test_confirm_and_edit_message_edit_with_eof(self, mock_input):
        """Test user editing the message and finishing with EOF."""
        mock_input.side_effect = ["e", "new message with eof", EOFError]
        helper = GitCommitHelper(commit_message="old message")
        self.assertTrue(helper._confirm_and_edit_message())
        self.assertEqual(helper.commit_message, "new message with eof")

    @patch("builtins.input", side_effect=["e", "", "END", "y"])
    def test_confirm_and_edit_message_edit_empty_then_approve(self, mock_input):
        """Test user provides empty edit, then approves original."""
        helper = GitCommitHelper(commit_message="original message")
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            self.assertTrue(helper._confirm_and_edit_message())
            self.assertIn("提交信息不能为空", mock_stdout.getvalue())
        self.assertEqual(helper.commit_message, "original message")

    def test_confirm_and_edit_message_auto_approve(self):
        """Test auto_approve skips confirmation."""
        helper = GitCommitHelper(commit_message="test message", auto_approve=True)
        self.assertTrue(helper._confirm_and_edit_message())

    def test_confirm_and_edit_message_no_message(self):
        """Test confirmation when no message was extracted."""
        helper = GitCommitHelper(commit_message=None)
        self.assertFalse(helper._confirm_and_edit_message())

    def test_execute_git_commands_add_files_and_commit(self):
        """Test committing specific files, including all added."""
        (Path(self.test_dir) / "file1.txt").write_text("content1")
        (Path(self.test_dir) / "file2.txt").write_text("content2")
        helper = GitCommitHelper(commit_message="commit all changes", files_to_add=["file1.txt", "file2.txt"])
        self.assertTrue(helper._execute_git_commands())
        self.assertEqual(self._get_last_commit_message(), "commit all changes")

        # Verify both files are in the commit
        diff_output = subprocess.check_output(["git", "diff", "HEAD^", "HEAD", "--name-only"]).decode()
        self.assertIn("file1.txt", diff_output)
        self.assertIn("file2.txt", diff_output)

    def test_execute_git_commands_add_specific_files(self):
        """Test committing specific files from a larger set of changes."""
        # Create new files
        (Path(self.test_dir) / "file1.txt").write_text("content1")
        (Path(self.test_dir) / "file2.txt").write_text("content2")
        helper = GitCommitHelper(commit_message="commit specific", files_to_add=["file1.txt"])
        self.assertTrue(helper._execute_git_commands())
        self.assertEqual(self._get_last_commit_message(), "commit specific")

        # Check that only file1 is in the commit
        diff_output = subprocess.check_output(["git", "diff", "HEAD^", "HEAD", "--name-only"]).decode()
        self.assertIn("file1.txt", diff_output)
        self.assertNotIn("file2.txt", diff_output)

    def test_execute_git_commands_no_files_to_add_returns_false(self):
        """Test that if files_to_add is empty, it returns False and no commit is made."""
        initial_commit_count = self._get_commit_count()
        (Path(self.test_dir) / "new_untracked_file.txt").write_text("some content")  # Create a file but don't add it

        helper = GitCommitHelper(commit_message="should not commit", files_to_add=[])

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            self.assertFalse(helper._execute_git_commands())
            self.assertIn("未指定文件，跳过添加到暂存区。", mock_stdout.getvalue())

        # Verify no new commit was made
        self.assertEqual(self._get_commit_count(), initial_commit_count)
        # Verify the file is still untracked
        status_output = subprocess.check_output(["git", "status", "--porcelain"]).decode()
        self.assertIn("?? new_untracked_file.txt", status_output)

    @patch("subprocess.run")
    def test_execute_git_commands_called_process_error(self, mock_run: MagicMock) -> None:
        """Test handling of CalledProcessError during git command."""
        # Create a temporary directory to simulate git repo
        with tempfile.TemporaryDirectory() as tmp_repo:
            mock_run.side_effect = [
                subprocess.CompletedProcess(
                    args=["git", "rev-parse"], returncode=0, stdout=f"{tmp_repo}\n", stderr=""
                ),  # For git_root
                subprocess.CompletedProcess(args=["git", "add"], returncode=0, stdout="", stderr=""),  # For git add
                subprocess.CalledProcessError(1, ["git", "commit"], "stdout", "stderr: pre-commit hook failed"),
            ]
            helper = GitCommitHelper(commit_message="a message", files_to_add=["file.txt"])
            with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                self.assertFalse(helper._execute_git_commands())
                self.assertIn("Git命令执行失败！", mock_stderr.getvalue())
                self.assertIn("pre-commit hook failed", mock_stderr.getvalue())

    @patch("subprocess.run", side_effect=FileNotFoundError("git not found"))
    def test_execute_git_commands_git_not_found(self, mock_run):
        """Test handling of FileNotFoundError (git not installed)."""
        helper = GitCommitHelper(commit_message="a message", files_to_add=["file.txt"])
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            self.assertFalse(helper._execute_git_commands())
            self.assertIn("错误: 'git' 命令未找到。", mock_stderr.getvalue())

    def test_run_full_flow_approved(self):
        """Test the full run() flow with user approval."""
        (Path(self.test_dir) / "a.txt").write_text("a")
        response = "[git commit message]\n[start]\nmy commit\n[end]"
        helper = GitCommitHelper(response_text=response, files_to_add=["a.txt"])
        with patch("builtins.input", return_value="y"):
            self.assertTrue(helper.run())
        self.assertEqual(self._get_last_commit_message(), "my commit")

    def test_run_full_flow_rejected(self):
        """Test the full run() flow with user rejection."""
        response = "[git commit message]\n[start]\nmy commit\n[end]"
        helper = GitCommitHelper(
            response_text=response, files_to_add=["b.txt"]
        )  # Needs files to add for _execute_git_commands to proceed
        with patch("builtins.input", return_value="n"), patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            self.assertFalse(helper.run())
            self.assertIn("提交已取消", mock_stdout.getvalue())

    def test_run_no_message(self):
        """Test run() when no commit message is found."""
        helper = GitCommitHelper(response_text="nothing here")
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            self.assertFalse(helper.run())
            self.assertIn("在响应中未找到有效的Git提交信息", mock_stdout.getvalue())

    @patch("builtins.input", side_effect=["invalid", "y"])
    def test_confirm_and_edit_message_invalid_input(self, mock_input):
        """Test invalid input is handled correctly."""
        helper = GitCommitHelper(commit_message="test message")
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            self.assertTrue(helper._confirm_and_edit_message())
            self.assertIn("无效输入", mock_stdout.getvalue())


class TestMainFunction(unittest.TestCase):
    """
    Test suite for the main function in git_commit_helper.py.
    """

    def setUp(self):
        """Set up a temporary directory and files for main function tests."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create a dummy response file
        self.response_file = Path(self.test_dir) / ".lastgptanswer"
        response_content = "[git commit message]\n[start]\nmain test commit\n[end]"
        self.response_file.write_text(response_content, "utf-8")

        # Setup git repo
        subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], check=True)
        # Create an initial commit to allow subsequent commits
        (Path(self.test_dir) / "initial_file_main.txt").write_text("initial content main")
        subprocess.run(["git", "add", "initial_file_main.txt"], check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit for main tests"], check=True)

    def tearDown(self):
        """Clean up the temporary directory."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir)
        # Restore sys.argv if modified
        if hasattr(self, "original_argv"):
            sys.argv = self.original_argv

    def _get_last_commit_message(self) -> str:
        """Helper to get the message of the last commit."""
        return subprocess.check_output(["git", "log", "-1", "--pretty=%B"]).decode("utf-8").strip()

    def _get_commit_count(self) -> int:
        """Helper to get the total number of commits."""
        return int(subprocess.check_output(["git", "rev-list", "--count", "HEAD"]).decode("utf-8").strip())

    def test_main_auto_approve(self):
        """Test main with --auto-approve."""
        (Path(self.test_dir) / "main_test_file.txt").write_text("data")
        self.original_argv = sys.argv
        sys.argv = [
            "git_commit_helper.py",
            "--response-file",
            str(self.response_file),
            "--auto-approve",
            "--add",  # Must provide --add for the commit to proceed
            "main_test_file.txt",
        ]

        main()
        last_commit = self._get_last_commit_message()
        self.assertEqual(last_commit, "main test commit")
        diff_output = subprocess.check_output(["git", "diff", "HEAD^", "HEAD", "--name-only"]).decode()
        self.assertIn("main_test_file.txt", diff_output)

    def test_main_with_add_files(self):
        """Test main with --add argument."""
        (Path(self.test_dir) / "another_file.txt").write_text("more data")
        self.original_argv = sys.argv
        sys.argv = [
            "git_commit_helper.py",
            "--response-file",
            str(self.response_file),
            "--auto-approve",
            "--add",
            "another_file.txt",
        ]

        main()
        diff_output = subprocess.check_output(["git", "diff", "HEAD^", "HEAD", "--name-only"]).decode()
        self.assertIn("another_file.txt", diff_output)
        self.assertNotIn("initial_file_main.txt", diff_output)  # Ensure only the added file is committed

    def test_main_response_file_not_found(self):
        """Test main when response file does not exist."""
        self.original_argv = sys.argv
        sys.argv = ["git_commit_helper.py", "--response-file", "nonexistent.txt"]
        with self.assertRaises(SystemExit) as cm, patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("响应文件未找到", mock_stderr.getvalue())

    @patch("tools.git_commit_helper.GitCommitHelper.run", return_value=False)
    def test_main_helper_run_fails(self, mock_run):
        """Test main when helper.run() returns False."""
        self.original_argv = sys.argv
        sys.argv = [
            "git_commit_helper.py",
            "--response-file",
            str(self.response_file),
            "--add",
            "dummy.txt",
        ]  # provide dummy file for run to proceed to internal logic
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)

    @patch("tools.git_commit_helper.GitCommitHelper.__init__", side_effect=Exception("Unexpected error"))
    def test_main_unexpected_exception(self, mock_init):
        """Test main handling an unexpected exception."""
        self.original_argv = sys.argv
        sys.argv = ["git_commit_helper.py", "--response-file", str(self.response_file)]
        with self.assertRaises(SystemExit) as cm, patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("发生意外错误: Unexpected error", mock_stderr.getvalue())

    def test_main_no_add_argument_no_commit(self):
        """Test main behavior when --add argument is not provided (should not commit)."""
        (Path(self.test_dir) / "untracked_main_file.txt").write_text("some content")
        initial_commit_count = self._get_commit_count()
        self.original_argv = sys.argv
        sys.argv = ["git_commit_helper.py", "--response-file", str(self.response_file), "--auto-approve"]

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, patch("sys.exit") as mock_exit:
            main()
            self.assertIn("未指定文件，跳过添加到暂存区。", mock_stdout.getvalue())
            mock_exit.assert_called_once_with(1)

        # Verify no new commit was made
        self.assertEqual(self._get_commit_count(), initial_commit_count)
        # Verify the file is still untracked
        status_output = subprocess.check_output(["git", "status", "--porcelain"]).decode()
        self.assertIn("?? untracked_main_file.txt", status_output)


if __name__ == "__main__":
    unittest.main()
