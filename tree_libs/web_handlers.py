import asyncio
import logging
import os
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from lsp.client import GenericLSPClient, LSPFeatureError
from lsp.language_id import LanguageId
from tree import (
    ParserLoader,
    ParserUtil,
    SymbolTrie,
    perform_trie_search,
    update_trie_if_needed,
)
from tree_libs.ast import line_number_from_unnamed_symbol

from .app import FileSearchResults, WebServiceState

# from .app import FileSearchResults, WebServiceState

logger = logging.getLogger(__name__)


def clamp(value: int, min_val: int, max_val: int) -> int:
    """限制数值范围"""
    return max(min_val, min(max_val, value))


# --- Handler for /complete ---
async def handle_symbol_completion(prefix: str, max_results: int, state: WebServiceState) -> Dict[str, List[Any]]:
    if not prefix:
        return {"completions": []}

    trie = state.symbol_trie
    max_results = clamp(int(max_results), 1, 50)

    results = trie.search_prefix(prefix, max_results=max_results, use_bfs=True)
    # Note: Database fallback logic is removed as the DB logic is not present in the provided tree.py
    # If db integration is needed, it should be added here.

    return {"completions": results}


# --- Handler for /symbol_content ---
async def handle_get_symbol_content(
    symbol_path: str, json_format: bool, lsp_enabled: bool, state: WebServiceState
) -> PlainTextResponse | JSONResponse:
    # 1. Parse Path
    parse_result = _parse_symbol_path(symbol_path)
    if isinstance(parse_result, PlainTextResponse):
        return parse_result
    file_path_part, symbols = parse_result

    # 2. Validate and Lookup Symbols
    lookup_result = _validate_and_lookup_symbols(file_path_part, symbols, state)
    if isinstance(lookup_result, PlainTextResponse):
        return lookup_result
    symbol_results = lookup_result

    if not symbol_results:
        return PlainTextResponse(f"No symbols found for path: {symbol_path}", status_code=404)

    # 3. Read Source Code
    source_code_result = _read_source_code(symbol_results[0]["file_path"])
    if isinstance(source_code_result, PlainTextResponse):
        return source_code_result
    source_code = source_code_result

    # 4. Extract Contents
    contents = _extract_contents(source_code, symbol_results)

    # 5. LSP Enhancement (if enabled)
    collected_symbols = []
    if lsp_enabled:
        lookup_cache: Dict[str, Any] = {}
        for symbol in symbol_results:
            try:
                lsp_client = state.get_lsp_client(symbol["file_path"])
                collected_symbols.extend(await _location_to_symbol(symbol, lsp_client, state, lookup_cache))
            except Exception as e:
                logger.error(f"LSP enhancement failed for symbol {symbol.get('name')}: {e}")

    # 6. Build Response
    response_data = collected_symbols + _build_json_response(symbol_results, contents)
    if json_format:
        return JSONResponse(content=response_data)
    else:
        return PlainTextResponse("\n\n".join(item["content"] for item in response_data))


# --- Helpers for /symbol_content ---
def _parse_symbol_path(symbol_path: str) -> tuple[str, list[str]] | PlainTextResponse:
    if "/" not in symbol_path:
        return PlainTextResponse(
            "Symbol path format is incorrect. Should be file_path/symbol1,symbol2,...", status_code=400
        )
    last_slash_index = symbol_path.rfind("/", 1)
    file_path_part = symbol_path[:last_slash_index]
    symbols_part = symbol_path[last_slash_index + 1 :]
    symbols = [s.strip() for s in symbols_part.split(",") if s.strip()]
    if not symbols:
        return PlainTextResponse("At least one symbol is required.", status_code=400)
    return (file_path_part, symbols)


def _validate_and_lookup_symbols(
    file_path_part: str, symbols: list[str], state: WebServiceState
) -> list[Dict[str, Any]] | PlainTextResponse:
    update_trie_if_needed(file_path_part, state.file_symbol_trie, state.file_parser_info_cache, just_path=True)
    symbol_results = []
    for symbol in symbols:
        full_symbol_path = f"{file_path_part}/{symbol}"
        line_number = line_number_from_unnamed_symbol(symbol)
        if line_number != -1:
            file_path_part = file_path_part.removeprefix("symbol:")
            if file_path_part not in state.file_parser_info_cache:
                return PlainTextResponse(f"Parser info not cached for file: {file_path_part}", status_code=404)
            parser_instance: ParserUtil = state.file_parser_info_cache[file_path_part][0]
            formatted_path = state.file_parser_info_cache[file_path_part][2]
            result = (
                parser_instance.near_symbol_at_line(line_number - 1)
                if symbol.startswith("near_")
                else parser_instance.symbol_at_line(line_number - 1)
            )
            if not result:
                return PlainTextResponse(f"Symbol not found: {symbol}", status_code=404)
            result["file_path"] = formatted_path
        else:
            result = state.file_symbol_trie.search_exact(full_symbol_path)
            if not result:
                return PlainTextResponse(f"Symbol not found: {symbol}", status_code=404)

        result["name"] = full_symbol_path.removeprefix("symbol:")
        symbol_results.append(result)
    return symbol_results


def _read_source_code(file_path: str) -> bytes | PlainTextResponse:
    try:
        with open(file_path, "rb") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
        return PlainTextResponse(f"Could not read file: {str(e)}", status_code=500)


def _extract_contents(source_code: bytes, symbol_results: list) -> list[str]:
    return [source_code[res["location"][2][0] : res["location"][2][1]].decode("utf8") for res in symbol_results]


def _build_json_response(symbol_results: list, contents: list) -> list:
    return [
        {
            "name": res["name"],
            "file_path": res["file_path"],
            "content": content,
            "location": {
                "start_line": res["location"][0][0],
                "start_col": res["location"][0][1],
                "end_line": res["location"][1][0],
                "end_col": res["location"][1][1],
                "block_range": res["location"][2],
            },
            "calls": res.get("calls", []),
        }
        for res, content in zip(symbol_results, contents)
    ]


# --- LSP-based symbol location logic (used by /symbol_content) ---
async def _location_to_symbol(
    symbol: Dict[str, Any], lsp_client: GenericLSPClient, state: WebServiceState, lookup_cache: Dict[str, Any]
) -> List[Dict[str, Any]]:
    collected_symbols: List[Dict] = []
    file_content_cache: Dict[str, bytes] = {}
    file_lines_cache: Dict[str, List[str]] = {}

    await _initialize_lsp_server(symbol, lsp_client)
    symbol_file_path = symbol["file_path"]
    calls = [(1, call) for call in symbol.get("calls", [])]
    symbols_filter: set[str] = set()
    for level, call in calls:
        if level > 3:
            break
        try:
            symbols = await _process_call(
                call, symbol_file_path, lsp_client, file_content_cache, file_lines_cache, state, lookup_cache
            )
            for sym in symbols:
                if sym["file_path"] == symbol_file_path:
                    if sym["name"] in symbols_filter:
                        continue
                    symbols_filter.add(sym["name"])
                    logger.info("Checking calls for same-file symbol %s.%s", sym["file_path"], sym["name"])
                    calls.extend([(level + 1, c) for c in sym.get("calls", [])])
            collected_symbols.extend(symbols)
        except (ConnectionError, TimeoutError, RuntimeError) as e:
            logger.error(f"Error processing call {call.get('name')}: {e}")

    return collected_symbols


async def _initialize_lsp_server(symbol: Dict[str, Any], lsp_client: GenericLSPClient) -> None:
    file_path = symbol["file_path"]
    with open(file_path, "r", encoding="utf-8") as f:
        file_content = f.read()
    abs_file_path = os.path.abspath(file_path)
    lsp_client.send_notification(
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": f"file://{abs_file_path}",
                "languageId": LanguageId.get_language_id(file_path),
                "version": 1,
                "text": file_content,
            }
        },
    )


async def _process_call(
    call: Dict,
    file_path: str,
    lsp_client: GenericLSPClient,
    file_content_cache: Dict,
    file_lines_cache: Dict,
    state: WebServiceState,
    lookup_cache: Dict,
) -> List[Dict]:
    call_name = call["name"]
    line, char = call["start_point"][0] + 1, call["start_point"][1] + 1
    definition = await lsp_client.get_definition(os.path.abspath(file_path), line, char)
    if not definition:
        return []

    definitions = definition if isinstance(definition, list) else [definition]
    collected_symbols: List[Dict] = []
    for def_item in definitions:
        uri = def_item.get("uri", "")
        def_path = unquote(urlparse(uri).path) if uri.startswith("file://") else ""
        if not def_path:
            continue
        cache_key = f"{def_path}:{def_item.get('range', {}).get('start', {}).get('line', 0)}"
        if cache_key in lookup_cache:
            continue
        symbols = await _process_definition(def_item, call_name, file_content_cache, file_lines_cache, state)
        lookup_cache[cache_key] = symbols
        collected_symbols.extend(symbols)
    return collected_symbols


async def _process_definition(
    def_item: Dict, call_name: str, file_content_cache: Dict, file_lines_cache: Dict, state: WebServiceState
) -> List[Dict]:
    uri = def_item.get("uri", "")
    def_path = unquote(urlparse(uri).path) if uri.startswith("file://") else ""
    if not def_path or not os.path.exists(def_path):
        return []
    rel_def_path = state.config.relative_path(def_path)
    update_trie_if_needed(
        f"symbol:{rel_def_path}", state.file_symbol_trie, state.file_parser_info_cache, just_path=True
    )
    lines = _get_file_content(def_path, file_content_cache, file_lines_cache)
    symbol_name = _extract_symbol_name(def_item, lines)
    if not symbol_name:
        return []
    return _collect_symbols(rel_def_path, symbol_name, call_name, file_content_cache, state)


def _get_file_content(file_path: str, file_content_cache: Dict, file_lines_cache: Dict) -> List[str]:
    if file_path not in file_content_cache:
        content = _read_source_code(file_path)
        if isinstance(content, bytes):
            file_content_cache[file_path] = content
            file_lines_cache[file_path] = content.decode("utf8").splitlines()
        else:  # Is a PlainTextResponse
            return []
    return file_lines_cache[file_path]


def _extract_symbol_name(def_item: Dict, lines: List[str]) -> str:
    start = def_item.get("range", {}).get("start", {})
    end = def_item.get("range", {}).get("end", {})
    start_line, start_char = start.get("line", 0), start.get("character", 0)
    end_char = end.get("character", start_char + 1)
    if start_line >= len(lines):
        return ""
    target_line = lines[start_line]
    symbol_name = target_line[start_char:end_char].strip()
    return symbol_name or _expand_symbol_from_line(target_line, start_char, end_char)


def _collect_symbols(
    rel_def_path: str, symbol_name: str, call_name: str, file_content_cache: Dict, state: WebServiceState
) -> List[Dict]:
    symbols = perform_trie_search(
        trie=state.file_symbol_trie,
        prefix=f"symbol:{rel_def_path}/{symbol_name}",
        max_results=5,
        file_path=rel_def_path,
        file_parser_info_cache=state.file_parser_info_cache,
        search_exact=True,
    )
    collected = []
    for s in symbols:
        if not s:
            continue
        start_point, end_point, block_range = s["location"]
        content = file_content_cache[os.path.abspath(rel_def_path)][block_range[0] : block_range[1]].decode("utf8")
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
                "content": content,
                "jump_from": call_name,
                "calls": s.get("calls", []),
            }
        )
    return collected


def _expand_symbol_from_line(line: str, start: int, end: int) -> str:
    while start > 0 and (line[start - 1].isidentifier() or line[start - 1] == "_"):
        start -= 1
    while end < len(line) and (line[end].isidentifier() or line[end] == "_"):
        end += 1
    return line[start:end].strip() or "<unnamed>"


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
    parser_loader = ParserLoader()
    parser_util = ParserUtil(parser_loader)
    symbol_results: Dict[str, Any] = {}
    total_start_time = time.time()
    for file_result in results.results:
        try:
            current_mtime = os.path.getmtime(file_result.file_path)
            if file_result.file_path in state.symbol_cache:
                cached_mtime, code_map = state.symbol_cache[file_result.file_path]
                if cached_mtime == current_mtime:
                    pass  # Use cache
                else:
                    _, code_map = parser_util.get_symbol_paths(file_result.file_path)
                    state.symbol_cache[file_result.file_path] = (current_mtime, code_map)
            else:
                _, code_map = parser_util.get_symbol_paths(file_result.file_path)
                state.symbol_cache[file_result.file_path] = (current_mtime, code_map)

            locations = [(match.line - 1, match.column_range[0] - 1) for match in file_result.matches]
            symbols = parser_util.find_symbols_for_locations(code_map, locations, max_context_size=max_context_size)
            rel_path = state.config.relative_to_current_path(file_result.file_path)
            for key, value in symbols.items():
                value["name"] = f"{rel_path}/{key}"
                value["file_path"] = rel_path
            symbol_results.update(symbols)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(f"Error parsing {file_result.file_path}: {e}")
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
        return remaining, []
    file_path = remaining[:slash_idx]
    symbols = list(remaining[slash_idx + 1 :].split(","))
    return file_path, symbols


def _determine_current_prefix(file_path: str | None, symbols: list[str]) -> str:
    if symbols and any(symbols):
        return f"symbol:{file_path}/{symbols[-1]}"
    if file_path:
        return f"symbol:{file_path}"
    return ""


def _build_completion_results(file_path: str | None, symbols: list[str], results: list) -> list[str]:
    if not file_path:
        return []
    base_str = f"symbol:{file_path}/"
    symbol_prefix = ",".join(symbols[:-1]) + "," if len(symbols) > 1 else ""
    completions = []
    for result in results:
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
    # Again, DB fallback is omitted.

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
