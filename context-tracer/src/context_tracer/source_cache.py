import os
from typing import Dict, Optional, Tuple

from .stmt_line_table import StmtLineTable


class SourceCacheManager:
    """
    Manages a cache of StmtLineTable instances for different source files.

    This class provides a centralized way to get the source code for a specific
    line in a file, intelligently handling multi-line statements. It caches
    the parsed AST and line information to avoid re-reading and re-parsing
    files, which is crucial for performance in a debugger setting.

    A single global instance of this class is created for application-wide use.
    """

    def __init__(self):
        """Initializes the SourceCacheManager."""
        # Cache mapping filenames to their StmtLineTable objects.
        self._table_cache: Dict[str, StmtLineTable] = {}
        # Cache for file contents to avoid re-reading from disk.
        self._source_cache: Dict[str, str] = {}

    def add_source(self, filename: str, source_code: str):
        """
        Manually adds source code to the cache, bypassing file I/O.

        This is useful for testing or for sources that don't exist on disk
        (e.g., code from `exec`).

        Args:
            filename: A unique identifier for the source code (e.g., '<string>').
            source_code: The Python source code content.
        """
        if filename not in self._source_cache:
            self._source_cache[filename] = source_code
            # If a StmtLineTable was somehow created before this
            # (e.g., from a failed file read), we should invalidate it.
            if filename in self._table_cache:
                del self._table_cache[filename]

    def _get_table(self, filename: str) -> Optional[StmtLineTable]:
        """
        Retrieves or creates a StmtLineTable for a given file.

        Handles file reading and caching of both source code and the table.
        """
        if filename in self._table_cache:
            return self._table_cache[filename]

        try:
            source_code = self._source_cache.get(filename)
            if source_code is None:
                # Ensure the path is absolute and normalized for a consistent cache key.
                abs_filename = os.path.abspath(filename)
                if abs_filename in self._source_cache:
                    source_code = self._source_cache[abs_filename]
                else:
                    with open(abs_filename, "r", encoding="utf-8") as f:
                        source_code = f.read()
                    self._source_cache[abs_filename] = source_code
                filename = abs_filename  # Use the canonical path as the key

            table = StmtLineTable(source_code, filename)
            self._table_cache[filename] = table
            return table
        except (FileNotFoundError, IOError, SyntaxError) as e:
            # This can happen for generated code, C extensions, or invalid files.
            print(f"Warning: Could not load or parse source for {filename}: {e}")
            return None

    def get_source_for_line(self, filename: str, lineno: int) -> Optional[str]:
        """
        Gets the source code corresponding to a specific line in a file.

        If the line is part of a multi-line simple statement, the full
        statement's source is returned. Otherwise, the source of the
        single line itself is returned.

        Args:
            filename: The path to the source file.
            lineno: The 1-based line number.

        Returns:
            The corresponding source code as a string, or None if the file
            cannot be read or the line number is invalid.
        """
        table = self._get_table(filename)
        if not table:
            return None

        # First, try to get the full multi-line simple statement source.
        statement_source = table.get_statement_source(lineno)
        if statement_source:
            return statement_source

        # Fallback: If it's not part of a multi-line simple statement
        # (e.g., if/def/class line, comment, or a simple single-line statement),
        # return just that single line's source.
        if 1 <= lineno <= len(table.lines):
            return table.lines[lineno - 1]

        # Line number is out of bounds for the file.
        return None

    def get_statement_info(self, filename: str, lineno: int) -> Optional[Tuple[str, int, int]]:
        """
        Gets the full source, start, and end line for the statement at a given line.

        This method intelligently handles multi-line simple statements and provides
        the necessary context (start and end lines) for consumers like a debugger.

        Args:
            filename: The path to the source file.
            lineno: The 1-based line number.

        Returns:
            A tuple (source_code, start_lineno, end_lineno), or None if the
            file cannot be processed or the line is invalid.
        """
        table = self._get_table(filename)
        if not table:
            return None

        # First, check if the line is part of a mapped multi-line simple statement.
        statement_range = table.get_statement_range(lineno)
        if statement_range:
            start, end = statement_range
            # get_statement_source is efficient as it uses the same range.
            source = table.get_statement_source(lineno)
            if source is not None:
                return source, start, end

        # Fallback: If not in a mapped statement (e.g., if/def/class line,
        # comment, or a simple single-line statement), return the single line.
        if 1 <= lineno <= len(table.lines):
            source = table.lines[lineno - 1]
            return source, lineno, lineno

        # Line number is out of bounds.
        return None

    def clear_cache(self):
        """Clears the entire cache."""
        self._table_cache.clear()
        self._source_cache.clear()


# A global instance to be used throughout the application.
# This acts as a singleton, providing a single point of access to the cache.
source_cache_manager = SourceCacheManager()


def get_source_for_line(filename: str, lineno: int) -> Optional[str]:
    """
    A convenient module-level function to get source code for a line.

    See SourceCacheManager.get_source_for_line for details.
    """
    return source_cache_manager.get_source_for_line(filename, lineno)


def get_statement_info(filename: str, lineno: int) -> Optional[Tuple[str, int, int]]:
    """
    A convenient module-level function to get statement info for a line.

    See SourceCacheManager.get_statement_info for details.
    """
    return source_cache_manager.get_statement_info(filename, lineno)
