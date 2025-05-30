import logging
import sys
import threading
import time
from typing import Any

import lldb

from .events import StepAction, handle_special_stop
from .utils import get_state_str, get_stop_reason_str


class EventLoop:
    def __init__(self, tracer: Any, listener: lldb.SBListener, logger: logging.Logger) -> None:
        self.tracer: Any = tracer
        self.listener: lldb.SBListener = listener
        self.logger: logging.Logger = logger
        self.die_event: threading.Event = threading.Event()

    def run(self) -> None:
        event: lldb.SBEvent = lldb.SBEvent()
        while not self.die_event.is_set():
            ok: bool = self.listener.WaitForEvent(1, event)
            if ok:
                # 处理输出事件
                if event.GetType() & lldb.SBProcess.eBroadcastBitSTDOUT:
                    process = lldb.SBProcess.GetProcessFromEvent(event)
                    if process:
                        try:
                            output = process.GetSTDOUT(1024)
                        except SystemError as e:
                            continue
                        if output:
                            sys.stdout.write(output)
                            sys.stdout.flush()

                # 处理错误事件
                elif event.GetType() & lldb.SBProcess.eBroadcastBitSTDERR:
                    process = lldb.SBProcess.GetProcessFromEvent(event)
                    if process:
                        try:
                            error = process.GetSTDERR(1024)
                        except SystemError as e:
                            continue
                        if error:
                            sys.stderr.write(error)
                            sys.stderr.flush()

                # 处理状态变化事件
                elif event.GetType() & lldb.SBProcess.eBroadcastBitStateChanged:
                    process: lldb.SBProcess = lldb.SBProcess.GetProcessFromEvent(event)
                    if process and process.IsValid():
                        self._handle_process_event(process)

    def _handle_process_event(self, process: lldb.SBProcess) -> None:
        state: int = process.GetState()
        self.logger.info("Process state: %s", get_state_str(state))
        if state == lldb.eStateStopped:
            thread: lldb.SBThread = process.GetSelectedThread()
            stop_reason: int = thread.GetStopReason()

            if stop_reason == lldb.eStopReasonBreakpoint:
                bp_id: int = thread.GetStopReasonDataAtIndex(0)
                bp_loc_id: int = thread.GetStopReasonDataAtIndex(1)
                self.logger.info("Breakpoint ID: %d, Location: %d", bp_id, bp_loc_id)
                frame: lldb.SBFrame = thread.GetFrameAtIndex(0)
                self.tracer.breakpoint_handler.handle_breakpoint(frame, bp_id)
            elif stop_reason == lldb.eStopReasonPlanComplete:
                if self.tracer.entry_point_breakpoint_event.is_set():
                    frame: lldb.SBFrame = thread.GetFrameAtIndex(0)
                    action: StepAction = self.tracer.step_handler.on_step_hit(frame)
                    if action == StepAction.STEP_OVER:
                        self.logger.info("Step over detected")
                        thread.StepInstruction(True)
                    elif action == StepAction.STEP_IN:
                        thread.StepInstruction(False)
            elif stop_reason == lldb.eStopReasonTrace:
                self.logger.info("hit trace, continue execution")
                process.Continue()
            else:
                handle_special_stop(thread, stop_reason, self.logger, self.tracer.target, die_event=self.die_event)

        elif state in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
            if state == lldb.eStateExited:
                exit_status: int = process.GetExitStatus()
                self.logger.info("Process exited with status: %d", exit_status)
            elif state == lldb.eStateCrashed:
                self.logger.error("Process crashed")
            elif state == lldb.eStateDetached:
                self.logger.info("Process detached")
            self.die_event.set()
