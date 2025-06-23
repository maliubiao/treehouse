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
