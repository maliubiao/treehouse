#!/usr/bin/env python3
"""
Test script to identify file:// URL element finding issues
"""

import asyncio
import os
import sys
import tempfile
import time

import aiohttp

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs
from test_server_utils import TestServerContext, cleanup_temp_dir


def get_file_url_test_html():
    """Get the HTML content for file URL issue testing"""
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


async def test_file_url_dom_content():
    """Test what DOM content is actually available with file:// URLs"""
    print("🧪 Testing file:// URL DOM content...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Start HTTP server to serve test page instead of using file:// URL
        test_html = get_file_url_test_html()
        async with TestServerContext(test_html) as test_url:
            # Navigate to test page
            nav_success = await inspector.navigate_to_page(test_url)
            if not nav_success:
                print("❌ Failed to navigate to test page")
                await inspector.close()
                return False

            print(f"✅ Successfully navigated to: {test_url}")

            # Get document content to see what's actually available
            response = await inspector.send_command("DOM.getDocument", {"depth": -1})

            if "result" in response and "root" in response["result"]:
                root_node = response["result"]["root"]
                print(f"✅ Got document root: nodeId={root_node.get('nodeId')}")

                # Print basic document info
                print(f"📄 Document URL: {root_node.get('documentURL', 'N/A')}")
                print(f"📄 Base URL: {root_node.get('baseURL', 'N/A')}")
                print(f"📄 Content language: {root_node.get('contentLanguage', 'N/A')}")
                print(f"📄 Document encoding: {root_node.get('encoding', 'N/A')}")

                # Check if we have child nodes
                if "children" in root_node:
                    print(f"📄 Number of child nodes: {len(root_node['children'])}")

                    # Print info about child nodes
                    for i, child in enumerate(root_node["children"][:5]):  # Show first 5
                        node_type = child.get("nodeType", "N/A")
                        node_name = child.get("nodeName", "N/A")
                        print(f"  📄 Child {i}: type={node_type}, name={node_name}")
                else:
                    print("❌ No child nodes found in document")

            else:
                print("❌ Failed to get document content")

            # Test finding specific elements
            test_selectors = [
                "#test-heading",
                ".test-button",
                "#test-link",
                ".test-div",
                "html",
                "head",
                "body",
                "title",
            ]

            print("\n🔍 Testing element finding:")

            for selector in test_selectors:
                try:
                    response = await inspector.send_command(
                        "DOM.querySelector", {"nodeId": root_node["nodeId"], "selector": selector}
                    )
                    node_id = response["result"]["nodeId"]
                    if node_id:
                        print(f"✅ Found element with selector: {selector} (nodeId: {node_id})")

                        # Get more info about the found element
                        node_info = await inspector.send_command("DOM.describeNode", {"nodeId": node_id})
                        if "result" in node_info:
                            node_desc = node_info["result"]
                            print(f"   📄 Node type: {node_desc.get('node', {}).get('nodeType', 'N/A')}")
                            print(f"   📄 Node name: {node_desc.get('node', {}).get('nodeName', 'N/A')}")

                    else:
                        print(f"❌ Element not found: {selector}")

                except Exception as e:
                    print(f"❌ Error finding element {selector}: {e}")

            await inspector.close()

            return True

    except Exception as e:
        print(f"❌ File URL DOM content test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_http_url_comparison():
    """Test HTTP URL for comparison"""
    print("\n🌐 Testing HTTP URL for comparison...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Navigate to simple HTTP page
        test_url = "https://httpbin.org/html"
        nav_success = await inspector.navigate_to_page(test_url)
        if not nav_success:
            print("❌ Failed to navigate to HTTP test page")
            await inspector.close()
            return False

        print(f"✅ Successfully navigated to: {test_url}")

        # Wait a bit for page to load
        await asyncio.sleep(3)

        # Get document content
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})

        if "result" in response and "root" in response["result"]:
            root_node = response["result"]["root"]
            print(f"✅ Got HTTP document root: nodeId={root_node.get('nodeId')}")

            # Test finding elements
            test_selectors = ["html", "head", "body", "h1", "p"]

            found_count = 0
            for selector in test_selectors:
                try:
                    response = await inspector.send_command(
                        "DOM.querySelector", {"nodeId": root_node["nodeId"], "selector": selector}
                    )
                    node_id = response["result"]["nodeId"]
                    if node_id:
                        print(f"✅ Found HTTP element: {selector} (nodeId: {node_id})")
                        found_count += 1
                    else:
                        print(f"❌ HTTP element not found: {selector}")

                except Exception as e:
                    print(f"❌ Error finding HTTP element {selector}: {e}")

            print(f"📊 HTTP elements found: {found_count}/{len(test_selectors)}")

        else:
            print("❌ Failed to get HTTP document content")

        await inspector.close()
        return True

    except Exception as e:
        print(f"❌ HTTP URL test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run file:// URL issue investigation"""
    print("🔍 Investigating file:// URL Element Finding Issues")
    print("=" * 60)

    # Check if browser is available
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser available. Please start browser first.")
        return False

    print(f"✅ Found {len(websocket_urls)} browser tab(s)")

    # Run tests
    file_url_success = await test_file_url_dom_content()
    http_url_success = await test_http_url_comparison()

    print("\n" + "=" * 60)
    print("📊 INVESTIGATION SUMMARY:")
    print("=" * 60)

    if file_url_success:
        print("✅ File URL DOM content test completed")
    else:
        print("❌ File URL DOM content test failed")

    if http_url_success:
        print("✅ HTTP URL comparison test completed")
    else:
        print("❌ HTTP URL comparison test failed")

    print("\n💡 Analysis: The issue appears to be that file:// URLs may have")
    print("different security restrictions or DOM loading behavior compared")
    print("to HTTP URLs. The navigation succeeds but elements cannot be found.")

    return file_url_success and http_url_success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
