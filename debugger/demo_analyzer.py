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
    if c > 10:
        raise ValueError(1)
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


@generate_unit_tests(
    # 我们明确指定要为这两个函数生成测试
    target_functions=["innermost_raiser", "middle_handler_and_reraiser"],
    output_dir="generated_tests/exception_demo",
    report_dir="call_reports/exception_demo",
    auto_confirm=True,
    trace_llm=True,
    num_workers=0,  # 使用单线程以便于观察和调试日志
    model_name="deepseek-v3",
    checker_model_name="deepseek-v3",
)
def exception_demo_entrypoint():
    """
    主入口点，用于演示对各种异常路径的跟踪。
    装饰器会自动跟踪并为 `target_functions` 和此函数本身生成测试。
    """
    print("--- Starting Exception Tracing Demo ---")

    # 场景 1: 正常执行流程，没有任何异常。
    # 预期: innermost_raiser 返回成功, middle_handler... 执行 finally 并返回成功结果。
    print("\n[SCENARIO 1] Clean run, no exceptions.")
    res1 = middle_handler_and_reraiser(should_raise_in_child=False, should_reraise=False)
    print(f"--> Scenario 1 Result: '{res1}' (Expected: 'Innermost success')")

    # 场景 2: 异常被捕获并处理。
    # 预期: innermost_raiser 抛出异常, middle_handler... 捕获它, 执行 finally, 并返回“已处理”消息。
    print("\n[SCENARIO 2] Exception caught and handled.")
    res2 = middle_handler_and_reraiser(should_raise_in_child=True, should_reraise=False)
    print(f"--> Scenario 2 Result: '{res2}' (Expected: 'Middle handled exception')")

    # 场景 3: 异常被捕获后重新抛出。
    # 预期: innermost_raiser 抛出, middle_handler... 捕获, 执行 finally, 然后重新抛出。
    #       此处的 try/except 块将捕获重抛的异常。
    print("\n[SCENARIO 3] Exception reraised and caught by entrypoint.")
    try:
        middle_handler_and_reraiser(should_raise_in_child=True, should_reraise=True)
    except CustomError as e:
        print(f"--> Scenario 3 Result: Caught reraised exception: '{e}'")

    deep1(0)
    print("\n--- Exception Tracing Demo Finished ---")


if __name__ == "__main__":
    # 我们调用入口点。在场景3之后，程序会正常结束。
    # `atexit` 钩子会触发，并基于记录的跟踪数据（包括所有复杂的异常路径）生成单元测试。
    exception_demo_entrypoint()

    print("\nDemo script finished. Test generation will now start based on the collected traces.")
    print("The formatted traces for targeted functions will be displayed for verification.")
