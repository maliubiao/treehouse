import asyncio
import logging
import os
import time
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

from fastapi.responses import JSONResponse, PlainTextResponse

from lsp.client import GenericLSPClient, LSPFeatureError
from lsp.language_id import LanguageId
from tree import (
    ParserLoader,
    ParserUtil,
    perform_trie_search,
    update_trie_if_needed,
)
from tree_libs.ast import line_number_from_unnamed_symbol

from .app import FileSearchResults, WebServiceState

logger = logging.getLogger(__name__)


def clamp(value: int, min_val: int, max_val: int) -> int:
    """限制数值范围"""
    return max(min_val, min(max_val, value))


# --- Centralized Caching and Parsing Logic ---


def _update_trie_from_code_map(file_path: str, code_map: Dict[str, Any], state: WebServiceState, parser: ParserUtil):
    """Helper to update the file_symbol_trie with symbols from a given code_map."""
    rel_path = state.config.relative_path(file_path)
    for path, info in code_map.items():
        # The key in the trie should be fully qualified for global uniqueness.
        full_path = f"symbol:{rel_path}/{path}"
        # The symbol_info object itself should contain the relative path.
        symbol_info = parser.code_map_builder.build_symbol_info(info, rel_path)
        state.file_symbol_trie.insert(full_path, symbol_info)


async def _get_cached_file_data(
    file_path: str, state: WebServiceState
) -> Tuple[Optional[ParserUtil], Optional[Dict[str, Any]]]:
    """
    Retrieves parsed file data (ParserUtil instance and code_map) from cache,
    updating the cache if the file is new or has been modified.
    This is the single source of truth for file parsing.
    Returns (ParserUtil, code_map) or (None, None) if parsing fails.
    """
    clean_file_path = file_path.removeprefix("symbol:")
    try:
        current_mtime = os.path.getmtime(clean_file_path)
    except (FileNotFoundError, OSError):
        return None, None

    # Get the current asyncio event loop to run the synchronous lock in an executor.
    # This is necessary because state.lock is a standard threading.Lock, which is
    # not compatible with the `async with` statement that caused the TypeError.
    loop = asyncio.get_running_loop()

    # First, check cache with the lock
    await loop.run_in_executor(None, state.lock.acquire)
    try:
        if clean_file_path in state.file_parser_info_cache:
            cached_mtime, parser, code_map = state.file_parser_info_cache[clean_file_path]
            if cached_mtime == current_mtime:
                return parser, code_map
    finally:
        state.lock.release()

    # If not in cache or modified, parse the file (outside the lock to avoid blocking)
    parser_loader = ParserLoader()
    parser = ParserUtil(parser_loader)
    try:
        paths, code_map = parser.get_symbol_paths(clean_file_path)
    except (ValueError, FileNotFoundError) as e:
        logger.warning(f"Error parsing {clean_file_path}: {e}")
        # Cache failure to avoid re-parsing a broken file repeatedly
        await loop.run_in_executor(None, state.lock.acquire)
        try:
            state.file_parser_info_cache[clean_file_path] = (current_mtime, None, None)
        finally:
            state.lock.release()
        return None, None

    # After parsing, acquire lock to update cache and trie
    await loop.run_in_executor(None, state.lock.acquire)
    try:
        # Re-check in case another thread parsed and cached it while we were parsing
        if clean_file_path in state.file_parser_info_cache:
            cached_mtime, cached_parser, cached_code_map = state.file_parser_info_cache[clean_file_path]
            if cached_mtime >= current_mtime:
                return cached_parser, cached_code_map

        # Update cache and trie
        state.file_parser_info_cache[clean_file_path] = (current_mtime, parser, code_map)
        _update_trie_from_code_map(clean_file_path, code_map, state, parser)

        return parser, code_map
    finally:
        state.lock.release()


# --- Handler for /complete ---
async def handle_symbol_completion(prefix: str, max_results: int, state: WebServiceState) -> Dict[str, List[Any]]:
    if not prefix:
        return {"completions": []}

    trie = state.symbol_trie
    max_results = clamp(int(max_results), 1, 50)

    results = trie.search_prefix(prefix, max_results=max_results, use_bfs=True)
    return {"completions": results}


# --- LSP-based Call Resolution ---
class LSPCallResolver:
    """Encapsulates the logic for resolving symbol calls using an LSP client."""

    def __init__(self, state: WebServiceState):
        self.state: WebServiceState = state
        self.lookup_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.file_content_cache: Dict[str, bytes] = {}
        self.file_lines_cache: Dict[str, List[str]] = {}

    async def resolve_calls_for_symbols(self, symbols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        For a given list of symbols, resolves their internal calls to other symbols.
        """
        resolved_symbols: List[Dict[str, Any]] = []
        for symbol in symbols:
            try:
                lsp_client = self.state.get_lsp_client(symbol["file_path"])
                if lsp_client:
                    resolved_symbols.extend(await self._location_to_symbol(symbol, lsp_client))
            except (ConnectionError, TimeoutError, RuntimeError) as e:
                logger.error("LSP enhancement failed for symbol %s: %s", symbol.get("name"), e)

        return resolved_symbols

    async def _location_to_symbol(self, symbol: Dict[str, Any], lsp_client: GenericLSPClient) -> List[Dict[str, Any]]:
        """Converts call locations within a symbol to full symbol definitions."""
        await self._initialize_lsp_server(symbol, lsp_client)

        collected_symbols: List[Dict[str, Any]] = []
        # Use a queue for breadth-first traversal of calls
        call_queue: List[Tuple[int, Dict[str, Any]]] = [(1, call) for call in symbol.get("calls", [])]
        processed_symbols: Set[str] = set()

        while call_queue:
            level, call = call_queue.pop(0)
            if level > 3:  # Limit recursion depth
                continue

            try:
                symbols_from_call = await self._process_call(call, symbol["file_path"], lsp_client)
                for sym in symbols_from_call:
                    unique_symbol_id = f"{sym.get('file_path', '')}:{sym.get('name', '')}"
                    if unique_symbol_id in processed_symbols:
                        continue
                    processed_symbols.add(unique_symbol_id)

                    collected_symbols.append(sym)
                    # If the new symbol is in the same file, explore its calls as well
                    if sym.get("file_path") == symbol["file_path"]:
                        call_queue.extend([(level + 1, c) for c in sym.get("calls", [])])

            except (ConnectionError, TimeoutError, RuntimeError) as e:
                logger.error("Error processing call %s: %s", call.get("name"), e)

        return collected_symbols

    async def _initialize_lsp_server(self, symbol: Dict[str, Any], lsp_client: GenericLSPClient) -> None:
        """Sends a textDocument/didOpen notification to the LSP server."""
        file_path = symbol["file_path"]
        abs_file_path = os.path.abspath(file_path)
        uri = f"file://{abs_file_path}"

        # Avoid re-opening the same file
        if uri in lsp_client.open_documents:
            return

        content_bytes = self._read_source_code_bytes(file_path)
        if content_bytes is None:
            return

        lsp_client.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": LanguageId.get_language_id(file_path),
                    "version": 1,
                    "text": content_bytes.decode("utf-8", errors="ignore"),
                }
            },
        )

    async def _process_call(
        self, call: Dict[str, Any], file_path: str, lsp_client: GenericLSPClient
    ) -> List[Dict[str, Any]]:
        """Processes a single call location to find its definition."""
        line, char = call["start_point"][0] + 1, call["start_point"][1] + 1
        definitions = await lsp_client.get_definition(os.path.abspath(file_path), line, char)
        if not definitions:
            return []

        definitions = definitions if isinstance(definitions, list) else [definitions]
        collected_symbols: List[Dict[str, Any]] = []
        for def_item in definitions:
            uri = def_item.get("uri", "")
            def_path = unquote(urlparse(uri).path) if uri.startswith("file://") else ""
            if not def_path:
                continue

            cache_key = f"{def_path}:{def_item.get('range', {}).get('start', {}).get('line', 0)}"
            if cache_key in self.lookup_cache:
                collected_symbols.extend(self.lookup_cache[cache_key])
                continue

            symbols = await self._process_definition(def_item, call["name"])
            self.lookup_cache[cache_key] = symbols
            collected_symbols.extend(symbols)
        return collected_symbols

    async def _process_definition(self, def_item: Dict[str, Any], call_name: str) -> List[Dict[str, Any]]:
        """Processes a definition item returned by the LSP server."""
        uri = def_item.get("uri", "")
        def_path = unquote(urlparse(uri).path) if uri.startswith("file://") else ""
        if not def_path or not os.path.exists(def_path):
            return []

        rel_def_path = self.state.config.relative_path(def_path)
        # Ensure file is parsed and in cache
        await _get_cached_file_data(rel_def_path, self.state)

        lines = self._get_file_lines(def_path)
        if not lines:
            return []

        symbol_name = self._extract_symbol_name_from_definition(def_item, lines)
        if not symbol_name:
            return []

        return self._collect_symbols_from_trie(rel_def_path, symbol_name, call_name)

    def _get_file_lines(self, file_path: str) -> List[str]:
        """Gets file content as lines, using a cache."""
        if file_path not in self.file_lines_cache:
            content_bytes = self._read_source_code_bytes(file_path)
            if content_bytes is None:
                self.file_lines_cache[file_path] = []
                return []
            self.file_lines_cache[file_path] = content_bytes.decode("utf8", errors="ignore").splitlines()
        return self.file_lines_cache[file_path]

    def _read_source_code_bytes(self, file_path: str) -> Optional[bytes]:
        """Reads file content as bytes, using a cache."""
        if file_path not in self.file_content_cache:
            try:
                with open(file_path, "rb") as f:
                    self.file_content_cache[file_path] = f.read()
            except (FileNotFoundError, PermissionError, IsADirectoryError):
                self.file_content_cache[file_path] = b""
                return None
        return self.file_content_cache[file_path]

    @staticmethod
    def _expand_symbol_from_line(line: str, start: int, end: int) -> str:
        """Expands a slice to cover the whole identifier at that position."""
        while start > 0 and (line[start - 1].isidentifier() or line[start - 1] == "_"):
            start -= 1
        while end < len(line) and (line[end].isidentifier() or line[end] == "_"):
            end += 1
        return line[start:end].strip() or "<unnamed>"

    def _extract_symbol_name_from_definition(self, def_item: Dict[str, Any], lines: List[str]) -> str:
        """Extracts a symbol name from an LSP definition item."""
        start = def_item.get("range", {}).get("start", {})
        end = def_item.get("range", {}).get("end", {})
        start_line, start_char = start.get("line", 0), start.get("character", 0)
        end_char = end.get("character", start_char + 1)

        if start_line >= len(lines):
            return ""

        target_line = lines[start_line]
        symbol_name = target_line[start_char:end_char].strip()
        # If the range is a single point, expand it to the full identifier.
        if not symbol_name:
            return self._expand_symbol_from_line(target_line, start_char, end_char)
        return symbol_name

    def _collect_symbols_from_trie(self, rel_def_path: str, symbol_name: str, call_name: str) -> List[Dict[str, Any]]:
        """Searches the trie for a symbol and formats it for the response."""
        full_prefix = f"symbol:{rel_def_path}/{symbol_name}"
        symbols = perform_trie_search(
            trie=self.state.file_symbol_trie,
            prefix=full_prefix,
            max_results=5,
            file_path=rel_def_path,
            file_parser_info_cache=self.state.file_parser_info_cache,
            search_exact=True,
        )

        collected = []
        for s in symbols:
            if not s:
                continue
            start_point, end_point, block_range = s["location"]
            collected.append(
                {
                    "name": symbol_name,
                    "file_path": rel_def_path,
                    "location": {
                        "start_line": start_point[0],
                        "start_col": start_point[1],
                        "end_line": end_point[0],
                        "end_col": end_point[1],
                        "block_range": block_range,
                    },
                    "jump_from": call_name,
                    "calls": s.get("calls", []),
                }
            )
        return collected


# --- Main Handler for /symbol_content ---
async def handle_get_symbol_content(
    symbol_path: str, json_format: bool, lsp_enabled: bool, state: WebServiceState
) -> PlainTextResponse | JSONResponse:
    # Stage 1: Parse and Validate Request
    parse_result = _parse_symbol_request(symbol_path)
    if isinstance(parse_result, PlainTextResponse):
        return parse_result
    file_path_part, symbol_names = parse_result

    # Stage 2: Retrieve Core Symbols from Trie
    core_symbols = await _retrieve_core_symbols(file_path_part, symbol_names, state)
    if isinstance(core_symbols, PlainTextResponse):
        return core_symbols
    if not core_symbols:
        return PlainTextResponse(f"No symbols found for path: {symbol_path}", status_code=404)

    # Stage 3: LSP-based Enhancement
    lsp_symbols = []
    if lsp_enabled:
        resolver = LSPCallResolver(state)
        lsp_symbols = await resolver.resolve_calls_for_symbols(core_symbols)

    # Stage 4: Combine, Enrich, and Format Response
    all_symbols = _deduplicate_symbols(core_symbols + lsp_symbols)
    enriched_symbols = _enrich_symbols_with_content(all_symbols)

    if json_format:
        return JSONResponse(content=enriched_symbols)

    text_content = "\n\n".join(item.get("content", "") for item in enriched_symbols)
    return PlainTextResponse(text_content)


# --- Helpers for /symbol_content Pipeline ---


def _parse_symbol_request(symbol_path: str) -> Tuple[str, List[str]] | PlainTextResponse:
    """Parses the 'file/path/symbol1,symbol2' string."""
    if "/" not in symbol_path:
        return PlainTextResponse(
            "Symbol path format is incorrect. Should be file_path/symbol1,symbol2,...", status_code=400
        )
    last_slash_index = symbol_path.rfind("/")
    file_path_part = symbol_path[:last_slash_index]
    symbols_part = symbol_path[last_slash_index + 1 :]
    symbols = [s.strip() for s in symbols_part.split(",") if s.strip()]
    if not symbols:
        return PlainTextResponse("At least one symbol is required in the path.", status_code=400)
    return (file_path_part, symbols)


def _normalize_symbol_location_in_place(symbol: Dict[str, Any]) -> None:
    """
    Normalizes the 'location' field of a symbol to be a dictionary, modifying the symbol in place.
    Converts from tuple format `((start_line, start_col), (end_line, end_col), block_range)`
    to dict format `{'start_line': ..., 'end_line': ..., 'block_range': ...}`.
    """
    location = symbol.get("location")
    if isinstance(location, (list, tuple)) and len(location) == 3:
        start_point, end_point, block_range = location
        # Additional checks for robustness
        if (
            isinstance(start_point, (list, tuple))
            and len(start_point) == 2
            and isinstance(end_point, (list, tuple))
            and len(end_point) == 2
        ):
            symbol["location"] = {
                "start_line": start_point[0],
                "start_col": start_point[1],
                "end_line": end_point[0],
                "end_col": end_point[1],
                "block_range": block_range,
            }


async def _retrieve_core_symbols(
    file_path_part: str, symbols: List[str], state: WebServiceState
) -> List[Dict[str, Any]] | PlainTextResponse:
    """Retrieves the initial set of symbols from the trie based on the request."""
    # Ensure the file is parsed and its data is cached.
    parser_util, _ = await _get_cached_file_data(file_path_part, state)
    if not parser_util:
        return PlainTextResponse(f"Could not parse file: {file_path_part}", status_code=500)

    symbol_results: List[Dict[str, Any]] = []
    for symbol_name in symbols:
        line_number = line_number_from_unnamed_symbol(symbol_name)
        if line_number != -1:
            result = _lookup_symbol_by_line(file_path_part, symbol_name, line_number, state, parser_util)
        else:
            result = _lookup_symbol_by_name(file_path_part, symbol_name, state)

        if isinstance(result, PlainTextResponse):
            # Log or handle specific symbol lookup errors if needed, for now just continue
            logger.warning(f"Could not find symbol '{symbol_name}' in '{file_path_part}': {result.body.decode()}")
            continue
        if result:
            symbol_results.append(result)

    return symbol_results


def _lookup_symbol_by_line(
    file_path_part: str,
    symbol_name: str,
    line_number: int,
    state: WebServiceState,
    parser_instance: ParserUtil,
) -> Optional[Dict[str, Any]] | PlainTextResponse:
    """Finds a symbol based on a line number (e.g., 'at_123' or 'near_123')."""
    clean_file_path = file_path_part.removeprefix("symbol:")
    formatted_path = state.config.relative_path(clean_file_path)

    if symbol_name.startswith("near_"):
        result = parser_instance.near_symbol_at_line(line_number - 1)
    else:
        result = parser_instance.symbol_at_line(line_number - 1)

    if not result:
        return PlainTextResponse(f"Symbol not found at line {line_number} in {clean_file_path}", status_code=404)

    _normalize_symbol_location_in_place(result)

    result["file_path"] = formatted_path
    result["name"] = f"{formatted_path}/{symbol_name}"
    return result


def _lookup_symbol_by_name(
    file_path_part: str, symbol_name: str, state: WebServiceState
) -> Optional[Dict[str, Any]] | PlainTextResponse:
    """Finds a symbol by its fully qualified name in the trie."""
    # The trie is expected to be up-to-date via _get_cached_file_data.
    full_symbol_path = f"{file_path_part}/{symbol_name}"
    if not full_symbol_path.startswith("symbol:"):
        full_symbol_path = f"symbol:{full_symbol_path}"

    result = state.file_symbol_trie.search_exact(full_symbol_path)
    if not result:
        return PlainTextResponse(f"Symbol not found: {full_symbol_path}", status_code=404)

    # Make a copy to avoid modifying the cached data in the Trie
    result = result.copy()
    _normalize_symbol_location_in_place(result)

    result["name"] = full_symbol_path.removeprefix("symbol:")
    return result


def _deduplicate_symbols(symbols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicates a list of symbol dictionaries based on file_path and name."""
    seen: Set[Tuple[str, str]] = set()
    deduplicated_list: List[Dict[str, Any]] = []
    for symbol in symbols:
        # Use a location-based key for better uniqueness if available
        location = symbol.get("location")
        if location and isinstance(location, dict) and "block_range" in location:
            key = (symbol.get("file_path", ""), str(location["block_range"]))
        else:  # Fallback for symbols without full location info yet
            key = (symbol.get("file_path", ""), symbol.get("name", ""))

        if key not in seen:
            seen.add(key)
            deduplicated_list.append(symbol)
    return deduplicated_list


def _enrich_symbols_with_content(symbols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reads source files and adds 'content' to each symbol dictionary."""
    enriched_list = []
    file_cache: Dict[str, bytes] = {}

    for symbol in symbols:
        file_path = symbol.get("file_path")
        location = symbol.get("location")
        if not file_path or not location:
            continue

        if file_path not in file_cache:
            try:
                with open(file_path, "rb") as f:
                    file_cache[file_path] = f.read()
            except (IOError, OSError):
                file_cache[file_path] = b""

        source_code = file_cache.get(file_path)
        if not source_code:
            continue

        # Ensure location is a dict with block_range
        if isinstance(location, dict) and "block_range" in location:
            block_range = location["block_range"]
        # Handle tuple-based location for backward compatibility
        elif isinstance(location, (list, tuple)) and len(location) == 3:
            block_range = location[2]
        else:
            continue

        start_byte, end_byte = block_range
        symbol["content"] = source_code[start_byte:end_byte].decode("utf-8", errors="ignore")
        enriched_list.append(symbol)

    return enriched_list


# --- Handler for /lsp/didChange ---
async def handle_lsp_did_change(file_path: str, content: str, state: WebServiceState) -> JSONResponse | Dict:
    try:
        client = state.get_lsp_client(file_path)
        if not client or not client.running:
            return JSONResponse(status_code=501, content={"message": "LSP client not initialized"})
        client.did_change(file_path, content)
        logger.info("Processed didChange notification for %s", file_path)
        return {"status": "success"}
    except LSPFeatureError as e:
        logger.warning("Feature not supported: %s", e)
        return JSONResponse(status_code=400, content={"message": f"Feature not supported: {e.feature}"})
    except Exception as e:
        traceback.print_exc()
        logger.error("Failed to process didChange: %s", e)
        return JSONResponse(status_code=500, content={"message": "Internal server error"})


# --- Handler for /search-to-symbols ---
async def handle_search_to_symbols(
    results: FileSearchResults, max_context_size: int, state: WebServiceState
) -> JSONResponse:
    symbol_results: Dict[str, Any] = {}
    total_start_time = time.time()
    for file_result in results.results:
        parser_util, code_map = await _get_cached_file_data(file_result.file_path, state)

        if not parser_util or not code_map:
            logger.warning(f"Could not get parsed data for {file_result.file_path}, skipping.")
            continue

        try:
            locations = [(match.line - 1, match.column_range[0] - 1) for match in file_result.matches]
            symbols = parser_util.find_symbols_for_locations(code_map, locations, max_context_size=max_context_size)
            rel_path = state.config.relative_to_current_path(file_result.file_path)
            for key, value in symbols.items():
                value["name"] = f"{rel_path}/{key}"
                value["file_path"] = rel_path
            symbol_results.update(symbols)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(f"Error processing symbols for {file_result.file_path}: {e}")
            continue
    logger.info(f"Total processing time for search-to-symbols: {time.time() - total_start_time:.3f}s")
    return JSONResponse(content={"results": symbol_results, "count": len(symbol_results)})


# --- Handler for /complete_realtime ---
async def handle_symbol_completion_realtime(prefix: str, max_results: int, state: WebServiceState) -> PlainTextResponse:
    prefix = unquote(prefix)
    max_results = clamp(max_results, 1, 50)

    file_path, symbols = _parse_symbol_prefix(prefix)
    current_prefix = _determine_current_prefix(file_path, symbols)

    results = []
    if current_prefix:
        # Ensure the file is parsed and trie is up-to-date before searching
        if file_path:
            await _get_cached_file_data(file_path, state)

        results = perform_trie_search(
            trie=state.file_symbol_trie,
            prefix=current_prefix,
            max_results=max_results,
            file_path=file_path,
            file_parser_info_cache=state.file_parser_info_cache,
            use_bfs=True,
        )
    completions = _build_completion_results(file_path, symbols, results)
    return PlainTextResponse("\n".join(completions))


def _parse_symbol_prefix(prefix: str) -> tuple[str | None, list[str]]:
    if not prefix.startswith("symbol:"):
        return None, []
    remaining = prefix.removeprefix("symbol:")
    slash_idx = remaining.rfind("/")
    if slash_idx == -1:
        # This handles cases like "symbol:filename" where there are no further symbols
        file_path_only = remaining.split(",")[0]
        symbols = remaining.split(",")
        # A bit ambiguous, let's treat the whole thing as file_path if no slash
        # and first part as symbol if comma exists.
        # This part of logic is tricky based on original code.
        # Let's stick to slash-based separation.
        return remaining, []

    file_path = remaining[:slash_idx]
    symbols = list(remaining[slash_idx + 1 :].split(","))
    return file_path, symbols


def _determine_current_prefix(file_path: str | None, symbols: list[str]) -> str:
    if not file_path:
        return ""
    # If there's an empty string at the end of symbols list, it means user typed a comma
    # and is waiting for next suggestion. So we should search for the file prefix.
    if symbols and symbols[-1]:
        return f"symbol:{file_path}/{symbols[-1]}"
    return f"symbol:{file_path}/"


def _build_completion_results(file_path: str | None, symbols: list[str], results: list) -> list[str]:
    if not file_path:
        return []
    base_str = f"symbol:{file_path}/"
    # If the last symbol is empty, it means we are starting a new symbol completion
    symbol_prefix = ",".join(symbols[:-1]) if (symbols and symbols[-1]) else ",".join(symbols)
    if symbol_prefix:
        symbol_prefix += ","

    completions = []
    for result in results:
        # result["name"] is expected to be a full path like 'symbol:path/to/file.py/symbol'
        symbol_name = result["name"].split("/")[-1]
        full_path = f"{base_str}{symbol_prefix}{symbol_name}"
        completions.append(full_path.replace("//", "/"))
    return completions


# --- Handler for /complete_simple ---
async def handle_symbol_completion_simple(prefix: str, max_results: int, state: WebServiceState) -> PlainTextResponse:
    if not prefix:
        return PlainTextResponse("")

    max_results = clamp(int(max_results), 1, 50)
    results = state.symbol_trie.search_prefix(prefix, max_results=max_results, use_bfs=True)

    output = []
    for item in results:
        details = item.get("details", {})
        file_path = details.get("file_path")
        if not file_path:
            continue
        file_base = state.config.relative_path(file_path)
        symbol_name = item["name"]
        if symbol_name.startswith("symbol:"):
            output.append(symbol_name)
        else:
            output.append(f"symbol:{file_base}/{symbol_name}")

    return PlainTextResponse("\n".join(output))
