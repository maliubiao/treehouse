#!/usr/bin/env python3
"""
Test runner for DWARF cache tests
"""

import argparse
import os
import sys
import unittest
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import test modules
from tests.test_dwarf_cache.test_dwarf_cache_manager import TestDwarfCacheManager
from tests.test_dwarf_cache.test_integration import TestSourceHandlerIntegration
from tests.test_dwarf_cache.test_invalidation import TestCacheInvalidation


def run_tests(test_type="all"):
    """Run the specified tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    if test_type == "all":
        suite.addTests(loader.loadTestsFromTestCase(TestDwarfCacheManager))
        suite.addTests(loader.loadTestsFromTestCase(TestCacheInvalidation))
        suite.addTests(loader.loadTestsFromTestCase(TestSourceHandlerIntegration))
    elif test_type == "unit":
        suite.addTests(loader.loadTestsFromTestCase(TestDwarfCacheManager))
    elif test_type == "invalidation":
        suite.addTests(loader.loadTestsFromTestCase(TestCacheInvalidation))
    elif test_type == "integration":
        suite.addTests(loader.loadTestsFromTestCase(TestSourceHandlerIntegration))
    else:
        print(f"Unknown test type: {test_type}")
        return False

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description="Run DWARF cache tests")
    parser.add_argument(
        "test_type",
        nargs="?",
        default="all",
        choices=["all", "unit", "invalidation", "integration", "performance"],
        help="Type of tests to run",
    )
    parser.add_argument("--coverage", action="store_true", help="Run with coverage report")

    args = parser.parse_args()

    if args.coverage:
        try:
            import coverage

            cov = coverage.Coverage()
            cov.start()
            success = run_tests(args.test_type)
            cov.stop()
            cov.save()

            print("\nCoverage Report:")
            cov.report()

            # Generate HTML report
            html_dir = Path(__file__).parent / "htmlcov"
            cov.html_report(directory=str(html_dir))
            print(f"\nHTML coverage report generated in: {html_dir}")

            return success
        except ImportError:
            print("Coverage module not installed. Running tests without coverage.")
            return run_tests(args.test_type)
    else:
        return run_tests(args.test_type)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
