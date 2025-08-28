#!/usr/bin/env python3
"""
Test script to verify window detection accuracy
"""

import asyncio
import os
import sys

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs


async def test_window_detection():
    """Test window detection accuracy"""
    print("🖥️  Testing window detection accuracy...")

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

        # Test window detection multiple times
        for i in range(5):
            window_info = inspector.find_chrome_window()
            if window_info:
                x, y, width, height = window_info
                print(f"🔍 Window detection #{i + 1}: pos=({x}, {y}), size={width}x{height}")

                # Check if window size is reasonable
                if width < 100 or height < 100:
                    print(f"❌ Window size seems too small: {width}x{height}")
                elif width > 5000 or height > 5000:
                    print(f"❌ Window size seems too large: {width}x{height}")
                else:
                    print(f"✅ Window size seems reasonable")
            else:
                print(f"❌ Window detection #{i + 1}: No window found")

            await asyncio.sleep(1)

        # Test DPI scaling factor
        scale_factor = inspector.get_display_scale_factor()
        print(f"📏 Display scale factor: {scale_factor}")

        # Test UI offset calculation
        ui_offset = inspector.get_browser_ui_offset(scale_factor)
        print(f"🏗️  Browser UI offset: {ui_offset}px")

        await inspector.close()
        return True

    except Exception as e:
        print(f"❌ Window detection test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run window detection test"""
    print("🖥️  Window Detection Accuracy Test")
    print("=" * 50)

    # Check if browser is available
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser available. Please start browser first.")
        print("Start command: open -a 'Microsoft Edge' --args --remote-debugging-port=9222")
        return False

    print(f"✅ Found {len(websocket_urls)} browser tab(s)")

    # Run the test
    success = await test_window_detection()

    print("\n" + "=" * 50)
    if success:
        print("✅ Window detection test completed")
    else:
        print("❌ Window detection test failed")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
