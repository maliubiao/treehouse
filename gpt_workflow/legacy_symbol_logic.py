"""
This file is deprecated.

It contains the old logic for fetching and prioritizing symbols to build context for the LLM.
This approach has been replaced by a full-file context method. This code is kept for
archival and reference purposes only.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Optional

from colorama import Fore

from llm_query import (
    FileSearchResult,
    FileSearchResults,
    MatchResult,
    query_symbol_service,
)

if TYPE_CHECKING:
    from llm_query import ModelSwitch


def get_and_prioritize_symbols_legacy(
    uniq_references: set,
    main_call_chain: Optional[List[Dict]],
    exception_location: Optional[tuple],
    model_switch: ModelSwitch,
    silent: bool = False,
) -> dict:
    """
    DEPRECATED: Fetches symbols and prioritizes them based on the call stack at the time of the exception.
    It uses a layered approach, adding symbols from the call stack first (deepest to shallowest),
    and then filling any remaining context budget with other referenced symbols.

    1. The call stack at the moment of exception is reconstructed from the trace.
    2. Symbols from this stack are added, starting from the exception source (deepest) and moving up.
    3. If context budget remains, other symbols that were called during the trace are added, smallest first.
    """
    if not uniq_references:
        return {}

    if not silent:
        print(Fore.CYAN + "\n" + "=" * 15 + " Building Smart Context (Legacy) " + "=" * 15)

    # 1. Get model configuration and token budget
    config = model_switch.current_config
    MAX_SYMBOLS_TOKENS = (config.max_context_size or 32768) - 4096
    if not silent:
        print(
            Fore.BLUE
            + f"Model context limit: {config.max_context_size}, budget for symbols: {MAX_SYMBOLS_TOKENS} tokens (estimated)."
        )

    # 2. Fetch ALL referenced symbols to get their content and size
    file_to_lines = defaultdict(list)
    for filename, lineno in uniq_references:
        if filename and lineno:
            file_to_lines[filename].append(lineno)

    file_results = []
    for filename, lines in file_to_lines.items():
        matches = [MatchResult(line=lineno, column_range=(0, 0), text="") for lineno in lines]
        file_results.append(FileSearchResult(file_path=filename, matches=matches))

    all_symbols = query_symbol_service(FileSearchResults(results=file_results), 1024 * 1024)
    if not all_symbols:
        if not silent:
            print(Fore.RED + "Could not retrieve any symbol information.")
        return {}
    if not silent:
        for sym in all_symbols:
            print("symbol service returns symbol: %s" % sym)
    # 3. Create a lookup map for symbols with their approximate token counts
    location_to_symbol_map = {}
    total_tokens = 0  # Track total tokens of all symbols
    for name, symbol_data in all_symbols.items():
        content = symbol_data.get("code", "")
        tokens = len(content) // 3
        total_tokens += tokens
        location_to_symbol_map[name] = {"name": name, "tokens": tokens, "data": symbol_data}

    # 4. Check if all symbols fit within token budget
    if total_tokens <= MAX_SYMBOLS_TOKENS:
        if not silent:
            print(Fore.CYAN + "\nAll symbols fit within token budget. Adding all without prioritization:")
        final_symbols = {name: data["data"] for name, data in location_to_symbol_map.items()}
        if not silent:
            print(Fore.GREEN + f"  ✓ Added all {len(final_symbols)} symbols ({total_tokens} tokens)")
            print(
                Fore.CYAN
                + f"\nSelected {len(final_symbols)} symbols with a total of ~{total_tokens} tokens for context."
            )
            print(Fore.CYAN + "=" * 54)
        return final_symbols

    # 5. Reconstruct the call stack at the point of exception
    call_stack_at_exception = []
    if main_call_chain:
        temp_stack = []
        for ref in main_call_chain:
            ref_type = ref.get("type")
            if ref_type == "call":
                temp_stack.append((ref.get("filename", "?"), ref.get("lineno", 0)))
            elif ref_type == "return":
                if temp_stack:
                    temp_stack.pop()
            elif ref_type == "exception":
                call_stack_at_exception = list(temp_stack)
                break

    if not call_stack_at_exception and exception_location:
        call_stack_at_exception.append(exception_location)

    # 6. Prioritize and build the final list of symbols
    final_symbols = {}
    added_symbol_names = set()
    current_tokens = 0

    # 6a. Add symbols from the call stack, deepest first
    if call_stack_at_exception:
        if not silent:
            print(Fore.CYAN + "\nAdding symbols from exception call stack (deepest first):")
        for loc in reversed(call_stack_at_exception):
            file_path, lineno = loc

            containing_symbol = None
            smallest_size = float("inf")
            for symbol_info in location_to_symbol_map.values():
                s_file = symbol_info["data"]["file_path"]
                s_start = symbol_info["data"]["start_line"]
                s_end = symbol_info["data"]["end_line"]
                if s_file == file_path and s_start <= lineno <= s_end:
                    symbol_size = s_end - s_start
                    if symbol_size < smallest_size:
                        containing_symbol = symbol_info
                        smallest_size = symbol_size

            if containing_symbol:
                name = containing_symbol["name"]
                tokens = containing_symbol["tokens"]
                if name in added_symbol_names:
                    continue

                if current_tokens + tokens <= MAX_SYMBOLS_TOKENS:
                    final_symbols[name] = containing_symbol["data"]
                    current_tokens += tokens
                    added_symbol_names.add(name)
                    if not silent:
                        print(Fore.GREEN + f"  ✓ Added: {name} ({tokens} tokens)")
                else:
                    if not silent:
                        print(Fore.YELLOW + f"  - Skipping {name} ({tokens} tokens) to fit context. Budget full.")
                    break

    # 6b. Fill remaining budget with other referenced symbols, smallest first
    if current_tokens < MAX_SYMBOLS_TOKENS:
        if not silent:
            print(Fore.CYAN + "\nFilling remaining context with other referenced symbols (smallest first):")

        other_symbols = []
        for symbol_info in location_to_symbol_map.values():
            if symbol_info["name"] not in added_symbol_names:
                other_symbols.append(symbol_info)

        sorted_other_symbols = sorted(other_symbols, key=lambda x: x["tokens"])

        for symbol in sorted_other_symbols:
            if current_tokens + symbol["tokens"] <= MAX_SYMBOLS_TOKENS:
                final_symbols[symbol["name"]] = symbol["data"]
                current_tokens += symbol["tokens"]
                added_symbol_names.add(symbol["name"])
                if not silent:
                    print(Fore.GREEN + f"  ✓ Added: {symbol['name']} ({symbol['tokens']} tokens)")
            else:
                break

    total_symbols = len(final_symbols)
    if not silent:
        print(f"\nSelected {total_symbols} symbols with a total of ~{current_tokens} tokens for context.")
        print("=" * 54)

    if not final_symbols and all_symbols:
        if not silent:
            print(Fore.RED + "Error: No symbols could be added. The primary exception symbol might be too large.")

    return final_symbols
