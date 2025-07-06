import logging
import threading
from typing import TYPE_CHECKING, Optional

import lldb

from .debugger_api import (
    DebuggerApi,
    IOHandler,
    LldbDebuggerApi,
    SystemIOHandler,
)
from .events import StepAction, handle_special_stop
from .libc_hooker import get_libc_hooker
from .utils import get_state_str, get_stop_reason_str

if TYPE_CHECKING:
    from .core import Tracer  # Avoid circular import issues


class EventLoop:
    def __init__(
        self,
        tracer: "Tracer",
        listener: lldb.SBListener,
        logger: logging.Logger,
        debugger_api: Optional[DebuggerApi] = None,
        io_handler: Optional[IOHandler] = None,
    ) -> None:
        self.tracer: "Tracer" = tracer
        self.listener: lldb.SBListener = listener
        self.logger: logging.Logger = logger
        self.debugger_api: DebuggerApi = debugger_api or LldbDebuggerApi(self.tracer)
        self.io_handler: IOHandler = io_handler or SystemIOHandler()
        self.die_event: threading.Event = threading.Event()
        self.threads = {}

    def run(self) -> None:
        while not self.die_event.is_set():
            ok, event = self.debugger_api.wait_for_event(self.listener, 1)
            if ok:
                self._process_event(event)
            else:
                # 如果在超时时间内没有收到事件，则记录当前调试器状态
                self._log_current_debugger_status()

    def _process_event(self, event: lldb.SBEvent) -> None:
        """处理事件分发"""
        if (
            self.debugger_api.get_event_broadcaster_class_name(event)
            == self.debugger_api.get_process_broadcaster_class_name()
        ):
            if self.debugger_api.is_stdout_event(event):
                self._handle_stdout_event(event)
            elif self.debugger_api.is_stderr_event(event):
                self._handle_stderr_event(event)
            elif self.debugger_api.is_state_changed_event(event):
                self._handle_state_change_event(event)
        else:
            self.logger.warning("Unhandled event type: %s", self.debugger_api.get_event_broadcaster_class_name(event))

    def _handle_stdout_event(self, event: lldb.SBEvent) -> None:
        """处理标准输出事件"""
        process = self.debugger_api.get_process_from_event(event)
        if not process:
            return

        try:
            output = self.debugger_api.get_process_stdout(process, 1024)
            if output:
                self.io_handler.write_stdout(output)
        except SystemError:
            pass  # 忽略异常，继续执行

    def _handle_stderr_event(self, event: lldb.SBEvent) -> None:
        """处理标准错误事件"""
        process = self.debugger_api.get_process_from_event(event)
        if not process:
            return

        try:
            error = self.debugger_api.get_process_stderr(process, 1024)
            if error:
                self.io_handler.write_stderr(error)
        except SystemError:
            pass  # 忽略异常，继续执行

    def _handle_state_change_event(self, event: lldb.SBEvent) -> None:
        """处理状态变化事件"""
        process: Optional[lldb.SBProcess] = self.debugger_api.get_process_from_event(event)
        if process and process.IsValid():
            self._handle_process_state(process, event)

    def _handle_process_state(self, process: lldb.SBProcess, event: lldb.SBEvent) -> None:
        """处理进程状态变化"""
        state: int = self.debugger_api.get_process_state(process)
        if state == lldb.eStateStopped:
            self._handle_stopped_state(process, event)
        elif state in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
            self._handle_termination_state(process, state)
        elif state == lldb.eStateRunning:
            return
        else:
            self.logger.info("Unhandled process state: %s", get_state_str(state))

    def _handle_stopped_state(self, process: lldb.SBProcess, event: lldb.SBEvent) -> None:
        """处理停止状态"""
        thread: lldb.SBThread = self.debugger_api.get_selected_thread(process)
        if self.tracer.main_thread_id > 0 and thread.GetThreadID() != self.tracer.main_thread_id:
            self.logger.info(
                "Thread %s stopped, but main thread is %s, continuing execution",
                thread.GetThreadID(),
                self.tracer.main_thread_id,
            )
            self.debugger_api.step_out(thread)
            return
        count = 0
        while self.debugger_api.get_thread_stop_reason(thread) == lldb.eStopReasonNone and count < 10:
            # 线程还没有停止，等待一段时间，reason获取不到
            self.debugger_api.sleep(0.1)
            count += 1
        if count >= 10:
            for i in self.debugger_api.get_process_threads(process):
                if self.debugger_api.get_thread_stop_reason(i) != lldb.eStopReasonNone:
                    self.logger.info(
                        "Thread %s found with stop reason %s after excessive wait.",
                        i.GetThreadID(),
                        self.debugger_api.get_thread_stop_reason(i),
                    )
            self.logger.info("Excessive wait for thread stop reason, continuing process.")
            self.debugger_api.continue_process(process)
            return
        stop_reason = self.debugger_api.get_thread_stop_reason(thread)
        if stop_reason == lldb.eStopReasonBreakpoint:
            self._handle_breakpoint_stop(process, thread)
        elif stop_reason == lldb.eStopReasonPlanComplete:
            self._handle_plan_complete(thread)
        elif stop_reason == lldb.eStopReasonTrace:
            self.logger.info("hit trace, continue execution")
            self.debugger_api.continue_process(process)
        else:
            handle_special_stop(thread, stop_reason, self.logger, self.tracer.target, die_event=self.die_event)
        _ = event  # 显式标记参数为已使用，避免警告

    def _handle_breakpoint_stop(self, process: lldb.SBProcess, thread: lldb.SBThread) -> None:
        """处理断点停止"""
        count = 0
        while self.debugger_api.get_stop_reason_data_at_index(thread, 0) > 0xFFFFFFFFFFFFFF and count < 20:
            # 等待线程停止数据更新
            self.debugger_api.sleep(0.1)
            count += 1
        if count >= 20:
            self.logger.warning("Failed to get valid breakpoint ID after 20 attempts, continuing process.")
            self.debugger_api.continue_process(process)
            return
        bp_id: int = self.debugger_api.get_stop_reason_data_at_index(thread, 0)
        frame = self.debugger_api.get_frame_at_index(thread, 0)
        pc = self.debugger_api.get_frame_pc(frame)

        # Handle entry point breakpoint first
        if (
            not self.tracer.entry_point_breakpoint_event.is_set()
            and self.tracer.breakpoint is not None
            and bp_id == self.tracer.breakpoint.GetID()
        ):
            self.tracer.main_thread_id = thread.GetThreadID()
            self.tracer.entry_point_breakpoint_event.set()
            self.tracer.step_handler.base_frame_count = frame.thread.GetNumFrames()
            self.debugger_api.step_instruction(thread, False)
            self.logger.info("Entry point breakpoint hit: thread %s", thread.GetThreadID())
            return
        elif pc in self.tracer.breakpoint_seen:
            self._handle_lr_breakpoint(thread)
        elif bp_id == self.tracer.pthread_create_breakpoint_id:
            # 保持调用但不赋值
            self.handle_pthread_create_breakpoint(process, thread)
        elif bp_id == self.tracer.pthread_join_breakpoint_id:
            self.logger.info("Hit pthread_join breakpoint, continuing execution")
            self.debugger_api.continue_process(process)
        else:
            # bp_loc_id: int = self.debugger_api.get_stop_reason_data_at_index(thread, 1)
            bp = self.debugger_api.find_breakpoint_by_id(self.tracer.target, bp_id)
            self.logger.info("Breakpoint %s hit at PC: 0x%x, frame: %s, thread %s", bp, pc, frame, thread)
            self.tracer.breakpoint_handler.handle_breakpoint(frame, bp_id)

    def handle_pthread_create_breakpoint(self, process: lldb.SBProcess, thread: lldb.SBThread) -> None:
        """
        Handle pthread_create breakpoint by setting a breakpoint at the thread entry point.
        For ARM64, the thread function pointer is passed as the third argument (x2 register).
        """
        frame = self.debugger_api.get_frame_at_index(thread, 0)
        # On ARM64, the thread function pointer is in x2 register
        # (args are in x0, x1, x2, x3, etc. for the first few arguments)
        thread_function_ptr_reg = self.debugger_api.find_register(frame, "x2")
        thread_function_ptr = thread_function_ptr_reg.GetValueAsUnsigned()

        if thread_function_ptr:
            addr = self.debugger_api.resolve_load_address(self.tracer.target, thread_function_ptr)
            if not addr.IsValid():
                self.logger.error("无法解析线程函数指针地址: 0x%x", thread_function_ptr)
                self.debugger_api.continue_process(process)
                return
            if addr.symbol.prologue_size > 0:
                thread_function_ptr += addr.symbol.prologue_size
            # Create a breakpoint at the thread entry point
            bp = self.debugger_api.create_breakpoint_by_address(self.tracer.target, thread_function_ptr)
            if bp.IsValid():
                bp_id = bp.GetID()
                self.logger.info("在线程入口点创建断点: %s", bp)
                # Add breakpoint ID to thread entry seen set
                self.tracer.thread_breakpoint_seen.add(bp_id)
            else:
                self.logger.error("在线程入口点创建断点失败：0x%x", thread_function_ptr)
            # self.logger.info("%s\n", self.debugger_api.resolve_load_address(self.tracer.target, thread_function_ptr))
        # Continue execution
        self.debugger_api.continue_process(process)

    def _handle_lr_breakpoint(self, thread: lldb.SBThread) -> None:
        """处理LR断点"""
        frame: lldb.SBFrame = self.debugger_api.get_frame_at_index(thread, 0)
        pc = self.debugger_api.get_frame_pc(frame)

        if self.tracer.modules.should_skip_address(pc):
            self.logger.debug("Skipped LR breakpoint at 0x%x", pc)
            return

        action: StepAction = self.tracer.step_handler.on_step_hit(frame, "lr_breakpoint")
        self.action_handle(action, thread)

    def action_handle(self, action: StepAction, thread: lldb.SBThread) -> None:
        """处理特定的步进动作"""
        # self.logger.info("Handling action: %s", action.name)
        if action == StepAction.STEP_OVER:
            # self.logger.info("Step over detected")
            err = self.debugger_api.step_instruction(thread, True)
            if err.Fail():
                self.logger.error("Step instruction failed: %s", err.GetCString())
        elif action == StepAction.STEP_IN:
            # self.logger.info("Step in detected")
            err = self.debugger_api.step_instruction(thread, False)
            if err.Fail():
                self.logger.error("Step instruction failed: %s", err.GetCString())
        elif action == StepAction.SOURCE_STEP_IN:
            self.debugger_api.step_into(thread, lldb.eOnlyDuringStepping)
            # self.logger.info("Source step in detected")
        elif action == StepAction.SOURCE_STEP_OVER:
            self.debugger_api.step_over(thread, lldb.eOnlyDuringStepping)
            # self.logger.info("Source step over detected")
        elif action == StepAction.SOURCE_STEP_OUT:
            # self.logger.info("Step out detected")
            self.debugger_api.step_out(thread)

    def _handle_plan_complete(self, thread: lldb.SBThread) -> None:
        """处理计划完成"""
        if self.tracer.entry_point_breakpoint_event.is_set():
            frame: lldb.SBFrame = self.debugger_api.get_frame_at_index(thread, 0)
            action: StepAction = self.tracer.step_handler.on_step_hit(frame, "threadplan")
            self.action_handle(action, thread)

    def _handle_termination_state(self, process: lldb.SBProcess, state: int) -> None:
        """处理进程终止状态"""
        if state == lldb.eStateExited:
            exit_status: int = self.debugger_api.get_process_exit_status(process)
            self.logger.info("Process exited with status: %d", exit_status)
        elif state == lldb.eStateCrashed:
            self.logger.error("Process crashed")
        elif state == lldb.eStateDetached:
            self.logger.info("Process detached")
        self.die_event.set()

    def _log_current_debugger_status(self) -> None:
        """
        当没有收到事件时，记录当前调试器状态（进程、线程、栈帧）。
        使用 tracer 的 run_cmd 来获取状态。
        """
        process = self.tracer.process
        if process and process.IsValid():
            state = self.debugger_api.get_process_state(process)
            if state == lldb.eStateStopped:
                self.logger.info("--- Debugger Status (No Event Received) ---")
                self.logger.info("Process State: %s", get_state_str(state))

                try:
                    # 获取进程状态（包含通用信息）
                    # tracer.run_cmd 会将命令输出记录到 logger
                    result = self.debugger_api.run_command("process status")
                    if not (result and result.Succeeded()):
                        self.logger.warning("Failed to get process status.")

                    # 获取线程列表（包含当前栈帧信息）
                    result = self.debugger_api.run_command("thread list")
                    if not (result and result.Succeeded()):
                        self.logger.warning("Failed to get thread list.")

                    # 显式获取当前选定线程的栈帧信息
                    result = self.debugger_api.run_command("frame info")
                    if not (result and result.Succeeded()):
                        self.logger.warning("Failed to get current frame info.")
                except ValueError as e:
                    self.logger.error("Error running LLDB command for status check: %s", e)
                self.logger.info("--- End Debugger Status ---")
            else:
                self.logger.info(
                    "Process is not stopped (current state: %s). Skipping detailed status log.", get_state_str(state)
                )
        else:
            self.logger.info("No valid process to log status.")
