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
        # 验证断点位置信息
        if not self.entry_point_breakpoint_event.is_set() and self.tracer.breakpoint.GetID() == bp_loc:
            self.tracer.main_thread_id = frame.thread.id
            self.logger.info(
                "Hit entry point breakpoint at %s, thread_id %d", frame.GetFunctionName(), self.tracer.main_thread_id
            )
            if not self.entry_point_breakpoint_event.is_set():
                self.entry_point_breakpoint_event.set()
                self.tracer.step_handler.base_frame_count = frame.thread.GetNumFrames()
                self.tracer.modules._build_skip_modules_ranges()
                if self.tracer.config_manager.config.get("dump_modules_for_skip"):
                    self.tracer.modules.dump_modules_for_skip()
                    sys.exit(0)
                if self.tracer.config_manager.config.get("dump_source_files_for_skip"):
                    self.tracer.source_ranges.dump_source_files_for_skip()
                    sys.exit(0)
                frame.thread.StepInstruction(False)
                return
        if self.entry_point_breakpoint_event.is_set():
            frame.thread.process.Continue()
            return
        file_spec = frame.GetLineEntry().GetFileSpec()
        line = frame.GetLineEntry().GetLine()
        self.logger.info("Break at %s:%d pc:0x%x", file_spec.fullpath, line, frame.GetPC())
        thread = frame.GetThread()
        thread.StepInstruction(False)
