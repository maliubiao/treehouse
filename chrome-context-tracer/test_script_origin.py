#!/usr/bin/env python3
"""
Test script to verify script origin (filename/URL) extraction functionality
"""

import asyncio
import os
import shutil
import sys
import tempfile

from aiohttp import web

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs, launch_browser_with_debugging


async def start_test_server(html_content):
    """Start a simple HTTP server to serve the test HTML"""
    app = web.Application()

    async def handler(request):
        return web.Response(text=html_content, content_type="text/html")

    app.router.add_get("/", handler)
    app.router.add_get("/test.html", handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", 8080)
    await site.start()

    return runner


async def test_script_origin():
    """Test that script origin information is properly retrieved and displayed"""
    print("🧪 Testing script origin information extraction...")

    # Get browser tabs - try to find existing ones first
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("⚠️  No browser tabs available, launching Microsoft Edge...")
        # Launch Microsoft Edge with debugging enabled
        if await launch_browser_with_debugging("edge", 9222):
            print("✅ Microsoft Edge launched successfully")
            # Wait for browser to start
            await asyncio.sleep(3)
            # Try to find tabs again
            websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
            if not websocket_urls:
                print("❌ Still no browser tabs available after launch")
                return False
        else:
            print("❌ Failed to launch browser")
            return False

    try:
        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()
        print("✅ Connected to browser")

        # Create a simple test page with event listeners
        test_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Script Origin Test</title>
</head>
<body>
    <button id="test-btn">Test Button</button>
    
    <script>
        function testHandler() {
            console.log('Button clicked!');
        }
        
        // Add event listener
        document.getElementById('test-btn').addEventListener('click', testHandler);
    </script>
</body>
</html>
"""

        # Start HTTP server to serve the test HTML
        server_runner = await start_test_server(test_html)
        test_url = "http://localhost:8080/test.html"

        # Navigate to test page
        nav_success = await inspector.navigate_to_page(test_url)
        if not nav_success:
            print("❌ Failed to navigate to test page")
            return False

        # Wait for page to load and ensure DOM is ready
        await asyncio.sleep(3)

        # Find the button element - try multiple approaches
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        # Try query selector
        response = await inspector.send_command("DOM.querySelector", {"nodeId": root_node_id, "selector": "#test-btn"})

        node_id = response["result"]["nodeId"]
        if not node_id:
            # Try alternative approach - get all elements and search
            print("⚠️  Button not found with querySelector, trying alternative approach...")
            response = await inspector.send_command(
                "DOM.querySelectorAll", {"nodeId": root_node_id, "selector": "button"}
            )

            if response["result"]["nodeIds"]:
                node_id = response["result"]["nodeIds"][0]
                print(f"✅ Found button with nodeId: {node_id}")
            else:
                print("❌ Test button not found - checking page content...")
                # Debug: get page content to see what's there
                response = await inspector.send_command("DOM.getOuterHTML", {"nodeId": root_node_id})
                print(f"Page content: {response['result']['outerHTML'][:200]}...")
                return False

        # Get event listeners
        listeners_data = await inspector.get_element_event_listeners(node_id)

        # Format listeners (this should now include script origin info)
        formatted_listeners = await inspector.format_event_listeners(listeners_data)

        print("📋 Formatted event listeners:")
        print("=" * 50)
        print(formatted_listeners)
        print("=" * 50)

        # Check if script origin information is included
        if (
            "脚本来源:" in formatted_listeners
            or "脚本URL:" in formatted_listeners
            or "script_" in formatted_listeners
            and ".js" in formatted_listeners
        ):
            print("✅ Script origin information is being retrieved")
            success = True
        else:
            print("❌ Script origin information not found in output")
            success = False

        await inspector.close()

        # Cleanup - stop the HTTP server
        await server_runner.cleanup()

        return success

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run the test"""
    print("🚀 Testing script origin information functionality")
    result = await test_script_origin()

    if result:
        print("🎉 Test passed! Script origin information is working correctly.")
    else:
        print("❌ Test failed!")

    return result


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
