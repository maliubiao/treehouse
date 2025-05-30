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


def get_state_str(state):
    """Convert state integer to descriptive string."""
    state_map = {
        lldb.eStateInvalid: "Invalid",
        lldb.eStateUnloaded: "Unloaded",
        lldb.eStateConnected: "Connected",
        lldb.eStateAttaching: "Attaching",
        lldb.eStateLaunching: "Launching",
        lldb.eStateStopped: "Stopped",
        lldb.eStateRunning: "Running",
        lldb.eStateStepping: "Stepping",
        lldb.eStateCrashed: "Crashed",
        lldb.eStateDetached: "Detached",
        lldb.eStateExited: "Exited",
        lldb.eStateSuspended: "Suspended",
    }
    return state_map.get(state, f"Unknown ({state})")
