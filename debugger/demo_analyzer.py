import asyncio
from typing import AsyncGenerator

from debugger.unit_test_generator_decorator import generate_unit_tests


class CustomError(Exception):
    """一个用于演示的自定义异常。"""

    pass


def innermost_raiser(should_raise: bool) -> str:
    """如果被指示，则抛出一个 CustomError 异常。"""
    print(f"    [Innermost] Running. Will raise? {should_raise}")
    if should_raise:
        raise CustomError("Error from the innermost function.")
    return "Innermost success"


def deep1(c):
    """一个用于演示深层递归和异常的函数。"""
    if c > 10:
        raise ValueError(f"Recursion depth limit reached at {c}")
    deep1(c + 1)


def middle_handler_and_reraiser(should_raise_in_child: bool, should_reraise: bool) -> str:
    """
    一个包含try...except...finally的复杂函数。
    它调用一个可能抛异常的子函数，并可以根据参数决定是否捕获或重新抛出该异常。
    """
    result = "Middle default result"
    print(f"  [Middle] Running. Will call child that raises? {should_raise_in_child}")
    try:
        # 这个调用是跟踪的焦点
        result = innermost_raiser(should_raise_in_child)
        print(f"  [Middle] Child call succeeded. Result: {result}")
    except CustomError as e:
        # 当innermost_raiser抛出异常时，会进入这里
        print(f"  [Middle] Caught exception: {e}")
        result = "Middle handled exception"
        if should_reraise:
            # 根据参数，我们可能重新抛出异常
            print("  [Middle] Reraising exception...")
            raise
    finally:
        # 这个块在所有执行路径中都应该被跟踪器记录下来，无论是否有异常
        print("  [Middle] Executing finally block.")
    return result


def generator_function(count: int):
    """
    一个生成器函数，用于测试对 `yield` 语句的跟踪。
    跟踪器应能捕获到函数的多次暂停和恢复。
    """
    print("    [Generator] Starting.")
    for i in range(count):
        print(f"    [Generator] Yielding {i}")
        yield i
        print(f"    [Generator] Resumed after yielding {i}")
    print("    [Generator] Finished.")


def advanced_generator_function():
    """
    一个更高级的生成器函数，用于演示 send, throw 和 close 方法。
    """
    print("    [Advanced Generator] Starting.")
    value_received = None
    try:
        for i in range(3):
            print(f"    [Advanced Generator] About to yield {i}")
            # 'yield'表达式返回通过'send()'发送的值
            value_received = yield i
            print(f"    [Advanced Generator] Resumed after yielding {i}. Received: {value_received}")
    except GeneratorExit:
        # 当 .close() 被调用时，会抛出 GeneratorExit
        print("    [Advanced Generator] Generator was closed early.")
    except ValueError as e:
        # 捕获由 .throw() 注入的异常
        print(f"    [Advanced Generator] Caught an injected exception: {e}")
    finally:
        # 这个 finally 块在正常完成或关闭时都应该执行
        print("    [Advanced Generator] Executing finally block.")
    print("    [Advanced Generator] Finished.")
    return "Generator completed"


async def async_function(duration: float) -> str:
    """
    一个异步函数，用于测试对 `async/await` 的跟踪。
    它模拟一个异步操作，如网络请求。
    """
    print(f"    [Async] Starting, will wait for {duration}s.")
    await asyncio.sleep(duration)
    print("    [Async] Finished waiting.")
    return "Async success"


async def async_generator_function(count: int) -> AsyncGenerator[int, None]:
    """
    一个异步生成器，结合了异步和生成器特性。
    用于测试对 `async for` 和 `yield` 在异步上下文中的跟踪。
    """
    print("    [Async Generator] Starting.")
    for i in range(count):
        print(f"    [Async Generator] Yielding {i}")
        await asyncio.sleep(0.01)
        yield i
        print(f"    [Async Generator] Resumed after yielding {i}")
    print("    [Async Generator] Finished.")


async def run_async_demos():
    """
    运行所有异步场景。
    此函数由主同步入口点通过 `asyncio.run()` 调用。
    """
    print("\n--- Starting Asynchronous Scenarios ---")

    # 场景 6: 异步函数。
    print("\n[SCENARIO 6] Asynchronous function.")
    async_res = await async_function(0.02)
    print(f"--> Scenario 6 Result: '{async_res}'")

    # 场景 7: 异步生成器函数。
    print("\n[SCENARIO 7] Asynchronous generator function.")
    async_gen_results = [item async for item in async_generator_function(3)]
    print(f"--> Scenario 7 Result: Consumed async generator. Values: {async_gen_results}")

    print("\n--- Asynchronous Scenarios Finished ---")


@generate_unit_tests(
    # 我们明确指定要为这些函数生成测试，包括新增的编排函数
    target_functions=[
        "comprehensive_demo_entrypoint",
        "run_async_demos",
        "innermost_raiser",
        "middle_handler_and_reraiser",
        "deep1",
        "generator_function",
        "advanced_generator_function",
        "async_function",
        "async_generator_function",
    ],
    output_dir="generated_tests/exception_demo",
    report_dir="call_reports/exception_demo",
    auto_confirm=True,
    trace_llm=True,
    num_workers=0,  # 使用单线程以便于观察和调试日志
    model_name="deepseek-v3",
    checker_model_name="deepseek-v3",
)
def comprehensive_demo_entrypoint():
    """
    主同步入口点，用于演示对各种Python特性的跟踪。
    此函数首先执行一系列同步操作，然后启动一个异步事件循环来执行异步操作。
    """
    print("--- Starting Comprehensive Tracing Demo ---")

    # --- 同步场景 ---
    print("\n--- Starting Synchronous Scenarios ---")

    # 场景 1: 正常执行流程，没有任何异常。
    print("\n[SCENARIO 1] Clean run, no exceptions.")
    res1 = middle_handler_and_reraiser(should_raise_in_child=False, should_reraise=False)
    print(f"--> Scenario 1 Result: '{res1}' (Expected: 'Innermost success')")

    # 场景 2: 异常被捕获并处理。
    print("\n[SCENARIO 2] Exception caught and handled.")
    res2 = middle_handler_and_reraiser(should_raise_in_child=True, should_reraise=False)
    print(f"--> Scenario 2 Result: '{res2}' (Expected: 'Middle handled exception')")

    # 场景 3: 异常被捕获后重新抛出。
    print("\n[SCENARIO 3] Exception reraised and caught by entrypoint.")
    try:
        middle_handler_and_reraiser(should_raise_in_child=True, should_reraise=True)
    except CustomError as e:
        print(f"--> Scenario 3 Result: Caught reraised exception: '{e}'")

    # 场景 4: 带有异常的深层递归。
    print("\n[SCENARIO 4] Deep recursion with exception.")
    try:
        deep1(0)
    except (ValueError, RecursionError) as e:
        print(f"--> Scenario 4 Result: Caught final exception from deep_recursion: {e}")

    # --- 场景 5: 生成器函数综合测试 ---
    print("\n--- [SCENARIO 5] Comprehensive Generator Tests ---")

    # 场景 5.1: 使用 for 循环进行基本迭代
    print("\n[SCENARIO 5.1] Basic iteration with a 'for' loop.")
    gen_results_for_loop = []
    for item in generator_function(3):
        print(f"  [Main] Consumed item {item} from generator.")
        gen_results_for_loop.append(item)
    print(f"--> Scenario 5.1 Result: Consumed with for loop. Values: {gen_results_for_loop}")

    # 场景 5.2: 使用 next() 手动迭代并捕获 StopIteration
    print("\n[SCENARIO 5.2] Manual iteration with next() and handling StopIteration.")
    gen_manual = generator_function(2)
    try:
        print(f"  [Main] Manual next() call 1: {next(gen_manual)}")
        print(f"  [Main] Manual next() call 2: {next(gen_manual)}")
        print(f"  [Main] Manual next() call 3 (expecting StopIteration): {next(gen_manual)}")
    except StopIteration:
        print("--> Scenario 5.2 Result: Caught StopIteration as expected.")

    # 使用新的高级生成器来演示 send, throw, close
    print("\n--- Using advanced generator for send, throw, close ---")

    # 场景 5.3: 使用 send() 方法向生成器发送值
    print("\n[SCENARIO 5.3] Sending values into a generator with send().")
    gen_send = advanced_generator_function()
    val = next(gen_send)  # 必须先调用 next() 或 send(None) 来启动生成器
    print(f"  [Main] Initial value from generator: {val}")
    try:
        next_val = gen_send.send("Hello from main")
        print(f"  [Main] Sent 'Hello from main', got back: {next_val}")
        next_val_2 = gen_send.send("Another message")
        print(f"  [Main] Sent 'Another message', got back: {next_val_2}")
        gen_send.send("Final message before it ends")
    except StopIteration as e:
        print(f"--> Scenario 5.3 Result: Generator finished. Return value: '{e.value}'")

    # 场景 5.4: 使用 throw() 方法在生成器内部抛出异常
    print("\n[SCENARIO 5.4] Injecting an exception with throw().")
    gen_throw = advanced_generator_function()
    next(gen_throw)  # 启动生成器
    try:
        print("  [Main] Injecting ValueError into generator...")
        gen_throw.throw(ValueError, "Test exception from throw")
        print("  [Main] This line should not be reached if throw() works.")
    except StopIteration as e:
        print(f"--> Scenario 5.4 Result: Generator caught exception, then finished. Return value: '{e.value}'")

    # 场景 5.5: 使用 close() 方法提前关闭生成器
    print("\n[SCENARIO 5.5] Closing a generator early with close().")
    gen_close = advanced_generator_function()
    next(gen_close)  # 启动生成器
    print("  [Main] Closing generator...")
    gen_close.close()
    try:
        next(gen_close)
    except StopIteration:
        print("--> Scenario 5.5 Result: Generator is closed and raises StopIteration on next call.")

    print("\n--- Synchronous Scenarios Finished ---")

    # --- 异步场景 ---
    # 从同步上下文中启动并运行异步任务
    asyncio.run(run_async_demos())

    print("\n--- Comprehensive Tracing Demo Finished ---")


if __name__ == "__main__":
    # 直接执行同步的入口点函数。
    # 装饰器中的 atexit 钩子将在脚本完全结束后触发，
    # 基于收集到的所有同步和异步场景的跟踪数据生成单元测试。
    comprehensive_demo_entrypoint()

    print("\nDemo script finished. Test generation will now start based on the collected traces.")
    print("The formatted traces for targeted functions will be displayed for verification.")
