"""
Comprehensive unit tests for tree_libs/web_handlers.py

This test suite covers all the API handlers and helper functions in the web_handlers module,
including symbol completion, symbol content retrieval, LSP integration, and search functionality.
The tests are structured to reflect the refactored, modular architecture of the handlers.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch

from fastapi.responses import JSONResponse, PlainTextResponse

from lsp.client import GenericLSPClient
from tree import ParserUtil
from tree_libs.app import FileSearchResult, FileSearchResults, MatchResult, WebServiceState
from tree_libs.web_handlers import (
    LSPCallResolver,
    _enrich_symbols_with_content,
    _lookup_symbol_by_line,
    _lookup_symbol_by_name,
    _parse_symbol_request,
    _retrieve_core_symbols,
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
        self.assertEqual(clamp(5, 1, 10), 5)

    def test_clamp_below_range(self):
        self.assertEqual(clamp(-5, 1, 10), 1)

    def test_clamp_above_range(self):
        self.assertEqual(clamp(15, 1, 10), 10)


class TestSymbolCompletion(unittest.IsolatedAsyncioTestCase):
    """Test symbol completion handlers."""

    def setUp(self):
        self.mock_config = Mock()
        self.mock_config.relative_path.return_value = "test/path.py"

        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = self.mock_config
        self.mock_state.symbol_trie = Mock()

    async def test_handle_symbol_completion_valid_prefix(self):
        """Test symbol completion with valid prefix returns expected results."""
        mock_results = [{"name": "test_symbol", "details": {}}]
        self.mock_state.symbol_trie.search_prefix.return_value = mock_results

        result = await handle_symbol_completion("test", 10, self.mock_state)

        self.assertEqual(result, {"completions": mock_results})
        self.mock_state.symbol_trie.search_prefix.assert_called_once_with("test", max_results=10, use_bfs=True)


# --- Tests for the /symbol_content Pipeline ---


class TestSymbolContentPipeline(unittest.IsolatedAsyncioTestCase):
    """High-level integration tests for the handle_get_symbol_content pipeline."""

    def setUp(self):
        self.mock_state = Mock(spec=WebServiceState)

    @patch("tree_libs.web_handlers._parse_symbol_request")
    @patch("tree_libs.web_handlers._retrieve_core_symbols", new_callable=AsyncMock)
    @patch("tree_libs.web_handlers.LSPCallResolver")
    @patch("tree_libs.web_handlers._enrich_symbols_with_content")
    async def test_full_pipeline_success_json(self, mock_enrich, mock_lsp_resolver_class, mock_retrieve, mock_parse):
        """Test a successful run through the pipeline with LSP enabled and JSON output."""
        # --- Arrange ---
        # Stage 1: Parsing
        mock_parse.return_value = ("test.py", ["my_func"])

        # Stage 2: Core Retrieval
        core_symbol = {"name": "my_func", "file_path": "test.py", "location": {"block_range": (0, 20)}}
        mock_retrieve.return_value = [core_symbol]

        # Stage 3: LSP Enhancement
        lsp_symbol = {"name": "called_func", "file_path": "lib.py", "location": {"block_range": (50, 80)}}
        mock_lsp_resolver_instance = mock_lsp_resolver_class.return_value
        mock_lsp_resolver_instance.resolve_calls_for_symbols = AsyncMock(return_value=[lsp_symbol])

        # Stage 4: Enrichment
        enriched_symbols = [
            {"name": "my_func", "content": "def my_func(): ..."},
            {"name": "called_func", "content": "def called_func(): ..."},
        ]
        mock_enrich.return_value = enriched_symbols

        # --- Act ---
        result = await handle_get_symbol_content(
            "test.py/my_func", json_format=True, lsp_enabled=True, state=self.mock_state
        )

        # --- Assert ---
        mock_parse.assert_called_once_with("test.py/my_func")
        mock_retrieve.assert_called_once_with("test.py", ["my_func"], self.mock_state)
        mock_lsp_resolver_class.assert_called_once_with(self.mock_state)
        mock_lsp_resolver_instance.resolve_calls_for_symbols.assert_called_once_with([core_symbol])
        self.assertEqual(mock_enrich.call_args[0][0][0], core_symbol)
        self.assertEqual(mock_enrich.call_args[0][0][1], lsp_symbol)

        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(json.loads(result.body), enriched_symbols)

    @patch("tree_libs.web_handlers._parse_symbol_request", return_value=PlainTextResponse("Bad path", status_code=400))
    async def test_pipeline_fails_at_parsing(self, _mock_parse):
        """Test that the pipeline exits early if parsing fails."""
        result = await handle_get_symbol_content("bad/path", False, False, self.mock_state)
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.body, b"Bad path")

    @patch("tree_libs.web_handlers._parse_symbol_request", return_value=("test.py", ["func"]))
    @patch("tree_libs.web_handlers._retrieve_core_symbols", new_callable=AsyncMock, return_value=[])
    async def test_pipeline_no_symbols_found(self, _mock_retrieve, _mock_parse):
        """Test the 404 case when no core symbols are found."""
        result = await handle_get_symbol_content("test.py/nonexistent", False, False, self.mock_state)
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 404)
        self.assertIn(b"No symbols found", result.body)


class TestSymbolContentHelpers(unittest.TestCase):
    """Unit tests for the helper functions in the /symbol_content pipeline."""

    def test_parse_symbol_request_valid(self):
        """Test parsing of a valid symbol path."""
        result = _parse_symbol_request("path/to/file.py/func1,func2")
        self.assertEqual(result, ("path/to/file.py", ["func1", "func2"]))

    def test_parse_symbol_request_invalid(self):
        """Test that invalid paths return a PlainTextResponse."""
        result = _parse_symbol_request("no_slash_at_all")
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 400)

    @patch("builtins.open", new_callable=mock_open, read_data=b"def func():\n    pass")
    def test_enrich_symbols_with_content(self, mock_file):
        """Test that content is correctly added to symbol dicts."""
        symbols = [
            {"name": "func", "file_path": "test.py", "location": {"block_range": (0, 20)}},
            {"name": "other", "file_path": "test.py", "location": [(), (), (0, 20)]},
        ]
        enriched = _enrich_symbols_with_content(symbols)
        self.assertEqual(len(enriched), 2)
        self.assertEqual(enriched[0]["content"], "def func():\n    pass")
        self.assertEqual(enriched[1]["content"], "def func():\n    pass")
        mock_file.assert_called_once_with("test.py", "rb")


class TestCoreSymbolLookupHelpers(unittest.TestCase):
    """Tests for synchronous symbol lookup helpers."""

    def setUp(self):
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.config = Mock()

    def test_lookup_symbol_by_name_success(self):
        """Test successful lookup by name."""
        mock_result = {"file_path": "test.py", "location": ((0, 0), (1, 0), (0, 20)), "calls": []}
        self.mock_state.file_symbol_trie.search_exact.return_value = mock_result
        result = _lookup_symbol_by_name("test.py", "my_func", self.mock_state)
        self.assertEqual(result["name"], "test.py/my_func")
        self.mock_state.file_symbol_trie.search_exact.assert_called_once_with("symbol:test.py/my_func")

    def test_lookup_symbol_by_name_not_found(self):
        """Test 404 response when a symbol name is not found."""
        self.mock_state.file_symbol_trie.search_exact.return_value = None
        result = _lookup_symbol_by_name("test.py", "nonexistent", self.mock_state)
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 404)

    def test_lookup_symbol_by_line_success(self):
        """Test successful lookup by line number."""
        mock_parser = Mock(spec=ParserUtil)
        mock_parser.symbol_at_line.return_value = {"location": ((9, 0), (10, 0), (100, 200)), "calls": []}
        self.mock_state.config.relative_path.return_value = "test.py"

        result = _lookup_symbol_by_line("test.py", "at_10", 10, self.mock_state, mock_parser)

        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "test.py/at_10")
        mock_parser.symbol_at_line.assert_called_once_with(9)  # line - 1


class TestRetrieveCoreSymbols(unittest.IsolatedAsyncioTestCase):
    """Tests for the async _retrieve_core_symbols orchestrator function."""

    def setUp(self):
        self.mock_state = Mock(spec=WebServiceState)

    @patch("tree_libs.web_handlers._lookup_symbol_by_name")
    @patch("tree_libs.web_handlers._lookup_symbol_by_line")
    @patch("tree_libs.web_handlers._get_cached_file_data", new_callable=AsyncMock)
    async def test_retrieve_core_symbols_success(self, mock_get_cached, mock_lookup_line, mock_lookup_name):
        """Test successful retrieval of mixed symbol types."""
        mock_parser = Mock(spec=ParserUtil)
        mock_get_cached.return_value = (mock_parser, {"some": "codemap"})
        mock_lookup_name.return_value = {"name": "test.py/my_func"}
        mock_lookup_line.return_value = {"name": "test.py/at_10"}

        result = await _retrieve_core_symbols("test.py", ["my_func", "at_10"], self.mock_state)

        mock_get_cached.assert_called_once_with("test.py", self.mock_state)
        mock_lookup_name.assert_called_once_with("test.py", "my_func", self.mock_state)
        mock_lookup_line.assert_called_once_with("test.py", "at_10", 10, self.mock_state, mock_parser)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "test.py/my_func")
        self.assertEqual(result[1]["name"], "test.py/at_10")

    @patch("tree_libs.web_handlers._get_cached_file_data", new_callable=AsyncMock)
    async def test_retrieve_core_symbols_parser_fails(self, mock_get_cached):
        """Test that a 500 response is returned if file parsing fails."""
        mock_get_cached.return_value = (None, None)
        result = await _retrieve_core_symbols("test.py", ["my_func"], self.mock_state)
        self.assertIsInstance(result, PlainTextResponse)
        self.assertEqual(result.status_code, 500)
        self.assertIn(b"Could not parse file", result.body)


class TestLSPCallResolver(unittest.IsolatedAsyncioTestCase):
    """Focused tests for the LSPCallResolver class."""

    def setUp(self):
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = Mock()
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}
        self.mock_lsp_client = MagicMock(spec=GenericLSPClient)
        self.mock_lsp_client.open_documents = set()
        self.mock_state.get_lsp_client.return_value = self.mock_lsp_client
        self.resolver = LSPCallResolver(self.mock_state)

    @patch("builtins.open", new_callable=mock_open, read_data=b"def my_func():\n    other_func()")
    @patch("os.path.abspath", return_value="/abs/path/to/test.py")
    async def test_initialize_lsp_server(self, _mock_abspath, _mock_file):
        """Test that 'didOpen' is sent correctly."""
        symbol = {"file_path": "test.py"}
        await self.resolver._initialize_lsp_server(symbol, self.mock_lsp_client)

        self.mock_lsp_client.send_notification.assert_called_once()
        args, _ = self.mock_lsp_client.send_notification.call_args
        self.assertEqual(args[0], "textDocument/didOpen")
        self.assertEqual(args[1]["textDocument"]["uri"], "file:///abs/path/to/test.py")

    @patch.object(LSPCallResolver, "_process_definition", new_callable=AsyncMock)
    async def test_process_call_success(self, mock_process_def):
        """Test successful processing of a single call."""
        self.mock_lsp_client.get_definition = AsyncMock(return_value=[{"uri": "file:///abs/lib.py", "range": {}}])
        mock_process_def.return_value = [{"name": "resolved_symbol"}]

        call = {"name": "other_func", "start_point": (1, 4)}
        results = await self.resolver._process_call(call, "test.py", self.mock_lsp_client)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "resolved_symbol")
        self.mock_lsp_client.get_definition.assert_called_once()
        mock_process_def.assert_called_once()

    @patch("tree_libs.web_handlers._get_cached_file_data", new_callable=AsyncMock)
    @patch.object(LSPCallResolver, "_collect_symbols_from_trie")
    @patch.object(LSPCallResolver, "_extract_symbol_name_from_definition")
    @patch("os.path.exists", return_value=True)
    async def test_process_definition_success(
        self, _mock_exists, mock_extract_name, mock_collect, mock_get_cached_data
    ):
        """Test successful processing of a definition from LSP."""
        self.resolver._get_file_lines = Mock(return_value=["def other_func(): pass"])
        mock_extract_name.return_value = "other_func"
        mock_collect.return_value = [{"name": "other_func"}]
        self.mock_state.config.relative_path.return_value = "lib.py"
        rel_def_path = "lib.py"

        def_item = {"uri": "file:///abs/lib.py", "range": {}}
        results = await self.resolver._process_definition(def_item, "call_name")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "other_func")
        mock_get_cached_data.assert_called_once_with(rel_def_path, self.resolver.state)
        mock_extract_name.assert_called_once()
        mock_collect.assert_called_once_with("lib.py", "other_func", "call_name")


# --- Tests for Other Handlers ---


class TestLSPDidChangeHandler(unittest.IsolatedAsyncioTestCase):
    """Test LSP didChange handler."""

    def setUp(self):
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_lsp_client = Mock()
        self.mock_lsp_client.running = True
        self.mock_state.get_lsp_client.return_value = self.mock_lsp_client

    async def test_handle_lsp_did_change_success(self):
        """Test successful LSP didChange handling."""
        result = await handle_lsp_did_change("test.py", "new content", self.mock_state)
        self.assertEqual(result, {"status": "success"})
        self.mock_lsp_client.did_change.assert_called_once_with("test.py", "new content")


class TestSearchToSymbolsHandler(unittest.IsolatedAsyncioTestCase):
    """Test the search-to-symbols handler."""

    def setUp(self):
        self.mock_config = Mock()
        self.mock_config.relative_to_current_path.return_value = "test/path.py"
        self.mock_config.relative_path.return_value = "test/path.py"
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = self.mock_config
        self.mock_state.symbol_cache = {}

    @patch("tree_libs.web_handlers._get_cached_file_data", new_callable=AsyncMock)
    async def test_handle_search_to_symbols_success(self, mock_get_cached_data):
        """Test successful search-to-symbols handling."""
        mock_parser_util = Mock(spec=ParserUtil)
        mock_parser_util.find_symbols_for_locations.return_value = {"symbol1": {}}
        mock_code_map = {"some_code": "map"}
        mock_get_cached_data.return_value = (mock_parser_util, mock_code_map)

        search_results = FileSearchResults(
            results=[
                FileSearchResult(file_path="test.py", matches=[MatchResult(line=1, column_range=(1, 5), text="sym")])
            ]
        )
        result = await handle_search_to_symbols(search_results, 16384, self.mock_state)

        self.assertIsInstance(result, JSONResponse)
        mock_get_cached_data.assert_called_once_with("test.py", self.mock_state)
        mock_parser_util.find_symbols_for_locations.assert_called_once()


class TestRealtimeCompletionHandler(unittest.IsolatedAsyncioTestCase):
    """Test the realtime completion handler."""

    def setUp(self):
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.file_symbol_trie = Mock()
        self.mock_state.file_parser_info_cache = {}

    @patch("tree_libs.web_handlers._get_cached_file_data", new_callable=AsyncMock)
    @patch("tree_libs.web_handlers.perform_trie_search")
    @patch("tree_libs.web_handlers.unquote")
    async def test_handle_symbol_completion_realtime_success(self, mock_unquote, mock_perform_search, mock_get_cached):
        """Test successful realtime completion."""
        mock_unquote.return_value = "symbol:test.py/func"
        mock_perform_search.return_value = [{"name": "test.py/func1"}, {"name": "test.py/func2"}]

        result = await handle_symbol_completion_realtime("symbol:test.py/func", 10, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        body = result.body.decode()
        self.assertIn("symbol:test.py/func1", body)
        self.assertIn("symbol:test.py/func2", body)
        mock_get_cached.assert_called_once_with("test.py", self.mock_state)


class TestSimpleCompletionHandler(unittest.IsolatedAsyncioTestCase):
    """Test the simple completion handler."""

    def setUp(self):
        self.mock_config = Mock()
        self.mock_config.relative_path.return_value = "test/path.py"
        self.mock_state = Mock(spec=WebServiceState)
        self.mock_state.config = self.mock_config
        self.mock_state.symbol_trie = Mock()

    async def test_handle_symbol_completion_simple_success(self):
        """Test successful simple completion."""
        mock_results = [
            {"name": "test_symbol", "details": {"file_path": "/abs/path/test.py"}},
            {"name": "symbol:another", "details": {"file_path": "/abs/path/other.py"}},
        ]
        self.mock_state.symbol_trie.search_prefix.return_value = mock_results

        result = await handle_symbol_completion_simple("test", 10, self.mock_state)

        self.assertIsInstance(result, PlainTextResponse)
        body = result.body.decode()
        self.assertIn("symbol:test/path.py/test_symbol", body)
        self.assertIn("symbol:another", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
