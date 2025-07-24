"""
Test package for claude code proxy
Contains path setup utility to enable relative imports
"""

import os
import sys


def setup_path():
    """Ensure tests can import from parent directory."""
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        print(f"Added {parent_dir} to sys.path")


def package_root():
    """Return the package root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
