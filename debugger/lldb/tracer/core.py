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
from .logger import LogManager
from .modules import ModuleManager
from .source_ranges import SourceRangeManager
from .step_handler import StepHandler
from .utils import get_platform_stdin_listener


class Tracer:
    def __init__(self, **kwargs: Any) -> None:
        self.program_path: Optional[str] = kwargs.get("program_path")
        self.program_args: List[str] = kwargs.get("program_args", [])
        self.attach_pid: Optional[int] = kwargs.get("attach_pid")
        logfile: Optional[str] = kwargs.get("logfile")
        config_file: Optional[str] = kwargs.get("config_file")
        self.stdin_forwarding_thread = None
        self.stdin_forwarding_stop = threading.Event()
        self.log_manager: LogManager = LogManager(None, logfile)
        self.logger: logging.Logger = self.log_manager.logger
        self.config_manager: ConfigManager = ConfigManager(config_file, self.logger)
        self.log_manager.config = self.config_manager.config
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
        self.listener.StartListeningForEventClass(
            self.debugger,
            lldb.SBProcess.GetBroadcasterClassName(),
            lldb.SBProcess.eBroadcastBitStateChanged
            | lldb.SBProcess.eBroadcastBitSTDOUT
            | lldb.SBProcess.eBroadcastBitSTDERR,
        )

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
        self.thread_breakpoint_seen: set[int] = set()  # 用于跟踪已见断点ID

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
        self.set_pthread_create_breakpoint()
        # self.set_pthread_join_breakpoint()
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
        assert self.process.GetState() == lldb.eStateStopped

        threading.Thread(target=self.continue_to_main, daemon=True).start()
        self.event_loop.run()
        self.cleanup()
        return True

    def install(self, target: lldb.SBTarget) -> None:
        self.target = target
        self.debugger.HandleCommand("command script import --allow-reload tracer")
        bp_config = self.config_manager.config.get("start_breakpoint", {})
        bp_type = bp_config.get("type", "entry")

        # 在附加模式下，默认使用main符号作为入口点
        if self.attached and bp_type == "entry":
            bp_type = "symbol"
            bp_config["symbol"] = "main"
            self.logger.info("Using 'main' symbol as entry point in attach mode")

        if bp_type == "module":
            self._set_module_breakpoint(bp_config)
        elif bp_type == "symbol":
            self._set_symbol_breakpoint(bp_config)
        elif bp_type == "source":
            self._set_source_breakpoint(bp_config)
        else:  # 默认入口点断点
            self._set_entrypoint_breakpoint()
        if self.config_manager.config.get("log_breakpoint_details"):
            self.log_manager.log_breakpoint_info(self.breakpoint)

    def _set_entrypoint_breakpoint(self):
        """设置默认入口点断点"""
        bps = set_entrypoint_breakpoints(self.debugger)
        if len(bps) > 1:
            self.logger.info(
                "Found multiple entry points, using first one: %s",
                ", ".join([f"{name} (ID: {bp.GetID()})" for name, bp in bps]),
            )  # 修复日志格式
        name, bp = bps[0]
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

        self.breakpoint = self.target.BreakpointCreateByName(symbol_name)
        self.breakpoint.SetOneShot(True)
        self.logger.info("Set symbol breakpoint on: %s", symbol_name)  # 修复日志格式

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
