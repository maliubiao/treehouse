import logging
import sys
import threading
from typing import TYPE_CHECKING

import lldb

from .events import StepAction, handle_special_stop
from .utils import get_stop_reason_str

if TYPE_CHECKING:
    from .core import Tracer  # Avoid circular import issues


class EventLoop:
    def __init__(self, tracer: "Tracer", listener: lldb.SBListener, logger: logging.Logger) -> None:
        self.tracer: Tracer = tracer
        self.listener: lldb.SBListener = listener
        self.logger: logging.Logger = logger
        self.die_event: threading.Event = threading.Event()

    def run(self) -> None:
        event: lldb.SBEvent = lldb.SBEvent()
        while not self.die_event.is_set():
            ok: bool = self.listener.WaitForEvent(1, event)
            if ok:
                self._process_event(event)

    def _process_event(self, event: lldb.SBEvent) -> None:
        """处理事件分发"""
        if event.GetType() & lldb.SBProcess.eBroadcastBitSTDOUT:
            self._handle_stdout_event(event)
        elif event.GetType() & lldb.SBProcess.eBroadcastBitSTDERR:
            self._handle_stderr_event(event)
        elif event.GetType() & lldb.SBProcess.eBroadcastBitStateChanged:
            self._handle_state_change_event(event)

    def _handle_stdout_event(self, event: lldb.SBEvent) -> None:
        """处理标准输出事件"""
        process = lldb.SBProcess.GetProcessFromEvent(event)
        if not process:
            return

        try:
            output = process.GetSTDOUT(1024)
            if output:
                sys.stdout.write(output)
                sys.stdout.flush()
        except SystemError:
            pass  # 忽略异常，继续执行

    def _handle_stderr_event(self, event: lldb.SBEvent) -> None:
        """处理标准错误事件"""
        process = lldb.SBProcess.GetProcessFromEvent(event)
        if not process:
            return

        try:
            error = process.GetSTDERR(1024)
            if error:
                sys.stderr.write(error)
                sys.stderr.flush()
        except SystemError:
            pass  # 忽略异常，继续执行

    def _handle_state_change_event(self, event: lldb.SBEvent) -> None:
        """处理状态变化事件"""
        process: lldb.SBProcess = lldb.SBProcess.GetProcessFromEvent(event)
        if process and process.IsValid():
            self._handle_process_state(process)

    def _handle_process_state(self, process: lldb.SBProcess) -> None:
        """处理进程状态变化"""
        state: int = process.GetState()
        if state == lldb.eStateStopped:
            self._handle_stopped_state(process)
        elif state in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
            self._handle_termination_state(process, state)

    def _handle_stopped_state(self, process: lldb.SBProcess) -> None:
        """处理停止状态"""
        thread: lldb.SBThread = process.GetSelectedThread()
        stop_reason: int = thread.GetStopReason()

        if stop_reason == lldb.eStopReasonBreakpoint:
            self._handle_breakpoint_stop(thread)
        elif stop_reason == lldb.eStopReasonPlanComplete:
            self._handle_plan_complete(thread)
        elif stop_reason == lldb.eStopReasonTrace:
            self.logger.info("hit trace, continue execution")
            process.Continue()
        else:
            handle_special_stop(thread, stop_reason, self.logger, self.tracer.target, die_event=self.die_event)

    def _handle_breakpoint_stop(self, thread: lldb.SBThread) -> None:
        """处理断点停止"""
        bp_id: int = thread.GetStopReasonDataAtIndex(0)
        if bp_id in self.tracer.breakpoint_seen:
            self._handle_lr_breakpoint(thread)
        else:
            bp_loc_id: int = thread.GetStopReasonDataAtIndex(1)
            self.logger.info("Breakpoint ID: %d, Location: %d", bp_id, bp_loc_id)
            frame: lldb.SBFrame = thread.GetFrameAtIndex(0)
            self.tracer.breakpoint_handler.handle_breakpoint(frame, bp_id)

    def _handle_lr_breakpoint(self, thread: lldb.SBThread) -> None:
        """处理LR断点"""
        # self.logger.info("Hit LR breakpoint, continuing execution")
        frame: lldb.SBFrame = thread.GetFrameAtIndex(0)
        action: StepAction = self.tracer.step_handler.on_step_hit(frame)
        self.action_handle(action, thread)

    def action_handle(self, action: StepAction, thread: lldb.SBThread) -> None:
        """处理特定的步进动作"""
        if action == StepAction.STEP_OVER:
            # self.logger.info("Step over detected")
            thread.StepInstruction(True)
        elif action == StepAction.STEP_IN:
            # self.logger.info("Step in detected")
            thread.StepInstruction(False)
        elif action == StepAction.SOURCE_STEP_IN:
            thread.StepInto()
            # self.logger.info("Source step in detected")
        elif action == StepAction.SOURCE_STEP_OVER:
            thread.StepOver()
            # self.logger.info("Source step over detected")
        elif action == StepAction.SOURCE_STEP_OUT:
            # self.logger.info("Step out detected")
            thread.StepOut()

    def _handle_plan_complete(self, thread: lldb.SBThread) -> None:
        """处理计划完成"""
        if self.tracer.entry_point_breakpoint_event.is_set():
            frame: lldb.SBFrame = thread.GetFrameAtIndex(0)
            action: StepAction = self.tracer.step_handler.on_step_hit(frame)
            self.action_handle(action, thread)

    def _handle_termination_state(self, process: lldb.SBProcess, state: int) -> None:
        """处理进程终止状态"""
        if state == lldb.eStateExited:
            exit_status: int = process.GetExitStatus()
            self.logger.info("Process exited with status: %d", exit_status)
        elif state == lldb.eStateCrashed:
            self.logger.error("Process crashed")
        elif state == lldb.eStateDetached:
            self.logger.info("Process detached")
        self.die_event.set()
