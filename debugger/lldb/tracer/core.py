import bisect
import fnmatch
import os
import re
import sys
import threading
import time
from functools import lru_cache

import lldb
from ai import set_entrypoint_breakpoints
from op_parser import OperandType, parse_operands
from rich.color import Color
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .breakpoints import entry_point_breakpoint_event
from .config import ConfigManager
from .events import StepAction, handle_special_stop
from .logging import LogManager
from .symbols import symbol_renderer
from .utils import get_stop_reason_str


class Tracer:
    _max_cached_files = 10

    @lru_cache(maxsize=_max_cached_files)
    def _get_file_lines(self, filepath):
        try:
            with open(filepath, "rb") as f:
                content = f.read()
                return content.decode("utf-8").splitlines()
        except (FileNotFoundError, PermissionError) as e:
            self.logger.error("Error reading file %s: %s", filepath, str(e))
            return None
        except (UnicodeDecodeError, IOError) as e:
            self.logger.error("Unexpected error reading file %s: %s", filepath, str(e))
            return None

    def __init__(self, **kwargs):
        self.program_path = kwargs.get("program_path")
        self.program_args = kwargs.get("program_args")
        logfile = kwargs.get("logfile")
        config_file = kwargs.get("config_file")

        self.log_manager = LogManager(None, logfile)
        self.logger = self.log_manager.logger
        self.config_manager = ConfigManager(config_file, self.logger)
        self.log_manager.config = self.config_manager.config
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.Initialize()
        self.debugger.SetAsync(True)
        self.debugger.SetInternalVariable(
            "target.process.extra-startup-command", "QSetLogging:bitmask=LOG_ALL", self.logger.name
        )
        self.listener = lldb.SBListener("TracerListener")
        self.listener.StartListeningForEventClass(
            self.debugger,
            lldb.SBProcess.GetBroadcasterClassName(),
            lldb.SBProcess.eBroadcastBitStateChanged,
        )
        self.breakpoint = None
        self._target = None
        self.process = None

        # 初始化模块相关属性
        self._module_ranges = {}
        self._skip_ranges = []
        self._skip_addresses = []
        self._sorted_ranges = []
        self._sorted_addresses = []
        self._last_source_key = None

        # 初始化符号缓存
        self._symbol_cache = {}
        self._module_cache = {}
        self._section_cache = {}

        # 初始化配置相关属性
        self._skip_modules = self.config_manager.config.get("skip_modules", [])
        self._log_target_info = self.config_manager.config.get("log_target_info", False)
        self._log_module_info = self.config_manager.config.get("log_module_info", False)
        self._log_breakpoint_details = self.config_manager.config.get("log_breakpoint_details", False)

    def symbols_html_renderer(self, symbols) -> str:
        return symbol_renderer(symbols)

    def symbols(self):
        if not self._target or not self._target.IsValid():
            self.logger.error("No valid target")
            return {}

        result = {}
        for module in self._target.module_iter():
            module_name = module.GetFileSpec().GetFilename()
            module_info = {
                "file": module.GetFileSpec().fullpath,
                "platform_file": module.GetPlatformFileSpec().fullpath if module.GetPlatformFileSpec() else None,
                "uuid": module.GetUUIDString(),
                "triple": module.GetTriple(),
                "num_sections": module.GetNumSections(),
                "num_symbols": module.GetNumSymbols(),
            }
            module_info["symbol_details"] = []
            for i in range(module.GetNumSymbols()):
                symbol = module.GetSymbolAtIndex(i)
                symbol_info = {
                    "name": symbol.GetName(),
                    "type": str(symbol.GetType()),
                    "start_addr": hex(symbol.GetStartAddress().GetFileAddress()),
                    "end_addr": (
                        hex(symbol.GetEndAddress().GetFileAddress()) if symbol.GetEndAddress().IsValid() else None
                    ),
                }
                context = symbol.GetStartAddress().GetSymbolContext(lldb.eSymbolContextLineEntry)
                if context.line_entry.IsValid():
                    line_entry = context.line_entry
                    symbol_info["source"] = {
                        "file": line_entry.GetFileSpec().fullpath,
                        "line": line_entry.GetLine(),
                        "column": line_entry.GetColumn(),
                    }
                module_info["symbol_details"].append(symbol_info)
            result[module_name] = module_info
        return result

    def cleanup(self):
        if self.debugger:
            self.debugger.Terminate()

    def continue_to_main(self):
        while not entry_point_breakpoint_event.is_set():
            print("Waiting for entry point breakpoint to be hit...")
            self.process.Continue()
            time.sleep(0.1)

    def start(self):
        if not self.program_path:
            self.logger.error("No program path specified")
            return False

        self._target = self.debugger.CreateTarget(self.program_path)
        if not self._target or not self._target.IsValid():
            self.logger.error("Failed to create valid target for %s", self.program_path)
            return False

        if self.config_manager.config.get("log_target_info"):
            self.log_manager.log_target_info(self._target)

        symbols = self.symbols()
        html_content = self.symbols_html_renderer(symbols)
        output_path = os.path.join(os.path.dirname(self.program_path), "symbols.html")
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            self.logger.info("Saved symbol information to %s", output_path)
        except (IOError, OSError) as e:
            self.logger.error("Failed to save symbol information: %s", str(e))

        self.install(self._target)
        error = lldb.SBError()
        self.process = self._target.Launch(
            self.listener, self.program_args, None, None, None, None, os.getcwd(), 0, True, error
        )
        if not self.process:
            self.logger.error("Failed to launch process")
            return False
        assert self.process.GetState() == lldb.eStateStopped
        threading.Thread(target=self.continue_to_main, daemon=True).start()
        self._event_loop()
        self.cleanup()
        return True

    def dump_modules_for_skip(self):
        """Dump模块信息并生成skip modules配置(反转逻辑:用户选择保留的模块)"""
        if not self._target or not self._target.IsValid():
            self.logger.error("No valid target to dump modules")
            return

        self.load_modules_addresses()
        console = Console()

        # 获取所有模块并按完整路径排序
        modules = []
        for module in self._target.module_iter():
            file_spec = module.GetFileSpec()
            full_path = file_spec.fullpath
            modules.append((full_path, module))

        # 按完整路径排序
        modules.sort(key=lambda x: x[0].lower())

        # 显示所有模块
        table = Table(show_header=True, header_style="bold magenta", title="[bold]Available Modules[/bold]")
        table.add_column("Index", style="cyan")
        table.add_column("Module Name", style="green")
        table.add_column("Full Path", style="dim")

        for idx, (full_path, module) in enumerate(modules):
            filename = module.GetFileSpec().GetFilename()
            table.add_row(
                str(idx),
                Text(filename, style="bold green"),
                Text(full_path, style="dim"),
            )

        console.print(Panel.fit(table, title="[bold]Select Modules to KEEP[/bold]", border_style="blue"))

        # 获取用户选择
        selected = Prompt.ask("Enter module indexes to KEEP (comma separated, empty to skip all)", default="")

        if not selected:
            # 如果用户没有选择任何模块，则跳过所有模块
            skip_modules = [module.GetFileSpec().GetFilename() for _, module in modules]
        else:
            try:
                indexes = [int(i.strip()) for i in selected.split(",")]
                keep_modules = [modules[i][1].GetFileSpec().GetFilename() for i in indexes if 0 <= i < len(modules)]
                # 反转逻辑：用户选择的是要保留的，其余都跳过
                skip_modules = [
                    module.GetFileSpec().GetFilename()
                    for _, module in modules
                    if module.GetFileSpec().GetFilename() not in keep_modules
                ]
            except ValueError:
                self.logger.error("Invalid input format")
                return

        if skip_modules:
            self.config_manager.save_skip_modules(skip_modules)
            console.print(f"[green]Saved skip modules (all except kept): {', '.join(skip_modules)}[/green]")
        else:
            console.print("[yellow]No modules will be skipped[/yellow]")

    def _event_loop(self):
        event = lldb.SBEvent()
        while True:
            ok = self.listener.WaitForEvent(1, event)
            if ok:
                process = lldb.SBProcess.GetProcessFromEvent(event)
                if process and process.IsValid():
                    self._handle_process_event(process)

    def _handle_process_event(self, process):
        state = process.GetState()

        if state == lldb.eStateStopped:
            thread = process.GetSelectedThread()
            stop_reason = thread.GetStopReason()

            if stop_reason == lldb.eStopReasonBreakpoint:
                bp_id = thread.GetStopReasonDataAtIndex(0)
                bp_loc_id = thread.GetStopReasonDataAtIndex(1)
                self.logger.info("Breakpoint ID: %d, Location: %d", bp_id, bp_loc_id)
                frame = thread.GetFrameAtIndex(0)
                self._on_breakpoint_hit(frame, bp_id)
            elif stop_reason == lldb.eStopReasonPlanComplete:
                if entry_point_breakpoint_event.is_set():
                    frame = thread.GetFrameAtIndex(0)
                    ret = self.on_step_hit(frame)
                    if ret == StepAction.STEP_OVER:
                        self.logger.info("Step over detected")
                        thread.StepInstruction(True)
                    elif ret == StepAction.STEP_IN:
                        thread.StepInstruction(False)
            elif stop_reason == lldb.eStopReasonTrace:
                self.logger.info("hit trace, continue execution")
                self.process.Continue()
            else:
                handle_special_stop(thread, stop_reason, self.logger, self._target)

        elif state in (lldb.eStateExited, lldb.eStateCrashed, lldb.eStateDetached):
            if state == lldb.eStateExited:
                exit_status = process.GetExitStatus()
                self.logger.info("Process exited with status: %d", exit_status)
            elif state == lldb.eStateCrashed:
                self.logger.error("Process crashed")
            elif state == lldb.eStateDetached:
                self.logger.info("Process detached")
            return

    def _build_skip_modules_ranges(self):
        """Build address ranges for modules that should be skipped with colored UI output."""
        self.load_modules_addresses()  # 确保模块地址已加载

        self._skip_ranges = []
        if not self._skip_modules:
            return

        console = Console()
        skipped_modules = set()

        # 创建表格显示被跳过的模块
        skip_table = Table(show_header=True, header_style="bold red", title="[bold]Skipped Modules[/bold]")
        skip_table.add_column("Module Name", style="cyan")
        skip_table.add_column("Pattern Match", style="magenta")
        skip_table.add_column("Sections", justify="right")

        for module_name, module_info in self._module_ranges.items():
            matched_patterns = []
            basename = os.path.basename(module_name)

            # 检查完整路径和basename是否匹配任何skip模式
            for pattern in self._skip_modules:
                if fnmatch.fnmatch(module_name, pattern) or fnmatch.fnmatch(basename, pattern):
                    matched_patterns.append(pattern)

            if not matched_patterns:
                continue

            skipped_modules.add(module_name)
            section_count = 0

            for section_info in module_info["sections"]:
                self._skip_ranges.append(
                    {
                        "module": module_info["module"],
                        "section": section_info["section"],
                        "start_addr": section_info["start_addr"],
                        "end_addr": section_info["end_addr"],
                    }
                )
                section_count += 1

            # 为每个被跳过的模块添加一行表格数据
            skip_table.add_row(
                Text(module_name, style="bold green"),
                Text("\n".join(matched_patterns), style="yellow"),
                Text(str(section_count), style="bold blue"),
            )

        # 显示被跳过的模块信息
        if skipped_modules:
            console.print(
                Panel.fit(
                    skip_table,
                    title="[bold yellow]Skipped Modules Configuration[/bold yellow]",
                    border_style="blue",
                    padding=(1, 2),
                )
            )

            # 显示详细的地址范围信息
            range_table = Table(
                show_header=True, header_style="bold magenta", title="[bold]Skipped Address Ranges[/bold]"
            )
            range_table.add_column("Module", style="cyan")
            range_table.add_column("Section", style="green")
            range_table.add_column("Address Range", justify="right")
            range_table.add_column("Size", justify="right")

            for range_info in self._skip_ranges:
                module_name = range_info["module"].GetFileSpec().GetFilename()
                section_name = range_info["section"].GetName()
                start = range_info["start_addr"]
                end = range_info["end_addr"]
                size = end - start

                # 格式化地址范围显示
                range_text = Text()
                range_text.append(f"0x{start:016x}", style="bright_cyan")
                range_text.append(" → ", style="dim")
                range_text.append(f"0x{end:016x}", style="bright_green")

                range_table.add_row(
                    Text(module_name), Text(section_name), range_text, Text(f"{size:,} bytes", style="bright_blue")
                )

            console.print(
                Panel.fit(range_table, title="[bold]Skipped Memory Ranges[/bold]", border_style="green", padding=(1, 2))
            )
        else:
            console.print("[bold yellow]No modules matched skip patterns[/bold yellow]")

        # Sort ranges by start address for bisect
        self._skip_ranges.sort(key=lambda x: x["start_addr"])
        self._skip_addresses = [x["start_addr"] for x in self._skip_ranges]

    def _should_skip_address(self, address):
        """Check if address is in any skip module range."""
        if not self._skip_ranges:
            return False

        idx = bisect.bisect_right(self._skip_addresses, address) - 1
        if 0 <= idx < len(self._skip_ranges):
            range_info = self._skip_ranges[idx]
            if range_info["start_addr"] <= address < range_info["end_addr"]:
                offset = address - range_info["start_addr"]
                self.logger.info(
                    "Step over addr 0x%x at module %s section %s offset 0x%x",
                    address,
                    range_info["module"].GetFileSpec().GetFilename(),
                    range_info["section"].GetName(),
                    offset,
                )
                return True
        return False

    def on_step_hit(self, frame):
        """Handle step events with detailed debug information."""
        pc = frame.GetPCAddress().GetLoadAddress(self._target)
        insts = self._target.ReadInstructions(frame.addr, 1)
        if insts.GetSize() == 0:
            self.logger.warning("No instructions found at PC: 0x%x", pc)
            return StepAction.CONTINUE

        inst = insts.GetInstructionAtIndex(0)
        if not inst.IsValid():
            self.logger.warning("Invalid instruction at PC: 0x%x", pc)
            return StepAction.CONTINUE

        mnemonic = inst.GetMnemonic(self._target)
        operands = inst.GetOperands(self._target)
        function = frame.symbol.name
        line_entry = frame.GetLineEntry()
        source_info = ""
        source_line = ""

        if line_entry.IsValid():
            filepath = line_entry.GetFileSpec().fullpath
            dirname, basename = os.path.split(filepath)
            parent_dir = os.path.basename(dirname)
            short_path = os.path.join(parent_dir, basename)
            line_num = line_entry.GetLine()
            source_info = f"{short_path}:{line_num}"
            if lines := self._get_file_lines(filepath):
                if 0 < line_num <= len(lines):
                    source_line = lines[line_num - 1].strip()

        current_source_key = f"{source_info};{source_line}"
        if hasattr(self, "_last_source_key") and current_source_key == self._last_source_key:
            source_info = ""
            source_line = ""
        self._last_source_key = current_source_key

        parsed_oprands = parse_operands(operands, max_ops=4)
        if mnemonic.startswith("b"):
            self.logger.info("Branch instruction detected: %s", mnemonic)

        if mnemonic in ("br", "braa", "brab", "blraa"):
            if parsed_oprands[0].type == OperandType.REGISTER:
                jump_to = frame.register[parsed_oprands[0].value]
                addr = self._target.ResolveLoadAddress(jump_to.unsigned)
                if self._should_skip_address(jump_to.unsigned):
                    self.logger.info("%s Skipping jump to register value: %s", mnemonic, addr.symbol.name)
                    return StepAction.STEP_OVER
                self.logger.info("%s Jumping to register value: %s", mnemonic, addr)
        elif mnemonic == "b":
            self.logger.info("%s Branching to address: %s", mnemonic, parsed_oprands[0].value)
        elif mnemonic == "bl":
            target_addr = parsed_oprands[0].value
            raw_target_addr = int(target_addr, 16)
            if self._should_skip_address(raw_target_addr):
                addr = self._target.ResolveLoadAddress(raw_target_addr)
                self.logger.info("%s Skipping branch to address: %s, %s", mnemonic, target_addr, addr.symbol.name)
                return StepAction.STEP_OVER
            self.logger.info(
                "%s Branching to address: %s, %s",
                mnemonic,
                target_addr,
                self._target.ResolveLoadAddress(int(target_addr, 16)).symbol.name,
            )
        elif mnemonic == "ret":
            self.logger.info("Returning from function: %s", function)

        if source_line:
            self.logger.info("0x%x %s %s ; %s // %s", pc, mnemonic, operands, source_info, source_line)
        else:
            self.logger.info("0x%x %s %s ; %s", pc, mnemonic, operands, source_info)

        return StepAction.STEP_IN

    def _on_breakpoint_hit(self, frame, bp_loc):
        # 验证断点位置信息
        if self.breakpoint.GetID() == bp_loc:
            self.logger.info("Hit entry point breakpoint at %s", frame.GetFunctionName())
            if not entry_point_breakpoint_event.is_set():
                entry_point_breakpoint_event.set()
                self._build_skip_modules_ranges()
                if self.config_manager.config.get("dump_modules_for_skip"):
                    self.dump_modules_for_skip()
                    sys.exit(0)
        file_spec = frame.GetLineEntry().GetFileSpec()
        line = frame.GetLineEntry().GetLine()
        self.logger.info("Break at %s:%d", file_spec.fullpath, line)
        thread = frame.GetThread()
        thread.StepInstruction(False)

    def load_modules_addresses(self):
        """Load and cache all module address ranges for quick lookup."""
        if not self._target or not self._target.IsValid():
            self.logger.error("No valid target to load modules")
            return

        if not hasattr(self, "_module_ranges"):
            self._module_ranges = {}

        for module in self._target.module_iter():
            module_info = {"module": module, "sections": []}

            for section in module.section_iter():
                load_addr = section.GetLoadAddress(self._target)
                if load_addr != lldb.LLDB_INVALID_ADDRESS:
                    start_addr = load_addr
                    end_addr = start_addr + section.GetByteSize()
                    section_info = {
                        "section": section,
                        "name": section.GetName(),
                        "start_addr": start_addr,
                        "end_addr": end_addr,
                        "size": section.GetByteSize(),
                    }
                    module_info["sections"].append(section_info)

            self._module_ranges[module.GetFileSpec().GetFilename()] = module_info
        self.logger.debug("Loaded module address ranges for %d modules", len(self._module_ranges))

    def dump_modules_info(self):
        """Display module information with colored UI including sections and address ranges."""
        if not self._target or not self._target.IsValid():
            self.logger.error("No valid target to dump modules")
            return

        console = Console()
        if not hasattr(self, "_module_ranges"):
            self.load_modules_addresses()

        section_colors = {
            "__text": Color.from_rgb(100, 200, 100),
            "__data": Color.from_rgb(200, 100, 100),
            "__bss": Color.from_rgb(150, 150, 200),
            "__const": Color.from_rgb(200, 200, 100),
            "__cstring": Color.from_rgb(200, 150, 200),
        }

        for module_info in self._module_ranges.values():
            module_table = Table(show_header=True, header_style="bold magenta", box=None)
            module_table.add_column("Section", style="bold")
            module_table.add_column("Address Range", justify="right")
            module_table.add_column("Size", justify="right")

            total_size = 0
            for section_info in module_info["sections"]:
                section_name = section_info["name"]
                start_addr = section_info["start_addr"]
                end_addr = section_info["end_addr"]
                size = section_info["size"]
                total_size += size

                base_color = section_colors.get(section_name.split(".")[0], Color.from_rgb(180, 180, 180))
                section_style = Style(color=base_color)

                range_text = Text()
                range_text.append(f"0x{start_addr:016x}", style=Style(color=Color.from_rgb(100, 200, 200)))
                range_text.append(" → ", style="dim")
                range_text.append(f"0x{end_addr:016x}", style=Style(color=Color.from_rgb(200, 150, 100)))

                module_table.add_row(
                    Text(section_name, style=section_style),
                    range_text,
                    Text(f"{size} bytes", style="dim"),
                )

            summary_text = Text()
            summary_text.append(f"Total sections: {len(module_info['sections'])}", style="bold")
            summary_text.append(" | ", style="dim")
            summary_text.append(f"Total size: {total_size} bytes", style="bold")

            console.print(
                Panel.fit(
                    module_table,
                    title=f"[bold cyan]{module_info['module'].GetFileSpec().GetFilename()}[/bold cyan]",
                    border_style="blue",
                    padding=(0, 1),
                )
            )
            console.print()

    def find_module_by_address(self, address):
        """Find module and section containing the given address using bisect for O(log n) lookup."""
        if not self._sorted_ranges:
            self._build_sorted_ranges()

        if isinstance(address, str):
            try:
                address = int(address, 16)
            except ValueError:
                self.logger.error("Invalid address format: %s", address)
                return None, None, None

        idx = bisect.bisect_right(self._sorted_addresses, address) - 1
        if 0 <= idx < len(self._sorted_ranges):
            range_info = self._sorted_ranges[idx]
            if range_info["start_addr"] <= address < range_info["end_addr"]:
                offset = address - range_info["start_addr"]
                return (range_info["module"], range_info["section"], offset)

        self.logger.debug("Address 0x%x not found in any module", address)
        return None, None, None

    def _build_sorted_ranges(self):
        """Build sorted list of address ranges for binary search."""
        if not hasattr(self, "_module_ranges"):
            self.load_modules_addresses()

        self._sorted_ranges = []
        for module_name, module_info in self._module_ranges.items():
            for section_info in module_info["sections"]:
                self._sorted_ranges.append(
                    {
                        "module": module_info["module"],
                        "section": section_info["section"],
                        "start_addr": section_info["start_addr"],
                        "end_addr": section_info["end_addr"],
                    }
                )

        # Sort ranges by start address
        self._sorted_ranges.sort(key=lambda x: x["start_addr"])
        self._sorted_addresses = [x["start_addr"] for x in self._sorted_ranges]

    def _capture_arguments(self, frame):
        return {
            var.GetName(): var.GetValue()
            for var in frame.GetVariables(True, True, True, True)
            if var.GetName().startswith("arg[") or var.GetName() in frame.GetFunction().GetArgumentNames()
        }

    def _capture_frame_locals(self, frame):
        return {var.GetName(): var.GetValue() for var in frame.get_locals()}

    def _capture_return_value(self, frame):
        lang = self._target.GetLanguage()
        arch = self._target.GetTriple().split("-")[0]
        expr_map = {
            (lldb.eLanguageTypeC_plus_plus, "x86_64"): "$rax",
            (lldb.eLanguageTypeC_plus_plus, "aarch64"): "$x0",
            (lldb.eLanguageTypeGo, ""): "$r1",
        }
        return self._eval_expression(frame, expr_map.get((lang, arch), "$r0"))

    def _parse_trace_comment(self, frame):
        line_entry = frame.GetLineEntry()
        filepath = line_entry.GetFileSpec().fullpath
        line_num = line_entry.GetLine()

        if lines := self._get_file_lines(filepath):
            if line_num <= len(lines):
                source_line = lines[line_num - 1].strip()
                lang_patterns = {
                    lldb.eLanguageTypePython: r"#\s*trace\s+(.*)",
                    lldb.eLanguageTypeGo: r"//\s*trace\s+(.*)",
                    lldb.eLanguageTypeC: r"//\s*trace\s+(.*)",
                    lldb.eLanguageTypeC_plus_plus: r"//\s*trace\s+(.*)",
                    lldb.eLanguageTypeRust: r"///\s*trace\s+(.*)",
                    lldb.eLanguageTypeObjC: r"//\s*trace\s+(.*)",
                }
                if pattern := lang_patterns.get(frame.GuessLanguage()):
                    if match := re.search(pattern, source_line):
                        return match.group(1).strip()
        return None

    def _eval_expression(self, frame, expr):
        options = lldb.SBExpressionOptions()
        options.SetFetchDynamicValue(lldb.eDynamicCanRunTarget)
        options.SetUnwindOnError(True)
        result = frame.EvaluateExpression(expr, options)
        if result.GetError().Fail():
            self.logger.error("Evaluation failed for %s: %s", expr, result.GetError())
        return result.GetValue() if result.IsValid() else "<error>"

    def install(self, target):
        self._target = target
        bps = set_entrypoint_breakpoints(self.debugger)
        self.debugger.HandleCommand("command script import --allow-reload ./tracer.py")
        if len(bps) > 1:
            print("found entry, only use first one", ",".join([f"{name} (ID: {bp.GetID()})" for name, bp in bps]))
        name, bp = bps[0]
        # bp.SetScriptCallbackFunction("tracer.breakpoint_function_wrapper")
        bp.SetOneShot(True)
        symbol_context_list = target.FindFunctions(name)
        for symbol_context in symbol_context_list:
            symbol = symbol_context.GetSymbol()
            module = symbol_context.GetModule()
            function = symbol_context.GetFunction()
            self.logger.info("Setting breakpoint at function: %s in module: %s in symbol: %s", function, module, symbol)
        self.breakpoint = bp
        if self.config_manager.config.get("log_breakpoint_details"):
            self.log_manager.log_breakpoint_info(self.breakpoint)
