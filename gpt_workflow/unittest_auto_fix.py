import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import _Call

from colorama import Fore, Style
from report_generator import ReportGenerator

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
            color = Fore.RED if issue_type == "FAILURE" else Fore.YELLOW

            print(color + f"  {i + 1}: [{issue_type}] in {func_name} ({error_type})")
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

    def display_selected_error_details(self, selected_error: Dict) -> None:
        """
        Display detailed information for the selected test error, including traceback and tracer logs.
        This method populates `self.uniq_references` and `self.trace_log`.
        """
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
            self._display_tracer_logs(selected_error["file_path"], selected_error["line"])

    def lookup_reference(self, file_path: str, lineno: int) -> None:
        """Display reference information for a specific file and line."""

        self._display_tracer_logs(file_path, lineno)

    def _display_tracer_logs(self, file_path: str, line: int) -> None:
        """Display relevant tracer logs for the error location."""
        log_extractor = tracer.TraceLogExtractor(str(Path(__file__).parent.parent / "debugger/logs/run_all_tests.log"))
        try:
            logs, references_group = log_extractor.lookup(file_path, line)
            if logs:
                self.trace_log = logs[0]
                print(Fore.BLUE + "\nTracer Logs:")
                print(Fore.BLUE + "-" * 30)
                print(Fore.BLUE + f"{logs[0]}" + Style.RESET_ALL)

                for references in references_group:
                    print(Fore.BLUE + "\nCall Chain References:")
                    indent_level = 0
                    for ref in references:
                        if ref.get("type") == "call":
                            self.uniq_references.add((ref.get("filename", "?"), ref.get("lineno", 0)))
                            print(
                                Fore.CYAN
                                + "  " * indent_level
                                + f"→ {ref.get('func', '?')}() at {ref.get('filename', '?')}:{ref.get('lineno', '?')}"
                            )
                            indent_level += 1
                        elif ref.get("type") == "return":
                            indent_level = max(0, indent_level - 1)
                            print(Fore.GREEN + "  " * indent_level + f"← {ref.get('func', '?')}() returned")
                        elif ref.get("type") == "exception":
                            indent_level = max(0, indent_level - 1)
                            print(Fore.RED + "  " * indent_level + f"✗ {ref.get('func', '?')}() raised exception")
            else:
                print(Fore.YELLOW + f"\nNo tracer logs found for this location, {file_path}:{line}")
        except (FileNotFoundError, PermissionError, ValueError) as e:
            print(Fore.RED + f"\nFailed to extract tracer logs: {str(e)}")

    def get_symbol_info_for_references(self, references: list) -> dict:
        """获取符号信息用于参考展示"""
        file_to_lines = defaultdict(list)
        for filename, lineno in references:
            file_to_lines[filename].append(lineno)
        file_results = []
        for filename, lines in file_to_lines.items():
            matches = [MatchResult(line=lineno, column_range=(0, 0), text="") for lineno in lines]
            file_results.append(FileSearchResult(file_path=filename, matches=matches))

        search_results = FileSearchResults(results=file_results)
        symbol_results = query_symbol_service(search_results, 128 * 1024)

        if symbol_results and isinstance(symbol_results, dict):
            print(Fore.BLUE + "\nSymbol Information:")
            print(Fore.BLUE + "-" * 30)
            for name, symbol in symbol_results.items():
                print(Fore.CYAN + f"Symbol: {name}")
                print(Fore.BLUE + f"  File: {symbol['file_path']}:{symbol['start_line']}-{symbol['end_line']}")

        return symbol_results

    @staticmethod
    @tracer.trace(
        target_files=["*.py"],
        enable_var_trace=True,
        report_name="run_all_tests.html",
        ignore_self=False,
        ignore_system_paths=True,
        disable_html=True,
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
        "--model", default="deepseek-r1", help="Specify the language model to use (e.g., deepseek-r1, gpt-4, etc.)"
    )
    parser.add_argument(
        "--direct-fix", action="store_true", help="Directly generate a fix without the interactive explanation step."
    )
    parser.add_argument(
        "--auto-pilot", action="store_true", help="Enable fully automated regression analysis and fix mode."
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


def _perform_direct_fix(auto_fix: TestAutoFix, symbol_result: dict, model_switch: ModelSwitch, user_req: str):
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
    p = PatchPromptBuilder(use_patch=True, symbols=[], tokens_left=model_switch.current_config.max_context_size)
    p.process_search_results(symbol_result)
    prompt = p.build(user_requirement=prompt_content)
    print(Fore.YELLOW + "正在生成修复方案...")
    text = model_switch.query(model_switch.model_name, prompt, stream=True)
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


def _perform_two_step_fix(auto_fix: TestAutoFix, symbol_result: dict, model_switch: ModelSwitch):
    """
    Performs an interactive, two-step fix:
    1. Analyzes the failure and presents the analysis.
    2. Gets user feedback and direction.
    3. Generates a patch based on the analysis and user's final command.
    """
    print(Fore.YELLOW + "\nStep 1: Generating failure analysis...")

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
        use_patch=False, symbols=[], tokens_left=model_switch.current_config.max_context_size
    )
    p_explain.process_search_results(symbol_result)
    prompt_explain = p_explain.build(user_requirement=analyze_prompt_content)
    stream = model_switch.query(model_switch.model_name, prompt_explain, stream=True)
    analysis_text = _consume_stream_and_get_text(stream)

    # Step 2: Get user feedback on the analysis
    user_directive = _get_user_feedback_on_analysis(analysis_text)
    if not user_directive:
        print(Fore.RED + "User aborted the fix process.")
        return

    # Step 3: Generate the fix based on analysis and user directive
    print(Fore.YELLOW + "\nStep 2: Generating fix based on analysis and user directive...")
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
    p_fix = PatchPromptBuilder(use_patch=True, symbols=[], tokens_left=model_switch.current_config.max_context_size)
    p_fix.process_search_results(symbol_result)
    prompt_fix = p_fix.build(user_requirement=fix_prompt_content)

    text = model_switch.query(model_switch.model_name, prompt_fix, stream=True)
    process_patch_response(text, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])


def _perform_automated_fix_and_report(
    auto_fix: TestAutoFix,
    selected_error: dict,
    symbol_result: dict,
    model_switch: ModelSwitch,
    report_generator: ReportGenerator,
):
    """Analyzes an error, generates a report, and applies a fix in auto-pilot mode."""
    print(Fore.YELLOW + "Generating problem analysis for report...")

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
        use_patch=False, symbols=[], tokens_left=model_switch.current_config.max_context_size
    )
    p_explain.process_search_results(symbol_result)
    prompt_explain = p_explain.build(user_requirement=explain_prompt_content)
    stream = model_switch.query(model_switch.model_name, prompt_explain, stream=True)
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
    p_fix = PatchPromptBuilder(use_patch=True, symbols=[], tokens_left=model_switch.current_config.max_context_size)
    p_fix.process_search_results(symbol_result)
    prompt_fix = p_fix.build(user_requirement=fix_prompt_content)

    # Step 3: Generate and save the report
    report_path = report_generator.create_report(test_info=selected_error, analysis=analysis_text, prompt=prompt_fix)
    print(Fore.GREEN + f"Analysis report saved to: {report_path}")

    # Step 4: Generate and apply the fix
    print(Fore.YELLOW + "Generating and applying fix...")
    text_fix = model_switch.query(model_switch.model_name, prompt_fix, stream=True)
    process_patch_response(text_fix, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])


def run_fix_loop(args: argparse.Namespace):
    """Main loop for interactive test fixing."""
    model_switch = ModelSwitch()
    model_switch.select(args.model)
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

        symbol_result = auto_fix.get_symbol_info_for_references(list(auto_fix.uniq_references))

        if fix_mode == "direct":
            _perform_direct_fix(auto_fix, symbol_result, model_switch, args.user_requirement)
        elif fix_mode == "two_step":
            _perform_two_step_fix(auto_fix, symbol_result, model_switch)

        continue_choice = input(Fore.GREEN + "\n补丁已应用。是否继续修复下一个问题？ (y/n): ").strip().lower()
        if continue_choice != "y":
            print(Fore.RED + "用户选择退出修复流程。")
            break


def run_auto_pilot_loop(args: argparse.Namespace):
    """Main loop for the fully automated test fixing and reporting workflow."""
    print(Fore.MAGENTA + "🚀 " + "=" * 20 + " Auto-Pilot Mode Engaged " + "=" * 20 + " 🚀")
    model_switch = ModelSwitch()
    model_switch.select(args.model)
    report_generator = ReportGenerator()
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

        symbol_result = auto_fix.get_symbol_info_for_references(list(auto_fix.uniq_references))
        _perform_automated_fix_and_report(auto_fix, selected_error, symbol_result, model_switch, report_generator)

        print(Fore.GREEN + "\n补丁已应用。将自动重新运行测试以验证修复效果...")


def main():
    """Main entry point for test auto-fix functionality."""
    args = parse_args()

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

    if args.auto_pilot:
        run_auto_pilot_loop(args)
    else:
        run_fix_loop(args)


if __name__ == "__main__":
    main()
