import sys
from typing import TYPE_CHECKING

import lldb

if TYPE_CHECKING:
    from .core import Tracer  # Avoid circular import issues


class BreakpointHandler:
    def __init__(self, tracer: "Tracer"):
        self.tracer = tracer
        self.logger = tracer.logger
        self.entry_point_breakpoint_event = tracer.entry_point_breakpoint_event

    def handle_breakpoint(self, frame: lldb.SBFrame, bp_loc):
        # 如果已经设置了入口断点事件，则继续进程
        if self.entry_point_breakpoint_event.is_set():
            frame.thread.process.Continue()
            return

        # 处理其他断点（在入口断点设置之前）
        file_spec = frame.GetLineEntry().GetFileSpec()
        line = frame.GetLineEntry().GetLine()
        self.logger.info("Break at %s:%d pc:0x%x", file_spec.fullpath, line, frame.GetPC())
        thread = frame.GetThread()
        thread.StepInstruction(False)
