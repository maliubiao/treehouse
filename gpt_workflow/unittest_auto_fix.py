import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

from debugger import tracer
import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)
from llm_query import MatchResult, FileSearchResult, FileSearchResults
from llm_query import query_symbol_service, GLOBAL_MODEL_CONFIG


class TestAutoFix:
    def __init__(self, test_results: Dict):
        self.test_results = test_results
        self.error_details = self._extract_error_details()
        self.uniq_references = set()

    def _extract_error_details(self) -> List[Dict]:
        """Extract error details from test results in a structured format."""
        error_details = []

        if isinstance(self.test_results.get("results"), dict):
            for category in ["errors", "failures"]:
                for error in self.test_results.get("results", {}).get(category, []):
                    if isinstance(error, dict):
                        error_details.append(
                            {
                                "file_path": self._get_absolute_path(error.get("file_path", "unknown")),
                                "line": error.get("line"),
                                "function": error.get("function", "unknown"),
                                "error_type": error.get("error_type", "UnknownError"),
                                "error_message": error.get("error_message", "Unknown error"),
                                "traceback": error.get("traceback", ""),
                                "issue_type": category[:-1],  # removes 's' from 'errors'/'failures'
                            }
                        )

        return error_details

    def _get_absolute_path(self, file_path: str) -> str:
        """Convert relative path to absolute path."""
        if not file_path or file_path == "unknown":
            return file_path

        if os.path.isabs(file_path):
            return file_path
        return os.path.join(os.getcwd(), file_path)

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
        abs_path = self._get_absolute_path(file_path)
        print(Fore.CYAN + f"\nLooking up reference for: {abs_path}:{lineno}")
        self._display_tracer_logs(abs_path, lineno)

    def _display_tracer_logs(self, file_path: str, line: int) -> None:
        """Display relevant tracer logs for the error location."""
        log_extractor = tracer.TraceLogExtractor()
        try:
            logs, references_group = log_extractor.lookup(file_path, line)
            if logs:
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

    def get_symbol_info_for_references(self, ref_files: list, references: list) -> dict:
        """获取符号信息用于参考展示"""
        # 创建FileSearchResult对象
        file_results = []
        for filename, lineno in references:
            # 为每个引用创建MatchResult
            match_result = MatchResult(
                line=lineno,
                column_range=(0, 1),
                text="",  # 列信息未知时使用默认值  # 文本内容不需要
            )
            # 按文件分组结果
            file_result = next((fr for fr in file_results if fr.file_path == filename), None)
            if file_result:
                file_result.matches.append(match_result)
            else:
                file_results.append(FileSearchResult(file_path=filename, matches=[match_result]))

        # 创建FileSearchResults容器
        search_results = FileSearchResults(results=file_results)

        # 调用符号查询API
        symbol_results = query_symbol_service(search_results, GLOBAL_MODEL_CONFIG.max_context_size)

        # 构建符号字典
        symbol_dict = {}
        if symbol_results and isinstance(symbol_results, dict):
            print(Fore.BLUE + "\nSymbol Information:")
            print(Fore.BLUE + "-" * 30)
            for name, symbol in symbol_results.items():
                print(Fore.CYAN + f"Symbol: {name}")
                print(Fore.GREEN + f"start_line: {symbol['start_line']}")
                print(Fore.GREEN + f"end_line: {symbol['end_line']}")
                print(Fore.GREEN + f"code:\n{symbol['code']}")

        return symbol_results

    def get_error_context(self, file_path: str, line: int, context_lines: int = 5) -> Optional[List[str]]:
        """Get context around the error line from source file."""
        abs_path = self._get_absolute_path(file_path)
        if not os.path.exists(abs_path):
            return None

        with open(abs_path, "r") as f:
            lines = f.readlines()

        start = max(0, line - context_lines - 1)
        end = min(len(lines), line + context_lines)
        return [line.strip() for line in lines[start:end]]

    @staticmethod
    @tracer.trace(target_files=["*.py"])
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
        auto_fix.get_symbol_info_for_references([], list(auto_fix.uniq_references))


if __name__ == "__main__":
    main()
