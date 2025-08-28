#!/usr/bin/env python3
"""
Test navigation with real website to verify page loading works
"""

import asyncio
import os
import sys
import time

import aiohttp

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs, launch_browser_with_debugging


async def test_real_website_navigation():
    """Test navigation to a real website like baidu.com"""
    print("🧪 Testing navigation to real website (baidu.com)...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()
        print("✅ Connected to browser")

        # Navigate to baidu.com
        test_url = "https://www.baidu.com"
        print(f"🌐 Navigating to: {test_url}")

        nav_success = await inspector.navigate_to_page(test_url)
        if not nav_success:
            print("❌ Failed to navigate to baidu.com")
            await inspector.close()
            return False

        print("✅ Successfully navigated to baidu.com")

        # Wait a bit more for the page to fully load
        await asyncio.sleep(3)

        # Test finding some common elements on baidu.com
        test_selectors = [
            "#kw",  # Search input box
            "#su",  # Search button
            ".head_wrapper",  # Header wrapper
            "body",  # Body element
            "html",  # HTML element
        ]

        # Get document root
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]
        print(f"✅ Got document root node ID: {root_node_id}")

        found_elements = 0
        for selector in test_selectors:
            try:
                response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": selector}
                )
                node_id = response["result"]["nodeId"]
                if node_id:
                    print(f"✅ Found element with selector: {selector} (nodeId: {node_id})")
                    found_elements += 1
                else:
                    print(f"❌ Element not found: {selector}")
            except Exception as e:
                print(f"❌ Error finding element {selector}: {e}")

        print(f"📊 Found {found_elements}/{len(test_selectors)} elements on baidu.com")

        # If we found some elements, try to get the page title
        if found_elements > 0:
            try:
                # Get page title
                response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "title"}
                )
                title_node_id = response["result"]["nodeId"]
                if title_node_id:
                    # Get the title text
                    response = await inspector.send_command("DOM.getOuterHTML", {"nodeId": title_node_id})
                    title_html = response["result"]["outerHTML"]
                    print(f"📄 Page title: {title_html}")
            except Exception as e:
                print(f"⚠️ Could not get page title: {e}")

        await inspector.close()
        return found_elements > 0

    except Exception as e:
        print(f"❌ Real website navigation test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run real website test"""
    print("🚀 Testing Navigation with Real Website")
    print("=" * 50)

    # Check if browser is available
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser available. Please start browser first.")
        return False

    print(f"✅ Found {len(websocket_urls)} browser tab(s)")

    # Run the test
    success = await test_real_website_navigation()

    print("\n" + "=" * 50)
    if success:
        print("🎉 Real website navigation test PASSED!")
        print("✅ Page navigation and element finding works with real websites")
    else:
        print("❌ Real website navigation test FAILED")
        print("⚠️  There may be issues with page navigation or element finding")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
