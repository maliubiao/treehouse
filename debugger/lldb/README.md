# lldb python 编译使用教程

## LLDB Python绑定编译

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

## Python环境配置
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

## Tracer工具使用说明

tracer.py是一个基于LLDB的调试工具，提供以下功能：
- 符号信息查看
- 模块地址范围分析
- 断点管理
- 指令级跟踪
- 模块跳过功能
- 交互式符号查看器

### 基本用法

```bash
python3 tracer.py -e /path/to/program [-a arg1 -a arg2] [-l logfile] [-c config.yaml]
```

### 主要功能选项

1. **查看符号信息**:
   运行后会生成symbols.html文件，包含所有模块的符号信息，支持交互式搜索和排序：
   ```bash
   python3 tracer.py -e /path/to/program
   ```

2. **跳过特定模块**:
   使用`--dump-modules-for-skip`选项可以交互式选择要跳过的模块:
   ```bash
   python3 tracer.py -e /path/to/program --dump-modules-for-skip
   ```
   选择后会保存到配置文件中

3. **详细日志**:
   使用`--verbose`选项开启详细日志:
   ```bash
   python3 tracer.py -e /path/to/program --verbose
   ```

4. **配置文件**:
   可以通过`-c`指定YAML格式的配置文件，支持热重载:
   ```bash
   python3 tracer.py -e /path/to/program -c config.yaml
   ```

### 配置文件示例 (YAML格式)

```yaml
# 最大跟踪步数
max_steps: 1000

# 是否启用JIT编译
enable_jit: false

# 日志选项
log_target_info: true
log_module_info: true
log_breakpoint_details: true

# 要跳过的模块模式列表(支持通配符)
skip_modules:
  - "libc*"
  - "ld-*"
  - "libstdc++*"

# 是否在启动时显示模块选择界面
dump_modules_for_skip: false
```

### 模块跳过功能

模块跳过功能允许你指定不需要跟踪的模块，如系统库等。使用方式：

1. 交互式选择要跳过的模块：
   ```bash
   python3 tracer.py -e /path/to/program --dump-modules-for-skip
   ```

2. 在配置文件中直接指定要跳过的模块模式：
   ```yaml
   skip_modules:
     - "libc*"
     - "ld-*"
   ```

3. 运行时跳过逻辑：
   - 当执行流进入跳过的模块时，会自动执行"step over"操作
   - 跳过模块的地址范围会在启动时显示
   - 跳过操作会记录在日志中

### 符号查看器

工具会生成一个交互式的HTML符号查看器(symbols.html)，功能包括：
- 按模块分组的符号列表
- 支持按名称、类型、地址范围排序
- 全局搜索功能
- 显示符号的源代码位置信息
- 响应式设计，支持不同屏幕尺寸

### 测试脚本

运行测试脚本验证功能:
```bash
./test_tracer.sh
./test_basic.sh
```

### 调试技巧

1. 查看模块地址范围：
   ```bash
   python3 tracer.py -e /path/to/program --verbose
   ```

2. 跟踪特定指令：
   - 在源代码中添加注释标记：
     ```c
     // trace this_function
     void this_function() {...}
     ```

3. 分析崩溃：
   - 工具会自动捕获SIGSEGV等信号并显示调用栈