import asyncio
import threading
import time
from typing import AsyncGenerator

from debugger.unit_test_generator_decorator import generate_unit_tests


class CustomError(Exception):
    """一个用于演示的自定义异常。"""

    pass


def innermost_raiser(should_raise: bool) -> str:
    """如果被指示，则抛出一个 CustomError 异常。"""
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
    try:
        # 这个调用是跟踪的焦点
        result = innermost_raiser(should_raise_in_child)
    except CustomError as e:
        # 当innermost_raiser抛出异常时，会进入这里
        result = "Middle handled exception"
        if should_reraise:
            # 根据参数，我们可能重新抛出异常
            raise
    finally:
        # 这个块在所有执行路径中都应该被跟踪器记录下来，无论是否有异常
        # In a real scenario, this block might do cleanup.
        pass
    return result


def generator_function(count: int):
    """
    一个生成器函数，用于测试对 `yield` 语句的跟踪。
    跟踪器应能捕获到函数的多次暂停和恢复。
    """
    for i in range(count):
        yield i


def advanced_generator_function():
    """
    一个更高级的生成器函数，用于演示 send, throw 和 close 方法。
    """
    value_received = None
    try:
        for i in range(3):
            # 'yield'表达式返回通过'send()'发送的值
            value_received = yield i
    except GeneratorExit:
        # 当 .close() 被调用时，会抛出 GeneratorExit
        pass
    except ValueError:
        # 捕获由 .throw() 注入的异常
        pass
    finally:
        # 这个 finally 块在正常完成或关闭时都应该执行
        pass
    return "Generator completed"


async def async_function(duration: float) -> str:
    """
    一个异步函数，用于测试对 `async/await` 的跟踪。
    它模拟一个异步操作，如网络请求。
    """
    await asyncio.sleep(duration)
    return "Async success"


async def async_generator_function(count: int) -> AsyncGenerator[int, None]:
    """
    一个异步生成器，结合了异步和生成器特性。
    用于测试对 `async for` 和 `yield` 在异步上下文中的跟踪。
    """
    for i in range(count):
        await asyncio.sleep(0.01)
        yield i


async def run_async_demos():
    """
    运行所有异步场景。
    此函数由主同步入口点通过 `asyncio.run()` 调用。
    """
    # 场景 6: 异步函数。
    await async_function(0.02)

    # 场景 7: 异步生成器函数。
    _ = [item async for item in async_generator_function(3)]


def threaded_worker_function(thread_id: int, duration: float) -> str:
    """
    一个在独立线程中执行的工作函数。
    用于测试跟踪器在多线程环境下的能力。
    """
    time.sleep(duration)
    result = f"Thread {thread_id} finished after {duration}s."
    return result


def run_multithreading_demo():
    """
    创建、启动并等待多个线程完成。
    这是多线程跟踪场景的编排函数。
    """
    threads = []
    # 创建两个线程，每个都调用 threaded_worker_function
    thread1 = threading.Thread(target=threaded_worker_function, args=(1, 0.02), name="WorkerThread-1")
    thread2 = threading.Thread(target=threaded_worker_function, args=(2, 0.03), name="WorkerThread-2")

    threads.extend([thread1, thread2])

    # 启动所有线程
    for thread in threads:
        thread.start()

    # 等待所有线程完成
    for thread in threads:
        thread.join()


@generate_unit_tests(
    # 我们明确指定要为这些函数生成测试，包括新增的编排函数
    target_functions=[
        "comprehensive_demo_entrypoint",
        "run_async_demos",
        "run_multithreading_demo",
        "threaded_worker_function",
        "innermost_raiser",
        "middle_handler_and_reraiser",
        "deep1",
        "generator_function",
        "advanced_generator_function",
        "async_function",
        "async_generator_function",
    ],
    output_dir="generated_tests/comprehensive_demo",
    report_dir="call_reports/comprehensive_demo",
    auto_confirm=True,
    trace_llm=True,
    verbose_trace=True,  # <--- [新功能] 开启实时详细跟踪日志 (同时会生成 logs/raw_trace_events.log)
    num_workers=0,  # 使用单线程以便于观察和调试日志
    model_name="deepseek-v3",
    checker_model_name="deepseek-v3",
)
def comprehensive_demo_entrypoint():
    """
    主同步入口点，用于演示对各种Python特性的跟踪。
    此函数首先执行一系列同步操作，然后启动一个异步事件循环来执行异步操作。
    """
    print("\n--- Starting Comprehensive Tracing Demo ---")
    print("Verbose trace output will be shown below:")

    # --- 同步场景 ---
    print("\n[SCENARIO 1] Clean run, no exceptions.")
    middle_handler_and_reraiser(should_raise_in_child=False, should_reraise=False)

    print("\n[SCENARIO 2] Exception caught and handled.")
    middle_handler_and_reraiser(should_raise_in_child=True, should_reraise=False)

    print("\n[SCENARIO 3] Exception reraised and caught by entrypoint.")
    try:
        middle_handler_and_reraiser(should_raise_in_child=True, should_reraise=True)
    except CustomError:
        pass

    print("\n[SCENARIO 4] Deep recursion with exception.")
    try:
        deep1(0)
    except (ValueError, RecursionError):
        pass

    # --- 场景 5: 生成器函数综合测试 ---
    print("\n[SCENARIO 5.1] Basic iteration with a 'for' loop.")
    for _ in generator_function(3):
        pass

    print("\n[SCENARIO 5.2] Manual iteration with next() and handling StopIteration.")
    gen_manual = generator_function(2)
    try:
        next(gen_manual)
        next(gen_manual)
        next(gen_manual)
    except StopIteration:
        pass

    # 使用新的高级生成器来演示 send, throw, close
    print("\n[SCENARIO 5.3] Sending values into a generator with send().")
    gen_send = advanced_generator_function()
    next(gen_send)
    try:
        gen_send.send("Hello from main")
        gen_send.send("Another message")
        gen_send.send("Final message before it ends")
    except StopIteration:
        pass

    print("\n[SCENARIO 5.4] Injecting an exception with throw().")
    gen_throw = advanced_generator_function()
    next(gen_throw)
    try:
        gen_throw.throw(ValueError, "Test exception from throw")
    except StopIteration:
        pass

    print("\n[SCENARIO 5.5] Closing a generator early with close().")
    gen_close = advanced_generator_function()
    next(gen_close)
    gen_close.close()
    try:
        next(gen_close)
    except StopIteration:
        pass

    # --- 异步场景 ---
    # 从同步上下文中启动并运行异步任务
    print("\n[SCENARIO 6 & 7] Running asynchronous scenarios.")
    asyncio.run(run_async_demos())

    # --- 多线程场景 ---
    print("\n[SCENARIO 8] Running multi-threading scenarios.")
    run_multithreading_demo()

    print("\n--- Comprehensive Tracing Demo Finished ---")


if __name__ == "__main__":
    # 直接执行同步的入口点函数。
    # 装饰器中的 atexit 钩子将在脚本完全结束后触发，
    # 基于收集到的所有同步和异步场景的跟踪数据生成单元测试。
    comprehensive_demo_entrypoint()

    print(
        "\nDemo script finished. Test generation will now start based on the collected traces.\n"
        "The formatted final traces for targeted functions will be displayed below for verification."
    )
