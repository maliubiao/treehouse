# Sys.Monitoring 异步追踪测试

本测试演示了 Python `sys.monitoring` 系统在追踪异步操作、并发协程和深层调用栈方面的能力。

## 目的

本测试旨在：
- 展示 `sys.monitoring` 对 async/await 操作的追踪能力
- 演示具有独立深层调用栈的多个协程的并发执行
- 测试监控系统如何处理不同协程间的交错执行
- 提供包含错误处理和生成器的复杂异步模式示例

## 主要特性

### 并发协程与深层调用栈
- `deep_stack_operation_a()`: 具有3+层深度的递归异步函数
- `deep_stack_operation_b()`: 带有字符串处理的替代深层栈模式
- `run_concurrent_coroutines()`: 使用 `asyncio.gather()` 同时启动多个协程

### 复杂异步模式
- 异步生成器 (`async_result_generator`)
- 带有错误处理的嵌套异步调用
- 基于运行时值的条件性 await
- 在 catch 块中包含异步操作的异常处理

### 监控设置
- `MonitoringTracer` 类配置 `sys.monitoring` 用于：
  - 函数进入/退出事件 (PY_START, PY_RETURN, PY_UNWIND)
  - 行执行事件 (LINE)
  - 异常事件 (RAISE, EXCEPTION_HANDLED)
  - Yield 事件 (PY_YIELD)

## 使用方法

运行测试：
```bash
python sys_monitoring_test.py
```

输出将显示：
1. 包含各种数据场景的复杂异步操作测试用例
2. 并发协程执行结果
3. 显示执行流程的详细监控事件

## 预期输出分析

监控事件将展示：
- 不同协程间的交错执行
- 带有递归异步调用的深层调用栈遍历
- 并发操作间的正确上下文切换
- 通过异步调用栈的异常处理和传播

此测试特别适用于理解 Python 监控系统如何在具有复杂调用层次结构的并发异步操作中跟踪执行上下文。

---

# Sys.Monitoring Async Tracing Test (English)

This test demonstrates Python's `sys.monitoring` system for tracing asynchronous operations with concurrent coroutines and deep call stacks.

## Purpose

The test is designed to:
- Showcase `sys.monitoring` capabilities for tracing async/await operations
- Demonstrate concurrent execution of multiple coroutines with independent deep call stacks
- Test how the monitoring system handles interleaved execution across different coroutines
- Provide examples of complex async patterns with error handling and generators

## Key Features

### Concurrent Coroutines with Deep Stacks
- `deep_stack_operation_a()`: Recursive async function with 3+ levels of depth
- `deep_stack_operation_b()`: Alternative deep stack pattern with string processing
- `run_concurrent_coroutines()`: Launches multiple coroutines simultaneously using `asyncio.gather()`

### Complex Async Patterns
- Async generators (`async_result_generator`)
- Nested async calls with error handling
- Conditional awaits based on runtime values
- Exception handling with async operations in catch blocks

### Monitoring Setup
- `MonitoringTracer` class configures `sys.monitoring` for:
  - Function entry/exit events (PY_START, PY_RETURN, PY_UNWIND)
  - Line execution events (LINE)
  - Exception events (RAISE, EXCEPTION_HANDLED)
  - Yield events (PY_YIELD)

## Usage

Run the test:
```bash
python sys_monitoring_test.py
```

The output will show:
1. Complex async operation test cases with various data scenarios
2. Concurrent coroutine execution results
3. Detailed monitoring events showing the execution flow

## Expected Output Analysis

The monitoring events will demonstrate:
- Interleaved execution between different coroutines
- Deep call stack traversal with recursive async calls
- Proper context switching between concurrent operations
- Exception handling and propagation through async call stacks

This test is particularly useful for understanding how Python's monitoring system tracks execution context across concurrent async operations with complex call hierarchies.