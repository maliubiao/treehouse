# This file makes the 'unittester' directory a Python package.

# Expose the main UnitTestGenerator class for easier imports,
# maintaining a consistent public API.
from .generator import UnitTestGenerator

__all__ = ["UnitTestGenerator"]
