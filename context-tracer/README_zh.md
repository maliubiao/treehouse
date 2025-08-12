[English](./README.md)

# Context Tracer (上下文追踪器)

`context-tracer` 是一个为深度调试和性能分析而设计的、强大的独立Python执行追踪器。它能提供关于代码执行流程的详细、实时洞察，并生成功能丰富的交互式HTML报告，用于事后分析。

## ✨ 核心特性

- **详细的执行追踪**: 捕获函数调用、返回值、逐行执行和异常。
- **交互式HTML报告**: 生成一个独立的HTML文件，包含可折叠的调用树、带语法高亮的源代码预览和搜索功能。
- **强大的命令行接口**: 无需修改代码，即可从终端轻松追踪任何Python脚本或模块。
- **高度可配置**: 通过CLI标志或YAML配置文件，精确控制要追踪的内容（特定文件、行范围）、要忽略的内容（系统库、特定函数）以及要捕獲的內容（变量值）。
- **低侵入性**: 可以附加到任何正在运行的脚本上，是调试复杂应用的理想选择。
- **为 Python 3.12+ 准备就绪**: 利用新的 `sys.monitoring` API，在现代Python版本上实现更低开销的追踪。

## 📊 交互式HTML报告

生成的HTML报告是 `context-tracer` 的核心亮点之一，它将复杂的执行流转化为直观的交互式视图。

- **可折叠的调用树**: 清晰地查看调用层级，并可自由展开或折叠任何子树。
- **源码预览**: 点击 "view source" 按钮，可在弹窗中查看高亮显示的源代码。当前行和执行过的行都会被特别标记。
- **聚焦与复制**:
    - **聚焦子树 (🔍)**: 将任何函数调用及其完整的子调用栈在一个新页面中打开，隔离分析。
    - **复制子树 (📋)**: 将子树的文本表示复制到剪贴板。
- **框架模式 (Skeleton View)**: 隐藏所有 `line`, `var`, `trace` 事件，只显示 `call` 和 `return` 的骨架，以便快速概览程序结构。
- **局部详情切换 (👁️)**: 在框架模式下，可以临时显示某个特定子树的完整详情。
- **全局搜索和主题切换**: 快速搜索日志内容，并根据偏好切换代码高亮主题。

## 🚀 快速入门

### 1. 安装

首先，使用`pip`安装开发依赖项，以便您可以构建该软件包。

```bash
# 安装构建依赖
pip install build
# 构建软件包
python -m build
```

然后，安装已构建的软件包：

```bash
# 从 dist 目录安装 .whl 文件
pip install dist/context_tracer-*.whl
```

### 2. 使用方法

#### 追踪一个 Python 脚本

```bash
# 追踪脚本及其参数
context-tracer your_script.py --script-arg1 --script-arg2
```

#### 追踪一个模块

```bash
# 追踪模块及其参数 (注意使用 -- 分隔)
context-tracer -m your_package.main -- --module-arg1
```

执行后，一个日志文件 (`trace.log`) 和一个HTML报告 (`trace_report.html`) 将在当前工作目录下的 `logs` 目录中生成。

#### 示例：追踪脚本并自动打开报告

```bash
context-tracer --open-report --enable-var-trace my_app.py
```

此命令将：
1.  追踪 `my_app.py` 的执行过程。
2.  启用详细的变量赋值追踪。
3.  完成后自动在您的Web浏览器中打开生成的 `trace_report.html`。

## ⚙️ 配置

`context-tracer` 可以通过命令行参数或YAML文件进行配置，以适应更复杂的场景。

### 命令行选项

| 选项 | 简写 | 参数 | 描述 | YAML 键 |
|---|---|---|---|---|
| `--help` | `-h` | | 显示帮助信息并退出。 | `N/A` |
| `--module` | `-m` | `MODULE` | 以模块方式执行和追踪目标。 | `target_module` |
| `--config` | | `PATH` | 从YAML文件加载配置。 | `N/A` |
| `--watch-files` | | `PATTERN` | 要监控的文件模式（支持glob通配符，可多次使用）。 | `watch_files` |
| `--open-report` | | | 完成后自动打开HTML报告。 | `open_report` |
| `--verbose` | | | 显示详细的调试信息。 | `verbose` |
| `--capture-vars`| | `EXPR` | 要捕获的变量表达式（可多次使用）。 | `capture_vars` |
| `--exclude-functions` | | `NAME` | 要排除的函数名（可多次使用）。 | `exclude_functions`|
| `--line-ranges` | | `RANGE` | 要追踪的行范围，格式：`'file:start-end'`。 | `line_ranges` |
| `--enable-var-trace` | | | 启用变量操作的详细追踪。 | `enable_var_trace`|
| `--disable-html`| | | 禁用HTML报告生成。 | `disable_html` |
| `--report-name` | | `NAME` | 自定义HTML报告文件名。 | `report_name` |
| `--include-system` | | | 追踪系统路径和第三方库中的代码。 | `ignore_system_paths: false` |
| `--include-stdlibs` | | `LIB` | 强制追踪指定的标准库（即使忽略系统路径）。 | `include_stdlibs`|
| `--trace-self` | | | 追踪`context-tracer`自身的代码（用于调试）。 | `ignore_self: false` |
| `--trace-c-calls` | | | 追踪C函数的调用 (Python 3.12+)。 | `trace_c_calls` |
| `--start-function` | | `FUNC` | 指定开始追踪的函数，格式：`'file:lineno'`。 | `start_function` |
| `--source-base-dir` | | `PATH` | 设置源码根目录，用于在报告中显示相对路径。 | `source_base_dir`|

### 使用 YAML 配置文件

创建一个 `tracer_config.yaml` 文件：

```yaml
report_name: "my_app_trace.html"
target_files:
  - "src/core/**/*.py"
  - "utils/helpers.py"
enable_var_trace: true
ignore_system_paths: false  # 等同于 --include-system
include_stdlibs:
  - "json"
  - "re"
source_base_dir: "./src"
```

然后使用您的配置运行追踪器：
```bash
context-tracer --config tracer_config.yaml my_app.py
```

### 在代码中使用

对于程序化控制，您可以使用 `@trace` 装饰器或 `TraceContext` 上下文管理器。

#### 使用 `@trace` 装饰器

```python
from context_tracer.tracer import trace

@trace(report_name="my_func_trace.html", enable_var_trace=True)
def function_to_debug(a, b):
    # ... 函数逻辑 ...
    return a + b

function_to_debug(10, 20)
```

#### 使用上下文管理器

```python
from context_tracer.tracer import TraceConfig, TraceContext

config = TraceConfig(
    target_files=["my_module.py"],
    enable_var_trace=True,
    report_name="manual_trace.html"
)

with TraceContext(config):
    # ... 需要被追踪的代码 ...
    import my_module
    my_module.run()
```

## 📦 从源码构建

要从源码构建软件包，您首先需要安装开发依赖项。

```bash
# 以可编辑模式安装软件包及开发依赖
pip install -e .[dev]
```

然后，您可以使用提供的构建脚本：

**在 macOS 或 Linux 上:**
```bash
./build.sh
```

**在 Windows 上:**
```bat
.\build.bat
```

构建产物（一个 `.whl` wheel 文件和一个 `.tar.gz` 源码分发包）将被放置在 `dist/` 目录下。

## 📜 许可证

本项目根据 MIT 许可证授权。