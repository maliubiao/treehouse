# LLDB Tracer

高级LLDB调试工具，提供源代码行级变量跟踪，提供汇编级指令跟踪及寄存器内存使用跟踪

> **注意**: tracer模块已从 `tracer/` 重命名为 `native_context_tracer/`，以更好地反映其原生上下文跟踪功能。

## 目录
- [使用示例](#使用示例)
- [功能特性](#功能特性)
  - [环境变量配置](#环境变量配置)
  - [模块跳过配置](#模块跳过配置)
  - [步进策略配置](#步进策略配置)
  - [循环检测](#循环检测)
  - [符号可视化](#符号可视化)
  - [libc函数参数自动跟踪](#libc函数参数自动跟踪)
  - [源代码基础目录](#源代码基础目录)
  - [符号追踪](#符号追踪)
- [配置选项](#配置选项)
  - [基本调试选项](#基本调试选项)
  - [步进控制选项](#步进控制选项)
  - [符号追踪选项](#符号追踪选项)
  - [环境与路径选项](#环境与路径选项)
  - [UI控制选项](#ui控制选项)
- [高级主题](#高级主题)
  - [问题排查](#问题排查)
  - [调试优化](#调试优化)

## 使用示例

基本使用：
```bash
python -m native_context_tracer.tracer_main -e /path/to/program -a arg1 -a arg2
```

启用详细日志：
```bash
python -m native_context_tracer.tracer_main -e /path/to/program --verbose
```

生成跳过模块配置：
```bash
python -m native_context_tracer.tracer_main -e /path/to/program --dump-modules-for-skip
```

## 功能特性

### 环境变量配置
在配置文件中设置环境变量：
```yaml
environment:
  DEBUG: "1"
  PATH: "/custom/path:$PATH"
  CUSTOM_SETTING: "special_value"
```

环境变量将以`KEY=VALUE`格式传递给被调试程序，支持变量扩展（如`$PATH`）。

### 模块跳过配置
使用`--dump-modules-for-skip`生成配置，工具会交互式显示所有模块并让用户选择保留的模块，其余模块将被跳过。

### 步进策略配置
针对特定源代码文件指定步进策略：
```yaml
step_action:
  "/path/to/source/file.c": [[10, 20], "step_over"]
  "/another/source/file.py": [[5, 15], "source_step_in"]
```

- **格式**：`文件路径: [[起始行号, 结束行号], "步进策略"]`
- **支持策略**：
  - `step_in`：单步进入函数调用
  - `step_over`：单步跳过函数调用
  - `step_out`：单步跳出当前函数
  - `source_step_in`：源码级单步进入
  - `source_step_over`：源码级单步跳过

### 循环检测
为避免在循环中无限步进，工具会检测以下情况：
1. 当同一行代码被命中超过10次时，自动执行`step_out`退出当前帧
2. 当同一分支目标地址被命中超过10次时，自动跳出循环

阈值可通过修改`BRANCH_MAX_TOLERANCE`常量（位于`native_context_tracer/step_handler.py`）调整：
```python
# 默认循环检测阈值
BRANCH_MAX_TOLERANCE = 10
```

### 符号可视化
运行后会生成`symbols.html`文件，在浏览器中打开可查看交互式符号信息，包括：
- 函数调用关系
- 变量值变化
- 内存地址映射

### libc函数参数自动跟踪
#### 功能概述
1. 自动根据ABI规范解析libc函数的参数
2. 在函数调用时记录参数值
3. 在函数返回时记录返回值
4. 只需要配置函数名列表即可工作

#### 配置方法
在`tracer_config.yaml`中添加`libc_functions`配置项：
```yaml
libc_functions:
  - fopen
  - fclose 
  - read
  - write
  - malloc
  - free
```

#### 实现原理
- **ARM64架构**：使用x0-x7寄存器传递前8个参数
- **x86_64架构**：使用rdi, rsi, rdx, rcx, r8, r9寄存器传递前6个参数
- **栈参数**：通过`frame.FindVariable()`获取
- **返回值处理**：存储在x0/rax寄存器中

#### 日志格式
函数调用日志示例：
```
[时间戳] CALL fopen(path="/etc/passwd", mode="r") 
[时间戳] RET fopen => 0x1234 (FILE*)
```

### 源代码基础目录
- **目的**: 用于缩短日志中显示的源代码路径。当源代码路径较长时，可以指定一个基础目录，日志中将显示相对于该基础目录的路径。
- **配置方法**: 在 `tracer_config.yaml` 中设置 `source_base_dir` 为你的项目根目录或源代码的公共父目录。
```yaml
source_base_dir: "/path/to/your/project/src" # 例如：/Users/richard/code/terminal-llm
```
- **效果**: 如果 `source_base_dir` 设置为 `/Users/richard/code/terminal-llm`，那么 `/Users/richard/code/terminal-llm/debugger/lldb/native_context_tracer/step_handler.py` 将显示为 `debugger/lldb/native_context_tracer/step_handler.py`。

### 符号追踪
除了行级追踪，还支持对特定函数符号的进入和退出进行追踪，这对于理解程序执行流程和性能分析非常有用。
通过配置 `tracer_config.yaml` 文件中的以下选项来启用和定制符号追踪：

```yaml
symbol_trace_enabled: true # 启用符号追踪功能
symbol_trace_patterns:    # 定义要追踪的符号模式列表
  - module: "your_executable_name" # 模块名，通常是可执行文件名或动态库名
    regex: "function_prefix.*" # 匹配函数名的正则表达式，例如 "main|my_func_.*"
  - module: "libc.so.6" # 示例：追踪libc库中的函数
    regex: "malloc|free"
symbol_trace_cache_file: "symbol_cache.json" # 可选：符号信息缓存文件路径
```

## 配置选项

### 基本调试选项
| 选项 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `max_steps` | int | 100 | 最大调试步数限制 |
| `log_target_info` | bool | true | 是否记录目标程序信息 |
| `log_module_info` | bool | true | 是否记录模块加载信息 |
| `log_breakpoint_details` | bool | true | 是否记录断点详细信息 |
| `log_mode` | string | "instruction" | 日志模式："source"或"instruction" |
| `call_trace_file` | string | "call_trace.txt" | 调用跟踪输出文件 |

### 步进控制选项
| 选项 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `step_action` | dict | {} | 特定文件的步进策略配置 |
| `skip_modules` | list | [] | 要跳过的模块列表 |
| `skip_source_files` | list | [] | 要跳过的源文件列表 |
| `dump_modules_for_skip` | bool | false | 是否生成跳过模块配置 |
| `dump_source_files_for_skip` | bool | false | 是否生成跳过源文件配置 |
| `skip_symbols_file` | string | "skip_symbols.yaml" | 跳过符号配置文件路径 |

### 符号追踪选项
| 选项 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `symbol_trace_enabled` | bool | false | 全局符号追踪启用开关 |
| `symbol_trace_patterns` | list | [] | 符号追踪模式配置 |
| `symbol_trace_cache_file` | string | null | 符号追踪缓存文件路径 |

### 环境与路径选项
| 选项 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `environment` | dict | {} | 调试环境变量设置 |
| `source_search_paths` | list | [] | 源代码搜索路径 |
| `source_base_dir` | string | "" | 源代码基础目录（用于缩短日志路径） |
| `use_source_cache` | bool | true | 是否使用源代码缓存 |
| `cache_dir` | string | "cache" | 缓存文件目录 |

### 表达式与函数跟踪
| 选项 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `expression_hooks` | list | [] | 表达式钩子配置 |
| `libc_functions` | list | [] | 要跟踪的libc函数列表 |

### UI控制选项
| 选项 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `show_console` | bool | false | 是否显示LLDB控制台窗口 |
| `forward_stdin` | bool | true | 是否转发标准输入到调试程序 |

## 高级主题

### 问题排查

#### `step`指令跳过关键函数调用
`step`指令可能跳过关键函数调用（如`RUN_ALL_TESTS()`），而`stepi`（指令级单步）能正确进入。原因包括：

1. **代码优化干扰调试**
   - 编译器优化（如内联函数）导致源码与汇编指令不对应
   - 示例：`bl 0x1089f419c`调用`RUN_ALL_TESTS()(.thunk.0)`，实际是PLT跳转

2. **Thunk函数干扰**
   - 函数调用被重定向到Thunk封装，调试器`step`可能跳过Thunk层

3. **调试器局限性**
   - `step`依赖源码符号表，在优化代码中易失效；`stepi`直接跟踪机器指令

#### 寻找正确的断点
attach进去后，使用以下命令检查：
```bash
bt       # 查看调用栈
thread list  # 列出所有线程
```

#### lldb API注意事项
LLDB API在某些情况下可能返回不一致结果：
- `process.threads`可能返回空列表（内部锁问题）
- `GetStopReason`需要等待正确结果

### 调试优化
- 改进了无效行条目的处理逻辑，默认继续跟踪
- 增强源代码表达式评估的健壮性
- 优化调试信息处理流程，整合源代码表达式评估
- 支持在步进策略中指定特定行范围的调试行为