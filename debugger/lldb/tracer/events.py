from enum import Enum, auto

import lldb

from .utils import get_stop_reason_str


class StepAction(Enum):
    """Enumeration for step action decisions"""

    STEP_OVER = auto()
    STEP_IN = auto()
    CONTINUE = auto()
    SOURCE_STEP_IN = auto()
    SOURCE_STEP_OVER = auto()
    SOURCE_STEP_OUT = auto()


def handle_special_stop(thread, stop_reason, logger, target=None, die_event=False):
    """Handle various stop reasons with enhanced information and actions."""
    frame = thread.GetFrameAtIndex(0) if thread.GetNumFrames() > 0 else None
    process = thread.GetProcess()

    # Get current location if frame is available
    location_info = ""
    if frame and frame.IsValid():
        file_spec = frame.GetLineEntry().GetFileSpec()
        line = frame.GetLineEntry().GetLine()
        func_name = frame.GetFunctionName() or "unknown function"
        location_info = " at %s:%d in %s" % (file_spec.GetFilename(), line, func_name)

    if stop_reason == lldb.eStopReasonWatchpoint:
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

    elif stop_reason == lldb.eStopReasonSignal:
        signal_num = thread.GetStopReasonDataAtIndex(0)
        signal_name = process.GetUnixSignals().GetSignalAsCString(signal_num)
        logger.info("Received signal %d (%s)%s", signal_num, signal_name, location_info)

        # For common signals like SIGSEGV, provide more context
        if signal_num == 11:  # SIGSEGV
            logger.error("Segmentation fault%s", location_info)
            if frame and frame.IsValid():
                # Attempt to get more context about the crash
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

    elif stop_reason == lldb.eStopReasonException:
        exc_desc = ""
        if thread.GetStopReasonDataCount() >= 2:
            exc_type = thread.GetStopReasonDataAtIndex(0)
            exc_addr = thread.GetStopReasonDataAtIndex(1)
            exc_desc = " type=0x%x, address=0x%x" % (exc_type, exc_addr)
        stop_desc = thread.GetStopDescription(1024)
        if "EXC_BREAKPOINT" in stop_desc:
            logger.info("Process hit a breakpoint: %s", stop_desc)
            return
        logger.info("Exception occurred%s %s", exc_desc, stop_desc)
        target.process.Stop()
        if die_event:
            logger.info("Process will exit due to exception stop reason.")
            die_event.set()
    elif stop_reason in (
        lldb.eStopReasonExec,
        lldb.eStopReasonFork,
        lldb.eStopReasonVFork,
        lldb.eStopReasonVForkDone,
        lldb.eStopReasonThreadExiting,
        lldb.eStopReasonInstrumentation,
        lldb.eStopReasonTrace,
    ):
        reason_str = {
            lldb.eStopReasonExec: "Exec",
            lldb.eStopReasonFork: "Process forked, child PID: %d",
            lldb.eStopReasonVFork: "Process vforked, child PID: %d",
            lldb.eStopReasonVForkDone: "VFork done",
            lldb.eStopReasonThreadExiting: "Thread %d is exiting",
            lldb.eStopReasonInstrumentation: "Instrumentation event",
            lldb.eStopReasonTrace: "Trace event",
        }[stop_reason]

        if stop_reason in (lldb.eStopReasonFork, lldb.eStopReasonVFork):
            child_pid = thread.GetStopReasonDataAtIndex(0)
            logger.info(reason_str + location_info, child_pid)
        elif stop_reason == lldb.eStopReasonThreadExiting:
            logger.info(reason_str + location_info, thread.GetThreadID())
        else:
            logger.info(reason_str + location_info)

    else:
        # logger.info("Unhandled stop reason: %s %s %s", stop_reason, get_stop_reason_str(stop_reason), location_info)
        thread.StepInstruction(True)
