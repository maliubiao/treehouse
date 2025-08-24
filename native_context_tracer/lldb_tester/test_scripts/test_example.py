import lldb


def run_test(context):
    """
    测试示例：设置断点并验证程序停在预期位置
    """
    # 安全执行命令（带错误检查）
    context.run_command("breakpoint set --name test_function")

    # 验证断点是否设置成功 - 使用正确的API
    breakpoints = context.target.breakpoints
    if len(breakpoints) == 0:
        raise AssertionError("No breakpoints set")

    # 继续执行
    context.run_command("continue")

    # 获取当前进程状态
    process = context.process
    state = process.GetState()

    # 检查程序是否已停止
    if state != lldb.eStateStopped:
        raise AssertionError(f"Process is not stopped (state={state})")

    # 验证是否停在test_function
    thread = process.GetSelectedThread()
    frame = thread.GetFrameAtIndex(0)
    function_name = frame.GetFunctionName()
    if "test_function" not in function_name:
        raise AssertionError(
            f"Not stopped in test_function. Stopped in: {function_name if function_name else 'unknown function'}"
        )

    print("Example test passed")
