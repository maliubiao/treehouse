from typing import List

import colorama

from .models import TestResult, TestStatus


class TestReporter:
    """Collects test results and prints a summary."""

    def __init__(self):
        self.results: List[TestResult] = []

    def add_result(self, result: TestResult):
        """Adds a test result to the collection."""
        self.results.append(result)

    def print_summary(self):
        """Prints a formatted summary of all test results."""
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)
        error = sum(1 for r in self.results if r.status == TestStatus.ERROR)

        print("\n=== Test Summary ===")
        print(f"Total: {len(self.results)}, Passed: {passed}, Failed: {failed}, Error: {error}, Skipped: {skipped}")

        if failed > 0 or error > 0:
            print("\n=== Failed/Error Tests ===")
            for result in self.results:
                if result.status in (TestStatus.FAILED, TestStatus.ERROR):
                    print(f"{result.name}: {result.message}")

    @staticmethod
    def print_result(result: TestResult):
        """Prints the result of a single test function."""
        if result.status == TestStatus.PASSED:
            status_color = colorama.Fore.GREEN
        elif result.status == TestStatus.FAILED:
            status_color = colorama.Fore.RED
        else:
            status_color = colorama.Fore.YELLOW

        status_msg = f"{status_color}[{result.status.value}]{colorama.Style.RESET_ALL}"
        print(f"{status_msg} {result.name} ({result.duration:.2f}s)")
