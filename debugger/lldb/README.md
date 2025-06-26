# LLDB Tracer

高级LLDB调试工具，提供源代码行级变量跟踪，提供汇编级指令跟踪及寄存器内存使用跟踪

## 使用示例

基本使用：
```bash
./tracer_main.py -e /path/to/program -a arg1 -a arg2
```

启用详细日志：
```bash
./tracer_main.py -e /path/to/program --verbose
```

生成跳过模块配置：
```bash
./tracer_main.py -e /path/to/program --dump-modules-for-skip
```

## 新功能

### 环境变量配置
在配置文件中设置环境变量：
```yaml
# tracer_config.yaml
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

阈值可通过修改`BRANCH_MAX_TOLERANCE`常量（位于`tracer/step_handler.py`）调整：
```python
# 默认循环检测阈值
BRANCH_MAX_TOLERANCE = 10
```

### 符号可视化
运行后会生成`symbols.html`文件，在浏览器中打开可查看交互式符号信息，包括：
- 函数调用关系
- 变量值变化
- 内存地址映射

## libc函数参数自动跟踪功能

### 功能概述
1. 自动根据ABI规范解析libc函数的参数
2. 在函数调用时记录参数值
3. 在函数返回时记录返回值
4. 只需要配置函数名列表即可工作

### 配置方法
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

### 实现原理
- **ARM64架构**：使用x0-x7寄存器传递前8个参数
- **x86_64架构**：使用rdi, rsi, rdx, rcx, r8, r9寄存器传递前6个参数
- **栈参数**：通过`frame.FindVariable()`获取
- **返回值处理**：存储在x0/rax寄存器中

### 日志格式
函数调用日志示例：
```
[时间戳] CALL fopen(path="/etc/passwd", mode="r") 
[时间戳] RET fopen => 0x1234 (FILE*)
```

## 调试优化
- 改进了无效行条目的处理逻辑，默认继续跟踪
- 增强源代码表达式评估的健壮性
- 优化调试信息处理流程，整合源代码表达式评估
- 支持在步进策略中指定特定行范围的调试行为
- 支持在步进策略中指定特定行范围的调试行为

### 源代码基础目录 (source_base_dir)
- **目的**: 用于缩短日志中显示的源代码路径。当源代码路径较长时，可以指定一个基础目录，日志中将显示相对于该基础目录的路径。
- **配置方法**: 在 `tracer_config.yaml` 中设置 `source_base_dir` 为你的项目根目录或源代码的公共父目录。
```yaml
source_base_dir: "/path/to/your/project/src" # 例如：/Users/richard/code/terminal-llm
```
- **效果**: 如果 `source_base_dir` 设置为 `/Users/richard/code/terminal-llm`，那么 `/Users/richard/code/terminal-llm/debugger/lldb/tracer/step_handler.py` 将显示为 `debugger/lldb/tracer/step_handler.py`。


`step`指令跳过关键函数调用（如`RUN_ALL_TESTS()`），而`stepi`（指令级单步）能正确进入。以下是根本原因和解决方案：

---

### **问题原因**
1. **代码优化干扰调试**
   - 编译器优化（如内联函数）导致源码与汇编指令不对应。`RUN_ALL_TESTS()`被内联或通过PLT跳转表调用，`step`基于源码行号单步，无法追踪优化后的跳转逻辑。
   - 示例：`bl 0x1089f419c`调用`RUN_ALL_TESTS()(.thunk.0)`，实际是PLT跳转（`adrp`+`add`+`br`组合），`step`无法识别此跳转。

2. **Thunk函数干扰**
   - 函数调用被重定向到Thunk封装（如`RUN_ALL_TESTS() (.thunk.0)`），调试器`step`可能跳过Thunk层，直接停在目标函数后。

3. **调试器局限性**
   - `step`依赖源码符号表，在优化代码中易失效；`stepi`直接跟踪机器指令，不受源码结构影响。


### 寻找正确的断点
attach进去, bt , thread list , 挨个检查   

### lldb的api bug
如果process.threads为0， 这是个错误，api 错误，它内部其试一次获取锁，如果一次失败，会获取到空值，去掉这个锁，重编译，其实循环在一秒内，通常能获取到正常的内容, 如果不是立刻的话，GetStopReason特别这个api，如果不等到它的正确结果，不知道进程为什么停止   
```cpp
SBThread SBProcess::GetThreadAtIndex(size_t index) {
  LLDB_INSTRUMENT_VA(this, index);

  SBThread sb_thread;
  ThreadSP thread_sp;
  ProcessSP process_sp(GetSP());
  if (process_sp) {
    Process::StopLocker stop_locker; //删除
    if (stop_locker.TryLock(&process_sp->GetRunLock())) { //删除
      std::lock_guard<std::recursive_mutex> guard(
          process_sp->GetTarget().GetAPIMutex());
      thread_sp = process_sp->GetThreadList().GetThreadAtIndex(index, false);
      sb_thread.SetThread(thread_sp);
    } //删除
  }
```

### 符号追踪 (Symbol Tracing)
除了行级追踪，还支持对特定函数符号的进入和退出进行追踪，这对于理解程序执行流程和性能分析非常有用。
通过配置 `tracer_config.yaml` 文件中的以下选项来启用和定制符号追踪：

```yaml
# tracer_config.yaml 示例
enable_symbol_trace: true # 启用符号追踪功能
symbol_trace_patterns:    # 定义要追踪的符号模式列表
  - module: "your_executable_name" # 模块名，通常是可执行文件名或动态库名
    regex: "function_prefix.*" # 匹配函数名的正则表达式，例如 "main|my_func_.*"
  - module: "libc.so.6" # 示例：追踪libc库中的函数
    regex: "malloc|free"
# symbol_trace_cache_file: "symbol_cache.json" # 可选：符号信息缓存文件路径，默认为空
```
- `enable_symbol_trace`: 布尔值，设置为 `true` 启用符号追踪。
- `symbol_trace_patterns`: 列表，每个元素是一个字典，包含 `module` 和 `regex` 字段。
  - `module`: 字符串，指定要追踪的模块名（例如，可执行文件名称或动态库名称）。
  - `regex`: 字符串，一个正则表达式，用于匹配模块内要追踪的函数符号名称。
- `symbol_trace_cache_file`: 字符串，可选，指定一个文件路径用于缓存已匹配的符号信息，以加速后续启动。

