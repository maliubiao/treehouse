import argparse
import json
import os
import re
import sys
import unittest
from collections import defaultdict

from debugger import tracer


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
        "test_name", nargs="?", default=None, help="Optional test case to run (format: TestCase.test_method)"
    )
    parser.add_argument("--json", action="store_true", help="Output test results in JSON format")
    parser.add_argument(
        "--extract-errors", action="store_true", help="Extract error details in machine-readable format"
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

    def addFailure(self, test, err):
        super().addFailure(test, err)
        test_id = test.id()
        tb = self._exc_info_to_string(err, test)
        file_path, line, func_name = self._parse_test_id(test_id, tb)
        error_type = type(err[1]).__name__
        self.results["failures"].append(
            {
                "test": str(test),
                "error_type": error_type,
                "error_message": str(err[1]),
                "traceback": tb,
                "file_path": file_path,
                "line": line,
                "function": func_name,
            }
        )

    def addError(self, test, err):
        super().addError(test, err)
        test_id = test.id()
        tb = self._exc_info_to_string(err, test)
        file_path, line, func_name = self._parse_test_id(test_id, tb)
        error_type = type(err[1]).__name__ if err[1] else "UnknownError"
        self.results["errors"].append(
            {
                "test": str(test),
                "error_type": error_type,
                "error_message": str(err[1]) if err[1] else "Unknown error occurred",
                "traceback": tb,
                "file_path": file_path,
                "line": line,
                "function": func_name,
            }
        )

    def _parse_test_id(self, test_id, tb=None):
        parts = test_id.split(".")
        base_module = parts[0]

        # Handle test modules in tests directory
        if base_module.startswith("test_"):
            module_path = os.path.join("tests", f"{base_module}.py")
        else:
            module_path = base_module.replace(".", "/") + ".py"

        # Search in project directory first
        file_path = None
        project_root = os.getcwd()
        full_path = os.path.join(project_root, module_path)
        if os.path.exists(full_path):
            file_path = full_path
        else:
            # Fallback to sys.path search
            for path in sys.path:
                full_path = os.path.join(path, module_path)
                if os.path.exists(full_path):
                    file_path = full_path
                    break

        # Extract line number using regex
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
            "results": dict(self.results),
        }

    def get_error_details(self):
        error_details = []
        for error in self.results.get("errors", []):
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


def main():
    add_gpt_path_to_syspath()
    args = parse_args()
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    try:
        if args.test_name:
            suite.addTests(loader.loadTestsFromName(args.test_name))
        else:
            # Auto-discover tests in 'tests' directory
            discovered = loader.discover(start_dir="tests", pattern="test*.py")
            suite.addTests(discovered)

        if args.json:
            runner = unittest.TextTestRunner(verbosity=args.verbosity, resultclass=JSONTestResult)
            result = runner.run(suite)
            print("capture error_details:")
            if args.extract_errors:
                print(json.dumps(result.get_error_details(), indent=2))
            else:
                print(json.dumps(result.get_json_results(), indent=2))
        else:
            runner = unittest.TextTestRunner(verbosity=args.verbosity)
            result = runner.run(suite)

        sys.exit(not result.wasSuccessful())

    except (ImportError, AttributeError) as e:
        sys.stderr.write(f"\nERROR: {str(e)}\n")
        sys.stderr.write("Make sure test modules follow naming convention 'test_*.py'\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"\nCRITICAL ERROR: {str(e)}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
