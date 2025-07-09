import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, call, mock_open, patch

project_root = Path(__file__).resolve().parent.parent / "debugger/lldb"

sys.path.insert(0, str(project_root))
from tracer.source_handler import SourceHandler

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))


@patch.dict("sys.modules", {"lldb": MagicMock()})
class TestSourceHandlerInitialization(unittest.TestCase):
    """Test cases for SourceHandler initialization."""

    def setUp(self):
        """Set up test environment with mocked Tracer and dependencies."""
        self.mock_tracer = MagicMock()
        self.mock_tracer.config_manager.get_source_search_paths.return_value = []
        self.mock_tracer.logger = MagicMock(spec=logging.Logger)
        self.source_handler = SourceHandler(self.mock_tracer)

    def test_init_initializes_attributes_correctly(self):
        """
        Tests that SourceHandler initializes all attributes correctly
        when provided with a valid tracer object. This test does not use setUp.
        """
        # Create mock tracer with required attributes
        mock_tracer = MagicMock()
        mock_tracer.logger = MagicMock()
        mock_tracer.config_manager.get_source_search_paths.return_value = ["/search/path1", "/search/path2"]

        # Instantiate SourceHandler
        handler = SourceHandler(mock_tracer)

        # Verify tracer reference
        self.assertIs(handler.tracer, mock_tracer)

        # Verify logger reference
        self.assertIs(handler.logger, mock_tracer.logger)

        # Verify source search paths
        self.assertEqual(
            handler._source_search_paths, ["/search/path1", "/search/path2"], "Should correctly set source search paths"
        )

        # Verify cache initialization
        self.assertEqual(handler._resolved_path_cache, {}, "Path cache should be empty dictionary")
        self.assertEqual(handler._line_entries_cache, {}, "Line entries cache should be empty dictionary")
        self.assertEqual(handler._line_to_next_line_cache, {}, "Line-to-next-line cache should be empty dictionary")

    def test_initialization(self):
        """Test that SourceHandler initializes with correct attributes and dependencies after setUp."""
        self.assertIs(self.source_handler.tracer, self.mock_tracer)
        self.assertIs(self.source_handler.logger, self.mock_tracer.logger)
        self.assertEqual(
            self.source_handler._source_search_paths,
            [],  # From setUp default
        )
        self.assertEqual(self.source_handler._resolved_path_cache, {})
        self.assertEqual(self.source_handler._line_entries_cache, {})
        self.assertEqual(self.source_handler._line_to_next_line_cache, {})


@patch.dict("sys.modules", {"lldb": MagicMock()})
class TestSourceHandlerFileReading(unittest.TestCase):
    """Test cases for SourceHandler's file reading functionality."""

    def setUp(self):
        """Set up test environment with mocked Tracer and dependencies."""
        self.mock_tracer = MagicMock()
        self.mock_tracer.config_manager.get_source_search_paths.return_value = []
        self.mock_tracer.logger = MagicMock(spec=logging.Logger)
        self.source_handler = SourceHandler(self.mock_tracer)

    @patch("builtins.open", new_callable=mock_open, read_data=b"line1\nline2\nline3")
    def test_get_file_lines_success(self, mock_file_open):
        """Test reading file lines successfully with caching."""
        file_path = "/test/path/file.py"

        # First call - should read from filesystem
        result = self.source_handler.get_file_lines(file_path)
        self.assertEqual(result, ["line1", "line2", "line3"])
        mock_file_open.assert_called_once_with(file_path, "rb")

        # Second call - should return cached result
        mock_file_open.reset_mock()
        result_cached = self.source_handler.get_file_lines(file_path)
        self.assertEqual(result_cached, ["line1", "line2", "line3"])
        mock_file_open.assert_not_called()

    @patch("builtins.open", side_effect=FileNotFoundError("File not found"))
    def test_get_file_lines_file_not_found(self, mock_file_open):
        """Tests handling of FileNotFoundError with proper warning."""
        filepath = "/missing/file.c"

        result = self.source_handler.get_file_lines(filepath)

        self.assertIsNone(result)
        self.mock_tracer.logger.warning.assert_called_once()
        args, _ = self.mock_tracer.logger.warning.call_args
        self.assertEqual(args[1], filepath)  # 正确验证文件路径在第二个参数
        self.assertIn("File not found", str(args[2]))  # 验证异常信息

    @patch("builtins.open", side_effect=PermissionError("Access denied"))
    def test_get_file_lines_permission_error(self, mock_file_open):
        """Tests handling of PermissionError with proper warning."""
        filepath = "/restricted/file.c"

        result = self.source_handler.get_file_lines(filepath)

        self.assertIsNone(result)
        self.mock_tracer.logger.warning.assert_called_once()
        args, _ = self.mock_tracer.logger.warning.call_args
        self.assertEqual(args[1], filepath)  # 修复：直接验证第二个参数是否为文件路径
        self.assertIn("Access denied", str(args[2]))  # 新增：验证错误消息

    @patch("builtins.open", side_effect=ValueError("Unexpected error"))
    def test_get_file_lines_unexpected_error(self, mock_file_open):
        """Tests handling of unexpected errors with proper logging."""
        filepath = "/problematic/file.c"

        result = self.source_handler.get_file_lines(filepath)

        self.assertIsNone(result)
        self.mock_tracer.logger.error.assert_called_once()
        args, kwargs = self.mock_tracer.logger.error.call_args

        # Extract formatted message
        formatted_msg = args[0] % (args[1], str(args[2]))
        self.assertIn(filepath, formatted_msg)
        self.assertIn("Unexpected error", formatted_msg)
        self.assertTrue(kwargs.get("exc_info", False))


@patch.dict("sys.modules", {"lldb": MagicMock()})
class TestSourceHandlerPathResolution(unittest.TestCase):
    """Test cases for SourceHandler's path resolution functionality."""

    def setUp(self):
        """Set up test environment with mocked Tracer and dependencies."""
        self.mock_tracer = MagicMock()
        self.mock_tracer.config_manager.get_source_search_paths.return_value = []
        self.mock_tracer.logger = MagicMock(spec=logging.Logger)
        self.source_handler = SourceHandler(self.mock_tracer)

    def test_resolve_source_path_absolute_exists(self):
        """Tests resolution when provided absolute path exists by mocking os.path."""
        # Setup
        test_path = "/fake/abs/path/to/file.c"

        # Mock filesystem interactions specifically within source_handler's os.path usage
        with patch("tracer.source_handler.os.path") as mock_os_path:
            mock_os_path.isabs.return_value = True
            mock_os_path.exists.return_value = True
            mock_os_path.resolve.side_effect = lambda x: x  # Mock resolve to return path itself

            # Execute
            result = self.source_handler.resolve_source_path(test_path)

            # Assert
            self.assertEqual(result, test_path)
            self.assertEqual(self.source_handler._resolved_path_cache[test_path], test_path)
            mock_os_path.isabs.assert_called_once_with(test_path)
            mock_os_path.exists.assert_called_once_with(test_path)

    def test_resolve_source_path_relative_found_in_search(self):
        """Test resolving relative path using search paths."""
        rel_path = "relative/file.py"
        resolved_path = "/test/search/path1/relative/file.py"
        self.source_handler._source_search_paths = ["/test/search/path1", "/test/search/path2"]

        with (
            patch("tracer.source_handler.os.path.exists") as mock_exists,
            patch("tracer.source_handler.Path") as MockPath,
        ):
            # Mock Path.cwd() to control current working directory behavior
            MockPath.cwd.return_value = MagicMock(spec=Path)
            MockPath.cwd.return_value.__truediv__.return_value = MagicMock(
                spec=Path, resolve=MagicMock(return_value=Path("/cwd/relative/file.py"))
            )  # Mock Path.cwd() / rel_path

            # Mock Path constructor for search paths
            def mock_path_constructor(path_str):
                if path_str == rel_path:
                    # For Path(rel_path).resolve() when trying current directory
                    return MagicMock(spec=Path, resolve=MagicMock(return_value=Path("/cwd/relative/file.py")))
                elif path_str == "/test/search/path1":
                    return MagicMock(
                        spec=Path,
                        __truediv__=MagicMock(
                            return_value=MagicMock(spec=Path, resolve=MagicMock(return_value=Path(resolved_path)))
                        ),
                    )
                elif path_str == "/test/search/path2":
                    return MagicMock(
                        spec=Path,
                        __truediv__=MagicMock(
                            return_value=MagicMock(
                                spec=Path, resolve=MagicMock(return_value=Path("/test/search/path2/relative/file.py"))
                            )
                        ),
                    )
                return Path(path_str)  # Fallback for other Path constructions

            MockPath.side_effect = mock_path_constructor
            MockPath.return_value = MagicMock(resolve=MagicMock(return_value=Path("/resolved/path")))  # Default return

            mock_exists.side_effect = lambda path: path == resolved_path

            result = self.source_handler.resolve_source_path(rel_path)
            self.assertEqual(result, str(Path(resolved_path).resolve()))  # Path.resolve() returns resolved version
            self.assertEqual(self.source_handler._resolved_path_cache[rel_path], str(Path(resolved_path).resolve()))

    def test_resolve_source_path_found_in_cwd(self):
        """Test resolving relative path in current working directory."""
        rel_path = "local.py"
        abs_path = str(Path.cwd() / rel_path)  # Use real Path for initial construction

        with (
            patch("tracer.source_handler.os.path.exists") as mock_exists,
            patch("tracer.source_handler.Path") as MockPath,
        ):
            # Make MockPath act like real Path for .cwd() and division
            MockPath.cwd.return_value = Path.cwd()  # Actual Path object
            MockPath.side_effect = lambda x: Path(x)  # For Path(path_str)
            MockPath.return_value = MagicMock(
                resolve=MagicMock(return_value=Path(abs_path).resolve())
            )  # For Path(abs_path).resolve()

            mock_exists.side_effect = lambda path: path == str(Path(abs_path).resolve())
            result = self.source_handler.resolve_source_path(rel_path)
            self.assertEqual(result, str(Path(abs_path).resolve()))
            self.assertEqual(self.source_handler._resolved_path_cache[rel_path], str(Path(abs_path).resolve()))

    def test_resolve_source_path_not_found(self):
        """Test handling unresolvable paths gracefully."""
        bad_path = "missing.py"
        self.source_handler._source_search_paths = ["/test/search/path1", "/test/search/path2"]

        with patch("tracer.source_handler.os.path.exists", return_value=False):
            result = self.source_handler.resolve_source_path(bad_path)
            self.assertIsNone(result)
            self.assertEqual(self.source_handler._resolved_path_cache[bad_path], None)
            self.mock_tracer.logger.warning.assert_called_once_with(
                "Source file not found: '%s'. Searched in: %s", bad_path, ["/test/search/path1", "/test/search/path2"]
            )

    def test_resolve_source_path_cached(self):
        """Test that resolve_source_path returns cached result when available."""
        # Setup
        test_path = "/Users/richard/code/terminal-llm/debugger/lldb/basic_program/basic_main.c"

        # Pre-populate cache
        self.source_handler._resolved_path_cache[test_path] = test_path

        # Execute
        result = self.source_handler.resolve_source_path(test_path)

        # Verify
        self.assertEqual(result, test_path, "Should return cached path without file system checks")
        # Ensure no filesystem calls if cached
        with patch("tracer.source_handler.os.path.isabs") as mock_isabs:
            self.source_handler.resolve_source_path(test_path)
            mock_isabs.assert_not_called()


@patch.dict("sys.modules", {"lldb": MagicMock()})
class TestSourceHandlerLineMapBuilding(unittest.TestCase):
    """Test cases for SourceHandler's line entry processing and line map building."""

    def setUp(self):
        """Set up test environment with mocked Tracer and dependencies."""
        self.mock_tracer = MagicMock()
        self.mock_tracer.config_manager.get_source_search_paths.return_value = []
        self.mock_tracer.logger = MagicMock(spec=logging.Logger)
        self.source_handler = SourceHandler(self.mock_tracer)

    # @patch("tracer.source_handler.Progress")
    # @patch("tracer.source_handler.TextColumn")
    # @patch("tracer.source_handler.BarColumn")
    # @patch("tracer.source_handler.MofNCompleteColumn")
    # @patch("tracer.source_handler.TimeRemainingColumn")
    # def test_get_compile_unit_line_entries_large_compile_unit(self, *mocks):
    #     """
    #     Tests that _get_compile_unit_line_entries correctly handles large compile units
    #     (>500 entries) by using the progress bar and processing all valid entries.
    #     Verifies that the progress bar is initialized but doesn't test its UI behavior.
    #     """
    #     # Setup mock compile unit
    #     mock_compile_unit = MagicMock()
    #     mock_file_spec = MagicMock()
    #     mock_file_spec.GetDirectory.return_value = "/mock/dir"
    #     mock_file_spec.GetFilename.return_value = "large_file.c"
    #     mock_compile_unit.GetFileSpec.return_value = mock_file_spec

    #     # Create 600 valid entries
    #     num_entries = 600
    #     valid_entries = []
    #     for i in range(num_entries):
    #         entry = MagicMock()
    #         entry.IsValid.return_value = True
    #         entry.GetLine.return_value = i + 1
    #         entry.GetColumn.return_value = 0
    #         valid_entries.append(entry)

    #     mock_compile_unit.GetNumLineEntries.return_value = num_entries
    #     mock_compile_unit.GetLineEntryAtIndex.side_effect = lambda idx: valid_entries[idx]

    #     # Execute function
    #     result = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)

    #     # Verify results
    #     self.assertEqual(len(result), num_entries)
    #     self.assertEqual([e.GetLine() for e in result], list(range(1, num_entries + 1)))

    #     # Verify caching
    #     cache_key = "/mock/dir/large_file.c"
    #     self.assertIn(cache_key, self.source_handler._line_entries_cache)
    #     self.assertEqual(result, self.source_handler._line_entries_cache[cache_key])

    def test_get_compile_unit_line_entries_small_compile_unit(self):
        """
        Tests that _get_compile_unit_line_entries correctly processes a small compile unit
        (<500 entries) by:
        1. Generating the correct cache key
        2. Filtering invalid/zero-line entries
        3. Sorting valid entries by line and column
        4. Caching results for subsequent calls
        """
        # Setup mock compile unit
        mock_compile_unit = MagicMock()
        mock_file_spec = MagicMock()
        mock_file_spec.GetDirectory.return_value = "/mock/dir"
        mock_file_spec.GetFilename.return_value = "mock_file.c"
        mock_compile_unit.GetFileSpec.return_value = mock_file_spec

        # Create 8 valid and 2 invalid line entries
        valid_entries = []
        line_cols = [(1, 0), (2, 1), (3, 100), (3, 50), (4, 4), (5, 5), (6, 6), (7, 7)]
        for line, col in line_cols:
            entry = MagicMock()
            entry.IsValid.return_value = True
            entry.GetLine.return_value = line
            entry.GetColumn.return_value = col
            valid_entries.append(entry)

        invalid_entries = [
            MagicMock(IsValid=MagicMock(return_value=True), GetLine=MagicMock(return_value=0)),  # Valid but line=0
            MagicMock(IsValid=MagicMock(return_value=False)),  # Invalid entry
        ]

        all_entries = valid_entries + invalid_entries
        num_entries = len(all_entries)
        mock_compile_unit.GetNumLineEntries.return_value = num_entries
        mock_compile_unit.GetLineEntryAtIndex.side_effect = lambda idx: all_entries[idx]

        # First call - uncached
        result = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)

        # Verify results
        self.assertEqual(len(result), len(valid_entries))
        # Check sorted order: (line, column)
        expected_order = [1, 2, 3, 3, 4, 5, 6, 7]
        expected_columns = [0, 1, 50, 100, 4, 5, 6, 7]
        for i, entry in enumerate(result):
            self.assertEqual(entry.GetLine(), expected_order[i])
            self.assertEqual(entry.GetColumn(), expected_columns[i])

        # Verify caching
        cache_key = "/mock/dir/mock_file.c"
        self.assertIn(cache_key, self.source_handler._line_entries_cache)
        self.assertEqual(result, self.source_handler._line_entries_cache[cache_key])

        # Reset mock call counters
        mock_compile_unit.GetNumLineEntries.reset_mock()
        mock_compile_unit.GetLineEntryAtIndex.reset_mock()

        # Second call - cached
        result_cached = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)
        self.assertEqual(result, result_cached)
        mock_compile_unit.GetNumLineEntries.assert_not_called()
        mock_compile_unit.GetLineEntryAtIndex.assert_not_called()

    def test_get_compile_unit_line_entries_empty_compile_unit(self):
        """Test that empty compile units return an empty list of line entries."""
        mock_compile_unit = MagicMock()
        mock_file_spec = MagicMock()
        mock_file_spec.GetDirectory.return_value = "/empty/dir"
        mock_file_spec.GetFilename.return_value = "empty_file.c"
        mock_compile_unit.GetFileSpec.return_value = mock_file_spec
        mock_compile_unit.GetNumLineEntries.return_value = 0

        # Clear cache to ensure fresh test
        self.source_handler._line_entries_cache = {}

        result = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)

        # Correct assertion: verify empty list is returned
        self.assertEqual(result, [])
        # Verify cache was populated correctly
        self.assertEqual(self.source_handler._line_entries_cache["/empty/dir/empty_file.c"], [])

    def test_build_line_to_next_line_map_raises_when_get_line_entries_fails(self):
        """
        Test that _build_line_to_next_line_map propagates exceptions raised by
        _get_compile_unit_line_entries during map construction.

        This simulates a scenario where the helper method fails due to unexpected
        conditions (e.g., invalid compile unit, debug info issues). The test ensures
        the exception isn't swallowed and cache remains unaffected.
        """
        # Create mock Tracer with logger and config manager
        tracer_mock = MagicMock()
        tracer_mock.logger = MagicMock()
        tracer_mock.config_manager = MagicMock()
        tracer_mock.config_manager.get_source_search_paths.return_value = []

        # Initialize SourceHandler instance
        source_handler = SourceHandler(tracer_mock)

        # Create mock compile unit with file spec
        compile_unit_mock = MagicMock()  # lldb.SBCompileUnit spec not needed as it's mocked
        file_spec_mock = MagicMock()
        dummy_filepath = "/dummy/file.c"
        file_spec_mock.fullpath = dummy_filepath
        compile_unit_mock.GetFileSpec.return_value = file_spec_mock

        # Ensure cache doesn't contain our test filepath
        self.assertNotIn(dummy_filepath, source_handler._line_to_next_line_cache)

        # Configure helper method to raise exception
        exception_msg = "Simulated debug info failure"
        with patch.object(source_handler, "_get_compile_unit_line_entries", side_effect=RuntimeError(exception_msg)):
            with self.assertRaises(RuntimeError) as cm:
                source_handler._build_line_to_next_line_map(compile_unit_mock)

            # Verify correct exception message
            self.assertEqual(str(cm.exception), exception_msg)

            # Ensure cache wasn't modified after failure
            self.assertNotIn(dummy_filepath, source_handler._line_to_next_line_cache)

    def test_returns_cached_map_when_filepath_exists_in_cache(self):
        """Tests that cached line map is returned when filepath exists in cache."""
        # Setup
        mock_filepath = "/path/to/file.c"
        expected_map = {10: (20, 5), 30: (30, 0)}
        self.source_handler._line_to_next_line_cache = {mock_filepath: expected_map}

        mock_compile_unit = MagicMock()
        mock_file_spec = MagicMock()
        mock_file_spec.fullpath = mock_filepath
        mock_compile_unit.GetFileSpec.return_value = mock_file_spec

        # Execute
        result = self.source_handler._build_line_to_next_line_map(mock_compile_unit)

        # Verify
        self.assertEqual(result, expected_map)
        mock_compile_unit.GetFileSpec.assert_called_once()

    def test_builds_and_caches_map_when_not_in_cache(self):
        """Tests that line map is built and cached when not present in cache."""
        # Setup
        mock_filepath = "/path/to/file.c"
        self.source_handler._line_to_next_line_cache = {}

        mock_compile_unit = MagicMock()
        mock_file_spec = MagicMock()
        mock_file_spec.fullpath = mock_filepath
        mock_compile_unit.GetFileSpec.return_value = mock_file_spec

        # Mock line entries
        mock_entry1 = MagicMock()
        mock_entry1.GetLine.return_value = 10
        mock_entry1.GetColumn.return_value = 5

        mock_entry2 = MagicMock()
        mock_entry2.GetLine.return_value = 20
        mock_entry2.GetColumn.return_value = 3

        mock_entry3 = MagicMock()
        mock_entry3.GetLine.return_value = 20
        mock_entry3.GetColumn.return_value = 7

        mock_entry4 = MagicMock()
        mock_entry4.GetLine.return_value = 30
        mock_entry4.GetColumn.return_value = 1

        # Patch internal method to return mock entries
        with patch.object(
            self.source_handler,
            "_get_compile_unit_line_entries",
            return_value=[mock_entry1, mock_entry2, mock_entry3, mock_entry4],
        ) as mock_get_entries:
            # Execute
            result = self.source_handler._build_line_to_next_line_map(mock_compile_unit)

            # Verify
            expected_map = {
                10: (20, 3),  # First occurrence of line 10 maps to next entry (20,3)
                20: (20, 7),  # First occurrence of line 20 maps to next entry (20,7)
                30: (30, 0),  # Last entry maps to itself with column 0
            }
            self.assertEqual(result, expected_map)
            self.assertEqual(self.source_handler._line_to_next_line_cache[mock_filepath], expected_map)
            mock_get_entries.assert_called_once_with(mock_compile_unit)

    def test_returns_empty_map_when_no_line_entries(self):
        """Tests that empty map is returned when no valid line entries exist."""
        # Setup
        mock_filepath = "/path/to/file.c"
        self.source_handler._line_to_next_line_cache = {}

        mock_compile_unit = MagicMock()
        mock_file_spec = MagicMock()
        mock_file_spec.fullpath = mock_filepath
        mock_compile_unit.GetFileSpec.return_value = mock_file_spec

        # Patch to return empty entries list
        with patch.object(self.source_handler, "_get_compile_unit_line_entries", return_value=[]):
            # Execute
            result = self.source_handler._build_line_to_next_line_map(mock_compile_unit)

            # Verify
            self.assertEqual(result, {})
            self.assertEqual(self.source_handler._line_to_next_line_cache[mock_filepath], {})


@patch.dict("sys.modules", {"lldb": MagicMock()})
class TestSourceHandlerStatementExtraction(unittest.TestCase):
    """Test cases for SourceHandler's statement extraction functionality."""

    def setUp(self):
        """Set up test environment with mocked Tracer and dependencies."""
        self.mock_tracer = MagicMock()
        self.mock_tracer.config_manager.get_source_search_paths.return_value = []
        self.mock_tracer.logger = MagicMock(spec=logging.Logger)
        self.source_handler = SourceHandler(self.mock_tracer)

    def test_get_source_code_for_statement_when_build_map_raises(self):
        """
        Test that get_source_code_for_statement correctly propagates exceptions
        raised during the _build_line_to_next_line_map call.

        This simulates a scenario where the internal call to build the line map
        fails due to an unexpected frame exit condition. The test verifies that
        the exception propagates correctly.
        """
        # Create mock frame and line entry
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec().fullpath = "/mock/path/file.c"
        mock_line_entry.GetLine.return_value = 195

        mock_compile_unit = MagicMock()
        mock_frame = MagicMock()
        mock_frame.GetLineEntry.return_value = mock_line_entry
        mock_frame.GetCompileUnit.return_value = mock_compile_unit

        # Setup mock responses for helper methods
        self.source_handler.resolve_source_path = MagicMock(return_value="/resolved/path/file.c")
        self.source_handler.get_file_lines = MagicMock(return_value=["line"] * 300)

        # Configure the exception to be raised
        exception_msg = "Frame exited without a 'return' or 'exception' event being traced."
        with patch.object(self.source_handler, "_build_line_to_next_line_map", side_effect=RuntimeError(exception_msg)):
            # Verify the exception is propagated
            with self.assertRaises(RuntimeError) as cm:
                self.source_handler.get_source_code_for_statement(mock_frame)

            # Verify exception message
            self.assertEqual(str(cm.exception), exception_msg)

    def test_get_source_code_for_statement_multiline(self):
        """Tests extraction of multi-line statements spanning multiple lines with specific end column.

        This test verifies that:
        1. The function correctly handles a valid line entry from a frame
        2. Properly resolves the source file path
        3. Reads the source file lines
        4. Uses the line map to determine statement boundaries
        5. Combines multiple lines into a single statement string
        6. Handles the end column correctly when trimming the last line
        """
        # Create mock frame and line entry
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_frame.GetLineEntry.return_value = mock_line_entry
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = "/test/path/source.c"
        mock_line_entry.GetLine.return_value = 66

        # Create mock compile unit
        mock_compile_unit = MagicMock()
        mock_frame.GetCompileUnit.return_value = mock_compile_unit

        # Setup return values for handler methods
        with (
            patch.object(
                self.source_handler, "resolve_source_path", return_value="/resolved/path/source.c"
            ) as mock_resolve,
            patch.object(
                self.source_handler,
                "get_file_lines",
                return_value=[
                    "",  # Line 0 (unused)
                    *[""] * 64,  # Lines 1-65
                    '    printf("Loop iteration: %d\\n", i);',  # Line 66
                    "  }",  # Line 67
                    "",  # Line 68
                ],
            ) as mock_get_lines,
            patch.object(
                self.source_handler, "_build_line_to_next_line_map", return_value={66: (67, 3)}
            ) as mock_build_map,
        ):
            # Call the method under test
            result = self.source_handler.get_source_code_for_statement(mock_frame)

            # Verify result
            self.assertEqual(result, 'printf("Loop iteration: %d\\n", i); }')

            # Verify method calls
            mock_resolve.assert_called_once_with("/test/path/source.c")
            mock_get_lines.assert_called_once_with("/resolved/path/source.c")
            mock_build_map.assert_called_once_with(mock_compile_unit)

    def test_get_source_code_for_statement_single_line_behavior(self):
        """
        Tests that get_source_code_for_statement returns only the current line
        when the next statement starts on the same line.
        """
        # Create mock frame and line entry
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec().fullpath = "/test/file.c"
        mock_line_entry.GetLine.return_value = 5
        mock_compile_unit = MagicMock()
        mock_frame.GetLineEntry.return_value = mock_line_entry
        mock_frame.GetCompileUnit.return_value = mock_compile_unit

        # Mock file content
        file_lines = ["line1", "line2", "line3", "line4", "  line5: single statement  ", "line6"]

        # Mock line map indicating same-line statement
        line_map = {5: (5, 10)}

        with (
            patch.object(self.source_handler, "resolve_source_path", return_value="/test/file.c") as mock_resolve,
            patch.object(self.source_handler, "get_file_lines", return_value=file_lines) as mock_get_lines,
            patch.object(self.source_handler, "_build_line_to_next_line_map", return_value=line_map) as mock_build_map,
        ):
            result = self.source_handler.get_source_code_for_statement(mock_frame)

        # Verify expected result
        expected = "line5: single statement"
        self.assertEqual(result, expected)

    def test_get_source_code_for_statement_as_in_trace(self):
        """
        Tests the exact scenario from the runtime trace where the function
        returns 'asm volatile("nop"); loop_100(); /' for specific input.
        """
        # Create mock frame and line entry
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec().fullpath = "/basic_main.c"
        mock_line_entry.GetLine.return_value = 196
        mock_compile_unit = MagicMock()
        mock_frame.GetLineEntry.return_value = mock_line_entry
        mock_frame.GetCompileUnit.return_value = mock_compile_unit

        # Mock file content matching trace scenario
        file_lines = [""] * 195  # Unused lines 1-195
        file_lines.append('    asm volatile("nop");')  # Line 196
        file_lines.append("    loop_100();")  # Line 197
        file_lines.append(" / ...")  # Line 198

        # Mock line map matching trace data
        line_map = {196: (198, 3)}

        with (
            patch.object(self.source_handler, "resolve_source_path", return_value="/basic_main.c") as mock_resolve,
            patch.object(self.source_handler, "get_file_lines", return_value=file_lines) as mock_get_lines,
            patch.object(self.source_handler, "_build_line_to_next_line_map", return_value=line_map) as mock_build_map,
        ):
            result = self.source_handler.get_source_code_for_statement(mock_frame)

        # Verify expected result from trace
        expected = 'asm volatile("nop"); loop_100(); /'
        self.assertEqual(result, expected)

    def test_get_source_code_for_single_line_statement(self):
        """
        Tests that a single-line statement is correctly extracted and returned
        as a stripped string when the current statement spans only one line.
        """
        # Test data
        original_path = "/mock/original/path/file.c"
        resolved_path = "/mock/resolved/path/file.c"
        start_line = 64
        expected_result = "// 循环100次，打印当前循环次数"

        # Create mock frame with valid line entry
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = original_path
        mock_line_entry.GetLine.return_value = start_line
        mock_frame.GetLineEntry.return_value = mock_line_entry
        mock_compile_unit = MagicMock()
        mock_frame.GetCompileUnit.return_value = mock_compile_unit

        # Prepare mock file content
        mock_lines = [""] * (start_line - 1)  # Empty lines before target
        mock_lines.append(f"    {expected_result}    ")  # Target line with padding

        # Patch instance methods with mocks
        with (
            patch.object(self.source_handler, "resolve_source_path", return_value=resolved_path) as mock_resolve,
            patch.object(self.source_handler, "get_file_lines", return_value=mock_lines) as mock_get_lines,
            patch.object(
                self.source_handler, "_build_line_to_next_line_map", return_value={start_line: (start_line, 3)}
            ) as mock_build_map,
        ):
            # Execute the method under test
            result = self.source_handler.get_source_code_for_statement(mock_frame)

            # Assert the result matches expected stripped content
            self.assertEqual(result, expected_result)

            # Verify critical interactions
            mock_resolve.assert_called_once_with(original_path)
            mock_get_lines.assert_called_once_with(resolved_path)
            mock_build_map.assert_called_once_with(mock_compile_unit)

    def test_returns_error_when_source_file_not_found(self):
        """
        Tests that the function returns an error string when the source file
        cannot be resolved. This scenario occurs when resolve_source_path()
        returns None, indicating the source file doesn't exist.
        """
        # Create mock frame and line entry objects
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()

        # Configure mock objects
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = "/path/to/source.c"
        mock_line_entry.GetLine.return_value = 42
        mock_frame.GetLineEntry.return_value = mock_line_entry

        # Patch resolve_source_path to return None (file not found)
        with patch.object(self.source_handler, "resolve_source_path", return_value=None):
            result = self.source_handler.get_source_code_for_statement(mock_frame)

        # Verify the expected error string is returned
        expected_error = "<source file '/path/to/source.c' not found>"
        self.assertEqual(result, expected_error)

    def test_returns_statement_source_when_file_found(self):
        """
        Tests that the function returns the correct source code statement
        when the source file is found and line information is available.
        This covers the normal execution path where all dependencies succeed.
        """
        # Create mock frame and line entry objects
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_compile_unit = MagicMock()

        # Configure mock objects
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = "/path/to/source.c"
        mock_line_entry.GetLine.return_value = 4  # Line number in file_lines
        mock_frame.GetLineEntry.return_value = mock_line_entry
        mock_frame.GetCompileUnit.return_value = mock_compile_unit

        # Configure mocks for successful path
        with (
            patch.object(self.source_handler, "resolve_source_path", return_value="/resolved/source.c"),
            patch.object(
                self.source_handler,
                "get_file_lines",
                return_value=[
                    "",  # Line 0 (unused)
                    "Line 1",  # Line 1
                    "Line 2",  # Line 2
                    "  if (condition) {",  # Line 3 (adjusted to line 4 for test data)
                    "    do_something();",  # Line 4 (adjusted to line 5 for test data)
                    "  }",  # Line 5 (adjusted to line 6 for test data)
                    "}",  # Line 6 (adjusted to line 7 for test data)
                ],
            ),
            patch.object(
                self.source_handler,
                "_build_line_to_next_line_map",
                return_value={
                    4: (6, 3)  # 修改为 (6, 3) 以正确捕获第6行的完整内容
                },
            ),
        ):
            result = self.source_handler.get_source_code_for_statement(mock_frame)

        # Verify the concatenated source lines
        expected_source = "if (condition) { do_something(); }"
        self.assertEqual(result, expected_source)

    def test_returns_empty_string_when_line_entry_invalid(self):
        """
        Tests that the function returns an empty string when the line entry
        from the frame is invalid. This handles cases where debug information
        is missing or incomplete.
        """
        # Create mock frame with invalid line entry
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = False
        mock_frame.GetLineEntry.return_value = mock_line_entry

        result = self.source_handler.get_source_code_for_statement(mock_frame)
        self.assertEqual(result, "")

    def test_handles_missing_lines_gracefully(self):
        """
        Tests that the function handles cases where the source file exists
        but the requested line number is out of bounds.
        """
        # Create mock frame and line entry
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        # 创建并配置编译单元mock
        mock_compile_unit = MagicMock()
        mock_compile_unit.GetNumLineEntries.return_value = 0  # 显式返回整数0

        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = "/path/to/source.c"
        mock_line_entry.GetLine.return_value = 999  # Non-existent line
        mock_frame.GetLineEntry.return_value = mock_line_entry
        mock_frame.GetCompileUnit.return_value = mock_compile_unit  # 设置编译单元

        # Configure dependencies
        with (
            patch.object(self.source_handler, "resolve_source_path", return_value="/real/source.c"),
            patch.object(self.source_handler, "get_file_lines", return_value=["line1", "line2"]),
        ):
            result = self.source_handler.get_source_code_for_statement(mock_frame)

        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
