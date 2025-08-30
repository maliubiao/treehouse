#!/usr/bin/env python3
"""
CDP Debugger Handler - Manages script parsing, debugger events, and source code retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from .i18n import _

if TYPE_CHECKING:
    from .cdp_client import DOMInspector


class DebuggerHandler:
    """Handles logic related to the CDP Debugger domain."""

    def __init__(self, client: "DOMInspector"):
        """
        Initializes the DebuggerHandler.

        Args:
            client: The main DOMInspector client instance.
        """
        self.client = client
        self._initial_pause_handled: bool = False

    async def handle_script_parsed(self, params: Dict[str, Any]) -> None:
        """Process Debugger.scriptParsed events and cache script metadata."""
        script_id = params.get("scriptId")
        if not script_id:
            return

        url = params.get("url", "")

        # Use the full URL for display if available, as it provides more context than just the basename.
        # If no URL is provided, it's likely an inline or dynamically evaluated script.
        filename = url if url else _("Inline Script (ID: {script_id})", script_id=script_id)

        self.client.script_cache.setdefault(script_id, {})
        self.client.script_cache[script_id].update(
            {
                "url": url,
                "filename": filename,
                "scriptInfo": params,
            }
        )

    async def get_script_source_info(self, script_id: str, line_number: int, column_number: int) -> Dict[str, Any]:
        """Get script source information, using cache first."""
        cached_data = self.client.script_cache.get(script_id, {})

        base_info: Dict[str, Any] = {
            "scriptId": script_id,
            "lineNumber": line_number,
            "columnNumber": column_number,
        }

        if "source" in cached_data:
            return {**base_info, **cached_data}

        try:
            response = await self.client.send_command("Debugger.getScriptSource", {"scriptId": script_id})
            if "error" in response:
                error_msg = response["error"].get("message", "Unknown error")
                self.client.script_cache.setdefault(script_id, {}).update({"error": error_msg, "source": None})
                return {**base_info, **cached_data, "source": None, "error": error_msg}

            script_source = response["result"]["scriptSource"]
            self.client.script_cache.setdefault(script_id, {}).update({"source": script_source})
            final_data = self.client.script_cache.get(script_id, {})
            return {**base_info, **final_data}
        except (ConnectionError, TimeoutError):
            # These are critical errors that indicate the connection is lost.
            # They should not be swallowed. Let them propagate to the main loop.
            raise
        except Exception as e:
            # Other errors (e.g., script not found) can be handled gracefully.
            error_str = str(e)
            self.client.script_cache.setdefault(script_id, {}).update({"error": error_str, "source": None})
            return {**base_info, **cached_data, "source": None, "error": error_str}

    async def handle_debugger_paused(self, params: Dict[str, Any]) -> None:
        """Process Debugger.paused events, printing call stack and variable info."""
        # Handle the initial pause when attaching to a Node.js process started with --inspect-brk
        if self.client.is_node_target and not self._initial_pause_handled:
            self.client.did_receive_initial_node_pause = True
            print(_("\nDebugger attached. Node.js process is paused at the start."))
            call_frames_list = params.get("callFrames", [])
            if call_frames_list:
                frame = call_frames_list[0]
                location = frame.get("location", {})
                script_id = location.get("scriptId")
                line = location.get("lineNumber", 0) + 1
                script_info = self.client.script_cache.get(script_id, {})
                filename = script_info.get("filename", f"scriptId:{script_id}")
                print(_("Paused at: {filename}:{line}", filename=filename, line=line))

            # Automatically resume execution for a non-interactive experience
            self._initial_pause_handled = True
            await self.client.resume_debugger()
            print(_("Execution resumed."))
            return

        reason = params.get("reason")
        call_frames = params.get("callFrames", [])

        # Custom header based on pause reason
        header_text = ""
        if reason == "exception":
            header_text = _(" Paused on exception ")
        elif reason == "debuggerStatement":
            header_text = _(" Paused on 'debugger' statement ")
        else:
            header_text = _(" Debugger paused ")

        print(f"\n{'=' * 20}{header_text}{'=' * 20}")

        if reason == "exception":
            exception_data = params.get("data", {})
            if exception_data and "description" in exception_data:
                # The description can be multi-line, just show the first line (the error message)
                error_message = exception_data["description"].split("\n")[0]
                print(_("Exception: {error_message}", error_message=error_message))

        print(_("Reason: {reason}\n", reason=reason))

        print(_("--- Stack Trace ---"))
        for i, frame in enumerate(call_frames):
            func_name = frame.get("functionName") or "(anonymous)"
            location = frame.get("location", {})
            script_id = location.get("scriptId")
            line = location.get("lineNumber", 0) + 1
            col = location.get("columnNumber", 0) + 1
            script_info = self.client.script_cache.get(script_id, {})
            filename = script_info.get("filename", f"scriptId:{script_id}")
            print(f"  [{i}] {func_name} at {filename}:{line}:{col}")
        print("")

        for i, frame in enumerate(call_frames):
            await self._process_and_print_call_frame(frame, i)

        print("=" * (42 + len(header_text)))
        print(_("Resuming execution..."))

        await self.client.resume_debugger()

    async def _get_variables_from_scope_chain(self, scope_chain: List[Dict[str, Any]]) -> Dict[str, str]:
        """Extract local and closure variables from a scope chain."""
        variables: Dict[str, str] = {}
        for scope in scope_chain:
            scope_type = scope.get("type")
            if scope_type in ["local", "closure"]:
                scope_object = scope.get("object", {})
                object_id = scope_object.get("objectId")
                if object_id:
                    try:
                        props_response = await self.client.send_command(
                            "Runtime.getProperties", {"objectId": object_id, "ownProperties": True}
                        )
                        for prop in props_response.get("result", {}).get("result", []):
                            name = prop.get("name")
                            value_obj = prop.get("value", {})
                            description = value_obj.get("description", str(value_obj.get("value", "N/A")))
                            if name:
                                variables[name] = description
                    except Exception as e:
                        print(
                            _(
                                "Warning: Could not get variables for scope {scope_type}: {e}",
                                scope_type=scope_type,
                                e=e,
                            )
                        )
        return variables

    async def _process_and_print_call_frame(self, frame: Dict[str, Any], frame_index: int) -> None:
        """Process a single call frame: get source, variables, and format output."""
        func_name = frame.get("functionName") or "(anonymous)"
        # Handle different callFrame structures:
        # - Debugger.paused: has a nested 'location' object.
        # - Runtime.exceptionThrown: has location info at the top level of the frame.
        # We use the frame itself as a fallback if 'location' is not found.
        location = frame.get("location", frame)
        script_id = location.get("scriptId")
        line_number = location.get("lineNumber", 0)
        column_number = location.get("columnNumber", 0)

        script_info = self.client.script_cache.get(script_id, {})
        filename = script_info.get("filename", f"scriptId:{script_id}")

        print(
            _(
                "--- Frame {frame_index}: {func_name} ({filename}:{line_number}:{column_number}) ---",
                frame_index=frame_index,
                func_name=func_name,
                filename=filename,
                line_number=line_number + 1,
                column_number=column_number + 1,
            )
        )

        variables = await self._get_variables_from_scope_chain(frame.get("scopeChain", []))

        # Truncate variables string for readability
        MAX_VARS_LENGTH = 250
        variables_str = ", ".join(f"{name}: {value}" for name, value in variables.items())
        if len(variables_str) > MAX_VARS_LENGTH:
            variables_str = variables_str[:MAX_VARS_LENGTH] + "..."

        print(_("Source Context:"))

        source_info = await self.get_script_source_info(script_id, line_number, column_number)
        source_code = source_info.get("source")

        if source_code:
            lines = source_code.split("\n")
            script_start_line = script_info.get("scriptInfo", {}).get("startLine", 0)
            relative_line_number = line_number - script_start_line
            start = max(0, relative_line_number - 2)
            end = min(len(lines), relative_line_number + 3)

            MAX_LINE_LENGTH = 400
            CONTEXT_CHARS = 80

            for i in range(start, end):
                prefix = "->" if i == relative_line_number else "  "

                if i < 0 or i >= len(lines):
                    continue

                line_content = lines[i]

                # Current line of execution
                if i == relative_line_number:
                    # Handle very long lines (minified code)
                    if len(line_content) > MAX_LINE_LENGTH:
                        start_col = max(0, column_number - CONTEXT_CHARS)
                        end_col = column_number + CONTEXT_CHARS
                        snippet = line_content[start_col:end_col]
                        prefix_indicator = "..." if start_col > 0 else ""
                        suffix_indicator = "..." if end_col < len(line_content) else ""
                        line_to_print = f"{prefix_indicator}{snippet}{suffix_indicator}"

                        if variables_str:
                            line_to_print += f"    // {variables_str}"
                        print(f" {prefix} {i + script_start_line + 1: >4} | {line_to_print}")

                        print(
                            _(
                                "         | ... (line truncated, showing snippet around column {col_num}) ...",
                                col_num=column_number + 1,
                            )
                        )
                    # Handle normal length lines
                    else:
                        line_to_print = line_content
                        if variables_str:
                            if len(line_to_print.strip()) > 0:
                                line_to_print += f"    // {variables_str}"
                            else:
                                line_to_print = f"// {variables_str}"
                        print(f" {prefix} {i + script_start_line + 1: >4} | {line_to_print}")

                # Context lines
                else:
                    if len(line_content) > MAX_LINE_LENGTH:
                        line_to_print = line_content[:MAX_LINE_LENGTH] + "..."
                    else:
                        line_to_print = line_content
                    print(f" {prefix} {i + script_start_line + 1: >4} | {line_to_print}")
        else:
            print(_("  [Source code not available]"))
        print("")

    async def handle_exception_thrown(self, params: Dict[str, Any]) -> None:
        """Process Runtime.exceptionThrown events, printing call stack and source."""
        exception_details = params.get("exceptionDetails")
        if not exception_details:
            return

        exception_obj = exception_details.get("exception", {})
        # Get the first line of the description, which is usually the error message.
        exception_desc = exception_obj.get("description", "No description").split("\n")[0]
        header = _("💥 Unhandled Exception Caught 💥")

        print(f"\n{'=' * 20}{header}{'=' * 20}")
        print(f"  {exception_desc}\n")

        stack_trace = exception_details.get("stackTrace")
        if not stack_trace or not stack_trace.get("callFrames"):
            print(_("  [No stack trace available]"))
            print("=" * (40 + len(header)))
            return

        call_frames = stack_trace.get("callFrames", [])

        print(_("--- Stack Trace ---"))
        for i, frame in enumerate(call_frames):
            func_name = frame.get("functionName") or "(anonymous)"
            # `exceptionThrown` frames have location info at the top level.
            # Use `frame` as the source for location data.
            location = frame
            script_id = location.get("scriptId")
            line = location.get("lineNumber", 0) + 1
            col = location.get("columnNumber", 0) + 1
            script_info = self.client.script_cache.get(script_id, {})
            filename = script_info.get("filename", f"scriptId:{script_id}")
            print(f"  [{i}] {func_name} at {filename}:{line}:{col}")
        print("")

        for i, frame in enumerate(call_frames):
            # The `callFrames` from Runtime.exceptionThrown do NOT contain a `scopeChain`.
            # Our `_process_and_print_call_frame` gracefully handles this by not showing variables.
            await self._process_and_print_call_frame(frame, i)

        print("=" * (40 + len(header)))
