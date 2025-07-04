# -*- coding: utf-8 -*-
"""
This module provides functionality to resolve the source location of imports
within a given code frame. It uses AST parsing to analyze the source code
and determines the file path of non-standard-library modules.
"""

import ast
import importlib.util
import inspect
import os
import sys
import types
from typing import Dict, Optional, Set, Tuple

# A set of paths that contain standard library modules.
# We initialize it once to avoid repeated computation.
# On some systems, real_prefix is used for virtual environments.
_STD_LIB_PATHS = {sys.prefix, sys.exec_prefix}
if hasattr(sys, "real_prefix"):
    _STD_LIB_PATHS.add(sys.real_prefix)


def _is_std_lib_path(path: str) -> bool:
    """
    Determine if a given module path belongs to the standard library.

    Enhanced to handle special cases like 'built-in' and 'frozen' modules,
    and properly recognize stdlib paths in different environments.
    """
    if not path:
        return False

    # Handle special markers for built-in/frozen modules
    if path in {"built-in", "frozen"}:
        return True

    # Normalize paths for comparison
    normalized_path = os.path.normpath(path)

    # Check against known stdlib paths
    for lib_path in _STD_LIB_PATHS:
        normalized_lib_path = os.path.normpath(lib_path)
        if normalized_path.startswith(normalized_lib_path):
            return True

    # 修复点：使用 sys.base_prefix 获取系统Python安装路径
    base_python_path = sys.base_prefix
    python_lib_path = os.path.join(base_python_path, f"lib/python{sys.version_info.major}.{sys.version_info.minor}")
    if normalized_path.startswith(os.path.normpath(python_lib_path)):
        return True

    # 修复点：添加系统标准库路径检测
    stdlib_path = os.path.join(
        base_python_path, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages"
    )
    if normalized_path.startswith(os.path.normpath(stdlib_path)):
        return True

    return False


# pylint: disable=invalid-name
class _ImportVisitor(ast.NodeVisitor):
    """
    An AST visitor that collects information about import statements.

    It gathers all `import` and `from ... import` statements and stores
    the relationship between the name injected into the local namespace
    and the full module path it refers to. It correctly resolves relative
    imports using the package context.
    """

    def __init__(self, package: Optional[str]):
        """
        Initializes the visitor.

        Args:
            package: The name of the package containing the code being parsed.
                     This is crucial for resolving relative imports.
                     It can be retrieved from `frame.f_globals.get('__package__')`.
        """
        self._package = package
        # Stores tuples of (injected_name, absolute_module_to_resolve)
        self.imports: Set[Tuple[str, str]] = set()

    def visit_Import(self, node: ast.Import) -> None:
        """Handles `import module` and `import module as alias`."""
        for alias in node.names:
            if alias.asname:
                injected_name = alias.asname
                module_name = alias.name
            else:
                # 关键修复：普通导入语句只使用顶级包名
                injected_name = alias.name.split(".")[0]
                module_name = alias.name.split(".")[0]  # 仅使用顶级包名

            self.imports.add((injected_name, module_name))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """
        Handles `from module import name` and `from .relative import name`.
        """
        # Resolve the base module, handling relative imports (e.g., . or ..)
        # importlib.util.resolve_name is the standard and robust way to do this.
        relative_module_path = "." * node.level + (node.module or "")

        # If it's a pure relative import like `from . import foo`, we need the package context.
        if not relative_module_path:
            self.generic_visit(node)
            return

        try:
            # For `from package import module`, the spec to find is `package`.
            # For `from package.module import name`, it's `package.module`.
            # We resolve the name to get the absolute module path.
            absolute_base_module = importlib.util.resolve_name(relative_module_path, self._package)
        except ImportError:
            # If resolution fails, we cannot proceed with this import.
            # This can happen with malformed or dynamic-only imports.
            self.generic_visit(node)
            return

        for alias in node.names:
            if alias.name == "*":
                # Wildcard imports inject names that are not statically determinable
                # from the AST of this file alone. We skip them.
                continue

            # The name injected into the namespace.
            injected_name = alias.asname or alias.name

            # The module we need to find the file for is the base module.
            # e.g., for `from myapp.utils import helper`, we need to find `myapp.utils`.
            self.imports.add((injected_name, absolute_base_module))

        self.generic_visit(node)


def resolve_imports(frame: types.FrameType) -> Dict[str, Dict[str, str]]:
    """
    Resolves non-standard-library imports from a given execution frame.

    This function inspects the source code of the file associated with the
    frame, parses it to find all import statements, and determines the
    absolute file path for each imported module that is not part of the

    Python standard library.

    Args:
        frame: The execution frame to analyze.

    Returns:
        A dictionary mapping the imported variable names (as they appear in
        the code) to their source module information. Returns an empty
        dictionary if the source cannot be found or parsed.

        Example of the returned structure:
        {
            'my_util': {
                'module': 'my_project.utils',
                'path': '/path/to/my_project/utils.py'
            },
            'another_func': {
                'module': 'my_project.helpers',
                'path': '/path/to/my_project/helpers.py'
            }
        }
    """
    try:
        filename = inspect.getsourcefile(frame)
        if not filename or not os.path.exists(filename):
            return {}

        with open(filename, "r", encoding="utf-8") as f:
            source_code = f.read()

    except (TypeError, OSError):
        # Could fail if frame is for a dynamically generated code object
        return {}

    try:
        tree = ast.parse(source_code, filename=filename)
    except SyntaxError:
        # The source file might have invalid syntax
        return {}

    # Get package context from the frame's globals for relative import resolution.
    package = frame.f_globals.get("__package__")

    visitor = _ImportVisitor(package=package)
    visitor.visit(tree)

    resolved_imports: Dict[str, Dict[str, str]] = {}
    for injected_name, module_name in visitor.imports:
        try:
            # Find the module's specification.
            spec = importlib.util.find_spec(module_name)
        except (ValueError, ImportError):
            # Invalid module name or other import issue.
            continue

        if not spec or not spec.origin or spec.origin == "built-in":
            # Skip built-in modules or namespace packages without a file location.
            continue

        # Check if the module is part of the standard library.
        if _is_std_lib_path(spec.origin):
            continue

        resolved_imports[injected_name] = {
            "module": module_name,
            "path": spec.origin,
        }

    return resolved_imports
