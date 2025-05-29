import threading

import lldb

entry_point_breakpoint_event = threading.Event()


def breakpoint_function_wrapper(frame, bp_loc, extra_args, internal_dict):
    """处理LLDB断点事件的包装函数"""
    entry_point_breakpoint_event.set()

    thread = frame.GetThread()
    process = thread.GetProcess()
    target = process.GetTarget()
    debugger = target.GetDebugger()

    # 验证基本对象访问
    print(f"Current function: {frame.GetFunctionName()}")
    print(f"Thread ID: {thread.GetThreadID()}")
    print(f"Process ID: {process.GetProcessID()}")
    print(f"Target: {target.GetExecutable().GetFilename()}")

    # 验证断点位置信息
    print(f"Breakpoint ID: {bp_loc.GetBreakpoint().GetID()}")
    print(f"Breakpoint address: {hex(bp_loc.GetAddress().GetLoadAddress(target))}")

    # 处理extra_args参数
    if extra_args and extra_args.IsValid():
        print("Extra arguments provided:")
        if extra_args.GetValueForKey("key"):
            print(f"Key: {extra_args.GetValueForKey('key').GetStringValue(100)}")
        if extra_args.GetValueForKey("value"):
            print(f"Value: {extra_args.GetValueForKey('value').GetStringValue(100)}")

    # 验证文档中提到的等效访问方式
    print(f"Debugger via frame: {debugger == frame.GetThread().GetProcess().GetTarget().GetDebugger()}")
    # 禁用当前断点位置并继续执行
    thread.StepInstruction(False)

    # 显式标记未使用的参数以避免警告
    _ = internal_dict
    return True
