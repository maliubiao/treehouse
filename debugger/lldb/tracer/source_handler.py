import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import lldb

if TYPE_CHECKING:
    from .core import Tracer


class SourceHandler:
    def __init__(self, tracer: "Tracer") -> None:
        self.tracer: "Tracer" = tracer
        self.logger: logging.Logger = tracer.logger

        # Caches
        self.compile_unit_entries_cache: Dict[str, list] = {}
        self.sorted_line_entries_cache: Dict[str, list] = {}
        self.line_to_next_line_cache: Dict[str, Dict[int, tuple]] = {}
        self.source_cache: Dict[str, List[str]] = {}
        self._resolved_path_cache: Dict[str, Optional[str]] = {}
        self._source_search_paths = self.tracer.config_manager.get_source_search_paths()

    @lru_cache(maxsize=100)
    def get_file_lines(self, filepath: str) -> Optional[List[str]]:
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

    def _get_compile_unit_line_entries(self, compile_unit: lldb.SBCompileUnit) -> List[lldb.SBLineEntry]:
        """获取并缓存编译单元的行条目"""
        cache_key = f"{compile_unit.GetFileSpec().fullpath}-{compile_unit.GetNumLineEntries()}"
        if cache_key in self.compile_unit_entries_cache:
            return self.compile_unit_entries_cache[cache_key]

        entries = []
        for i in range(compile_unit.GetNumLineEntries()):
            entry = compile_unit.GetLineEntryAtIndex(i)
            if entry.IsValid():
                entries.append(entry)

        # 缓存结果
        self.compile_unit_entries_cache[cache_key] = entries
        return entries

    def _get_sorted_line_entries(self, frame, filepath: str) -> List[lldb.SBLineEntry]:
        """获取按行号排序的行条目"""
        if filepath in self.sorted_line_entries_cache:
            return self.sorted_line_entries_cache[filepath]

        # 获取所有编译单元的行条目并排序
        all_entries = []

        entries = self._get_compile_unit_line_entries(frame.compile_unit)
        all_entries.extend(entries)

        # 按行号排序
        sorted_entries = sorted(all_entries, key=lambda e: e.GetLine())
        self.sorted_line_entries_cache[filepath] = sorted_entries
        return sorted_entries

    def _build_line_to_next_line_cache(self, filepath: str, sorted_entries: List[lldb.SBLineEntry]) -> Dict[int, tuple]:
        """构建行号到下一行条目的映射缓存，包含下一行列信息"""
        if filepath in self.line_to_next_line_cache:
            return self.line_to_next_line_cache[filepath]

        cache = {}
        # 创建行号和列号的元组列表
        line_entries = [(entry.GetLine(), entry.GetColumn()) for entry in sorted_entries if entry.GetLine() > 0]
        line_entries.sort()  # 按行号和列号排序

        # 构建映射: 每行 -> (下一有效行号, 下一行的列号)
        for i in range(len(line_entries) - 1):
            current_line = line_entries[i][0]
            next_line = line_entries[i + 1][0]
            next_column = line_entries[i + 1][1]
            if current_line not in cache:  # 只保存第一次出现的行号映射
                cache[current_line] = (next_line, next_column)

        # 最后一行映射到自身，列号为0
        if line_entries:
            last_line = line_entries[-1][0]
            if last_line not in cache:
                cache[last_line] = (last_line, 0)

        self.line_to_next_line_cache[filepath] = cache
        return cache

    def get_source_code_range(self, frame: lldb.SBFrame, filepath: str, start_line: int) -> str:
        """获取从起始行到下一行条目前的源代码，考虑列信息"""
        resolved_path = self.resolve_source_path(filepath)
        if not resolved_path:
            return ""
        filepath = resolved_path
        lines = self.get_file_lines(filepath)
        if not lines or start_line <= 0:
            return ""

        # 尝试获取下一行号及列号
        sorted_entries = self._get_sorted_line_entries(frame, filepath)
        line_cache = self._build_line_to_next_line_cache(filepath, sorted_entries)

        # 获取下一行信息：(行号, 列号)
        next_info = line_cache.get(start_line, (start_line, 0))
        end_line, next_column = next_info

        # 单行情况
        if start_line == end_line:
            if start_line - 1 < len(lines):
                return lines[start_line - 1].strip()
            return ""

        # 多行情况
        source_lines = []

        # 如果下一行的列号是0，不提取end_line
        if next_column == 0:
            end_line = end_line - 1

        # 提取从起始行到结束行的代码
        for line_num in range(start_line, end_line + 1):
            if line_num - 1 < len(lines):
                source_lines.append(lines[line_num - 1])

        return " ".join(source_lines).strip()

    def resolve_source_path(self, original_path: str) -> Optional[str]:
        """解析源文件路径，处理相对路径和搜索路径"""
        # 检查缓存
        if original_path in self._resolved_path_cache:
            return self._resolved_path_cache[original_path]

        resolved_path = None

        # 如果是绝对路径且存在
        if os.path.isabs(original_path) and os.path.exists(original_path):
            resolved_path = original_path
        # 如果是相对路径
        elif not os.path.isabs(original_path):
            # 尝试在搜索路径中查找
            for base_path in self._source_search_paths:
                candidate = os.path.join(base_path, original_path)
                if os.path.exists(candidate):
                    resolved_path = candidate
                    break
            # 如果搜索路径中未找到，尝试在当前工作目录查找
            if not resolved_path:
                candidate = os.path.abspath(original_path)
                if os.path.exists(candidate):
                    resolved_path = candidate

        # 如果仍未找到，记录警告
        if not resolved_path:
            self.logger.warning(
                "Source file not found: %s (searched in: %s)",
                original_path,
                ", ".join(self._source_search_paths) if self._source_search_paths else "current directory",
            )
        resolved_path = str(Path(resolved_path).resolve())
        # 更新缓存
        self._resolved_path_cache[original_path] = resolved_path
        return resolved_path
