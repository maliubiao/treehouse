"""
Package entrypoint for running as a module: `python -m chrome_context_tracer`
"""

from .cli import main

if __name__ == "__main__":
    main()
