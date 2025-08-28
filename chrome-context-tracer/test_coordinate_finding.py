#!/usr/bin/env python3
"""
Test coordinate-based element finding functionality
Tests the get_node_for_location feature and coordinate conversion
"""

import asyncio
import os
import sys
import time

import aiohttp

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs


async def test_coordinate_element_finding():
    """Test finding elements by coordinates"""
    print("🎯 Testing coordinate-based element finding...")

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

        # Navigate to baidu.com (known to have elements at various coordinates)
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

        # Test various coordinate positions
        test_coordinates = [
            (100, 100),  # Top-left area
            (200, 200),  # Upper area
            (400, 300),  # Center area
            (600, 400),  # Right-center area
            (300, 500),  # Lower area
        ]

        found_elements = 0
        for x, y in test_coordinates:
            try:
                print(f"🎯 Testing coordinate ({x}, {y})...")
                node_id = await inspector.get_node_for_location(x, y)

                if node_id:
                    print(f"✅ Found element at ({x}, {y}): nodeId={node_id}")
                    found_elements += 1

                    # Try to get element info
                    try:
                        node_info = await inspector.send_command("DOM.describeNode", {"nodeId": node_id})
                        if "result" in node_info:
                            node_desc = node_info["result"]["node"]
                            node_name = node_desc.get("nodeName", "unknown")
                            print(f"   📄 Element: {node_name}")

                            # If it has attributes, show some
                            if "attributes" in node_desc and node_desc["attributes"]:
                                attrs = node_desc["attributes"]
                                # Attributes come as [name1, value1, name2, value2, ...]
                                attr_pairs = []
                                for i in range(0, len(attrs), 2):
                                    if i + 1 < len(attrs):
                                        attr_pairs.append(f"{attrs[i]}='{attrs[i + 1]}'")

                                if attr_pairs:
                                    print(f"   📄 Attributes: {' '.join(attr_pairs[:3])}")  # Show first 3

                    except Exception as e:
                        print(f"   ⚠️  Could not get element details: {e}")

                else:
                    print(f"➖ No element found at ({x}, {y})")

            except Exception as e:
                print(f"❌ Error testing coordinate ({x}, {y}): {e}")

        print(f"📊 Coordinate finding results: {found_elements}/{len(test_coordinates)} coordinates found elements")

        await inspector.close()
        return found_elements > 0

    except Exception as e:
        print(f"❌ Coordinate element finding test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_coordinate_conversion():
    """Test coordinate conversion functionality"""
    print("\n🔄 Testing coordinate conversion...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Test display scale factor detection
        try:
            scale_factor = inspector.get_display_scale_factor()
            print(f"✅ Display scale factor: {scale_factor}")

            if scale_factor > 0 and scale_factor <= 4.0:  # Reasonable range
                print("✅ Scale factor is in reasonable range")
                scale_success = True
            else:
                print(f"⚠️  Scale factor seems unusual: {scale_factor}")
                scale_success = False

        except Exception as e:
            print(f"❌ Scale factor detection failed: {e}")
            scale_success = False

        # Test browser window detection
        try:
            window_info = inspector.find_chrome_window()
            if window_info:
                x, y, width, height = window_info
                print(f"✅ Browser window detected: pos=({x}, {y}), size={width}x{height}")

                if width > 0 and height > 0:
                    print("✅ Window dimensions are valid")
                    window_success = True
                else:
                    print("⚠️  Window dimensions seem invalid")
                    window_success = False
            else:
                print("⚠️  Browser window not detected (this may be normal)")
                window_success = True  # Not finding window is acceptable

        except Exception as e:
            print(f"❌ Browser window detection failed: {e}")
            window_success = False

        # Test coordinate conversion with sample coordinates
        try:
            screen_coords = [(500, 300), (800, 400), (1000, 500)]
            conversion_success = True

            for screen_x, screen_y in screen_coords:
                browser_x, browser_y = await inspector.convert_screen_to_browser_coords(screen_x, screen_y)
                if browser_x is not None and browser_y is not None:
                    print(f"✅ Converted screen ({screen_x}, {screen_y}) → browser ({browser_x}, {browser_y})")
                else:
                    print(f"⚠️  Coordinate conversion failed for ({screen_x}, {screen_y})")
                    conversion_success = False

        except Exception as e:
            print(f"❌ Coordinate conversion test failed: {e}")
            conversion_success = False

        await inspector.close()
        return scale_success and window_success and conversion_success

    except Exception as e:
        print(f"❌ Coordinate conversion test failed: {e}")
        return False


async def test_browser_ui_offset():
    """Test browser UI offset calculation"""
    print("\n🏗️  Testing browser UI offset calculation...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Test UI offset calculation with different scale factors
        test_scales = [1.0, 1.25, 1.5, 2.0]

        for scale in test_scales:
            ui_offset = inspector.get_browser_ui_offset(scale)
            print(f"✅ UI offset for scale {scale}: {ui_offset}px")

            if ui_offset > 0 and ui_offset < 500:  # Reasonable range
                print(f"✅ UI offset is reasonable for scale {scale}")
            else:
                print(f"⚠️  UI offset seems unusual for scale {scale}: {ui_offset}")

        await inspector.close()
        return True

    except Exception as e:
        print(f"❌ Browser UI offset test failed: {e}")
        return False


async def main():
    """Run all coordinate-based tests"""
    print("🎯 Starting Coordinate-Based Element Finding Tests")
    print("=" * 60)

    # Check if browser is available
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser available. Please start browser first.")
        return False

    print(f"✅ Found {len(websocket_urls)} browser tab(s)")

    test_results = {}

    # Run all tests
    test_results["coordinate_finding"] = await test_coordinate_element_finding()
    test_results["coordinate_conversion"] = await test_coordinate_conversion()
    test_results["ui_offset"] = await test_browser_ui_offset()

    # Print summary
    print("\n" + "=" * 60)
    print("📊 COORDINATE FINDING TEST SUMMARY:")
    print("=" * 60)

    total_tests = len(test_results)
    passed_tests = sum(test_results.values())

    for test_name, result in test_results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")

    print(f"\n📈 Results: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All coordinate finding tests passed!")
        return True
    else:
        print("⚠️  Some coordinate finding tests failed.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
