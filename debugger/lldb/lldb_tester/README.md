# LLDB 测试框架

这是一个用于测试LLDB API功能的自动化测试框架，支持测试统计、过滤和报告功能。

## 功能特性
- 自动在被测程序的main函数设置断点
- 支持加载测试脚本执行LLDB API测试
- **每个测试函数独立运行在全新进程环境中**
- **每个测试函数使用独立的target和进程**
- 支持多次执行被测函数
- 自动编译测试程序（增量编译）
- 智能匹配测试脚本与测试程序
- 测试结果统计和报告
- 测试用例自动发现
- 测试过滤和选择执行
- 彩色输出显示
- 值打印测试支持
- 智能清理编译产物
- 新增等待机制确保程序状态稳定

## 使用说明

### 命名规范
- 测试脚本：`test_<program_name>.py`
- 测试程序：`<program_name>.c` 或 `test_<program_name>.c`
- **测试函数**：
  - 以 `test_` 开头的函数（如 `test_example_function`）
  - 或名为 `run_test` 的函数
  
例如：
- `test_example.py` 对应 `example.c` 或 `test_example.c`
- `test_value_printing.py` 对应 `value_printing.c` 或 `test_value_printing.c`

### 测试脚本编写指南
在测试脚本中：
1. 程序启动时已在main函数入口停止
2. 使用`context.wait_for_stop()`确保程序处于停止状态
3. 步进操作后应检查程序状态
4. **每个测试函数都是独立运行的**
5. **避免在测试函数之间共享状态**
6. **每个测试函数都会启动全新的程序实例**
7. **每个测试函数使用独立的target和进程**

### 基本用法
```bash
# 自动编译所有测试程序
python3 lldb_tester.py --build

# 运行所有测试
python3 lldb_tester.py

# 运行指定测试
python3 lldb_tester.py -t test_scripts/test_example.py

# 使用通配符运行测试
python3 lldb_tester.py -p "test_*.py"

# 失败后继续执行
python3 lldb_tester.py --continue-on-failure

# 测试后清理编译产物
python3 lldb_tester.py --clean
```

### 测试目录结构
```
test_programs/    # 存放被测程序源代码(.c文件)
test_scripts/     # 存放测试脚本(.py文件)
```

### 输出示例
```
[PASSED] test_example.py (0.32s)
[PASSED] test_value_printing.py (1.15s)

=== Test Summary ===
Total: 2, Passed: 2, Failed: 0, Skipped: 0
```

### 注意事项
1. 测试程序使用增量编译策略，仅当源文件更新时重新编译
2. 使用`--clean`参数仅删除编译产物（可执行文件和dSYM目录），保留源代码
3. 测试脚本必须在`test_scripts`目录下且遵循命名规范
4. 确保LLDB Python绑定已正确安装
5. 使用`--build`参数可预编译所有测试程序
6. 测试程序文件名可以带或不带`test_`前缀
7. 测试函数需命名为`run_test`或以`test_`开头
8. 测试脚本中应使用`wait_for_stop()`确保程序状态
9. **每个测试函数都会启动全新的程序实例**
10. **避免在测试函数之间共享状态**
11. **框架会为每个测试函数创建独立的target和进程**