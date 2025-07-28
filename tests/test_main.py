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
from typing import (
    Any,
    DefaultDict,
    Dict,
    List,
    Optional,
    Pattern,
    Set,
    Tuple,
    Union,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Global cache to store source information of tests before they run.
# This helps to locate test source even if methods are mocked during execution.
TEST_SOURCE_INFO_CACHE: Dict[str, Dict[str, Any]] = {}


def is_lldb_available() -> bool:
    """Check if the lldb module is available."""
    try:
        import lldb  # type: ignore

        # A simple check to see if it's a real lldb, not a mock
        return hasattr(lldb, "SBDebugger")
    except (ImportError, ModuleNotFoundError):
        return False


def parse_args() -> argparse.Namespace:
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


def add_gpt_path_to_syspath() -> None:
    gpt_path = os.getenv("GPT_PATH")
    if gpt_path and os.path.isdir(gpt_path):
        sys.path.insert(0, gpt_path)
        print(f"Added GPT_PATH to sys.path: {gpt_path}")


def _cache_test_source_info(suite: unittest.TestSuite) -> None:
    """
    Iteratively traverse the test suite and cache source file and line number
    for each test case. This is done before tests are run to ensure we can
    locate the original source code, even if methods are mocked or decorated.
    """
    stack: List[Union[unittest.TestSuite, unittest.TestCase]] = [suite]
    while stack:
        current_suite_or_test = stack.pop()
        if isinstance(current_suite_or_test, unittest.TestCase):
            test = current_suite_or_test
            test_id = test.id()
            if test_id in TEST_SOURCE_INFO_CACHE:
                continue
            try:
                test_method_obj = getattr(test, test._testMethodName)

                # Use inspect.unwrap to get to the original function,
                # bypassing decorators like @mock.patch.
                original_func = inspect.unwrap(test_method_obj)

                # Now get source info from the unwrapped function object.
                file_path = inspect.getsourcefile(original_func)
                if not file_path:
                    continue  # Cannot determine file path

                _, line_no = inspect.getsourcelines(original_func)
                func_name = original_func.__name__

                TEST_SOURCE_INFO_CACHE[test_id] = {
                    "file_path": os.path.abspath(file_path),
                    "line": line_no,
                    "function": func_name,
                }
            except (AttributeError, TypeError, OSError, inspect.Error):
                # This can fail for various reasons (e.g., dynamically generated tests),
                # so we silently pass. The fallback in _collect_error_details will handle it.
                pass
        elif isinstance(current_suite_or_test, unittest.TestSuite):
            # Add tests from the suite to the stack to be processed.
            # We add them in reverse to maintain the original execution order.
            stack.extend(reversed(list(current_suite_or_test)))


def compile_pattern(pattern: str) -> Pattern[str]:
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


def filter_tests(suite: unittest.TestSuite, patterns: List[str]) -> unittest.TestSuite:
    """Filter test suite based on inclusion/exclusion patterns using an iterative approach."""
    include_patterns: List[Pattern[str]] = []
    exclude_patterns: List[Pattern[str]] = []

    # Parse patterns into include/exclude lists
    for pattern in patterns:
        if pattern.startswith("-"):
            exclude_patterns.append(compile_pattern(pattern[1:]))
        else:
            if pattern.startswith("+"):
                pattern = pattern[1:]
            include_patterns.append(compile_pattern(pattern))

    def should_include(test_id: str) -> bool:
        """Check if test should be included based on patterns"""
        # If no include patterns, include by default
        included = not include_patterns
        for p in include_patterns:
            if p.search(test_id):
                included = True
                break

        if not included:
            return False

        # Check exclusion patterns
        for p in exclude_patterns:
            if p.search(test_id):
                return False

        return True

    filtered_suite = unittest.TestSuite()
    all_test_cases: List[unittest.TestCase] = []

    # Iteratively flatten the suite to get all test cases
    stack: List[Union[unittest.TestSuite, unittest.TestCase]] = [suite]
    processed_suites: Set[int] = set()

    while stack:
        current = stack.pop()
        if id(current) in processed_suites:
            continue
        if isinstance(current, unittest.TestSuite):
            processed_suites.add(id(current))
            # Add contained tests to the stack for processing, in reverse to maintain order
            stack.extend(reversed(list(current)))
        elif isinstance(current, unittest.TestCase):
            all_test_cases.append(current)

    # Filter the flattened list of test cases
    for test in all_test_cases:
        if should_include(test.id()):
            filtered_suite.addTest(test)

    return filtered_suite


class JSONTestResult(unittest.TextTestResult):
    """
    A test result class that collects results in a machine-readable JSON format.
    It is designed to be robust, especially against errors in setUp/tearDown.
    """

    def __init__(self, stream: Any, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.results: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.all_issues: List[Dict[str, Any]] = []
        self._test_start_times: Dict[str, float] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        self._test_start_times[test.id()] = time.time()
        super().startTest(test)

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        elapsed = time.time() - self._test_start_times.get(test.id(), time.time())
        # A simple check for slow tests, changed from "timeout" for clarity.
        if elapsed > 0.1:
            self.all_issues.append(
                {
                    "type": "slow_test",
                    "test": str(test),
                    "details": f"Test execution was slow: {test.id()} took {elapsed:.3f}s",
                }
            )

    def addFailure(self, test: unittest.TestCase, err: Tuple[Any, Any, Any]) -> None:
        super().addFailure(test, err)
        self._collect_error_details(test, err, "failures")

    def addError(self, test: unittest.TestCase, err: Tuple[Any, Any, Any]) -> None:
        super().addError(test, err)
        self._collect_error_details(test, err, "errors")

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self.all_issues.append({"type": "skip", "test": str(test), "details": reason})

    def addExpectedFailure(self, test: unittest.TestCase, err: Tuple[Any, Any, Any]) -> None:
        super().addExpectedFailure(test, err)
        tb_string = self._exc_info_to_string(err, test)
        self.all_issues.append({"type": "expected_failure", "test": str(test), "details": tb_string})

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self.all_issues.append({"type": "unexpected_success", "test": str(test), "details": None})

    def addSubTest(
        self,
        test: unittest.TestCase,
        sub_test: unittest.TestCase,
        err: Optional[Tuple[Any, Any, Any]],
    ) -> None:
        """
        Called when a subtest finishes. This is a custom implementation
        to ensure subtest failures are routed through our detailed JSON
        reporting logic.
        """
        if err is not None:
            # The base TestResult.addSubTest appends to self.failures/errors
            # but does not call the addFailure/addError hooks. We want to
            # call those hooks to trigger our JSON reporting logic.
            if issubclass(err[0], test.failureException):
                self.addFailure(sub_test, err)
            else:
                self.addError(sub_test, err)
        else:
            # For successful subtests, the default behavior (from TextTestResult)
            # which handles verbose printing is sufficient.
            super().addSubTest(test, sub_test, err)

    def _collect_error_details(self, test: unittest.TestCase, err: Tuple[Any, Any, Any], category: str) -> None:
        """
        Robustly collects details about an error or failure.

        It prioritizes locating the source of the test case itself using
        pre-cached metadata. If that fails, it intelligently walks the traceback
        to find the test function, which is far more reliable than just taking
        the innermost frame of the stack.
        """
        try:
            test_id = test.id()
            tb_string = self._exc_info_to_string(err, test)
            err_type, err_value, err_tb = err

            error_type_name = err_type.__name__ if hasattr(err_type, "__name__") else "UnknownError"
            error_message = str(err_value)

            # --- Collect full stack trace and prepare for location finding ---
            frame_ref_lines: List[Tuple[str, int]] = []
            tb_frames = None
            if err_tb:
                tb_frames = traceback.extract_tb(err_tb)
                if tb_frames:
                    frame_ref_lines = [(frame.filename, frame.lineno) for frame in tb_frames]

            # --- Robust location finding logic ---
            file_path, line, func_name = "Unknown", 0, test_id

            # For subtests, the test object is a `_SubTest` wrapper which has a
            # `test_case` attribute pointing to the parent TestCase. We must use the
            # parent's ID to look up the pre-cached source information.
            base_test_id = getattr(test, "test_case", test).id()

            # 1. Use the cached test definition location as the primary source of truth.
            if base_test_id in TEST_SOURCE_INFO_CACHE:
                cached_info = TEST_SOURCE_INFO_CACHE[base_test_id]
                file_path = cached_info["file_path"]
                line = cached_info["line"]
                func_name = cached_info["function"]

            # 2. Fallback: If not cached, walk the traceback to find the test function.
            #    This is more reliable than using the innermost frame, which could be
            #    a library or helper function deep in the call stack.
            elif tb_frames:
                found_test_frame = False
                # Iterate from the site of the error backwards up the call stack.
                for frame in reversed(tb_frames):
                    # Use a heuristic: unittest methods are typically named 'test*'.
                    # This helps pinpoint the test function itself.
                    if frame.name.startswith("test"):
                        file_path = frame.filename
                        line = frame.lineno
                        func_name = frame.name
                        found_test_frame = True
                        break  # Found the most likely frame, stop searching.

                # If the heuristic fails, fall back to the innermost frame as a last resort.
                if not found_test_frame:
                    frame_to_report = tb_frames[-1]
                    file_path = frame_to_report.filename
                    line = frame_to_report.lineno
                    func_name = frame_to_report.name

            # 3. Ensure file path is absolute for consistency.
            if file_path and file_path != "Unknown" and not os.path.isabs(file_path):
                file_path = os.path.abspath(file_path)

            error_entry: Dict[str, Any] = {
                "test": str(test),
                "test_id": test_id,
                "error_type": error_type_name,
                "error_message": error_message,
                "traceback": tb_string,
                "file_path": file_path,
                "line": line,
                "function": func_name,
                "frame_ref_lines": frame_ref_lines,
            }
            self.results[category].append(error_entry)
            self.all_issues.append({"type": category.rstrip("s"), "test": str(test), "details": tb_string})

        except Exception as e:
            # Failsafe: if our own error reporting fails, record a generic error.
            internal_error_details = (
                f"INTERNAL ERROR in JSONTestResult._collect_error_details: {e}\n"
                f"{traceback.format_exc()}\n"
                "--- Original Error Traceback ---\n"
                f"{self._exc_info_to_string(err, test)}"
            )
            self.results["internal_errors"].append(
                {
                    "test_id": test.id() if hasattr(test, "id") else "unknown_test",
                    "details": internal_error_details,
                }
            )
            self.all_issues.append({"type": "internal_error", "test": str(test), "details": internal_error_details})

    def get_json_results(self) -> Dict[str, Any]:
        return {
            "total": self.testsRun,
            "success": self.testsRun - len(self.failures) - len(self.errors),
            "failures": len(self.failures),
            "errors": len(self.errors),
            "skipped": len(self.skipped),
            "expected_failures": len(self.expectedFailures),
            "unexpected_successes": len(self.unexpectedSuccesses),
            "results": dict(self.results),
            "all_issues": self.all_issues,
        }

    def get_error_details(self) -> List[Dict[str, Any]]:
        error_details: List[Dict[str, Any]] = []
        for category in ["errors", "failures"]:
            for error in self.results.get(category, []):
                error_details.append(
                    {
                        "file_path": error["file_path"],
                        "line": error["line"],
                        "function": error["function"],
                        "error_type": error["error_type"],
                        "error_message": error["error_message"],
                        "frame_ref_lines": error.get("frame_ref_lines", []),
                    }
                )
        return error_details


def run_tests(
    test_patterns: Optional[List[str]] = None,
    verbosity: int = 1,
    json_output: bool = False,
    extract_errors: bool = False,
    list_mode: bool = False,
) -> Union[unittest.TestResult, Dict[str, Any], List[Dict[str, Any]]]:
    # Check for LLDB availability and adjust test patterns
    if not is_lldb_available():
        if verbosity > 0:
            print(
                "WARNING: 'lldb' module not found. Skipping lldb-dependent tests.",
                file=sys.stderr,
            )
        lldb_test_modules = [
            "test_core",
            "test_debug_info_handler",
            "test_event_loop",
            "test_lldb_tracer",
            "test_source_handler",
            "test_source_ranges",
            "test_step_handler",
            "test_symbol_trace_plugin",
            "test_tracer_main",
        ]
        effective_patterns = list(test_patterns) if test_patterns else []
        for module in lldb_test_modules:
            effective_patterns.append(f"-{module}.*")
        test_patterns = effective_patterns

    loader = unittest.TestLoader()
    suite: unittest.TestSuite
    try:
        # Always discover all tests first
        discovered = loader.discover(start_dir="tests", pattern="test*.py")

        # IMPORTANT: Cache source info before any test runs or filtering.
        _cache_test_source_info(discovered)

        # Apply test filters if any patterns provided
        if test_patterns:
            suite = filter_tests(discovered, test_patterns)
        else:
            suite = discovered

        if list_mode:
            test_cases: List[str] = []
            # Iteratively collect test IDs to avoid recursion limits
            stack: List[Union[unittest.TestSuite, unittest.TestCase]] = [suite]
            processed_suites: Set[int] = set()

            while stack:
                current = stack.pop()
                if id(current) in processed_suites:
                    continue
                if isinstance(current, unittest.TestSuite):
                    processed_suites.add(id(current))
                    stack.extend(reversed(list(current)))
                elif isinstance(current, unittest.TestCase):
                    test_cases.append(current.id())

            for test_id in sorted(test_cases):
                print(test_id)
            return {"test_cases": sorted(test_cases)}

        if json_output:
            # Use a stream that doesn't interfere with the final JSON output
            stream = open(os.devnull, "w") if verbosity < 2 else sys.stderr
            runner = unittest.TextTestRunner(stream=stream, verbosity=verbosity, resultclass=JSONTestResult)
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


def main() -> None:
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
            # The result is already a dict, list, or other JSON-serializable object
            print(json.dumps(result, indent=2))

        exit_code = 0
        if isinstance(result, unittest.TestResult):
            exit_code = 0 if result.wasSuccessful() else 1
        elif isinstance(result, dict) and "total" in result:  # JSON result
            if result["errors"] > 0 or result["failures"] > 0:
                exit_code = 1
        # For list mode or extract-errors, exit code is 0 unless an exception occurred.

        sys.exit(exit_code)
    except Exception:
        sys.exit(2)


if __name__ == "__main__":
    main()
