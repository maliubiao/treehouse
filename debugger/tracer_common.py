import inspect
import re
from typing import TYPE_CHECKING, Any
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


def _truncate_sequence(value, keep_elements):
    if len(value) <= keep_elements:
        return repr(value)
    keep_list = []
    for i in range(keep_elements):
        keep_list.append(value[i])
    return f"{repr(keep_list)[:-1]} ...]"


def _truncate_dict(value, keep_elements):
    if len(value) <= keep_elements:
        return repr(value)
    keep_dict = {}
    i = keep_elements
    it = iter(value)
    while i > 0 and value:
        key = next(it)
        keep_dict[key] = value[key]
        i -= 1
    s = repr(keep_dict)
    return "%s ...}" % s[:-1]


def _truncate_object(value, keep_elements):
    if len(value.__dict__) <= keep_elements:
        return f"{type(value).__name__}.({repr(value.__dict__)})"
    keep_attrs = {}
    i = keep_elements
    it = iter(value.__dict__)
    while i > 0 and value.__dict__:
        key = next(it)
        keep_attrs[key] = value.__dict__[key]
        i -= 1
    s = repr(keep_attrs)
    return f"{type(value).__name__}(%s ...)" % s[:-1]


def truncate_repr_value(value: Any, keep_elements: int = 10) -> str:
    """
    Intelligently truncates a value and creates a suitable string representation for it,
    while preserving key type information.

    This function is specifically tuned to handle strings correctly, avoiding the
    "double-quoting" issue caused by applying `repr()` to a value that is already a string.

    Args:
        value: The value to be represented.
        keep_elements: The maximum number of elements to keep for sequences and dicts.

    Returns:
        A truncated string representation suitable for logging and code generation.
    """
    preview = "..."
    try:
        # [FIX] Explicitly handle strings to prevent double-quoting by `repr()`.
        # This is a common case and should be checked first for performance.
        # Handle primitive and special types
        if isinstance(value, str):
            if len(value) > _MAX_VALUE_LENGTH:
                half = _MAX_VALUE_LENGTH // 2
                omitted = len(value) - 2 * half
                return value[:half] + "..." + value[-half:] + f" (total length: {len(value)}, omitted: {omitted})"
            return value
        # Detect unittest.mock.Mock objects
        elif isinstance(value, Mock):
            # Provide a more informative representation for mock objects.
            try:
                name_part = f"name='{value._extract_mock_name()}'"
            except AttributeError:
                name_part = ""
            spec_part = f"spec={value.__class__}"
            preview = f"mock.Mock({', '.join(filter(None, [name_part, spec_part]))})"
        elif isinstance(value, (list, tuple)):
            preview = _truncate_sequence(value, keep_elements)
        elif isinstance(value, dict):
            preview = _truncate_dict(value, keep_elements)
        # For other objects with a custom __repr__, use it as it's the developer's intended representation.
        elif hasattr(value, "__repr__") and value.__repr__.__qualname__ != "object.__repr__":
            preview = repr(value)
        # As a fallback, use __str__ if it's customized.
        elif hasattr(value, "__str__") and value.__str__.__qualname__ != "object.__str__":
            preview = str(value)
        # For simple objects, show their structure.
        elif hasattr(value, "__dict__"):
            if inspect.ismodule(value):
                return f"<module '{value.__name__}'>"
            if inspect.isclass(value):
                return f"<class '{getattr(value, '__module__', '?')}.{value.__name__}'>"
            preview = _truncate_object(value, keep_elements)
        # The final fallback is the default repr().
        # Functions, methods, and other callables
        elif callable(value):
            s = repr(value)
            # General cleanup for callables
            s = re.sub(r"\s+at\s+0x[0-9a-fA-F]+", "", s)
            s = re.sub(r"\s+of\s+<class\s+'.*?'>", "", s)
            if len(s) > _MAX_VALUE_LENGTH:
                s = s[:_MAX_VALUE_LENGTH] + "..."
            return s
        else:
            preview = repr(value)
    except Exception as e:
        # Catch any error during representation generation to prevent the tracer from crashing.
        preview = f"[trace system error: {e}]"
    # Perform a final length check on all generated previews.
    if len(preview) > _MAX_VALUE_LENGTH:
        preview = preview[:_MAX_VALUE_LENGTH] + "..."
    return preview
