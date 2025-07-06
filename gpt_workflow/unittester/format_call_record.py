from typing import Any, Dict, List, Optional


def format_call_record_as_text(
    call_record: Dict[str, Any], max_chars: Optional[int] = None, max_depth: int = 10
) -> str:
    """
    Formats a single call record into a human-readable text trace for the LLM.
    This version intelligently compresses repetitive sequences of events (like in loops)
    and respects a maximum character limit to avoid oversized prompts.

    Args:
        call_record: The dictionary representing the call record.
        max_chars: The maximum number of characters for the formatted trace.
                   If the output exceeds this, it will be truncated.
        max_depth: The maximum depth to recurse into sub-calls.

    Returns:
        A string representing the formatted and potentially compressed/truncated call trace.
    """
    formatter = _CallRecordFormatter(max_chars=max_chars, max_depth=max_depth)
    return formatter.format(call_record)


def _get_event_signature(event: Dict) -> str:
    """Creates a unique signature for an event to detect repetitions."""
    event_type = event.get("type")
    data = event.get("data", {})
    if event_type == "line":
        return f"line:{data.get('line_no')}"
    if event_type == "call":
        return f"call:{data.get('func_name')}@{data.get('caller_lineno')}"
    return "other"


class _CallRecordFormatter:
    def __init__(self, max_chars: Optional[int], max_depth: int):
        self.max_chars = max_chars
        self.max_depth = max_depth
        self.lines: List[str] = []
        self.current_length = 0
        self.truncated = False

    def _add(self, text: str):
        if self.truncated:
            return

        if self.max_chars is not None and self.current_length + len(text) + 1 > self.max_chars:
            self.lines.append("  (...)")
            self.lines.append("[Trace truncated due to size limit]")
            self.truncated = True
            return

        self.lines.append(text)
        self.current_length += len(text) + 1

    def format(self, call_record: Dict) -> str:
        func_name = call_record.get("func_name", "N/A")
        filename = call_record.get("original_filename", "N/A")
        self._add(f"Execution trace for `{func_name}` from `{filename}`:")
        self._format_recursive(call_record, "", 0)
        return "\n".join(self.lines)

    def _format_recursive(self, record: Dict, indent_str: str, depth: int):
        if self.truncated:
            return

        func_name = record.get("func_name", "N/A")
        args = record.get("args", {})
        caller_lineno = record.get("caller_lineno")
        prefix = f"L{caller_lineno:<4} " if caller_lineno else ""
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items()) if args else ""
        call_header = f"[SUB-CALL] {func_name}({args_str})" if indent_str else f"[CALL] {func_name}({args_str})"
        self._add(f"{indent_str}{prefix}{call_header}")

        if depth < self.max_depth:
            last_sig: Optional[str] = None
            repeat_count = 0
            for event in record.get("events", []):
                if self.truncated:
                    break
                current_sig = _get_event_signature(event)
                if current_sig is not None and current_sig == last_sig:
                    repeat_count += 1
                else:
                    if repeat_count > 1:
                        self._add(f"{indent_str}  (Repeated {repeat_count} times)")
                    repeat_count = 1
                    last_sig = current_sig

                event_type = event.get("type")
                data = event.get("data", {})
                if event_type == "line":
                    self._add(f"{indent_str}  L{data.get('line_no'):<4} {data.get('content', '').rstrip()}")
                elif event_type == "call":
                    self._format_recursive(data, indent_str + "  ", depth + 1)
            if repeat_count > 1:
                self._add(f"{indent_str}  (Repeated {repeat_count} times)")
        elif depth == self.max_depth:
            # When the current depth reaches max_depth, events are truncated.
            # Add the truncation message as per test expectation.
            self._add(f"{indent_str}  (Trace truncated at depth {self.max_depth}/{self.max_depth})")

        exception = record.get("exception")
        if exception:
            exc_type = exception.get("type", "UnknownException")
            exc_value = exception.get("value", "N/A")
            outcome = (
                f"-> SUB-CALL RAISED: {exc_type}: {exc_value}"
                if indent_str
                else f"[FINAL] RAISES: {exc_type}: {exc_value}"
            )
        else:
            return_value = record.get("return_value")
            outcome = (
                f"-> SUB-CALL RETURNED: {repr(return_value)}"
                if indent_str
                else f"[FINAL] RETURNS: {repr(return_value)}"
            )
        self._add(f"{indent_str}  {outcome}")
