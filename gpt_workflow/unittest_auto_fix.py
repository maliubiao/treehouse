import argparse
import sys
from typing import Dict, List, Optional, Tuple

from debugger import tracer
import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)
from llm_query import MatchResult, FileSearchResult, FileSearchResults
from llm_query import query_symbol_service, GLOBAL_MODEL_CONFIG
from collections import defaultdict
from pathlib import Path
from llm_query import (
    PatchPromptBuilder,
    GPT_FLAGS,
    GPT_FLAG_PATCH,
    ModelSwitch,
    process_patch_response,
    GPT_VALUE_STORAGE,
    GPT_SYMBOL_PATCH,
)
from textwrap import dedent


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
                        # 添加文件存在性检查
                        file_path = error.get("file_path", "unknown")
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

    def display_errors(self, references: List[Tuple[str, int]] = None) -> None:
        """Display test errors in a user-friendly format with optional references."""
        self._print_stats()

        if not self.error_details:
            print(Fore.GREEN + "\nNo test issues found!")
            return

        print(Fore.YELLOW + "\nTest Issues Details:")
        print(Fore.YELLOW + "=" * 50)
        for i, error in enumerate(self.error_details, 1):
            print(Fore.RED + f"\nIssue #{i} ({error.get('issue_type', 'unknown')}):")
            print(Fore.CYAN + f"File: {error['file_path']}")
            print(Fore.CYAN + f"Line: {error['line']}")
            print(Fore.CYAN + f"Function: {error['function']}")
            print(Fore.MAGENTA + f"Type: {error['error_type']}")
            print(Fore.MAGENTA + f"Message: {error['error_message']}")
            if error.get("traceback"):
                print(Fore.YELLOW + "\nTraceback:")
                print(Fore.YELLOW + "-" * 30)
                print(Fore.RED + error["traceback"])
                print(Fore.YELLOW + "-" * 30)

            # Display references if provided
            if references:
                print(Fore.BLUE + "\nRelated References:")
                print(Fore.BLUE + "-" * 30)
                for ref_file, ref_line in references:
                    print(Fore.CYAN + f"→ {ref_file}:{ref_line}")

            # Add tracer log analysis
            if error.get("file_path") and error.get("line"):
                self._display_tracer_logs(error["file_path"], error["line"])

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
                    # 获取符号信息

                    for ref in references:
                        # 在符号字典中查找匹配信息
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
        except Exception as e:
            print(Fore.RED + f"\nFailed to extract tracer logs: {str(e)}")

    @tracer.trace(target_files=["*.py"], enable_var_trace=True, report_name="get_symbol_info_for_references.html")
    def get_symbol_info_for_references(self, ref_files: list, references: list) -> dict:
        """获取符号信息用于参考展示"""
        # 按filename分组建立映射
        file_to_lines = defaultdict(list)
        for filename, lineno in references:
            file_to_lines[filename].append(lineno)
        # 创建分组后的FileSearchResult对象
        file_results = []
        for filename, lines in file_to_lines.items():
            # 为每个行号创建MatchResult
            matches = [
                MatchResult(
                    line=lineno,
                    column_range=(0, 0),
                    text="",  # 列信息未知时使用默认值
                )
                for lineno in lines
            ]
            file_results.append(FileSearchResult(file_path=filename, matches=matches))

        # 创建FileSearchResults容器
        search_results = FileSearchResults(results=file_results)

        # 调用符号查询API
        symbol_results = query_symbol_service(search_results, GLOBAL_MODEL_CONFIG.max_context_size)

        # 构建符号字典
        if symbol_results and isinstance(symbol_results, dict):
            print(Fore.BLUE + "\nSymbol Information:")
            print(Fore.BLUE + "-" * 30)
            for name, symbol in symbol_results.items():
                print(Fore.CYAN + f"Symbol: {name}")
                print(Fore.BLUE + f"start_line: {symbol['start_line']}")
                print(Fore.BLUE + f"end_line: {symbol['end_line']}")
                print(Fore.GREEN + f"code:\n{symbol['code']}")

        return symbol_results

    def get_error_context(self, file_path: str, line: int, context_lines: int = 5) -> Optional[List[str]]:
        """Get context around the error line from source file."""

        with open(file_path, "r") as f:
            lines = f.readlines()

        start = max(0, line - context_lines - 1)
        end = min(len(lines), line + context_lines)
        return [line.strip() for line in lines[start:end]]

    @staticmethod
    @tracer.trace(target_files=["*.py"], enable_var_trace=True, report_name="run_all_tests.html")
    def run_tests(testcase: Optional[str] = None) -> Dict:
        """Run tests and return results in JSON format."""
        from tests.test_main import run_tests

        return run_tests(test_name=testcase, json_output=True)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Test auto-fix tool")
    parser.add_argument(
        "--testcase",
        help="Run specific test case (format: TestCase.test_method). If not provided, runs all tests",
    )
    parser.add_argument(
        "--lookup",
        nargs=2,
        metavar=("FILE", "LINE"),
        help="Lookup reference information for specific file and line number",
    )
    parser.add_argument("--user-requirement", help="User's specific requirements to be added to the prompt", default="")
    return parser.parse_args()


def main():
    """Main entry point for test auto-fix functionality."""
    args = parse_args()

    if args.lookup:
        file_path, line = args.lookup
        try:
            line_num = int(line)
            auto_fix = TestAutoFix({})
            auto_fix.lookup_reference(file_path, line_num)
        except ValueError:
            print(Fore.RED + "Error: LINE must be a valid integer")
            sys.exit(1)
    else:
        test_results = TestAutoFix.run_tests(args.testcase)
        auto_fix = TestAutoFix(test_results)
        auto_fix.display_errors()
        if not auto_fix.uniq_references:
            print(Fore.GREEN + "\nNo references found for the test issues.")
            return
        symbol_result = auto_fix.get_symbol_info_for_references([], list(auto_fix.uniq_references))

        # 用户交互界面
        print(Fore.YELLOW + "\n是否继续生成修复建议？")
        print(Fore.CYAN + "1. 解释问题的原因")
        print(Fore.CYAN + "2. 放弃并退出")
        choice = input(Fore.GREEN + "请选择 (1/2): ").strip()
        if choice == "2":
            print(Fore.RED + "退出程序")
            return
        elif choice != "1":
            print(Fore.RED + "无效的选择，退出程序")
            return
        print(Fore.YELLOW + "正在生成修复建议...")
        user_requirement = (Path(__file__).parent.parent / "prompts/tracer").read_text(encoding="utf-8")
        user_requirement += f"""
请根据以下tracer的报告, 按照分析要求，解释问题的原因, 请以中文回复
[trace log start]
{auto_fix.trace_log}
[trace log end]
"""
        p = PatchPromptBuilder(use_patch=False, symbols=[])
        p.process_search_results(symbol_result)
        prompt = p.build(user_requirement=user_requirement)
        print(prompt)
        explain_text = ModelSwitch().query_for_text("coder", prompt, stream=True)
        try:
            user_requirement = (
                input(Fore.GREEN + "请输入测试的目的（或按回车键跳过）: ")
                .encode("utf-8", errors="ignore")
                .decode("utf-8")
                .strip()
            )
        except Exception:
            user_requirement = (
                input(Fore.GREEN + "请输入测试的目的（或按回车键跳过）: ")
                .encode("latin1")
                .decode("utf-8", errors="ignore")
                .strip()
            )
        if not user_requirement:
            user_requirement = "按照专家建议，解决用户遇到的问题"
        GPT_FLAGS[GPT_FLAG_PATCH] = True
        p = PatchPromptBuilder(use_patch=True, symbols=[])
        p.process_search_results(symbol_result)
        prompt_content = f"""
请根据以下tracer的报告, 修复testcase相关问题, 请以中文回复, 需要注意# Debug 后的取值反映了真实的运行数据
技术专家的分析:
{explain_text}
用户的要求: {user_requirement}
[trace log start]
{auto_fix.trace_log}
[trace log end]
        """

        prompt = p.build(user_requirement=prompt_content)
        print(prompt)
        text = ModelSwitch().query_for_text("coder", prompt, stream=True)
        process_patch_response(text, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
