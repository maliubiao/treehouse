from typing import Dict, List, Optional, Tuple

import lldb

from .libc.abi import ABI, LibcABI


class LibcFunctionHooker:
    """处理libc函数调用和返回值的跟踪"""

    def __init__(self, tracer):
        self.tracer = tracer
        self.logger = tracer.logger
        self.target = tracer.target
        self.process = tracer.target.GetProcess()
        self.abi_type = ABI.get_platform_abi(self.target)
        self.libc_abi = LibcABI(self.target)
        self.function_breakpoints: Dict[str, lldb.SBBreakpoint] = {}
        self.return_breakpoints: Dict[int, lldb.SBBreakpoint] = {}
        self.function_stacks: Dict[int, Tuple[str, int]] = {}  # thread_id -> (func_name, lr)

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

            bp.SetCallback(self._handle_function_entry)
            self.function_breakpoints[func_name] = bp
            self.logger.info(f"Set breakpoint for libc function: {func_name}")

    def _handle_function_entry(self, frame, bp_loc, extra_args, internal_dict):
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
        return_bp.SetOneShot(True)
        return_bp.SetCallback(self._handle_function_return)
        self.return_breakpoints[lr_value] = return_bp

        # 保存函数调用上下文
        self.function_stacks[thread_id] = (func_name, lr_value)

        # 记录函数调用参数
        self._log_function_args(frame, func_name)

        # 继续执行
        return False

    def _handle_function_return(self, frame, bp_loc, extra_args, internal_dict):
        """处理libc函数返回"""
        thread = frame.GetThread()
        thread_id = thread.GetThreadID()

        if thread_id not in self.function_stacks:
            return False

        func_name, lr_value = self.function_stacks.pop(thread_id)

        # 记录返回值
        ret_value = ABI.get_return_value(frame, self.abi_type)
        self.logger.info(f"RET {func_name} => 0x{ret_value:x}")

        # 清理返回断点
        if lr_value in self.return_breakpoints:
            self.target.BreakpointDelete(self.return_breakpoints[lr_value].GetID())
            del self.return_breakpoints[lr_value]

        return False

    def _log_function_args(self, frame, func_name):
        """根据函数名记录特定参数格式"""
        args = ABI.get_function_args(frame, self.abi_type, func_name)
        parsed_args = self.libc_abi.parse_args(func_name, args, self.process)
        self.logger.info(f"CALL {func_name}({', '.join(parsed_args)})")
