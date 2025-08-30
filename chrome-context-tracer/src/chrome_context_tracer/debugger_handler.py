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
        print("=" * 20 + _("\n Paused on debugger statement ") + "=" * 20)
        reason = params.get("reason")
        call_frames = params.get("callFrames", [])
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

        print("=" * 66)
        print(_("Resuming execution..."))

        try:
            await self.client.send_command("Debugger.resume")
        except Exception as e:
            print(_("Error resuming debugger: {e}", e=e))

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
        location = frame.get("location", {})
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
        print(_("Source Context:"))

        variables = await self._get_variables_from_scope_chain(frame.get("scopeChain", []))
        variables_str = ", ".join(f"{name}: {value}" for name, value in variables.items())

        source_info = await self.get_script_source_info(script_id, line_number, column_number)
        source_code = source_info.get("source")

        if source_code:
            lines = source_code.split("\n")
            script_start_line = script_info.get("scriptInfo", {}).get("startLine", 0)
            relative_line_number = line_number - script_start_line
            start = max(0, relative_line_number - 2)
            end = min(len(lines), relative_line_number + 3)

            for i in range(start, end):
                prefix = "->" if i == relative_line_number else "  "
                line_content = lines[i]

                if i == relative_line_number:
                    if len(line_content.strip()) > 0:
                        line_content += f"    // {variables_str}"
                    else:
                        line_content += f"// {variables_str}"

                print(f" {prefix} {i + script_start_line + 1: >4} | {line_content}")
        else:
            print(_("  [Source code not available]"))
        print("")
