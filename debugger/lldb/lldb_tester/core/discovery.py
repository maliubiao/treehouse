import glob
import importlib.util
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Tuple


class TestFileFinder:
    """Discovers test files and maps them to their corresponding source programs."""

    @staticmethod
    def discover_test_files(test_dir: str, pattern: str = "test_*.py") -> List[str]:
        """
        Finds test script files matching a pattern in a directory.

        Args:
            test_dir: The directory to search for test scripts.
            pattern: The glob pattern to match test files.

        Returns:
            A list of paths to the discovered test files.
        """
        if not os.path.exists(test_dir):
            return []
        return glob.glob(os.path.join(test_dir, pattern))

    @staticmethod
    def map_tests_to_programs(test_files: List[str], programs_dir: str) -> Dict[str, str]:
        """
        Maps test scripts to their corresponding C/C++ source files.

        Args:
            test_files: A list of paths to test scripts.
            programs_dir: The directory containing the source code.

        Returns:
            A dictionary mapping test script paths to source file paths.
        """
        test_map = {}
        for test_file in test_files:
            base_name = os.path.basename(test_file)
            if base_name.startswith("test_") and base_name.endswith(".py"):
                program_name = base_name[5:-3]

                possible_files = [
                    os.path.join(programs_dir, f"{program_name}.c"),
                    os.path.join(programs_dir, f"{program_name}.cpp"),
                    os.path.join(programs_dir, f"test_{program_name}.c"),
                    os.path.join(programs_dir, f"test_{program_name}.cpp"),
                    os.path.join(programs_dir, f"{base_name[:-3]}.c"),
                    os.path.join(programs_dir, f"{base_name[:-3]}.cpp"),
                ]

                source_file = next((f for f in possible_files if os.path.exists(f)), None)

                if source_file:
                    test_map[test_file] = source_file
                else:
                    logging.warning("No matching source file for test: %s", test_file)
            else:
                logging.warning("Test file doesn't follow naming convention: %s", test_file)
        return test_map


class ScriptLoader:
    """Dynamically loads a Python module from a file."""

    @staticmethod
    def load_module_from_file(script_path: str) -> Any:
        """
        Loads a Python module from its file path.

        Args:
            script_path: The absolute or relative path to the Python script.

        Returns:
            The loaded module object.

        Raises:
            ImportError: If the module cannot be loaded.
        """
        module_name = os.path.splitext(os.path.basename(script_path))[0]
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create module spec from file: {script_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


class TestFunctionFinder:
    """Finds test functions within a given module."""

    @staticmethod
    def find(module: Any) -> List[Tuple[str, Callable]]:
        """
        Finds all functions in a module that match the test naming convention.

        Args:
            module: The module object to inspect.

        Returns:
            A list of tuples, where each tuple contains the name of the test
            function and the function object itself.
        """
        test_functions = []
        for name, func in module.__dict__.items():
            if callable(func) and (name.startswith("test_") or name == "run_test"):
                test_functions.append((name, func))
        return test_functions
