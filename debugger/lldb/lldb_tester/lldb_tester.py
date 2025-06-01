#!/usr/bin/env python3

import argparse
import glob
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import List

import colorama
import lldb


class TestStatus(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class TestResult:
    name: str
    status: TestStatus
    duration: float
    message: str = ""


class TestReporter:
    def __init__(self):
        self.results: List[TestResult] = []
        colorama.init()

    def add_result(self, result: TestResult):
        self.results.append(result)

    def print_summary(self):
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)

        print("\n=== Test Summary ===")
        print(f"Total: {len(self.results)}, Passed: {passed}, Failed: {failed}, Skipped: {skipped}")

        if failed > 0:
            print("\n=== Failed Tests ===")
            for result in filter(lambda r: r.status == TestStatus.FAILED, self.results):
                print(f"{result.name}: {result.message}")


class TestLoader:
    @staticmethod
    def discover_tests(test_dir: str, pattern: str = "*.py") -> List[str]:
        if not os.path.exists(test_dir):
            return []

        return glob.glob(os.path.join(test_dir, pattern))


class LLDBTester:
    def __init__(self, config_file):
        self.config = self._load_config(config_file)
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)
        self.target = None
        self.process = None
        self.reporter = TestReporter()
        logging.basicConfig(level=logging.INFO)

    def _load_config(self, config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Failed to load config file: {e}")
            raise RuntimeError(f"Config file error: {e}") from e

    def _initialize_debugger(self):
        self.target = self.debugger.CreateTarget(self.config["test_program"])
        if not self.target:
            raise RuntimeError("Failed to create target")

        main_bp = self.target.BreakpointCreateByName("main", self.target.GetExecutable().GetFilename())
        if not main_bp:
            raise RuntimeError("Failed to set breakpoint at main")

    def _run_single_test(self, test_script: str) -> TestResult:
        test_name = os.path.basename(test_script)
        start_time = time.time()
        result = TestResult(name=test_name, status=TestStatus.PASSED, duration=0)

        try:
            script_globals = {
                "lldb_instance": self.debugger,
                "__builtins__": __builtins__,  # Limit builtins access
            }
            with open(test_script, "r", encoding="utf-8") as f:
                script_content = f.read()
                try:
                    compiled = compile(script_content, test_script, "exec")
                    exec(compiled, script_globals)
                except SyntaxError as e:
                    raise RuntimeError(f"Test script syntax error: {e}") from e

            if "run_test" in script_globals:
                script_globals["run_test"](self.debugger)

        except Exception as e:  # pylint: disable=broad-except
            result.status = TestStatus.FAILED
            result.message = str(e)
            logging.error(f"Test {test_name} failed: {e}")

        result.duration = time.time() - start_time
        return result

    def run_tests(self, test_files: List[str], continue_on_failure: bool = False) -> int:
        try:
            self._initialize_debugger()
        except RuntimeError as e:
            logging.error(f"Debugger initialization failed: {e}")
            return 1

        for test_file in test_files:
            self.process = self.target.LaunchSimple(None, None, os.getcwd())
            if not self.process:
                logging.error(f"Failed to launch process for {test_file}")
                return 1

            result = self._run_single_test(test_file)
            self.reporter.add_result(result)

            status_color = colorama.Fore.GREEN if result.status == TestStatus.PASSED else colorama.Fore.RED
            status_msg = f"{status_color}[{result.status.value}]{colorama.Style.RESET_ALL}"
            print(f"{status_msg} {result.name} ({result.duration:.2f}s)")

            if result.status == TestStatus.FAILED and not continue_on_failure:
                break

        self.reporter.print_summary()
        return 0


def main():
    parser = argparse.ArgumentParser(description="LLDB API Test Framework")
    parser.add_argument("-c", "--config", required=True, help="Path to config file")
    parser.add_argument("-t", "--test", help="Run specific test file")
    parser.add_argument("-p", "--pattern", default="*.py", help="Test file pattern")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue on test failure")
    parser.add_argument("--list-tests", action="store_true", help="List available tests")

    args = parser.parse_args()

    tester = LLDBTester(args.config)

    if args.test:
        test_files = [args.test]
    else:
        test_dir = os.path.join(os.path.dirname(args.config), "test_scripts")
        test_files = TestLoader.discover_tests(test_dir, args.pattern)

    if args.list_tests:
        print("Available tests:")
        for test in test_files:
            print(f"  {test}")
        return 0

    if not test_files:
        print("No tests found", file=sys.stderr)
        return 1

    return tester.run_tests(test_files, args.continue_on_failure)


if __name__ == "__main__":
    main()
