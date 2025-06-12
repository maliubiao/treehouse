# LLDB 测试框架

这是一个用于测试LLDB API功能的自动化测试框架，支持测试统计、过滤和报告功能。

## 功能特性
- 自动在被测程序的main函数设置断点
- 支持加载测试脚本执行LLDB API测试
- **每个测试函数独立运行在全新进程环境中**
- **每个测试函数使用独立的target和进程**
- 支持多次执行被测函数
- 自动编译测试程序（增量编译）
- **支持C和C++测试程序**
- 智能匹配测试脚本与测试程序
- 测试结果统计和报告
- 测试用例自动发现
- 测试过滤和选择执行
- 彩色输出显示
- 值打印测试支持
- **完善的C++标准库类型格式化测试**
- 智能清理编译产物
- 新增等待机制确保程序状态稳定

## 使用说明

### 命名规范
- 测试脚本：`test_<program_name>.py`
- 测试程序：`<program_name>.c` 或 `<program_name>.cpp` 或 `test_<program_name>.c` 或 `test_<program_name>.cpp`
- **测试函数**：
  - 以 `test_` 开头的函数（如 `test_example_function`）
  - 或名为 `run_test` 的函数

例如：
- `test_example.py` 对应 `example.c`、`example.cpp`、`test_example.c` 或 `test_example.cpp`
- `test_value_printing.py` 对应 `value_printing.c`、`value_printing.cpp`、`test_value_printing.c` 或 `test_value_printing.cpp`

### 测试脚本编写指南
在测试脚本中：
1. 程序启动时已在main函数入口停止
2. 使用`context.wait_for_stop()`确保程序处于停止状态
3. 步进操作后应检查程序状态
4. **每个测试函数都是独立运行的**
5. **避免在测试函数之间共享状态**
6. **每个测试函数都会启动全新的程序实例**
7. **每个测试函数使用独立的target和进程**

### C++测试能力
框架支持全面的C++标准库类型测试，包括：
- 基本类型（int, float, char等）
- 序列容器（vector, list, deque）
- 关联容器（map, set, unordered_map, unordered_set）
- 容器适配器（queue, stack）
- 智能指针（shared_ptr, unique_ptr, weak_ptr）
- 元组（tuple）
- 原子类型（atomic）
- 复杂嵌套类型
- 自定义模板类

### C++值格式化输出示例
框架会输出结构化的值信息，格式如下：

```
[C++ VALUE] <变量名> (<类型>):
--------------------------------------------------------------------------------
<格式化后的值>
--------------------------------------------------------------------------------
```

以下是典型的输出示例：

```cpp
// 基本类型
[C++ VALUE] a (int):
--------------------------------------------------------------------------------
(int) 10
--------------------------------------------------------------------------------

// 容器类型
[C++ VALUE] numbers (std::__1::vector<int, std::__1::allocator<int> >):
--------------------------------------------------------------------------------
(std::vector<int>) numbers = size=5 {
  [0] = 1
  [1] = 2
  [2] = 3
  [3] = 4
  [4] = 5
}
--------------------------------------------------------------------------------

// 关联容器
[C++ VALUE] idToName (std::__1::map<int, std::__1::string>):
--------------------------------------------------------------------------------
(std::map<int, std::string>) idToName = size=3 {
  [0] = (first = 1, second = "Alice")
  [1] = (first = 2, second = "Bob")
  [2] = (first = 3, second = "Charlie")
}
--------------------------------------------------------------------------------

// 嵌套容器
[C++ VALUE] nestedContainer (std::__1::vector<std::__1::map<int, std::__1::string> >):
--------------------------------------------------------------------------------
(std::vector<std::map<int, std::string> >) nestedContainer = size=2 {
  [0] = size=2 {
    [0] = (first = 1, second = "one")
    [1] = (first = 2, second = "two")
  }
  [1] = size=2 {
    [0] = (first = 3, second = "three")
    [1] = (first = 4, second = "four")
  }
}
--------------------------------------------------------------------------------

// 智能指针
[C++ VALUE] sharedObj (std::__1::shared_ptr<ComplexType>):
--------------------------------------------------------------------------------
(std::__1::shared_ptr<ComplexType>) -> (ComplexType) {
  id: (int) 1,
  name: (std::string) name = "shared",
  values: (std::vector<int>) values = size=3 {
    [0] = 10
    [1] = 20
    [2] = 30
  }
}
--------------------------------------------------------------------------------

// 元组
[C++ VALUE] complexTuple (std::__1::tuple<int, double, std::__1::string>):
--------------------------------------------------------------------------------
(std::tuple<int, double, std::string>) complexTuple = size=3 {
  [0] = 10
  [1] = 3.1400000000000001
  [2] = "pi"
}
--------------------------------------------------------------------------------

// 自定义类型
[C++ VALUE] obj (TestClass):
--------------------------------------------------------------------------------
(TestClass) {m_value: (int) 42}
--------------------------------------------------------------------------------
```

### 基本用法
```bash
# 自动编译所有测试程序
python3 lldb_tester.py --build

# 运行所有测试
python3 lldb_tester.py

# 运行指定测试
python3 lldb_tester.py -t test_scripts/test_cpp_example.py

# 使用通配符运行测试
python3 lldb_tester.py -p "test_*.py"

# 失败后继续执行
python3 lldb_tester.py --continue-on-failure

# 测试后清理编译产物
python3 lldb_tester.py --clean
```

### 测试目录结构
```
test_programs/    # 存放被测程序源代码(.c/.cpp文件)
test_scripts/     # 存放测试脚本(.py文件)
```

### 输出示例
```
[PASSED] test_example.py (0.32s)
[PASSED] test_value_printing.py (1.15s)
[PASSED] test_cpp_example.py (2.41s)

=== Test Summary ===
Total: 3, Passed: 3, Failed: 0, Skipped: 0
```

### 注意事项
1. 测试程序使用增量编译策略，仅当源文件更新时重新编译
2. C程序使用gcc编译，C++程序使用g++编译
3. 使用`--clean`参数仅删除编译产物（可执行文件和dSYM目录），保留源代码
4. 测试脚本必须在`test_scripts`目录下且遵循命名规范
5. 确保LLDB Python绑定已正确安装
6. 使用`--build`参数可预编译所有测试程序
7. 测试程序文件名可以带或不带`test_`前缀
8. 测试函数需命名为`run_test`或以`test_`开头
9. 测试脚本中应使用`wait_for_stop()`确保程序状态
10. **每个测试函数都会启动全新的程序实例**
11. **避免在测试函数之间共享状态**
12. **框架会为每个测试函数创建独立的target和进程**
13. **C++测试需要编译器支持C++11或更高版本**