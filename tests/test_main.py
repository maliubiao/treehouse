import argparse
import fnmatch
import inspect
import json
import os
import re
import sys
import time
import traceback
import unittest
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def parse_args():
    parser = argparse.ArgumentParser(description="Run unit tests with flexible selection")
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        choices=[0, 1, 2],
        default=1,
        help="Output verbosity (0=quiet, 1=default, 2=verbose)",
    )
    parser.add_argument(
        "test_patterns",
        nargs="*",
        default=None,
        help="Test selection patterns (e.g. +test_module*, -/exclude.*/, TestCase.test_method)",
    )
    parser.add_argument("--json", action="store_true", help="Output test results in JSON format")
    parser.add_argument(
        "--extract-errors",
        action="store_true",
        help="Extract error details in machine-readable format",
    )
    parser.add_argument(
        "--list-tests",
        action="store_true",
        help="List all available test cases without running them",
    )
    return parser.parse_args()


def add_gpt_path_to_syspath():
    gpt_path = os.getenv("GPT_PATH")
    if gpt_path and os.path.isdir(gpt_path):
        sys.path.insert(0, gpt_path)
        print(f"Added GPT_PATH to sys.path: {gpt_path}")


def compile_pattern(pattern):
    """Compile pattern to regex or glob matcher"""
    if pattern.startswith("/") and pattern.endswith("/"):
        # Regular expression pattern
        try:
            return re.compile(pattern[1:-1])
        except re.error as e:
            sys.stderr.write(f"Invalid regex pattern '{pattern}': {e}\n")
            sys.exit(1)
    else:
        # Glob pattern (convert to regex)
        regex = fnmatch.translate(pattern)
        return re.compile(regex)


def filter_tests(suite, patterns):
    """Filter test suite based on inclusion/exclusion patterns"""
    include_patterns = []
    exclude_patterns = []

    # Parse patterns into include/exclude lists
    for pattern in patterns:
        if pattern.startswith("-"):
            exclude_patterns.append(compile_pattern(pattern[1:]))
        else:
            if pattern.startswith("+"):
                pattern = pattern[1:]
            include_patterns.append(compile_pattern(pattern))

    # Create new filtered test suite
    filtered_suite = unittest.TestSuite()

    def should_include(test_id):
        """Check if test should be included based on patterns"""
        # If no include patterns, include by default
        included = not include_patterns
        for pattern in include_patterns:
            if pattern.search(test_id):
                included = True
                break

        # Check exclusion patterns
        for pattern in exclude_patterns:
            if pattern.search(test_id):
                return False

        return included

    # Recursively filter tests
    for test in suite:
        if isinstance(test, unittest.TestCase):
            test_id = test.id()
            if should_include(test_id):
                filtered_suite.addTest(test)
        elif isinstance(test, unittest.TestSuite):
            # Recursively filter sub-suites
            filtered_subsuite = filter_tests(test, patterns)
            if filtered_subsuite.countTestCases() > 0:
                filtered_suite.addTest(filtered_subsuite)

    return filtered_suite


class JSONTestResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.results = defaultdict(list)
        self.all_issues = []

    def startTest(self, test):
        super().startTest(test)
        self._start_at_time = time.time()

    def addSuccess(self, test):
        super().addSuccess(test)
        elapsed = time.time() - self._start_at_time
        print(f"\n{test.id()}: {elapsed:.3f}s")
        if elapsed > 0.1:
            self.all_issues.append(("timeout", test, f"Test {test.id()} took too long: {elapsed:.3f}s"))

    def addFailure(self, test, err):
        self._add_error_details(test, err, "failures")
        self.all_issues.append(("failure", test, err))

    def addError(self, test, err):
        self._add_error_details(test, err, "errors")
        self.all_issues.append(("error", test, err))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.all_issues.append(("skip", test, reason))

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.all_issues.append(("expected_failure", test, err))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.all_issues.append(("unexpected_success", test, None))

    def _get_test_start_line(self, test):
        """Get the first line number of the test method."""
        try:
            test_method = getattr(test, test._testMethodName)
            lines, start_line = inspect.getsourcelines(test_method)
            return start_line
        except (AttributeError, TypeError, OSError):
            return None

    def _add_error_details(self, test, err, category):
        test_id = test.id()
        if test_id.count(".") == 2:
            module, class_name, method_name = test_id.split(".")
            method = getattr(getattr(sys.modules[module], class_name), method_name)
        elif test_id.count(".") > 2:
            module, class_name, method_name = test_id.rsplit(".", 2)
            method = getattr(getattr(sys.modules[module], class_name), method_name)
        else:
            module, method_name = test_id.split(".")
            method = getattr(sys.modules[module], method_name)
        file_path = method.__code__.co_filename
        line = method.__code__.co_firstlineno
        func_name = method.__name__
        for i in reversed(traceback.extract_tb(err[-1])):
            if method_name == i.name:
                file_path = i.filename
                line = i._code.co_firstlineno
                func_name = i.name
                break
        tb = self._exc_info_to_string(err, test)
        # Use test method start line if available
        error_type = type(err[1]).__name__ if err[1] else "UnknownError"
        error_entry = {
            "test": str(test),
            "error_type": error_type,
            "error_message": str(err[1]) if err[1] else "Unknown error occurred",
            "traceback": tb,
            "file_path": file_path,
            "line": line,
            "function": func_name,
        }
        self.results[category].append(error_entry)
        if category == "failures":
            self.failures.append((test, self._exc_info_to_string(err, test)))
        elif category == "errors":
            self.errors.append((test, self._exc_info_to_string(err, test)))

    def _parse_test_id(self, test_id, err=None):
        parts = test_id.split(".")
        base_module = parts[0]

        if base_module.startswith("test_"):
            module_path = os.path.join("tests", f"{base_module}.py")
        else:
            module_path = base_module.replace(".", "/") + ".py"
            if os.path.exists(os.path.join("tests", module_path)):
                file_path = os.path.join("tests", module_path)
                return file_path
        return err[-1].tb_frame.f_code.co_filename, err[-1].tb_frame.f_lineno, err[-1].tb_frame.f_code.co_name

    def get_json_results(self):
        return {
            "total": self.testsRun,
            "success": self.testsRun - len(self.failures) - len(self.errors),
            "failures": len(self.failures),
            "errors": len(self.errors),
            "skipped": len(self.skipped),
            "expected_failures": len(self.expectedFailures),
            "unexpected_successes": len(self.unexpectedSuccesses),
            "results": dict(self.results),
            "all_issues": [
                {
                    "type": issue[0],
                    "test": str(issue[1]),
                    "details": str(issue[2]) if issue[2] else None,
                }
                for issue in self.all_issues
            ],
        }

    def get_error_details(self):
        error_details = []
        for category in ["errors", "failures"]:
            for error in self.results.get(category, []):
                error_details.append(
                    {
                        "file_path": error["file_path"],
                        "line": error["line"],
                        "function": error["function"],
                        "error_type": error["error_type"],
                        "error_message": error["error_message"],
                    }
                )
        return error_details


def run_tests(test_patterns=None, verbosity=1, json_output=False, extract_errors=False, list_mode=False):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    try:
        # Always discover all tests first
        discovered = loader.discover(start_dir="tests", pattern="test*.py")

        # Apply test filters if any patterns provided
        if test_patterns:
            suite = filter_tests(discovered, test_patterns)
        else:
            suite = discovered

        if list_mode:
            # Collect test case names without running
            test_cases = []

            def collect_test_ids(test_suite):
                """Recursively collect all test case IDs"""
                for test in test_suite:
                    if isinstance(test, unittest.TestCase):
                        test_cases.append(test.id())
                    elif isinstance(test, unittest.TestSuite):
                        collect_test_ids(test)

            collect_test_ids(suite)
            # Sort by name and output
            for test_id in sorted(test_cases):
                print(test_id)
            return {"test_cases": test_cases}

        if json_output:
            runner = unittest.TextTestRunner(verbosity=verbosity, resultclass=JSONTestResult)
            result = runner.run(suite)
            if extract_errors:
                return result.get_error_details()
            return result.get_json_results()
        else:
            runner = unittest.TextTestRunner(verbosity=verbosity)
            result = runner.run(suite)
            return result

    except (ImportError, AttributeError) as e:
        sys.stderr.write(f"\nERROR: {str(e)}\n")
        sys.stderr.write("Make sure test modules follow naming convention 'test_*.py'\n")
        raise
    except Exception as e:
        sys.stderr.write(f"\nCRITICAL ERROR: {str(e)}\n")
        raise


def main():
    add_gpt_path_to_syspath()
    args = parse_args()

    try:
        result = run_tests(
            test_patterns=args.test_patterns,
            verbosity=args.verbosity,
            json_output=args.json,
            extract_errors=args.extract_errors,
            list_mode=args.list_tests,
        )

        if args.json:
            print("capture error_details:")
            print(json.dumps(result, indent=2))

        exit_code = 0 if (isinstance(result, dict) or result.wasSuccessful()) else 1
        sys.exit(exit_code)
    except Exception:
        sys.exit(2)


if __name__ == "__main__":
    main()
