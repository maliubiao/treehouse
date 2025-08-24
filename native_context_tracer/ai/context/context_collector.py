from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import lldb


@dataclass
class ThreadContext:
    thread_id: int
    index_id: int
    name: str
    queue: str
    stop_reason: int
    stop_description: str
    frame_count: int
    current_frame: Dict[str, Any]
    # memory_regions: Dict[str, Any]
    globals: Dict[str, Any]
    # registers: Dict[str, Any]
    variables: Dict[str, Any]
    extended_backtrace_types: List[str]
    history: List[Dict[str, Any]]  # Added thread history

    def to_dict(self):
        return asdict(self)


@dataclass
class ProcessContext:
    thread_count: int
    state: str
    pid: int
    total_threads: int
    selected_thread_id: Optional[int]
    # threads: Dict[str, Any]
    # memory_regions: Dict[str, Any]  # Added process-wide memory regions
    exit_status: Optional[int]  # Added exit status
    exit_description: Optional[str]  # Added exit description
    is_running: bool  # Added running state
    is_stopped: bool  # Added stopped state
    stop_id: int  # Added stop ID counter
    unique_id: int  # Added unique process ID
    unix_signals: Dict[str, bool]  # Added Unix signals info

    def to_dict(self):
        return asdict(self)


@dataclass
class TargetContext:
    triple: str
    byte_order: str
    address_byte_size: int
    code_byte_size: int
    data_byte_size: int
    valid: bool

    def to_dict(self):
        return asdict(self)


@dataclass
class DebugContext:
    thread: ThreadContext
    process: ProcessContext
    target: TargetContext
    environment: Dict[str, Any]

    def to_dict(self):
        return {
            "thread": self.thread.to_dict(),
            "process": self.process.to_dict(),
            "target": self.target.to_dict(),
            "environment": self.environment,
        }


class ContextCollector:
    def _get_thread_info(self, thread) -> Dict[str, Any]:
        if not thread or not thread.IsValid():
            return {
                "thread_id": 0,
                "index_id": 0,
                "name": "",
                "queue": "",
                "stop_reason": 0,
                "stop_description": "",
                "frame_count": 0,
                "current_frame": {},
                "globals": {},
                # "registers": {},
                "variables": {},
                "extended_backtrace_types": [],
                "history": [],
            }

        frame = thread.GetSelectedFrame() if thread.IsValid() else None
        thread_info = {
            "thread_id": thread.GetThreadID(),
            "index_id": thread.GetIndexID(),
            "name": thread.GetName() or "",
            "queue": thread.GetQueueName() or "",
            "stop_reason": thread.GetStopReason(),
            "stop_description": thread.GetStopDescription(256) or "",
            "frame_count": thread.GetNumFrames(),
            "current_frame": {},
            # 'memory_regions': {},
            "globals": {},
            # "registers": self._get_register_values(frame) if frame else {},
            "variables": self._get_local_variables(frame) if frame else {},
            "extended_backtrace_types": self._get_extended_backtrace_types(thread),
            "history": self._get_thread_history(thread),
        }

        if frame and frame.IsValid():
            thread_info["current_frame"] = {
                "function": frame.GetFunctionName(),
                "line_entry": str(frame.GetLineEntry()),
                "pc": frame.GetPC(),
                "symbol": frame.GetSymbol().GetName() if frame.GetSymbol() else "",
            }

        return thread_info

    def _get_thread_history(self, thread) -> List[Dict[str, Any]]:
        if not thread or not thread.IsValid():
            return []

        history = []
        try:
            history_threads = thread.GetProcess().GetHistoryThreads(thread.GetStopReasonDataAtIndex(0))
            for i in range(history_threads.GetSize()):
                hist_thread = history_threads.GetThreadAtIndex(i)
                history.append({"thread_id": hist_thread.GetThreadID(), "frames": self._get_thread_frames(hist_thread)})
        except:
            pass
        return history

    def _get_thread_frames(self, thread) -> List[Dict[str, Any]]:
        frames = []
        for i in range(thread.GetNumFrames()):
            frame = thread.GetFrameAtIndex(i)
            frames.append(
                {"function": frame.GetFunctionName(), "pc": frame.GetPC(), "line_entry": str(frame.GetLineEntry())}
            )
        return frames

    def _get_extended_backtrace_types(self, thread) -> List[str]:
        if not thread or not thread.IsValid():
            return []

        types = []
        try:
            for i in range(thread.GetProcess().GetNumExtendedBacktraceTypes()):
                types.append(thread.GetProcess().GetExtendedBacktraceTypeAtIndex(i))
        except:
            pass
        return types

    def _get_register_values(self, frame) -> Dict[str, Any]:
        registers = {}
        if not frame or not frame.IsValid():
            return registers

        reg_set = frame.GetRegisters()
        for regs in reg_set:
            for reg in regs:
                registers[reg.GetName()] = {
                    "value": reg.GetValue(),
                    "type": reg.GetTypeName(),
                    "size": reg.GetByteSize(),
                }
        return registers

    def _get_local_variables(self, frame) -> Dict[str, Any]:
        variables = {}
        if not frame or not frame.IsValid():
            return variables

        values = frame.GetVariables(True, True, True, True)
        for val in values:
            variables[val.GetName()] = self._get_structured_data(val)
        return variables

    def _get_memory_regions(self, process) -> Dict[str, Any]:
        regions = {}
        if not process or not process.IsValid():
            return regions

        region_list = process.GetMemoryRegions()
        for i in range(region_list.GetSize()):
            region = lldb.SBMemoryRegionInfo()
            if region_list.GetMemoryRegionAtIndex(i, region):
                regions[f"region_{i}"] = {
                    "start": region.GetRegionBase(),
                    "end": region.GetRegionEnd(),
                    "size": region.GetRegionEnd() - region.GetRegionBase(),
                    "permissions": {
                        "readable": region.IsReadable(),
                        "writable": region.IsWritable(),
                        "executable": region.IsExecutable(),
                    },
                    "mapped": region.IsMapped(),
                    "name": region.GetName() or "",
                    "page_size": region.GetPageSize(),
                }
        return regions

    def _get_structured_data(self, var, depth=0) -> Any:
        if depth > 3:
            return str(var)

        if not var.IsValid():
            return None

        if var.GetType().IsPointerType():
            return {
                "type": "pointer",
                "value": var.GetValue(),
                "dereferenced": self._get_structured_data(var.Dereference(), depth + 1)
                if var.Dereference().IsValid()
                else None,
            }
        elif var.GetType().IsAggregateType():
            children = {}
            for child in getattr(var, "GetChildren", []):
                children[child.GetName()] = self._get_structured_data(child, depth + 1)
            return {"type": var.GetType().GetName(), "value": var.GetValue(), "children": children}
        else:
            return {"type": var.GetType().GetName(), "value": var.GetValue(), "summary": var.GetSummary()}

    def _get_process_context(self, process) -> Dict[str, Any]:
        if not process or not process.IsValid():
            return {
                "thread_count": 0,
                "state": "invalid",
                "pid": 0,
                "total_threads": 0,
                "selected_thread_id": None,
                # "threads": {},
                # 'memory_regions': {},
                "exit_status": None,
                "exit_description": None,
                # "is_alive": False,
                "is_running": False,
                "is_stopped": False,
                "stop_id": 0,
                "unique_id": 0,
                "unix_signals": {},
            }

        thread_info = {}
        for thread in process:
            thread_info[str(thread.GetThreadID())] = self._get_thread_info(thread)

        unix_signals = {}
        try:
            signals = process.GetUnixSignals()
            for i in range(signals.GetNumSignals()):
                sig_name = signals.GetSignalName(i)
                if sig_name:
                    unix_signals[sig_name] = signals.GetSignalInfo(i).should_stop
        except:
            pass

        return ProcessContext(
            thread_count=process.GetNumThreads(),
            state=str(process.GetState()),
            pid=process.GetProcessID(),
            selected_thread_id=process.GetSelectedThread().GetThreadID() if process.GetSelectedThread() else None,
            exit_status=process.GetExitStatus() if process.GetState() == lldb.eStateExited else None,
            exit_description=process.GetExitDescription() if process.GetState() == lldb.eStateExited else None,
            is_running=process.is_running,
            is_stopped=process.is_stopped,
            stop_id=process.GetStopID(),
            unique_id=process.GetUniqueID(),
            total_threads=process.num_threads,
            unix_signals=unix_signals,
        ).to_dict()

    def _get_target_context(self, target) -> Dict[str, Any]:
        if not target or not target.IsValid():
            return {
                "triple": "invalid",
                "byte_order": "invalid",
                "address_byte_size": 0,
                "code_byte_size": 0,
                "data_byte_size": 0,
                "valid": False,
            }

        return TargetContext(
            triple=target.GetTriple(),
            byte_order=str(target.GetByteOrder()),
            address_byte_size=target.GetAddressByteSize(),
            code_byte_size=target.GetCodeByteSize(),
            data_byte_size=target.GetDataByteSize(),
            valid=target.IsValid(),
        ).to_dict()

    def collect_full_context(self, debugger) -> DebugContext:
        target = debugger.GetSelectedTarget()
        process = target.GetProcess()
        thread = process.GetSelectedThread() if process.IsValid() else None

        try:
            from .environment_probe import DebugEnvironment

            env_probe = DebugEnvironment(debugger)
            env_data = {
                "compiler": env_probe.get_compiler_info(),
                # "loaded_images": env_probe.get_loaded_images(),
                "runtime_stats": {
                    "thread_count": process.GetNumThreads(),
                    "state": str(process.GetState()),
                    "pid": process.GetProcessID(),
                    "selected_thread_id": process.GetSelectedThread().GetThreadID()
                    if process.GetSelectedThread()
                    else None,
                },
            }
        except Exception as e:
            env_data = {"error": str(e)}

        return DebugContext(
            thread=ThreadContext(**self._get_thread_info(thread)),
            process=ProcessContext(**self._get_process_context(process)),
            target=TargetContext(**self._get_target_context(target)),
            environment=env_data,
        )
