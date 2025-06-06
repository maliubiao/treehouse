import sys

import lldb


class BreakpointHandler:
    def __init__(self, tracer):
        self.tracer = tracer
        self.logger = tracer.logger
        self.entry_point_breakpoint_event = tracer.entry_point_breakpoint_event

    def handle_breakpoint(self, frame, bp_loc):
        # 验证断点位置信息
        if self.tracer.breakpoint.GetID() == bp_loc:
            self.logger.info("Hit entry point breakpoint at %s", frame.GetFunctionName())
            if not self.entry_point_breakpoint_event.is_set():
                self.entry_point_breakpoint_event.set()
                self.tracer.modules._build_skip_modules_ranges()
                if self.tracer.config_manager.config.get("dump_modules_for_skip"):
                    self.tracer.modules.dump_modules_for_skip()
                    sys.exit(0)
                if self.tracer.config_manager.config.get("dump_source_files_for_skip"):
                    self.tracer.source_ranges.dump_source_files_for_skip()
                    sys.exit(0)

        file_spec = frame.GetLineEntry().GetFileSpec()
        line = frame.GetLineEntry().GetLine()
        self.logger.info("Break at %s:%d", file_spec.fullpath, line)
        thread = frame.GetThread()
        thread.StepInstruction(False)
