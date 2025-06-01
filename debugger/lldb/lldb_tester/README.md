# LLDB 测试框架

这是一个用于测试LLDB API功能的自动化测试框架，支持测试统计、过滤和报告功能。

## 功能特性
- 自动在被测程序的main函数设置断点
- 支持加载测试脚本执行LLDB API测试
- 测试完成后自动重启进程
- 支持多次执行被测函数
- 提供测试程序管理
- 测试结果统计和报告
- 测试用例自动发现
- 测试过滤和选择执行
- 彩色输出显示

## 使用说明

### 配置文件(config.json)
```json
{
    "test_program": "path/to/test_program",
    "test_script": "path/to/test_script.py"  # 可选，单个测试时使用
}
```

### 基本用法
```bash
# 运行所有测试
python3 lldb_tester.py -c config.json

# 运行单个测试
python3 lldb_tester.py -c config.json -t test_scripts/test_example.py

# 列出所有可用测试
python3 lldb_tester.py -c config.json --list-tests

# 使用通配符运行测试
python3 lldb_tester.py -c config.json -p "test_*.py"

# 失败后继续执行
python3 lldb_tester.py -c config.json --continue-on-failure
```

### 测试脚本规范
测试脚本必须包含`run_test(lldb_instance)`函数，例如：
```python
def run_test(lldb_instance):
    # 设置断点
    lldb_instance.HandleCommand("breakpoint set --name test_function")
    
    # 继续执行
    lldb_instance.HandleCommand("continue")
    
    # 验证结果
    frame = lldb_instance.GetSelectedTarget().GetProcess().GetSelectedThread().GetSelectedFrame()
    if frame.GetFunctionName() != "test_function":
        raise AssertionError("Failed to stop at test_function")
```

### 测试目录结构
```
test_programs/    # 存放被测程序
test_scripts/     # 存放测试脚本
```

### 输出示例
```
[PASSED] test_example.py (0.32s)
[FAILED] test_error.py (0.15s): Failed to stop at test_function

=== Test Summary ===
Total: 2, Passed: 1, Failed: 1, Skipped: 0

=== Failed Tests ===
test_error.py: Failed to stop at test_function
```