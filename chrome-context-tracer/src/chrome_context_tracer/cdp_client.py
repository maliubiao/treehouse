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
        print(_("Connected to Browser DevTools: {websocket_url}", websocket_url=self.websocket_url))

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
                                future.set_exception(Exception(_("Command failed: {error}", error=response["error"])))
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
            "CSS.styleSheetAdded": self.dom.handle_style_sheet_added,
            "Debugger.scriptParsed": self.debugger.handle_script_parsed,
            "Debugger.paused": self.debugger.handle_debugger_paused,
        }
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
            self.connection_errors = 0
            return result
        except asyncio.TimeoutError:
            self.connection_errors += 1
            self._pending_responses.pop(message_id, None)
            raise TimeoutError(_("Command {method} timed out after 30 seconds", method=method))
        except Exception as e:
            self.connection_errors += 1
            self._pending_responses.pop(message_id, None)
            raise e

    async def enable_domains(self) -> None:
        """Enable all necessary domains for the current session."""
        if not self.session_id:
            print(_("Warning: Cannot enable domains without a session ID."))
            return
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

    async def _handle_console_api_called(self, params: Dict[str, Any]) -> None:
        """
        Handle Runtime.consoleAPICalled events.
        Prioritizes the custom message handler (for features like element selection)
        before falling back to the generic console listener.
        """
        if self.console_message_handler:
            await self.console_message_handler({"type": params.get("type", ""), "message": params, "raw": params})
        elif self.console_listening:
            message_parts = [str(arg.get("value", arg.get("description", ""))) for arg in params.get("args", [])]
            print(f"CONSOLE.{params.get('type', 'log').upper()}: {' '.join(message_parts)}")

    async def _handle_console_message_added(self, params: Dict[str, Any]) -> None:
        """
        Handle Console.messageAdded events.
        Prioritizes the custom message handler before falling back to the generic console listener.
        """
        message = params.get("message", {})
        if self.console_message_handler:
            await self.console_message_handler({"type": message.get("level", ""), "message": params, "raw": params})
        elif self.console_listening:
            print(f"CONSOLE.{message.get('level', 'log').upper()}: {message.get('text', '')}")

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
