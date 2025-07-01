# 🤖 AI 驱动的 Python 单元测试生成器

这是一个利用运行时分析和大型语言模型（LLM）自动为您的 Python 函数生成单元测试的工具。您只需通过一个简单的装饰器指定目标函数，正常运行您的代码，然后就能在程序结束时获得一个完整的、可运行的 `unittest` 测试文件。

## ✨ 核心特性

- **基于运行时生成**: 测试用例是根据函数在实际执行中的输入、输出和异常来创建的，确保测试的真实性和相关性。
- **零侵入式集成**: 只需一个装饰器 (`@generate_unit_tests`) 即可启动，无需修改您的函数逻辑。
- **智能 Mocking**: 自动识别并 mock 外部依赖（如 `time.sleep`, 文件I/O, API调用等），让您专注于核心业务逻辑的测试。
- **批量处理**: 能够一次性为多个函数生成测试，并将它们智能地组织在同一个测试文件中。
- **高度可定制**: 提供丰富的参数，允许您控制输出目录、模型选择、交互行为等。
- **兼容现有测试**: 如果测试文件已存在，它能智能地将新的测试用例合并到现有的 `TestCase` 类中，而不是粗暴地覆盖。

## ⚙️ 工作流程

本工具的工作流程简单而强大：

1.  **装饰**: 您在代码的一个入口函数上（例如 `main` 函数或测试脚本的启动函数）添加 `@generate_unit_tests` 装饰器。
2.  **指定目标**: 在装饰器中，您通过 `target_functions` 参数告知工具您希望为哪些函数生成测试。
3.  **正常运行**: 像往常一样运行您的 Python 脚本。
4.  **运行时跟踪**: 装饰器会在后台启动一个跟踪器，当您的目标函数被调用时，它会悄悄地记录下所有关键信息：传入的参数、返回值、抛出的异常以及对其他函数的调用。
5.  **LLM 生成**: 当您的脚本执行完毕后，工具会整理收集到的运行时数据，构建一个详细的提示（Prompt），并将其发送给语言模型。
6.  **获取结果**: LLM 会返回一个完整的 Python 单元测试文件。该文件包含了所有必要的导入、动态的 `sys.path` 设置、测试类、以及基于运行时数据生成的测试方法（包括断言和 Mock）。

---

## 🚀 快速上手

让我们通过一个具体的例子来感受一下它的威力。

### 步骤 1: 准备您的代码

假设我们有以下文件 `debugger/demo_analyzer.py`，其中包含一些我们想要测试的函数。

```python
# debugger/demo_analyzer.py
import time
from debugger.unit_test_generator_decorator import generate_unit_tests

def faulty_sub_function(x):
    """一个会抛出异常的子函数"""
    if x > 150:
        raise ValueError("输入值不能大于 150")
    return x * 10

def complex_sub_function(a, b):
    """一个包含循环和变量变化的子函数"""
    total = a
    for idx in range(b):
        total += idx + 1
        time.sleep(0.01) # 这是一个外部依赖，应该被 mock

    try:
        result = faulty_sub_function(total)
    except ValueError:
        result = -1

    return result

# 使用装饰器自动生成单元测试
# - target_functions: 指定为同一个文件中的两个函数，它们将被批量处理
# - auto_confirm: 自动接受所有LLM建议，无需手动确认
@generate_unit_tests(
    target_functions=["complex_sub_function", "faulty_sub_function"],
    output_dir="generated_tests",
    auto_confirm=True
)
def main_entrypoint(val1, val2):
    """演示的主入口函数"""
    print("--- 开始执行主函数 ---")
    intermediate_result = complex_sub_function(val1, val2)
    final_result = complex_sub_function(intermediate_result, 0)
    print(f"最终结果: {final_result}")
    print("--- 主函数执行完毕 ---")
    return final_result

if __name__ == "__main__":
    main_entrypoint(10, 20)
```

### 步骤 2: 运行脚本

在您的终端中，直接运行这个 Python 文件：

```bash
python debugger/demo_analyzer.py
```

您会看到程序的正常输出，紧接着是测试生成器开始工作的日志。

### 步骤 3: 查看生成的测试文件

运行结束后，检查您在 `output_dir` 中指定的目录 (`generated_tests`)。您会发现一个新的测试文件，例如 `test_demo_analyzer.py`。其内容将非常接近下面的示例：

```python
# generated_tests/test_demo_analyzer.py

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from debugger.demo_analyzer import complex_sub_function, faulty_sub_function


class TestDemoAnalyzer(unittest.TestCase):
    """
    Test suite for functions in demo_analyzer.
    """

    @patch("debugger.demo_analyzer.faulty_sub_function")
    @patch("time.sleep")
    def test_complex_sub_function_handles_value_error(self, mock_sleep, mock_faulty_sub):
        """
        Test case for complex_sub_function where faulty_sub_function raises a ValueError.
        """
        # --- Arrange ---
        # Configure the mock to simulate the captured behavior
        mock_faulty_sub.side_effect = ValueError("输入值不能大于 150")
        
        a = 10
        b = 20

        # --- Act ---
        result = complex_sub_function(a, b)

        # --- Assert ---
        # Assert the function returned the expected value after catching the exception
        self.assertEqual(result, -1)
        # Verify that the mocked dependency was called correctly
        mock_faulty_sub.assert_called_once_with(220)
        # Verify time.sleep was called
        self.assertEqual(mock_sleep.call_count, 20)

    @patch("debugger.demo_analyzer.faulty_sub_function")
    @patch("time.sleep")
    def test_complex_sub_function_success_path(self, mock_sleep, mock_faulty_sub):
        """
        Test case for complex_sub_function with a successful execution path.
        """
        # --- Arrange ---
        mock_faulty_sub.return_value = -10 # Simulate the return value
        
        a = -1
        b = 0

        # --- Act ---
        result = complex_sub_function(a, b)

        # --- Assert ---
        self.assertEqual(result, -10)
        mock_faulty_sub.assert_called_once_with(-1)
        mock_sleep.assert_not_called() # The loop was not entered

    def test_faulty_sub_function_raises_error(self):
        """
        Test that faulty_sub_function raises ValueError for large inputs.
        """
        # --- Arrange ---
        x = 220
        
        # --- Act & Assert ---
        with self.assertRaises(ValueError) as cm:
            faulty_sub_function(x)
        self.assertEqual(str(cm.exception), "输入值不能大于 150")

    def test_faulty_sub_function_returns_value(self):
        """
        Test that faulty_sub_function returns correct value for valid inputs.
        """
        # --- Arrange ---
        x = -1

        # --- Act ---
        result = faulty_sub_function(x)

        # --- Assert ---
        self.assertEqual(result, -10)


if __name__ == "__main__":
    unittest.main()

```
**看！** 这个文件是完全自包含且可立即运行的。它自动处理了：
- `sys.path` 的设置，使其可移植。
- 对 `time.sleep` 和 `faulty_sub_function` 的 `patch`（mock）。
- 基于运行时捕获到的真实数据（如 `a=10, b=20`）设置测试场景。
- 对正常返回值 (`assertEqual`) 和异常 (`assertRaises`) 的断言。
- 验证 mock 对象是否被正确调用 (`assert_called_once_with`)。

---

## 📖 详细配置与使用

`@generate_unit_tests` 装饰器接受多个参数，让您可以精细地控制其行为。

| 参数 | 类型 | 默认值 | 描述 |
| --- | --- | --- | --- |
| `target_functions` | `List[str]` | **(必需)** | 一个字符串列表，包含您希望生成测试的函数名称。 |
| `output_dir` | `str` | `"generated_tests"` | 生成的单元测试文件存放的目录。 |
| `report_dir` | `str` | `"call_reports"` | 存放中间产物——JSON 格式的运行时分析报告。 |
| `auto_confirm` | `bool` | `False` | 是否自动确认所有交互式提示（如文件名建议、文件合并）。在CI/CD环境或脚本化执行时非常有用。 |
| `enable_var_trace`| `bool` | `True` | 是否在运行时跟踪变量的变化。通常保持开启以提供更丰富的上下文。 |
| `model_name` | `str` | `"deepseek-r1"` | 用于生成测试代码的核心 LLM 模型名称。 |
| `checker_model_name`| `str` | `"deepseek-v3"` | 用于辅助任务（如命名建议、代码合并）的模型。通常可使用一个更快、更便宜的模型。 |
| `use_symbol_service`| `bool` | `True` | **上下文策略**。`True` (默认) 表示使用符号服务，只提取目标函数及其依赖的精确代码片段作为上下文，速度快、成本低。`False` 表示将整个源文件的内容作为上下文，更完整但可能更慢、更贵。 |
| `trace_llm` | `bool` | `False` | 是否记录与 LLM 的完整交互（prompt 和 response）。用于调试生成器本身。 |
| `llm_trace_dir` | `str` | `"llm_traces"` | 如果 `trace_llm` 为 `True`，交互日志将保存在此目录。 |

### 高级用法：多个入口点

如果您在多个地方使用了 `@generate_unit_tests` 装饰器，程序退出时，生成器会依次处理每一个。为了避免对同一个目标函数重复生成测试，建议为不同的测试任务配置不同的 `output_dir`，或者确保一个函数只被一个测试任务所覆盖。

---

## 🛠️ 独立的调试追踪工具 (`tracer`)

除了AI单元测试生成，本库还包含一个功能强大的独立执行追踪器 `tracer`。您可以用它来调试任何 Python 脚本，深入理解其执行流程，而无需生成测试。它会将追踪信息实时输出到控制台，并生成一份详细、可交互的 HTML 报告。

`tracer` 可以通过三种方式使用：**命令行**、**YAML配置文件** 或 **在代码中直接调用**。

### 1. 通过命令行 (CLI) 使用

这是最直接的使用方式，适合快速调试脚本。

**基本语法:**
```bash
python -m debugger.tracer_main [OPTIONS] <your_script.py> [SCRIPT_ARGUMENTS]
```

**命令行选项:**

| 选项 (Option) | YAML 键 (Key) | 描述 |
| --- | --- | --- |
| `-h`, `--help` | N/A | 显示帮助信息并退出。 |
| `--config <path>` | N/A | 指定一个 YAML 配置文件路径。 |
| `--watch-files <pattern>` | `target_files` | 要追踪的文件模式，支持通配符 (例如: `src/**/*.py`)。可多次使用。 |
| `--capture-vars <expr>` | `capture_vars` | 在每一步要捕获并显示的变量或表达式。可多次使用。 |
| `--exclude-functions <name>` | `exclude_functions` | 要从追踪中排除的函数名。可多次使用。 |
| `--line-ranges <file:start-end>`| `line_ranges`| 仅追踪特定文件的指定行号范围 (例如: `app.py:50-100`)。 |
| `--enable-var-trace` | `enable_var_trace` | 启用详细的变量赋值追踪（可能影响性能）。 |
| `--report-name <name.html>` | `report_name` | 自定义生成的 HTML 报告文件名。 |
| `--open-report` | `open_report` | 追踪结束后自动在浏览器中打开 HTML 报告。 |
| `--disable-html` | `disable_html` | 禁止生成 HTML 报告。 |
| `--include-system` | (反) `ignore_system_paths` | 默认忽略标准库和第三方库，使用此选项以包含它们。 |
| `--include-stdlibs <name>` | `include_stdlibs`| 即使在忽略系统库时，也强制追踪指定的标准库 (例如: `json`, `re`)。可多次使用。 |
| `--trace-self` | (反) `ignore_self` | 包含追踪器自身的代码执行（用于调试 `tracer`）。 |
| `--start-function <file:lineno>` | `start_function` | 从指定文件和行号的函数调用开始追踪。 |
| `--source-base-dir <path>` | `source_base_dir` | 设置源代码的根目录，用于在报告中显示更简洁的相对路径。 |

**示例:**

```bash
# 基本用法：追踪一个脚本
python -m debugger.tracer_main my_script.py

# 追踪脚本，并传递参数给脚本
python -m debugger.tracer_main my_script.py --user=test --mode=fast

# 复杂用法：指定追踪范围、捕获变量并自动打开报告
python -m debugger.tracer_main \
    --watch-files="src/core/*.py" \
    --capture-vars="app_state.user_id" \
    --exclude-functions="log_message" \
    --open-report \
    my_script.py
```

### 2. 通过 YAML 文件配置

对于复杂或需要复用的配置，使用 YAML 文件是最佳选择。

**使用方法:**
```bash
python -m debugger.tracer_main --config my_tracer_config.yaml my_script.py
```

**示例 `my_tracer_config.yaml`:**
```yaml
# 报告文件名
report_name: "trace_report_for_my_app.html"

# 追踪的目标文件模式列表
target_files:
  - "src/core/**/*.py"
  - "utils/helpers.py"

# 要捕获的变量/表达式列表
capture_vars:
  - "user_id"
  - "context['request_id']"

# 要忽略的函数列表
exclude_functions:
  - "log_message"
  - "_internal_helper"

# 启用变量赋值追踪
enable_var_trace: true

# 默认不追踪系统库...
ignore_system_paths: true
# ...但是，特别追踪 'json' 和 're' 这两个标准库
include_stdlibs:
  - "json"
  - "re"

# 源代码根目录
source_base_dir: "./src"
```
> **注意**: 命令行中指定的参数会覆盖 YAML 文件中的相同设置。

### 3. 在代码中编程方式使用

您也可以在代码中导入并启动追踪器，这对于需要精细控制追踪启停时机或在现有测试框架中集成非常有用。

#### a) 使用 `@trace` 装饰器

这是为单个函数（及其调用的一切）启用追踪的最简单方法。

```python
from debugger.tracer import trace

@trace(report_name="my_func_trace.html", enable_var_trace=True)
def function_to_debug(a, b):
    # ... 函数逻辑 ...
    c = a + b
    return c

function_to_debug(10, 20)
```

#### b) 使用 `start_trace` 和 `stop_trace`

这种方式提供了最大的灵活性。

```python
from debugger import tracer

# 创建一个配置对象
config = tracer.TraceConfig(
    target_files=["my_module.py"],
    enable_var_trace=True,
    report_name="manual_trace.html"
)

# 启动追踪
t = tracer.start_trace(config=config)

try:
    # ... 在这里运行您想调试的代码 ...
    import my_module
    my_module.run()
finally:
    # 停止追踪并生成报告
    tracer.stop_trace(t)
```

### 追踪输出

- **控制台**: 实时显示彩色的执行流，包括函数调用（`↘ CALL`）、返回值（`↗ RETURN`）、执行的代码行（`▷ LINE`）和异常（`⚠ EXCEPTION`）。
- **HTML 报告**: 在 `debugger/logs/` 目录下生成一份交互式报告。它提供可折叠的调用树、源代码预览、执行行高亮和搜索功能，是事后分析的强大工具。