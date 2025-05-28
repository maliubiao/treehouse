import argparse
import bisect
import fnmatch
import json
import logging
import os
import re
import sys
import threading
import time
from enum import Enum, auto
from functools import lru_cache

import lldb
from ai import set_entrypoint_breakpoints
from op_parser import OperandType, parse_disassembly, parse_operands
from rich.color import Color
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.style import Style
from rich.table import Table
from rich.text import Text


def symbol_renderer(symbols):
    """
    Render symbols data as an interactive HTML page with sorting and filtering capabilities.
    Returns a Flask response with the HTML content.
    """
    if not symbols:
        return "<div>No symbols data available</div>"

    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Symbols Viewer</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.datatables.net/1.13.5/css/dataTables.bootstrap5.min.css" rel="stylesheet">
    <style>
        .symbol-table { font-family: monospace; font-size: 0.9em; }
        .module-header { background-color: #f8f9fa; cursor: pointer; }
        .symbol-details { display: none; }
        .address { color: #6c757d; }
        .source-info { color: #0d6efd; }
        .symbol-content {
            font-family: monospace;
            white-space: pre;
            background-color: #f8f9fa;
            padding: 10px;
            border-radius: 5px;
        }
        .dataTables_wrapper .dataTables_paginate .paginate_button { padding: 0.3em 0.8em; }
    </style>
</head>
<body>
    <div class="container-fluid mt-3">
        <h3>Symbols Viewer</h3>
        <div class="mb-3">
            <input type="text" id="globalSearch" class="form-control" placeholder="Search all symbols...">
        </div>
        <div class="accordion" id="modulesAccordion">
"""

    for module_name, module_data in symbols.items():
        has_symbol_details = "symbol_details" in module_data and module_data["symbol_details"]
        symbol_count = len(module_data["symbol_details"]) if has_symbol_details else 0

        if not has_symbol_details:
            continue

        html += f"""
            <div class="accordion-item">
                <h2 class="accordion-header" id="heading{module_name}">
                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse"
                            data-bs-target="#collapse{module_name}" aria-expanded="false"
                            aria-controls="collapse{module_name}">
                        {module_name} (Symbols: {symbol_count})
                    </button>
                </h2>
                <div id="collapse{module_name}" class="accordion-collapse collapse"
                    aria-labelledby="heading{module_name}" data-bs-parent="#modulesAccordion">
                    <div class="accordion-body">
                        <table class="table table-sm table-hover symbol-table" id="table{module_name}">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Type</th>
                                    <th>Address Range</th>
                                    <th>Source Location</th>
                                </tr>
                            </thead>
                            <tbody>
        """

        for symbol in module_data["symbol_details"]:
            source_info = ""
            if "source" in symbol:
                source_info = f"{symbol['source']['file']}:{symbol['source']['line']}"

            html += f"""
                                <tr>
                                    <td>{symbol["name"]}</td>
                                    <td>{symbol["type"]}</td>
                                    <td class="address">
                                        {symbol["start_addr"]}
                                        {f"→ {symbol['end_addr']}" if symbol["end_addr"] else ""}
                                    </td>
                                    <td class="source-info">{source_info}</td>
                                </tr>
            """

        html += """
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        """

    html += """
        </div>
    </div>

    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.5/js/jquery.dataTables.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.5/js/dataTables.bootstrap5.min.js"></script>
    <script>
        $(document).ready(function() {
            // Initialize DataTables for each module table with enhanced options
            $('.symbol-table').each(function() {
                $(this).DataTable({
                    pageLength: 20,
                    lengthMenu: [10, 20, 50, 100, 200],
                    searching: true,
                    stateSave: true,
                    deferRender: true,
                    processing: true,
                    responsive: true,
                    dom: '<"top"lf>rt<"bottom"ip>',
                    language: {
                        search: "_INPUT_",
                        searchPlaceholder: "Search symbols...",
                        lengthMenu: "Show _MENU_ symbols per page",
                        info: "Showing _START_ to _END_ of _TOTAL_ symbols",
                        infoEmpty: "No symbols available",
                        infoFiltered: "(filtered from _MAX_ total symbols)"
                    },
                    columnDefs: [
                        { targets: [0,1,2,3], orderable: true },
                        { targets: '_all', orderable: false }
                    ]
                });
            });

            // Global search across all tables
            $('#globalSearch').on('keyup', function() {
                const searchTerm = this.value.toLowerCase();
                $('.symbol-table tbody tr').each(function() {
                    const rowText = $(this).text().toLowerCase();
                    $(this).toggle(rowText.includes(searchTerm));
                });
            });
        });
    </script>
</body>
</html>
"""
    return html


class ConfigManager:
    def __init__(self, config_file=None, logger=None):
        self.logger = logger
        self.config = {
            "max_steps": 100,
            "enable_jit": False,
            "log_target_info": True,
            "log_module_info": True,
            "log_breakpoint_details": True,
            "skip_modules": [],
            "dump_modules_for_skip": False,
        }
        self.config_file = config_file
        if config_file:
            self._load_config(config_file)
            self.config_watcher = threading.Thread(target=self._watch_config, daemon=True)
            self.config_watcher.start()
        else:
            self.config_file = "tracer_config.yaml"  # 改为yaml后缀

    def _load_config(self, filepath):
        try:
            import yaml  # 新增yaml导入

            with open(filepath, encoding="utf-8") as f:
                config = yaml.safe_load(f)  # 使用yaml加载
                self.config.update(config)
                self.logger.info(f"Loaded config from {filepath}: {config}")
        except (yaml.YAMLError, OSError) as e:  # 改为捕获YAMLError
            self.logger.error(f"Error loading config file {filepath}: {str(e)}")

    def _watch_config(self):
        last_mtime = 0
        while True:
            try:
                current_mtime = os.path.getmtime(self.config_file)
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    self._load_config(self.config_file)
                    self.logger.info("Config file reloaded")
            except OSError as e:
                self.logger.error(f"Error watching config file: {str(e)}")
            time.sleep(1)

    def save_skip_modules(self, modules):
        """保存skip modules到配置文件，合并现有配置"""
        if not self.config_file:
            self.logger.warning("No config file specified, skip modules not saved")
            return
        try:
            import yaml

            # 读取现有配置或创建空配置
            config = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}

            # 合并skip_modules列表并去重
            existing_modules = set(config.get("skip_modules", []))
            new_modules = set(modules)
            merged_modules = list(existing_modules.union(new_modules))

            # 更新配置并写入
            config["skip_modules"] = merged_modules
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.dump(config, f, indent=4, sort_keys=False)

            # 更新内存中的配置
            self.config["skip_modules"] = merged_modules
            self.logger.info(
                f"Saved skip modules to {self.config_file} (merged {len(existing_modules)} existing with {len(new_modules)} new)"
            )
        except (yaml.YAMLError, OSError) as e:
            self.logger.error(f"Error saving skip modules: {str(e)}")


class LogManager:
    def __init__(self, config, logfile=None):
        self.config = config
        self.logfile = logfile
        self.logger = logging.getLogger("Tracer")
        self.logger.setLevel(logging.DEBUG)
        self._init_logger()

    def _init_logger(self):
        formatter = logging.Formatter("[%(asctime)s][%(thread)d][%(levelname)s][%(lineno)d] %(message)s")

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        if self.logfile:
            file_handler = logging.FileHandler(self.logfile)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def log_target_info(self, target):
        if not self.config.get("log_target_info"):
            return

        self.logger.debug("Target info:")
        self.logger.debug("  Triple: %s", target.GetTriple())
        self.logger.debug("  Address byte size: %s", target.GetAddressByteSize())
        self.logger.debug("  Byte order: %s", target.GetByteOrder())
        self.logger.debug("  Code byte size: %s", target.GetCodeByteSize())
        self.logger.debug("  Data byte size: %s", target.GetDataByteSize())
        self.logger.debug("  ABI name: %s", target.GetABIName())

        executable = target.GetExecutable()
        if executable:
            self.logger.debug("  Executable: %s", executable.fullpath)

        platform = target.GetPlatform()
        if platform:
            self.logger.debug("  Platform: %s", platform.GetName())

    def log_module_info(self, module):
        if not self.config.get("log_module_info"):
            return

        self.logger.debug("Module info:")
        self.logger.debug("  File: %s", module.GetFileSpec().fullpath)
        self.logger.debug("  UUID: %s", module.GetUUIDString())
        self.logger.debug("  Num symbols: %s", module.GetNumSymbols())
        self.logger.debug("  Num sections: %s", module.GetNumSections())
        self.logger.debug("  Num compile units: %s", module.GetNumCompileUnits())

    def log_breakpoint_info(self, bp):
        if not self.config.get("log_breakpoint_details"):
            return

        self.logger.debug("Breakpoint info:")
        self.logger.debug("  ID: %s", bp.GetID())
        self.logger.debug("  Enabled: %s", bp.IsEnabled())
        self.logger.debug("  One shot: %s", bp.IsOneShot())
        self.logger.debug("  Internal: %s", bp.IsInternal())
        self.logger.debug("  Hardware: %s", bp.IsHardware())
        self.logger.debug("  Condition: %s", bp.GetCondition())
        self.logger.debug("  Hit count: %s", bp.GetHitCount())
        self.logger.debug("  Num locations: %s", bp.GetNumLocations())


def breakpoint_function_wrapper(frame, bp_loc, extra_args, internal_dict):
    """处理LLDB断点事件的包装函数

    Args:
        frame: 当前执行帧对象
        bp_loc: 断点位置对象
        extra_args: 额外参数字典
        internal_dict: 保留参数(LLDB接口要求)
    """
    entry_point_breakpoint_event.set()

    thread = frame.GetThread()
    process = thread.GetProcess()
    target = process.GetTarget()
    debugger = target.GetDebugger()

    # 验证基本对象访问
    print(f"Current function: {frame.GetFunctionName()}")
    print(f"Thread ID: {thread.GetThreadID()}")
    print(f"Process ID: {process.GetProcessID()}")
    print(f"Target: {target.GetExecutable().GetFilename()}")

    # 验证断点位置信息
    print(f"Breakpoint ID: {bp_loc.GetBreakpoint().GetID()}")
    print(f"Breakpoint address: {hex(bp_loc.GetAddress().GetLoadAddress(target))}")

    # 处理extra_args参数
    if extra_args and extra_args.IsValid():
        print("Extra arguments provided:")
        if extra_args.GetValueForKey("key"):
            print(f"Key: {extra_args.GetValueForKey('key').GetStringValue(100)}")
        if extra_args.GetValueForKey("value"):
            print(f"Value: {extra_args.GetValueForKey('value').GetStringValue(100)}")

    # 验证文档中提到的等效访问方式
    print(f"Debugger via frame: {debugger == frame.GetThread().GetProcess().GetTarget().GetDebugger()}")
    # 禁用当前断点位置并继续执行
    thread.StepInstruction(False)

    # 显式标记未使用的参数以避免警告
    _ = internal_dict
    return True


entry_point_breakpoint_event = threading.Event()


class StepAction(Enum):
    """Enumeration for step action decisions"""

    STEP_OVER = auto()
    STEP_IN = auto()
    CONTINUE = auto()


class Tracer:
    _max_cached_files = 10
    _lang_patterns = {
        lldb.eLanguageTypePython: r"#\s*trace\s+(.*)",
        lldb.eLanguageTypeGo: r"//\s*trace\s+(.*)",
        lldb.eLanguageTypeC: r"//\s*trace\s+(.*)",
        lldb.eLanguageTypeC_plus_plus: r"//\s*trace\s+(.*)",
        lldb.eLanguageTypeRust: r"///\s*trace\s+(.*)",
        lldb.eLanguageTypeObjC: r"//\s*trace\s+(.*)",
    }

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

    def _get_stop_reason_str(self, reason):
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

    def _handle_process_event(self, process):
        state = process.GetState()
        state_str = lldb.SBDebugger.StateAsCString(state)

        # Map state values to descriptive strings for better logging
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

        # self.logger.debug("Process state: %s (%s)", state_str, state_map.get(state, "Unknown"))

        if state == lldb.eStateStopped:
            thread = process.GetSelectedThread()
            stop_reason = thread.GetStopReason()
            stop_reason_str = self._get_stop_reason_str(stop_reason)
            # self.logger.info("Thread %d stopped: %s", thread.GetThreadID(), stop_reason_str)

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
                self._handle_special_stop(thread, stop_reason)

        elif state == lldb.eStateExited:
            exit_status = process.GetExitStatus()
            self.logger.info("Process exited with status: %d", exit_status)
            return
        elif state == lldb.eStateCrashed:
            self.logger.error("Process crashed")
            return
        elif state == lldb.eStateDetached:
            self.logger.info("Process detached")
            return
        elif state == lldb.eStateRunning or state == lldb.eStateStepping:
            pass
            # self.logger.debug("Process is running/stepping")

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
        if idx >= 0 and idx < len(self._skip_ranges):
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
        # Get current instruction
        insts = self._target.ReadInstructions(frame.addr, 1)
        if insts.GetSize() == 0:
            self.logger.warning("No instructions found at PC: 0x%x", pc)
            return StepAction.CONTINUE
        inst = insts.GetInstructionAtIndex(0)
        if not inst.IsValid():
            self.logger.warning("Invalid instruction at PC: 0x%x", pc)
            return StepAction.CONTINUE
        # Get instruction details
        mnemonic = inst.GetMnemonic(self._target)
        operands = inst.GetOperands(self._target)
        # Get frame information
        function = frame.symbol.name
        line_entry = frame.GetLineEntry()
        source_info = ""
        source_line = ""
        if line_entry.IsValid():
            filepath = line_entry.GetFileSpec().fullpath
            # 修改这里：只显示basename和它的上级目录
            dirname, basename = os.path.split(filepath)
            parent_dir = os.path.basename(dirname)
            short_path = os.path.join(parent_dir, basename)
            line_num = line_entry.GetLine()
            source_info = "%s:%d" % (short_path, line_num)
            # Get source line from cache
            if lines := self._get_file_lines(filepath):
                if 0 < line_num <= len(lines):
                    source_line = lines[line_num - 1].strip()

        # 添加去重逻辑
        current_source_key = f"{source_info};{source_line}"
        if hasattr(self, "_last_source_key") and current_source_key == self._last_source_key:
            source_info = ""  # 如果与前一个相同，则清空source_info
            source_line = ""  # 清空source_line
        self._last_source_key = current_source_key  # 保存当前key用于下次比较

        parsed_oprands = parse_operands(operands, max_ops=4)
        if mnemonic.startswith("b"):
            self.logger.info("Branch instruction detected: %s", mnemonic)
        if mnemonic == "br" or mnemonic == "br" or mnemonic == "braa" or mnemonic == "brab" or mnemonic == "blraa":
            if parsed_oprands[0].type == OperandType.REGISTER:
                jump_to = frame.register[parsed_oprands[0].value]
                if self._should_skip_address(jump_to.unsigned):
                    self.logger.info("%s Skipping jump to register value: %s", mnemonic, jump_to)
                    return StepAction.STEP_OVER
                self.logger.info("%s Jumping to register value: %s", mnemonic, jump_to)
        elif mnemonic == "b":
            self.logger.info("%s Branching to address: %s", mnemonic, parsed_oprands[0].value)
        elif mnemonic == "bl":
            target_addr = parsed_oprands[0].value
            if self._should_skip_address(int(target_addr, 16)):
                self.logger.info("%s Skipping branch to address: %s", mnemonic, target_addr)
                return StepAction.STEP_OVER
            self.logger.info(
                "%s Branching to address: %s, at module: %s",
                mnemonic,
                target_addr,
                self.find_module_by_address(int(target_addr, 16)),
            )
        elif mnemonic == "ret":
            if parsed_oprands:
                self.logger.info("Returning from function with value: %s", parsed_oprands[0].value)
            else:
                self.logger.info("Returning from function: %s", function)
        # Log detailed step information with source line
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

        # Color palette for different sections
        section_colors = {
            "__text": Color.from_rgb(100, 200, 100),  # Green for code
            "__data": Color.from_rgb(200, 100, 100),  # Red for data
            "__bss": Color.from_rgb(150, 150, 200),  # Blue for bss
            "__const": Color.from_rgb(200, 200, 100),  # Yellow for const
            "__cstring": Color.from_rgb(200, 150, 200),  # Purple for strings
        }

        for module_name, module_info in self._module_ranges.items():
            # Create a panel for each module
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

                # Determine section color
                base_color = section_colors.get(section_name.split(".")[0], Color.from_rgb(180, 180, 180))
                section_style = Style(color=base_color)

                # Format address range with gradient
                range_text = Text()
                range_text.append("0x%016x" % start_addr, style=Style(color=Color.from_rgb(100, 200, 200)))
                range_text.append(" → ", style="dim")
                range_text.append("0x%016x" % end_addr, style=Style(color=Color.from_rgb(200, 150, 100)))

                # Add row to table
                module_table.add_row(
                    Text(section_name, style=section_style),
                    range_text,
                    Text("%d bytes" % size, style="dim"),
                )

            # Create summary text with module info
            summary_text = Text()
            summary_text.append("Total sections: %d" % len(module_info["sections"]), style="bold")
            summary_text.append(" | ", style="dim")
            summary_text.append("Total size: %d bytes" % total_size, style="bold")

            # Display the module panel with module name in the title
            console.print(
                Panel.fit(
                    module_table, title=f"[bold cyan]{module_name}[/bold cyan]", border_style="blue", padding=(0, 1)
                )
            )
            console.print()  # Add spacing between modules

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

        # Binary search in sorted ranges
        idx = bisect.bisect_right(self._sorted_addresses, address) - 1
        if idx >= 0 and idx < len(self._sorted_ranges):
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

    def _handle_special_stop(self, thread, stop_reason):
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
            watchpoint = self._target.FindWatchpointByID(wp_id)
            if watchpoint and watchpoint.IsValid():
                self.logger.info(
                    "Watchpoint %d triggered%s: address=0x%x, size=%d",
                    wp_id,
                    location_info,
                    watchpoint.GetWatchAddress(),
                    watchpoint.GetWatchSize(),
                )

        elif stop_reason == lldb.eStopReasonSignal:
            signal_num = thread.GetStopReasonDataAtIndex(0)
            signal_name = process.GetUnixSignals().GetSignalAsCString(signal_num)
            self.logger.info("Received signal %d (%s)%s", signal_num, signal_name, location_info)

            # For common signals like SIGSEGV, provide more context
            if signal_num == 11:  # SIGSEGV
                self.logger.error("Segmentation fault%s", location_info)
                if frame and frame.IsValid():
                    # Attempt to get more context about the crash
                    self.logger.info("Stack trace at crash point:")
                    for i in range(min(5, thread.GetNumFrames())):
                        f = thread.GetFrameAtIndex(i)
                        self.logger.info(
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
            self.logger.info("Exception occurred%s%s", exc_desc, location_info)

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
                self.logger.info(reason_str + location_info, child_pid)
            elif stop_reason == lldb.eStopReasonThreadExiting:
                self.logger.info(reason_str + location_info, thread.GetThreadID())
            else:
                self.logger.info(reason_str + location_info)

        else:
            self.logger.info("Unhandled stop reason: %s%s", self._get_stop_reason_str(stop_reason), location_info)

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
                if pattern := self._lang_patterns.get(frame.GuessLanguage()):
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


def parse_args():
    parser = argparse.ArgumentParser(description="LLDB Tracer Tool")
    parser.add_argument("-e", "--program-path", required=True, help="Path to the debugged program")
    parser.add_argument("-a", "--program-args", action="append", default=[], help="Program arguments (repeatable)")
    parser.add_argument("-l", "--logfile", help="Path to log output")
    parser.add_argument("-c", "--config-file", help="Path to config file")
    parser.add_argument("--condition", help="Breakpoint condition expression")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "--dump-modules-for-skip", action="store_true", help="Dump module information and generate skip modules config"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    tracer = Tracer(
        program_path=args.program_path,
        program_args=args.program_args,
        logfile=args.logfile,
        config_file=args.config_file,
    )
    if args.verbose:
        tracer.logger.setLevel(logging.DEBUG)
        tracer.config_manager.config.update(
            {
                "log_target_info": True,
                "log_module_info": True,
                "log_breakpoint_details": True,
            }
        )
    if args.dump_modules_for_skip:
        tracer.config_manager.config["dump_modules_for_skip"] = True
    tracer.start()


if __name__ == "__main__":
    main()
