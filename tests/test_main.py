import argparse
import json
import os
import re
import sys
import unittest
from collections import defaultdict
import inspect

from debugger import tracer


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run unit tests with flexible selection"
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        choices=[0, 1, 2],
        default=1,
        help="Output verbosity (0=quiet, 1=default, 2=verbose)",
    )
    parser.add_argument(
        "test_name",
        nargs="?",
        default=None,
        help="Optional test case to run (format: TestCase.test_method)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output test results in JSON format"
    )
    parser.add_argument(
        "--extract-errors",
        action="store_true",
        help="Extract error details in machine-readable format",
    )
    return parser.parse_args()


def add_gpt_path_to_syspath():
    gpt_path = os.getenv("GPT_PATH")
    if gpt_path and os.path.isdir(gpt_path):
        sys.path.insert(0, gpt_path)
        print(f"Added GPT_PATH to sys.path: {gpt_path}")


class JSONTestResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.results = defaultdict(list)
        self.all_issues = []

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
        tb = self._exc_info_to_string(err, test)
        file_path, line, func_name = self._parse_test_id(test_id, tb)
        # Use test method start line if available
        test_start_line = self._get_test_start_line(test)
        if test_start_line:
            line = test_start_line
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

    def _parse_test_id(self, test_id, tb=None):
        parts = test_id.split(".")
        base_module = parts[0]

        if base_module.startswith("test_"):
            module_path = os.path.join("tests", f"{base_module}.py")
        else:
            module_path = base_module.replace(".", "/") + ".py"

        project_root = os.getcwd()
        full_path = os.path.join(project_root, module_path)
        if os.path.exists(full_path):
            file_path = full_path
        else:
            for path in sys.path:
                full_path = os.path.join(path, module_path)
                if os.path.exists(full_path):
                    file_path = full_path
                    break

        line = None
        if tb:
            for entry in tb.splitlines():
                if 'File "' in entry and os.path.basename(module_path) in entry:
                    match = re.search(r"line (\d+)", entry)
                    if match:
                        line = int(match.group(1))
                        break

        return file_path, line, parts[-1]

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


def run_tests(test_name=None, verbosity=1, json_output=False, extract_errors=False):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    try:
        if test_name:
            suite.addTests(loader.loadTestsFromName(test_name))
        else:
            discovered = loader.discover(start_dir="tests", pattern="test*.py")
            suite.addTests(discovered)

        if json_output:
            runner = unittest.TextTestRunner(
                verbosity=verbosity, resultclass=JSONTestResult
            )
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
        sys.stderr.write(
            "Make sure test modules follow naming convention 'test_*.py'\n"
        )
        raise
    except Exception as e:
        sys.stderr.write(f"\nCRITICAL ERROR: {str(e)}\n")
        raise


def main():
    add_gpt_path_to_syspath()
    args = parse_args()

    try:
        result = run_tests(
            test_name=args.test_name,
            verbosity=args.verbosity,
            json_output=args.json,
            extract_errors=args.extract_errors,
        )

        if args.json:
            print("capture error_details:")
            print(json.dumps(result, indent=2))

        sys.exit(
            not result.wasSuccessful() if isinstance(result, unittest.TestResult) else 0
        )
    except Exception:
        sys.exit(2)


if __name__ == "__main__":
    main()
