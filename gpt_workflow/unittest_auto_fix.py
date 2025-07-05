import argparse
import concurrent.futures
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional
from unittest.mock import _Call

from colorama import Fore, Style
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

_Call.__repr__ = lambda self: f"<Call id={id(self)}>"  # type: ignore


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


def _reload_project_modules():
    """
    Unloads project-specific modules from sys.modules to force a reload.
    This is critical for re-running tests after a code patch has been applied,
    as Python's import system caches modules by default. It is especially
    important to reload test modules so that `unittest.mock.patch` decorators
    are re-applied to the newly-loaded application code.
    """
    project_module_prefixes = ("test_", "gpt_workflow", "debugger", "llm_query")

    modules_to_reload = [name for name in sys.modules if name.startswith(project_module_prefixes)]

    if modules_to_reload:
        print(Fore.CYAN + "\nReloading project modules to apply changes...")
        reloaded_count = 0
        for name in sorted(modules_to_reload):
            if name in sys.modules:
                del sys.modules[name]
                reloaded_count += 1
        print(Fore.BLUE + f"  Unloaded {reloaded_count} project modules to ensure a fresh state for the next test run.")


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
            self._display_tracer_logs(selected_error["file_path"], selected_error["line"], silent=silent)

    def lookup_reference(self, file_path: str, lineno: int) -> None:
        """Display reference information for a specific file and line."""
        self._display_tracer_logs(file_path, lineno)

    def _display_tracer_logs(self, file_path: str, line: int, silent: bool = False) -> None:
        """
        Display relevant tracer logs for the error location and identify the exception source.
        """
        from gpt_lib import graph_tracer

        fn = str(Path(__file__).parent.parent / "debugger/logs/run_all_tests.log")
        log_extractor = graph_tracer.GraphTraceLogExtractor(fn)
        log_extractor.export_trace_graph_text(
            graph_tracer.ROOT_FRAME_ID,
            Path(__file__).parent.parent / "debugger/logs/run_all_tests.graph.txt",
            show_full_trace=True,
        )
        # log_extractor = tracer.TraceLogExtractor(fn)
        try:
            logs, references_group = log_extractor.lookup(file_path, line, sibling_func=["setUp"])
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
        for name, symbol_data in all_symbols.items():
            content = symbol_data.get("code", "")
            tokens = len(content) // 3
            location_to_symbol_map[name] = {"name": name, "tokens": tokens, "data": symbol_data}

        # 4. Reconstruct the call stack at the point of exception
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

        # 5. Prioritize and build the final list of symbols
        final_symbols = {}
        added_symbol_names = set()
        current_tokens = 0

        # 5a. Add symbols from the call stack, deepest first
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

        # 5b. Fill remaining budget with other referenced symbols, smallest first
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


def _perform_direct_fix(auto_fix: TestAutoFix, symbol_result: dict, fixer_model_switch: ModelSwitch, user_req: str):
    """Performs a direct, one-step fix by analyzing the tracer log and generating a patch."""
    print(Fore.YELLOW + "\nAttempting to generate a fix directly...")

    if not user_req:
        user_req = "分析并解决用户遇到的问题，修复test_*符号中的错误"

    prompt_content = f"""
请根据以下tracer的报告, 分析问题原因并直接修复testcase相关问题。请以中文回复, 需要注意# Debug 后的取值反映了真实的运行数据。
用户的要求: {user_req}
[trace log start]
{auto_fix.trace_log}
[trace log end]
    """

    GPT_FLAGS[GPT_FLAG_PATCH] = True
    p = PatchPromptBuilder(
        use_patch=True, symbols=[], tokens_left=fixer_model_switch.current_config.max_context_size * 3
    )
    p.process_search_results(symbol_result)
    prompt = p.build(user_requirement=prompt_content)
    print(Fore.YELLOW + "正在生成修复方案...")
    text = fixer_model_switch.query(fixer_model_switch.model_name, prompt, stream=True)
    process_patch_response(text, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])


def _get_user_feedback_on_analysis(analysis_text: str) -> str:
    """
    Presents the AI's analysis to the user and asks for feedback on how to proceed with the fix.

    Returns:
        A string containing the user's directive for the fix, or an empty string to abort.
    """
    print(Fore.YELLOW + "\n" + "=" * 15 + " User Review and Direction " + "=" * 15)
    print(Fore.CYAN + "The AI has analyzed the issue. Please review its findings and provide direction for the fix.")
    print(Fore.YELLOW + "=" * 54)

    print(Fore.GREEN + "Please choose a course of action:")
    print(Fore.CYAN + "  1. Accept the analysis and proceed with the recommended fix.")
    print(Fore.CYAN + "  2. The analysis is correct, but I want to provide a specific instruction.")
    print(Fore.CYAN + "  3. The analysis seems wrong. I will provide a new direction.")
    print(Fore.CYAN + "  q. Quit the fix process.")

    while True:
        choice = input(Fore.GREEN + "Your choice (1/2/3/q): ").strip().lower()

        if choice == "1":
            return "按照上述技术专家的分析，解决用户遇到的问题，修复单元测试中的错误，使其能够成功通过。"
        elif choice == "2":
            user_instruction = input(Fore.GREEN + "Please provide your specific instruction: ").strip()
            if user_instruction:
                return user_instruction
            else:
                print(Fore.RED + "Instruction cannot be empty. Please try again.")
        elif choice == "3":
            user_instruction = input(Fore.GREEN + "Please describe the correct analysis and how to fix it: ").strip()
            if user_instruction:
                return user_instruction
            else:
                print(Fore.RED + "Direction cannot be empty. Please try again.")
        elif choice == "q":
            return ""  # Empty string signals to abort
        else:
            print(Fore.RED + "Invalid choice. Please enter 1, 2, 3, or q.")


def _perform_two_step_fix(
    auto_fix: TestAutoFix, symbol_result: dict, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch
):
    """
    Performs an interactive, two-step fix:
    1. Analyzes the failure and presents the analysis.
    2. Gets user feedback and direction.
    3. Generates a patch based on the analysis and user's final command.
    """
    print(Fore.YELLOW + "\nStep 1: Generating failure analysis...")
    print(Fore.CYAN + f"(Using Analyzer: {analyzer_model_switch.model_name})")

    # Load the specialized analysis prompt
    analyze_prompt_template = (Path(__file__).parent.parent / "prompts/unittest_analyze_failure.py.prompt").read_text(
        encoding="utf-8"
    )
    analyze_prompt_content = f"""
{analyze_prompt_template}
[trace log start]
{auto_fix.trace_log}
[trace log end]
"""
    p_explain = PatchPromptBuilder(
        use_patch=False, symbols=[], tokens_left=analyzer_model_switch.current_config.max_context_size * 3
    )
    p_explain.process_search_results(symbol_result)
    prompt_explain = p_explain.build(user_requirement=analyze_prompt_content)
    stream = analyzer_model_switch.query(analyzer_model_switch.model_name, prompt_explain, stream=True)
    analysis_text = _consume_stream_and_get_text(stream)

    # Step 2: Get user feedback on the analysis
    user_directive = _get_user_feedback_on_analysis(analysis_text)
    if not user_directive:
        print(Fore.RED + "User aborted the fix process.")
        return

    # Step 3: Generate the fix based on analysis and user directive
    print(Fore.YELLOW + "\nStep 2: Generating fix based on analysis and user directive...")
    print(Fore.CYAN + f"(Using Fixer: {fixer_model_switch.model_name})")
    fix_prompt_template = (Path(__file__).parent.parent / "prompts/unittest_generate_fix.py.prompt").read_text(
        encoding="utf-8"
    )
    fix_prompt_content = f"""
{fix_prompt_template}

[技术专家的分析报告]
{analysis_text}
[用户最终指令]
{user_directive}
[trace log start]
{auto_fix.trace_log}
[trace log end]
    """
    GPT_FLAGS[GPT_FLAG_PATCH] = True
    p_fix = PatchPromptBuilder(
        use_patch=True, symbols=[], tokens_left=fixer_model_switch.current_config.max_context_size * 3
    )
    p_fix.process_search_results(symbol_result)
    prompt_fix = p_fix.build(user_requirement=fix_prompt_content)

    text = fixer_model_switch.query(fixer_model_switch.model_name, prompt_fix, stream=True)
    process_patch_response(text, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])


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
    explain_prompt_template = (Path(__file__).parent.parent / "prompts/unittest_analyze_failure.py.prompt").read_text(
        encoding="utf-8"
    )
    explain_prompt_content = f"""
{explain_prompt_template}
请根据以下tracer的报告, 按照分析要求，解释问题的原因, 请以中文回复
[trace log start]
{auto_fix.trace_log}
[trace log end]
"""
    p_explain = PatchPromptBuilder(
        use_patch=False, symbols=[], tokens_left=analyzer_model_switch.current_config.max_context_size * 3
    )
    p_explain.process_search_results(symbol_result)
    prompt_explain = p_explain.build(user_requirement=explain_prompt_content)
    stream = analyzer_model_switch.query(analyzer_model_switch.model_name, prompt_explain, stream=True)
    analysis_text = _consume_stream_and_get_text(stream, print_stream=True)

    # Step 2: Prepare the fix prompt (which will also be in the report)
    user_req_for_fix = "按照专家建议，解决用户遇到的问题，修复test_*符号中的错误"
    fix_prompt_template = (Path(__file__).parent.parent / "prompts/unittest_generate_fix.py.prompt").read_text(
        encoding="utf-8"
    )
    fix_prompt_content = f"""
{fix_prompt_template}

[技术专家的分析报告]
{analysis_text}
[用户最终指令]
{user_req_for_fix}
[trace log start]
{auto_fix.trace_log}
[trace log end]
    """
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
    text_fix = fixer_model_switch.query(fixer_model_switch.model_name, prompt_fix, stream=True)
    process_patch_response(text_fix, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])


def run_fix_loop(args: argparse.Namespace, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch):
    """Main loop for interactive test fixing."""
    fix_mode = None

    if not args.direct_fix:
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

    while True:
        _reload_project_modules()
        print(Fore.CYAN + "\n" + "=" * 20 + " 开始新一轮测试 " + "=" * 20)
        test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
        auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)
        selected_error = auto_fix.select_error_interactive()

        if not selected_error:
            if not auto_fix.error_details:
                print(Fore.GREEN + "\n🎉 恭喜！所有测试均已通过。")
            else:
                print(Fore.RED + "\n用户选择退出修复流程。")
            break

        auto_fix.uniq_references = set()
        auto_fix.trace_log = ""
        auto_fix.display_selected_error_details(selected_error)

        if not auto_fix.uniq_references:
            print(Fore.YELLOW + "\n未找到错误的有效引用。无法自动修复，请手动检查。")
            continue_choice = input(Fore.GREEN + "\n是否返回列表选择其他问题或重新运行测试? (y/n): ").strip().lower()
            if continue_choice == "y":
                continue
            else:
                break

        symbol_result = auto_fix.get_and_prioritize_symbols(fixer_model_switch)

        if not symbol_result:
            print(Fore.RED + "无法构建修复上下文，跳过此问题。")
            continue

        if fix_mode == "direct":
            _perform_direct_fix(auto_fix, symbol_result, fixer_model_switch, args.user_requirement)
        elif fix_mode == "two_step":
            _perform_two_step_fix(auto_fix, symbol_result, analyzer_model_switch, fixer_model_switch)

        continue_choice = input(Fore.GREEN + "\n补丁已应用。是否继续修复下一个问题？ (y/n): ").strip().lower()
        if continue_choice != "y":
            print(Fore.RED + "用户选择退出修复流程。")
            break


def run_auto_pilot_loop(args: argparse.Namespace, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch):
    """Main loop for the fully automated test fixing and reporting workflow."""
    print(Fore.MAGENTA + "🚀 " + "=" * 20 + " Auto-Pilot Mode Engaged " + "=" * 20 + " 🚀")
    report_generator = ReportGenerator(report_dir=args.report_dir)
    failure_tracker = FailureTracker(max_attempts=2)

    while True:
        _reload_project_modules()
        print(Fore.CYAN + "\n" + "=" * 20 + " 开始新一轮测试 " + "=" * 20)
        test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
        auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)
        auto_fix._print_stats()

        if not auto_fix.error_details:
            print(Fore.GREEN + "\n🎉 恭喜！所有测试均已通过。Auto-Pilot完成任务。")
            break

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
            break

        failure_tracker.record_attempt(selected_error)
        attempt_count = failure_tracker.get_attempt_count(selected_error)
        print(Fore.CYAN + f"\n▶️ 开始处理错误 (第 {attempt_count}/2 次尝试):")

        auto_fix.uniq_references = set()
        auto_fix.trace_log = ""
        auto_fix.display_selected_error_details(selected_error)

        if not auto_fix.uniq_references:
            print(Fore.YELLOW + "\n未找到错误的有效引用，无法自动修复。跳过此错误。")
            continue

        symbol_result = auto_fix.get_and_prioritize_symbols(fixer_model_switch)
        if not symbol_result:
            print(Fore.RED + "无法构建修复上下文，跳过此问题。")
            continue

        _perform_automated_fix_and_report(
            auto_fix, selected_error, symbol_result, analyzer_model_switch, fixer_model_switch, report_generator
        )

        print(Fore.GREEN + "\n补丁已应用。将自动重新运行测试以验证修复效果...")


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
    analyze_prompt_template = (Path(__file__).parent.parent / "prompts/unittest_analyze_failure.py.prompt").read_text(
        encoding="utf-8"
    )
    analyze_prompt_content = f"""
{analyze_prompt_template}
[trace log start]
{auto_fix.trace_log}
[trace log end]
"""
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
    fix_prompt_template = (Path(__file__).parent.parent / "prompts/unittest_generate_fix.py.prompt").read_text(
        encoding="utf-8"
    )
    fix_prompt_content = f"""
{fix_prompt_template}

[技术专家的分析报告]
{analyzed_error.analysis_text}
[用户最终指令]
{user_directive}
[trace log start]
{analyzed_error.trace_log}
[trace log end]
    """
    GPT_FLAGS[GPT_FLAG_PATCH] = True
    p_fix = PatchPromptBuilder(
        use_patch=True, symbols=[], tokens_left=fixer_model_switch.current_config.max_context_size * 3
    )
    p_fix.process_search_results(analyzed_error.symbol_result)
    prompt_fix = p_fix.build(user_requirement=fix_prompt_content)

    text = fixer_model_switch.query(fixer_model_switch.model_name, prompt_fix, stream=True)
    process_patch_response(text, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])


def _perform_interactive_fix_from_analysis(analyzed_error: AnalyzedError, fixer_model_switch: ModelSwitch):
    """Takes a pre-analyzed error and walks the user through the fixing process."""
    # 1. Present the pre-computed analysis and get user feedback
    print(Fore.BLUE + "\n--- AI Analysis ---" + Style.RESET_ALL)
    print(analyzed_error.analysis_text)
    print(Fore.BLUE + "-------------------" + Style.RESET_ALL)

    user_directive = _get_user_feedback_on_analysis(analyzed_error.analysis_text)
    if not user_directive:
        print(Fore.RED + "User aborted the fix process.")
        return

    # 2. Generate the fix
    _generate_and_apply_patch_from_analysis(analyzed_error, user_directive, fixer_model_switch)


def run_parallel_analysis_workflow(
    args: argparse.Namespace, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch
):
    """Main loop for the parallel analysis, sequential fix workflow."""
    # This outer loop controls a full test-and-analyze cycle.
    run_new_cycle = True
    while run_new_cycle:
        # Default to exiting after this cycle, unless user chooses to continue.
        run_new_cycle = False

        _reload_project_modules()
        print(Fore.CYAN + "\n" + "=" * 20 + " 开始新一轮测试 " + "=" * 20)
        test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
        auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)
        auto_fix._print_stats()

        if not auto_fix.error_details:
            print(Fore.GREEN + "\n🎉 恭喜！所有测试均已通过。")
            break  # Exit the workflow entirely

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
            print(Fore.RED + "\nNo errors could be analyzed successfully. Re-running tests.")
            run_new_cycle = True
            continue  # Re-run the outer loop.

        # This inner loop allows fixing multiple issues from the same analysis batch.
        while successful_analyses:
            selected_analysis = select_analysis_to_fix_interactive(successful_analyses)

            if not selected_analysis:
                # User quit the selection menu ('q').
                print(Fore.YELLOW + "\nNo issue selected from the current batch.")
                user_choice = (
                    input(Fore.GREEN + "Do you want to re-run tests and start a new analysis cycle? (y/n): ")
                    .strip()
                    .lower()
                )
                if user_choice == "y":
                    run_new_cycle = True
                break  # Break inner loop, outer loop condition will be checked.

            _perform_interactive_fix_from_analysis(selected_analysis, fixer_model_switch)

            # Remove the issue that was just addressed
            successful_analyses.remove(selected_analysis)

            if not successful_analyses:
                print(Fore.GREEN + "\nAll analyzed issues from this batch have been addressed.")
                print(
                    Fore.CYAN + "The workflow will now re-run all tests to verify the fixes and check for new issues."
                )
                run_new_cycle = True
                break  # Inner loop terminates, outer loop will re-run.

            print(Fore.GREEN + "\nPatch applied. What would you like to do next?")
            print(Fore.CYAN + "  1. Fix another issue from the remaining list.")
            print(Fore.CYAN + "  2. Re-run all tests to start a new analysis cycle.")
            print(Fore.CYAN + "  q. Quit the workflow.")

            user_choice = ""
            while user_choice not in ["1", "2", "q"]:
                user_choice = input(Fore.GREEN + "Your choice (1/2/q): ").strip().lower()
                if user_choice not in ["1", "2", "q"]:
                    print(Fore.RED + "Invalid choice. Please enter 1, 2, or q.")

            if user_choice == "1":
                # User wants to continue with this batch.
                continue  # Continues the inner `while successful_analyses` loop
            elif user_choice == "2":
                # User wants to abandon this batch and start a new cycle.
                run_new_cycle = True
                break  # Breaks the inner loop
            elif user_choice == "q":
                # User wants to quit entirely.
                run_new_cycle = False  # Ensure we exit
                break  # Breaks the inner loop

    if not run_new_cycle:
        print(Fore.RED + "\nWorkflow finished.")


def run_parallel_autofix_workflow(
    args: argparse.Namespace, analyzer_model_switch: ModelSwitch, fixer_model_switch: ModelSwitch
):
    """Main loop for the parallel analysis and automated fix workflow."""
    print(Fore.MAGENTA + "🚀 " + "=" * 20 + " Parallel Auto-Fix Mode Engaged " + "=" * 20 + " 🚀")
    failure_tracker = FailureTracker(max_attempts=2)

    while True:
        _reload_project_modules()
        print(Fore.CYAN + "\n" + "=" * 20 + " 开始新一轮测试 " + "=" * 20)
        test_results = TestAutoFix.run_tests(test_patterns=args.test_patterns, verbosity=args.verbosity)
        auto_fix = TestAutoFix(test_results, user_requirement=args.user_requirement)
        auto_fix._print_stats()

        if not auto_fix.error_details:
            print(Fore.GREEN + "\n🎉 恭喜！所有测试均已通过。Parallel Auto-Fix完成任务。")
            break

        # Filter out errors that have exceeded the retry limit
        errors_to_analyze = [e for e in auto_fix.error_details if not failure_tracker.has_exceeded_limit(e)]

        if not errors_to_analyze:
            print(Fore.RED + "\n所有剩余错误已达到最大重试次数，无法继续自动修复。")
            skipped = failure_tracker.get_skipped_errors()
            print(Fore.YELLOW + f"被放弃的错误 ({len(skipped)}):")
            for i, (file_path, line) in enumerate(skipped):
                print(f"  {i + 1}. {file_path}:{line}")
            print(Fore.MAGENTA + "Parallel Auto-Fix 退出。")
            break

        # Run parallel analysis
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
            print(Fore.RED + "\nNo errors could be analyzed successfully. Re-running test cycle.")
            # Record an attempt for all errors we tried to analyze to prevent infinite loops on analysis failure
            for error in errors_to_analyze:
                failure_tracker.record_attempt(error)
            continue

        print(Fore.GREEN + f"\nAnalysis complete. Attempting to fix {len(successful_analyses)} issues sequentially.")

        # Sequentially apply fixes for all successfully analyzed errors
        for i, analyzed_error in enumerate(successful_analyses):
            error_detail = analyzed_error.error_detail
            func_name = error_detail.get("function", "unknown")
            failure_tracker.record_attempt(error_detail)  # Record attempt before trying to fix
            attempt_count = failure_tracker.get_attempt_count(error_detail)

            print(Fore.YELLOW + "\n" + "-" * 70)
            print(
                Fore.CYAN
                + f"Fixing issue {i + 1}/{len(successful_analyses)} in {func_name} (Attempt {attempt_count}/2)"
            )
            _consume_stream_and_get_text(iter([analyzed_error.analysis_text]), print_stream=True)

            # The default directive, same as choice '1' in interactive mode
            user_directive = "按照上述技术专家的分析，解决用户遇到的问题，修复单元测试中的错误，使其能够成功通过。"

            _generate_and_apply_patch_from_analysis(analyzed_error, user_directive, fixer_model_switch)
            print(Fore.GREEN + f"Patch applied for {func_name}.")

        print(Fore.CYAN + "\nAll patches from this batch have been applied. Re-running tests to verify...")


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

    while True:
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

        # Use a simple, direct, automated fix approach for the child process
        _perform_direct_fix(auto_fix, symbol_result, fixer_model_switch, args.user_requirement)

        print(Fore.GREEN + "\nPatch applied. Re-running test to verify...")


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
