import ast
import hashlib
import json
import os
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

# A tuple of "simple" statement node types from the `ast` module.
# Used by the AstParserStrategy.
_SIMPLE_STMT_NODES = (
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Return,
    ast.Pass,
    ast.Break,
    ast.Continue,
    ast.Raise,
    ast.Assert,
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
)

# A set of "simple" statement node types for Tree-sitter.
# Used by the TreeSitterParserStrategy.
_TS_SIMPLE_STMT_NODES = {
    "expression_statement",
    "assignment",
    "augmented_assignment",
    "return_statement",
    "pass_statement",
    "break_statement",
    "continue_statement",
    "raise_statement",
    "assert_statement",
    "import_statement",
    "import_from_statement",
    "global_statement",
    "nonlocal_statement",
    "delete_statement",
}


class StmtLineTableCache:
    """
    Manages a disk cache for StmtLineTable results to improve performance.

    The cache is invalidated if the source file's size or modification time changes.
    Cache files are stored in a subdirectory within the system's temporary directory.
    """

    def __init__(self) -> None:
        """Initializes the cache and creates the cache directory if it doesn't exist."""
        try:
            cache_dir = Path(tempfile.gettempdir()) / "context_tracer_cache" / "stmt_line_table"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_dir: Optional[Path] = cache_dir
        except (OSError, PermissionError) as e:
            print(f"Warning: Could not create StmtLineTable cache directory: {e}")
            self.cache_dir = None

    def _get_cache_path(self, filename: str) -> Optional[Path]:
        """Generates a unique cache file path from a source filename using a hash."""
        if not self.cache_dir:
            return None
        try:
            abs_path = os.path.abspath(filename)
            hasher = hashlib.sha256(abs_path.encode("utf-8"))
            return self.cache_dir / f"{hasher.hexdigest()}.json"
        except (OSError, ValueError):
            return None

    @staticmethod
    def _get_file_metadata(filename: str) -> Optional[Dict[str, Any]]:
        """Gets the size and modification time of a file."""
        try:
            stat = os.stat(filename)
            return {"size": stat.st_size, "mtime": stat.st_mtime}
        except (FileNotFoundError, OSError):
            return None

    def get(self, filename: str) -> Optional[List[Optional[Tuple[int, int]]]]:
        """
        Retrieves a line map from the cache if it's valid.

        Args:
            filename: The absolute path to the source file.

        Returns:
            The cached line map, or None if the cache is invalid or doesn't exist.
        """
        if not self.cache_dir or not Path(filename).is_file() or filename.startswith("<"):
            return None  # Don't cache non-file sources

        cache_path = self._get_cache_path(filename)
        if not cache_path or not cache_path.exists():
            return None

        current_metadata = self._get_file_metadata(filename)
        if not current_metadata:
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            cached_metadata = data.get("metadata", {})
            if (
                cached_metadata.get("size") == current_metadata["size"]
                and cached_metadata.get("mtime") == current_metadata["mtime"]
            ):
                return data.get("line_map")
        except (IOError, json.JSONDecodeError, KeyError):
            # Cache is corrupted or invalid, treat as a miss
            pass

        return None

    def set(self, filename: str, line_map: List[Optional[Tuple[int, int]]]) -> None:
        """
        Saves a line map to the cache.

        Args:
            filename: The absolute path to the source file.
            line_map: The line map data to cache.
        """
        if not self.cache_dir or not Path(filename).is_file() or filename.startswith("<"):
            return

        metadata = self._get_file_metadata(filename)
        if not metadata:
            return

        cache_path = self._get_cache_path(filename)
        if not cache_path:
            return

        data_to_cache = {"metadata": metadata, "line_map": line_map}

        try:
            # Atomic write: write to temp file then rename
            temp_path = cache_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data_to_cache, f)
            os.rename(temp_path, cache_path)
        except (IOError, OSError) as e:
            print(f"Warning: Could not write StmtLineTable cache for {filename}: {e}")


# Module-level singleton instance for the cache manager.
_cache = StmtLineTableCache()


class StatementParserStrategy(Protocol):
    """
    A protocol defining the interface for statement parsing strategies.
    This allows swapping different parsers (e.g., AST, Tree-sitter)
    while maintaining a consistent interface for StmtLineTable.
    """

    def build_line_map(self, source_code: str, filename: str, line_count: int) -> List[Optional[Tuple[int, int]]]:
        """
        Parses source code and builds a map from line numbers to statement ranges.

        Args:
            source_code: The Python source code to parse.
            filename: The filename, used for error reporting.
            line_count: The total number of lines in the source code.

        Returns:
            A list where the index `i` corresponds to line `i+1`. The value
            is a tuple `(start_lineno, end_lineno)` for the simple statement
            containing that line, or None if the line is not part of one.
        """
        ...


class AstParserStrategy:
    """A statement parser strategy that uses Python's built-in `ast` module."""

    def build_line_map(self, source_code: str, filename: str, line_count: int) -> List[Optional[Tuple[int, int]]]:
        """Builds the line map using `ast.walk`."""
        line_map: List[Optional[Tuple[int, int]]] = [None] * line_count
        try:
            tree = ast.parse(source_code, filename=filename)
        except SyntaxError as e:
            print(f"Warning: SyntaxError in {filename}, line map may be incomplete (AST): {e}")
            return line_map

        for node in ast.walk(tree):
            if isinstance(node, _SIMPLE_STMT_NODES):
                start_lineno = node.lineno
                # getattr is used for python versions before 3.8
                end_lineno = getattr(node, "end_lineno", start_lineno)

                for line_num in range(start_lineno, end_lineno + 1):
                    if 0 <= line_num - 1 < len(line_map):
                        line_map[line_num - 1] = (start_lineno, end_lineno)
        return line_map


class TreeSitterParserStrategy:
    """
    A high-performance statement parser strategy using Tree-sitter.
    This is generally much faster than the AST-based approach.
    """

    _parser = None

    @classmethod
    def _initialize_parser(cls) -> None:
        """Initializes the Tree-sitter parser for Python, loading the grammar."""
        if cls._parser:
            return

        try:
            from tree_sitter import Language, Parser
            from tree_sitter_python import language as python_language

            # mypy complains about cls.parser, but it's a valid dynamic assignment
            cls._parser = Parser(Language(python_language()))  # type: ignore
        except (ImportError, OSError) as e:
            raise ImportError(
                "Tree-sitter or python grammar not installed. Please run `pip install tree-sitter tree-sitter-python`."
            ) from e

    def build_line_map(self, source_code: str, filename: str, line_count: int) -> List[Optional[Tuple[int, int]]]:
        """Builds the line map by traversing the Tree-sitter CST."""
        self._initialize_parser()
        line_map: List[Optional[Tuple[int, int]]] = [None] * line_count

        try:
            tree = self._parser.parse(bytes(source_code, "utf8"))  # type: ignore
        except Exception as e:
            print(f"Warning: Tree-sitter parsing failed for {filename}: {e}")
            return line_map

        # Use a work queue for a non-recursive BFS traversal of the tree.
        queue = [tree.root_node]
        while queue:
            node = queue.pop(0)

            if node.type in _TS_SIMPLE_STMT_NODES:
                # Tree-sitter points are 0-indexed (row, col).
                # Our line numbers are 1-indexed.
                start_lineno = node.start_point[0] + 1
                end_lineno = node.end_point[0] + 1

                for line_num in range(start_lineno, end_lineno + 1):
                    if 0 <= line_num - 1 < len(line_map):
                        line_map[line_num - 1] = (start_lineno, end_lineno)

            # Add children to the queue to continue traversal.
            # We don't need to descend into simple statements we've already processed.
            if node.type not in _TS_SIMPLE_STMT_NODES:
                queue.extend(node.children)

        return line_map


class StmtLineTable:
    """
    Parses Python source code to map each line number to the full multi-line
    simple statement it belongs to.

    This class uses a pluggable strategy system (`ast` or `tree-sitter`) for
    parsing, with `tree-sitter` being the high-performance default. It identifies
    self-contained, executable statements like assignments (`x = ...`) and
    `return`, excluding the structural lines of compound statements (`if`, `for`).

    To improve performance, it uses a disk-based cache (`StmtLineTableCache`)
    to store parsing results, avoiding re-parsing of unchanged files.

    Attributes:
        source_code (str): The Python source code.
        filename (str): The filename associated with the source code.
        lines (List[str]): The source code split into lines.
        line_map (List[Optional[Tuple[int, int]]]): A mapping from 0-indexed
            line number to a tuple `(start_lineno, end_lineno)`.
    """

    def __init__(
        self,
        source_code: str,
        filename: str = "<string>",
        strategy: str = "ast",
    ):
        """
        Initializes the table and builds the line-to-statement mapping.

        This method will first attempt to load the mapping from a disk cache.
        If the cache is missing or stale, it will parse the source code using
        the specified strategy and then save the result to the cache.

        Args:
            source_code: The Python source code to analyze.
            filename: The filename for error reporting.
            strategy: The parsing strategy to use ('tree-sitter' or 'ast').

        Raises:
            ValueError: If an unknown strategy is provided.
        """
        self.source_code = source_code
        self.filename = filename
        self.lines = self.source_code.splitlines()
        self._strategy: StatementParserStrategy

        if strategy == "tree-sitter":
            self._strategy = TreeSitterParserStrategy()
        elif strategy == "ast":
            self._strategy = AstParserStrategy()
        else:
            raise ValueError(f"Unknown parser strategy: {strategy}")

        # Try to load from cache first.
        cached_map = _cache.get(self.filename)
        if cached_map is not None:
            self.line_map = cached_map
        else:
            # If cache miss, build the map.
            built_map = self._build_table()
            self.line_map = built_map
            # Save the newly built map to the cache for next time.
            _cache.set(self.filename, built_map)

    def _build_table(self) -> List[Optional[Tuple[int, int]]]:
        """Delegates the AST/CST walk to the chosen strategy."""
        return self._strategy.build_line_map(self.source_code, self.filename, len(self.lines))

    def get_statement_range(self, lineno: int) -> Optional[Tuple[int, int]]:
        """
        Gets the start and end line numbers of the statement for a given line.

        Args:
            lineno: The 1-based line number to query.

        Returns:
            A tuple (start_lineno, end_lineno) or None if the line is not
            part of a simple statement.
        """
        if not 1 <= lineno <= len(self.line_map):
            return None
        return self.line_map[lineno - 1]

    def get_statement_source(self, lineno: int) -> Optional[str]:
        """
        Gets the full source code of the statement containing the given line.

        Args:
            lineno: The 1-based line number to query.

        Returns:
            The source code of the statement, or None if not found.
        """
        statement_range = self.get_statement_range(lineno)
        if not statement_range:
            return None

        start_lineno, end_lineno = statement_range
        statement_lines = self.lines[start_lineno - 1 : end_lineno]
        return "\n".join(statement_lines)


if __name__ == "__main__":
    import traceback
    from typing import Any, Dict, List

    # A cleaner test source without misleading line number comments.
    test_source = textwrap.dedent(
        """\
    # Simple assignment
    x = 1

    # Multi-line list assignment
    my_list = [
        1, 2, 3,
        4, 5, 6
    ]

    # An if statement (compound, should not be mapped)
    if x > 0:
        # A statement inside the if block
        print("positive")

    # Multi-line function call assignment
    result = str(
        "a long string"
    )

    # A comment line
    # Another comment line

    # Another simple statement
    y = x + 1
    """
    )

    # Test definitions:
    # 'query': A unique snippet on a line to be queried.
    # 'expected': The full simple statement that should contain the query line,
    #             or None if the line is not part of a simple statement.
    test_definitions: List[Dict[str, Any]] = [
        {"query": "x = 1", "expected": "x = 1"},
        {
            "query": "1, 2, 3,",
            "expected": textwrap.dedent(
                """\
                my_list = [
                    1, 2, 3,
                    4, 5, 6
                ]"""
            ).strip(),
        },
        {
            "query": "4, 5, 6",  # Test another line in the same multi-line stmt
            "expected": textwrap.dedent(
                """\
                my_list = [
                    1, 2, 3,
                    4, 5, 6
                ]"""
            ).strip(),
        },
        {"query": 'print("positive")', "expected": 'print("positive")'},
        {
            "query": '"a long string"',
            "expected": textwrap.dedent(
                """\
                result = str(
                    "a long string"
                )"""
            ).strip(),
        },
        {"query": "y = x + 1", "expected": "y = x + 1"},
        {"query": "if x > 0:", "expected": None},
        {"query": "# A comment line", "expected": None},
        {"query": "# An if statement", "expected": None},
    ]

    def find_line_num(source_lines: List[str], snippet: str) -> int:
        """Finds the 1-based line number of the first line containing the snippet."""
        for i, line in enumerate(source_lines):
            if snippet in line:
                return i + 1
        raise ValueError(f"Snippet for line number query not found: {snippet!r}")

    def get_snippet_range(source_text: str, snippet: str) -> Tuple[int, int]:
        """Gets the 1-based start and end line numbers of a snippet in the source."""
        start_index = source_text.find(snippet)
        if start_index == -1:
            raise ValueError(f"Expected snippet not found in source: {snippet!r}")

        start_line = source_text.count("\n", 0, start_index) + 1
        end_line = start_line + snippet.count("\n")
        return start_line, end_line

    def run_tests(strategy_name: str) -> bool:
        """Runs the dynamic test suite for a given parsing strategy."""
        print(f"--- Running tests for strategy: '{strategy_name}' ---")
        all_passed = True
        source_lines = test_source.splitlines()

        try:
            # Create a temporary file to test the caching mechanism
            with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".py") as temp_f:
                temp_f.write(test_source)
                temp_filename = temp_f.name

            table = StmtLineTable(test_source, temp_filename, strategy=strategy_name)

            # Test cache hit
            start_time = time.time()
            table_cached = StmtLineTable(test_source, temp_filename, strategy=strategy_name)
            end_time = time.time()
            if (end_time - start_time) < 0.01:  # Should be very fast
                print("  PASS: Cache hit was successful and fast.")
            else:
                print(f"  FAIL: Cache hit took too long ({end_time - start_time:.4f}s).")
                all_passed = False

            # Test cache invalidation
            with open(temp_filename, "a") as temp_f:
                temp_f.write("\n# new line\n")
            new_source = test_source + "\n# new line\n"
            table_invalidated = StmtLineTable(new_source, temp_filename, strategy=strategy_name)
            if len(table_invalidated.line_map) > len(table.line_map):
                print("  PASS: Cache was correctly invalidated on file change.")
            else:
                print("  FAIL: Cache was not invalidated on file change.")
                all_passed = False

            os.remove(temp_filename)

            for i, test in enumerate(test_definitions):
                query_snippet = test["query"]
                expected_stmt_snippet = test["expected"]

                # Dynamically determine the line number to query
                query_lineno = find_line_num(source_lines, query_snippet)

                # Dynamically determine the expected line range
                expected_range: Optional[Tuple[int, int]] = None
                if expected_stmt_snippet is not None:
                    expected_range = get_snippet_range(test_source, expected_stmt_snippet)

                # 1. Test get_statement_range
                actual_range = table.get_statement_range(query_lineno)

                test_label = f"Test {i + 1} (line {query_lineno}, query: '{query_snippet[:20]}...')"
                if actual_range == expected_range:
                    print(f"  PASS: {test_label} -> Got range {actual_range}")
                else:
                    print(f"  FAIL: {test_label}")
                    print(f"    - Expected range: {expected_range}")
                    print(f"    - Got range:      {actual_range}")
                    all_passed = False

                # 2. Test get_statement_source
                actual_source = table.get_statement_source(query_lineno)

                # Normalize whitespace for a more robust comparison
                norm_actual = " ".join(actual_source.split()) if actual_source else None
                norm_expected = " ".join(expected_stmt_snippet.split()) if expected_stmt_snippet else None

                if norm_actual == norm_expected:
                    if expected_stmt_snippet:  # Only print PASS for non-None cases
                        print(f"  PASS: {test_label} -> Got correct source")
                else:
                    print(f"  FAIL: {test_label} (source code mismatch)")
                    print(f"    - Expected: {expected_stmt_snippet!r}")
                    print(f"    - Got:      {actual_source!r}")
                    all_passed = False

        except Exception as e:
            print(f"  ERROR: An exception occurred during testing for '{strategy_name}': {e}")
            traceback.print_exc()
            all_passed = False

        print("-" * (34 + len(strategy_name)))
        return all_passed

    import time

    # Run tests for both strategies
    ts_passed = run_tests("tree-sitter")
    ast_passed = run_tests("ast")

    print("\n--- Summary ---")
    if ts_passed and ast_passed:
        print("✅ All strategies passed and are consistent.")
    else:
        print("❌ Some tests failed.")
        exit(1)
