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


class Tracer:
    def __init__(self, **kwargs: Any) -> None:
        self.program_path: Optional[str] = kwargs.get("program_path")
        self.program_args: List[str] = kwargs.get("program_args", [])
        logfile: Optional[str] = kwargs.get("logfile")
        config_file: Optional[str] = kwargs.get("config_file")

        self.log_manager: LogManager = LogManager(None, logfile)
        self.logger: logging.Logger = self.log_manager.logger
        self.config_manager: ConfigManager = ConfigManager(config_file, self.logger)
        self.log_manager.config = self.config_manager.config

        self.debugger: lldb.SBDebugger = lldb.SBDebugger.Create()
        self.debugger.Initialize()
        self.debugger.SetAsync(True)
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

        # 初始化组件
        self.modules: Optional[ModuleManager] = None
        self.source_ranges: Optional[SourceRangeManager] = None
        self.step_handler: Optional[StepHandler] = None
        self.breakpoint_handler: Optional[BreakpointHandler] = None
        self.event_loop: Optional[EventLoop] = None

        self.lr_breakpoint_id: Optional[int] = None

    def continue_to_main(self) -> None:
        while not self.entry_point_breakpoint_event.is_set():
            print("Waiting for entry point breakpoint to be hit...")
            if self.process:
                self.process.Continue()
            time.sleep(0.1)

    def start(self) -> bool:
        if not self.program_path:
            self.logger.error("No program path specified")
            return False

        self.target = self.debugger.CreateTarget(self.program_path)
        if not self.target or not self.target.IsValid():
            self.logger.error("Failed to create valid target for %s", self.program_path)
            return False

        # 初始化组件
        self.modules = ModuleManager(self.target, self.logger, self.config_manager)
        self.source_ranges = SourceRangeManager(self.target, self.logger, self.config_manager)
        self.step_handler = StepHandler(self)
        self.breakpoint_handler = BreakpointHandler(self)
        self.event_loop = EventLoop(self, self.listener, self.logger)

        if self.config_manager.config.get("log_target_info"):
            self.log_manager.log_target_info(self.target)

        self.install(self.target)
        error = lldb.SBError()
        self.process = self.target.Launch(
            self.listener, self.program_args, None, None, None, None, os.getcwd(), 0, True, error
        )
        if not self.process:
            self.logger.error("Failed to launch process")
            return False
        assert self.process.GetState() == lldb.eStateStopped

        threading.Thread(target=self.continue_to_main, daemon=True).start()
        self.event_loop.run()
        self.cleanup()
        return True

    def cleanup(self) -> None:
        if self.debugger:
            self.debugger.Terminate()

    def install(self, target: lldb.SBTarget) -> None:
        self.target = target
        bps = set_entrypoint_breakpoints(self.debugger)
        self.debugger.HandleCommand("command script import --allow-reload tracer")
        if len(bps) > 1:
            print("found entry, only use first one", ",".join([f"{name} (ID: {bp.GetID()})" for name, bp in bps]))
        name, bp = bps[0]
        bp.SetOneShot(True)
        self.breakpoint = bp

        if self.config_manager.config.get("log_breakpoint_details"):
            self.log_manager.log_breakpoint_info(self.breakpoint)
