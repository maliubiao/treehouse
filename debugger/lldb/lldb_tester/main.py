import argparse
import glob
import json
import locale
import logging
import os
import shutil
import subprocess
import sys
from typing import Dict

import lldb
from lldb_tester.core.discovery import ScriptLoader, TestFileFinder, TestFunctionFinder
from lldb_tester.core.executor import TestFunctionExecutor
from lldb_tester.core.models import TestResult, TestStatus
from lldb_tester.core.reporter import TestReporter


class LLDBTester:
    def __init__(self, config_file=None):
        self.config = self._load_config(config_file) if config_file else {}
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)
        self.reporter = TestReporter()
        logging.basicConfig(level=logging.INFO)

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        self.test_programs_dir = os.path.join(os.path.dirname(__file__), "test_programs")
        self.test_scripts_dir = os.path.join(os.path.dirname(__file__), "test_scripts")
        self.temp_files = []

    def _load_config(self, config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logging.error("Failed to load config file: %s", e)
            raise RuntimeError(f"Config file error: {e}") from e

    def run_tests(self, test_map: Dict[str, str], continue_on_failure: bool = False) -> int:
        """
        Orchestrates the test execution process.
        """
        for test_script, source_file in test_map.items():
            try:
                executable = self.compile_test_program(source_file)
                module = ScriptLoader.load_module_from_file(test_script)
                test_functions = TestFunctionFinder.find(module)

                if not test_functions:
                    result = TestResult(
                        name=os.path.basename(test_script),
                        status=TestStatus.ERROR,
                        duration=0,
                        message="No test functions (e.g., 'run_test' or 'test_*') found.",
                    )
                    self.reporter.add_result(result)
                    TestReporter.print_result(result)
                    if not continue_on_failure:
                        return 1
                    continue

                for func_name, test_func in test_functions:
                    full_test_name = f"{os.path.basename(test_script)}::{func_name}"
                    executor = TestFunctionExecutor(self.debugger, executable, full_test_name, test_func)
                    result = executor.run()

                    self.reporter.add_result(result)
                    TestReporter.print_result(result)

                    if result.status in (TestStatus.FAILED, TestStatus.ERROR) and not continue_on_failure:
                        logging.error("Aborting tests due to failure in %s", full_test_name)
                        self.reporter.print_summary()
                        return 1

            except Exception as e:
                result = TestResult(
                    name=os.path.basename(test_script),
                    status=TestStatus.ERROR,
                    duration=0,
                    message=f"Framework error: {str(e)}",
                )
                self.reporter.add_result(result)
                TestReporter.print_result(result)
                logging.error("Failed to run test script %s: %s", test_script, e, exc_info=True)
                if not continue_on_failure:
                    self.reporter.print_summary()
                    return 1

        self.reporter.print_summary()
        failed_or_error = any(r.status in (TestStatus.FAILED, TestStatus.ERROR) for r in self.reporter.results)
        return 1 if failed_or_error else 0

    def compile_test_program(self, source_path: str) -> str:
        """
        Compiles a C/C++ test program if it's outdated.
        """
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Test program source not found: {source_path}")

        executable = os.path.splitext(source_path)[0]
        dsym_dir = executable + ".dSYM"

        needs_compile = not os.path.exists(executable) or os.path.getmtime(source_path) > os.path.getmtime(executable)

        if needs_compile:
            if os.path.exists(executable):
                os.remove(executable)
            if os.path.exists(dsym_dir):
                shutil.rmtree(dsym_dir)

            compiler = "g++" if source_path.endswith(".cpp") else "gcc"
            cmd = [compiler, "-g", "-O0", source_path, "-o", executable]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if result.returncode != 0:
                raise RuntimeError(f"Compilation failed for {source_path}:\n{result.stderr}")
            print(f"Compiled: {source_path} -> {executable}")
        else:
            print(f"Using existing executable: {executable}")

        return executable

    def build_all_programs(self) -> int:
        """
        Compiles all found C/C++ test programs.
        """
        test_programs = glob.glob(os.path.join(self.test_programs_dir, "*.c")) + glob.glob(
            os.path.join(self.test_programs_dir, "*.cpp")
        )
        if not test_programs:
            print("No test programs found to build.", file=sys.stderr)
            return 1

        for program in test_programs:
            try:
                self.compile_test_program(program)
            except Exception as e:
                print(f"Failed to build {program}: {e}", file=sys.stderr)
                return 1
        return 0

    def cleanup(self):
        """
        Cleans up compiled artifacts, leaving source files intact.
        """
        # Clean known temporary files
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                if os.path.isdir(temp_file):
                    shutil.rmtree(temp_file)
                else:
                    os.remove(temp_file)
        self.temp_files = []

        # Clean all build artifacts in the test programs directory
        for root, dirs, files in os.walk(self.test_programs_dir):
            for file in files:
                if not (file.endswith(".c") or file.endswith(".cpp")):
                    file_path = os.path.join(root, file)
                    try:
                        if os.access(file_path, os.X_OK) and not os.path.isdir(file_path):
                            os.remove(file_path)
                            print(f"Removed executable: {file_path}")
                    except OSError:
                        pass  # Ignore permission errors etc.

            for dir_name in list(dirs):  # Iterate over a copy
                if dir_name.endswith(".dSYM"):
                    dir_path = os.path.join(root, dir_name)
                    shutil.rmtree(dir_path)
                    print(f"Removed dSYM directory: {dir_path}")
                    dirs.remove(dir_name)


def main():
    # Detect system language
    lang, _ = locale.getdefaultlocale()
    is_chinese = lang and lang.startswith("zh")

    parser = argparse.ArgumentParser(description="LLDB API 测试框架" if is_chinese else "LLDB API Test Framework")

    parser.add_argument("-c", "--config", help="配置文件路径" if is_chinese else "Path to config file")
    parser.add_argument("-t", "--test", help="运行指定测试文件" if is_chinese else "Run specific test file")
    parser.add_argument(
        "-p", "--pattern", default="test_*.py", help="测试文件匹配模式" if is_chinese else "Test file pattern"
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="失败时继续执行" if is_chinese else "Continue on test failure",
    )
    parser.add_argument(
        "--list-tests", action="store_true", help="列出可用测试" if is_chinese else "List available tests"
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="构建所有测试程序并退出" if is_chinese else "Build all test programs and exit",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="测试后清理构建产物" if is_chinese else "Clean up build artifacts after tests",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="启用详细日志" if is_chinese else "Enable verbose logging"
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s - %(levelname)s - %(message)s")

    tester = LLDBTester(args.config)

    if args.build:
        return tester.build_all_programs()

    if args.test:
        test_files = [args.test] if os.path.exists(args.test) else []
    else:
        test_files = TestFileFinder.discover_test_files(tester.test_scripts_dir, args.pattern)

    if args.list_tests:
        print("Available tests:")
        for test in test_files:
            print(f"  {test}")
        return 0

    if not test_files:
        print("No tests found.", file=sys.stderr)
        return 1

    test_map = TestFileFinder.map_tests_to_programs(test_files, tester.test_programs_dir)
    if not test_map:
        print("No valid test-program mappings found.", file=sys.stderr)
        return 1

    exit_code = tester.run_tests(test_map, args.continue_on_failure)

    if args.clean:
        print("Cleaning up build artifacts...")
        tester.cleanup()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
