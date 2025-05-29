from enum import Enum, auto

import lldb


def get_stop_reason_str(reason):
    """Convert stop reason integer to descriptive string."""
    reason_map = {
        lldb.eStopReasonInvalid: "Invalid",
        lldb.eStopReasonNone: "None",
        lldb.eStopReasonTrace: "Trace",
        lldb.eStopReasonBreakpoint: "Breakpoint",
        lldb.eStopReasonWatchpoint: "Watchpoint",
        lldb.eStopReasonSignal: "Signal",
        lldb.eStopReasonException: "Exception",
        lldb.eStopReasonExec: "Exec",
        lldb.eStopReasonFork: "Fork",
        lldb.eStopReasonVFork: "VFork",
        lldb.eStopReasonVForkDone: "VForkDone",
        lldb.eStopReasonPlanComplete: "PlanComplete",
        lldb.eStopReasonThreadExiting: "ThreadExiting",
        lldb.eStopReasonInstrumentation: "Instrumentation",
    }
    return reason_map.get(reason, f"Unknown ({reason})")


class OperandType(Enum):
    REGISTER = auto()
    IMMEDIATE = auto()
    MEMORY = auto()
    LABEL = auto()
