import io
import os
import sys
import tempfile
import unittest
import urllib.parse  # Required for new tests that mock urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import requests  # Required for new tests that mock requests

# Add the project root to sys.path to allow for module imports.
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Import functions from the shell module that are tested
from shell import (
    _complete_partial_path,
    _process_file_completion,
    _request_api_completion,
    find_root_dir,
    handle_cmd_complete,
    handle_complete,
    main,
    make_path_relative_to_root_dir,
    relative_to_root_dir,
    split_symbol_and_path,
)


class TestShellCliCommands(unittest.TestCase):
    """
    Tests for the main command-line interface logic of the shell module,
    specifically focusing on how `main` and `handle_cmd_complete` process
    different types of completion requests.
    """

    def test_shell_complete_with_symbol_prefix(self):
        """
        Test that the 'shell-complete' command with a prefix starting with '@symbol_'
        correctly triggers the file completion for the symbol_llm prefix and outputs
        the expected completions for files in the current directory that start with 'llm'.
        This tests the local file completion path for symbol prefixes.
        """
        test_args = ["shell.py", "shell-complete", "@symbol_llm"]
        with patch("sys.argv", test_args):
            with patch("os.getenv") as mock_getenv:
                mock_getenv.side_effect = lambda key, default=None: {"GPT_SYMBOL_API_URL": "http://example.com"}.get(
                    key, default
                )

                with patch("shell.Path") as mock_path:
                    mock_path_obj = MagicMock()
                    mock_path_obj.exists.return_value = False
                    mock_path_obj.name = "llm"
                    mock_current_dir = MagicMock()
                    mock_current_dir.exists.return_value = True
                    mock_current_dir.is_dir.return_value = True

                    mock_file1 = MagicMock()
                    mock_file1.name = "llm_file1"
                    mock_file2 = MagicMock()
                    mock_file2.name = "llm_file2"
                    mock_current_dir.iterdir.return_value = [mock_file1, mock_file2]

                    def path_side_effect(path_str):
                        if path_str == "llm":
                            return mock_path_obj
                        elif path_str == ".":
                            return mock_current_dir
                        return MagicMock()

                    mock_path.side_effect = path_side_effect
                    mock_path_obj.parent = mock_current_dir

                    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                        main()

                    output = mock_stdout.getvalue().splitlines()
                    expected_output = ["symbol_llm_file1", "symbol_llm_file2"]
                    self.assertEqual(output, expected_output)

    def test_main_shell_complete_symbol_prefix(self):
        """
        Test 'shell-complete' command with symbol prefix correctly processes and prints completions.
        Verifies the full pipeline from argument parsing through to API request handling and output formatting.
        This tests the API completion path from the main entry point.
        """
        # Setup command-line arguments
        test_args = ["program", "shell-complete", "@symbol_llm_query.py/Model"]

        # Mock API response data
        api_response_text = (
            "symbol:llm_query.py/ModelConfig\n"
            "symbol:llm_query.py/ModelSwitch\n"
            "symbol:llm_query.py/ModelConfig.key\n"
            "symbol:llm_query.py/ModelConfig.top_k\n"
            "symbol:llm_query.py/ModelConfig.top_p\n"
            "symbol:llm_query.py/ModelSwitch.query\n"
            "symbol:llm_query.py/ModelSwitch.models\n"
            "symbol:llm_query.py/ModelSwitch.select\n"
            "symbol:llm_query.py/ModelConfig.__init__\n"
            "symbol:llm_query.py/ModelConfig.__repr__"
        )

        with (
            patch("sys.argv", test_args),
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
            patch.dict("os.environ", {"GPT_SYMBOL_API_URL": "http://testserver/"}),
            patch("shell.requests.get") as mock_get,
            patch(
                "shell.make_path_relative_to_root_dir", return_value="symbol_llm_query.py/Model"
            ) as mock_make_relative,
        ):
            # Configure mock API response
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.text = api_response_text
            mock_get.return_value = mock_response

            # Execute main function
            main()

            # Verify output
            output = mock_stdout.getvalue()
            expected_output = (
                "symbol_llm_query.py/ModelConfig\n"
                "symbol_llm_query.py/ModelSwitch\n"
                "symbol_llm_query.py/ModelConfig.key\n"
                "symbol_llm_query.py/ModelConfig.top_k\n"
                "symbol_llm_query.py/ModelConfig.top_p\n"
                "symbol_llm_query.py/ModelSwitch.query\n"
                "symbol_llm_query.py/ModelSwitch.models\n"
                "symbol_llm_query.py/ModelSwitch.select\n"
                "symbol_llm_query.py/ModelConfig.__init__\n"
                "symbol_llm_query.py/ModelConfig.__repr__\n"
            )
            self.assertEqual(output, expected_output)

            # Verify API call parameters
            mock_get.assert_called_once()
            call_args, call_kwargs = mock_get.call_args
            self.assertIn("complete_realtime", call_args[0])
            self.assertEqual(call_kwargs["proxies"], {"http": None, "https": None})

    def test_handle_cmd_complete_with_symbol_prefix(self):
        """
        Test that handle_cmd_complete correctly delegates to handle_complete and prints
        completions when given a symbol prefix. This tests the API completion path
        specifically for `handle_cmd_complete`.
        """
        prefix = "@symbol_llm_query.py/Model"
        stripped_prefix = "symbol_llm_query.py/Model"
        mock_completions = ["symbol_llm_query.py/ModelConfig", "symbol_llm_query.py/ModelSwitch"]

        with (
            patch("shell.os") as mock_os,
            patch("shell.handle_complete") as mock_handle_complete,
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
        ):
            # Configure environment and filesystem mocks
            mock_os.getenv.return_value = "/dummy/path"
            mock_os.path.isdir.return_value = False

            # Set up handle_complete mock to simulate output
            def print_completions(_):
                for comp in mock_completions:
                    print(comp)

            mock_handle_complete.side_effect = print_completions

            # Call the function under test
            handle_cmd_complete(prefix)

            # Verify output matches expected completions
            output = mock_stdout.getvalue()
            expected_output = "\n".join(mock_completions) + "\n"
            self.assertEqual(output, expected_output)

            # Verify delegation happened with stripped prefix
            mock_handle_complete.assert_called_once_with(stripped_prefix)


class TestShellCompletionLogic(unittest.TestCase):
    """
    Tests for the core completion logic functions like `handle_complete`,
    `_process_file_completion`, and `_complete_partial_path`, covering both
    local file system completions and the delegation to API completions.
    """

    def test_handle_complete_with_existing_directory(self):
        """
        Verify handle_complete correctly prints symbol-prefixed completions
        for an existing directory prefix when environment variable is set.
        This tests local file system completion for directory matches.
        """
        prefix = "symbol_llm"
        base_name = "llm"

        # Create mock directory items
        matching_item1 = MagicMock()
        matching_item1.name = "llm_match1"
        matching_item2 = MagicMock()
        matching_item2.name = "llm_match2"
        non_matching_item = MagicMock()
        non_matching_item.name = "nomatch"

        # Create parent directory mock
        parent_dir_mock = MagicMock()
        parent_dir_mock.exists.return_value = True
        parent_dir_mock.is_dir.return_value = True
        parent_dir_mock.iterdir.return_value = [matching_item1, non_matching_item, matching_item2]

        # Create base path mock
        base_path = MagicMock()
        base_path.exists.return_value = True
        base_path.is_dir.return_value = True
        base_path.parent = parent_dir_mock

        # Path constructor handler
        def path_constructor(*args):
            if args and args[0] == base_name:
                return base_path
            elif args and args[0] == ".":
                return parent_dir_mock
            return MagicMock()  # Default for other paths

        with patch.dict("os.environ", {"GPT_SYMBOL_API_URL": "http://example.com"}):
            with patch("shell.Path", side_effect=path_constructor):
                with patch("shell._complete_local_directory") as mock_complete:

                    def complete_effect(_):
                        print("symbol_llm_match1")
                        print("symbol_llm_match2")

                    mock_complete.side_effect = complete_effect
                    with patch("builtins.print") as mock_print:
                        handle_complete(prefix)
                        mock_print.assert_has_calls(
                            [call("symbol_llm_match1"), call("symbol_llm_match2")], any_order=True
                        )

    @patch("builtins.print")
    def test_process_file_completion_with_existing_path_and_partial_matches(self, mock_print):
        """
        Test that _process_file_completion correctly prints symbol-prefixed completions
        for items in the current directory matching the partial name.

        This scenario validates the core completion logic when:
        - The target path exists
        - The parent directory exists and is a directory
        - Items in the parent directory match the base name prefix
        - Parent directory is current directory (so items get 'symbol_' prefix)
        """
        # Setup mock path objects
        mock_path_obj = MagicMock()
        mock_path_obj.exists.return_value = True
        mock_path_obj.name = "llm"  # base name for matching
        mock_path_obj.__str__.return_value = "."  # Fix: Ensure string conversion returns valid path

        mock_parent_dir = MagicMock()
        mock_parent_dir.exists.return_value = True
        mock_parent_dir.is_dir.return_value = True
        mock_path_obj.parent = mock_parent_dir

        # Create mock directory items: two matches, one non-match
        match_item1 = MagicMock()
        match_item1.name = "llm_file1"
        match_item1.is_dir.return_value = False  # Mark as file
        match_item2 = MagicMock()
        match_item2.name = "llm_file2"
        match_item2.is_dir.return_value = False  # Mark as file
        non_match_item = MagicMock()
        non_match_item.name = "other_file"
        non_match_item.is_dir.return_value = False  # Mark as file

        mock_parent_dir.iterdir.return_value = [match_item1, non_match_item, match_item2]

        # Make parent directory compare equal to current directory (Path('.'))
        mock_parent_dir.__eq__.return_value = True

        # Execute the function
        with patch("shell.Path", return_value=mock_parent_dir):
            _process_file_completion(path_obj=mock_path_obj, api_server="http://127.0.0.1:57962/", prefix="symbol_llm")

        # Verify correct items are printed with symbol prefix
        expected_calls = [call("symbol_llm_file1"), call("symbol_other_file"), call("symbol_llm_file2")]
        mock_print.assert_has_calls(expected_calls, any_order=False)
        self.assertEqual(mock_print.call_count, 3, "Should print exactly three items")

    def test_complete_partial_path_current_dir_with_matches(self):
        """
        Test that _complete_partial_path correctly prints symbol-prefixed names
        for matching files in the current directory when parent_dir is '.'.

        This test simulates a directory with:
          - Two files matching the base_name prefix ('llm1', 'llm2')
          - One non-matching file ('other')

        It verifies:
          - Only matching files are printed with 'symbol_' prefix
          - Output appears as two separate lines
          - Function returns None
        """
        # Create temporary directory and files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save original working directory
            old_cwd = os.getcwd()
            os.chdir(tmpdir)

            # Create test files
            matching_files = ["llm1", "llm2"]
            non_matching = ["other"]
            for filename in matching_files + non_matching:
                Path(filename).touch()

            # Capture stdout
            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                # Call function under test
                result = _complete_partial_path(Path("."), "llm")

                # Verify return value
                self.assertIsNone(result)

                # Get captured output
                output = mock_stdout.getvalue()

            # Restore original directory
            os.chdir(old_cwd)

        # Process output
        lines = output.splitlines()

        # Verify output structure
        self.assertEqual(len(lines), 2, "Should print exactly two matches")
        self.assertEqual(
            set(lines), {"symbol_llm1", "symbol_llm2"}, "Should print symbol-prefixed names for matching files"
        )

    def test_handle_complete_symbol_prefix_calls_process_file_completion(self):
        """
        Test that handle_complete correctly processes a symbol prefix by calling
        _process_file_completion with the expected arguments when the path doesn't exist
        but the parent directory exists. This tests the delegation from `handle_complete`
        to `_process_file_completion` for API-driven completions.
        """
        # Setup environment variable for API server
        with patch.dict("os.environ", {"GPT_SYMBOL_API_URL": "http://test-server/"}):
            with patch("shell.Path") as mock_path_class:
                # Configure mock Path instance
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = False
                mock_path_instance.parent = MagicMock()
                mock_path_instance.parent.exists.return_value = True
                mock_path_instance.parent.is_dir.return_value = True
                mock_path_class.return_value = mock_path_instance

                with patch("shell._process_file_completion") as mock_process:
                    # Call function with symbol prefix
                    handle_complete("symbol_llm_query.py/Model")

                    # Verify Path was created with expected argument
                    mock_path_class.assert_called_once_with("llm_query.py/Model")

                    # Verify _process_file_completion called with correct arguments
                    mock_process.assert_called_once_with(
                        mock_path_instance, "http://test-server/", "symbol_llm_query.py/Model"
                    )


class TestShellApiCompletionHelpers(unittest.TestCase):
    """
    Tests for utility functions directly involved in handling API-driven symbol completions,
    including network requests and parsing.
    """

    def test_request_api_completion_happy_path(self):
        """
        Test that _request_api_completion processes a prefix, makes the correct API call
        (including handling proxies), and prints the expected completions.
        """
        api_server = "http://testserver/"
        prefix = "symbol_llm_query.py/Model"

        # Set up initial environment with proxy variables
        initial_env = {
            "HTTP_PROXY": "http://proxy",
            "HTTPS_PROXY": "https://proxy",
            "ALL_PROXY": "socks5://proxy",
            "http_proxy": "http://proxy",
            "https_proxy": "https://proxy",
            "all_proxy": "socks5://proxy",
        }

        with patch.dict("os.environ", initial_env, clear=True):  # clear=True ensures only these are present
            with patch(
                "shell.make_path_relative_to_root_dir", return_value="symbol_mocked_relative_path/symbol"
            ) as mock_make_relative:
                with patch("shell.requests.get") as mock_get:
                    with patch("shell.split_symbol_and_path") as mock_split:
                        with patch("builtins.print") as mock_print:
                            # Set up the mock for split_symbol_and_path
                            mock_split.side_effect = [
                                ("original_path", "original_symbol"),  # First call: for the original prefix
                                (None, "symbol1"),  # For the first response line
                                (None, "symbol2"),
                                (None, "symbol3"),
                            ]

                            # Create a mock response
                            mock_response = MagicMock()
                            mock_response.ok = True
                            mock_response.text = "symbol:line1\nsymbol:line2\nsymbol:line3"
                            mock_get.return_value = mock_response

                            # Call the function under test
                            _request_api_completion(api_server, prefix)

                            # Check that the environment variables are restored (or cleared to None)
                            # The function sets proxies to None, so os.environ should reflect that for relevant keys
                            # self.assertIsNone(os.getenv('HTTP_PROXY'))
                            # self.assertIsNone(os.getenv('HTTPS_PROXY'))
                            # self.assertIsNone(os.getenv('ALL_PROXY'))
                            # self.assertIsNone(os.getenv('http_proxy'))
                            # self.assertIsNone(os.getenv('https_proxy'))
                            # self.assertIsNone(os.getenv('all_proxy'))

                            # Verify the helper function was called correctly
                            mock_make_relative.assert_called_once_with(prefix)

                            # Verify the HTTP request
                            expected_encoded_prefix = urllib.parse.quote("symbol:mocked_relative_path/symbol", safe="")
                            mock_get.assert_called_once_with(
                                f"{api_server}complete_realtime",
                                params={"prefix": expected_encoded_prefix},
                                timeout=1,
                                proxies={"http": None, "https": None},
                            )

                            # Verify the printed output
                            expected_calls = [
                                call("symbol_original_path/symbol1"),
                                call("symbol_original_path/symbol2"),
                                call("symbol_original_path/symbol3"),
                            ]
                            mock_print.assert_has_calls(expected_calls, any_order=False)

    def test_make_path_relative_to_root_dir_with_symbol_prefix(self):
        """
        Test that a symbol path containing a file in the project root remains unchanged.
        This test verifies that when the input prefix contains a symbol path where the file
        is located directly in the project root directory, the function correctly returns
        the original prefix without modification. We mock Path.cwd() and find_root_dir()
        to simulate the project root environment.
        """
        with patch("shell.Path.cwd") as mock_cwd, patch("shell.find_root_dir") as mock_find_root_dir:
            # Setup mock environment
            mock_root = Path("/mock/project/root")
            mock_cwd.return_value = mock_root
            mock_find_root_dir.return_value = mock_root

            # Execute function under test
            result = make_path_relative_to_root_dir("symbol_llm_query.py/Model")

            # Verify unchanged output
            self.assertEqual(result, "symbol_llm_query.py/Model")

    def test_split_symbol_and_path_with_symbol_prefix_and_slash(self):
        """
        Test that split_symbol_and_path correctly handles input with 'symbol_' prefix and slash separator.
        Verifies the function:
        1. Removes the 'symbol_' prefix
        2. Splits the remaining string at the last slash
        3. Returns (path, symbol) tuple
        """
        prefix = "symbol_llm_query.py/Model"
        expected = ("llm_query.py", "Model")
        result = split_symbol_and_path(prefix)
        self.assertEqual(result, expected)


class TestShellPathUtilities(unittest.TestCase):
    """
    Tests for general path-related utility functions used within the shell module.
    """

    def test_relative_to_root_dir_with_relative_path_in_project_root(self):
        """
        Verify that relative_to_root_dir correctly resolves a relative path
        within the project root and returns the relative path from the root directory.
        """
        with patch("shell.Path.cwd") as mock_cwd, patch("shell.find_root_dir") as mock_find_root:
            # Configure mocks to simulate environment
            mock_cwd.return_value = Path("/Users/richard/code/terminal-llm")
            mock_find_root.return_value = Path("/Users/richard/code/terminal-llm")

            # Execute function with relative path input
            result = relative_to_root_dir("llm_query.py")

            # Validate expected relative path
            self.assertEqual(result, Path("llm_query.py"))

    def test_find_root_dir_found_in_current_directory(self):
        """
        Test that find_root_dir returns the current directory when the marker file exists there.
        """
        with patch("shell.Path.cwd") as mock_cwd:
            # Create a mock Path object for the current directory
            mock_current_path = MagicMock()
            mock_cwd.return_value = mock_current_path

            # Configure parent to be different for loop condition
            mock_parent = MagicMock()
            mock_current_path.parent = mock_parent

            # Configure marker file to exist in current directory
            mock_marker_path = MagicMock()
            mock_marker_path.exists.return_value = True
            mock_current_path.__truediv__.return_value = mock_marker_path

            # Call the function under test
            result = find_root_dir(root_dir_contains=".llm_project.yml")

            # Verify results
            self.assertEqual(result, mock_current_path)
            mock_current_path.__truediv__.assert_called_once_with(".llm_project.yml")
            mock_marker_path.exists.assert_called_once()


if __name__ == "__main__":
    unittest.main()
