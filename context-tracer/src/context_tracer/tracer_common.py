import inspect
import re
from itertools import islice
from typing import TYPE_CHECKING, Any, Union
from unittest.mock import Mock

if TYPE_CHECKING:
    from unittest.mock import Mock

# Constants
_MAX_VALUE_LENGTH = 256
_MAX_SEQ_ITEMS = 10


class TraceTypes:
    """Trace event and message type constants"""

    # Event types
    CALL = "call"
    RETURN = "return"
    LINE = "line"
    EXCEPTION = "exception"
    MODULE = "module"

    # Message types
    ERROR = "error"
    TRACE = "trace"
    VAR = "var"

    # Color types
    COLOR_CALL = "call"
    COLOR_RETURN = "return"
    COLOR_VAR = "var"
    COLOR_LINE = "line"
    COLOR_ERROR = "error"
    COLOR_TRACE = "trace"
    COLOR_RESET = "reset"
    COLOR_EXCEPTION = "exception"  # For consistency with event types
    COLOR_DEBUG = "debug"

    # Log prefixes
    PREFIX_CALL = "CALL"
    PREFIX_RETURN = "RETURN"
    PREFIX_MODULE = "MODULE"
    PREFIX_EXCEPTION = "EXCEPTION"

    # HTML classes
    HTML_CALL = "call"
    HTML_RETURN = "return"
    HTML_ERROR = "error"
    HTML_LINE = "line"
    HTML_TRACE = "trace"
    HTML_VAR = "var"


def _truncate_sequence(value: Union[list, tuple], keep_elements: int, safe: bool, max_depth: int, _depth: int) -> str:
    """Helper to truncate list or tuple representations."""
    is_tuple = isinstance(value, tuple)
    open_bracket, close_bracket = ("(", ")") if is_tuple else ("[", "]")

    if len(value) <= keep_elements:
        items_to_render = value
        suffix = ""
    else:
        items_to_render = value[:keep_elements]
        suffix = ", ..."

    # Recursively call truncate_repr_value for each item.
    # The 'safe' flag is important for nested structures to avoid side-effects.
    rendered_items = [
        truncate_repr_value(item, keep_elements=keep_elements, safe=safe, max_depth=max_depth, _depth=_depth + 1)
        for item in items_to_render
    ]

    body = ", ".join(rendered_items)

    # Handle trailing comma for single-element tuples
    if is_tuple and len(value) == 1:
        body += ","

    return f"{open_bracket}{body}{suffix}{close_bracket}"


def _truncate_dict(value: dict, keep_elements: int, safe: bool, max_depth: int, _depth: int) -> str:
    """Helper to truncate dict representations."""
    if len(value) <= keep_elements:
        items_to_render = value.items()
        suffix = ""
    else:
        items_to_render = islice(value.items(), keep_elements)
        suffix = ", ..."

    rendered_items = []
    for k, v in items_to_render:
        # Recursively call for both key and value
        k_repr = truncate_repr_value(k, keep_elements=keep_elements, safe=safe, max_depth=max_depth, _depth=_depth + 1)
        v_repr = truncate_repr_value(v, keep_elements=keep_elements, safe=safe, max_depth=max_depth, _depth=_depth + 1)
        rendered_items.append(f"{k_repr}: {v_repr}")

    body = ", ".join(rendered_items)
    return f"{{{body}{suffix}}}"


def _truncate_object(value: object, keep_elements: int, safe: bool, max_depth: int, _depth: int) -> str:
    """Helper to truncate object attribute representations."""
    attributes = getattr(value, "__dict__", {})
    if not attributes:
        return repr(value)  # Fallback for objects without __dict__

    class_name = type(value).__name__

    # Check if all keys are valid identifiers to use `key=value` format.
    all_keys_are_identifiers = all(isinstance(k, str) and k.isidentifier() for k in attributes)

    if not all_keys_are_identifiers:
        # Fallback to a dict representation of attributes, suggesting **kwargs.
        dict_repr = _truncate_dict(attributes, keep_elements, safe, max_depth, _depth + 1)
        return f"{class_name}(**{dict_repr})"

    # All keys are identifiers, so we can use `key=value` format.
    if len(attributes) <= keep_elements:
        items_to_render = attributes.items()
        suffix = ""
    else:
        items_to_render = islice(attributes.items(), keep_elements)
        suffix = ", ..."

    rendered_items = []
    for k, v in items_to_render:
        # Key is already known to be a string and identifier.
        v_repr = truncate_repr_value(v, keep_elements=keep_elements, safe=True, max_depth=max_depth, _depth=_depth + 1)
        rendered_items.append(f"{k}={v_repr}")

    body = ", ".join(rendered_items)
    return f"{class_name}({body}{suffix})"


def truncate_repr_value(
    value: Any, keep_elements: int = 10, safe: bool = False, max_depth: int = 2, _depth: int = 1
) -> str:
    """
    Intelligently truncates a value and creates a suitable string representation for it,
    while preserving key type information. It prevents infinite recursion by limiting
    the depth of nested structures.

    This function is specifically tuned to handle strings correctly, avoiding the
    "double-quoting" issue caused by applying `repr()` to a value that is already a string.

    Args:
        value: The value to be represented.
        keep_elements: The maximum number of elements to keep for sequences and dicts.
        safe: If True, avoids calling custom __repr__ or __str__ methods on objects
              to prevent side effects.
        max_depth: The maximum recursion depth for nested structures.
        _depth: Internal counter for the current recursion depth.
    """
    if inspect.isframe(value):
        return "<frame object>"

    # If not in safe mode, or if it's a whitelisted type, proceed with the full logic.
    preview = "..."
    try:
        if isinstance(value, str):
            if len(value) > _MAX_VALUE_LENGTH:
                half = _MAX_VALUE_LENGTH // 2
                omitted = len(value) - 2 * half
                # Use single quotes for consistency with repr()
                return repr(value[:half] + value[-half:]) + f" (total length: {len(value)}, omitted: {omitted})"
            return repr(value)
        elif isinstance(value, (bool, int, float)):
            return repr(value)
        elif callable(value):
            if hasattr(value, "__code__"):
                return f"callable: {str(inspect.signature(value))}"
            if inspect.isbuiltin(value):
                return f"builtin callable: {value.__name__}"
        # Detect unittest.mock.Mock objects
        elif isinstance(value, Mock):
            # Provide a more informative representation for mock objects.
            try:
                # _extract_mock_name() is an internal API of unittest.mock but quite stable and useful.
                name_part = f"name='{value._extract_mock_name()}'"
            except AttributeError:
                name_part = ""
            # The default repr() for MagicMock with a spec can cause recursion errors.
            # We create a safe, simplified representation instead.
            spec_class = getattr(value, "_spec_class", None)
            spec_part = f"spec={getattr(spec_class, '__name__', '(unknown)')}" if spec_class is not None else ""
            preview = f"mock.Mock({', '.join(filter(None, [name_part, spec_part]))})"
        elif isinstance(value, (list, tuple)):
            if _depth >= max_depth:
                return "[...]"
            preview = _truncate_sequence(value, keep_elements, safe, max_depth, _depth)
        elif isinstance(value, dict):
            if _depth >= max_depth:
                return "{...}"
            preview = _truncate_dict(value, keep_elements, safe, max_depth, _depth)
        # For other objects with a custom __repr__, use it as it's the developer's intended representation.
        elif hasattr(value, "__repr__") and value.__repr__.__qualname__ != "object.__repr__":
            if not safe:
                preview = repr(value)
            else:
                # In safe mode, we've detected a custom __repr__ but we will not call it
                # to avoid side effects. Provide a generic representation instead.
                preview = f"<{type(value).__name__} object>"
        # As a fallback, use __str__ if it's customized.
        elif hasattr(value, "__str__") and value.__str__.__qualname__ != "object.__str__":
            if not safe:
                preview = str(value)
            else:
                # In safe mode, we've detected a custom __str__ but we will not call it.
                preview = f"<{type(value).__name__} object>"
        # For simple objects, show their structure.
        elif hasattr(value, "__dict__"):
            if inspect.ismodule(value):
                return f"<module '{value.__name__}'>"
            if inspect.isclass(value):
                return f"<class '{getattr(value, '__module__', '?')}.{value.__name__}'>"
            if _depth >= max_depth:
                return "..."
            preview = _truncate_object(value, keep_elements, safe, max_depth, _depth)
        else:
            preview = repr(value)
    except Exception as e:
        # Catch any error during representation generation to prevent the tracer from crashing.
        preview = f"[trace system error: {e}]"
    # Perform a final length check on all generated previews.
    if len(preview) > _MAX_VALUE_LENGTH:
        preview = preview[:_MAX_VALUE_LENGTH] + "..."
    return preview
