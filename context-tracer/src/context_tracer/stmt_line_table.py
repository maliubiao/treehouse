import ast
import textwrap
from typing import List, Optional, Tuple

# A tuple of "simple" statement node types from the `ast` module.
# Simple statements are those that do not contain a nested block of other
# statements. This list is used to distinguish them from compound statements
# like If, For, While, FunctionDef, ClassDef, Try, etc.
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


class StmtLineTable:
    """
    Parses Python source code to build a mapping from each line number
    to the full multi-line simple statement it belongs to.

    This class is designed to identify self-contained, executable statements,
    such as assignments (`x = ...`), expressions (e.g., function calls), or
    `return` statements. It specifically excludes the structural lines of
    compound statements like `if`, `for`, `try`, `def`, and `class`. The goal
    is to find statements that might be written on a single line but are
    split across multiple lines for readability.

    The analysis is done by walking the Abstract Syntax Tree (AST) of the code.
    It builds a lookup table where each line number maps to the start and end
    lines of the simple statement it is part of. This makes subsequent lookups
    very fast (O(1)).

    For example, in an `if` block, the `if ...:` line itself is not mapped,
    but the statements inside the `if` block's body are.

    Note:
        This relies on `node.end_lineno`, which was added in Python 3.8.

    Attributes:
        source_code (str): The Python source code.
        filename (str): The filename associated with the source code.
        lines (List[str]): The source code split into lines.
        line_map (List[Optional[Tuple[int, int]]]): A list where the index
            `i` corresponds to line `i+1` of the source. The value is a
            tuple `(start_lineno, end_lineno)` for the statement
            containing that line.
    """

    def __init__(self, source_code: str, filename: str = "<string>"):
        """
        Initializes the StmtLineTable and builds the line-to-statement mapping.

        Args:
            source_code: The Python source code to analyze.
            filename: The filename for error reporting during parsing.

        Raises:
            SyntaxError: If the source code is not valid Python.
        """
        self.source_code = source_code
        self.filename = filename
        self.lines = self.source_code.splitlines()
        self.line_map: List[Optional[Tuple[int, int]]] = [None] * len(self.lines)
        self._build_table()

    def _build_table(self):
        """
        Walks the AST of the source code to populate the line_map.

        This method only considers "simple" statements (e.g., assignments,
        expressions, return) and ignores compound statements (e.g., if, for,
        def, class). This is because the goal is to identify self-contained
        executable statements, which may span multiple lines for formatting,
        rather than entire logical blocks.
        """
        try:
            tree = ast.parse(self.source_code, filename=self.filename)
        except SyntaxError as e:
            # Allow initialization even with syntax errors.
            # Queries for lines within valid parts of the code might still be
            # possible if the AST was partially built, but it's safer to
            # assume failure. We print a warning for diagnostics.
            print(f"Warning: SyntaxError in {self.filename}, line map may be incomplete: {e}")
            return

        for node in ast.walk(tree):
            # We only map simple statements, not compound statement blocks.
            if isinstance(node, _SIMPLE_STMT_NODES):
                # All statement nodes have `lineno`.
                # `end_lineno` is available on Python 3.8+
                start_lineno = node.lineno
                end_lineno = getattr(node, "end_lineno", start_lineno)

                # The range is inclusive.
                for line_num in range(start_lineno, end_lineno + 1):
                    # The list is 0-indexed, line numbers are 1-indexed.
                    if 0 <= line_num - 1 < len(self.line_map):
                        self.line_map[line_num - 1] = (start_lineno, end_lineno)

    def get_statement_range(self, lineno: int) -> Optional[Tuple[int, int]]:
        """
        Gets the start and end line numbers of the statement containing the given line.

        Args:
            lineno: The 1-based line number to query.

        Returns:
            A tuple (start_lineno, end_lineno) if the line is part of a
            simple statement, or None if the line is empty, a comment, part of
            a compound statement's structure, or out of bounds.
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
            The source code of the statement as a string, or None if the line
            is not part of a simple statement.
        """
        statement_range = self.get_statement_range(lineno)
        if not statement_range:
            return None

        start_lineno, end_lineno = statement_range
        # Slice from 0-indexed list of lines.
        statement_lines = self.lines[start_lineno - 1 : end_lineno]
        return "\n".join(statement_lines)


# Main block for self-testing and demonstration of the new SourceCacheManager
if __name__ == "__main__":
    # This block now demonstrates the new, improved functionality provided
    # by the SourceCacheManager, which is built on top of StmtLineTable.

    # A dummy decorator for the test source to be syntactically valid.
    def my_decorator(f):
        return f

    test_source = textwrap.dedent(
        """\
    # 1. A simple assignment
    x = 1

    # 4. A multi-line list
    my_list = [
        1, 2, 3,
        4, 5, 6
    ]

    # 10. A function call with multi-line arguments
    print("Hello",
          "World",
          sep=", ")

    # 14. An if/elif/else block
    if x > 0:
        print("positive") # Line 16
    elif x < 0:
        print("negative")
    else:
        print("zero")

    # 21. A multi-line statement using backslashes
    y = 1 + \\
        2 + \\
        3

    # 25. A decorated function
    @my_decorator
    def my_func():
        # 28. A pass statement inside a function
        pass

    # 31. A try-except-finally block
    try:
        result = 1 / x
    except ZeroDivisionError:
        print("Cannot divide by zero")
    finally:
        print("Done.")
    """
    )

    # In a real application, the manager would read from files.
    # For this test, we'll manually add the source to the cache.
    # We must import here to avoid circular dependencies.
    from debugger.source_cache import source_cache_manager

    DUMMY_FILENAME = "test_source.py"
    source_cache_manager.add_source(DUMMY_FILENAME, test_source)

    print("=" * 80)
    print(f"Analyzing source from '{DUMMY_FILENAME}' using the new SourceCacheManager:")
    print("-" * 80)
    print(test_source)
    print("=" * 80)
    print("New Behavior: All lines now return source code.")
    print("Multi-line statements return the full block; others return the single line.")
    print("=" * 80)

    total_lines = len(test_source.splitlines())

    for i in range(1, total_lines + 1):
        source_line = test_source.splitlines()[i - 1].strip()
        if not source_line:
            print(f"Line {i:<2}: (Empty line)")
            continue

        print(f"Line {i:<2}: {source_line}")

        # Use the new global function from the source cache manager
        retrieved_source = source_cache_manager.get_source_for_line(DUMMY_FILENAME, i)

        if retrieved_source:
            INDENTED_SOURCE = textwrap.indent(retrieved_source, "     ")
            print(f"  -> Retrieved Source:\n{INDENTED_SOURCE}")
        else:
            # This should not happen for valid lines with the new manager
            print("  -> Failed to retrieve source.")
        print("-" * 20)
