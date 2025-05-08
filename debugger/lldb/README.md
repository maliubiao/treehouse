# lldb python 编译使用教程

```shell
#uv 切换到在用的那个python版本, 编译对应的binding
cmake -S llvm -B lldb-build -DCMAKE_BUILD_TYPE=Debug -G Ninja  -DLLVM_ENABLE_PROJECTS="clang;lldb;clang-tools-extra" -DLLVM_ENABLE_RUNTIMES=""  -DLLDB_USE_SYSTEM_DEBUGSERVER=ON  -DLLDB_INCLUDE_TESTS=OFF
cd lldb-build; ninja 

bin/lldb-python
#编译好的lldb
bin/lldb
#lldb python模块,跟uv环境指定的对应
lib/python3.13/site-packages/
```

## 使用
需要正确的配置PYTHONHOME, 比如uv的虚拟环境在.venv   
给lldb, lldb-python设置环境PYTHONPATH, 继续自python本身的sys.path    

```python
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
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf8'
        )
        paths = eval(result.stdout.strip())
        return [p for p in paths if p and os.path.exists(p)]
    except Exception as e:
        print(f"Warning: Failed to get external Python paths: {e}", file=sys.stderr)
        return []

external_paths = get_external_python_paths()

#此处为虚拟环境的sys.path
os.environ["PYTHONPATH"] = os.path.pathsep.join(filter(None, external_paths))
#此处为我的虚拟环境
os.environ["PYTHONHOME"] = os.path.expanduser("~/code/terminal-llm/.venv")
#此处为编译过的lldb
os.system("/Users/richard/code/llvm-project/lldb-build/bin/lldb")

```


