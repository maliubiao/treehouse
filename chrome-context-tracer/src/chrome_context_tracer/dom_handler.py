#!/usr/bin/env python3
"""
CDP DOM Handler - Manages DOM/CSS inspection, element selection, and JS interaction.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from .i18n import _
from .utils import get_mouse_detector_js

if TYPE_CHECKING:
    from .cdp_client import DOMInspector


class DOMHandler:
    """Handles logic related to DOM, CSS, and element inspection."""

    def __init__(self, client: "DOMInspector"):
        """
        Initializes the DOMHandler.

        Args:
            client: The main DOMInspector client instance.
        """
        self.client = client
        self.element_selection_result: Optional[Any] = None
        self.original_console_handler: Optional[Callable[..., Any]] = None

    async def handle_style_sheet_added(self, params: Dict[str, Any]) -> None:
        """Process CSS.styleSheetAdded events and cache stylesheet headers."""
        header = params.get("header")
        if header and "styleSheetId" in header:
            self.client.stylesheet_headers[header["styleSheetId"]] = header

    async def find_element(self, selector: str) -> Optional[int]:
        """Find an element by CSS selector, returning its nodeId."""
        response = await self.client.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]
        response = await self.client.send_command("DOM.querySelector", {"nodeId": root_node_id, "selector": selector})
        return response["result"]["nodeId"]

    async def get_element_styles(self, node_id: int) -> Dict[str, Any]:
        """Get the complete style information for an element."""
        response = await self.client.send_command("CSS.getMatchedStylesForNode", {"nodeId": node_id})
        if "error" in response:
            print(_("CSS.getMatchedStylesForNode error: {error}", error=response["error"]))
            return {}
        return response.get("result", {})

    def _format_node_description(self, node_data: Dict[str, Any], is_target: bool = False) -> str:
        """Format a readable description of a DOM node."""
        if is_target:
            return _("Selected Element")
        if not node_data:
            return _("unknown ancestor")

        node_name = node_data.get("localName", node_data.get("nodeName", "unknown")).lower()
        if node_name.startswith("#"):
            return node_name

        attributes = node_data.get("attributes", [])
        attrs_dict = dict(zip(attributes[::2], attributes[1::2]))

        desc = node_name
        if "id" in attrs_dict and attrs_dict["id"]:
            desc += f"#{attrs_dict['id']}"
        if "class" in attrs_dict and attrs_dict["class"]:
            class_list = attrs_dict["class"].strip().split()
            if class_list:
                desc += "." + ".".join(class_list)
        return desc

    async def get_element_event_listeners(self, node_id: int) -> List[Dict[str, Any]]:
        """Get event listeners for an element, its ancestors, and the window object."""
        all_listeners: List[Dict[str, Any]] = []
        object_ids_to_release: List[str] = []

        try:
            resolve_response = await self.client.send_command("DOM.resolveNode", {"nodeId": node_id})
            current_object_id = resolve_response.get("result", {}).get("object", {}).get("objectId")
            is_target_node = True

            while current_object_id:
                object_ids_to_release.append(current_object_id)
                try:
                    listeners_response = await self.client.send_command(
                        "DOMDebugger.getEventListeners", {"objectId": current_object_id}
                    )
                    listeners = listeners_response.get("result", {}).get("listeners", [])
                    if listeners:
                        node_response = await self.client.send_command(
                            "DOM.requestNode", {"objectId": current_object_id}
                        )
                        current_node_id = node_response.get("result", {}).get("nodeId")
                        if current_node_id:
                            describe_response = await self.client.send_command(
                                "DOM.describeNode", {"nodeId": current_node_id}
                            )
                            node_data = describe_response.get("result", {}).get("node", {})
                            source_description = self._format_node_description(node_data, is_target_node)
                            for listener in listeners:
                                listener["sourceNodeDescription"] = source_description
                            all_listeners.extend(listeners)
                except Exception as e:
                    # Print a warning but continue, as the ancestry chain might be broken by an iframe or shadow DOM
                    print(_("Warning: Could not get listeners for an ancestor node: {e}", e=e))

                is_target_node = False

                get_parent_js = "function() { return this.parentElement; }"
                parent_response = await self.client.send_command(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": current_object_id,
                        "functionDeclaration": get_parent_js,
                        "returnByValue": False,
                    },
                )
                parent_object = parent_response.get("result", {}).get("result", {})
                if not parent_object or parent_object.get("subtype") == "null":
                    break
                current_object_id = parent_object.get("objectId")
                if not current_object_id:
                    break
        except Exception as e:
            print(_("Warning: Error traversing ancestors. Listener list may be incomplete. Error: {e}", e=e))
        finally:
            for obj_id in object_ids_to_release:
                try:
                    await self.client.send_command("Runtime.releaseObject", {"objectId": obj_id})
                except Exception:
                    pass

        window_object_id = None
        try:
            eval_response = await self.client.send_command("Runtime.evaluate", {"expression": "window"})
            window_object_id = eval_response.get("result", {}).get("result", {}).get("objectId")
            if window_object_id:
                listeners_response = await self.client.send_command(
                    "DOMDebugger.getEventListeners", {"objectId": window_object_id}
                )
                listeners = listeners_response.get("result", {}).get("listeners", [])
                for listener in listeners:
                    listener["sourceNodeDescription"] = _("window")
                all_listeners.extend(listeners)
        except Exception as e:
            print(_("Warning: Could not get window event listeners: {e}", e=e))
        finally:
            if window_object_id:
                try:
                    await self.client.send_command("Runtime.releaseObject", {"objectId": window_object_id})
                except Exception:
                    # If connection is already closed, this might fail. Ignore.
                    pass

        return all_listeners

    async def get_element_html(self, node_id: int) -> str:
        """Get the HTML representation of an element."""
        response = await self.client.send_command("DOM.getOuterHTML", {"nodeId": node_id})
        return response["result"]["outerHTML"]

    async def get_element_screen_coords(self, node_id: int) -> Optional[Tuple[int, int]]:
        """Get the on-screen viewport coordinates (center) of a DOM element."""
        try:
            response = await self.client.send_command("DOM.resolveNode", {"nodeId": node_id})
            object_id = response["result"]["object"]["objectId"]
            js_code = """
            (function(element) {
                if (!element) return null;
                const rect = element.getBoundingClientRect();
                if (!rect) return null;
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;
                return { x: Math.round(centerX), y: Math.round(centerY) };
            })(this)
            """
            response = await self.client.send_command(
                "Runtime.callFunctionOn", {"objectId": object_id, "functionDeclaration": js_code, "returnByValue": True}
            )
            exception_details = response.get("result", {}).get("exceptionDetails")
            if exception_details:
                error_message = exception_details.get("exception", {}).get("description", "Unknown JS error")
                print(
                    _("JS execution failed in get_element_screen_coords: {error_message}", error_message=error_message)
                )
                return None
            result = response.get("result", {}).get("result", {})
            if result.get("type") == "object" and "value" in result:
                coords = result["value"]
                if coords and "x" in coords and "y" in coords:
                    return (coords["x"], coords["y"])
            return None
        except Exception as e:
            print(_("Failed to get element screen coordinates: {e}", e=e))
            return None

    async def get_node_by_selector(self, selector: str) -> Optional[int]:
        """Get a DOM node ID by its CSS selector."""
        try:
            doc_response = await self.client.send_command("DOM.getDocument", {"depth": 1})
            root_node_id = doc_response.get("result", {}).get("root", {}).get("nodeId")
            if not root_node_id:
                print(_("Could not get root document node"))
                return None
            response = await self.client.send_command(
                "DOM.querySelector", {"nodeId": root_node_id, "selector": selector}
            )
            node_id = response.get("result", {}).get("nodeId")
            if node_id and node_id != 0:
                print(_("Found nodeId {node_id} for selector '{selector}'", node_id=node_id, selector=selector))
                return node_id
            else:
                print(_("Selector '{selector}' did not match any element", selector=selector))
                return None
        except Exception as e:
            print(_("Failed to find element by selector: {e}", e=e))
            return None

    async def get_stylesheet_text(self, style_sheet_id: str) -> str:
        """Get the full text of a stylesheet."""
        if style_sheet_id in self.client.stylesheet_cache:
            return self.client.stylesheet_cache[style_sheet_id]
        response = await self.client.send_command("CSS.getStyleSheetText", {"styleSheetId": style_sheet_id})
        text = response["result"]["text"]
        self.client.stylesheet_cache[style_sheet_id] = text
        return text

    async def format_styles(self, styles_data: Dict[str, Any]) -> str:
        """Format style information to mimic DevTools display."""
        output = []
        if styles_data.get("inlineStyle"):
            inline_style = styles_data["inlineStyle"]
            if inline_style.get("cssProperties"):
                output.append("element.style {")
                for prop in inline_style["cssProperties"]:
                    if prop.get("value"):
                        output.append(f"    {prop['name']}: {prop['value']};")
                output.append("}\n")

        if styles_data.get("matchedCSSRules"):
            for rule_match in styles_data["matchedCSSRules"]:
                rule = rule_match["rule"]
                selector_text = rule["selectorList"]["text"]
                style_sheet_id = rule.get("styleSheetId")
                source_info = self.client._get_source_info(rule, style_sheet_id) if style_sheet_id else ""
                if source_info:
                    output.append(source_info)
                output.append(f"{selector_text} {{")
                if rule["style"].get("cssProperties"):
                    for prop in rule["style"]["cssProperties"]:
                        if prop.get("value"):
                            important = " !important" if prop.get("important") else ""
                            disabled = " /* disabled */" if prop.get("disabled") else ""
                            line_info = f" /* line: {prop['range']['startLine'] + 1} */" if prop.get("range") else ""
                            output.append(f"    {prop['name']}: {prop['value']}{important};{disabled}{line_info}")
                output.append("}\n")
        return "\n".join(output)

    async def format_event_listeners(self, listeners_data: List[Dict[str, Any]]) -> str:
        """Format event listener information, grouping by script location."""
        if not listeners_data:
            return _("No event listeners found.")

        script_groups: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for listener in listeners_data:
            script_id = listener.get("scriptId")
            key = (script_id, listener.get("lineNumber", 0), listener.get("columnNumber", 0))
            if script_id is None:
                key = ("no_script", listener.get("backendNodeId", 0), listener.get("type"))

            if key not in script_groups:
                script_groups[key] = {"event_types": set(), "source_descriptions": set(), "listeners": []}
            group = script_groups[key]
            group["event_types"].add(listener["type"])
            if listener.get("sourceNodeDescription"):
                group["source_descriptions"].add(listener["sourceNodeDescription"])
            group["listeners"].append(listener)

        output_parts = []
        for i, (key, group_data) in enumerate(script_groups.items(), 1):
            output_parts.append(f"{_('📍 Listener Group #{i}')}\n" + "=" * 50)
            event_types = sorted(list(group_data["event_types"]))
            source_descs = sorted(list(group_data["source_descriptions"]))
            output_parts.append(_("🎯 Event Types: {event_types}", event_types=", ".join(event_types)))
            if source_descs:
                output_parts.append(_("🔗 Bound To: {source_descs}", source_descs=", ".join(source_descs)))

            first_listener = group_data["listeners"][0]
            output_parts.append(
                _(
                    "⚙️  Properties: useCapture={useCapture}, passive={passive}, once={once}",
                    useCapture=first_listener.get("useCapture", False),
                    passive=first_listener.get("passive", False),
                    once=first_listener.get("once", False),
                )
            )

            if key[0] != "no_script":
                script_id, line_num, col_num = str(key[0]), int(key[1]), int(key[2])
                script_info = await self.client.debugger.get_script_source_info(script_id, line_num, col_num)
                if script_info.get("url"):
                    output_parts.append(_("🌐 Script URL: {url}", url=script_info["url"]))
                else:
                    output_parts.append(_("📄 Inline/Dynamic Script (ID: {script_id})", script_id=script_id))
                output_parts.append(
                    _("📍 Location: Line {line_num}, Col {col_num}", line_num=line_num + 1, col_num=col_num + 1)
                )

                if script_info.get("source"):
                    output_parts.append(_("📝 Source Code Snippet:"))
                    lines = script_info["source"].split("\n")
                    start = max(0, line_num - 2)
                    end = min(len(lines), line_num + 3)

                    MAX_LINE_LENGTH = 400
                    CONTEXT_CHARS = 150

                    for idx in range(start, end):
                        prefix = "→" if idx == line_num else " "
                        line_content = lines[idx]

                        # For the actual line of the event listener, if it's too long, show a snippet around the column.
                        if idx == line_num and len(line_content) > MAX_LINE_LENGTH:
                            start_col = max(0, col_num - CONTEXT_CHARS)
                            end_col = col_num + CONTEXT_CHARS

                            snippet = line_content[start_col:end_col]

                            prefix_indicator = "..." if start_col > 0 else ""
                            suffix_indicator = "..." if end_col < len(line_content) else ""

                            line_to_print = f"{prefix_indicator}{snippet}{suffix_indicator}"
                            output_parts.append(f"  {prefix} {idx + 1: >4} | {line_to_print}")
                            # Add a note about truncation
                            output_parts.append(
                                _(
                                    "         | ... (line truncated, showing snippet around column {col_num}) ...",
                                    col_num=col_num + 1,
                                )
                            )
                        # For other lines (context lines) or short lines, just print them (truncating if necessary).
                        else:
                            if len(line_content) > MAX_LINE_LENGTH:
                                line_to_print = line_content[:MAX_LINE_LENGTH] + "..."
                            else:
                                line_to_print = line_content
                            output_parts.append(f"  {prefix} {idx + 1: >4} | {line_to_print}")
            else:
                if first_listener.get("handler"):
                    handler_desc = first_listener["handler"].get("description", "N/A")
                    output_parts.append(_("📋 Handler: {handler_desc}", handler_desc=handler_desc))
            output_parts.append("")

        total_listeners = len(listeners_data)
        total_groups = len(script_groups)
        output_parts.append(
            _(
                "📊 Summary: {total_listeners} listeners found, grouped into {total_groups} locations.",
                total_listeners=total_listeners,
                total_groups=total_groups,
            )
        )
        return "\n".join(output_parts)

    async def inject_javascript_file(self, js_code_or_path: str) -> bool:
        """Inject a JavaScript code string or file into the current page."""
        js_code = js_code_or_path
        # Heuristic to check if it's a file path: not multiline and exists as a file.
        if "\n" not in js_code_or_path and os.path.exists(js_code_or_path):
            try:
                with open(js_code_or_path, "r", encoding="utf-8") as f:
                    js_code = f.read()
            except Exception as e:
                print(f"Failed to read JS file {js_code_or_path}: {e}")
                return False

        try:
            response = await self.client.send_command(
                "Runtime.evaluate",
                {"expression": js_code, "returnByValue": False, "awaitPromise": True, "userGesture": False},
            )
            if "result" in response and "exceptionDetails" in response["result"]:
                error_msg = response["result"]["exceptionDetails"]["exception"].get("description", "JS error")
                print(_("❌ JavaScript injection failed: {error_msg}", error_msg=error_msg))
                return False
            print(_("✅ JavaScript code injected successfully."))
            return True
        except Exception as e:
            print(_("❌ Error during JavaScript injection: {e}", e=e))
            return False

    async def wait_for_pointer_selection(self) -> Optional[int]:
        """Wait for the user to select an element using the mouse pointer."""
        print(_("\n🎯 Mouse selection mode enabled."))
        print(_("Move your mouse over the target element and click to select."))
        print(_("Press ESC to cancel selection.\n"))
        element_info = await self.start_element_selection_mode()
        if element_info and element_info != "cancelled":
            print(_("✅ Element selected: {tagName}", tagName=element_info.get("tagName", "Unknown")))
            element_path = element_info.get("path")
            if element_path:
                return await self.get_node_by_selector(element_path)
        elif element_info == "cancelled":
            print(_("Selection mode exited."))
        else:
            print(_("No valid element was selected."))
        return None

    async def start_element_selection_mode(self) -> Optional[Dict[str, Any]]:
        """Start element selection mode and return the selected element's info."""
        try:
            js_code = get_mouse_detector_js()
        except FileNotFoundError:
            return None
        if not await self.inject_javascript_file(js_code):
            print(_("❌ JavaScript injection failed, cannot start element selection mode."))
            return None

        self.element_selection_result = None
        self.original_console_handler = self.client.console_message_handler
        self.client.console_message_handler = self._handle_element_selection_console

        try:
            await self.client.send_command(
                "Runtime.evaluate", {"expression": "window.startElementSelection();", "returnByValue": False}
            )
            timeout = 30.0
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.element_selection_result is not None:
                    break
                await asyncio.sleep(0.1)

            if self.element_selection_result is None:
                print(_("⏰ Element selection timed out."))
                await self.client.send_command(
                    "Runtime.evaluate", {"expression": "window.stopElementSelection();", "returnByValue": False}
                )
            return self.element_selection_result
        except Exception as e:
            print(_("❌ Error during element selection: {e}", e=e))
            return None
        finally:
            self.client.console_message_handler = self.original_console_handler
            self.element_selection_result = None

    async def _handle_element_selection_console(self, console_data: Dict[str, Any]) -> None:
        """Process console messages during element selection."""
        try:
            params = console_data.get("message", {})
            message_text = ""
            if isinstance(params, dict) and "args" in params:
                message_parts = [arg.get("value", "") for arg in params.get("args", []) if arg.get("type") == "string"]
                message_text = " ".join(message_parts)

            if "[CHROME_TRACER_SELECTED]" in message_text:
                json_start = message_text.find("{")
                if json_start != -1:
                    try:
                        self.element_selection_result = json.loads(message_text[json_start:])
                    except json.JSONDecodeError:
                        self.element_selection_result = "error"
            elif "[CHROME_TRACER_CANCELLED]" in message_text:
                self.element_selection_result = "cancelled"
        except Exception as e:
            print(_("❌ Error handling element selection console message: {e}", e=e))
            self.element_selection_result = "error"

    async def format_html(self, html_content: str) -> str:
        """Format HTML output."""
        return html_content

    async def get_node_for_location(self, x: int, y: int) -> Optional[int]:
        """Get the node ID for a given viewport (x, y) coordinate."""
        try:
            response = await self.client.send_command("DOM.getNodeForLocation", {"x": x, "y": y})
            node_id = response.get("result", {}).get("nodeId")
            if node_id and node_id != 0:
                return node_id
            return None
        except Exception:
            return None
