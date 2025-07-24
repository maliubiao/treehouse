"""
Conftest file for pytest, handles path setup for relative imports
"""

import os
import sys

# Ensure tests can import from parent directory
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
    print(f"Added {parent_dir} to sys.path")

# Set PYTHONPATH to include the project root
os.environ["PYTHONPATH"] = os.pathsep.join([os.getenv("PYTHONPATH", ""), parent_dir, os.path.dirname(parent_dir)])
