import argparse
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from typing import Any, Dict, List, Optional, Union

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def parse_args():
    parser = argparse.ArgumentParser(description="Run pytest tests with flexible selection")
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
        help="Optional test case to run (supports pytest -k style matching)",
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


class PytestJSONReporter:
    def __init__(self):
        self.results = defaultdict(list)
        self.all_issues = []
        self.start_times = {}
        self.stats = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
            "error": 0,
        }

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_logstart(self, nodeid, location):
        self.start_times[nodeid] = time.time()

    @pytest.hookimpl(trylast=True)
    def pytest_runtest_logfinish(self, nodeid, location):
        elapsed = time.time() - self.start_times.get(nodeid, time.time())
        if elapsed > 0.1:
            self.all_issues.append(("timeout", nodeid, f"Test {nodeid} took too long: {elapsed:.3f}s"))

    def pytest_runtest_logreport(self, report):
        self.stats["total"] += 1
        if report.passed:
            self.stats["passed"] += 1
        elif report.failed:
            self.stats["failed"] += 1
            try:
                self._record_failure(report)
            except Exception as e:
                error_entry = {
                    "test": report.nodeid,
                    "error_type": "InternalError",
                    "error_message": f"Failed to record failure: {str(e)}",
                    "traceback": traceback.format_exc(),
                    "file_path": str(report.fspath) if hasattr(report, "fspath") else None,
                    "line": report.location[1] if hasattr(report, "location") else None,
                    "function": report.location[2]
                    if hasattr(report, "location") and len(report.location) > 2
                    else None,
                }
                self.results["failures"].append(error_entry)
                self.all_issues.append(("failure", report.nodeid, error_entry))
        elif report.skipped:
            self.stats["skipped"] += 1
            self._record_skipped(report)
        elif hasattr(report, "wasxfail"):
            if report.passed:
                self.stats["xpassed"] += 1
                self._record_xpassed(report)
            else:
                self.stats["xfailed"] += 1
                self._record_xfailed(report)

    def _record_failure(self, report):
        try:
            error_type = "Exception"
            error_message = ""
            tb = []

            if hasattr(report.longrepr, "reprtraceback"):
                error_type = (
                    report.longrepr.reprcrash.message.split(":")[0]
                    if hasattr(report.longrepr, "reprcrash")
                    else "Exception"
                )
                error_message = (
                    ":".join(report.longrepr.reprcrash.message.split(":")[1:]).strip()
                    if hasattr(report.longrepr, "reprcrash")
                    else str(report.longrepr)
                )

                for entry in report.longrepr.reprtraceback.reprentries:
                    tb.append(str(entry))
            else:
                lines = report.longreprtext.split("\n")
                if lines:
                    first_line = lines[0]
                    if ":" in first_line:
                        parts = first_line.split(":")
                        error_type = parts[0].strip()
                        error_message = ":".join(parts[1:]).strip()
                    else:
                        error_type = first_line.strip()

                tb = report.longreprtext.split("\n")

            error_entry = {
                "test": report.nodeid,
                "error_type": error_type,
                "error_message": error_message,
                "traceback": "\n".join(tb),
                "file_path": str(report.fspath) if hasattr(report, "fspath") else None,
                "line": report.location[1] if hasattr(report, "location") else None,
                "function": report.location[2] if hasattr(report, "location") and len(report.location) > 2 else None,
            }
            self.results["failures"].append(error_entry)
            self.all_issues.append(("failure", report.nodeid, error_entry))
        except Exception as e:
            error_entry = {
                "test": report.nodeid,
                "error_type": "InternalError",
                "error_message": f"Failed to process failure report: {str(e)}",
                "traceback": traceback.format_exc(),
                "file_path": str(report.fspath) if hasattr(report, "fspath") else None,
                "line": report.location[1] if hasattr(report, "location") else None,
                "function": report.location[2] if hasattr(report, "location") and len(report.location) > 2 else None,
            }
            self.results["failures"].append(error_entry)
            self.all_issues.append(("failure", report.nodeid, error_entry))

    def _record_skipped(self, report):
        try:
            if isinstance(report.longrepr, tuple):
                reason = report.longrepr[2].split(":")[-1].strip() if len(report.longrepr) > 2 else str(report.longrepr)
            else:
                reason = str(report.longrepr)
            self.all_issues.append(("skip", report.nodeid, reason))
        except Exception as e:
            self.all_issues.append(("skip", report.nodeid, f"Failed to get skip reason: {str(e)}"))

    def _record_xpassed(self, report):
        self.all_issues.append(("unexpected_success", report.nodeid, None))

    def _record_xfailed(self, report):
        self.all_issues.append(("expected_failure", report.nodeid, None))

    def get_json_results(self) -> Dict[str, Any]:
        return {
            "total": self.stats["total"],
            "success": self.stats["passed"],
            "failures": self.stats["failed"],
            "errors": 0,  # pytest combines errors and failures
            "skipped": self.stats["skipped"],
            "expected_failures": self.stats["xfailed"],
            "unexpected_successes": self.stats["xpassed"],
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

    def get_error_details(self) -> List[Dict[str, Any]]:
        return [
            {
                "file_path": error.get("file_path"),
                "line": error.get("line"),
                "function": error.get("function"),
                "error_type": error.get("error_type"),
                "error_message": error.get("error_message"),
            }
            for error in self.results.get("failures", [])
        ]


def run_tests(
    test_name: Optional[str] = None,
    verbosity: int = 1,
    json_output: bool = False,
    extract_errors: bool = False,
    list_mode: bool = False,
) -> Union[Dict[str, Any], pytest.ExitCode]:
    pytest_args = ["tests"]

    if verbosity == 0:
        pytest_args.append("-q")
    elif verbosity == 2:
        pytest_args.append("-v")

    if test_name:
        pytest_args.extend(["-k", test_name])

    if list_mode:
        pytest_args.extend(["--collect-only", "-q"])
        collected = []

        def pytest_collection_modifyitems(items):
            for item in items:
                collected.append(item.nodeid)

        pytest.main(pytest_args, plugins=[pytest_collection_modifyitems])
        return {"test_cases": sorted(collected)}

    reporter = PytestJSONReporter()
    if json_output:
        pytest_args.append("--tb=native")  # 获取更详细的traceback

    exit_code = pytest.main(pytest_args, plugins=[reporter])

    if json_output:
        if extract_errors:
            return reporter.get_error_details()
        return reporter.get_json_results()
    return exit_code


def main():
    add_gpt_path_to_syspath()
    args = parse_args()

    try:
        result = run_tests(
            test_name=args.test_name,
            verbosity=args.verbosity,
            json_output=args.json,
            extract_errors=args.extract_errors,
            list_mode=args.list_tests,
        )

        if args.json:
            print("capture error_details:")
            print(json.dumps(result, indent=2))

        sys.exit(result if isinstance(result, int) else 0)
    except Exception as e:
        print(f"Error running tests: {str(e)}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
