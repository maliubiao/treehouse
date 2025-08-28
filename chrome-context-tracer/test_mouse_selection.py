#!/usr/bin/env python3
"""
Test script for mouse pointer selection functionality
This script tests the mouse selection feature with tracing
"""

import asyncio
import os
import sys
import tempfile

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs, launch_browser_with_debugging
from test_server_utils import TestServerContext, cleanup_temp_dir


def get_mouse_test_html():
    """Get the HTML content for mouse selection testing"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Mouse Selection Test Page</title>
    <style>
        body {
            margin: 0;
            padding: 20px;
            font-family: Arial, sans-serif;
        }
        
        .test-element {
            width: 100px;
            height: 50px;
            margin: 10px;
            padding: 10px;
            border: 2px solid #007bff;
            background-color: #f8f9fa;
            cursor: pointer;
            text-align: center;
            line-height: 50px;
        }
        
        .test-element:hover {
            background-color: #e9ecef;
            border-color: #0056b3;
        }
        
        #element1 { position: absolute; left: 50px; top: 50px; }
        #element2 { position: absolute; left: 200px; top: 100px; }
        #element3 { position: absolute; left: 350px; top: 150px; }
        #element4 { position: absolute; left: 500px; top: 200px; }
    </style>
</head>
<body>
    <h1>Mouse Selection Test</h1>
    <p>Move mouse over elements and press 'm' to select</p>
    
    <div class="test-element" id="element1">Element 1</div>
    <div class="test-element" id="element2">Element 2</div>
    <div class="test-element" id="element3">Element 3</div>
    <div class="test-element" id="element4">Element 4</div>
    
    <script>
        // Add click handlers for testing
        document.querySelectorAll('.test-element').forEach(el => {
            el.addEventListener('click', function() {
                console.log('Element clicked:', this.id);
            });
        });
        
        // Log element positions on load
        window.addEventListener('load', function() {
            console.log('=== Mouse Selection Test Page Loaded ===');
            document.querySelectorAll('.test-element').forEach(el => {
                const rect = el.getBoundingClientRect();
                console.log(`Element ${el.id}:`, {
                    cssPosition: {
                        left: el.style.left,
                        top: el.style.top
                    },
                    boundingRect: {
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height
                    }
                });
            });
        });
    </script>
</body>
</html>
"""


async def test_mouse_selection():
    """Test mouse pointer selection functionality"""
    print("🖱️  Testing mouse pointer selection...")

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

        # Start HTTP server to serve test page
        test_html = get_mouse_test_html()
        async with TestServerContext(test_html) as test_url:
            print(f"📄 Created test page: {test_url}")

            # Navigate to test page
            nav_success = await inspector.navigate_to_page(test_url)
            if not nav_success:
                print("❌ Failed to navigate to test page")
                await inspector.close()
                return False

            print("✅ Test page loaded")

            # Test mouse selection using manual coordinate input instead of keyboard library
            print("\n🎯 Starting mouse selection test...")
            print("Please move mouse over an element and note its position")
            print("We'll use a fixed test position for this demonstration")

            # Use coordinates within the browser window content area
            # Browser window is at (2179, 25) with size (1920, 997)
            # UI offset is approximately 120px (address bar + tabs)
            # So content area starts at window_y + ui_offset
            window_x, window_y, window_width, window_height = 2179, 25, 1920, 997
            ui_offset = 120  # Estimated browser UI height

            # Calculate coordinates inside the content area
            test_x = window_x + 100  # 100px from left edge of window
            test_y = window_y + ui_offset + 100  # 100px from top of content area

            print(f"Using test coordinates: ({test_x}, {test_y})")
            print(f"Window: ({window_x}, {window_y}), Size: {window_width}x{window_height}")
            print(f"UI offset: {ui_offset}")

            # Convert to browser coordinates and get node
            browser_x, browser_y = await inspector.convert_screen_to_browser_coords(test_x, test_y)
            if browser_x is not None and browser_y is not None:
                print(f"Converted to browser coordinates: ({browser_x}, {browser_y})")
                node_id = await inspector.get_node_for_location(browser_x, browser_y)
            else:
                node_id = None

            if node_id:
                print(f"✅ Successfully selected element with nodeId: {node_id}")

                # Get element info
                html_content = await inspector.get_element_html(node_id)
                print(f"📝 Selected element HTML:\n{html_content}")

                # Get styles
                styles_data = await inspector.get_element_styles(node_id)
                formatted_styles = await inspector.format_styles(styles_data)
                print(f"🎨 Selected element styles:\n{formatted_styles}")

                success = True
            else:
                print("❌ No element selected or selection cancelled")
                success = False

            await inspector.close()

            return success

    except Exception as e:
        print(f"❌ Mouse selection test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Main test function"""
    print("🖱️  Mouse Pointer Selection Test")
    print("=" * 50)

    # Check if browser is available
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser available. Please start browser first.")
        print("Start command: open -a 'Microsoft Edge' --args --remote-debugging-port=9222")
        return False

    print(f"✅ Found {len(websocket_urls)} browser tab(s)")

    # Run the test
    success = await test_mouse_selection()

    print("\n" + "=" * 50)
    if success:
        print("✅ Mouse selection test completed successfully")
    else:
        print("❌ Mouse selection test failed")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
