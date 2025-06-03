import bisect
import fnmatch
import os
import sys
from collections import defaultdict

import lldb
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text


class ModuleManager:
    def __init__(self, target, logger, config_manager):
        self._target = target
        self.logger = logger
        self.config_manager = config_manager
        self._module_ranges = {}
        self._skip_ranges = []
        self._sorted_ranges = []
        self._sorted_addresses = []
        self._skip_addresses = []
        self._skip_cache = {}
        self._addr_to_sym_cache = {}

    def load_modules_addresses(self):
        """Load and cache all module address ranges for quick lookup."""
        if not self._target or not self._target.IsValid():
            self.logger.error("No valid target to load modules")
            return

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

            self._module_ranges[module.file.fullpath] = module_info
        self.logger.debug("Loaded module address ranges for %d modules", len(self._module_ranges))

    def dump_modules_info(self):
        """Display module information with colored UI including sections and address ranges."""
        if not self._target or not self._target.IsValid():
            self.logger.error("No valid target to dump modules")
            return

        console = Console()
        if not self._module_ranges:
            self.load_modules_addresses()

        section_colors = {
            "__text": "green",
            "__data": "red",
            "__bss": "blue",
            "__const": "yellow",
            "__cstring": "magenta",
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

                base_color = section_colors.get(section_name.split(".")[0], "dim")
                range_text = Text()
                range_text.append(f"0x{start_addr:016x}", style=f"bright_cyan")
                range_text.append(" → ", style="dim")
                range_text.append(f"0x{end_addr:016x}", style=f"bright_green")

                module_table.add_row(
                    Text(section_name, style=f"bold {base_color}"),
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
        if not self._module_ranges:
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

    def _build_skip_modules_ranges(self):
        """Build address ranges for modules that should be skipped with colored UI output."""
        self.load_modules_addresses()  # 确保模块地址已加载

        self._skip_ranges = []
        skip_modules = self.config_manager.config.get("skip_modules", [])
        if not skip_modules:
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
            for pattern in skip_modules:
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

    def should_skip_address(self, address, module_fullpath=""):
        """检查地址是否在跳过范围内，使用缓存优化"""
        # 首先检查缓存
        if address in self._skip_cache:
            return self._skip_cache[address]

        if module_fullpath:
            # 如果提供了模块路径，检查是否在跳过模块列表中
            skip_modules = self.config_manager.config.get("skip_modules", [])
            if any(fnmatch.fnmatch(module_fullpath, pattern) for pattern in skip_modules):
                self._skip_cache[address] = True
                return True

        skip_result = False

        # 检查模块范围
        if self._skip_ranges:
            idx = bisect.bisect_right(self._skip_addresses, address) - 1
            if 0 <= idx < len(self._skip_ranges):
                range_info = self._skip_ranges[idx]
                if range_info["start_addr"] <= address < range_info["end_addr"]:
                    skip_result = True

        # 更新缓存
        self._skip_cache[address] = skip_result
        return skip_result

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

    def get_addr_symbol(self, address):
        """获取地址对应的符号名，使用缓存"""
        if address in self._addr_to_sym_cache:
            return self._addr_to_sym_cache[address]

        addr = self._target.ResolveLoadAddress(address)
        sym_name = addr.symbol.name if addr.symbol.IsValid() else "unknown"
        self._addr_to_sym_cache[address] = sym_name
        return sym_name
