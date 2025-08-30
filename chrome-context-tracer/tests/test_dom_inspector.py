#!/usr/bin/env python3
"""
Test script for DOM Inspector functionality using Python tracer
This script tests the key functions with a new browser profile
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chrome_context_tracer import DOMInspector, launch_browser_with_debugging
from chrome_context_tracer.browser_manager import find_chrome_tabs
from chrome_context_tracer.utils import find_free_safe_port
from test_server_utils import TestServerContext


async def setup_test_page_and_inspector():
    """Create test page and return inspector connected to it"""
    # Get browser tabs
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        return None, None, None

    # Connect to inspector
    inspector = DOMInspector(websocket_urls[0])
    await inspector.connect()

    # Create test server context
    test_html = get_test_html()
    port = find_free_safe_port()
    server_context = TestServerContext(test_html, port=port)
    test_url = await server_context.__aenter__()

    nav_success = await inspector.navigate_to_page(test_url)
    if not nav_success:
        await inspector.close()
        await server_context.__aexit__(None, None, None)
        return None, None, None

    return inspector, test_url, server_context


def get_test_html():
    """Get the test HTML content for DOM Inspector tests"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>DOM Inspector Test Page</title>
    <style>
        .test-button {
            background-color: #007bff;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        .test-button:hover {
            background-color: #0056b3;
        }
        .test-div {
            margin: 20px;
            padding: 15px;
            border: 2px solid #ddd;
            background-color: #f8f9fa;
        }
        #test-heading {
            color: #333;
            font-family: Arial, sans-serif;
        }
    </style>
</head>
<body>
    <div class="test-div">
        <h1 id="test-heading">DOM Inspector Test</h1>
        <button class="test-button" onclick="handleClick()" id="test-button">
            Test Button
        </button>
        <p>This is a test paragraph with <a href="#" id="test-link">a link</a>.</p>
    </div>

    <script>
        function handleClick() {
            console.log('Button clicked!');
        }
        
        // Add event listeners for testing
        document.getElementById('test-link').addEventListener('click', function(e) {
            e.preventDefault();
            console.log('Link clicked!');
        });
        
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                console.log('Escape pressed');
            }
        });
    </script>
</body>
</html>
"""


async def test_browser_connection():
    """Test browser connection with new profile"""
    print("🧪 Testing browser connection with new profile...")

    try:
        # Launch browser with new profile (use Edge since Chrome is not installed)
        success, _ = await launch_browser_with_debugging("edge", 9222, return_process_info=True)
        if not success:
            print("❌ Failed to launch browser")
            return False

        # Wait for browser to start
        await asyncio.sleep(3)

        # Find Chrome tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs found")
            return False

        print(f"✅ Found {len(websocket_urls)} browser tab(s)")

        # Test navigation to our test page using HTTP server
        test_html = get_test_html()
        port = find_free_safe_port()
        async with TestServerContext(test_html, port=port) as test_url:
            print(f"🧪 Testing navigation to test page: {test_url}")
            inspector = DOMInspector(websocket_urls[0])
            await inspector.connect()

            # Navigate to test page
            nav_success = await inspector.navigate_to_page(test_url)
            if not nav_success:
                print("❌ Failed to navigate to test page")
                await inspector.close()
                return False

            print("✅ Successfully navigated to test page")
            await inspector.close()
            return True

    except Exception as e:
        print(f"❌ Browser connection test failed: {e}")
        return False


async def test_dom_inspector_connection():
    """Test DOMInspector connection and basic functionality"""
    print("\n🧪 Testing DOMInspector connection...")

    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser tabs available for testing")
        return False

    try:
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Test basic CDP commands
        response = await inspector.send_command("Target.getTargets", use_session=False)
        targets = response.get("result", {}).get("targetInfos", [])

        print(f"✅ Connected successfully, found {len(targets)} targets")

        await inspector.close()
        return True

    except Exception as e:
        print(f"❌ DOMInspector connection test failed: {e}")
        return False


async def test_element_finding():
    """Test element finding functionality"""
    print("\n🧪 Testing element finding...")

    try:
        inspector, test_url, server_context = await setup_test_page_and_inspector()
        if not inspector:
            print("❌ Failed to setup test page and inspector")
            return False

        # Get document
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        # Test finding elements by selector
        test_selectors = ["#test-heading", ".test-button", "#test-link", ".test-div"]

        found_elements = 0
        for selector in test_selectors:
            try:
                response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": selector}
                )
                node_id = response["result"]["nodeId"]
                if node_id:
                    print(f"✅ Found element with selector: {selector}")
                    found_elements += 1
                else:
                    print(f"❌ Element not found: {selector}")
            except Exception as e:
                print(f"❌ Error finding element {selector}: {e}")

        print(f"✅ Found {found_elements}/{len(test_selectors)} elements")

        await inspector.close()

        # Cleanup server
        await server_context.__aexit__(None, None, None)

        return found_elements > 0

    except Exception as e:
        print(f"❌ Element finding test failed: {e}")
        return False


async def test_style_extraction():
    """Test style extraction functionality"""
    print("\n🧪 Testing style extraction...")

    try:
        inspector, test_url, server_context = await setup_test_page_and_inspector()
        if not inspector:
            print("❌ Failed to setup test page and inspector")
            return False

        # Find a test element
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        response = await inspector.send_command(
            "DOM.querySelector", {"nodeId": root_node_id, "selector": ".test-button"}
        )
        node_id = response["result"]["nodeId"]

        if not node_id:
            print("❌ Test button not found")
            return False

        # Get styles
        styles_data = await inspector.get_element_styles(node_id)

        # Format and check styles
        formatted_styles = await inspector.format_styles(styles_data)

        # Check if we got some style information
        if "background-color" in formatted_styles.lower():
            print("✅ Style extraction successful")
            print("Sample styles:")
            lines = formatted_styles.split("\n")[:10]  # Show first 10 lines
            for line in lines:
                if line.strip():
                    print(f"  {line}")
            success = True
        else:
            print("❌ No style information extracted")
            success = False

        await inspector.close()

        # Cleanup server
        await server_context.__aexit__(None, None, None)

        return success

    except Exception as e:
        print(f"❌ Style extraction test failed: {e}")
        return False


async def test_event_listener_extraction():
    """Test event listener extraction functionality"""
    print("\n🧪 Testing event listener extraction...")

    try:
        inspector, test_url, server_context = await setup_test_page_and_inspector()
        if not inspector:
            print("❌ Failed to setup test page and inspector")
            return False

        # Find a test element with event listeners
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        response = await inspector.send_command("DOM.querySelector", {"nodeId": root_node_id, "selector": "#test-link"})
        node_id = response["result"]["nodeId"]

        if not node_id:
            print("❌ Test link not found")
            return False

        # Get event listeners
        listeners_data = await inspector.get_element_event_listeners(node_id)

        # Format and check listeners
        formatted_listeners = await inspector.format_event_listeners(listeners_data)

        if (
            formatted_listeners
            and "无事件监听器" not in formatted_listeners
            and "No event listeners" not in formatted_listeners
        ):
            print("✅ Event listener extraction successful")
            print("Sample event listeners:")
            lines = formatted_listeners.split("\n")[:8]  # Show first 8 lines
            for line in lines:
                if line.strip():
                    print(f"  {line}")
            success = True
        else:
            print("❌ No event listeners found")
            success = False

        await inspector.close()

        # Cleanup server
        await server_context.__aexit__(None, None, None)

        return success

    except Exception as e:
        print(f"❌ Event listener extraction test failed: {e}")
        return False


async def main():
    """Run all tests"""
    print("🚀 Starting DOM Inspector Tests with New Browser Profile")
    print("=" * 60)

    test_results = {}

    # Run tests
    test_results["browser_connection"] = await test_browser_connection()
    test_results["dom_inspector_connection"] = await test_dom_inspector_connection()
    test_results["element_finding"] = await test_element_finding()
    test_results["style_extraction"] = await test_style_extraction()
    test_results["event_listener_extraction"] = await test_event_listener_extraction()

    # Print summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY:")
    print("=" * 60)

    total_tests = len(test_results)
    passed_tests = sum(test_results.values())

    for test_name, result in test_results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")

    print(f"\n📈 Results: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All tests passed!")
        return True
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
