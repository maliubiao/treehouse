import argparse
import asyncio
from typing import Optional

from .browser_manager import find_chrome_tabs
from .cdp_client import DOMInspector
from .i18n import _
from .line_trace_config import LineTraceConfig, load_config


async def inspect_element_styles(
    url_pattern: str,
    selector: str,
    port: int,
    show_events: bool,
    show_html: bool,
    from_pointer: bool,
):
    """主函数：检查元素的样式和事件监听器"""
    websocket_urls = await find_chrome_tabs(port)
    if not websocket_urls:
        print(_("No browser tabs found. Please ensure the browser is running with remote debugging enabled:"))
        print("Chrome: chrome --remote-debugging-port=9222")
        print("Edge: msedge --remote-debugging-port=9222")
        print(_("Or specify the correct port: --port <port_number>"))
        return

    inspector = DOMInspector(websocket_urls[0])
    await inspector.connect()

    try:
        target_id = await inspector.find_tab_by_url(url_pattern)
        if not target_id:
            print(_("No tab found matching URL '{url_pattern}' or selection was cancelled.", url_pattern=url_pattern))
            return

        session_id = await inspector.attach_to_tab(target_id)
        if not session_id:
            print(_("Failed to attach to tab."))
            return

        node_id = None
        if from_pointer:
            node_id = await inspector.wait_for_pointer_selection()
            if not node_id:
                print(_("No element selected, exiting."))
                return
        elif selector:
            node_id = await inspector.find_element(selector)
            if not node_id:
                print(_("No element found matching selector '{selector}'.", selector=selector))
                return
        else:
            print(_("Error: Either --selector must be provided or --from-pointer must be used."))
            return

        print(_("Found element, nodeId: {node_id}", node_id=node_id))

        styles_data = await inspector.get_element_styles(node_id)
        formatted_styles = await inspector.format_styles(styles_data)
        print(_("\nElement Style Information:"))
        print("=" * 60)
        print(formatted_styles)

        if show_events:
            listeners_data = await inspector.get_element_event_listeners(node_id)
            formatted_listeners = await inspector.format_event_listeners(listeners_data)
            print(_("\nEvent Listener Information:"))
            print("=" * 60)
            print(formatted_listeners)

        if show_html:
            html_content = await inspector.get_element_html(node_id)
            formatted_html = await inspector.format_html(html_content)
            print(_("\nElement HTML Representation:"))
            print("=" * 60)
            print(formatted_html)

    finally:
        await inspector.close()


async def run_debugger_trace(
    url_pattern: str,
    port: int,
    ws_url: Optional[str] = None,
    pause_on_exceptions_state: str = "all",
    is_node: bool = False,
    line_trace_config_path: Optional[str] = None,
) -> None:
    """Runs the debugger trace mode, connecting to a browser tab or a direct WebSocket URL."""
    inspector: Optional[DOMInspector] = None
    try:
        line_trace_config: Optional[LineTraceConfig] = None
        if line_trace_config_path:
            try:
                line_trace_config = load_config(line_trace_config_path)
                print(
                    _(
                        "✅ Line tracing mode enabled with config: {path}",
                        path=line_trace_config_path,
                    )
                )
            except (FileNotFoundError, ValueError, IsADirectoryError):
                # Error is printed inside load_config, or we handle filesystem errors here
                print(
                    _(
                        "❌ Error: Could not read line trace config file at {path}",
                        path=line_trace_config_path,
                    )
                )
                return

        if is_node:
            if not ws_url:
                print(_("Error: --node flag requires --ws-url to be specified."))
                return
            print(_("Connecting to Node.js target: {ws_url}", ws_url=ws_url))
            inspector = DOMInspector(ws_url)
            inspector.is_node_target = True
        elif ws_url:
            print(_("Connecting directly to WebSocket: {ws_url}", ws_url=ws_url))
            inspector = DOMInspector(ws_url)
        else:
            websocket_urls = await find_chrome_tabs(port)
            if not websocket_urls:
                print(_("No browser tabs found. Please ensure the browser is running with remote debugging enabled:"))
                return
            inspector = DOMInspector(websocket_urls[0])

        await inspector.start_console_listening()
        await inspector.connect()

        # For browser targets, we need to find and attach to a tab.
        if not is_node and not ws_url:
            target_id = await inspector.find_tab_by_url(url_pattern)
            if not target_id:
                print(
                    _("No tab found matching URL '{url_pattern}' or selection was cancelled.", url_pattern=url_pattern)
                )
                return

            session_id = await inspector.attach_to_tab(target_id)
            if not session_id:
                print(_("Failed to attach to tab."))
                return

        # Pass config to the debugger handler
        if line_trace_config:
            inspector.debugger.set_line_trace_config(line_trace_config)

        if pause_on_exceptions_state != "none":
            await inspector.set_pause_on_exceptions(pause_on_exceptions_state)

        stop_event = asyncio.Event()

        print(_("\n✅ Debugger trace mode activated."))
        if line_trace_config:
            print(_("Waiting for 'debugger;' statement to start line-by-line tracing..."))
        elif pause_on_exceptions_state != "none":
            print(
                _(
                    "Waiting for 'debugger;' statements, console messages, and {state} exceptions.",
                    state=pause_on_exceptions_state,
                )
            )
        else:
            print(_("Waiting for 'debugger;' statements and console messages in the attached page."))

        if is_node:
            # For Node.js targets started with --inspect-brk, we must send this command
            # to tell the runtime to start execution and break at the first line.
            await inspector.run_if_waiting_for_debugger()

        print(_("Press Ctrl+C to exit."))
        await stop_event.wait()

    except asyncio.CancelledError:
        print(_("\nExiting debugger trace mode."))
    except ConnectionRefusedError:
        print(
            _("Connection refused. Is the target running and the WebSocket URL correct? URL: {ws_url}", ws_url=ws_url)
        )
    finally:
        if inspector:
            await inspector.close()


def main():
    parser = argparse.ArgumentParser(
        description=_("Browser DOM Inspection and Debugging Trace Tool (Supports Chrome/Edge)")
    )
    parser.add_argument("--port", type=int, default=9222, help=_("Browser debugging port"))
    parser.add_argument("--ws-url", help=_("Direct WebSocket URL for CDP connection (e.g., for Node.js)"))

    subparsers = parser.add_subparsers(dest="command", required=True, help=_("Available commands"))

    # --- Inspect command ---
    parser_inspect = subparsers.add_parser("inspect", help=_("Inspect element styles and event listeners"))
    parser_inspect.add_argument(
        "--url", help=_("URL pattern to match (optional, will prompt for selection if not specified)")
    )
    parser_inspect.add_argument("--selector", help=_("CSS selector (optional if using --from-pointer)"))
    parser_inspect.add_argument("--events", action="store_true", help=_("Show event listener information"))
    parser_inspect.add_argument("--html", action="store_true", help=_("Show element HTML representation"))
    parser_inspect.add_argument("--from-pointer", action="store_true", help=_("Select element using the mouse pointer"))

    # --- Trace command ---
    parser_trace = subparsers.add_parser(
        "trace", help=_("Trace JS 'debugger;' statements and show call stack and console messages")
    )
    parser_trace.add_argument(
        "--url", help=_("URL pattern to match (optional, will prompt for selection if not specified)")
    )
    parser_trace.add_argument(
        "--pause-on-exceptions",
        choices=["none", "uncaught", "all"],
        default="uncaught",
        help=_("Set pause on exceptions mode. Default is 'uncaught'."),
    )
    parser_trace.add_argument(
        "--node", action="store_true", help=_("Enable Node.js debugging mode (requires --ws-url)")
    )
    parser_trace.add_argument(
        "--line-trace-config",
        metavar="CONFIG_PATH",
        help=_("Path to a YAML config file to enable line-by-line tracing from 'debugger;' statements."),
    )

    args = parser.parse_args()
    url_pattern = args.url if hasattr(args, "url") and args.url else ""

    try:
        if args.command == "inspect":
            if not args.selector and not args.from_pointer:
                parser_inspect.error(_("Either --selector must be provided or --from-pointer must be used."))
            asyncio.run(
                inspect_element_styles(url_pattern, args.selector, args.port, args.events, args.html, args.from_pointer)
            )
        elif args.command == "trace":
            asyncio.run(
                run_debugger_trace(
                    url_pattern,
                    args.port,
                    args.ws_url,
                    args.pause_on_exceptions,
                    args.node,
                    args.line_trace_config,
                )
            )
    except KeyboardInterrupt:
        print(_("\nInterrupted by user. Exiting."))
