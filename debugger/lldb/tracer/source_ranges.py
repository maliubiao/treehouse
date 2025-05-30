import bisect
import fnmatch
import os
from collections import namedtuple

import lldb
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from .source_cache import SourceCacheManager
from .source_statistics import SourceStatistics
from .source_tree import SourceTreeBuilder  # 导入树构建器

# 定义命名元组存储源文件范围信息
SourceRange = namedtuple("SourceRange", ["symbol", "start_addr", "end_addr"])
# 新增合并范围的数据结构
MergedRange = namedtuple("MergedRange", ["start_addr", "end_addr"])


class SourceRangeManager:
    def __init__(self, target, logger, config_manager):
        self._target = target
        self.logger = logger
        self.config_manager = config_manager
        self._source_ranges = []
        self._merged_ranges = []  # 新增合并后的范围列表
        self._sorted_addresses = []
        self._skip_source_files = self.config_manager.config.get("skip_source_files", [])
        self._skip_modules = self.config_manager.config.get("skip_modules", [])
        self._console = Console()
        self.cache_manager = SourceCacheManager(target, logger, config_manager)

        # 缓存文件路径的跳过决策
        self._file_skip_cache = {}

        # 统计数据结构
        self.pattern_stats = {pattern: {"files": 0, "symbols": 0} for pattern in self._skip_source_files}
        self.total_files = 0
        self.total_symbols = 0
        self.skipped_symbols = 0
        self.cache_hits = 0  # 缓存命中统计

        # 树状结构构建器
        self.tree_builder = SourceTreeBuilder()

    def build_source_file_ranges(self):
        """增量构建源文件过滤范围，优化内存使用"""
        if not self._target or not self._target.IsValid():
            return

        # 重置统计
        self._source_ranges = []
        self._merged_ranges = []  # 重置合并范围
        self.pattern_stats = {pattern: {"files": 0, "symbols": 0} for pattern in self._skip_source_files}
        self.total_files = 0
        self.total_symbols = 0
        self.skipped_symbols = 0
        self.cache_hits = 0  # 重置缓存命中计数
        matched_files = set()

        # 创建进度条
        progress_columns = [
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeElapsedColumn(),
            TextColumn("| Files: {task.fields[files]} | Symbols: {task.fields[symbols]}/{task.fields[total_symbols]}"),
        ]

        with Progress(*progress_columns, console=self._console) as progress:
            # 步骤1: 按模块处理
            total_modules = self._target.GetNumModules()
            module_task = progress.add_task(
                "[cyan]Processing modules...", total=total_modules, files=0, symbols=0, total_symbols=0
            )

            for module_idx, module in enumerate(self._target.module_iter()):
                module_name = os.path.basename(module.GetFileSpec().fullpath)
                full_path = module.GetFileSpec().fullpath

                # 检查模块是否在跳过列表中
                skip_module = False
                for pattern in self._skip_modules:
                    if fnmatch.fnmatch(full_path, pattern) or fnmatch.fnmatch(module_name, pattern):
                        self.logger.debug("Skipping module: %s (matches pattern: %s)", module_name, pattern)
                        skip_module = True
                        break

                if skip_module:
                    progress.update(module_task, advance=1)
                    continue  # 跳过整个模块

                progress.update(
                    module_task,
                    advance=1,
                    description=f"[cyan]Processing module {module_name} ({module_idx + 1}/{total_modules})",
                )

                # 尝试从缓存加载
                cache_symbols = self.cache_manager.load_cache(module)
                module_load_base = module.GetObjectFileHeaderAddress().GetLoadAddress(self._target)

                if cache_symbols:
                    # 应用ALSR修正并添加到范围列表
                    corrected_symbols = self.cache_manager.apply_alsr_correction(cache_symbols, module_load_base)
                    self._source_ranges.extend(corrected_symbols)

                    continue

                # 没有缓存，处理当前模块
                module_symbols = []
                num_symbols = module.GetNumSymbols()
                symbol_task = progress.add_task(
                    f"[yellow]  Symbols in {module_name}",
                    total=num_symbols,
                    visible=num_symbols > 0,
                    files=self.total_files,
                    symbols=self.skipped_symbols,
                    total_symbols=self.total_symbols,
                )

                for symbol_idx in range(num_symbols):
                    symbol = module.GetSymbolAtIndex(symbol_idx)
                    if symbol.GetType() != lldb.eSymbolTypeCode:
                        progress.update(symbol_task, advance=1)
                        continue

                    self.total_symbols += 1

                    # 获取符号的编译单元
                    comp_unit = symbol.addr.GetCompileUnit()
                    if not comp_unit:
                        progress.update(symbol_task, advance=1)
                        continue

                    file_spec = comp_unit.GetFileSpec()
                    full_path = file_spec.fullpath
                    if not full_path:
                        progress.update(symbol_task, advance=1)
                        continue

                    # 添加到树构建器
                    self.tree_builder.add_symbol(full_path)

                    # 新文件计数
                    if full_path not in matched_files:
                        self.total_files += 1
                        matched_files.add(full_path)

                    # 检查是否匹配跳过模式 - 使用缓存优化
                    matched = False
                    # 检查缓存
                    if full_path in self._file_skip_cache:
                        self.cache_hits += 1
                        matched = self._file_skip_cache[full_path]
                    else:
                        # 缓存未命中，进行匹配
                        for pattern in self._skip_source_files:
                            if fnmatch.fnmatch(full_path, pattern) or fnmatch.fnmatch(
                                os.path.basename(full_path), pattern
                            ):
                                matched = True
                                if full_path not in matched_files:
                                    self.pattern_stats[pattern]["files"] += 1
                                    matched_files.add(full_path)
                                self.pattern_stats[pattern]["symbols"] += 1
                                self.skipped_symbols += 1
                                break
                        if not matched:
                            self.logger.debug(
                                "Symbol %s in file %s does not match any skip pattern", symbol.GetName(), full_path
                            )
                        # 更新缓存
                        self._file_skip_cache[full_path] = matched

                    if not matched:
                        progress.update(symbol_task, advance=1)
                        continue

                    # 获取符号地址范围
                    start_addr = symbol.GetStartAddress().GetLoadAddress(self._target)
                    end_addr = symbol.GetEndAddress().GetLoadAddress(self._target)
                    file_start_addr = symbol.GetStartAddress().GetFileAddress()
                    file_end_addr = symbol.GetEndAddress().GetFileAddress()

                    if start_addr == lldb.LLDB_INVALID_ADDRESS or end_addr == lldb.LLDB_INVALID_ADDRESS:
                        progress.update(symbol_task, advance=1)
                        continue

                    # 创建元组并添加到范围列表
                    symbol_info = (symbol, start_addr, end_addr)
                    self._source_ranges.append(symbol_info)

                    # 保存模块符号信息用于缓存
                    module_symbols.append((symbol.GetName(), file_start_addr, file_end_addr))

                    progress.update(
                        symbol_task,
                        advance=1,
                        files=self.total_files,
                        symbols=self.skipped_symbols,
                        total_symbols=self.total_symbols,
                    )

                # 保存模块的缓存
                if module_symbols:
                    self.cache_manager.save_cache(module, module_symbols)

                progress.remove_task(symbol_task)

            progress.remove_task(module_task)

        # 合并连续地址区间
        self._merge_consecutive_ranges()

        # 显示统计信息
        self._display_statistics()

        # 排序范围以便快速查找
        self._merged_ranges.sort(key=lambda x: x.start_addr)  # 按start_addr排序
        self._sorted_addresses = [x.start_addr for x in self._merged_ranges]

    def _merge_consecutive_ranges(self):
        """合并连续的地址区间"""
        if not self._source_ranges:
            return

        # 按起始地址排序
        self._source_ranges.sort(key=lambda x: x[1])
        merged = []
        current_symbol, current_start, current_end = self._source_ranges[0]

        for i in range(1, len(self._source_ranges)):
            symbol, start, end = self._source_ranges[i]
            # 检查当前区间是否与下一个连续
            if current_end == start:
                # 扩展当前区间
                current_end = end
            else:
                # 保存当前合并区间
                merged.append(MergedRange(current_start, current_end))
                current_start, current_end = start, end

        # 添加最后一个区间
        merged.append(MergedRange(current_start, current_end))

        # 更新合并后范围列表
        self._merged_ranges = merged
        self.logger.debug(f"Merged {len(self._source_ranges)} ranges into {len(merged)} consecutive ranges")

    def _display_statistics(self):
        """显示源文件过滤统计信息并生成Mermaid图表"""
        # 显示表格统计
        stats = SourceStatistics(self.pattern_stats, self.total_files, self.total_symbols, self.skipped_symbols)
        stats.display()
        self.tree_builder.print_tree()

        # 显示缓存命中率
        if self.total_symbols > 0:
            hit_rate = (self.cache_hits / self.total_symbols) * 100
            self._console.print(
                f"[bold cyan]File skip cache:[/bold cyan] "
                f"Hits: {self.cache_hits}/{self.total_symbols} "
                f"({hit_rate:.2f}%)"
            )

        # 显示范围合并信息
        if self._source_ranges:
            self._console.print(
                f"[bold cyan]Range merging:[/bold cyan] "
                f"Merged {len(self._source_ranges)} ranges into "
                f"{len(self._merged_ranges)} consecutive blocks"
            )

    def dump_source_files_for_skip(self):
        """转储源文件信息并生成配置文件"""
        if not self._target or not self._target.IsValid():
            self.logger.error("No valid target to dump source files")
            return

        console = self._console
        source_files = set()

        # 收集所有源文件
        for module in self._target.module_iter():
            # 跳过配置为skip_modules的模块
            module_name = os.path.basename(module.GetFileSpec().fullpath)
            full_path = module.GetFileSpec().fullpath
            skip_module = any(
                fnmatch.fnmatch(full_path, pattern) or fnmatch.fnmatch(module_name, pattern)
                for pattern in self.config_manager.config.get("skip_modules", [])
            )
            if skip_module:
                continue

            for comp_unit in module.compile_units:
                file_spec = comp_unit.GetFileSpec()
                full_path = file_spec.fullpath
                if full_path:
                    source_files.add(full_path)

        # 按路径排序
        sorted_files = sorted(source_files)
        output_file = self.config_manager.config.get("source_files_list_file", "source_files.yaml")

        try:
            # 保存所有源文件到YAML
            with open(output_file, "w", encoding="utf-8") as f:
                yaml.dump(sorted_files, f, indent=4, default_flow_style=False)

            console.print(f"[bold green]Saved source files list to {output_file}[/bold green]")
            console.print(f"[bold yellow]Total source files: {len(sorted_files)}[/bold yellow]")
            console.print("\n[bold]Next steps:[/bold]")
            console.print("1. Edit the file to add patterns under 'skip_source_files' key")
            console.print("2. Example patterns:")
            console.print("   skip_source_files:")
            console.print("     - '*libc.so*'")
            console.print("     - '*/stdlib.c'")
            console.print("3. Save the file and restart the tracer")
        except Exception as e:
            self.logger.error("Failed to save source files list: %s", str(e))
            console.print(f"[bold red]Error saving file: {str(e)}[/bold red]")

    def should_skip_source_address(self, address):
        """检查地址是否在源文件跳过范围内"""
        if not self._merged_ranges:
            return False

        idx = bisect.bisect_right(self._sorted_addresses, address) - 1
        if 0 <= idx < len(self._merged_ranges):
            merged_range = self._merged_ranges[idx]
            if merged_range.start_addr <= address < merged_range.end_addr:
                self.logger.info(
                    "Step over addr 0x%x in merged range: [0x%x, 0x%x)",
                    address,
                    merged_range.start_addr,
                    merged_range.end_addr,
                )
                return True
        return False
