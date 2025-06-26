from enum import Enum, auto

import lldb

from .utils import get_stop_reason_str


class StepAction(Enum):
    """Enumeration for step action decisions"""

    INVALID = auto()
    STEP_OVER = auto()
    STEP_IN = auto()
    CONTINUE = auto()
    SOURCE_STEP_IN = auto()
    SOURCE_STEP_OVER = auto()
    SOURCE_STEP_OUT = auto()
    STEP_OUT = auto()
    STEP_INTO_THUNK = auto()


def handle_special_stop(thread, stop_reason, logger, target=None, die_event=False):
    """Handle various stop reasons with enhanced information and actions."""

    def _get_location_info(frame):
        """Helper to get location info from frame."""
        if not frame or not frame.IsValid():
            return ""
        file_spec = frame.GetLineEntry().GetFileSpec()
        line = frame.GetLineEntry().GetLine()
        func_name = frame.GetFunctionName() or "unknown function"
        return f" at {file_spec.GetFilename()}:{line} in {func_name}"

    def _handle_watchpoint(thread, target, location_info):
        """Handle watchpoint stop reason."""
        wp_id = thread.GetStopReasonDataAtIndex(0)
        watchpoint = target.FindWatchpointByID(wp_id) if target else None
        if watchpoint and watchpoint.IsValid():
            logger.info(
                "Watchpoint %d triggered%s: address=0x%x, size=%d",
                wp_id,
                location_info,
                watchpoint.GetWatchAddress(),
                watchpoint.GetWatchSize(),
            )

    def _handle_signal(thread, process, location_info):
        """Handle signal stop reason."""
        signal_num = thread.GetStopReasonDataAtIndex(0)
        signal_name = process.GetUnixSignals().GetSignalAsCString(signal_num)
        logger.info("Received signal %d (%s)%s", signal_num, signal_name, location_info)

        if signal_num == 11:  # SIGSEGV
            logger.error("Segmentation fault%s", location_info)
            if thread.GetNumFrames() > 0:
                logger.info("Stack trace at crash point:")
                for i in range(min(5, thread.GetNumFrames())):
                    f = thread.GetFrameAtIndex(i)
                    logger.info(
                        "  #%d: %s at %s:%d",
                        i,
                        f.GetFunctionName(),
                        f.GetLineEntry().GetFileSpec().GetFilename(),
                        f.GetLineEntry().GetLine(),
                    )
        elif signal_num == 17:  # SIGSTOP
            logger.info("Process stopped by SIGSTOP%s", location_info)
            thread.process.Continue()

    def _handle_exception(thread, stop_desc, die_event, debugger):
        """Handle exception stop reason."""
        exc_desc = ""
        if thread.GetStopReasonDataCount() >= 2:
            exc_type = thread.GetStopReasonDataAtIndex(0)
            exc_addr = thread.GetStopReasonDataAtIndex(1)
            exc_desc = f" type=0x{exc_type:x}, address=0x{exc_addr:x}"

        if "EXC_BREAKPOINT" in stop_desc:
            logger.info("Breakpoint encountered: %s", stop_desc)
            # 在断点处启动交互式控制台
            from .lldb_console import show_console

            show_console(debugger)
            return True

        logger.info("Exception occurred%s %s", exc_desc, stop_desc)
        target.process.Stop()
        if die_event:
            logger.info("Process will exit due to exception stop reason.")
            die_event.set()
        return False

    def _handle_special_events(thread, stop_reason, location_info):
        """Handle special process events."""
        reason_handlers = {
            lldb.eStopReasonExec: lambda: "Exec",
            lldb.eStopReasonFork: lambda: f"Process forked, child PID: {thread.GetStopReasonDataAtIndex(0)}",
            lldb.eStopReasonVFork: lambda: f"Process vforked, child PID: {thread.GetStopReasonDataAtIndex(0)}",
            lldb.eStopReasonVForkDone: lambda: "VFork done",
            lldb.eStopReasonThreadExiting: lambda: f"Thread {thread.GetThreadID()} is exiting",
            lldb.eStopReasonInstrumentation: lambda: "Instrumentation event",
            lldb.eStopReasonTrace: lambda: "Trace event",
        }

        if stop_reason in reason_handlers:
            logger.info(reason_handlers[stop_reason]() + location_info)
            return True
        return False

    # Main function logic
    frame = thread.GetFrameAtIndex(0) if thread.GetNumFrames() > 0 else None
    location_info = _get_location_info(frame)
    process = thread.GetProcess()

    if stop_reason == lldb.eStopReasonWatchpoint:
        _handle_watchpoint(thread, target, location_info)
    elif stop_reason == lldb.eStopReasonSignal:
        _handle_signal(thread, process, location_info)
    elif stop_reason == lldb.eStopReasonException:
        stop_desc = thread.GetStopDescription(1024)
        if _handle_exception(thread, stop_desc, die_event):
            return
    elif _handle_special_events(thread, stop_reason, location_info):
        pass
    else:
        logger.info(
            "Unhandled stop reason:%s %s %s %s",
            stop_reason,
            get_stop_reason_str(stop_reason),
            location_info,
            str(thread),
        )
        thread.process.Continue()
