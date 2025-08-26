"""
Pytest configuration for native_context_tracer tests.

This file automatically sets up the Python path for all tests.
"""

import sys
from pathlib import Path

# Add src directory to Python path for all tests
project_root = Path.cwd()
src_path = project_root / "src"

if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
