"""
Path manipulation utilities for the debugger.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

_cached_sorted_paths: List[str] = sorted(
    (os.path.abspath(p) for p in sys.path if os.path.isdir(p)),  # Ensure path entry is a directory
    key=len,
    reverse=True,
)
# Module-level cache for path conversion results.
_path_result_cache: Dict[str, str] = {}


def to_relative_module_path(normalized_path: str) -> str:
    """
    Converts an absolute file path to a relative module path string,
    based on the current Python path (`sys.path`).

    The path is made relative to the longest matching path in `sys.path`.
    If no match is found in `sys.path`, it provides a sensible fallback:
    - For `__init__.py` files, it returns `package_name/__init__.py`.
    - For other files, it returns just the `file_name.py`.

    The output always uses forward slashes '/' as separators.

    Args:
        normalized_path: The absolute path to the file.

    Returns:
        The relative module path string (e.g., 'my_package/my_module.py').

    Raises:
        ValueError: If the provided path is not absolute.
    """
    if normalized_path in _path_result_cache:
        return _path_result_cache[normalized_path]

    best_match: Optional[str] = None
    for p_path in _cached_sorted_paths:
        try:
            # A path is a prefix if the common path is the path itself.
            if os.path.commonpath([normalized_path, p_path]) == p_path:
                best_match = p_path
                break
        except ValueError:
            # This can happen if paths are on different drives on Windows,
            # or if one path is relative (which we've already checked against).
            continue

    final_path: str
    if best_match:
        # The path is found within one of the sys.path directories.
        relative_path = os.path.relpath(normalized_path, start=best_match)
        # Ensure forward slashes for consistency across platforms.
        final_path = relative_path.replace(os.path.sep, "/")
    else:
        # The path is not in sys.path. Fallback to a sensible representation.
        file_path = Path(normalized_path)
        if file_path.name == "__init__.py":
            # For __init__.py, include the parent directory to signify the package.
            parts = file_path.parts
            if len(parts) > 2:  # e.g. ('/', 'package', '__init__.py')
                final_path = str(Path(*parts[-2:]))
            else:  # e.g. ('/', '__init__.py')
                final_path = file_path.name
        else:
            # For other files, just the filename is a reasonable fallback.
            final_path = file_path.name

    _path_result_cache[normalized_path] = final_path
    return final_path
