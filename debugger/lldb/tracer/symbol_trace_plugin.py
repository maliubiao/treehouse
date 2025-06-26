import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING

import lldb

if TYPE_CHECKING:
    # 避免循环导入问题
    from .core import Tracer  # noqa: F401

# 全局回调注册状态
_CALLBACKS_REGISTERED = False
_SYMBOL_TRACE_INSTANCE = None


def _on_enter_breakpoint_wrapper(frame, bp_loc, extra_args, _):
    """全局入口断点回调分发器"""
    print("on_enter_breakpoint_wrapper called: ", frame)
    if not extra_args.IsValid():
        return False
    _SYMBOL_TRACE_INSTANCE._on_enter_breakpoint(frame, bp_loc)
    return False


def _on_return_breakpoint_wrapper(frame, bp_loc, extra_args, _):
    """全局返回断点回调分发器"""
    print("on_return_breakpoint_wrapper called: ", frame)
    if not extra_args.IsValid():
        return False
    _SYMBOL_TRACE_INSTANCE._on_return_breakpoint(frame, bp_loc)
    return False


def register_global_callbacks(run_cmd, logger=None):
    """
    在LLDB环境中注册全局回调函数

    参数:
        run_cmd: 执行LLDB命令的函数
        logger: 可选的日志记录器
    """
    global _CALLBACKS_REGISTERED
    if _CALLBACKS_REGISTERED:
        if logger:
            logger.info("Global callbacks already registered")
        return True
    try:
        # 导入当前模块
        _ = run_cmd("script import tracer")
        # 注册入口回调
        _ = run_cmd(
            "script globals()['_on_enter_breakpoint_wrapper'] = tracer.symbol_trace_plugin._on_enter_breakpoint_wrapper"
        )
        # 注册返回回调
        _ = run_cmd(
            "script globals()['_on_return_breakpoint_wrapper'] = "
            "tracer.symbol_trace_plugin._on_return_breakpoint_wrapper"
        )
        _CALLBACKS_REGISTERED = True
        return True
    except Exception as e:
        if logger:
            logger.error(f"Failed to register global callbacks: {str(e)}")
        return False


class SymbolTrace:
    def __init__(self, tracer: "Tracer", notify_class, symbol_info_cache_file=None):
        """
        初始化符号追踪器

        参数:
            tracer: Tracer 对象
            notify_class: 通知处理类
            symbol_info_cache_file: 符号缓存文件路径(可选)
        """
        global _SYMBOL_TRACE_INSTANCE
        self.tracer = tracer

        self.notify = notify_class
        self.symbol_info_cache_file = symbol_info_cache_file
        self.regex_cache = {}  # 正则匹配结果缓存
        self.enter_breakpoints = {}
        self.thread_stacks = defaultdict(list)
        self.lock = threading.Lock()
        _SYMBOL_TRACE_INSTANCE = self
        self.tracer.run_cmd(
            "script globals()['_symbol_trace_instance'] = tracer.symbol_trace_plugin._SYMBOL_TRACE_INSTANCE"
        )
        # 注册全局回调
        if not register_global_callbacks(self.tracer.run_cmd, self.tracer.logger):
            self.tracer.logger.error("SymbolTrace initialization failed due to callback registration failure")
            raise RuntimeError("Failed to register global callbacks")

        # 加载缓存
        self._load_regex_cache()

    def _load_regex_cache(self):
        """从文件加载正则匹配缓存"""
        if not self.symbol_info_cache_file or not os.path.exists(self.symbol_info_cache_file):
            self.regex_cache = {}
            return

        try:
            with open(self.symbol_info_cache_file, "r", encoding="utf-8") as f:
                # 确保缓存键是字符串
                self.regex_cache = json.load(f)

        except (FileNotFoundError, json.JSONDecodeError):
            # 空文件或无效JSON时忽略
            self.regex_cache = {}
        except Exception as e:
            self.tracer.logger.error(f"Failed to load regex cache: {str(e)}")
            self.regex_cache = {}

    def _save_regex_cache(self):
        """保存正则匹配缓存到文件"""
        if not self.symbol_info_cache_file:
            return

        try:
            with open(self.symbol_info_cache_file, "w", encoding="utf-8") as f:
                json.dump(self.regex_cache, f, indent=2)
        except (IOError, TypeError, ValueError) as e:
            self.tracer.logger.error(f"Failed to save regex cache: {str(e)}")

    def _compile_regex_pattern(self, symbol_regex):
        """编译正则表达式模式"""
        try:
            return re.compile(symbol_regex)
        except re.error as e:
            self.tracer.logger.error(f"Invalid regex pattern: {symbol_regex} - {str(e)}")
            return None

    def _find_matching_symbols(self, module, pattern):
        """查找匹配正则表达式的符号"""
        symbol_names = set()
        num_symbols = module.GetNumSymbols()

        for idx in range(num_symbols):
            symbol = module.GetSymbolAtIndex(idx)
            if not symbol.IsValid():
                continue

            # 只处理函数符号
            if symbol.GetType() != lldb.eSymbolTypeCode:
                continue

            name = symbol.GetName()
            if not name:
                continue

            # 检查是否匹配正则表达式
            if pattern.search(name):
                symbol_names.add(name)

        return symbol_names

    def _get_cache_key(self, module):
        """获取模块的缓存键"""
        uuid_str = module.GetUUIDString()
        if uuid_str:
            return f"UUID:{uuid_str}"
        # 如果没有UUID，回退到模块名（不推荐）
        self.tracer.logger.warning(f"Module {module.GetFileSpec().GetFilename()} has no UUID")
        return module.GetFileSpec().GetFilename()

    def _create_breakpoint(self, symbol_name, module_name):
        """为符号创建断点"""
        bp = self.tracer.target.BreakpointCreateByName(symbol_name, module_name)
        if not bp.IsValid():
            self.tracer.logger.error(f"Failed to create breakpoint for symbol: {symbol_name}")
            return None

        bp.SetOneShot(False)
        bp_id = bp.GetID()
        self.enter_breakpoints[bp_id] = {"symbol": symbol_name, "module": module_name}

        # 设置回调
        args = {}
        data = lldb.SBStructuredData()
        data.SetFromJSON(json.dumps(args))
        sb_error = bp.SetScriptCallbackFunction("_on_enter_breakpoint_wrapper", data)
        if sb_error.Fail():
            self.tracer.logger.error(f"Failed to set script callback for breakpoint {bp}: {sb_error.GetCString()}")
            return None

        return bp

    def register_symbols(self, module_name, symbol_regex):
        """注册要跟踪的符号"""
        # 查找模块
        module_spec = lldb.SBFileSpec(module_name)
        module = self.tracer.target.FindModule(module_spec)
        if not module.IsValid():
            self.tracer.logger.error(f"Module not found: {module_name}")
            self.tracer.logger.error("Available modules:")
            for idx in range(self.tracer.target.GetNumModules()):
                mod = self.tracer.target.GetModuleAtIndex(idx)
                self.tracer.logger.error(f"  - {mod.GetFileSpec().GetFilename()} ({mod.GetFileSpec().GetFullPath()})")
            return 0

        # 获取缓存键
        cache_key = f"{self._get_cache_key(module)}|{symbol_regex}"

        # 检查缓存
        if cache_key in self.regex_cache:
            symbol_names = set(self.regex_cache[cache_key])
            self.tracer.logger.info(
                f"Using cached symbols for {module_name}:{symbol_regex} ({len(symbol_names)} symbols)"
            )
        else:
            # 编译正则表达式
            pattern = self._compile_regex_pattern(symbol_regex)
            if pattern is None:
                return 0

            # 收集匹配的符号
            symbol_names = self._find_matching_symbols(module, pattern)

            # 缓存结果
            self.regex_cache[cache_key] = list(symbol_names)
            self._save_regex_cache()

        count = len(symbol_names)
        if count == 0:
            self.tracer.logger.error(f"No symbols found matching: {symbol_regex}")
            return 0

        # 显示进度
        self.tracer.logger.info(f"Found {count} symbols. Setting breakpoints...")

        # 为每个符号设置进入断点
        progress_interval = max(1, count // 10)  # 每10%显示一次进度
        valid_bp_count = 0
        processed_count = 0

        for symbol_name in symbol_names:
            bp = self._create_breakpoint(symbol_name, module_name)
            if bp is not None:
                valid_bp_count += 1

            processed_count += 1
            # 更新进度
            if processed_count % progress_interval == 0:
                self.tracer.logger.info(f"Progress: {processed_count}/{count} breakpoints set")

        self.tracer.logger.info(f"Successfully set {valid_bp_count} breakpoints")
        return valid_bp_count

    def _on_enter_breakpoint(self, frame, bp_loc):
        """处理进入符号事件"""
        thread = frame.GetThread()
        thread_id = thread.GetThreadID()
        bp = bp_loc.GetBreakpoint()
        bp_id = bp.GetID()

        # 获取符号信息
        symbol_info = self.enter_breakpoints.get(bp_id)
        if not symbol_info:
            self.tracer.logger.error(f"Breakpoint info not found for breakpoint id: {bp_id}")
            return False

        symbol_name = symbol_info["symbol"]
        module_name = symbol_info["module"]

        # 获取函数返回地址
        return_addresses = self._get_return_addresses(symbol_name)
        if not return_addresses:
            self.tracer.logger.error(f"No return addresses found for symbol: {symbol_name}")
            return False

        # 为当前调用实例创建返回断点
        return_bps = []
        for addr in return_addresses:
            # 确保地址有效
            if addr <= 0:
                continue

            bp = self.tracer.target.BreakpointCreateByAddress(addr)
            if not bp.IsValid():
                continue

            bp.SetOneShot(True)
            args = {}
            data = lldb.SBStructuredData()
            data.SetFromJSON(json.dumps(args))
            bp.SetScriptCallbackFunction("_on_return_breakpoint_wrapper", data)
            return_bps.append(bp.GetID())

        # 记录调用栈信息
        with self.lock:
            self.thread_stacks[thread_id].append(
                {"symbol": symbol_name, "module": module_name, "enter_time": time.time(), "return_bps": return_bps}
            )

        # 触发通知
        if hasattr(self.notify, "symbol_enter"):
            self.notify.symbol_enter(
                {"symbol": symbol_name, "module": module_name, "thread_id": thread_id, "timestamp": time.time()}
            )

        return False  # 不停止执行

    def _get_return_addresses(self, symbol_name):
        """获取函数的所有返回指令地址"""
        # 查找符号 - 使用基础名称匹配
        context_list = self.tracer.target.FindFunctions(symbol_name, lldb.eFunctionNameTypeBase)
        if context_list.GetSize() == 0:
            # 尝试自动匹配模式
            context_list = self.tracer.target.FindFunctions(symbol_name, lldb.eFunctionNameTypeAuto)
            if context_list.GetSize() == 0:
                return []

        context = context_list.GetContextAtIndex(0)
        function = context.GetFunction()
        symbol = context.GetSymbol()

        # 优先使用函数获取指令
        if function and function.IsValid():
            instructions = function.GetInstructions(self.tracer.target)
        elif symbol and symbol.IsValid():
            instructions = symbol.GetInstructions(self.tracer.target)
        else:
            return []

        return_addresses = []
        function_end_addr = 0

        # 获取函数结束地址
        if function and function.IsValid():
            function_end_addr = function.GetEndAddress().GetLoadAddress(self.tracer.target)

        for i in range(instructions.GetSize()):
            inst = instructions.GetInstructionAtIndex(i)
            addr = inst.GetAddress().GetLoadAddress(self.tracer.target)

            # 如果函数结束地址有效，检查是否超出范围
            if function_end_addr > 0 and addr > function_end_addr:
                break

            mnemonic = inst.GetMnemonic(self.tracer.target)

            # 检查是否为返回指令
            if mnemonic and mnemonic.lower().startswith("ret"):
                return_addresses.append(addr)

        # 如果没有找到返回指令，尝试使用函数结束地址
        if not return_addresses and function_end_addr > 0:
            return_addresses.append(function_end_addr)

        return return_addresses

    def _on_return_breakpoint(self, frame, _):
        """处理离开符号事件"""
        thread = frame.GetThread()
        thread_id = thread.GetThreadID()

        with self.lock:
            stack = self.thread_stacks.get(thread_id, [])
            if not stack:
                return False

            # 获取最近的调用记录
            current_call = stack[-1]
            symbol_name = current_call["symbol"]
            module_name = current_call["module"]
            enter_time = current_call["enter_time"]
            return_bps = current_call["return_bps"]

            # 计算持续时间
            duration = time.time() - enter_time

            # 清理其他返回断点
            for bp_id in return_bps:
                # 确保断点存在再删除
                bp_obj = self.tracer.target.FindBreakpointByID(bp_id)
                if bp_obj and bp_obj.IsValid():
                    self.tracer.target.BreakpointDelete(bp_id)

            # 从调用栈中移除
            stack.pop()
            if not stack:
                del self.thread_stacks[thread_id]

        # 触发通知
        if hasattr(self.notify, "symbol_leave"):
            self.notify.symbol_leave(
                {
                    "symbol": symbol_name,
                    "module": module_name,
                    "thread_id": thread_id,
                    "duration": duration,
                    "timestamp": time.time(),
                }
            )

        return False  # 不停止执行

    def shutdown(self):
        """清理资源"""
        # 删除所有进入断点
        for bp_id in list(self.enter_breakpoints.keys()):
            bp = self.tracer.target.FindBreakpointByID(bp_id)
            if bp and bp.IsValid():
                self.tracer.target.BreakpointDelete(bp_id)
        self.enter_breakpoints.clear()

        # 清理所有返回断点
        for stack in list(self.thread_stacks.values()):
            for call in stack:
                for bp_id in call["return_bps"]:
                    bp = self.tracer.target.FindBreakpointByID(bp_id)
                    if bp and bp.IsValid():
                        self.tracer.target.BreakpointDelete(bp_id)
        self.thread_stacks.clear()

        # 保存正则匹配缓存
        self._save_regex_cache()


class NotifyClass:
    """默认通知类，用户可继承此类实现自定义行为"""

    def symbol_enter(self, symbol_info):
        """当进入符号时调用"""

    def symbol_leave(self, symbol_info):
        """当离开符号时调用"""
