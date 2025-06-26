import logging
import os
import tempfile
import threading
import time

import lldb
from tracer.symbol_trace_plugin import NotifyClass, SymbolTrace, SymbolTraceEvent, register_global_callbacks


class TraceNotify(NotifyClass):
    """自定义通知类，用于捕获符号追踪事件"""

    def __init__(self):
        super().__init__()
        self.events = []
        self.enter_count = 0
        self.leave_count = 0
        self.lock = threading.Lock()
        self.thread_stacks = {}

        # Initialize a standard logger from stdlib
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def symbol_enter(self, event: SymbolTraceEvent):
        """重写进入符号通知方法"""
        with self.lock:
            self.enter_count += 1

            # 初始化线程调用栈
            if event.thread_id not in self.thread_stacks:
                self.thread_stacks[event.thread_id] = []
            event.depth = len(self.thread_stacks[event.thread_id])
            # 记录调用深度
            self.thread_stacks[event.thread_id].append(event.symbol)
            # 记录事件
            self.events.append(("enter", event))

    def symbol_leave(self, event: SymbolTraceEvent):
        """重写离开符号通知方法"""
        with self.lock:
            self.leave_count += 1

            depth = 0
            if event.thread_id in self.thread_stacks and self.thread_stacks[event.thread_id]:
                # 验证调用栈一致性
                if self.thread_stacks[event.thread_id][-1] == event.symbol:
                    self.thread_stacks[event.thread_id].pop()

                # 记录当前深度
                depth = len(self.thread_stacks[event.thread_id])
            event.depth = depth
            self.events.append(("leave", event))

    def validate_stacks(self):
        """验证所有线程调用栈是否为空"""
        with self.lock:
            for stack in self.thread_stacks.values():
                if stack:
                    return False
            return True


def test_symbol_trace(context):
    """测试符号追踪功能"""
    # 设置main函数入口断点
    context.run_command("breakpoint set --name main")
    context.run_command("process launch --no-stdin")
    register_global_callbacks(context.run_command)

    # 等待程序停在main函数
    if not _wait_for_process_stopped(context):
        raise RuntimeError("Failed to stop at main function")

    # 创建临时缓存文件
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        cache_file = temp_file.name

    try:
        # 初始化测试环境
        notify, symbol_trace = _setup_test_environment(context, cache_file)

        # 执行测试并验证结果
        _run_and_validate_test(context, notify, symbol_trace)

        print(f"Symbol trace test passed. Captured {notify.enter_count} enter and {notify.leave_count} leave events.")

    finally:
        # 清理资源
        _cleanup_resources(cache_file, symbol_trace)


def _wait_for_process_stopped(context, timeout=5):
    """等待进程停止"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        process = context.target.GetProcess()
        if process.GetState() == lldb.eStateStopped:
            return True
        time.sleep(0.1)
    return False


def _setup_test_environment(context, cache_file):
    """设置测试环境"""
    notify = TraceNotify()
    symbol_trace = SymbolTrace(
        tracer=_create_fake_tracer(context), notify_class=notify, symbol_info_cache_file=cache_file
    )

    # 注册要追踪的符号
    symbols = [
        "test_function_1",
        "test_function_2",
        "nested_function",
        "parameterized_function",
        "recursive_function",
        "function_with_return",
    ]
    symbols_registered = symbol_trace.register_symbols(
        module_name=_get_module_name(context),
        symbol_regex="|".join(symbols),
        auto_confirm=True,
    )

    if symbols_registered == 0:
        raise RuntimeError("Failed to register any symbols for tracing")

    return notify, symbol_trace


def _create_fake_tracer(context):
    """创建模拟tracer实例"""

    class FakeTracer:
        def __init__(self):
            self.target = context.target
            self.logger = logging.getLogger(__name__)
            self.logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.run_cmd = context.run_command

    return FakeTracer()


def _get_module_name(context):
    """获取可执行文件名作为模块名"""
    executable = context.target.GetExecutable()
    return executable.GetFilename() or executable.GetFullPath()


def _run_and_validate_test(context, notify, symbol_trace):
    """执行测试并验证结果"""
    context.run_command("continue")

    if not _wait_for_events(notify):
        raise AssertionError("Timeout waiting for trace events")

    _validate_event_counts(notify)
    _validate_event_sequences(notify)


def _wait_for_events(notify, timeout=10):
    """等待足够的事件发生"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if notify.enter_count >= 11 and notify.leave_count >= 11:
            return True
        time.sleep(0.1)
    return False


def _validate_event_counts(notify):
    """验证事件数量"""
    if notify.enter_count < 11:
        raise AssertionError(f"Expected at least 11 enter events, got {notify.enter_count}")
    if notify.leave_count < 11:
        raise AssertionError(f"Expected at least 11 leave events, got {notify.leave_count}")
    if not notify.validate_stacks():
        raise AssertionError("Some function calls were not properly unwound")


def _validate_event_sequences(notify):
    """验证事件序列"""
    expected_main_sequence = [
        ("enter", "test_function_1", 1),
        ("leave", "test_function_1", 0),
        ("enter", "test_function_2", 1),
        ("leave", "test_function_2", 0),
        ("enter", "nested_function", 1),
        ("enter", "test_function_1", 2),
        ("leave", "test_function_1", 1),
        ("enter", "test_function_2", 2),
        ("leave", "test_function_2", 1),
        ("leave", "nested_function", 0),
        ("enter", "parameterized_function", 1),
        ("leave", "parameterized_function", 0),
        ("enter", "recursive_function", 1),
        ("enter", "recursive_function", 2),
        ("enter", "recursive_function", 3),
        ("enter", "recursive_function", 4),
        ("leave", "recursive_function", 3),
        ("leave", "recursive_function", 2),
        ("leave", "recursive_function", 1),
        ("leave", "recursive_function", 0),
        ("enter", "function_with_return", 1),
        ("leave", "function_with_return", 0),
    ]

    main_thread_events = [
        (event_type, info.symbol, info.depth) for event_type, info in notify.events if info.thread_id == 1
    ]

    for i, (actual, expected) in enumerate(
        zip(main_thread_events[: len(expected_main_sequence)], expected_main_sequence)
    ):
        if actual != expected:
            raise AssertionError(f"Main thread event mismatch at position {i}: expected {expected}, got {actual}")


def _cleanup_resources(cache_file, symbol_trace):
    """清理测试资源"""
    if symbol_trace is not None:
        symbol_trace.shutdown()
    if os.path.exists(cache_file):
        os.remove(cache_file)
