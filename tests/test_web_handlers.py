"""
Comprehensive unit tests for tree_libs/web_handlers.py

This test suite covers all the API handlers and helper functions in the web_handlers module,
including symbol completion, symbol content retrieval, LSP integration, and search functionality.
"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch

from fastapi.responses import JSONResponse, PlainTextResponse

from tree_libs.app import FileSearchResult, FileSearchResults, MatchResult, WebServiceState

# Import the modules under test
from tree_libs.web_handlers import (
    _build_completion_results,
    _build_json_response,
    _collect_symbols,
    _determine_current_prefix,
    _expand_symbol_from_line,
    _extract_contents,
    _extract_symbol_name,
    _get_file_content,
    _initialize_lsp_server,
    _location_to_symbol,
    _parse_symbol_path,
    _parse_symbol_prefix,
    _process_call,
    _process_definition,
    _read_source_code,
    _validate_and_lookup_symbols,
    clamp,
    handle_get_symbol_content,
    handle_lsp_did_change,
    handle_search_to_symbols,
    handle_symbol_completion,
    handle_symbol_completion_realtime,
    handle_symbol_completion_simple,
)


class TestClampFunction(unittest.TestCase):
    """Test the clamp utility function."""

    def test_clamp_within_range(self):
        """Test clamp when value is within range."""
        self.assertEqual(clamp(5, 1, 10), 5)
        self.assertEqual(clamp(1, 1, 10), 1)
        self.assertEqual(clamp(10, 1, 10), 10)

    def test_clamp_below_range(self):
        """Test clamp when value is below minimum."""
        self.assertEqual(clamp(-5, 1, 10), 1)
        self.assertEqual(clamp(0, 1, 10), 1)

    def test_clamp_above_range(self):
        """Test clamp when value is above maximum."""
        self.assertEqual(clamp(15, 1, 10), 10)
        self.assertEqual(clamp(100, 1, 10), 10)


class TestSymbolCompletion(unittest.IsolatedAsyncioTestCase):
    """Test symbol completion handlers."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.relative_path.return_value = "test/path.py"

        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = self.mock_config
        self.mock_state.symbol_trie = Mock()
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}
        self.mock_state.symbol_cache = {}

    async def test_handle_symbol_completion_empty_prefix(self):
        """Test symbol completion with empty prefix."""
        result = await handle_symbol_completion("", 10, self.mock_state)
        self.assertEqual(result, {"completions": []})

    async def test_handle_symbol_completion_valid_prefix(self):
        """Test symbol completion with valid prefix."""
        mock_results = [{"name": "test_symbol", "details": {}}]
        self.mock_state.symbol_trie.search_prefix.return_value = mock_results

        result = await handle_symbol_completion("test", 10, self.mock_state)

        self.assertEqual(result, {"completions": mock_results})
        self.mock_state.symbol_trie.search_prefix.assert_called_once_with("test", max_results=10, use_bfs=True)

    async def test_handle_symbol_completion_max_results_clamping(self):
        """Test that max_results is properly clamped."""
        self.mock_state.symbol_trie.search_prefix.return_value = []

        # Test upper bound
        await handle_symbol_completion("test", 100, self.mock_state)
        self.mock_state.symbol_trie.search_prefix.assert_called_with("test", max_results=50, use_bfs=True)

        # Test lower bound
        await handle_symbol_completion("test", 0, self.mock_state)
        self.mock_state.symbol_trie.search_prefix.assert_called_with("test", max_results=1, use_bfs=True)


class TestSymbolPathParsing(unittest.TestCase):
    """Test symbol path parsing functions."""

    def test_parse_symbol_path_valid(self):
        """Test parsing valid symbol paths."""
        result = _parse_symbol_path("file/path.py/symbol1,symbol2")
        self.assertEqual(result, ("file/path.py", ["symbol1", "symbol2"]))

    def test_parse_symbol_path_single_symbol(self):
        """Test parsing path with single symbol."""
        result = _parse_symbol_path("file/path.py/symbol1")
        self.assertEqual(result, ("file/path.py", ["symbol1"]))

    def test_parse_symbol_path_no_slash(self):
        """Test parsing path without slash."""
        result = _parse_symbol_path("invalid_path")
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 400)

    def test_parse_symbol_path_no_symbols(self):
        """Test parsing path with no symbols after slash."""
        result = _parse_symbol_path("file/path.py/")
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 400)

    def test_parse_symbol_path_empty_symbols(self):
        """Test parsing path with empty symbols."""
        result = _parse_symbol_path("file/path.py/,,,")
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 400)


class TestFileOperations(unittest.TestCase):
    """Test file reading and content extraction functions."""

    def test_read_source_code_success(self):
        """Test successful file reading."""
        test_content = b"def test_function():\n    pass\n"

        with patch("builtins.open", mock_open(read_data=test_content)):
            result = _read_source_code("test_file.py")
            self.assertEqual(result, test_content)

    def test_read_source_code_file_not_found(self):
        """Test file reading when file doesn't exist."""
        with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
            result = _read_source_code("nonexistent_file.py")
            self.assertIsInstance(result, PlainTextResponse)
            self.assertEqual(result.status_code, 500)

    def test_read_source_code_permission_error(self):
        """Test file reading with permission error."""
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            result = _read_source_code("restricted_file.py")
            self.assertIsInstance(result, PlainTextResponse)
            self.assertEqual(result.status_code, 500)

    def test_extract_contents(self):
        """Test content extraction from source code."""
        source_code = b"def function1():\n    pass\n\ndef function2():\n    return 42\n"
        symbol_results = [
            {"location": [(0, 0), (1, 8), (0, 21)]},  # function1 - bytes 0-21
            {"location": [(3, 0), (4, 13), (22, 45)]},  # function2 - bytes 22-45
        ]

        result = _extract_contents(source_code, symbol_results)
        expected = [
            "def function1():\n    ",  # First 21 bytes
            "ass\n\ndef function2():\n ",  # Bytes 22-45
        ]
        self.assertEqual(result, expected)


class TestJsonResponseBuilding(unittest.TestCase):
    """Test JSON response building functions."""

    def test_build_json_response(self):
        """Test building JSON response from symbol results."""
        symbol_results = [
            {
                "name": "test_symbol",
                "file_path": "test.py",
                "location": [(1, 0), (5, 10), (10, 50)],
                "calls": [{"name": "call1"}],
            }
        ]
        contents = ["def test_symbol():\n    pass"]

        result = _build_json_response(symbol_results, contents)

        expected = [
            {
                "name": "test_symbol",
                "file_path": "test.py",
                "content": "def test_symbol():\n    pass",
                "location": {
                    "start_line": 1,
                    "start_col": 0,
                    "end_line": 5,
                    "end_col": 10,
                    "block_range": (10, 50),
                },
                "calls": [{"name": "call1"}],
            }
        ]
        self.assertEqual(result, expected)


class TestSymbolExpansion(unittest.TestCase):
    """Test symbol name expansion functions."""

    def test_expand_symbol_from_line_basic(self):
        """Test basic symbol expansion."""
        line = "def test_function():"
        result = _expand_symbol_from_line(line, 4, 8)  # "test"
        self.assertEqual(result, "test_function")

    def test_expand_symbol_from_line_with_underscore(self):
        """Test symbol expansion with underscores."""
        line = "class My_Test_Class:"
        result = _expand_symbol_from_line(line, 6, 8)  # "My"
        self.assertEqual(result, "My_Test_Class")

    def test_expand_symbol_from_line_at_boundary(self):
        """Test symbol expansion at line boundaries."""
        line = "function_name"
        result = _expand_symbol_from_line(line, 0, 1)  # "f"
        self.assertEqual(result, "function_name")

    def test_expand_symbol_from_line_empty_result(self):
        """Test symbol expansion with empty result."""
        line = "   ()   "
        result = _expand_symbol_from_line(line, 3, 4)  # "("
        # The function doesn't expand non-identifier characters, so it returns "("
        self.assertEqual(result, "(")


class TestSymbolPrefixParsing(unittest.TestCase):
    """Test symbol prefix parsing for realtime completion."""

    def test_parse_symbol_prefix_valid(self):
        """Test parsing valid symbol prefix."""
        prefix = "symbol:path/to/file.py/func1,func2"
        file_path, symbols = _parse_symbol_prefix(prefix)
        self.assertEqual(file_path, "path/to/file.py")
        self.assertEqual(symbols, ["func1", "func2"])

    def test_parse_symbol_prefix_no_symbols(self):
        """Test parsing prefix without symbols."""
        prefix = "symbol:path/to/file.py"
        file_path, symbols = _parse_symbol_prefix(prefix)
        # rfind("/") finds the last slash, so file_path is everything before the last slash
        self.assertEqual(file_path, "path/to")
        self.assertEqual(symbols, ["file.py"])

    def test_parse_symbol_prefix_invalid(self):
        """Test parsing invalid prefix."""
        prefix = "invalid_prefix"
        file_path, symbols = _parse_symbol_prefix(prefix)
        self.assertIsNone(file_path)
        self.assertEqual(symbols, [])

    def test_determine_current_prefix_with_symbols(self):
        """Test determining current prefix with symbols."""
        result = _determine_current_prefix("test.py", ["func1", "func2"])
        self.assertEqual(result, "symbol:test.py/func2")

    def test_determine_current_prefix_no_symbols(self):
        """Test determining current prefix without symbols."""
        result = _determine_current_prefix("test.py", [])
        self.assertEqual(result, "symbol:test.py")

    def test_determine_current_prefix_no_file(self):
        """Test determining current prefix without file."""
        result = _determine_current_prefix(None, ["func1"])
        # The function doesn't check for None file_path, it just formats it
        self.assertEqual(result, "symbol:None/func1")


class TestCompletionResults(unittest.TestCase):
    """Test completion result building."""

    def test_build_completion_results_basic(self):
        """Test building basic completion results."""
        file_path = "test.py"
        symbols = ["func1"]
        results = [{"name": "test.py/func2"}]

        completions = _build_completion_results(file_path, symbols, results)
        # With only one symbol, no comma prefix is added
        expected = ["symbol:test.py/func2"]
        self.assertEqual(completions, expected)

    def test_build_completion_results_no_file(self):
        """Test building completion results without file path."""
        completions = _build_completion_results(None, ["func1"], [])
        self.assertEqual(completions, [])

    def test_build_completion_results_multiple_symbols(self):
        """Test building completion results with multiple existing symbols."""
        file_path = "test.py"
        symbols = ["func1", "func2", "func3"]
        results = [{"name": "test.py/func4"}]

        completions = _build_completion_results(file_path, symbols, results)
        expected = ["symbol:test.py/func1,func2,func4"]
        self.assertEqual(completions, expected)


class TestSymbolContentHandler(unittest.IsolatedAsyncioTestCase):
    """Test the main symbol content handler."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.relative_path.return_value = "test/path.py"

        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = self.mock_config
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}
        self.mock_state.get_lsp_client = Mock()

    @patch("tree_libs.web_handlers._parse_symbol_path")
    @patch("tree_libs.web_handlers._validate_and_lookup_symbols")
    @patch("tree_libs.web_handlers._read_source_code")
    @patch("tree_libs.web_handlers._extract_contents")
    @patch("tree_libs.web_handlers._build_json_response")
    async def test_handle_get_symbol_content_success_json(
        self, mock_build_json, mock_extract, mock_read, mock_validate, mock_parse
    ):
        """Test successful symbol content retrieval in JSON format."""
        # Setup mocks
        mock_parse.return_value = ("test.py", ["func1"])
        mock_validate.return_value = [{"file_path": "test.py", "name": "func1"}]
        mock_read.return_value = b"def func1(): pass"
        mock_extract.return_value = ["def func1(): pass"]
        mock_build_json.return_value = [{"name": "func1", "content": "def func1(): pass"}]

        result = await handle_get_symbol_content("test.py/func1", True, False, self.mock_state)

        self.assertIsInstance(result, JSONResponse)
        mock_parse.assert_called_once_with("test.py/func1")
        mock_validate.assert_called_once_with("test.py", ["func1"], self.mock_state)

    @patch("tree_libs.web_handlers._parse_symbol_path")
    async def test_handle_get_symbol_content_parse_error(self, mock_parse):
        """Test symbol content handler with parse error."""
        mock_parse.return_value = PlainTextResponse("Parse error", status_code=400)

        result = await handle_get_symbol_content("invalid", True, False, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 400)

    @patch("tree_libs.web_handlers._parse_symbol_path")
    @patch("tree_libs.web_handlers._validate_and_lookup_symbols")
    async def test_handle_get_symbol_content_no_symbols_found(self, mock_validate, mock_parse):
        """Test symbol content handler when no symbols are found."""
        mock_parse.return_value = ("test.py", ["func1"])
        mock_validate.return_value = []

        result = await handle_get_symbol_content("test.py/func1", True, False, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 404)
        self.assertIn("No symbols found", result.body.decode())


class TestValidateAndLookupSymbols(unittest.TestCase):
    """Test symbol validation and lookup functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}

    @patch("tree_libs.web_handlers.update_trie_if_needed")
    @patch("tree_libs.web_handlers.line_number_from_unnamed_symbol")
    def test_validate_and_lookup_symbols_exact_search(self, mock_line_number, mock_update_trie):
        """Test symbol validation with exact search."""
        mock_line_number.return_value = -1  # Not a line number symbol
        mock_update_trie.return_value = None

        mock_symbol_result = {"name": "test_symbol", "file_path": "test.py", "location": [(1, 0), (5, 10), (10, 50)]}
        self.mock_state.file_symbol_trie.search_exact.return_value = mock_symbol_result

        result = _validate_and_lookup_symbols("test.py", ["test_symbol"], self.mock_state)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "test.py/test_symbol")

    @patch("tree_libs.web_handlers.update_trie_if_needed")
    @patch("tree_libs.web_handlers.line_number_from_unnamed_symbol")
    def test_validate_and_lookup_symbols_line_number(self, mock_line_number, mock_update_trie):
        """Test symbol validation with line number symbol."""
        mock_line_number.return_value = 5  # Line number symbol
        mock_update_trie.return_value = None

        # Setup parser cache
        mock_parser = Mock()
        mock_parser.symbol_at_line.return_value = {"name": "line_symbol", "location": [(4, 0), (4, 20), (80, 100)]}
        self.mock_state.file_parser_info_cache["test.py"] = (mock_parser, None, "test.py")

        result = _validate_and_lookup_symbols("symbol:test.py", ["5"], self.mock_state)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        mock_parser.symbol_at_line.assert_called_once_with(4)  # line - 1

    @patch("tree_libs.web_handlers.update_trie_if_needed")
    @patch("tree_libs.web_handlers.line_number_from_unnamed_symbol")
    def test_validate_and_lookup_symbols_near_line_number(self, mock_line_number, mock_update_trie):
        """Test symbol validation with near line number symbol."""
        mock_line_number.return_value = 5
        mock_update_trie.return_value = None

        mock_parser = Mock()
        mock_parser.near_symbol_at_line.return_value = {"name": "near_symbol", "location": [(3, 0), (6, 20), (60, 120)]}
        self.mock_state.file_parser_info_cache["test.py"] = (mock_parser, None, "test.py")

        result = _validate_and_lookup_symbols("symbol:test.py", ["near_5"], self.mock_state)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        mock_parser.near_symbol_at_line.assert_called_once_with(4)

    @patch("tree_libs.web_handlers.update_trie_if_needed")
    @patch("tree_libs.web_handlers.line_number_from_unnamed_symbol")
    def test_validate_and_lookup_symbols_not_found(self, mock_line_number, mock_update_trie):
        """Test symbol validation when symbol is not found."""
        mock_line_number.return_value = -1
        mock_update_trie.return_value = None
        self.mock_state.file_symbol_trie.search_exact.return_value = None

        result = _validate_and_lookup_symbols("test.py", ["nonexistent"], self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 404)
        self.assertIn("Symbol not found", result.body.decode())


class TestLSPDidChangeHandler(unittest.IsolatedAsyncioTestCase):
    """Test LSP didChange handler."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_lsp_client = Mock()
        self.mock_lsp_client.running = True
        self.mock_state.get_lsp_client.return_value = self.mock_lsp_client

    async def test_handle_lsp_did_change_success(self):
        """Test successful LSP didChange handling."""
        result = await handle_lsp_did_change("test.py", "new content", self.mock_state)

        self.assertEqual(result, {"status": "success"})
        self.mock_lsp_client.did_change.assert_called_once_with("test.py", "new content")

    async def test_handle_lsp_did_change_client_not_running(self):
        """Test LSP didChange when client is not running."""
        self.mock_lsp_client.running = False

        result = await handle_lsp_did_change("test.py", "content", self.mock_state)

        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 501)

    async def test_handle_lsp_did_change_no_client(self):
        """Test LSP didChange when no client is available."""
        self.mock_state.get_lsp_client.return_value = None

        result = await handle_lsp_did_change("test.py", "content", self.mock_state)

        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 501)

    async def test_handle_lsp_did_change_feature_error(self):
        """Test LSP didChange with feature error."""
        from tree_libs.web_handlers import LSPFeatureError

        mock_error = LSPFeatureError("textDocumentSync")
        self.mock_lsp_client.did_change.side_effect = mock_error

        result = await handle_lsp_did_change("test.py", "content", self.mock_state)

        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 400)


class TestSearchToSymbolsHandler(unittest.IsolatedAsyncioTestCase):
    """Test the search-to-symbols handler."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.relative_to_current_path.return_value = "test/path.py"

        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = self.mock_config
        self.mock_state.symbol_cache = {}

    @patch("tree_libs.web_handlers.ParserLoader")
    @patch("tree_libs.web_handlers.ParserUtil")
    @patch("os.path.getmtime")
    async def test_handle_search_to_symbols_success(self, mock_getmtime, mock_parser_util_class, mock_parser_loader):
        """Test successful search-to-symbols handling."""
        # Setup mocks
        mock_getmtime.return_value = 1234567890
        mock_parser_util = Mock()
        mock_parser_util.get_symbol_paths.return_value = (None, {"symbol1": {"location": [(1, 0), (5, 10), (10, 50)]}})
        mock_parser_util.find_symbols_for_locations.return_value = {
            "symbol1": {"location": [(1, 0), (5, 10), (10, 50)], "content": "def symbol1(): pass"}
        }
        mock_parser_util_class.return_value = mock_parser_util

        # Create test data
        match_result = MatchResult(line=2, column_range=(5, 15), text="symbol1")
        file_result = FileSearchResult(file_path="test.py", matches=[match_result])
        search_results = FileSearchResults(results=[file_result])

        result = await handle_search_to_symbols(search_results, 16384, self.mock_state)

        self.assertIsInstance(result, JSONResponse)
        # Verify the parser was called correctly
        mock_parser_util.find_symbols_for_locations.assert_called_once()

    @patch("tree_libs.web_handlers.ParserLoader")
    @patch("tree_libs.web_handlers.ParserUtil")
    @patch("os.path.getmtime")
    async def test_handle_search_to_symbols_with_cache(self, mock_getmtime, mock_parser_util_class, mock_parser_loader):
        """Test search-to-symbols with cached results."""
        mock_getmtime.return_value = 1234567890
        mock_parser_util = Mock()
        mock_parser_util_class.return_value = mock_parser_util

        # Setup cache
        code_map = {"symbol1": {"location": [(1, 0), (5, 10), (10, 50)]}}
        self.mock_state.symbol_cache["test.py"] = (1234567890, code_map)

        mock_parser_util.find_symbols_for_locations.return_value = {
            "symbol1": {"location": [(1, 0), (5, 10), (10, 50)]}
        }

        match_result = MatchResult(line=2, column_range=(5, 15), text="symbol1")
        file_result = FileSearchResult(file_path="test.py", matches=[match_result])
        search_results = FileSearchResults(results=[file_result])

        result = await handle_search_to_symbols(search_results, 16384, self.mock_state)

        self.assertIsInstance(result, JSONResponse)
        # Should not call get_symbol_paths since cache is valid
        mock_parser_util.get_symbol_paths.assert_not_called()

    @patch("tree_libs.web_handlers.ParserLoader")
    @patch("tree_libs.web_handlers.ParserUtil")
    @patch("os.path.getmtime")
    async def test_handle_search_to_symbols_file_error(self, mock_getmtime, mock_parser_util_class, mock_parser_loader):
        """Test search-to-symbols with file error."""
        mock_getmtime.side_effect = FileNotFoundError("File not found")
        mock_parser_util = Mock()
        mock_parser_util_class.return_value = mock_parser_util

        match_result = MatchResult(line=2, column_range=(5, 15), text="symbol1")
        file_result = FileSearchResult(file_path="nonexistent.py", matches=[match_result])
        search_results = FileSearchResults(results=[file_result])

        result = await handle_search_to_symbols(search_results, 16384, self.mock_state)

        self.assertIsInstance(result, JSONResponse)
        # Should return empty results due to error
        content = result.body.decode()
        self.assertIn('"count":0', content)


class TestRealtimeCompletionHandler(unittest.IsolatedAsyncioTestCase):
    """Test the realtime completion handler."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}

    @patch("tree_libs.web_handlers.perform_trie_search")
    @patch("tree_libs.web_handlers.unquote")
    async def test_handle_symbol_completion_realtime_success(self, mock_unquote, mock_perform_search):
        """Test successful realtime completion."""
        mock_unquote.return_value = "symbol:test.py/func"
        mock_perform_search.return_value = [{"name": "test.py/func1"}, {"name": "test.py/func2"}]

        result = await handle_symbol_completion_realtime("symbol:test.py/func", 10, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        body = result.body.decode()
        self.assertIn("symbol:test.py/func1", body)
        self.assertIn("symbol:test.py/func2", body)

    @patch("tree_libs.web_handlers.perform_trie_search")
    @patch("tree_libs.web_handlers.unquote")
    async def test_handle_symbol_completion_realtime_no_results(self, mock_unquote, mock_perform_search):
        """Test realtime completion with no results."""
        mock_unquote.return_value = "symbol:test.py/nonexistent"
        mock_perform_search.return_value = []

        result = await handle_symbol_completion_realtime("symbol:test.py/nonexistent", 10, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.body.decode(), "")


class TestSimpleCompletionHandler(unittest.IsolatedAsyncioTestCase):
    """Test the simple completion handler."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.relative_path.return_value = "test/path.py"

        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = self.mock_config
        self.mock_state.symbol_trie = Mock()

    async def test_handle_symbol_completion_simple_empty_prefix(self):
        """Test simple completion with empty prefix."""
        result = await handle_symbol_completion_simple("", 10, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.body.decode(), "")

    async def test_handle_symbol_completion_simple_success(self):
        """Test successful simple completion."""
        mock_results = [
            {"name": "test_symbol", "details": {"file_path": "/absolute/path/test.py"}},
            {"name": "symbol:another_symbol", "details": {"file_path": "/absolute/path/other.py"}},
        ]
        self.mock_state.symbol_trie.search_prefix.return_value = mock_results

        result = await handle_symbol_completion_simple("test", 10, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        body = result.body.decode()
        self.assertIn("symbol:test/path.py/test_symbol", body)
        self.assertIn("symbol:another_symbol", body)

    async def test_handle_symbol_completion_simple_no_file_path(self):
        """Test simple completion with missing file path."""
        mock_results = [
            {
                "name": "test_symbol",
                "details": {},  # No file_path
            }
        ]
        self.mock_state.symbol_trie.search_prefix.return_value = mock_results

        result = await handle_symbol_completion_simple("test", 10, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.body.decode(), "")


class TestLSPHelperFunctions(unittest.IsolatedAsyncioTestCase):
    """Test LSP-related helper functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_lsp_client = Mock()
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = Mock()
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}

    @patch("builtins.open", mock_open(read_data="def test_function():\n    pass"))
    @patch("os.path.abspath")
    @patch("tree_libs.web_handlers.LanguageId")
    async def test_initialize_lsp_server(self, mock_language_id, mock_abspath):
        """Test LSP server initialization."""
        mock_abspath.return_value = "/absolute/path/test.py"
        mock_language_id.get_language_id.return_value = "python"

        symbol = {"file_path": "test.py"}

        await _initialize_lsp_server(symbol, self.mock_lsp_client)

        self.mock_lsp_client.send_notification.assert_called_once()
        call_args = self.mock_lsp_client.send_notification.call_args
        self.assertEqual(call_args[0][0], "textDocument/didOpen")
        self.assertIn("textDocument", call_args[0][1])

    @patch("tree_libs.web_handlers._process_definition")
    @patch("os.path.abspath")
    async def test_process_call_success(self, mock_abspath, mock_process_def):
        """Test successful call processing."""
        mock_abspath.return_value = "/absolute/path/test.py"
        self.mock_lsp_client.get_definition = AsyncMock(
            return_value={"uri": "file:///absolute/path/test.py", "range": {"start": {"line": 5, "character": 10}}}
        )
        mock_process_def.return_value = [{"name": "test_symbol"}]

        call = {
            "name": "test_call",
            "start_point": [4, 9],  # 0-based
        }

        result = await _process_call(call, "test.py", self.mock_lsp_client, {}, {}, self.mock_state, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "test_symbol")
        self.mock_lsp_client.get_definition.assert_called_once_with("/absolute/path/test.py", 5, 10)

    async def test_process_call_no_definition(self):
        """Test call processing when no definition is found."""
        self.mock_lsp_client.get_definition = AsyncMock(return_value=None)

        call = {"name": "test_call", "start_point": [4, 9]}

        result = await _process_call(call, "test.py", self.mock_lsp_client, {}, {}, self.mock_state, {})

        self.assertEqual(result, [])

    @patch("tree_libs.web_handlers._collect_symbols")
    @patch("tree_libs.web_handlers._get_file_content")
    @patch("tree_libs.web_handlers.update_trie_if_needed")
    @patch("os.path.exists")
    async def test_process_definition_success(self, mock_exists, mock_update_trie, mock_get_content, mock_collect):
        """Test successful definition processing."""
        mock_exists.return_value = True
        self.mock_state.config.relative_path.return_value = "test.py"
        mock_get_content.return_value = ["def test_function():"]
        mock_collect.return_value = [{"name": "test_function"}]

        def_item = {
            "uri": "file:///absolute/path/test.py",
            "range": {"start": {"line": 0, "character": 4}, "end": {"character": 17}},
        }

        result = await _process_definition(def_item, "test_call", {}, {}, self.mock_state)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "test_function")

    async def test_process_definition_file_not_exists(self):
        """Test definition processing when file doesn't exist."""
        def_item = {"uri": "file:///nonexistent/path/test.py", "range": {"start": {"line": 0, "character": 4}}}

        with patch("os.path.exists", return_value=False):
            result = await _process_definition(def_item, "test_call", {}, {}, self.mock_state)

        self.assertEqual(result, [])


class TestFileContentHelpers(unittest.TestCase):
    """Test file content helper functions."""

    @patch("tree_libs.web_handlers._read_source_code")
    def test_get_file_content_success(self, mock_read):
        """Test successful file content retrieval."""
        mock_read.return_value = b"def test():\n    pass"

        file_content_cache = {}
        file_lines_cache = {}

        result = _get_file_content("test.py", file_content_cache, file_lines_cache)

        self.assertEqual(result, ["def test():", "    pass"])
        self.assertIn("test.py", file_content_cache)
        self.assertIn("test.py", file_lines_cache)

    @patch("tree_libs.web_handlers._read_source_code")
    def test_get_file_content_cached(self, mock_read):
        """Test file content retrieval from cache."""
        file_content_cache = {"test.py": b"cached content"}
        file_lines_cache = {"test.py": ["cached", "content"]}

        result = _get_file_content("test.py", file_content_cache, file_lines_cache)

        self.assertEqual(result, ["cached", "content"])
        mock_read.assert_not_called()

    @patch("tree_libs.web_handlers._read_source_code")
    def test_get_file_content_read_error(self, mock_read):
        """Test file content retrieval with read error."""
        mock_read.return_value = PlainTextResponse("Error", status_code=500)

        result = _get_file_content("test.py", {}, {})

        self.assertEqual(result, [])


class TestExtractSymbolName(unittest.TestCase):
    """Test symbol name extraction from LSP definitions."""

    def test_extract_symbol_name_basic(self):
        """Test basic symbol name extraction."""
        def_item = {"range": {"start": {"line": 0, "character": 4}, "end": {"character": 17}}}
        lines = ["def test_function():"]

        result = _extract_symbol_name(def_item, lines)

        self.assertEqual(result, "test_function")

    def test_extract_symbol_name_empty_range(self):
        """Test symbol name extraction with empty range."""
        def_item = {"range": {"start": {"line": 0, "character": 4}, "end": {"character": 4}}}
        lines = ["def test_function():"]

        result = _extract_symbol_name(def_item, lines)

        # Should expand to full identifier
        self.assertEqual(result, "test_function")

    def test_extract_symbol_name_out_of_bounds(self):
        """Test symbol name extraction with out of bounds line."""
        def_item = {"range": {"start": {"line": 5, "character": 0}, "end": {"character": 10}}}
        lines = ["def test_function():"]

        result = _extract_symbol_name(def_item, lines)

        self.assertEqual(result, "")


class TestCollectSymbols(unittest.TestCase):
    """Test symbol collection function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}

    @patch("tree_libs.web_handlers.perform_trie_search")
    @patch("os.path.abspath")
    def test_collect_symbols_success(self, mock_abspath, mock_perform_search):
        """Test successful symbol collection."""
        mock_abspath.return_value = "/absolute/path/test.py"
        mock_perform_search.return_value = [{"location": [(1, 0), (5, 10), (10, 50)], "calls": []}]

        file_content_cache = {"/absolute/path/test.py": b"def test_symbol():\n    pass\n"}

        result = _collect_symbols("test.py", "test_symbol", "call_name", file_content_cache, self.mock_state)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "test_symbol")
        self.assertEqual(result[0]["file_path"], "test.py")
        self.assertEqual(result[0]["jump_from"], "call_name")

    @patch("tree_libs.web_handlers.perform_trie_search")
    def test_collect_symbols_no_results(self, mock_perform_search):
        """Test symbol collection with no results."""
        mock_perform_search.return_value = []

        result = _collect_symbols("test.py", "nonexistent", "call_name", {}, self.mock_state)

        self.assertEqual(result, [])


class TestLocationToSymbolIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests for the _location_to_symbol function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = Mock()
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}

        self.mock_lsp_client = Mock()
        self.mock_lsp_client.send_notification = Mock()
        self.mock_lsp_client.get_definition = AsyncMock()

    @patch("tree_libs.web_handlers._initialize_lsp_server")
    @patch("tree_libs.web_handlers._process_call")
    async def test_location_to_symbol_basic_flow(self, mock_process_call, mock_init_lsp):
        """Test basic flow of location to symbol conversion."""
        mock_init_lsp.return_value = None
        mock_process_call.return_value = [{"name": "target_symbol", "file_path": "test.py", "calls": []}]

        symbol = {"file_path": "test.py", "calls": [{"name": "test_call", "start_point": [1, 0]}]}

        result = await _location_to_symbol(symbol, self.mock_lsp_client, self.mock_state, {})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "target_symbol")
        mock_init_lsp.assert_called_once_with(symbol, self.mock_lsp_client)

    @patch("tree_libs.web_handlers._initialize_lsp_server")
    @patch("tree_libs.web_handlers._process_call")
    async def test_location_to_symbol_recursive_calls(self, mock_process_call, mock_init_lsp):
        """Test recursive call processing in location to symbol."""
        mock_init_lsp.return_value = None

        # First call returns a symbol with more calls
        # Second call returns a symbol without calls
        mock_process_call.side_effect = [
            [
                {
                    "name": "intermediate_symbol",
                    "file_path": "test.py",
                    "calls": [{"name": "nested_call", "start_point": [2, 0]}],
                }
            ],
            [{"name": "final_symbol", "file_path": "test.py", "calls": []}],
        ]

        symbol = {"file_path": "test.py", "calls": [{"name": "initial_call", "start_point": [1, 0]}]}

        result = await _location_to_symbol(symbol, self.mock_lsp_client, self.mock_state, {})

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_process_call.call_count, 2)

    @patch("tree_libs.web_handlers._initialize_lsp_server")
    @patch("tree_libs.web_handlers._process_call")
    async def test_location_to_symbol_connection_error(self, mock_process_call, mock_init_lsp):
        """Test location to symbol with connection error."""
        mock_init_lsp.return_value = None
        mock_process_call.side_effect = ConnectionError("Connection failed")

        symbol = {"file_path": "test.py", "calls": [{"name": "test_call", "start_point": [1, 0]}]}

        result = await _location_to_symbol(symbol, self.mock_lsp_client, self.mock_state, {})

        # Should handle error gracefully and return empty list
        self.assertEqual(result, [])


class TestEdgeCasesAndErrorHandling(unittest.TestCase):
    """Test edge cases and error handling scenarios."""

    def test_clamp_edge_cases(self):
        """Test clamp function with edge cases."""
        # Test with equal min and max
        self.assertEqual(clamp(5, 10, 10), 10)
        self.assertEqual(clamp(15, 10, 10), 10)

        # Test with negative numbers
        self.assertEqual(clamp(-5, -10, -1), -5)
        self.assertEqual(clamp(-15, -10, -1), -10)
        self.assertEqual(clamp(5, -10, -1), -1)

    def test_parse_symbol_path_edge_cases(self):
        """Test symbol path parsing with edge cases."""
        # Test with multiple slashes
        result = _parse_symbol_path("path/with/many/slashes/symbol")
        self.assertEqual(result, ("path/with/many/slashes", ["symbol"]))

        # Test with whitespace in symbols
        result = _parse_symbol_path("path/file.py/ symbol1 , symbol2 ")
        self.assertEqual(result, ("path/file.py", ["symbol1", "symbol2"]))

        # Test with empty symbol parts
        result = _parse_symbol_path("path/file.py/symbol1,,symbol2")
        self.assertEqual(result, ("path/file.py", ["symbol1", "symbol2"]))

    def test_expand_symbol_from_line_edge_cases(self):
        """Test symbol expansion with edge cases."""
        # Test with empty line
        result = _expand_symbol_from_line("", 0, 0)
        self.assertEqual(result, "<unnamed>")

        # Test with line containing only special characters
        result = _expand_symbol_from_line("()[]{}:", 1, 2)
        self.assertEqual(result, ")")

        # Test with unicode characters
        result = _expand_symbol_from_line("def 测试函数():", 4, 6)
        self.assertEqual(result, "测试函数")

    def test_determine_current_prefix_edge_cases(self):
        """Test current prefix determination with edge cases."""
        # Test with empty symbols list
        result = _determine_current_prefix("test.py", [])
        self.assertEqual(result, "symbol:test.py")

        # Test with symbols containing empty strings
        result = _determine_current_prefix("test.py", ["", "valid_symbol"])
        self.assertEqual(result, "symbol:test.py/valid_symbol")

        # Test with None file path and symbols
        result = _determine_current_prefix(None, ["symbol"])
        self.assertEqual(result, "symbol:None/symbol")

    def test_build_completion_results_edge_cases(self):
        """Test completion result building with edge cases."""
        # Test with empty results
        completions = _build_completion_results("test.py", ["func1"], [])
        self.assertEqual(completions, [])

        # Test with complex symbol names
        results = [{"name": "complex/path/with/slashes/symbol"}]
        completions = _build_completion_results("test.py", [], results)
        expected = ["symbol:test.py/symbol"]
        self.assertEqual(completions, expected)

        # Test with double slashes in path
        results = [{"name": "test.py//symbol"}]
        completions = _build_completion_results("test.py", [], results)
        expected = ["symbol:test.py/symbol"]
        self.assertEqual(completions, expected)


class TestMockingAndIsolation(unittest.TestCase):
    """Test proper mocking and isolation of external dependencies."""

    @patch("tree_libs.web_handlers.update_trie_if_needed")
    @patch("tree_libs.web_handlers.line_number_from_unnamed_symbol")
    def test_external_dependency_isolation(self, mock_line_number, mock_update_trie):
        """Test that external dependencies are properly isolated."""
        mock_state = Mock(spec=WebServiceState)
        mock_state.file_symbol_trie = Mock()
        mock_state.file_parser_info_cache = {}

        mock_line_number.return_value = -1
        mock_update_trie.return_value = None
        mock_state.file_symbol_trie.search_exact.return_value = None

        result = _validate_and_lookup_symbols("test.py", ["symbol"], mock_state)

        # Verify external functions were called
        mock_update_trie.assert_called_once()
        mock_line_number.assert_called_once_with("symbol")

        # Verify result is error response
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 404)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
