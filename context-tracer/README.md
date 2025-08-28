[中文](./README_zh.md)

# Context Tracer

`context-tracer` is a powerful, standalone Python execution tracer designed for deep debugging and performance analysis. It provides detailed, real-time insights into your code's execution flow and generates a rich, interactive HTML report for post-mortem analysis.

## ✨ Core Features

- **Detailed Execution Tracing**: Captures function calls, return values, line-by-line execution, and exceptions.
- **Interactive HTML Reports**: Generates a self-contained HTML file with a foldable call tree, source code preview with syntax highlighting, and search functionality.
- **Powerful Command-Line Interface**: Easily trace any Python script or module from the terminal without code modification.
- **Highly Configurable**: Control what to trace (specific files, line ranges), what to ignore (system libraries, specific functions), and what to capture (variable values) through CLI flags or a YAML config file.
- **Low Intrusion**: Can be attached to any running script, making it ideal for debugging complex applications.
- **Python 3.12+ Ready**: Leverages the new `sys.monitoring` API for lower overhead tracing on modern Python versions.
- **Timeout Protection**: Supports setting timeout limits to prevent long-running scripts from consuming excessive resources.

## 📊 The Interactive HTML Report

The generated HTML report is a key feature of `context-tracer`, turning a complex execution flow into an intuitive, interactive view.

- **Foldable Call Tree**: Clearly view the call hierarchy and freely expand or collapse any subtree.
- **Source Preview**: Click the "view source" button to see highlighted source code in a popup. The current line and executed lines are specially marked.
- **Focus & Copy**:
    - **Focus Subtree (🔍)**: Open any function call and its complete sub-call stack in a new page for isolated analysis.
    - **Copy Subtree (📋)**: Copy the text representation of a subtree to the clipboard.
- **Skeleton View**: Hide all `line`, `var`, and `trace` events to show only the `call` and `return` skeleton, providing a quick overview of the program structure.
- **Toggle Details (👁️)**: In skeleton mode, temporarily show the full details for a specific subtree.
- **Global Search and Theme Switching**: Quickly search through log messages and change the code highlight theme to your preference.
- **Navigation Bar**: Navigate long trace documents easily with the interactive scrollbar that shows a visual overview of the entire document structure and allows quick jumping to any position.

## 🚀 Quick Start

### 1. Installation

First, install the development dependencies using `pip` so you can build the package.

```bash
# Install build dependencies
pip install build
# Build the package
python -m build
```

Then, install the built package:

```bash
# Install the .whl file from the dist directory
pip install dist/context_tracer-*.whl
```

### 2. Usage

#### Trace a Python Script

```bash
# Trace a script and its arguments
context-tracer your_script.py --script-arg1 --script-arg2
```

#### Trace a Module

```bash
# Trace a module and its arguments (note the -- separator)
context-tracer -m your_package.main -- --module-arg1
```

After execution, a log file (`trace.log`) and an HTML report (`trace_report.html`) will be generated in a `logs` directory within your current working directory.

#### Example: Trace a script and automatically open the report

```bash
context-tracer --open-report --enable-var-trace my_app.py
```

This command will:
1.  Trace the execution of `my_app.py`.
2.  Enable detailed variable assignment tracing.
3.  Automatically open the generated `trace_report.html` in your web browser upon completion.

#### Example: Set timeout limit

```bash
# Set 3-second timeout to prevent long-running scripts
context-tracer --timeout 3 long_running_script.py
```

This command will:
1.  Trace the execution of `long_running_script.py`.
2.  Automatically terminate the trace and return exit code 124 if it runs longer than 3 seconds.

## ⚙️ Configuration

`context-tracer` can be configured via command-line arguments or a YAML file for more complex scenarios.

### Command-Line Options

| Option | Shorthand | Argument | Description | YAML Key |
|---|---|---|---|---|
| `--help` | `-h` | | Show help message and exit. | `N/A` |
| `--module` | `-m` | `MODULE` | Execute and trace a target as a module. | `target_module` |
| `--config` | | `PATH` | Load configuration from a YAML file. | `N/A` |
| `--watch-files` | | `PATTERN` | File patterns to monitor (supports glob, use multiple times). | `watch_files` |
| `--open-report` | | | Automatically open the HTML report upon completion. | `open_report` |
| `--verbose` | | | Display verbose debugging information. | `verbose` |
| `--capture-vars`| | `EXPR` | Variable expressions to capture (use multiple times). | `capture_vars` |
| `--exclude-functions` | | `NAME` | Function names to exclude (use multiple times). | `exclude_functions`|
| `--line-ranges` | | `RANGE` | Line ranges to trace, format: `'file:start-end'`. | `line_ranges` |
| `--enable-var-trace` | | | Enable detailed tracing of variable operations. | `enable_var_trace`|
| `--disable-html`| | | Disable HTML report generation. | `disable_html` |
| `--report-name` | | `NAME` | Custom filename for the HTML report. | `report_name` |
| `--include-system` | | | Trace code in system paths and third-party libraries. | `ignore_system_paths: false` |
| `--include-stdlibs` | | `LIB` | Force tracing specific stdlibs (even if system paths are ignored). | `include_stdlibs`|
| `--trace-self` | | | Trace `context-tracer`'s own code (for debugging). | `ignore_self: false` |
| `--trace-c-calls` | | | Trace calls to C functions (Python 3.12+). | `trace_c_calls` |
| `--start-function` | | `FUNC` | Specify a function to start tracing from, format: `'file:lineno'`. | `start_function` |
| `--source-base-dir` | | `PATH` | Set the source root directory for relative paths in the report. | `source_base_dir`|
| `--timeout` | | `SECONDS` | Timeout in seconds, force termination after this time | `timeout_seconds`|

### Using a YAML configuration file

Create a `tracer_config.yaml` file:

```yaml
report_name: "my_app_trace.html"
target_files:
  - "src/core/**/*.py"
  - "utils/helpers.py"
enable_var_trace: true
ignore_system_paths: false  # Equivalent to --include-system
include_stdlibs:
  - "json"
  - "re"
source_base_dir: "./src"
timeout_seconds: 30  # Set 30-second timeout
```

Then run the tracer with your config:
```bash
context-tracer --config tracer_config.yaml my_app.py
```

### In-Code Usage

For programmatic control, you can use the `@trace` decorator or the `TraceContext` context manager.

#### Using the `@trace` decorator

```python
from context_tracer.tracer import trace

@trace(report_name="my_func_trace.html", enable_var_trace=True)
def function_to_debug(a, b):
    # ... function logic ...
    return a + b

function_to_debug(10, 20)
```

#### Using the context manager

```python
from context_tracer.tracer import TraceConfig, TraceContext

config = TraceConfig(
    target_files=["my_module.py"],
    enable_var_trace=True,
    report_name="manual_trace.html",
    timeout_seconds=60  # Set 60-second timeout
)

with TraceContext(config):
    # ... code to be traced ...
    import my_module
    my_module.run()
```

## 📦 Building from Source

To build the package from source, you first need to install the development dependencies.

```bash
# Install the package in editable mode with development dependencies
pip install -e .[dev]
```

Then, you can use the provided build scripts:

**On macOS or Linux:**
```bash
./build.sh
```

**On Windows:**
```bat
.\build.bat
```

The build artifacts (a `.whl` wheel file and a `.tar.gz` source distribution) will be placed in the `dist/` directory.

## 📜 License

This project is licensed under the MIT License.