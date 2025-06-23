import fnmatch
import os

import lldb
import yaml
from rich.console import Console

from .source_cache import SourceCacheManager


class SourceRangeManager:
    def __init__(self, target, logger, config_manager):
        self._target = target
        self.logger = logger
        self.config_manager = config_manager
        self._skip_source_files = self.config_manager.config.get("skip_source_files", [])
        self._console = Console()
        self.cache_manager = SourceCacheManager(target, logger, config_manager)
        self._address_decision_cache = {}
        self._file_skip_cache = {}

    def should_skip_source_file_by_path(self, full_path):
        """根据文件路径判断是否跳过（使用缓存优化）"""
        # 检查文件缓存
        if full_path in self._file_skip_cache:
            decision = self._file_skip_cache[full_path]
            # self.logger.debug(f"File cache hit for {full_path}: skip={decision}")
            return decision

        # self.logger.debug(f"File cache miss for {full_path}, checking patterns...")

        # 检查是否匹配跳过模式
        matched_patterns = []
        for pattern in self._skip_source_files:
            if fnmatch.fnmatch(full_path, pattern):
                matched_patterns.append(f"path={pattern}")
            elif fnmatch.fnmatch(os.path.basename(full_path), pattern):
                matched_patterns.append(f"basename={pattern}")

        matched = len(matched_patterns) > 0

        # 更新缓存
        self._file_skip_cache[full_path] = matched

        # if matched:
        #     self.logger.info(f"Skipping file: {full_path}, matched: {', '.join(matched_patterns)}")
        # else:
        #     self.logger.debug(f"Not skipping file: {full_path}, no matching patterns")

        return matched

    def should_skip_source_address_dynamic(self, address):
        """动态检查地址是否应跳过（使用缓存优化）"""
        # 检查地址缓存
        if address in self._address_decision_cache:
            # self.logger.debug(f"Address cache hit for 0x{address:x}: {self._address_decision_cache[address]}")
            return self._address_decision_cache[address]

        # self.logger.debug(f"Address cache miss for 0x{address:x}, resolving...")

        # 解析地址获取源文件信息
        sb_addr = self._target.ResolveLoadAddress(address)
        if not sb_addr.IsValid():
            # self.logger.debug(f"Failed to resolve load address 0x{address:x}")
            self._address_decision_cache[address] = True
            return True

        # 使用行信息获取文件信息
        line_entry = sb_addr.GetLineEntry()
        if not line_entry or not line_entry.IsValid():
            self.logger.debug(f"No valid line entry found for address 0x{address:x}")
            self._address_decision_cache[address] = True
            return False

        file_spec = line_entry.GetFileSpec()
        if not file_spec:
            self.logger.debug(f"No file specification found for address 0x{address:x}")
            self._address_decision_cache[address] = False
            return False

        full_path = file_spec.fullpath
        # self.logger.debug(f"Address 0x{address:x} maps to file: {full_path}")

        # 使用文件路径检查函数
        matched = self.should_skip_source_file_by_path(full_path)

        # 更新地址缓存
        self._address_decision_cache[address] = matched

        # 记录缓存统计信息
        # self.logger.debug(
        #     f"Cache sizes: address_cache={len(self._address_decision_cache)}, "
        #     f"file_cache={len(self._file_skip_cache)}"
        # )
        return matched

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
