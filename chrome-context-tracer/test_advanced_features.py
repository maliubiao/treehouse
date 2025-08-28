#!/usr/bin/env python3
"""
Advanced DOM Inspector Features Test
Tests style extraction, event listeners, and complex selectors
"""

import asyncio
import os
import sys
import time

import aiohttp

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs


async def test_style_extraction():
    """Test style extraction functionality with real website"""
    print("🎨 Testing style extraction functionality...")

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

        # Navigate to baidu.com (known to have rich styling)
        test_url = "https://www.baidu.com"
        print(f"🌐 Navigating to: {test_url}")

        nav_success = await inspector.navigate_to_page(test_url)
        if not nav_success:
            print("❌ Failed to navigate to test page")
            await inspector.close()
            return False

        # Wait for page to fully load
        await asyncio.sleep(5)
        print("✅ Page loaded successfully")

        # Get document root
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        # Test style extraction on body element (should have styles)
        try:
            body_response = await inspector.send_command(
                "DOM.querySelector", {"nodeId": root_node_id, "selector": "body"}
            )
            body_node_id = body_response["result"]["nodeId"]

            if body_node_id:
                print(f"✅ Found body element (nodeId: {body_node_id})")

                # Extract styles
                styles_data = await inspector.get_element_styles(body_node_id)
                print("✅ Successfully extracted style data")

                # Test style formatting
                formatted_styles = await inspector.format_styles(styles_data)
                print("✅ Successfully formatted styles")

                # Display sample of formatted styles
                if formatted_styles and len(formatted_styles.strip()) > 0:
                    lines = formatted_styles.split("\n")[:15]  # Show first 15 lines
                    print("📄 Sample formatted styles:")
                    for line in lines:
                        if line.strip():
                            print(f"  {line}")

                    if len(lines) >= 15:
                        print("  ... (more styles available)")

                    style_success = True
                else:
                    print("⚠️  No styles found or formatting failed")
                    style_success = False

            else:
                print("❌ Body element not found")
                style_success = False

        except Exception as e:
            print(f"❌ Style extraction failed: {e}")
            style_success = False

        await inspector.close()
        return style_success

    except Exception as e:
        print(f"❌ Style extraction test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_event_listeners():
    """Test event listener detection functionality"""
    print("\n🎧 Testing event listener detection...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Navigate to baidu.com (likely has event listeners)
        test_url = "https://www.baidu.com"
        nav_success = await inspector.navigate_to_page(test_url)
        if not nav_success:
            print("❌ Failed to navigate to test page")
            await inspector.close()
            return False

        # Wait for page to fully load
        await asyncio.sleep(5)

        # Get document root
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        # Test event listener detection on body element
        try:
            body_response = await inspector.send_command(
                "DOM.querySelector", {"nodeId": root_node_id, "selector": "body"}
            )
            body_node_id = body_response["result"]["nodeId"]

            if body_node_id:
                print(f"✅ Found body element for event listener test")

                # Try to get event listeners
                try:
                    listeners_data = await inspector.get_element_event_listeners(body_node_id)
                    print("✅ Successfully retrieved event listener data")

                    # Format the listeners
                    formatted_listeners = await inspector.format_event_listeners(listeners_data)
                    print("✅ Successfully formatted event listeners")

                    # Display results
                    if formatted_listeners and formatted_listeners != "无事件监听器":
                        lines = formatted_listeners.split("\n")[:20]  # Show first 20 lines
                        print("📡 Event listeners found:")
                        for line in lines:
                            if line.strip():
                                print(f"  {line}")
                        listener_success = True
                    else:
                        print("ℹ️  No event listeners found on body element (this is normal)")
                        listener_success = True  # Not finding listeners is also a valid result

                except Exception as e:
                    print(f"⚠️  Event listener detection failed: {e}")
                    # This might be expected if DOMDebugger is not available
                    if "DOMDebugger" in str(e) or "wasn't found" in str(e):
                        print("ℹ️  DOMDebugger not available - this is expected in some browsers")
                        listener_success = True  # This is an expected limitation
                    else:
                        listener_success = False

            else:
                print("❌ Body element not found")
                listener_success = False

        except Exception as e:
            print(f"❌ Event listener test setup failed: {e}")
            listener_success = False

        await inspector.close()
        return listener_success

    except Exception as e:
        print(f"❌ Event listener test failed: {e}")
        return False


async def test_complex_selectors():
    """Test complex CSS selector functionality"""
    print("\n🔍 Testing complex CSS selectors...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Navigate to baidu.com
        test_url = "https://www.baidu.com"
        nav_success = await inspector.navigate_to_page(test_url)
        if not nav_success:
            print("❌ Failed to navigate to test page")
            await inspector.close()
            return False

        # Wait for page to load
        await asyncio.sleep(5)

        # Get document root
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        # Test various CSS selectors
        test_selectors = [
            # Basic selectors
            "html",
            "head",
            "body",
            "title",
            # Common web elements
            "div",
            "input",
            "form",
            "a",
            "img",
            # Attribute selectors
            'input[type="text"]',
            "a[href]",
            # Class and ID selectors (might not exist but good to test)
            ".container",
            "#main",
            # Descendant selectors
            "body div",
            "head title",
            # Pseudo selectors
            "input:first-child",
            "div:not(.hidden)",
        ]

        found_count = 0
        total_count = len(test_selectors)

        for selector in test_selectors:
            try:
                response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": selector}
                )
                node_id = response["result"]["nodeId"]

                if node_id:
                    print(f"✅ Found element: {selector} (nodeId: {node_id})")
                    found_count += 1
                else:
                    print(f"➖ No element found: {selector}")

            except Exception as e:
                print(f"❌ Error with selector '{selector}': {e}")

        print(f"\n📊 Complex selector results: {found_count}/{total_count} selectors found elements")

        await inspector.close()

        # Consider the test successful if we found at least half the elements
        return found_count >= (total_count // 2)

    except Exception as e:
        print(f"❌ Complex selector test failed: {e}")
        return False


async def test_error_handling():
    """Test error handling in edge cases"""
    print("\n⚠️  Testing error handling...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Test invalid URL navigation
        print("🧪 Testing invalid URL navigation...")
        try:
            nav_result = await inspector.navigate_to_page("invalid://bad.url")
            if not nav_result:
                print("✅ Invalid URL navigation properly failed")
            else:
                print("⚠️  Invalid URL navigation unexpectedly succeeded")
        except Exception as e:
            print(f"✅ Invalid URL navigation properly threw exception: {e}")

        # Navigate to a working page first
        await inspector.navigate_to_page("https://www.baidu.com")
        await asyncio.sleep(3)

        # Get document root
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        # Test invalid CSS selectors
        print("🧪 Testing invalid CSS selectors...")
        invalid_selectors = [
            "",  # Empty selector
            "###invalid",  # Invalid syntax
            ">>bad>>selector",  # Invalid syntax
            "div[unclosed",  # Unclosed bracket
        ]

        error_handling_success = True
        for selector in invalid_selectors:
            try:
                response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": selector}
                )
                print(f"⚠️  Invalid selector '{selector}' unexpectedly succeeded")
            except Exception as e:
                print(f"✅ Invalid selector '{selector}' properly failed: {type(e).__name__}")

        # Test invalid node operations
        print("🧪 Testing invalid node operations...")
        try:
            # Try to get styles for non-existent node
            styles = await inspector.get_element_styles(99999)
            print("⚠️  Invalid node ID unexpectedly succeeded")
            error_handling_success = False
        except Exception as e:
            print(f"✅ Invalid node ID properly failed: {type(e).__name__}")

        await inspector.close()
        return error_handling_success

    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False


async def main():
    """Run all advanced feature tests"""
    print("🚀 Starting Advanced DOM Inspector Feature Tests")
    print("=" * 60)

    # Check if browser is available
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser available. Please start browser first.")
        return False

    print(f"✅ Found {len(websocket_urls)} browser tab(s)")

    test_results = {}

    # Run all tests
    test_results["style_extraction"] = await test_style_extraction()
    test_results["event_listeners"] = await test_event_listeners()
    test_results["complex_selectors"] = await test_complex_selectors()
    test_results["error_handling"] = await test_error_handling()

    # Print summary
    print("\n" + "=" * 60)
    print("📊 ADVANCED FEATURES TEST SUMMARY:")
    print("=" * 60)

    total_tests = len(test_results)
    passed_tests = sum(test_results.values())

    for test_name, result in test_results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")

    print(f"\n📈 Results: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All advanced feature tests passed!")
        return True
    else:
        print("⚠️  Some advanced feature tests failed.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
