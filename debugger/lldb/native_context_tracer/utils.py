import importlib
import platform
import select
import sys

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


def get_symbol_type_str(symbol_type):
    """Convert symbol type integer to descriptive string."""
    symbol_type_map = {
        lldb.eSymbolTypeAny: "Any",
        lldb.eSymbolTypeInvalid: "Invalid",
        lldb.eSymbolTypeAbsolute: "Absolute",
        lldb.eSymbolTypeCode: "Code",
        lldb.eSymbolTypeResolver: "Resolver",
        lldb.eSymbolTypeData: "Data",
        lldb.eSymbolTypeTrampoline: "Trampoline",
        lldb.eSymbolTypeRuntime: "Runtime",
        lldb.eSymbolTypeException: "Exception",
        lldb.eSymbolTypeSourceFile: "SourceFile",
        lldb.eSymbolTypeHeaderFile: "HeaderFile",
        lldb.eSymbolTypeObjectFile: "ObjectFile",
        lldb.eSymbolTypeCommonBlock: "CommonBlock",
        lldb.eSymbolTypeBlock: "Block",
        lldb.eSymbolTypeLocal: "Local",
        lldb.eSymbolTypeParam: "Param",
        lldb.eSymbolTypeVariable: "Variable",
        lldb.eSymbolTypeVariableType: "VariableType",
        lldb.eSymbolTypeLineEntry: "LineEntry",
        lldb.eSymbolTypeLineHeader: "LineHeader",
        lldb.eSymbolTypeScopeBegin: "ScopeBegin",
        lldb.eSymbolTypeScopeEnd: "ScopeEnd",
        lldb.eSymbolTypeAdditional: "Additional",
        lldb.eSymbolTypeCompiler: "Compiler",
        lldb.eSymbolTypeInstrumentation: "Instrumentation",
        lldb.eSymbolTypeUndefined: "Undefined",
        lldb.eSymbolTypeObjCClass: "ObjCClass",
        lldb.eSymbolTypeObjCMetaClass: "ObjCMetaClass",
        lldb.eSymbolTypeObjCIVar: "ObjCIVar",
        lldb.eSymbolTypeReExported: "ReExported",
    }
    return symbol_type_map.get(symbol_type, f"Unknown ({symbol_type})")


def get_platform_stdin_listener():
    """获取平台特定的标准输入监听器"""
    os_name = platform.system()

    if os_name == "Windows":
        return WindowsStdinListener()
    else:  # Unix-like系统 (Linux, macOS)
        return UnixStdinListener()


class StdinListener:
    """标准输入监听器基类"""

    def has_input(self):
        raise NotImplementedError

    def read(self):
        raise NotImplementedError


class UnixStdinListener(StdinListener):
    """Unix-like系统的标准输入监听器"""

    def has_input(self):
        return select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], [])

    def read(self):
        return sys.stdin.readline()


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import msvcrt

msvcrt = importlib.import_module("msvcrt") if platform.system() == "Windows" else None


class WindowsStdinListener(StdinListener):
    """Windows系统的标准输入监听器"""

    def has_input(self):
        return msvcrt.kbhit() != 0

    def read(self):
        # Windows需要逐字符读取
        chars = []
        while msvcrt.kbhit():
            char = msvcrt.getwch()
            chars.append(char)
        return "".join(chars)
