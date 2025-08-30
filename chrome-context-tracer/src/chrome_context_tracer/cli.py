import argparse
import asyncio

from .browser_manager import find_chrome_tabs
from .cdp_client import DOMInspector
from .i18n import _


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


async def run_debugger_trace(url_pattern: str, port: int):
    """主函数：运行调试追踪器模式"""
    websocket_urls = await find_chrome_tabs(port)
    if not websocket_urls:
        print(_("No browser tabs found. Please ensure the browser is running with remote debugging enabled:"))
        return

    inspector = DOMInspector(websocket_urls[0])
    await inspector.connect()

    # Enable console to see logs from the test page
    await inspector.send_command("Runtime.enable")

    stop_event = asyncio.Event()

    try:
        target_id = await inspector.find_tab_by_url(url_pattern)
        if not target_id:
            print(_("No tab found matching URL '{url_pattern}' or selection was cancelled.", url_pattern=url_pattern))
            return

        session_id = await inspector.attach_to_tab(target_id)
        if not session_id:
            print(_("Failed to attach to tab."))
            return

        print(_("\n✅ Debugger trace mode activated."))
        print(_("Waiting for 'debugger;' statements in the attached page."))
        print(_("Press Ctrl+C to exit."))

        await stop_event.wait()

    except asyncio.CancelledError:
        print(_("\nExiting debugger trace mode."))
    finally:
        await inspector.close()


def main():
    parser = argparse.ArgumentParser(
        description=_("Browser DOM Inspection and Debugging Trace Tool (Supports Chrome/Edge)")
    )
    parser.add_argument("--port", type=int, default=9222, help=_("Browser debugging port"))

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
    parser_trace = subparsers.add_parser("trace", help=_("Trace JS 'debugger;' statements and show call stack"))
    parser_trace.add_argument(
        "--url", help=_("URL pattern to match (optional, will prompt for selection if not specified)")
    )

    args = parser.parse_args()
    url_pattern = args.url if args.url else ""

    try:
        if args.command == "inspect":
            if not args.selector and not args.from_pointer:
                parser_inspect.error(_("Either --selector must be provided or --from-pointer must be used."))
            asyncio.run(
                inspect_element_styles(url_pattern, args.selector, args.port, args.events, args.html, args.from_pointer)
            )
        elif args.command == "trace":
            asyncio.run(run_debugger_trace(url_pattern, args.port))
    except KeyboardInterrupt:
        print(_("\nInterrupted by user. Exiting."))
