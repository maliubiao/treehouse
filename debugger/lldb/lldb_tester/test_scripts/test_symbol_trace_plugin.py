import logging
import os
import tempfile
import threading
import time

import lldb
from tracer.symbol_trace_plugin import NotifyClass, SymbolTrace, register_global_callbacks


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

    def symbol_enter(self, symbol_info):
        """重写进入符号通知方法"""
        with self.lock:
            thread_id = symbol_info["thread_id"]
            self.enter_count += 1

            # 初始化线程调用栈
            if thread_id not in self.thread_stacks:
                self.thread_stacks[thread_id] = []

            # 记录调用深度
            depth = len(self.thread_stacks[thread_id])
            symbol_info["depth"] = depth
            self.thread_stacks[thread_id].append(symbol_info["symbol"])

            # 记录事件
            self.events.append(("enter", symbol_info))

    def symbol_leave(self, symbol_info):
        """重写离开符号通知方法"""
        with self.lock:
            thread_id = symbol_info["thread_id"]
            self.leave_count += 1

            if thread_id in self.thread_stacks and self.thread_stacks[thread_id]:
                # 验证调用栈一致性
                if self.thread_stacks[thread_id][-1] == symbol_info["symbol"]:
                    self.thread_stacks[thread_id].pop()

                # 记录当前深度
                depth = len(self.thread_stacks[thread_id])
                symbol_info["depth"] = depth

            # 记录事件
            self.events.append(("leave", symbol_info))

    def validate_stacks(self):
        """验证所有线程调用栈是否为空"""
        with self.lock:
            for thread_id, stack in self.thread_stacks.items():
                if stack:
                    return False
            return True


def test_symbol_trace(context):
    """
    测试符号追踪功能
    """
    # 创建临时缓存文件
    cache_file = tempfile.NamedTemporaryFile(delete=False).name

    class FakeTracer:
        """模拟的tracer类，用于测试"""

        def __init__(self):
            self.target = context.target
            self.logger = logging.getLogger(__name__)
            self.logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.run_cmd = context.run_command

    try:
        # 创建通知实例
        notify = TraceNotify()

        # 初始化符号追踪器
        symbol_trace = SymbolTrace(tracer=FakeTracer(), notify_class=notify, symbol_info_cache_file=cache_file)

        # 获取可执行文件名作为模块名
        executable = context.target.GetExecutable()
        module_name = executable.GetFilename()
        if not module_name:
            module_name = executable.GetFullPath()

        # 注册要追踪的符号
        symbols_registered = symbol_trace.register_symbols(
            module_name=module_name,
            symbol_regex="test_function_1|test_function_2|nested_function|parameterized_function|recursive_function|function_with_return",
        )

        if symbols_registered == 0:
            raise RuntimeError("Failed to register any symbols for tracing")
        # 继续执行程序以触发断点
        context.run_command("continue")
        # 等待符号事件发生
        start_time = time.time()
        while time.time() - start_time < 10:  # 10秒超时
            # 等待足够的事件发生
            if notify.enter_count >= 11 and notify.leave_count >= 11:
                break
            time.sleep(0.1)

        # 验证事件数量
        if notify.enter_count < 11:
            raise AssertionError(f"Expected at least 11 enter events, got {notify.enter_count}")

        if notify.leave_count < 11:
            raise AssertionError(f"Expected at least 11 leave events, got {notify.leave_count}")

        # 验证调用栈完整性
        if not notify.validate_stacks():
            raise AssertionError("Some function calls were not properly unwound")

        # 分析事件序列
        main_thread_events = []

        for event_type, info in notify.events:
            thread_id = info["thread_id"]

            # 只处理主线程事件
            if thread_id == 1:
                main_thread_events.append((event_type, info["symbol"], info["depth"]))

        # 验证主线程调用顺序
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

        # 只检查序列的前22个事件（实际可能更多）
        for i in range(min(len(expected_main_sequence), len(main_thread_events))):
            actual = main_thread_events[i]
            expected = expected_main_sequence[i]

            if actual != expected:
                raise AssertionError(f"Main thread event mismatch at position {i}: expected {expected}, got {actual}")

        print(f"Symbol trace test passed. Captured {notify.enter_count} enter and {notify.leave_count} leave events.")

    finally:
        # 清理资源
        if "symbol_trace" in locals():
            symbol_trace.shutdown()

        # 删除临时缓存文件
        if os.path.exists(cache_file):
            os.remove(cache_file)


# 框架要求的测试函数
def run_test(context):
    """主测试函数"""
    # 设置main函数入口断点
    context.run_command("breakpoint set --name main")
    context.run_command("run")
    register_global_callbacks(context.run_command)

    # 等待程序停在main函数
    start_time = time.time()
    while time.time() - start_time < 5:
        process = context.target.GetProcess()
        if process.GetState() == lldb.eStateStopped:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Failed to stop at main function")

    # 运行符号追踪测试
    test_symbol_trace(context)
