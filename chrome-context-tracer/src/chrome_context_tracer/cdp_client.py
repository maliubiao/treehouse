#!/usr/bin/env python3
"""
Core CDP Client - The DOMInspector class handles all communication
with the Chrome DevTools Protocol and coordinates different handlers.
"""
# from __future_ import annotations

import asyncio
import json
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp

from .debugger_handler import DebuggerHandler
from .dom_handler import DOMHandler
from .i18n import _
from .target_manager import TargetManager

# Default max message size for aiohttp is 4MB. Some sourcemaps or scripts can exceed this.
# We increase it to 16MB to be safe.
WEBSOCKET_MAX_MSG_SIZE = 16 * 1024 * 1024


class DOMInspector:
    """A client for the Chrome DevTools Protocol to inspect DOM elements."""

    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session_id: Optional[str] = None
        self.message_id = 1

        # Caches
        self.stylesheet_cache: Dict[str, str] = {}
        self.stylesheet_headers: Dict[str, Dict[str, Any]] = {}
        self.script_cache: Dict[str, Dict[str, Any]] = {}

        # State
        self.connection_errors = 0
        self.max_connection_errors = 5
        self.console_listening = False
        self.console_message_handler: Optional[Callable[[Dict[str, Any]], Any]] = None
        self.is_node_target: bool = False
        self.did_receive_initial_node_pause: bool = False

        # Handlers for different domains
        self.targets = TargetManager(self)
        self.dom = DOMHandler(self)
        self.debugger = DebuggerHandler(self)

        # Internal task management
        self._message_handler_task: Optional[asyncio.Task[None]] = None
        self._pending_responses: Dict[int, asyncio.Future[Any]] = {}

    async def connect(self) -> None:
        """Connect to the CDP WebSocket and start the background message listener."""
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.websocket_url, max_msg_size=WEBSOCKET_MAX_MSG_SIZE)
        self._message_handler_task = asyncio.create_task(self._message_listener())

        # Detect if this is a Node.js target based on WebSocket URL pattern
        if "node" in self.websocket_url.lower() or ":9229" in self.websocket_url:
            self.is_node_target = True
            print(_("Connected to Node.js DevTools: {websocket_url}", websocket_url=self.websocket_url))
        else:
            print(_("Connected to Browser DevTools: {websocket_url}", websocket_url=self.websocket_url))

        # If we are connecting directly to a page or a Node.js target, enable domains immediately.
        # Browser-level connections (e.g., for Target management) do not support these domains.
        if "/browser" not in self.websocket_url:
            await self.enable_domains()

    async def close(self) -> None:
        """Close the connection and clean up resources."""
        await self.stop_console_listening()
        if self._message_handler_task:
            self._message_handler_task.cancel()
            await asyncio.gather(self._message_handler_task, return_exceptions=True)
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session and not self.session.closed:
            await self.session.close()

    async def _message_listener(self) -> None:
        """Background task to listen for and dispatch all WebSocket messages."""
        if not self.ws:
            return
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    response = json.loads(msg.data)
                    if "id" in response:
                        future = self._pending_responses.pop(response["id"], None)
                        if future and not future.done():
                            if "error" in response:
                                # Use ValueError for application-level errors from CDP
                                future.set_exception(ValueError(_("Command failed: {error}", error=response["error"])))
                            else:
                                future.set_result(response)
                    elif "method" in response:
                        asyncio.create_task(self._handle_event(response))
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(_("WebSocket listener error: {e}", e=e))
            traceback.print_exc()
        finally:
            for future in self._pending_responses.values():
                if not future.done():
                    future.set_exception(Exception(_("WebSocket connection closed unexpectedly.")))

    async def _handle_event(self, event: Dict[str, Any]) -> None:
        """Route incoming events to the appropriate handler."""
        method = event.get("method")
        params = event.get("params", {})

        event_handlers = {
            "Runtime.consoleAPICalled": self._handle_console_api_called,
            "Console.messageAdded": self._handle_console_message_added,
            "Runtime.exceptionThrown": self.debugger.handle_exception_thrown,
            "Debugger.scriptParsed": self.debugger.handle_script_parsed,
            "Debugger.paused": self.debugger.handle_debugger_paused,
        }

        # Only add DOM/CSS handlers for browser targets
        if not self.is_node_target:
            event_handlers.update(
                {
                    "CSS.styleSheetAdded": self.dom.handle_style_sheet_added,
                }
            )

        handler = event_handlers.get(method)
        if handler:
            await handler(params)

    async def send_command(
        self, method: str, params: Optional[Dict[str, Any]] = None, use_session: bool = True
    ) -> Dict[str, Any]:
        """Send a command to the CDP and wait for its response."""
        if params is None:
            params = {}
        if not self.ws or self.ws.closed:
            raise ConnectionError(_("WebSocket connection is closed."))
        if self.connection_errors >= self.max_connection_errors:
            raise ConnectionError(_("Too many WebSocket errors, refusing further requests."))

        message_id = self.message_id
        self.message_id += 1
        message: Dict[str, Any] = {"id": message_id, "method": method, "params": params}
        if self.session_id and use_session:
            message["sessionId"] = self.session_id

        future = asyncio.get_running_loop().create_future()
        self._pending_responses[message_id] = future

        try:
            await self.ws.send_str(json.dumps(message))
            result = await asyncio.wait_for(future, timeout=30.0)
            # A successful command resets the connection error count.
            self.connection_errors = 0
            return result
        except asyncio.TimeoutError:
            self.connection_errors += 1
            self._pending_responses.pop(message_id, None)
            raise TimeoutError(_("Command {method} timed out after 30 seconds", method=method))
        except ValueError as e:
            # CDP application-level errors are raised as ValueErrors. They are not connection errors.
            self._pending_responses.pop(message_id, None)
            raise e
        except Exception as e:
            # Other exceptions (from aiohttp, etc.) are treated as connection errors.
            self.connection_errors += 1
            self._pending_responses.pop(message_id, None)
            raise e

    async def enable_domains(self) -> None:
        """Enable all necessary domains for the current session."""
        # Node.js targets don't support DOM/CSS/Page domains
        if self.is_node_target:
            domains_to_enable = ["Runtime", "Debugger", "Console"]
            print(_("Enabling Node.js compatible domains: {domains}", domains=", ".join(domains_to_enable)))
        else:
            domains_to_enable = ["DOM", "CSS", "Runtime", "Page", "Debugger", "Console"]

        for domain in domains_to_enable:
            try:
                await self.send_command(f"{domain}.enable")
            except Exception as e:
                print(
                    _(
                        "Warning: Could not enable {domain} domain. Functionality may be limited. Error: {e}",
                        domain=domain,
                        e=e,
                    )
                )
        print(_("✅ Domains enabled for the new session."))

    async def navigate_to_page(self, url: str) -> bool:
        """Navigate the attached tab to a new URL."""
        response = await self.send_command("Page.navigate", {"url": url})
        return "error" not in response

    # --- Delegated Methods ---

    async def find_tab_by_url(self, url_pattern: Optional[str] = None) -> Optional[str]:
        return await self.targets.find_tab_by_url(url_pattern)

    async def attach_to_tab(self, target_id: str) -> Optional[str]:
        session_id = await self.targets.attach_to_tab(target_id)
        if session_id:
            self.session_id = session_id
            await self.enable_domains()
        return session_id

    async def find_element(self, selector: str) -> Optional[int]:
        return await self.dom.find_element(selector)

    async def get_element_styles(self, node_id: int) -> Dict[str, Any]:
        return await self.dom.get_element_styles(node_id)

    async def get_element_event_listeners(self, node_id: int) -> List[Dict[str, Any]]:
        return await self.dom.get_element_event_listeners(node_id)

    async def get_element_html(self, node_id: int) -> str:
        return await self.dom.get_element_html(node_id)

    async def wait_for_pointer_selection(self) -> Optional[int]:
        return await self.dom.wait_for_pointer_selection()

    async def format_styles(self, styles_data: Dict[str, Any]) -> str:
        return await self.dom.format_styles(styles_data)

    async def format_event_listeners(self, listeners_data: List[Dict[str, Any]]) -> str:
        return await self.dom.format_event_listeners(listeners_data)

    async def format_html(self, html_content: str) -> str:
        return await self.dom.format_html(html_content)

    async def get_element_screen_coords(self, node_id: int) -> Optional[Tuple[int, int]]:
        return await self.dom.get_element_screen_coords(node_id)

    async def get_node_for_location(self, x: int, y: int) -> Optional[int]:
        return await self.dom.get_node_for_location(x, y)

    async def inject_javascript_file(self, js_code_or_path: str) -> bool:
        return await self.dom.inject_javascript_file(js_code_or_path)

    # --- Console Management ---

    async def start_console_listening(self, message_handler: Optional[Callable[[Dict[str, Any]], Any]] = None) -> None:
        """Start listening for console messages."""
        if self.console_listening:
            return
        self.console_message_handler = message_handler
        self.console_listening = True
        print(_("✅ Console listening enabled."))

    async def stop_console_listening(self) -> None:
        """Stop listening for console messages."""
        if not self.console_listening:
            return
        self.console_listening = False
        self.console_message_handler = None

    def _print_console_message(
        self, level: str, args: List[Dict[str, Any]], stack_trace: Optional[Dict[str, Any]] = None
    ) -> None:
        """Helper to format and print a console message with an optional stack trace."""
        message_parts = [str(arg.get("value", arg.get("description", ""))) for arg in args]

        # In Runtime.consoleAPICalled, a trace has level='trace'. In Console.messageAdded, it's level='log'
        # with a stack trace. We treat any 'trace'-level message specially for formatting.
        if level == "trace":
            header = f"CONSOLE.TRACE: {' '.join(message_parts)}".strip()
            print(header)
        else:
            header = f"CONSOLE.{level.upper()}: {' '.join(message_parts)}"
            print(header)

        if stack_trace and stack_trace.get("callFrames"):
            # For console.trace, the stack is the primary output. For others, it's context.
            if level != "trace":
                print(_("--- Stack Trace ---"))

            for frame in stack_trace["callFrames"]:
                func_name = frame.get("functionName") or "(anonymous)"
                url = frame.get("url", "unknown")
                filename = url.split("/")[-1] if url else "unknown"
                line = frame.get("lineNumber", 0) + 1
                col = frame.get("columnNumber", 0) + 1
                print(f"    at {func_name} ({filename}:{line}:{col})")

    async def _handle_console_api_called(self, params: Dict[str, Any]) -> None:
        """
        Handle Runtime.consoleAPICalled events.
        Prioritizes the custom message handler before falling back to the generic console listener.
        """
        if self.console_message_handler:
            await self.console_message_handler({"type": params.get("type", ""), "message": params, "raw": params})
        elif self.console_listening:
            self._print_console_message(
                level=params.get("type", "log"),
                args=params.get("args", []),
                stack_trace=params.get("stackTrace"),
            )

    async def _handle_console_message_added(self, params: Dict[str, Any]) -> None:
        """
        Handle Console.messageAdded events.
        This is often the primary event source for console messages when the Debugger domain is active.
        """
        message = params.get("message", {})
        if self.console_message_handler:
            await self.console_message_handler({"type": message.get("level", ""), "message": params, "raw": params})
        elif self.console_listening:
            level = message.get("level", "log")

            # Use detailed view for messages from JS console APIs ('console-api' source)
            if message.get("source") == "console-api" and "parameters" in message:
                self._print_console_message(
                    level=level,
                    args=message.get("parameters", []),
                    stack_trace=message.get("stackTrace"),
                )
            else:
                # Fallback for other messages (network, security, etc.) which only have 'text'
                print(f"CONSOLE.{level.upper()}: {message.get('text', '')}")

    # --- Debugger Controls ---

    async def set_pause_on_exceptions(self, state: str) -> None:
        """
        Sets the pause on exceptions state.

        Args:
            state: 'none', 'uncaught', or 'all'.
        """
        valid_states = ["none", "uncaught", "all"]
        if state not in valid_states:
            print(
                _(
                    "Warning: Invalid state '{state}' for set_pause_on_exceptions. Must be one of {valid_states}.",
                    state=state,
                    valid_states=valid_states,
                )
            )
            return

        try:
            await self.send_command("Debugger.setPauseOnExceptions", {"state": state})
            print(_("✅ Pause on exceptions mode set to '{state}'.", state=state))
        except Exception as e:
            print(_("⚠️  Warning: Could not set pause on exceptions mode: {e}", e=e))

    async def resume_debugger(self) -> None:
        """Sends the command to resume debugger execution."""
        try:
            await self.send_command("Debugger.resume")
        except Exception as e:
            print(_("⚠️  Warning: Could not resume debugger: {e}", e=e))

    async def run_if_waiting_for_debugger(self) -> None:
        """
        Sends the command to start execution if the target is waiting for a debugger.
        This is crucial for Node.js processes started with --inspect-brk.
        """
        try:
            print(_("Telling Node.js to start execution..."))
            await self.send_command("Runtime.runIfWaitingForDebugger")
        except Exception as e:
            print(_("⚠️  Warning: Could not send runIfWaitingForDebugger command: {e}", e=e))

    async def pause_debugger(self) -> None:
        """Sends the command to pause debugger execution."""
        try:
            await self.send_command("Debugger.pause")
        except Exception as e:
            print(_("⚠️  Warning: Could not pause debugger: {e}", e=e))

    async def step_into(self) -> None:
        """Sends the command to step into the next function call."""
        try:
            await self.send_command("Debugger.stepInto")
        except Exception as e:
            print(_("⚠️  Warning: Could not step into: {e}", e=e))

    async def step_over(self) -> None:
        """Sends the command to step over the next function call."""
        try:
            await self.send_command("Debugger.stepOver")
        except Exception as e:
            print(_("⚠️  Warning: Could not step over: {e}", e=e))

    async def step_out(self) -> None:
        """Sends the command to step out of the current function."""
        try:
            await self.send_command("Debugger.stepOut")
        except Exception as e:
            print(_("⚠️  Warning: Could not step out: {e}", e=e))

    async def set_blackbox_patterns(self, patterns: List[str]) -> None:
        """Sets patterns for scripts to be blackboxed by the debugger."""
        try:
            await self.send_command("Debugger.setBlackboxPatterns", {"patterns": patterns})
            if patterns:
                print(_("✅ Blackbox patterns set for line tracing."))
        except Exception as e:
            print(_("⚠️  Warning: Could not set blackbox patterns: {e}", e=e))

    def _get_source_info(self, rule: Dict[str, Any], style_sheet_id: str) -> str:
        """Helper to get the source file information for a CSS rule."""
        if style_sheet_id in self.stylesheet_headers:
            header = self.stylesheet_headers[style_sheet_id]
            source_url = header.get("sourceURL", "")
            if source_url:
                filename = source_url.split("/")[-1]
                line_num = rule.get("style", {}).get("range", {}).get("startLine", -1) + 1
                return f"{filename}:{line_num}"
        return ""
