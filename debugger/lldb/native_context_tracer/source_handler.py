import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import lldb
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn

if TYPE_CHECKING:
    from .core import Tracer


class SourceHandler:
    """
    Handles all operations related to source code, including file reading,
    path resolution, and parsing of debug information (line entries).
    """

    def __init__(self, tracer: "Tracer") -> None:
        self.tracer: "Tracer" = tracer
        self.logger: logging.Logger = tracer.logger
        self._source_search_paths = self.tracer.config_manager.get_source_search_paths()

        # Caches to improve performance
        self._resolved_path_cache: Dict[str, Optional[str]] = {}
        # { comp_unit_key: [SBLineEntry] }
        self._line_entries_cache: Dict[str, List[lldb.SBLineEntry]] = {}
        # { filepath: { line_num: (next_line, next_col) } }
        self._line_to_next_line_cache: Dict[str, Dict[int, Tuple[int, int]]] = {}

    @lru_cache(maxsize=128)
    def get_file_lines(self, filepath: str) -> Optional[List[str]]:
        """Reads a file and returns its lines, with caching."""
        try:
            # Use binary read and decode to handle potential encoding issues gracefully.
            with open(filepath, "rb") as f:
                content = f.read()
            return content.decode("utf-8", errors="replace").splitlines()
        except (FileNotFoundError, PermissionError) as e:
            self.logger.warning("Could not read file %s: %s", filepath, e)
            return None
        except Exception as e:
            self.logger.error("Unexpected error reading file %s: %s", filepath, e, exc_info=True)
            return None

    def _get_compile_unit_line_entries(self, compile_unit: lldb.SBCompileUnit) -> List[lldb.SBLineEntry]:
        """
        Retrieves and caches all valid line entries for a given compile unit.
        """
        # Create a unique key for the compile unit to use for caching.
        cache_key = f"{compile_unit.GetFileSpec().GetDirectory()}/{compile_unit.GetFileSpec().GetFilename()}"
        if cache_key in self._line_entries_cache:
            return self._line_entries_cache[cache_key]

        num_entries = compile_unit.GetNumLineEntries()
        entries = []

        # 添加空列表检查：当没有条目时直接返回
        if num_entries <= 0:
            self._line_entries_cache[cache_key] = entries
            return entries

        # Use a progress bar for large compile units to provide user feedback.
        if num_entries > 500:
            with Progress(
                TextColumn("[cyan]Parsing DWARF..."),
                BarColumn(),
                MofNCompleteColumn(),
                TimeRemainingColumn(),
                transient=True,
            ) as progress:
                task = progress.add_task(f"CU: {compile_unit.GetFileSpec().GetFilename()}", total=num_entries)
                for i in range(num_entries):
                    entry = compile_unit.GetLineEntryAtIndex(i)
                    if entry.IsValid() and entry.GetLine() > 0:
                        entries.append(entry)
                    progress.update(task, advance=1)
        else:
            for i in range(num_entries):
                entry = compile_unit.GetLineEntryAtIndex(i)
                if entry.IsValid() and entry.GetLine() > 0:
                    entries.append(entry)

        # 仅在列表非空时执行排序
        if entries:
            # Sort entries by line and then column for predictable order.
            entries.sort(key=lambda e: (e.GetLine(), e.GetColumn()))

        self._line_entries_cache[cache_key] = entries
        return entries

    def _build_line_to_next_line_map(self, compile_unit: lldb.SBCompileUnit) -> Dict[int, Tuple[int, int]]:
        """
        Builds a map from each line number to the start of the next line entry.
        This is crucial for extracting multi-line statements.
        """
        filepath = compile_unit.GetFileSpec().fullpath
        if filepath in self._line_to_next_line_cache:
            return self._line_to_next_line_cache[filepath]

        sorted_entries = self._get_compile_unit_line_entries(compile_unit)
        line_map = {}

        if not sorted_entries:
            self._line_to_next_line_cache[filepath] = {}
            return {}

        # For each entry, map its line number to the start of the *next* entry.
        for i in range(len(sorted_entries) - 1):
            current_line = sorted_entries[i].GetLine()
            next_entry = sorted_entries[i + 1]
            # Only map the first entry found for a given line to avoid overwriting.
            if current_line not in line_map:
                line_map[current_line] = (next_entry.GetLine(), next_entry.GetColumn())

        # The last line entry maps to itself, indicating the end.
        last_line = sorted_entries[-1].GetLine()
        if last_line not in line_map:
            line_map[last_line] = (last_line, 0)

        self._line_to_next_line_cache[filepath] = line_map
        return line_map

    def get_source_code_for_statement(self, frame: lldb.SBFrame) -> str:
        """
        Gets the full source code for the statement at the current frame's location,
        correctly handling multi-line statements.

        Args:
            frame: The current lldb.SBFrame.

        Returns:
            The source code of the full statement, or an empty string if it
            cannot be determined.
        """
        line_entry = frame.GetLineEntry()
        if not line_entry.IsValid():
            return ""

        filepath = line_entry.GetFileSpec().fullpath
        start_line = line_entry.GetLine()

        resolved_path = self.resolve_source_path(filepath)
        if not resolved_path:
            return f"<source file '{filepath}' not found>"

        lines = self.get_file_lines(resolved_path)
        if not lines or start_line <= 0:
            return ""

        # Build the map to find the end of the current statement.
        line_map = self._build_line_to_next_line_map(frame.GetCompileUnit())
        next_line_info = line_map.get(start_line)

        if not next_line_info:
            # If no next entry, just return the current line.
            return lines[start_line - 1].strip() if start_line <= len(lines) else ""

        end_line, end_col = next_line_info

        # If the next statement is on the same line, we can't span multiple lines.
        if end_line == start_line:
            return lines[start_line - 1].strip() if start_line <= len(lines) else ""

        # Collect all lines from the start line up to (but not including) the end line.
        source_lines = []
        for i in range(start_line, end_line):
            if i <= len(lines):
                source_lines.append(lines[i - 1])

        # Add the final line, but only up to the column of the next statement.
        if end_line <= len(lines) and end_col > 0:
            source_lines.append(lines[end_line - 1][:end_col])

        return " ".join(s.strip() for s in source_lines).strip()

    def resolve_source_path(self, original_path: str) -> Optional[str]:
        """
        Resolves a source file path, searching in configured directories if necessary.
        Uses a cache to speed up repeated lookups.
        """
        if original_path in self._resolved_path_cache:
            return self._resolved_path_cache[original_path]

        # 1. Check if the original path is absolute and exists.
        if os.path.isabs(original_path) and os.path.exists(original_path):
            self._resolved_path_cache[original_path] = original_path
            return original_path

        # 2. If not, search in the configured source search paths.
        for search_path in self._source_search_paths:
            candidate = os.path.join(search_path, original_path)
            if os.path.exists(candidate):
                resolved = str(Path(candidate).resolve())
                self._resolved_path_cache[original_path] = resolved
                return resolved

        # 3. If still not found, try resolving relative to the current working directory.
        candidate = os.path.abspath(original_path)
        if os.path.exists(candidate):
            resolved = str(Path(candidate).resolve())
            self._resolved_path_cache[original_path] = resolved
            return resolved

        # 4. If all fails, cache the failure and return None.
        self.logger.warning("Source file not found: '%s'. Searched in: %s", original_path, self._source_search_paths)
        self._resolved_path_cache[original_path] = None
        return None
