import logging
import os
import threading
import time
from typing import Any, List, Optional

import lldb
from ai import set_entrypoint_breakpoints

from .breakpoint_handler import BreakpointHandler
from .config import ConfigManager
from .event_loop import EventLoop
from .libc_hooker import prepare_hooker
from .logger import LogManager
from .modules import ModuleManager
from .source_ranges import SourceRangeManager
from .step_handler import StepHandler
from .symbol_trace_plugin import SymbolTrace, register_global_callbacks
from .utils import get_platform_stdin_listener


class Tracer:
    @property
    def config_manager(self) -> "ConfigManager":
        """配置管理器属性。"""
        return self._config_manager

    @config_manager.setter
    def config_manager(self, value: "ConfigManager"):
        """
        设置配置管理器，并自动更新 LogManager 的配置以保持一致。
        """
        self._config_manager = value
        if hasattr(self, "log_manager") and self.log_manager:
            self.log_manager.config = self._config_manager.config

    def __init__(self, **kwargs: Any) -> None:
        self.program_path: Optional[str] = kwargs.get("program_path")
        self.program_args: List[str] = kwargs.get("program_args", [])
        self.attach_pid: Optional[int] = kwargs.get("attach_pid")
        self.logfile: Optional[str] = kwargs.get("logfile")
        self.config_file: Optional[str] = kwargs.get("config_file")
        self.stdin_forwarding_thread = None
        self.stdin_forwarding_stop = threading.Event()
        self.log_manager: LogManager = LogManager(None, self.logfile)
        self.logger: logging.Logger = self.log_manager.logger

        # 此处赋值会调用 setter，自动处理 log_manager.config 的关联
        self.config_manager: ConfigManager = ConfigManager(self.config_file, self.logger)

        self.breakpoint_table = {}
        self.breakpoint_seen = set()
        self.debugger: lldb.SBDebugger = lldb.SBDebugger.Create()
        self.debugger.Initialize()
        self.debugger.SetAsync(True)

        # 修复行过长问题
        self.debugger.SetInternalVariable(
            "target.process.extra-startup-command", "QSetLogging:bitmask=LOG_ALL", self.logger.name
        )

        self.listener: lldb.SBListener = lldb.SBListener("TracerListener")

        self.breakpoint: Optional[lldb.SBBreakpoint] = None
        self.target: Optional[lldb.SBTarget] = None
        self.process: Optional[lldb.SBProcess] = None
        self.entry_point_breakpoint_event: threading.Event = threading.Event()
        self.die_event: threading.Event = threading.Event()
        self.attached: bool = False  # 标记是否为附加模式

        # 初始化组件
        self.modules: Optional[ModuleManager] = None
        self.source_ranges: Optional[SourceRangeManager] = None
        self.step_handler: Optional[StepHandler] = None
        self.breakpoint_handler: Optional[BreakpointHandler] = None
        self.event_loop: Optional[EventLoop] = None
        self.pthread_create_breakpoint_id: Optional[int] = None
        self.pthread_join_breakpoint_id: Optional[int] = None
        self.lr_breakpoint_id: Optional[int] = None
        self.thread_breakpoint_seen: set[int] = set()
        self.return_breakpoint_seen: set[int] = set()
        self.main_thread_id: Optional[int] = -1

    def continue_to_main(self) -> None:
        while not self.entry_point_breakpoint_event.is_set():
            if self.process:
                self.process.Continue()
            time.sleep(0.1)

    def attach(self, pid: int) -> bool:
        """附加到指定PID的进程"""
        try:
            self.logger.info("Attaching to process PID: %d", pid)  # 修复日志格式
            error = lldb.SBError()
            self.target = self.debugger.CreateTarget("")

            if not self.target:
                self.logger.error("Failed to create target for attaching")
                return False

            self.process = self.target.AttachToProcessWithID(self.listener, pid, error)

            if not error.Success():
                # 修复日志格式和权限提示
                self.logger.error("Attach failed: %s", error.GetCString())
                if "attach failed" in error.GetCString().lower() and "not permitted" in error.GetCString().lower():
                    self.logger.error("Permission denied. On macOS, you may need to:")
                    self.logger.error("1. Enable Developer Mode: sudo DevToolsSecurity -enable")
                    self.logger.error("2. Grant Terminal full disk access in System Settings > Privacy & Security")
                    self.logger.error(
                        "3. Add your user to the developer tools group: sudo dscl . append /Groups/_developer GroupMembership $(whoami)"
                    )
                return False

            if not self.process or not self.process.IsValid():
                self.logger.error("Invalid process after attach")
                return False
            if self.config_manager.config.get("forward_stdin", True):
                self._start_stdin_forwarding()
            self.attached = True
            self.logger.info("Successfully attached to process PID: %d", pid)  # 修复日志格式

            # 初始化组件
            self._initialize_components()

            # 设置断点
            self.install(self.target)
            self.entry_point_breakpoint_event.set()
            self.process.GetSelectedThread().StepInstruction(False)
            # self.set_pthread_create_breakpoint()
            # self.set_pthread_join_breakpoint()
            # 直接开始事件循环
            self.event_loop.run()
            self.cleanup()
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error("Unexpected error during attach: %s", str(e))
            return False

    def run_cmd(self, cmd: str, raise_on_error: bool = True) -> None:
        """执行LLDB命令"""
        if not self.debugger:
            self.logger.error("Debugger is not initialized")
            return
        if not cmd:
            self.logger.warning("Empty command provided")
            return
        self.logger.info("Running LLDB command: %s", cmd)
        command_interpreter = self.debugger.GetCommandInterpreter()
        result = lldb.SBCommandReturnObject()
        command_interpreter.HandleCommand(cmd, result)

        # Always log output if it exists, as it can be useful for debugging.
        output = result.GetOutput()
        if output:
            self.logger.info("Command output: %s", output.strip())

        # A command is only considered to have failed if Succeeded() is false AND there's an error message.
        if not result.Succeeded():
            error_msg = result.GetError()
            if error_msg:
                error_msg_stripped = error_msg.strip()
                if raise_on_error:
                    self.logger.error("Command failed: %s", error_msg_stripped)
                    raise ValueError(f"Command failed: {error_msg_stripped}")
                else:
                    self.logger.warning("Command failed (non-fatal): %s", error_msg_stripped)

    def _start_stdin_forwarding(self):
        """启动标准输入转发线程"""
        if not self.process or not self.process.IsValid():
            self.logger.warning("Cannot start stdin forwarding - no valid process")
            return

        self.logger.info("Starting stdin forwarding to debugged process")
        self.stdin_forwarding_stop.clear()
        self.stdin_forwarding_thread = threading.Thread(
            target=self._stdin_forwarding_loop, name="stdin_forwarding", daemon=True
        )
        self.stdin_forwarding_thread.start()

    def _stdin_forwarding_loop(self):
        """监听标准输入并转发给被调试进程"""
        listener = get_platform_stdin_listener()

        while not self.stdin_forwarding_stop.is_set():
            if not self.process or not self.process.IsValid():
                break

            # 检查是否有输入
            if listener.has_input():
                try:
                    data = listener.read()
                    if data:
                        # 转发给被调试进程
                        self.process.PutSTDIN(data)
                        self.logger.debug("Forwarded %d bytes to debugged process", len(data))  # 修复日志格式
                # 修复过于宽泛的异常捕获
                except OSError as e:
                    self.logger.error("OS error in stdin forwarding: %s", str(e))
                    break
                except Exception as e:  # pylint: disable=broad-exception-caught
                    self.logger.error("Unexpected error in stdin forwarding: %s", str(e))
                    break

            # 短暂休眠避免过度占用CPU
            time.sleep(0.05)

        self.logger.info("Stdin forwarding stopped")

    def cleanup(self) -> None:
        """停止标准输入转发并清理"""
        # 停止标准输入转发
        if self.stdin_forwarding_thread and self.stdin_forwarding_thread.is_alive():
            self.stdin_forwarding_stop.set()
            self.stdin_forwarding_thread.join(timeout=1.0)

        if self.debugger:
            self.debugger.Terminate()

    def _initialize_components(self):
        """初始化追踪器组件"""
        self.modules = ModuleManager(self.target, self.logger, self.config_manager)
        self.source_ranges = SourceRangeManager(self.target, self.logger, self.config_manager)
        self.step_handler = StepHandler(self)
        self.breakpoint_handler = BreakpointHandler(self)
        self.event_loop = EventLoop(self, self.listener, self.logger)
        prepare_hooker(self)

    def start(self) -> bool:
        if self.attach_pid:
            return self.attach(self.attach_pid)

        if not self.program_path:
            self.logger.error("No program path specified")
            return False
        self.target = self.debugger.CreateTarget(self.program_path)
        if not self.target or not self.target.IsValid():
            raise RuntimeError("Failed to create target for %s", self.program_path)  # 修复日志格式

        # 初始化组件
        self._initialize_components()

        if self.config_manager.config.get("log_target_info"):
            self.log_manager.log_target_info(self.target)

        self.install(self.target)
        # self.set_pthread_create_breakpoint()
        # self.set_pthread_join_breakpoint()
        self.listener.StartListeningForEventClass(
            self.debugger,
            lldb.SBProcess.GetBroadcasterClassName(),
            lldb.SBProcess.eBroadcastBitStateChanged
            | lldb.SBProcess.eBroadcastBitSTDOUT
            | lldb.SBProcess.eBroadcastBitSTDERR,
        )
        thread_event_mask = (
            lldb.SBThread.eBroadcastBitStackChanged
            | lldb.SBThread.eBroadcastBitThreadSuspended
            | lldb.SBThread.eBroadcastBitThreadResumed
            | lldb.SBThread.eBroadcastBitSelectedFrameChanged
            | lldb.SBThread.eBroadcastBitThreadSelected
        )
        self.listener.StartListeningForEventClass(
            self.debugger, lldb.SBThread.GetBroadcasterClassName(), thread_event_mask
        )
        error = lldb.SBError()

        # 获取环境变量配置
        env_vars = self.config_manager.get_environment_list()
        self.logger.info("Setting environment variables: %s", ", ".join(env_vars))

        self.process = self.target.Launch(
            self.listener,
            self.program_args,
            env_vars,  # 传入环境变量
            None,
            None,
            None,
            os.getcwd(),
            False,
            True,
            error,
        )
        if not self.process:
            self.logger.error("Failed to launch process")
            return False

        if self.config_manager.config.get("forward_stdin", True):
            self._start_stdin_forwarding()
        from .lldb_console import show_console

        self.run_cmd("settings set use-color true", raise_on_error=False)
        # show_console(self.debugger)
        self.run_cmd("settings set use-color false", raise_on_error=False)
        assert self.process.GetState() == lldb.eStateStopped

        if self.config_manager.get_symbol_trace_patterns:
            self.use_symbol_trace()
        threading.Thread(target=self.continue_to_main, daemon=True).start()
        self.event_loop.run()
        self.cleanup()
        return True

    def use_symbol_trace(self):
        register_global_callbacks(self.run_cmd, self.logger)
        self.symbol_trace = SymbolTrace(self, self.step_handler, self.config_manager.get_symbol_trace_cache_file())
        for source_pattern in self.config_manager.get_symbol_trace_patterns():
            self.symbol_trace.register_symbols(source_pattern.module, source_pattern.regex, False)

    def install(self, target: lldb.SBTarget) -> None:
        self.target = target
        self.run_cmd("command script import --allow-reload tracer")
        self.run_cmd("settings set target.use-fast-stepping true", raise_on_error=False)
        self.run_cmd("settings set target.process.follow-fork-mode child", raise_on_error=False)
        self.run_cmd("settings set use-color false", raise_on_error=False)
        bp_config = self.config_manager.config.get("start_breakpoint", {})
        bp_type = bp_config.get("type", "entry")

        # 在附加模式下，默认使用main符号作为入口点
        if self.attached and bp_type == "entry":
            bp_type = "symbol"
            bp_config["symbol"] = "main"
            self.logger.info("Using 'main' symbol as entry point in attach mode")

        self._set_entrypoint_breakpoint()
        if self.config_manager.config.get("log_breakpoint_details"):
            self.log_manager.log_breakpoint_info(self.breakpoint)

    def _set_entrypoint_breakpoint(self):
        """设置默认入口点断点"""
        bp = self.target.BreakpointCreateByName("main", os.path.basename(self.program_path))
        assert bp.IsValid(), "Failed to create entry point breakpoint"  # 修复日志格式
        self.logger.info("Set entry point breakpoint at %s", bp)
        bp.SetOneShot(True)
        self.breakpoint = bp

    def _set_module_breakpoint(self, config):
        """设置模块偏移断点"""
        module_name = config.get("module", "")
        offset = config.get("offset", 0)

        if not module_name or not offset:
            self.logger.warning("Invalid module breakpoint config, using default entry point")
            return self._set_entrypoint_breakpoint()

        # 查找模块
        for module in self.target.module_iter():
            if module_name in module.GetFileSpec().GetFilename():
                module_base = module.GetObjectFileHeaderAddress().GetLoadAddress(self.target)
                addr = module_base + offset
                self.breakpoint = self.target.BreakpointCreateByAddress(addr)
                self.breakpoint.SetOneShot(True)
                self.logger.info("Set module breakpoint at 0x%x in %s", addr, module_name)  # 修复日志格式
                return

        self.logger.error("Module not found: %s, using default entry point", module_name)  # 修复日志格式
        self._set_entrypoint_breakpoint()

    def _set_symbol_breakpoint(self, config):
        """设置符号断点"""
        symbol_name = config.get("symbol", "")

        if not symbol_name:
            self.logger.warning("Invalid symbol breakpoint config, using default entry point")
            return self._set_entrypoint_breakpoint()

        module = config.get("module", "")
        if not module:
            module = self.program_path

        # Find all matching symbols
        symbol_list: lldb.SBSymbolContextList = None
        if module:
            module_obj: lldb.SBModule = self.target.FindModule(lldb.SBFileSpec(module))
            if module_obj:
                symbol_list = module_obj.FindFunctions(symbol_name)

        # If no symbols found in specified module, search in all modules
        if symbol_list.GetSize() == 0:
            symbol_list = self.target.FindFunctions(symbol_name)

        # Interactive selection if multiple symbols found
        if symbol_list.GetSize() > 1:
            print("\nMultiple symbols found. Please select one:")
            symbols = []
            for i in range(symbol_list.GetSize()):
                symbol: lldb.SBSymbol = symbol_list.symbols[i]
                # addr = symbol.GetStartAddress().GetLoadAddress(self.target)
                module_name = symbol.addr.module.file.fullpath
                # details = f"[{i}] {symbol_name} at 0x{addr:x} in {module_name}"
                symbols.append(symbol)
                # print(details)

            while True:
                try:
                    choice = input("\nEnter selection number: ")
                    idx = int(choice)
                    if 0 <= idx < len(symbols):
                        selected_symbol: lldb.SBSymbol = symbols[idx]
                        self.breakpoint = self.target.BreakpointCreateByName(
                            selected_symbol.name, selected_symbol.addr.module.file.fullpath
                        )
                        self.breakpoint.SetOneShot(True)
                        self.logger.info(f"Set symbol breakpoint for %s", selected_symbol.name)  # 修复日志格式
                        return
                    else:
                        print(f"Invalid selection. Please enter a number between 0 and {len(symbols) - 1}")
                except ValueError:
                    print("Please enter a valid number")

        elif symbol_list.GetSize() == 1:
            # If only one symbol found, use it directly
            symbol = symbol_list.symbols[0]
            self.breakpoint = self.target.BreakpointCreateByName(symbol.name, symbol.addr.module.file.fullpath)
            self.breakpoint.SetOneShot(True)
            self.logger.info(f"Set symbol breakpoint for %s", symbol.name)  # 修复日志格式
            return
        else:
            # Fall back to simple name-based breakpoint
            module_name = os.path.basename(self.program_path)
            self.breakpoint = self.target.BreakpointCreateByName(symbol_name, module_name)
            self.breakpoint.SetOneShot(True)
            self.logger.info(f"Set symbol breakpoint on: %s in %s", symbol_name, module_name)  # 修复日志格式

    def _set_source_breakpoint(self, config):
        """设置源代码行号断点"""
        file_path = config.get("file", "")
        line = config.get("line", 0)

        if not file_path or not line:
            self.logger.warning("Invalid source breakpoint config, using default entry point")
            return self._set_entrypoint_breakpoint()

        self.breakpoint = self.target.BreakpointCreateByLocation(file_path, line)
        self.breakpoint.SetOneShot(True)
        self.logger.info("Set source breakpoint at %s:%d", file_path, line)  # 修复日志格式

    def set_pthread_create_breakpoint(self):
        """设置pthread_create函数的断点"""

        if not self.target:
            self.logger.error("No valid target to set pthread_create breakpoint")
            return
        pthread_create_bp = self.target.BreakpointCreateByName("pthread_create")
        if not pthread_create_bp.IsValid():
            self.logger.error("Failed to create pthread_create breakpoint")
            return
        pthread_create_bp.SetOneShot(False)
        self.pthread_create_breakpoint_id = pthread_create_bp.GetID()
        self.logger.info(
            "Set pthread_create breakpoint at %s", pthread_create_bp.GetLocationAtIndex(0).GetLoadAddress()
        )  # 修复日志格式

    def set_pthread_join_breakpoint(self):
        """设置pthread_join函数的断点"""
        if not self.target:
            self.logger.error("No valid target to set pthread_join breakpoint")
            return
        pthread_join_bp = self.target.BreakpointCreateByName("pthread_join")
        if not pthread_join_bp.IsValid():
            self.logger.error("Failed to create pthread_join breakpoint")
            return
        pthread_join_bp.SetOneShot(False)
        self.pthread_join_breakpoint_id = pthread_join_bp.GetID()
        self.logger.info("Set pthread_join breakpoint at %s", pthread_join_bp.GetLocationAtIndex(0).GetLoadAddress())
