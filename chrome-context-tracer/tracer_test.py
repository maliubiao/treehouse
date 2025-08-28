#!/usr/bin/env python3
"""
Comprehensive tracer test for DOM Inspector functionality
Uses Python tracer to test key functions with new browser profile
"""

import asyncio
import os
import sys
import tempfile
import time
from urllib.parse import urlparse

import aiohttp

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs, inspect_element_styles, launch_browser_with_debugging


async def create_test_page():
    """Create a simple test HTML page with various elements to inspect"""
    test_html = """
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

    # Create temporary HTML file
    temp_dir = tempfile.mkdtemp(prefix="dom_test_")
    html_file = os.path.join(temp_dir, "test_page.html")

    with open(html_file, "w") as f:
        f.write(test_html)

    return f"file://{html_file}", temp_dir


async def test_dom_inspector_connection():
    """Test DOMInspector connection - this will be traced"""
    print("🧪 Testing DOMInspector connection...")

    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser tabs available for testing")
        return False

    try:
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Test basic CDP commands
        response = await inspector.send_command("Target.getTargets")
        targets = response.get("result", {}).get("targetInfos", [])

        print(f"✅ Connected successfully, found {len(targets)} targets")

        await inspector.close()
        return True

    except Exception as e:
        print(f"❌ DOMInspector connection test failed: {e}")
        return False


async def test_element_finding():
    """Test element finding functionality - this will be traced"""
    print("🧪 Testing element finding...")

    try:
        # Create test page
        test_url, temp_dir = await create_test_page()

        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect and navigate to test page
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        nav_success = await inspector.navigate_to_page(test_url)
        if not nav_success:
            print("❌ Failed to navigate to test page")
            await inspector.close()
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

        # Cleanup temp directory
        import shutil

        try:
            shutil.rmtree(temp_dir)
        except:
            pass

        return found_elements > 0

    except Exception as e:
        print(f"❌ Element finding test failed: {e}")
        return False


async def test_style_extraction():
    """Test style extraction functionality - this will be traced"""
    print("🧪 Testing style extraction...")

    try:
        # Create test page
        test_url, temp_dir = await create_test_page()

        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect and navigate to test page
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        nav_success = await inspector.navigate_to_page(test_url)
        if not nav_success:
            print("❌ Failed to navigate to test page")
            await inspector.close()
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

        # Cleanup temp directory
        import shutil

        try:
            shutil.rmtree(temp_dir)
        except:
            pass

        return success

    except Exception as e:
        print(f"❌ Style extraction test failed: {e}")
        return False


async def detect_available_browsers():
    """Detect which browsers are available on the system"""
    import subprocess

    available_browsers = []

    # Check for Chrome
    try:
        subprocess.check_output(["which", "google-chrome"], stderr=subprocess.DEVNULL)
        available_browsers.append("chrome")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Check for Chrome on macOS
    try:
        subprocess.check_output(["which", "open"], stderr=subprocess.DEVNULL)
        # Check if Chrome app exists
        result = subprocess.run(["ls", "/Applications/Google Chrome.app"], capture_output=True, text=True)
        if result.returncode == 0:
            available_browsers.append("chrome")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Check for Edge
    try:
        subprocess.check_output(["which", "microsoft-edge"], stderr=subprocess.DEVNULL)
        available_browsers.append("edge")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Check for Edge on macOS
    try:
        subprocess.check_output(["which", "open"], stderr=subprocess.DEVNULL)
        # Check if Edge app exists
        result = subprocess.run(["ls", "/Applications/Microsoft Edge.app"], capture_output=True, text=True)
        if result.returncode == 0:
            available_browsers.append("edge")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return available_browsers


async def main():
    """Main test function that will be traced"""
    print("🚀 Starting DOM Inspector Tracer Tests")
    print("=" * 50)

    # Detect available browsers
    available_browsers = await detect_available_browsers()

    if not available_browsers:
        print("❌ No supported browsers found (Chrome/Edge)")
        print("Please install Chrome or Edge, or manually start a browser with:")
        print("  chrome --remote-debugging-port=9222")
        print("  or")
        print("  msedge --remote-debugging-port=9222")
        return False

    print(f"✅ Found available browsers: {', '.join(available_browsers)}")

    # Try to launch browser with new profile
    browser_launched = False
    for browser in available_browsers:
        print(f"🧪 Trying to launch {browser} with new profile...")
        success = await launch_browser_with_debugging(browser, 9222)
        if success:
            browser_launched = True
            print(f"✅ Successfully launched {browser}")
            break
        else:
            print(f"❌ Failed to launch {browser}")

    if not browser_launched:
        print("⚠️  Could not auto-launch browser, checking for manually started browsers...")

        # Check if there are already browser tabs available
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if websocket_urls:
            print(f"✅ Found existing browser tabs: {len(websocket_urls)}")
            browser_launched = True
        else:
            print("❌ No browsers available for testing")
            print("Please manually start a browser with remote debugging:")
            print("  chrome --remote-debugging-port=9222")
            print("  or")
            print("  msedge --remote-debugging-port=9222")
            return False

    # Wait for browser to start
    await asyncio.sleep(3)

    test_results = {}

    # Run tests that will be traced
    test_results["dom_inspector_connection"] = await test_dom_inspector_connection()
    test_results["element_finding"] = await test_element_finding()
    test_results["style_extraction"] = await test_style_extraction()

    # Print summary
    print("\n" + "=" * 50)
    print("📊 TRACER TEST SUMMARY:")
    print("=" * 50)

    total_tests = len(test_results)
    passed_tests = sum(test_results.values())

    for test_name, result in test_results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")

    print(f"\n📈 Results: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All tracer tests passed!")
        return True
    else:
        print("⚠️  Some tracer tests failed.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
