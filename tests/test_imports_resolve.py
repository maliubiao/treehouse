import importlib.util  # Added for dynamic module loading
import os
import shutil
import sys
import tempfile
import unittest

# from pathlib import Path # Removed as unused
from typing import Any, Dict

from gpt_workflow.unittester.imports_resolve import resolve_imports


def execute_and_resolve(code: str, module_name: str, package: str, project_root: str) -> Dict[str, Any]:
    """
    A helper to execute code in a specific module context and resolve imports.

    It now creates a temporary Python file, writes the given code to it,
    and then dynamically imports and executes this file. This ensures
    that `inspect.getsourcefile` can correctly retrieve a file path,
    mimicking a real module import for `resolve_imports`. This addresses
    the test environment setup issue identified in the analysis.
    """
    result = {}
    temp_file_path = None
    # Store and remove existing module entry if any, to ensure our temporary module is loaded
    original_sys_modules_entry = sys.modules.pop(module_name, None)
    original_sys_path = list(sys.path)  # Copy sys.path to restore later

    # Create a unique temporary directory within the project root for the module file
    # This helps ensure the temporary file's path is realistic relative to the project.
    temp_dir_suffix = tempfile.mkdtemp(dir=project_root)
    temp_file_name = "temp_module_for_test.py"
    temp_file_path = os.path.join(temp_dir_suffix, temp_file_name)

    try:
        # Write the test code to the temporary file.
        # 修复点：移除显式import inspect，避免污染测试环境
        with open(temp_file_path, "w", encoding="utf-8") as f:
            f.write(f"{code}\nresolver_hook()")  # 仅写入测试代码和钩子调用

        # Add the temporary directory to sys.path so Python's import system can find the module
        sys.path.insert(0, temp_dir_suffix)

        # 修复点：直接使用目标模块名创建规范
        spec = importlib.util.spec_from_file_location(module_name, temp_file_path)

        if spec is None:
            raise ImportError(f"Could not create module spec for {temp_file_path}")

        # Create a module object based on the spec
        module = importlib.util.module_from_spec(spec)

        # 修复点：移除冗余的__name__设置，保持规范中的名称
        # 仅设置关键属性
        module.__package__ = package
        module.__file__ = temp_file_path

        # Add the module to sys.modules under its target name.
        # This is essential for `resolve_imports` to correctly identify and process imports
        # originating from this simulated module.
        sys.modules[module_name] = module

        # 修复点：修改resolver_hook实现，内部动态导入inspect
        def resolver_hook():
            # 动态导入inspect避免污染模块全局空间
            # pylint: disable=import-outside-toplevel
            import inspect

            frame = inspect.currentframe().f_back
            nonlocal result
            result = resolve_imports(frame)

        # Inject `resolver_hook` into the module's global namespace.
        # This makes it callable by the code written to the temp file.
        module.resolver_hook = resolver_hook

        # Execute the module's code. This will run the `code` and then call `resolver_hook()`.
        spec.loader.exec_module(module)

    finally:
        # ----- Cleanup operations to ensure test isolation and environment restoration -----

        # Remove the temporary module from `sys.modules` if it's still there and is our temporary one.
        if module_name in sys.modules and sys.modules[module_name] is module:
            del sys.modules[module_name]
        # Restore the original module entry if one existed before our test.
        if original_sys_modules_entry is not None:
            sys.modules[module_name] = original_sys_modules_entry

        # Clean up the temporary file and its containing directory.
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if temp_dir_suffix and os.path.exists(temp_dir_suffix):
            shutil.rmtree(temp_dir_suffix)

        # Restore `sys.path` to its original state.
        sys.path[:] = original_sys_path

    return result


class TestImportsResolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Create a temporary project structure for testing."""
        cls.temp_dir = tempfile.mkdtemp(prefix="importer_test_")
        cls.project_root = os.path.join(cls.temp_dir, "my_project")

        # Project structure:
        # /tmp/importer_test_xxxx/
        # └── my_project/
        #     ├── __init__.py
        #     ├── app.py
        #     ├── utils.py
        #     └── services/
        #         ├── __init__.py
        #         └── api.py
        os.makedirs(os.path.join(cls.project_root, "services"))

        # Create empty files
        cls.files = {
            "init": os.path.join(cls.project_root, "__init__.py"),
            "app": os.path.join(cls.project_root, "app.py"),
            "utils": os.path.join(cls.project_root, "utils.py"),
            "services_init": os.path.join(cls.project_root, "services", "__init__.py"),
            "services_api": os.path.join(cls.project_root, "services", "api.py"),
        }
        for path in cls.files.values():
            with open(path, "w", encoding="utf-8") as f:
                # Add a dummy variable to make them importable targets
                if os.path.basename(path) != "__init__.py":
                    f.write("DUMMY_VAR = 1\n")

        # Add the temporary directory to Python's path
        sys.path.insert(0, cls.temp_dir)

    @classmethod
    def tearDownClass(cls):
        """Clean up the temporary directory and path."""
        sys.path.pop(0)
        shutil.rmtree(cls.temp_dir)

    def test_no_imports(self):
        code = "a = 1\nb = 2"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        self.assertEqual(result, {})

    def test_stdlib_imports_are_ignored(self):
        code = """
import os
import json
from collections import defaultdict
import sys as system
"""
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        self.assertEqual(result, {})

    def test_direct_import(self):
        code = "import my_project.utils"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        # The 'expected' variable was unused, removed to clean up code.
        self.assertIn("my_project", result)
        self.assertEqual(result["my_project"]["module"], "my_project.utils")
        self.assertEqual(os.path.normpath(result["my_project"]["path"]), os.path.normpath(self.files["utils"]))

    def test_direct_import_with_alias(self):
        code = "import my_project.utils as u"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        # The 'expected' variable was unused, removed to clean up code.
        self.assertIn("u", result)
        self.assertEqual(result["u"]["module"], "my_project.utils")
        self.assertEqual(os.path.normpath(result["u"]["path"]), os.path.normpath(self.files["utils"]))

    def test_from_import_module(self):
        code = "from my_project import utils"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        # The 'expected' variable was unused, removed to clean up code.
        self.assertIn("utils", result)
        self.assertEqual(result["utils"]["module"], "my_project")
        self.assertEqual(os.path.normpath(result["utils"]["path"]), os.path.normpath(self.files["init"]))

    def test_from_import_name(self):
        code = "from my_project.utils import DUMMY_VAR"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        # The 'expected' variable was unused, removed to clean up code.
        self.assertIn("DUMMY_VAR", result)
        self.assertEqual(result["DUMMY_VAR"]["module"], "my_project.utils")
        self.assertEqual(os.path.normpath(result["DUMMY_VAR"]["path"]), os.path.normpath(self.files["utils"]))

    def test_from_import_name_with_alias(self):
        code = "from my_project.utils import DUMMY_VAR as MY_VAR"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        # The 'expected' variable was unused, removed to clean up code.
        self.assertIn("MY_VAR", result)
        self.assertEqual(result["MY_VAR"]["module"], "my_project.utils")
        self.assertEqual(os.path.normpath(result["MY_VAR"]["path"]), os.path.normpath(self.files["utils"]))

    def test_wildcard_import_is_ignored(self):
        code = "from my_project.utils import *"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        self.assertEqual(result, {})

    def test_relative_import_sibling(self):
        # This code is conceptually inside my_project/app.py
        code = "from . import utils"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)
        # The 'expected' variable was unused, removed to clean up code.
        self.assertIn("utils", result)
        self.assertEqual(result["utils"]["module"], "my_project")
        self.assertEqual(os.path.normpath(result["utils"]["path"]), os.path.normpath(self.files["init"]))

    def test_relative_import_from_subpackage(self):
        # This code is conceptually inside my_project/services/api.py
        code = "from .. import utils"
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.services.api", "my_project.services", self.project_root)
        # The 'expected' variable was unused, removed to clean up code.
        self.assertIn("utils", result)
        self.assertEqual(result["utils"]["module"], "my_project")
        self.assertEqual(os.path.normpath(result["utils"]["path"]), os.path.normpath(self.files["init"]))

    def test_multiple_complex_imports(self):
        # This code is conceptually inside my_project/app.py
        code = """
import os
import my_project.utils as u
from my_project.services import api
from .utils import DUMMY_VAR as APP_VAR
"""
        # Pass self.project_root to execute_and_resolve for temporary file creation
        result = execute_and_resolve(code, "my_project.app", "my_project", self.project_root)

        # Expected result for 'u'
        self.assertIn("u", result)
        self.assertEqual(result["u"]["module"], "my_project.utils")
        self.assertEqual(os.path.normpath(result["u"]["path"]), os.path.normpath(self.files["utils"]))

        # Expected result for 'api'
        self.assertIn("api", result)
        self.assertEqual(result["api"]["module"], "my_project.services")
        self.assertEqual(os.path.normpath(result["api"]["path"]), os.path.normpath(self.files["services_init"]))

        # Expected result for 'APP_VAR'
        self.assertIn("APP_VAR", result)
        self.assertEqual(result["APP_VAR"]["module"], "my_project.utils")
        self.assertEqual(os.path.normpath(result["APP_VAR"]["path"]), os.path.normpath(self.files["utils"]))

        # 'os' should not be present
        self.assertNotIn("os", result)
        self.assertEqual(len(result), 3)


if __name__ == "__main__":
    unittest.main()
