from typing import Any, Callable, Dict, List, Optional, Tuple

import lldb

from .libc.abi import ABI, LibcABI

hooker: "LibcFunctionHooker" = None  # 全局hooker实例


def libc_breakpoint_callback(
    frame: lldb.SBFrame, bp_loc: lldb.SBBreakpointLocation, extra_args: Any, internal_dict: Dict[str, Any]
) -> bool:
    """Libc函数调用断点回调"""
    import pdb

    pdb.set_trace()
    hooker._handle_function_entry(frame, bp_loc, extra_args, internal_dict)
    frame.thread.GetProcess().Continue()  # 继续执行，允许函数调用完成


def libc_return_callback(
    frame: lldb.SBFrame, bp_loc: lldb.SBBreakpointLocation, extra_args: Any, internal_dict: Dict[str, Any]
) -> bool:
    """Libc函数返回断点回调"""
    hooker._handle_function_return(frame, bp_loc, extra_args, internal_dict)
    frame.thread.GetProcess().Continue()  # 继续执行，允许函数返回完成


def prepare_hooker(tracer):
    """初始化全局hooker实例"""
    global hooker
    if hooker is None:
        hooker = LibcFunctionHooker(tracer)
        hooker.setup_hooks()
    return hooker


def get_libc_hooker() -> "LibcFunctionHooker":
    """获取全局hooker实例"""
    return hooker


class LibcFunctionHooker:
    """处理libc函数调用和返回值的跟踪"""

    def __init__(self, tracer):
        self.tracer = tracer
        self.logger = tracer.logger
        self.target = tracer.target
        self.process = tracer.target.GetProcess()
        self.abi_type = ABI.get_platform_abi(self.target)
        self.libc_abi = LibcABI(self.target)
        self.return_breakpoints: Dict[int, lldb.SBBreakpoint] = {}
        self.function_stacks: Dict[int, Tuple[str, int]] = {}  # thread_id -> (func_name, lr)
        self.async_callbacks: List[Callable] = []
        self.libc_breakpoint_entry_seen = set()
        self.libc_breakpoint_return_seen = set()

    def add_async_callback(self, callback: Callable):
        """添加异步回调函数"""
        if callback not in self.async_callbacks:
            self.async_callbacks.append(callback)

    def remove_async_callback(self, callback: Callable):
        """移除异步回调函数"""
        if callback in self.async_callbacks:
            self.async_callbacks.remove(callback)

    def setup_hooks(self):
        """为配置的libc函数设置断点"""
        libc_funcs = self.tracer.config_manager.get_libc_functions()
        if not libc_funcs:
            return

        for func_name in libc_funcs:
            bp = self.target.BreakpointCreateByName(func_name)
            if not bp.IsValid():
                self.logger.warning(f"Failed to set breakpoint for {func_name}")
                continue
            self.libc_breakpoint_entry_seen.add(bp.GetID())
            self.logger.info(f"Set breakpoint for libc function: {func_name} {bp.GetID()}")

    def handle_function_entry(self, frame, bp_loc, extra_args, internal_dict):
        """处理libc函数入口"""
        thread = frame.GetThread()
        thread_id = thread.GetThreadID()
        func_name = frame.GetFunctionName()

        # 获取返回地址(LR)
        lr_value = ABI.get_lr_register(frame, self.abi_type)
        if not lr_value:
            self.logger.warning("Failed to get LR register")
            return False

        # 设置返回地址断点
        return_bp = self.target.BreakpointCreateByAddress(lr_value)
        if not return_bp.IsValid():
            self.logger.error(f"Failed to set return breakpoint for {func_name} at LR: 0x{lr_value:x}")
            return False
        return_bp.SetOneShot(True)
        self.libc_breakpoint_return_seen.add(return_bp.GetID())
        # 保存函数调用上下文
        self.function_stacks[thread_id] = (func_name, lr_value)
        # 记录函数调用参数
        args_info = self._log_function_args(frame, func_name)

        # 触发异步回调
        self._trigger_async_callbacks("entry", func_name, args_info, thread_id)

        # 继续执行
        return False

    def handle_function_return(self, frame, bp_loc, extra_args, internal_dict):
        """处理libc函数返回"""
        thread = frame.GetThread()
        thread_id = thread.GetThreadID()

        if thread_id not in self.function_stacks:
            return False

        func_name, lr_value = self.function_stacks.pop(thread_id)
        # 记录返回值
        ret_value = ABI.get_return_value(frame, self.abi_type)
        self.logger.info(f"RET {func_name} => 0x{ret_value:x}")

        # 触发异步回调
        self._trigger_async_callbacks("exit", func_name, ret_value, thread_id)

        # 清理返回断点
        if lr_value in self.return_breakpoints:
            self.target.BreakpointDelete(self.return_breakpoints[lr_value].GetID())
            del self.return_breakpoints[lr_value]

    def _log_function_args(self, frame, func_name) -> List[str]:
        """根据函数名记录特定参数格式"""
        try:
            args = ABI.get_function_args(frame, self.abi_type, func_name)
            parsed_args = self.libc_abi.parse_args(func_name, args, frame.GetThread().GetProcess())
            arg_str = f"CALL {func_name}({', '.join(parsed_args)})"
            self.logger.info(arg_str)
            return parsed_args
        except Exception as e:
            self.logger.error(f"Error parsing args for {func_name}: {str(e)}")
            return [f"<error: {str(e)}>"]

    def _trigger_async_callbacks(self, event_type: str, func_name: str, data: Any, thread_id: int):
        """触发所有注册的异步回调"""
        event_data = {
            "type": event_type,
            "function": func_name,
            "data": data,
            "thread_id": thread_id,
        }

        for callback in self.async_callbacks[:]:  # 使用副本避免修改中迭代
            try:
                callback(event_data)
            except Exception as e:
                self.logger.error(f"Async callback failed: {str(e)}")
                # 移除失败的回调防止持续出错
                self.async_callbacks.remove(callback)
