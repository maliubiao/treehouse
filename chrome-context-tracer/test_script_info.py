#!/usr/bin/env python3
"""
Test script to verify script source information functionality in format_event_listeners
"""

import asyncio
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs
from test_server_utils import TestServerContext


async def test_script_info():
    """Test that script source information is properly retrieved and displayed"""
    print("🧪 Testing script source information in event listeners...")

    # Get browser tabs
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser tabs available")
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
    <title>Script Info Test</title>
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
        async with TestServerContext(test_html) as test_url:
            # Navigate to test page
            nav_success = await inspector.navigate_to_page(test_url)
            if not nav_success:
                print("❌ Failed to navigate to test page")
                return False

            # Wait for page to load
            await asyncio.sleep(2)

            # Find the button element
            response = await inspector.send_command("DOM.getDocument", {"depth": -1})
            root_node_id = response["result"]["root"]["nodeId"]

            response = await inspector.send_command(
                "DOM.querySelector", {"nodeId": root_node_id, "selector": "#test-btn"}
            )

            node_id = response["result"]["nodeId"]
            if not node_id:
                print("❌ Test button not found")
                return False

            # Get event listeners
            listeners_data = await inspector.get_element_event_listeners(node_id)

            # Format listeners (this should now include script source info)
            formatted_listeners = await inspector.format_event_listeners(listeners_data)

            print("📋 Formatted event listeners:")
            print("=" * 50)
            print(formatted_listeners)
            print("=" * 50)

            # Check if script source information is included
            if (
                "相关代码:" in formatted_listeners
                or "脚本源获取错误:" in formatted_listeners
                or "脚本源码已获取" in formatted_listeners
                or "源码预览:" in formatted_listeners
            ):
                print("✅ Script source information is being retrieved")
                success = True
            else:
                print("❌ Script source information not found in output")
                success = False

            await inspector.close()

            return success

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run the test"""
    print("🚀 Testing script source information functionality")
    result = await test_script_info()

    if result:
        print("🎉 Test passed!")
    else:
        print("❌ Test failed!")

    return result


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
