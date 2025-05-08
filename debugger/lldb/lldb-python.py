#!/usr/bin/env python3

import subprocess
import pdb
import os
import sys
import json


def get_external_python_paths():
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import sys; print(sys.path)"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf8",
        )
        paths = eval(result.stdout.strip())
        return [p for p in paths if p and os.path.exists(p)]
    except Exception as e:
        print(f"Warning: Failed to get external Python paths: {e}", file=sys.stderr)
        return []


external_paths = get_external_python_paths()

os.environ["PYTHONPATH"] = os.path.pathsep.join(filter(None, external_paths))
os.environ["PYTHONHOME"] = os.path.expanduser("~/code/terminal-llm/.venv")
os.system("/Users/richard/code/llvm-project/lldb-build/bin/lldb")
