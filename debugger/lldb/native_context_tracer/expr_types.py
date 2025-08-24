from enum import Enum, auto


class ExprType(Enum):
    """
    Defines the types of expressions that can be extracted from source code.
    This categorization helps in deciding which expressions are suitable for
    evaluation in LLDB.
    """

    # --- Core Value-producing Expressions ---
    VARIABLE_ACCESS = auto()  # Accessing a variable, e.g., `my_var`
    POINTER_DEREF = auto()  # Dereferencing a pointer, e.g., `*ptr`
    ADDRESS_OF = auto()  # Taking the address of a variable, e.g., `&var`
    MEMBER_ACCESS = auto()  # Accessing a member of a struct/class, e.g., `obj.field`, `ptr->field`
    SUBSCRIPT_EXPRESSION = auto()  # Array or container access, e.g., `arr[i]`

    # --- Contextual Expressions ---
    ASSIGNMENT_TARGET = auto()  # The left-hand side of an assignment, e.g., `x` in `x = 10`
    TEMPLATE_INSTANCE = auto()  # A C++ template instantiation, e.g., `MyClass<int>` (for filtering)

    def __str__(self):
        return self.name


class ExprTypeHandler:
    """
    Maps tree-sitter node types to our simplified ExprType enumeration.
    This acts as a bridge between the raw AST and our internal representation.
    """

    # A mapping from tree-sitter's node type strings to our ExprType enum.
    # This list is curated to focus on expressions that are valuable for debugging.
    EXPR_TYPES = {
        # Identifiers are the most common form of variable access.
        "identifier": ExprType.VARIABLE_ACCESS,
        "field_identifier": ExprType.VARIABLE_ACCESS,  # e.g., the `field` in `obj.field`
        "qualified_identifier": ExprType.VARIABLE_ACCESS,  # e.g., `namespace::variable`
        # Pointer and memory operations.
        "pointer_expression": ExprType.POINTER_DEREF,
        "address_expression": ExprType.ADDRESS_OF,
        # Accessing members of aggregates.
        "field_expression": ExprType.MEMBER_ACCESS,
        "subscript_expression": ExprType.SUBSCRIPT_EXPRESSION,
        # Contextual types for special handling.
        "assignment_expression": ExprType.ASSIGNMENT_TARGET,
    }

    @staticmethod
    def get_expr_type(node_type: str) -> ExprType | None:
        """
        Retrieves the corresponding ExprType for a given tree-sitter node type.

        Args:
            node_type: The `type` attribute of a tree-sitter Node.

        Returns:
            The matching ExprType, or None if no mapping exists.
        """
        return ExprTypeHandler.EXPR_TYPES.get(node_type)
