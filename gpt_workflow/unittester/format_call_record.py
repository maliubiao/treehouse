from typing import Any, Dict


def format_call_record_as_text(call_record: Dict[str, Any], max_depth: int = 2) -> str:
    """
    Formats a single call record into a human-readable text trace for the LLM.
    This version correctly represents the nested structure and final outcomes,
    with an added `max_depth` parameter to control recursion depth.

    Args:
        call_record: The dictionary representing the call record.
        max_depth: The maximum depth to recurse into sub-calls.
                   A depth of 0 means only the top-level call header and final outcome
                   will be shown. A depth of 1 means direct sub-calls will be expanded,
                   but their internal details (lines, further sub-sub-calls) will be truncated.

    Returns:
        A string representing the formatted call trace.
    """
    trace_lines = []

    def _format_recursive(record: Dict, indent_str: str, current_depth: int, max_depth: int):
        # 1. Print the entry point of this specific record
        func_name = record.get("func_name", "N/A")
        args = record.get("args", {})
        caller_lineno = record.get("caller_lineno")
        prefix = f"L{caller_lineno:<4} " if caller_lineno else ""

        args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items()) if args else ""
        call_header = f"[SUB-CALL] {func_name}({args_str})" if indent_str else f"[CALL] {func_name}({args_str})"
        trace_lines.append(f"{indent_str}{prefix}{call_header}")

        # 2. Iterate through the internal events of this record, if within max_depth
        if current_depth < max_depth:
            for event in record.get("events", []):
                event_type = event.get("type")
                data = event.get("data", {})

                if event_type == "line":
                    line_no, content = data.get("line_no"), data.get("content", "").rstrip()
                    trace_lines.append(f"{indent_str}  L{line_no:<4} {content}")
                elif event_type == "call":
                    # If a sub-call event is found, recurse with incremented depth
                    _format_recursive(data, indent_str + "  ", current_depth + 1, max_depth)
        else:
            # If max_depth is reached or exceeded, indicate truncation (optional, but good for clarity)
            trace_lines.append(f"{indent_str}  (Trace truncated at depth {current_depth}/{max_depth})")

        # 3. Print the final outcome of this specific record
        exception = record.get("exception")
        if exception:
            exc_type = exception.get("type", "UnknownException")
            exc_value = exception.get("value", "N/A")
            outcome = (
                f"-> SUB-CALL RAISED: {exc_type}: {exc_value}"
                if indent_str
                else f"[FINAL] RAISES: {exc_type}: {exc_value}"
            )
            trace_lines.append(f"{indent_str}  {outcome}")
        else:
            return_value = record.get("return_value")
            outcome = (
                f"-> SUB-CALL RETURNED: {repr(return_value)}"
                if indent_str
                else f"[FINAL] RETURNS: {repr(return_value)}"
            )
            trace_lines.append(f"{indent_str}  {outcome}")

    # Start the formatting from the top-level record with initial depth 0
    func_name = call_record.get("func_name", "N/A")
    original_filename = call_record.get("original_filename", "N/A")
    trace_lines.append(f"Execution trace for `{func_name}` from `{original_filename}`:")
    _format_recursive(call_record, "", 0, max_depth)

    # Clean up the output slightly for better prompt injection
    return "\n".join(line.rstrip() for line in trace_lines).replace("\n  \n", "\n")
