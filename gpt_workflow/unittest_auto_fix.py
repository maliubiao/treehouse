import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
from unittest.mock import ANY

from colorama import Fore, Style
from fixer_prompt import FixerPromptGenerator
from report_generator import ReportGenerator
from tqdm import tqdm

from debugger import tracer
from llm_query import (
    GPT_FLAG_PATCH,
    GPT_FLAGS,
    GPT_SYMBOL_PATCH,
    GPT_VALUE_STORAGE,
    FileSearchResult,
    FileSearchResults,
    MatchResult,
    ModelSwitch,
    PatchPromptBuilder,
    process_patch_response,
    query_symbol_service,
)


def extract_test_case_trace_from_log(log_file_path: str, test_id: str) -> Optional[int]:
    """
    从日志文件中提取指定 test_id 对应的 CALL 语句的 frame_id。

    Args:
        log_file_path (str): 日志文件的路径。
        test_id (str): 要查找的 testMethod 名称 (例如: "test_on_step_hit_with_invalid_line_entry_and_instruction_mode")。

    Returns:
        Optional[int]: 如果找到对应的 frame_id，则返回其整数值；否则返回 None。
    """
    # 定义正则表达式来捕获 frame_id
    # r"\[frame:(\d+)\]" 解释:
    #   \[    : 匹配字面量 '['
    #   frame:: 匹配字面量 'frame:'
    #   (\d+) : 捕获一个或多个数字 (这是我们想要的 frame_id)
    #   \]    : 匹配字面量 ']'
    frame_id_pattern = re.compile(r"\[frame:(\d+)\]")

    # 构建要查找的 testMethod 字符串，提高匹配效率
    target_test_method_str = f"testMethod={test_id}"

    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                # 1. 快速字符串查找过滤：
                # 检查行中是否包含 "↘ CALL" 和 目标 testMethod 字符串。
                # 这是一个高效的初步过滤，避免对不相关的行进行正则匹配。
                if "↘ CALL" in line and target_test_method_str in line and "startTest(" in line:
                    # 2. 进一步检查是否包含 "[frame:"，如果包含，才尝试正则匹配
                    # 再次避免不必要的正则操作，因为有些行可能匹配前两个条件但没有 frame id
                    if "[frame:" in line:
                        # 3. 使用正则表达式提取 frame_id
                        match = frame_id_pattern.search(line)
                        if match:
                            # 提取捕获组1 (即括号内的数字)
                            frame_id_str = match.group(1)
                            # 转换为整数并返回，同时及时中止循环
                            return int(frame_id_str)

        # 如果循环结束仍未找到，则返回 None
        return None

    except FileNotFoundError:
        print(f"错误: 文件 '{log_file_path}' 未找到。")
        return None
    except Exception as e:
        print(f"读取文件时发生错误: {e}")
        return None


def _restart_with_original_args(auto_accept: bool = False):
    """
    Restarts the script with its original command-line arguments.
    This replaces the current process with a new one, ensuring a clean state.
    Optionally adds '--auto-accept-analysis' flag to persist choice across restarts.
    """
    print(Fore.MAGENTA + "\n" + "=" * 20 + " RESTARTING WORKFLOW " + "=" * 20)
    print(Fore.CYAN + "Restarting process to ensure a clean environment for the next cycle...")

    new_argv = sys.argv[:]
    if auto_accept and "--auto-accept-analysis" not in new_argv:
        new_argv.append("--auto-accept-analysis")

    try:
        os.execv(sys.executable, [sys.executable] + new_argv)
    except OSError as e:
        print(Fore.RED + f"Fatal: Failed to restart process: {e}")
        sys.exit(1)


class FailureTracker:
    """
    Tracks repeated failures for the same error location to avoid infinite loops.
    """

    def __init__(self, max_attempts: int):
        self._attempts = defaultdict(int)
        self._max_attempts = max_attempts

    def record_attempt(self, error: dict) -> None:
        """Increments the attempt counter for a given error."""
        key = self._get_key(error)
        self._attempts[key] += 1

    def has_exceeded_limit(self, error: dict) -> bool:
        """Checks if an error has reached the maximum attempt limit."""
        key = self._get_key(error)
        return self._attempts[key] >= self._max_attempts

    def get_attempt_count(self, error: dict) -> int:
        """Returns the current attempt count for an error."""
        return self._attempts[self._get_key(error)]

    @staticmethod
    def _get_key(error: dict) -> tuple:
        """Creates a unique key for an error based on its location."""
        return (error.get("file_path", "unknown"), error.get("line", 0))

    def get_skipped_errors(self) -> list:
        """Gets a list of all error keys that have been skipped."""
        return [key for key, count in self._attempts.items() if count >= self._max_attempts]


class TestAutoFix:
    def __init__(self, test_results: Dict, user_requirement: str = None):
        self.test_results = test_results
        self.user_requirement = user_requirement
        self.error_details = self._extract_error_details()
        self.uniq_references = set()
        self.trace_log = ""
        self.exception_location: Optional[tuple] = None  # (file_path, line_no)
        self.main_call_chain: Optional[List[Dict]] = None

    def _extract_error_details(self) -> List[Dict]:
        """Extract error details from test results in a structured format."""
        error_details = []

        if isinstance(self.test_results.get("results"), dict):
            for category in ["errors", "failures"]:
                for error in self.test_results.get("results", {}).get(category, []):
                    if isinstance(error, dict):
                        file_path = error.get("file_path", "unknown")
                        if file_path != "unknown" and not Path(file_path).exists():
                            print(Fore.YELLOW + f"Warning: File path from test results does not exist: {file_path}")
                            continue

                        error_details.append(
                            {
                                "test_id": error.get("test_id", "unknown"),
                                "file_path": file_path,
                                "line": error.get("line"),
                                "function": error.get("function", "unknown"),
                                "error_type": error.get("error_type", "UnknownError"),
                                "error_message": error.get("error_message", "Unknown error"),
                                "traceback": error.get("traceback", ""),
                                "issue_type": category[:-1],  # removes 's' from 'errors'/'failures'
                                "frame_ref_lines": error.get("frame_ref_lines", []),
                            }
                        )

        return error_details

    def _print_stats(self) -> None:
        """Print colored test statistics summary."""
        total = self.test_results.get("total", 0)
        success = self.test_results.get("success", 0)
        failures = self.test_results.get("failures", 0)
        errors = self.test_results.get("errors", 0)
        skipped = self.test_results.get("skipped", 0)

        print(Fore.CYAN + "\nTest Results Summary:")
        print(Fore.CYAN + "=" * 50)
        print(Fore.GREEN + f"Total: {total}")
        print(Fore.GREEN + f"Passed: {success}")
        print(Fore.RED + f"Failures: {failures}")
        print(Fore.YELLOW + f"Errors: {errors}")
        print(Fore.BLUE + f"Skipped: {skipped}")
        print(Fore.CYAN + "=" * 50)

    def select_error_interactive(self) -> Optional[Dict]:
        """
        Displays a list of all current errors and prompts the user to select one to fix.
        If only one error exists, it is selected automatically.

        Returns:
            The dictionary of the selected error, or None if no selection is made or possible.
        """
        self._print_stats()

        if not self.error_details:
            return None
        print(Fore.YELLOW + "\nPlease select an issue to fix:")
        print(Fore.YELLOW + "=" * 50)
        for i, error in enumerate(self.error_details):
            issue_type = error.get("issue_type", "unknown").upper()
            func_name = error.get("function", "unknown")
            error_type = error.get("error_type", "UnknownError")
            test_id = error.get("test_id", "unknown")
            color = Fore.RED if issue_type == "FAILURE" else Fore.YELLOW

            print(color + f"  {i + 1}: [{issue_type}] in {func_name} ({error_type})")
            print(Fore.CYAN + f"     ID:   {test_id}")
            print(Fore.CYAN + f"     File: {error['file_path']}:{error['line']}")

            error_message = error["error_message"]
            if len(error_message) > 100:
                error_message = error_message[:97] + "..."
            print(Fore.MAGENTA + f"     Msg:  {error_message}" + Style.RESET_ALL)

        print(Fore.YELLOW + "=" * 50)

        if len(self.error_details) == 1:
            print(Fore.GREEN + "\nAutomatically selecting the only available issue.")
            return self.error_details[0]

        while True:
            try:
                choice_str = input(
                    Fore.GREEN + f"Enter the number of the issue to fix (1-{len(self.error_details)}), or 'q' to quit: "
                ).strip()
                if choice_str.lower() == "q":
                    return None

                choice = int(choice_str)
                if 1 <= choice <= len(self.error_details):
                    return self.error_details[choice - 1]
                else:
                    print(Fore.RED + "Invalid choice. Please enter a number from the list.")
            except ValueError:
                print(Fore.RED + "Invalid input. Please enter a number or 'q'.")

    def display_selected_error_details(self, selected_error: Dict, silent: bool = False) -> None:
        """
        Display detailed information for the selected test error, including traceback and tracer logs.
        This method populates `self.uniq_references`, `self.trace_log` and `self.exception_location`.
        If `silent` is True, it will not print to stdout.
        """
        if not silent:
            print(Fore.YELLOW + "\nAnalyzing selected issue:")
            print(Fore.YELLOW + "=" * 50)

            print(Fore.RED + f"\nIssue ({selected_error.get('issue_type', 'unknown')}):")
            print(Fore.CYAN + f"File: {selected_error['file_path']}")
            print(Fore.CYAN + f"Line: {selected_error['line']}")
            print(Fore.CYAN + f"Function: {selected_error['function']}")
            print(Fore.MAGENTA + f"Type: {selected_error['error_type']}")
            print(Fore.MAGENTA + f"Message: {selected_error['error_message']}")

            if selected_error.get("traceback"):
                print(Fore.YELLOW + "\nTraceback:")
                print(Fore.YELLOW + "-" * 30)
                print(Fore.RED + selected_error["traceback"])
                print(Fore.YELLOW + "-" * 30)

        if selected_error.get("file_path") and selected_error.get("line"):
            self._display_tracer_logs(
                selected_error["file_path"],
                selected_error["line"],
                silent=silent,
                test_id=selected_error["test_id"],
                frame_ref_lines=selected_error.get("frame_ref_lines", []),
            )

    def lookup_reference(self, file_path: str, lineno: int) -> None:
        """Display reference information for a specific file and line."""
        self._display_tracer_logs(file_path, lineno)

    def _display_tracer_logs(
        self,
        file_path: str,
        line: int,
        silent: bool = False,
        test_id: str = "",
        frame_ref_lines: List[Tuple[str, int]] = None,
    ) -> None:
        """
        Display relevant tracer logs for the error location and identify the exception source.
        """
        from gpt_lib import graph_tracer

        config = graph_tracer.SiblingConfig(before=1, after=1, functions=["setUp", "tearDown"])
        fn = str(Path(__file__).parent.parent / "debugger/logs/run_all_tests.log")
        log_extractor = graph_tracer.GraphTraceLogExtractor(fn)
        log_extractor.export_trace_graph_text(
            graph_tracer.ROOT_FRAME_ID,
            Path(__file__).parent.parent / "debugger/logs/run_all_tests.graph.txt",
            show_full_trace=True,
        )

        # # log_extractor = tracer.TraceLogExtractor(fn)
        # logs, references_group = log_extractor.lookup(file_path, line, sibling_config=config)
        # if not logs and test_id:
        frame_id = extract_test_case_trace_from_log(str(fn), test_id=test_id.split(".")[-1])
        logs, references_group = log_extractor.lookup(frame_id=frame_id, next_siblings=2)
        if frame_ref_lines:
            for item in frame_ref_lines[:3]:
                self.uniq_references.add(item)
        self.uniq_references.add((file_path, line))
        try:
            if logs:
                self.trace_log = logs[0]
                if not silent:
                    print(Fore.BLUE + "\nTracer Logs:")
                    print(Fore.BLUE + "-" * 30)
                    print(Fore.BLUE + f"{logs[0]}" + Style.RESET_ALL)

                exception_found_in_trace = False
                if references_group:
                    self.main_call_chain = references_group[0]
                    if not silent:
                        print(Fore.BLUE + "\nCall Chain References:")

                    call_stack = []
                    indent_level = 0

                    for ref in self.main_call_chain:
                        ref_type = ref.get("type")
                        func_name = ref.get("func", "?")

                        if ref_type == "call":
                            ref_loc = (ref.get("filename", "?"), ref.get("lineno", 0))
                            call_stack.append(ref_loc)
                            self.uniq_references.add(ref_loc)
                            if not silent:
                                print(
                                    Fore.CYAN
                                    + "  " * indent_level
                                    + f"→ {func_name}() at {ref.get('filename', '?')}:{ref.get('lineno', '?')}"
                                )
                            indent_level += 1
                        elif ref_type == "return":
                            if call_stack:
                                call_stack.pop()
                            indent_level = max(0, indent_level - 1)
                            if not silent:
                                print(Fore.GREEN + "  " * indent_level + f"← {func_name}() returned")
                        elif ref_type == "exception":
                            indent_level = max(0, indent_level - 1)
                            if not silent:
                                print(Fore.RED + "  " * indent_level + f"✗ {func_name}() raised exception")
                            if call_stack:
                                self.exception_location = call_stack[-1]  # Deepest frame on stack
                                exception_found_in_trace = True
                                if not silent:
                                    print(
                                        Fore.MAGENTA
                                        + f"  Pinpointed exception source from tracer log: {self.exception_location[0]}:{self.exception_location[1]}"
                                    )

                if not exception_found_in_trace:
                    self.exception_location = (file_path, line)
                    if not silent:
                        print(
                            Fore.YELLOW
                            + f"\nCould not pinpoint exception in trace, using test report location as fallback: {file_path}:{line}"
                        )
            else:
                if not silent:
                    print(Fore.YELLOW + f"\nNo tracer logs found for this location, {file_path}:{line}")
                self.exception_location = (file_path, line)  # Fallback
        except (FileNotFoundError, PermissionError, ValueError) as e:
            if not silent:
                print(Fore.RED + f"\nFailed to extract tracer logs: {str(e)}")
            self.exception_location = (file_path, line)  # Fallback

    def get_and_prioritize_symbols(self, model_switch: ModelSwitch, silent: bool = False) -> dict:
        """
        Fetches symbols and prioritizes them based on the call stack at the time of the exception.
        It uses a layered approach, adding symbols from the call stack first (deepest to shallowest),
        and then filling any remaining context budget with other referenced symbols.

        1. The call stack at the moment of exception is reconstructed from the trace.
        2. Symbols from this stack are added, starting from the exception source (deepest) and moving up.
        3. If context budget remains, other symbols that were called during the trace are added, smallest first.
        """
        if not self.uniq_references:
            return {}

        if not silent:
            print(Fore.CYAN + "\n" + "=" * 15 + " Building Smart Context " + "=" * 15)

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
        for filename, lineno in self.uniq_references:
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
        if self.main_call_chain:
            temp_stack = []
            for ref in self.main_call_chain:
                ref_type = ref.get("type")
                if ref_type == "call":
                    temp_stack.append((ref.get("filename", "?"), ref.get("lineno", 0)))
                elif ref_type == "return":
                    if temp_stack:
                        temp_stack.pop()
                elif ref_type == "exception":
                    call_stack_at_exception = list(temp_stack)
                    break

        if not call_stack_at_exception and self.exception_location:
            call_stack_at_exception.append(self.exception_location)

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
            print(
                Fore.CYAN + f"\nSelected {total_symbols} symbols with a total of ~{current_tokens} tokens for context."
            )
            print(Fore.CYAN + "=" * 54)

        if not final_symbols and all_symbols:
            if not silent:
                print(Fore.RED + "Error: No symbols could be added. The primary exception symbol might be too large.")

        return final_symbols

    @staticmethod
    @tracer.trace(
        target_files=["*.py"],
        enable_var_trace=True,
        report_name="run_all_tests.html",
        ignore_self=False,
        ignore_system_paths=True,
        disable_html=True,
        source_base_dir=Path(__file__).parent.parent,
        exclude_functions=["symbol_at_line", "get_symbol_paths", "traverse", "search_exact", "__init__", "insert"],
    )
    def run_tests(test_patterns: Optional[List[str]] = None, verbosity: int = 1, list_tests: bool = False) -> Dict:
        """
        Run tests and return results in JSON format.
        """
        return run_tests(test_patterns=test_patterns, verbosity=verbosity, json_output=True, list_mode=list_tests)


from tests.test_main import run_tests


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Test auto-fix tool with continuous repair workflow.")
    parser.add_argument(
        "test_patterns",
        nargs="*",
        default=None,
        help="Test selection patterns (e.g. +test_module*, -/exclude.*/, TestCase.test_method)",
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        choices=[0, 1, 2],
        default=1,
        help="Output verbosity (0=quiet, 1=default, 2=verbose)",
    )
    parser.add_argument("--list-tests", action="store_true", help="List all available test cases without running them")
    parser.add_argument(
        "--lookup",
        nargs=2,
        metavar=("FILE", "LINE"),
        help="Lookup reference information for specific file and line number",
    )
    parser.add_argument("--user-requirement", help="User's specific requirements to be added to the prompt", default="")
    parser.add_argument(
        "--model",
        default="deepseek-r1",
        help="Specify the language model for FIXING the code. This is the 'fixer' model.",
    )
    parser.add_argument(
        "--analyzer-model",
        default=None,
        help="Specify the language model for ANALYZING the failure. This is the 'analyzer' model. If not provided, the fixer model will be used for analysis as well.",
    )
    parser.add_argument(
        "--direct-fix", action="store_true", help="Directly generate a fix without the interactive explanation step."
    )
    parser.add_argument(
        "--auto-pilot", action="store_true", help="Enable fully automated regression analysis and fix mode."
    )
    parser.add_argument(
        "--parallel-analysis",
        nargs="?",
        const=os.cpu_count() or 4,
        type=int,
        metavar="N",
        help="Enable parallel analysis of all failed tests with N concurrent workers, followed by INTERACTIVE fixing.",
    )
    parser.add_argument(
        "--parallel-autofix",
        nargs="?",
        const=os.cpu_count() or 4,
        type=int,
        metavar="N",
        help="Enable parallel analysis followed by AUTOMATED, sequential fixing of all detected issues using N workers for analysis.",
    )
    parser.add_argument(
        "--isolated-fix",
        action="store_true",
        help="Run each failing test in an isolated subprocess for analysis and fixing. Overrides other workflow modes.",
    )
    parser.add_argument(
        "--run-single-test",
        metavar="TEST_ID",
        help=argparse.SUPPRESS,  # Hide from help menu
        default=None,
        dest="single_test_id",
    )
    default_report_dir = Path(__file__).parent.parent / "doc/testcase-report"
    parser.add_argument(
        "--report-dir",
        default=str(default_report_dir),
        help=f"Directory to save analysis reports. Defaults to: {default_report_dir}",
    )
    parser.add_argument(
        "--auto-accept-analysis", action="store_true", help=argparse.SUPPRESS
    )  # Hidden arg for session state
    return parser.parse_args()


def _consume_stream_and_get_text(stream_generator, print_stream: bool = True) -> str:
    """Consumes a generator, prints its content, and returns the full text."""
    text_chunks = []
    if print_stream:
        print(Fore.BLUE + "--- AI Analysis ---" + Style.RESET_ALL)
    for chunk in stream_generator:
        if print_stream:
            print(chunk, end="", flush=True)
        text_chunks.append(chunk)
    if print_stream:
        print("\n" + Fore.BLUE + "-------------------" + Style.RESET_ALL)
    return "".join(text_chunks)


def _interactive_patch_and_retry(fixer_model_switch: ModelSwitch, prompt: str, symbol_storage: list) -> bool:
    """
    Interactively generates and applies a patch, allowing the user to retry on failure.
    Returns True on success, False on failure or user cancellation.
    """
    while True:
        try:
            print(Fore.YELLOW + "正在生成修复方案...")
            text_stream = fixer_model_switch.query(fixer_model_switch.model_name, prompt, stream=True)
            process_patch_response(text_stream, symbol_storage)
            return True  # Success
        except (ValueError, IndexError) as e:
            print(Fore.RED + f"\nError processing AI response to generate patch: {e}")
            print(
                Fore.YELLOW
                + "This can happen if the AI's response is malformed or doesn't follow the patch format correctly."
            )
            retry_choice = (
                input(Fore.YELLOW + "Would you like to try generating the fix again? (y/n): ").strip().lower()
            )
            if retry_choice != "y":
                print(Fore.RED + "User aborted the fix for this issue.")
                return False


def _perform_direct_fix(auto_fix: TestAutoFix, symbol_result: dict, fixer_model_switch: ModelSwitch, user_req: str):
    """Performs a direct, one-step fix by analyzing the tracer log and generating a patch."""
    print(Fore.YELLOW + "\nAttempting to generate a fix directly...")

    prompt_content = FixerPromptGenerator.create_direct_fix_prompt(trace_log=auto_fix.trace_log, user_req=user_req)

    GPT_FLAGS[GPT_FLAG_PATCH] = True
    p = PatchPromptBuilder(
        use_patch=True, symbols=[], tokens_left=fixer_model_switch.current_config.max_context_size * 3
    )
    p.process_search_results(symbol_result)
    prompt = p.build(user_requirement=prompt_content)

    _interactive_patch_and_retry(
        fixer_model_switch=fixer_model_switch, prompt=prompt, symbol_storage=GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH]
    )


def _get_user_feedback_on_analysis(analysis_text: str) -> tuple[str, bool]:
    """
    Presents the AI's analysis to the user and asks for feedback on how to proceed with the fix.

    Returns:
        A tuple containing:
        - A string with the user's directive for the fix (or empty to abort).
        - A boolean indicating if the choice should be remembered for the session.
    """
    print(Fore.YELLOW + "\n" + "=" * 15 + " User Review and Direction " + "=" * 15)
    print(Fore.CYAN + "The AI has analyzed the issue. Please review its findings and provide direction for the fix.")
    print(Fore.YELLOW + "=" * 54)

    print(Fore.GREEN + "Please choose a course of action:")
    print(Fore.CYAN + "  1. Accept analysis and proceed with recommended fix.")
    print(Fore.CYAN + "  2. Analysis is correct, but provide specific instruction.")
    print(Fore.CYAN + "  3. Analysis seems wrong, provide new direction.")
    print(Fore.YELLOW + "  4. Accept & auto-accept for this session.")
    print(Fore.CYAN + "  q. Quit the fix process.")

    while True:
        choice = input(Fore.GREEN + "Your choice (1/2/3/4/q): ").strip().lower()

        default_directive = "按照上述技术专家的分析，解决用户遇到的问题，修复单元测试中的错误，使其能够成功通过。"

        if choice == "1":
            return default_directive, False
        elif choice == "2":
            user_instruction = input(Fore.GREEN + "Please provide your specific instruction: ").strip()
            if user_instruction:
                return user_instruction, False
            else:
                print(Fore.RED + "Instruction cannot be empty. Please try again.")
        elif choice == "3":
            user_instruction = input(Fore.GREEN + "Please describe the correct analysis and how to fix it: ").strip()
            if user_instruction:
                return user_instruction, False
            else:
                print(Fore.RED + "Direction cannot be empty. Please try again.")
        elif choice == "4":
            print(Fore.YELLOW + "Will auto-accept analysis for the rest of this session.")
            return default_directive, True
        elif choice == "q":
            return "", False  # Empty string signals to abort
        else:
            print(Fore.RED + "Invalid choice. Please enter 1, 2, 3, 4, or q.")


def _perform_two_step_fix(
    auto_fix: TestAutoFix,
    symbol_result: dict,
    analyzer_model_switch: ModelSwitch,
    fixer_model_switch: ModelSwitch,
    auto_accept: bool = False,
) -> bool:
    """
    Performs an interactive, two-step fix and returns whether the choice should be remembered.
    1. Analyzes the failure and presents the analysis.
    2. Gets user feedback and direction (or skips if auto_accept is True).
    3. Generates a patch based on the analysis and user's final command.

    Returns:
        A boolean indicating if the "auto-accept" choice should be persisted for the next run.
    """
    print(Fore.YELLOW + "\nStep 1: Generating failure analysis...")
    print(Fore.CYAN + f"(Using Analyzer: {analyzer_model_switch.model_name})")

    # Step 1: Generate analysis prompt and query the model
    analyze_prompt_content = FixerPromptGenerator.create_analysis_prompt(trace_log=auto_fix.trace_log)
    p_explain = PatchPromptBuilder(
        use_patch=False, symbols=[], tokens_left=analyzer_model_switch.current_config.max_context_size * 3
    )
    p_explain.process_search_results(symbol_result)
    prompt_explain = p_explain.build(user_requirement=analyze_prompt_content)
    stream = analyzer_model_switch.query(analyzer_model_switch.model_name, prompt_explain, stream=True)
    analysis_text = _consume_stream_and_get_text(stream)

    # Step 2: Get user feedback on the analysis
    remember_choice = auto_accept
    if auto_accept:
        print(Fore.GREEN + "\nAuto-accepting analysis based on previous choice.")
        user_directive = "按照上述技术专家的分析，解决用户遇到的问题，修复单元测试中的错误，使其能够成功通过。"
    else:
        user_directive, remember_choice = _get_user_feedback_on_analysis(analysis_text)

    if not user_directive:
        print(Fore.RED + "User aborted the fix process.")
        return False  # Don't remember the choice if user aborts

    # Step 3: Generate the fix based on analysis and user directive
    print(Fore.YELLOW + "\nStep 2: Generating fix based on analysis and user directive...")
    print(Fore.CYAN + f"(Using Fixer: {fixer_model_switch.model_name})")
    fix_prompt_content = FixerPromptGenerator.create_fix_from_analysis_prompt(
        trace_log=auto_fix.trace_log,
        analysis_text=analysis_text,
        user_directive=user_directive,
    )

    GPT_FLAGS[GPT_FLAG_PATCH] = True
    p_fix = PatchPromptBuilder(
        use_patch=True, symbols=[], tokens_left=fixer_model_switch.current_config.max_context_size * 3
    )
    p_fix.process_search_results(symbol_result)
    prompt_fix = p_fix.build(user_requirement=fix_prompt_content)

    _interactive_patch_and_retry(
        fixer_model_switch=fixer_model_switch,
        prompt=prompt_fix,
        symbol_storage=GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH],
    )
    return remember_choice


def _perform_automated_fix_and_report(
    auto_fix: TestAutoFix,
    selected_error: dict,
    symbol_result: dict,
    analyzer_model_switch: ModelSwitch,
    fixer_model_switch: ModelSwitch,
    report_generator: ReportGenerator,
):
    """Analyzes an error, generates a report, and applies a fix in auto-pilot mode."""
    print(Fore.YELLOW + "Generating problem analysis for report...")
    print(Fore.CYAN + f"(Using Analyzer: {analyzer_model_switch.model_name})")

    # Step 1: Get Explanation for the report
    explain_prompt_content = FixerPromptGenerator.create_analysis_prompt(trace_log=auto_fix.trace_log)

    p_explain = PatchPromptBuilder(
        use_patch=False, symbols=[], tokens_left=analyzer_model_switch.current_config.max_context_size * 3
    )
    p_explain.process_search_results(symbol_result)
    prompt_explain = p_explain.build(user_requirement=explain_prompt_content)
    stream = analyzer_model_switch.query(analyzer_model_switch.model_name, prompt_explain, stream=True)
    analysis_text = _consume_stream_and_get_text(stream, print_stream=True)

    # Step 2: Prepare the fix prompt (which will also be in the report)
    user_req_for_fix = "按照专家建议，解决用户遇到的问题，修复test_*符号中的错误"
    fix_prompt_content = FixerPromptGenerator.create_fix_from_analysis_prompt(
        trace_log=auto_fix.trace_log,
        analysis_text=analysis_text,
        user_directive=user_req_for_fix,
    )
    GPT_FLAGS[GPT_FLAG_PATCH] = True
    p_fix = PatchPromptBuilder(
        use_patch=True, symbols=[], tokens_left=fixer_model_switch.current_config.max_context_size * 3
    )
    p_fix.process_search_results(symbol_result)
    prompt_fix = p_fix.build(user_requirement=fix_prompt_content)

    # Step 3: Generate and save the report
    report_path = report_generator.create_report(test_info=selected_error, analysis=analysis_text, prompt=prompt_fix)
    print(Fore.GREEN + f"Analysis report saved to: {report_path}")

    # Step 4: Generate and apply the fix
    print(Fore.YELLOW + "Generating and applying fix...")
    print(Fore.CYAN + f"(Using Fixer: {fixer_model_switch.model_name})")
    try:
        text_fix = fixer_model_switch.query(fixer_model_switch.model_name, prompt_fix, stream=True)
        process_patch_response(text_fix, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])
    except (ValueError, IndexError) as e:
        print(Fore.RED + f"\nError processing AI response to generate patch: {e}")
        print(Fore.YELLOW + "Automated fix failed. This can happen if the AI's response is malformed. Skipping.")


def run_fix_loop(args: argparse.Namespace, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch):
    """Main loop for interactive test fixing. Runs one cycle and then restarts."""
    fix_mode = None
    remember_choice = False

    if args.auto_accept_analysis:
        fix_mode = "two_step"
    elif not args.direct_fix:
        print(Fore.YELLOW + "\n请选择修复模式：")
        print(Fore.CYAN + "1. 解释并修复 (两步, 包含用户反馈)")
        print(Fore.CYAN + "2. 直接修复 (一步)")
        print(Fore.CYAN + "3. 退出")
        choice = input(Fore.GREEN + "请选择 (1/2/3): ").strip()

        if choice == "1":
            fix_mode = "two_step"
        elif choice == "2":
            fix_mode = "direct"
        else:
            print(Fore.RED + "已退出。")
            return
    else:
        fix_mode = "direct"

    print(Fore.CYAN + "\n" + "=" * 20 + " 开始新一轮测试 " + "=" * 20)
    test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
    auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)
    selected_error = auto_fix.select_error_interactive()

    if not selected_error:
        if not auto_fix.error_details:
            print(Fore.GREEN + "\n🎉 恭喜！所有测试均已通过。")
        else:
            print(Fore.RED + "\n用户选择退出修复流程。")
        return

    auto_fix.uniq_references = set()
    auto_fix.trace_log = ""
    auto_fix.display_selected_error_details(selected_error)

    if not auto_fix.uniq_references:
        print(Fore.YELLOW + "\n未找到错误的有效引用。无法自动修复，请手动检查。")
        continue_choice = input(Fore.GREEN + "\n是否返回列表选择其他问题或重新运行测试? (y/n): ").strip().lower()
        if continue_choice == "y":
            _restart_with_original_args()
        return

    symbol_result = auto_fix.get_and_prioritize_symbols(fixer_model_switch)

    if not symbol_result:
        print(Fore.RED + "无法构建修复上下文，跳过此问题。")
        _restart_with_original_args()  # Restart to try again or select another error
        return

    if fix_mode == "direct":
        _perform_direct_fix(auto_fix, symbol_result, fixer_model_switch, args.user_requirement)
    elif fix_mode == "two_step":
        remember_choice = _perform_two_step_fix(
            auto_fix, symbol_result, analyzer_model_switch, fixer_model_switch, auto_accept=args.auto_accept_analysis
        )

    continue_choice = input(Fore.GREEN + "\n补丁已应用。是否继续修复下一个问题？ (y/n): ").strip().lower()
    if continue_choice == "y":
        _restart_with_original_args(auto_accept=remember_choice)
    else:
        print(Fore.RED + "用户选择退出修复流程。")


def run_auto_pilot_loop(args: argparse.Namespace, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch):
    """Main loop for the fully automated test fixing and reporting workflow. Runs one cycle."""
    print(Fore.MAGENTA + "🚀 " + "=" * 20 + " Auto-Pilot Mode Engaged " + "=" * 20 + " 🚀")
    report_generator = ReportGenerator(report_dir=args.report_dir)
    # Note: FailureTracker state is lost on restart, which is acceptable.
    # It prevents infinite loops within a single run, not across runs.
    # A more persistent tracker (e.g., file-based) would be needed for cross-run tracking.
    failure_tracker = FailureTracker(max_attempts=2)

    print(Fore.CYAN + "\n" + "=" * 20 + " 开始新一轮测试 " + "=" * 20)
    test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
    auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)
    auto_fix._print_stats()

    if not auto_fix.error_details:
        print(Fore.GREEN + "\n🎉 恭喜！所有测试均已通过。Auto-Pilot完成任务。")
        return

    selected_error = None
    for error in auto_fix.error_details:
        if not failure_tracker.has_exceeded_limit(error):
            selected_error = error
            break

    if not selected_error:
        print(Fore.RED + "\n所有剩余错误已达到最大重试次数，无法继续自动修复。")
        skipped = failure_tracker.get_skipped_errors()
        print(Fore.YELLOW + f"被放弃的错误 ({len(skipped)}):")
        for i, (file_path, line) in enumerate(skipped):
            print(f"  {i + 1}. {file_path}:{line}")
        print(Fore.MAGENTA + "Auto-Pilot 退出。")
        return

    failure_tracker.record_attempt(selected_error)
    attempt_count = failure_tracker.get_attempt_count(selected_error)
    print(Fore.CYAN + f"\n▶️ 开始处理错误 (第 {attempt_count}/2 次尝试):")

    auto_fix.uniq_references = set()
    auto_fix.trace_log = ""
    auto_fix.display_selected_error_details(selected_error)

    if not auto_fix.uniq_references:
        print(Fore.YELLOW + "\n未找到错误的有效引用，无法自动修复。跳过此错误并重启。")
        _restart_with_original_args()
        return

    symbol_result = auto_fix.get_and_prioritize_symbols(fixer_model_switch)
    if not symbol_result:
        print(Fore.RED + "无法构建修复上下文，跳过此问题并重启。")
        _restart_with_original_args()
        return

    _perform_automated_fix_and_report(
        auto_fix, selected_error, symbol_result, analyzer_model_switch, fixer_model_switch, report_generator
    )

    print(Fore.GREEN + "\n补丁已应用。将自动重启进程以验证修复效果...")
    _restart_with_original_args()


class AnalyzedError(NamedTuple):
    """Data class to hold the results of a single error analysis."""

    error_detail: dict
    analysis_text: str
    trace_log: str
    symbol_result: dict
    success: bool


def analyze_error_task(
    error_detail: dict, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch
) -> AnalyzedError:
    """
    Analyzes a single test error. Designed to be run in a separate thread.
    This function is self-contained and does not print to stdout.
    """
    # Create a temporary instance to manage state for this specific error
    auto_fix = TestAutoFix(test_results={}, user_requirement="")

    # Populate internal state like trace_log, uniq_references by running analysis silently
    auto_fix.display_selected_error_details(error_detail, silent=True)
    if not auto_fix.uniq_references:
        return AnalyzedError(error_detail, "Failed to find references in tracer logs.", "", {}, False)

    # Get symbol context silently
    symbol_result = auto_fix.get_and_prioritize_symbols(fixer_model_switch, silent=True)
    if not symbol_result:
        return AnalyzedError(error_detail, "Failed to build symbol context.", auto_fix.trace_log, {}, False)

    # Perform the analysis query (without printing stream)
    analyze_prompt_content = FixerPromptGenerator.create_analysis_prompt(trace_log=auto_fix.trace_log)
    p_explain = PatchPromptBuilder(
        use_patch=False, symbols=[], tokens_left=analyzer_model_switch.current_config.max_context_size * 3
    )
    p_explain.process_search_results(symbol_result)
    prompt_explain = p_explain.build(user_requirement=analyze_prompt_content)
    stream = analyzer_model_switch.query(analyzer_model_switch.model_name, prompt_explain, stream=True)
    analysis_text = _consume_stream_and_get_text(stream, print_stream=False)

    return AnalyzedError(error_detail, analysis_text, auto_fix.trace_log, symbol_result, True)


def select_analysis_to_fix_interactive(analyzed_errors: List[AnalyzedError]) -> Optional[AnalyzedError]:
    """Displays a list of analyzed errors and prompts the user to select one."""
    print(Fore.YELLOW + "\n" + "=" * 15 + " Parallel Analysis Complete " + "=" * 15)
    print(Fore.CYAN + "Please select an issue to fix based on the AI's analysis:")
    print(Fore.YELLOW + "=" * 54)

    for i, result in enumerate(analyzed_errors):
        error = result.error_detail
        issue_type = error.get("issue_type", "unknown").upper()
        func_name = error.get("function", "unknown")
        error_type = error.get("error_type", "UnknownError")
        color = Fore.RED if issue_type == "FAILURE" else Fore.YELLOW

        print(color + f"  {i + 1}: [{issue_type}] in {func_name} ({error_type})")
        print(Fore.CYAN + f"     File: {error['file_path']}:{error['line']}")

        analysis_snippet = result.analysis_text.replace("\n", " ").strip()
        if len(analysis_snippet) > 120:
            analysis_snippet = analysis_snippet[:117] + "..."
        print(Fore.BLUE + f"     Analysis: {analysis_snippet}" + Style.RESET_ALL)

    print(Fore.YELLOW + "=" * 54)

    while True:
        try:
            choice_str = input(
                Fore.GREEN + f"Enter the number of the issue to fix (1-{len(analyzed_errors)}), or 'q' to quit: "
            ).strip()
            if choice_str.lower() == "q":
                return None
            choice = int(choice_str)
            if 1 <= choice <= len(analyzed_errors):
                return analyzed_errors[choice - 1]
            else:
                print(Fore.RED + "Invalid choice. Please enter a number from the list.")
        except ValueError:
            print(Fore.RED + "Invalid input. Please enter a number or 'q'.")


def _generate_and_apply_patch_from_analysis(
    analyzed_error: AnalyzedError, user_directive: str, fixer_model_switch: ModelSwitch
):
    """Generates and applies a patch based on a pre-computed analysis and a directive."""
    print(Fore.YELLOW + "\nGenerating fix based on analysis and user directive...")
    print(Fore.CYAN + f"(Using Fixer: {fixer_model_switch.model_name})")

    fix_prompt_content = FixerPromptGenerator.create_fix_from_analysis_prompt(
        trace_log=analyzed_error.trace_log,
        analysis_text=analyzed_error.analysis_text,
        user_directive=user_directive,
    )

    GPT_FLAGS[GPT_FLAG_PATCH] = True
    p_fix = PatchPromptBuilder(
        use_patch=True, symbols=[], tokens_left=fixer_model_switch.current_config.max_context_size * 3
    )
    p_fix.process_search_results(analyzed_error.symbol_result)
    prompt_fix = p_fix.build(user_requirement=fix_prompt_content)

    _interactive_patch_and_retry(
        fixer_model_switch=fixer_model_switch,
        prompt=prompt_fix,
        symbol_storage=GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH],
    )


def _perform_interactive_fix_from_analysis(analyzed_error: AnalyzedError, fixer_model_switch: ModelSwitch):
    """Takes a pre-analyzed error and walks the user through the fixing process."""
    # 1. Present the pre-computed analysis and get user feedback
    print(Fore.BLUE + "\n--- AI Analysis ---" + Style.RESET_ALL)
    print(analyzed_error.analysis_text)
    print(Fore.BLUE + "-------------------" + Style.RESET_ALL)

    user_directive, _ = _get_user_feedback_on_analysis(analyzed_error.analysis_text)
    if not user_directive:
        print(Fore.RED + "User aborted the fix process.")
        return

    # 2. Generate the fix
    _generate_and_apply_patch_from_analysis(analyzed_error, user_directive, fixer_model_switch)


def run_parallel_analysis_workflow(
    args: argparse.Namespace, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch
):
    """Main loop for the parallel analysis, sequential fix workflow. Runs one cycle."""
    print(Fore.CYAN + "\n" + "=" * 20 + " 开始新一轮测试 " + "=" * 20)
    test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
    auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)
    auto_fix._print_stats()

    if not auto_fix.error_details:
        print(Fore.GREEN + "\n🎉 恭喜！所有测试均已通过。")
        return

    print(
        Fore.CYAN
        + f"\nFound {len(auto_fix.error_details)} issues. Starting parallel analysis with {args.parallel_analysis} workers..."
    )

    analyzed_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel_analysis) as executor:
        future_to_error = {
            executor.submit(analyze_error_task, error, analyzer_model_switch, fixer_model_switch): error
            for error in auto_fix.error_details
        }
        for future in tqdm(
            concurrent.futures.as_completed(future_to_error),
            total=len(auto_fix.error_details),
            desc="Analyzing errors",
        ):
            analyzed_results.append(future.result())

    successful_analyses = [r for r in analyzed_results if r.success]
    failed_analyses = [r for r in analyzed_results if not r.success]

    if failed_analyses:
        print(Fore.RED + "\nSome analyses could not be completed:")
        for result in failed_analyses:
            func = result.error_detail.get("function", "unknown")
            print(Fore.YELLOW + f"  - {func}: {result.analysis_text}")

    if not successful_analyses:
        print(Fore.RED + "\nNo errors could be analyzed successfully. Restarting workflow.")
        _restart_with_original_args()
        return

    # This inner loop allows fixing multiple issues from the same analysis batch.
    while successful_analyses:
        selected_analysis = select_analysis_to_fix_interactive(successful_analyses)

        if not selected_analysis:
            print(Fore.YELLOW + "\nNo issue selected from the current batch.")
            user_choice = (
                input(Fore.GREEN + "Do you want to re-run tests and start a new analysis cycle? (y/n): ")
                .strip()
                .lower()
            )
            if user_choice == "y":
                _restart_with_original_args()
            return  # Exit if user says no or quits

        _perform_interactive_fix_from_analysis(selected_analysis, fixer_model_switch)
        successful_analyses.remove(selected_analysis)

        if not successful_analyses:
            print(Fore.GREEN + "\nAll analyzed issues from this batch have been addressed.")
            print(Fore.CYAN + "The workflow will now restart to verify fixes and check for new issues.")
            _restart_with_original_args()
            return

        print(Fore.GREEN + "\nPatch applied. What would you like to do next?")
        print(Fore.CYAN + "  1. Fix another issue from the remaining list.")
        print(Fore.CYAN + "  2. Restart the workflow (re-run all tests).")
        print(Fore.CYAN + "  q. Quit the workflow.")

        user_choice = ""
        while user_choice not in ["1", "2", "q"]:
            user_choice = input(Fore.GREEN + "Your choice (1/2/q): ").strip().lower()
            if user_choice not in ["1", "2", "q"]:
                print(Fore.RED + "Invalid choice. Please enter 1, 2, or q.")

        if user_choice == "1":
            continue  # Continue with the current list of analyses
        elif user_choice == "2":
            _restart_with_original_args()
            return
        elif user_choice == "q":
            print(Fore.RED + "\nWorkflow finished.")
            return


def run_parallel_autofix_workflow(
    args: argparse.Namespace, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch
):
    """Main loop for the parallel analysis and automated fix workflow. Runs one cycle."""
    print(Fore.MAGENTA + "🚀 " + "=" * 20 + " Parallel Auto-Fix Mode Engaged " + "=" * 20 + " 🚀")
    failure_tracker = FailureTracker(max_attempts=2)

    print(Fore.CYAN + "\n" + "=" * 20 + " 开始新一轮测试 " + "=" * 20)
    test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
    auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)
    auto_fix._print_stats()

    if not auto_fix.error_details:
        print(Fore.GREEN + "\n🎉 恭喜！所有测试均已通过。Parallel Auto-Fix完成任务。")
        return

    errors_to_analyze = [e for e in auto_fix.error_details if not failure_tracker.has_exceeded_limit(e)]

    if not errors_to_analyze:
        print(Fore.RED + "\n所有剩余错误已达到最大重试次数，无法继续自动修复。")
        # Displaying skipped errors might be less useful now since tracker state is not persisted.
        print(Fore.MAGENTA + "Parallel Auto-Fix 退出。")
        return

    print(
        Fore.CYAN
        + f"\nFound {len(errors_to_analyze)} issues to analyze. Starting parallel analysis with {args.parallel_autofix} workers..."
    )
    analyzed_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel_autofix) as executor:
        future_to_error = {
            executor.submit(analyze_error_task, error, analyzer_model_switch, fixer_model_switch): error
            for error in errors_to_analyze
        }
        for future in tqdm(
            concurrent.futures.as_completed(future_to_error),
            total=len(errors_to_analyze),
            desc="Analyzing errors",
        ):
            analyzed_results.append(future.result())

    successful_analyses = [r for r in analyzed_results if r.success]

    if not successful_analyses:
        print(Fore.RED + "\nNo errors could be analyzed successfully. Restarting test cycle.")
        _restart_with_original_args()
        return

    print(Fore.GREEN + f"\nAnalysis complete. Attempting to fix {len(successful_analyses)} issues sequentially.")

    for i, analyzed_error in enumerate(successful_analyses):
        error_detail = analyzed_error.error_detail
        func_name = error_detail.get("function", "unknown")
        # Failure tracking is per-run, which is fine.
        failure_tracker.record_attempt(error_detail)
        attempt_count = failure_tracker.get_attempt_count(error_detail)

        print(Fore.YELLOW + "\n" + "-" * 70)
        print(Fore.CYAN + f"Fixing issue {i + 1}/{len(successful_analyses)} in {func_name} (Attempt {attempt_count}/2)")
        _consume_stream_and_get_text(iter([analyzed_error.analysis_text]), print_stream=True)

        user_directive = "按照上述技术专家的分析，解决用户遇到的问题，修复单元测试中的错误，使其能够成功通过。"
        _generate_and_apply_patch_from_analysis(analyzed_error, user_directive, fixer_model_switch)
        print(Fore.GREEN + f"Patch applied for {func_name}.")

    print(Fore.CYAN + "\nAll patches from this batch have been applied. Restarting to verify...")
    _restart_with_original_args()


def run_isolated_fix_master(args: argparse.Namespace):
    """The parent process in isolated mode. Finds failing tests and spawns child processes to fix them."""
    print(Fore.MAGENTA + "🚀 " + "=" * 20 + " Isolated Fix Mode Engaged " + "=" * 20 + " 🚀")
    print(Fore.CYAN + "\nRunning all tests once to find failures...")

    # Run tests with low verbosity to get the list of failures
    initial_test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=0)
    failed_test_ids = set()
    results = initial_test_results.get("results", {})
    for category in ["errors", "failures"]:
        for error in results.get(category, []):
            test_id = error.get("test_id")
            if test_id:
                failed_test_ids.add(test_id)

    if not failed_test_ids:
        print(Fore.GREEN + "\n🎉 No failing tests found. Nothing to do.")
        auto_fix = TestAutoFix(initial_test_results)
        auto_fix._print_stats()
        return

    sorted_failed_ids = sorted(list(failed_test_ids))
    print(Fore.YELLOW + f"\nFound {len(sorted_failed_ids)} failing tests to fix:")
    for test_id in sorted_failed_ids:
        print(Fore.RED + f"  - {test_id}")

    fixed_count = 0
    for i, test_id in enumerate(sorted_failed_ids):
        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + f"Spawning isolated process for: {test_id} ({i + 1}/{len(sorted_failed_ids)})")
        print(Fore.CYAN + "=" * 70)

        command = [sys.executable, __file__, "--run-single-test", test_id]
        if args.user_requirement:
            command.extend(["--user-requirement", args.user_requirement])
        if args.model:
            command.extend(["--model", args.model])
        if args.analyzer_model:
            command.extend(["--analyzer-model", args.analyzer_model])
        command.extend(["-v", str(args.verbosity)])

        process = subprocess.run(command)

        if process.returncode == 0:
            print(Fore.GREEN + f"\n✅ Successfully fixed and verified: {test_id}")
            fixed_count += 1
        else:
            print(Fore.RED + f"\n❌ Failed to fix: {test_id}. See logs above. Moving to the next test.")

    print(Fore.MAGENTA + "\n" + "=" * 20 + " Isolated Fix Workflow Complete " + "=" * 20)
    print(Fore.CYAN + f"Summary: Attempted to fix {len(sorted_failed_ids)} tests, successfully fixed {fixed_count}.")
    print(Fore.CYAN + "Re-running all tests to get the final status...")
    final_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
    auto_fix = TestAutoFix(final_results)
    auto_fix._print_stats()


def run_single_test_fix_loop(args: argparse.Namespace, test_id: str):
    """The main loop for a child process, focusing on fixing a single test case."""
    print(Fore.CYAN + f"--- Child Process for Test: {test_id} ---")

    fixer_model_name = args.model
    analyzer_model_name = args.analyzer_model if args.analyzer_model else fixer_model_name
    analyzer_model_switch = ModelSwitch()
    analyzer_model_switch.select(analyzer_model_name)

    if analyzer_model_name == fixer_model_name:
        fixer_model_switch = analyzer_model_switch
    else:
        fixer_model_switch = ModelSwitch()
        fixer_model_switch.select(fixer_model_name)

    failure_tracker = FailureTracker(max_attempts=2)

    # This function now represents a single attempt. It will be restarted.
    print(Fore.CYAN + "\n" + "=" * 20 + f" Running test: {test_id} " + "=" * 20)
    test_results = TestAutoFix.run_tests(test_patterns=[test_id], verbosity=args.verbosity)
    auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)

    if not auto_fix.error_details:
        print(Fore.GREEN + "\n🎉 Test passed! Fix was successful.")
        sys.exit(0)

    selected_error = auto_fix.error_details[0]

    if failure_tracker.has_exceeded_limit(selected_error):
        print(Fore.RED + "\nMax attempts reached for this test. Aborting fix.")
        sys.exit(1)

    failure_tracker.record_attempt(selected_error)
    attempt_count = failure_tracker.get_attempt_count(selected_error)
    print(Fore.CYAN + f"\n▶️ Test failed. Starting fix attempt {attempt_count}/2...")

    auto_fix.uniq_references = set()
    auto_fix.trace_log = ""
    auto_fix.display_selected_error_details(selected_error)

    if not auto_fix.uniq_references:
        print(Fore.YELLOW + "\nCould not find references in tracer log. Cannot fix automatically.")
        sys.exit(1)

    symbol_result = auto_fix.get_and_prioritize_symbols(fixer_model_switch)
    if not symbol_result:
        print(Fore.RED + "Could not build context. Cannot fix automatically.")
        sys.exit(1)

    # Inlined logic from _perform_direct_fix for non-interactive use
    prompt_content = FixerPromptGenerator.create_direct_fix_prompt(
        trace_log=auto_fix.trace_log, user_req=args.user_requirement
    )

    GPT_FLAGS[GPT_FLAG_PATCH] = True
    p = PatchPromptBuilder(
        use_patch=True, symbols=[], tokens_left=fixer_model_switch.current_config.max_context_size * 3
    )
    p.process_search_results(symbol_result)
    prompt = p.build(user_requirement=prompt_content)

    try:
        print(Fore.YELLOW + "正在生成修复方案...")
        text = fixer_model_switch.query(fixer_model_switch.model_name, prompt, stream=True)
        process_patch_response(text, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])
    except (ValueError, IndexError) as e:
        print(Fore.RED + f"\nError applying patch: {e}. Automated fix failed in isolated mode.")
        sys.exit(1)

    print(Fore.GREEN + "\nPatch applied. Restarting process to verify...")
    _restart_with_original_args()


def main():
    """Main entry point for test auto-fix functionality."""
    args = parse_args()

    # --- New Isolated Fix Workflow ---
    if args.single_test_id:
        # This script is running as a child process.
        run_single_test_fix_loop(args, args.single_test_id)
        return

    # Check for mutually exclusive WORKFLOW modes.
    active_workflows = [
        bool(args.auto_pilot),
        args.parallel_analysis is not None,
        args.parallel_autofix is not None,
        args.isolated_fix,
    ]
    if sum(active_workflows) > 1:
        print(
            Fore.RED
            + "Error: --auto-pilot, --parallel-analysis, --parallel-autofix, and --isolated-fix are mutually exclusive."
        )
        sys.exit(1)

    if args.lookup:
        file_path, line = args.lookup
        try:
            line_num = int(line)
            auto_fix = TestAutoFix({}, user_requirement=args.user_requirement)
            auto_fix.lookup_reference(file_path, line_num)
        except ValueError:
            print(Fore.RED + "Error: LINE must be a valid integer")
            sys.exit(1)
        return

    if args.list_tests:
        test_results = TestAutoFix.run_tests(
            test_patterns=args.test_patterns, verbosity=args.verbosity, list_tests=True
        )
        if "test_cases" in test_results:
            print("\nAvailable test cases:")
            for test_id in test_results["test_cases"]:
                print(test_id)
        return

    # --- Model setup ---
    fixer_model_name = args.model
    analyzer_model_name = args.analyzer_model if args.analyzer_model else fixer_model_name

    print(Fore.CYAN + f"\nUsing Analyzer Model: {analyzer_model_name}")
    print(Fore.CYAN + f"Using Fixer Model   : {fixer_model_name}" + Style.RESET_ALL)

    analyzer_model_switch = ModelSwitch()
    analyzer_model_switch.select(analyzer_model_name)

    if analyzer_model_name == fixer_model_name:
        fixer_model_switch = analyzer_model_switch
    else:
        fixer_model_switch = ModelSwitch()
        fixer_model_switch.select(fixer_model_name)
    # --- End model setup ---

    if args.isolated_fix:
        # This script is the parent process in isolated mode.
        run_isolated_fix_master(args)
    elif args.auto_pilot:
        run_auto_pilot_loop(args, analyzer_model_switch, fixer_model_switch)
    elif args.parallel_autofix is not None:
        run_parallel_autofix_workflow(args, analyzer_model_switch, fixer_model_switch)
    elif args.parallel_analysis is not None:
        run_parallel_analysis_workflow(args, analyzer_model_switch, fixer_model_switch)
    else:
        run_fix_loop(args, analyzer_model_switch, fixer_model_switch)


if __name__ == "__main__":
    main()
