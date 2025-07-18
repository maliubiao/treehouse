import logging
from collections import defaultdict
from typing import Dict, List, Set, Tuple

from tree_sitter import Node

from .expr_types import ExprType
from .node_processor import NodeProcessor

# Configure logging
logger = logging.getLogger(__name__)


class ExpressionExtractor:
    """
    Extracts evaluatable expressions from a source code file using tree-sitter.

    This class walks the Abstract Syntax Tree (AST) generated by tree-sitter
    and identifies nodes that represent expressions useful for debugging, such as
    variable accesses, pointer dereferences, and member accesses.
    """

    def __init__(self):
        self.node_processor = NodeProcessor(self)
        self.source_code: bytes = b""
        # Caches to avoid redundant processing
        self.processed_nodes: Set[int] = set()
        self.added_expressions: Dict[int, Set[Tuple[ExprType, str]]] = defaultdict(set)
        # The final result
        self.results: Dict[int, List[Tuple[ExprType, str, Tuple[int, int, int, int]]]] = defaultdict(list)

    def extract(
        self, root_node: Node, source_code: bytes
    ) -> Dict[int, List[Tuple[ExprType, str, Tuple[int, int, int, int]]]]:
        """
        Extracts all relevant expressions from the given AST.

        Args:
            root_node: The root node of the tree-sitter AST.
            source_code: The source code as bytes.

        Returns:
            A dictionary mapping line numbers (0-indexed) to a list of extracted
            expressions. Each expression is a tuple containing its type, text,
            and position.
        """
        # Reset state for a new extraction
        self.source_code = source_code
        self.processed_nodes.clear()
        self.added_expressions.clear()
        self.results.clear()

        # Start the traversal from the root node
        self.traverse(root_node, source_code)
        return dict(self.results)

    def traverse(self, node: Node | None, source: bytes):
        """
        Recursively traverses the AST.

        For each node, it first checks if a specific handler exists in the
        `NodeProcessor`. If not, it processes the node's children. This
        top-down approach allows handlers to control the traversal of their
        subtrees.

        Args:
            node: The current node to traverse.
            source: The source code as bytes.
        """
        if node is None or node.id in self.processed_nodes:
            return

        # Mark node as processed to prevent infinite loops in cyclic graphs
        # (though ASTs are trees, this is good practice).
        self.mark_processed(node)

        # Let the NodeProcessor decide how to handle this node.
        # If it returns True, it has handled the node and its children.
        if self.node_processor.process(node, source):
            return

        # If no specific handler, traverse children by default.
        for child in node.children:
            self.traverse(child, source)

    def add_expression(self, node: Node, source: bytes, expr_type: ExprType):
        """

        Adds a validated expression to the results.

        This method performs filtering to avoid adding redundant, meaningless,
        or non-evaluatable expressions.

        Args:
            node: The node representing the expression.
            source: The source code as bytes.
            expr_type: The type of the expression.
        """
        # --- Filtering and Validation ---
        expr_text = source[node.start_byte : node.end_byte].decode("utf8").strip()
        if not expr_text:
            return

        # Filter out C/C++ keywords and primitive types
        if self._is_keyword_or_type(expr_text):
            return

        # Filter out expressions that are likely not useful or evaluatable
        if "::" in expr_text:  # Skip fully qualified names with namespaces
            return
        if "operator" in expr_text:  # Skip operator overloads
            return

        # --- Uniqueness Check ---
        start_line = node.start_point[0]
        if (expr_type, expr_text) in self.added_expressions[start_line]:
            return
        self.added_expressions[start_line].add((expr_type, expr_text))

        # --- Add to Results ---
        position = (
            node.start_point[0],
            node.start_point[1],
            node.end_point[0],
            node.end_point[1],
        )
        self.results[start_line].append((expr_type, expr_text, position))
        logger.debug("Extracted: Line %d, Type: %s, Text: '%s'", start_line + 1, expr_type.name, expr_text)

    def mark_processed(self, node: Node):
        """Marks a node and all its descendants as processed."""
        if node is None:
            return

        queue = [node]
        while queue:
            current = queue.pop(0)
            if current.id not in self.processed_nodes:
                self.processed_nodes.add(current.id)
                queue.extend(current.children)

    def _is_keyword_or_type(self, text: str) -> bool:
        """Checks if a given text is a common C/C++ keyword or primitive type."""
        # A set of common keywords and types to filter out.
        # This prevents extracting things like `int` or `for` as variables.
        cxx_keywords = {
            "int",
            "char",
            "float",
            "double",
            "void",
            "bool",
            "short",
            "long",
            "unsigned",
            "signed",
            "size_t",
            "auto",
            "const",
            "volatile",
            "static",
            "extern",
            "register",
            "struct",
            "class",
            "union",
            "enum",
            "typedef",
            "return",
            "if",
            "else",
            "for",
            "while",
            "do",
            "switch",
            "case",
            "default",
            "break",
            "continue",
            "goto",
            "sizeof",
            "new",
            "delete",
            "this",
            "nullptr",
            "true",
            "false",
            "try",
            "catch",
            "throw",
            "namespace",
            "using",
            "template",
            "typename",
            "virtual",
            "public",
            "protected",
            "private",
            "friend",
            "operator",
            "export",
            "explicit",
            "inline",
            "mutable",
            "thread_local",
            "const_cast",
            "static_cast",
            "dynamic_cast",
            "reinterpret_cast",
            "typeid",
        }
        return text in cxx_keywords
