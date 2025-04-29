import argparse
import os
import sys
import unittest


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
    return parser.parse_args()


def add_gpt_path_to_syspath():
    gpt_path = os.getenv("GPT_PATH")
    if gpt_path and os.path.isdir(gpt_path):
        sys.path.insert(0, gpt_path)
        print(f"Added GPT_PATH to sys.path: {gpt_path}")


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
