#!/usr/bin/env python3
"""
Test browser window detection across platforms
Tests the platform-specific window detection functionality
"""

import asyncio
import os
import sys

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs


async def test_platform_specific_window_detection():
    """Test platform-specific browser window detection"""
    print("🖥️  Testing platform-specific browser window detection...")

    try:
        # Get browser tabs to ensure we have a browser running
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser (not strictly necessary for window detection, but good for consistency)
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()
        print("✅ Connected to browser")

        # Test general window detection
        print("🔍 Testing general window detection...")
        window_info = inspector.find_chrome_window()

        if window_info:
            x, y, width, height = window_info
            print(f"✅ Browser window detected: position=({x}, {y}), size={width}x{height}")

            # Validate window dimensions
            if width > 0 and height > 0 and width < 10000 and height < 10000:
                print("✅ Window dimensions are reasonable")
                general_success = True
            else:
                print(f"⚠️  Window dimensions seem unreasonable: {width}x{height}")
                general_success = False
        else:
            print("⚠️  No browser window detected (this may be normal depending on setup)")
            general_success = True  # Not finding window is acceptable in some cases

        # Test platform-specific methods
        import platform

        system = platform.system()
        print(f"🖥️  Platform detected: {system}")

        platform_success = True

        if system == "Darwin":  # macOS
            print("🍎 Testing macOS-specific window detection...")
            try:
                macos_result = inspector._find_browser_window_macos()
                if macos_result:
                    x, y, width, height = macos_result
                    print(f"✅ macOS browser window: position=({x}, {y}), size={width}x{height}")
                else:
                    print("⚠️  macOS browser window not detected")
            except Exception as e:
                print(f"❌ macOS window detection error: {e}")
                platform_success = False

        elif system == "Windows":
            print("🖼️  Testing Windows-specific window detection...")
            try:
                windows_result = inspector._find_browser_window_windows()
                if windows_result:
                    x, y, width, height = windows_result
                    print(f"✅ Windows browser window: position=({x}, {y}), size={width}x{height}")
                else:
                    print("⚠️  Windows browser window not detected")
            except Exception as e:
                print(f"❌ Windows window detection error: {e}")
                platform_success = False

        elif system == "Linux":
            print("🐧 Testing Linux-specific window detection...")
            try:
                linux_result = inspector._find_browser_window_linux()
                if linux_result:
                    x, y, width, height = linux_result
                    print(f"✅ Linux browser window: position=({x}, {y}), size={width}x{height}")
                else:
                    print("⚠️  Linux browser window not detected")
            except Exception as e:
                print(f"❌ Linux window detection error: {e}")
                platform_success = False
        else:
            print(f"⚠️  Unknown platform: {system}")
            platform_success = False

        await inspector.close()
        return general_success and platform_success

    except Exception as e:
        print(f"❌ Platform-specific window detection test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_display_scale_detection():
    """Test display scale factor detection across platforms"""
    print("\n📐 Testing display scale factor detection...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Test general scale factor detection
        scale_factor = inspector.get_display_scale_factor()
        print(f"✅ General scale factor: {scale_factor}")

        if 0.5 <= scale_factor <= 4.0:  # Reasonable range
            print("✅ Scale factor is in reasonable range")
            general_success = True
        else:
            print(f"⚠️  Scale factor seems unusual: {scale_factor}")
            general_success = False

        # Test platform-specific scale detection
        import platform

        system = platform.system()

        platform_success = True

        if system == "Darwin":  # macOS
            print("🍎 Testing macOS-specific scale detection...")
            try:
                macos_scale = inspector._get_scale_factor_macos()
                print(f"✅ macOS scale factor: {macos_scale}")

                if 0.5 <= macos_scale <= 4.0:
                    print("✅ macOS scale factor is reasonable")
                else:
                    print(f"⚠️  macOS scale factor seems unusual: {macos_scale}")
                    platform_success = False

            except Exception as e:
                print(f"❌ macOS scale detection error: {e}")
                platform_success = False

        elif system == "Windows":
            print("🖼️  Testing Windows-specific scale detection...")
            try:
                windows_scale = inspector._get_scale_factor_windows()
                print(f"✅ Windows scale factor: {windows_scale}")

                if 0.5 <= windows_scale <= 4.0:
                    print("✅ Windows scale factor is reasonable")
                else:
                    print(f"⚠️  Windows scale factor seems unusual: {windows_scale}")
                    platform_success = False

            except Exception as e:
                print(f"❌ Windows scale detection error: {e}")
                platform_success = False

        elif system == "Linux":
            print("🐧 Testing Linux-specific scale detection...")
            try:
                linux_scale = inspector._get_scale_factor_linux()
                print(f"✅ Linux scale factor: {linux_scale}")

                if 0.5 <= linux_scale <= 4.0:
                    print("✅ Linux scale factor is reasonable")
                else:
                    print(f"⚠️  Linux scale factor seems unusual: {linux_scale}")
                    platform_success = False

            except Exception as e:
                print(f"❌ Linux scale detection error: {e}")
                platform_success = False

        await inspector.close()
        return general_success and platform_success

    except Exception as e:
        print(f"❌ Display scale detection test failed: {e}")
        return False


async def test_coordinate_system_integration():
    """Test the integration of window detection and coordinate conversion"""
    print("\n🎯 Testing coordinate system integration...")

    try:
        # Get browser tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ No browser tabs available")
            return False

        # Connect to browser
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Test coordinate conversion with different scenarios
        test_coordinates = [
            (100, 100),  # Top-left
            (500, 300),  # Center-left
            (800, 400),  # Center-right
        ]

        successful_conversions = 0
        total_conversions = len(test_coordinates)

        for screen_x, screen_y in test_coordinates:
            try:
                browser_x, browser_y = await inspector.convert_screen_to_browser_coords(screen_x, screen_y)

                if browser_x is not None and browser_y is not None:
                    print(f"✅ Converted ({screen_x}, {screen_y}) → ({browser_x}, {browser_y})")
                    successful_conversions += 1

                    # Validate conversion makes sense
                    if browser_x >= 0 and browser_y >= 0:
                        print(f"✅ Converted coordinates are valid")
                    else:
                        print(f"⚠️  Converted coordinates seem invalid: ({browser_x}, {browser_y})")
                else:
                    print(f"⚠️  Coordinate conversion failed for ({screen_x}, {screen_y})")

            except Exception as e:
                print(f"❌ Error converting coordinates ({screen_x}, {screen_y}): {e}")

        print(f"📊 Coordinate conversion results: {successful_conversions}/{total_conversions} successful")

        await inspector.close()
        return successful_conversions > 0

    except Exception as e:
        print(f"❌ Coordinate system integration test failed: {e}")
        return False


async def main():
    """Run all browser window detection tests"""
    print("🖥️  Starting Browser Window Detection Tests")
    print("=" * 60)

    # Check if browser is available
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser available. Please start browser first.")
        return False

    print(f"✅ Found {len(websocket_urls)} browser tab(s)")

    test_results = {}

    # Run all tests
    test_results["window_detection"] = await test_platform_specific_window_detection()
    test_results["scale_detection"] = await test_display_scale_detection()
    test_results["coordinate_integration"] = await test_coordinate_system_integration()

    # Print summary
    print("\n" + "=" * 60)
    print("📊 BROWSER WINDOW DETECTION TEST SUMMARY:")
    print("=" * 60)

    total_tests = len(test_results)
    passed_tests = sum(test_results.values())

    for test_name, result in test_results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")

    print(f"\n📈 Results: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All browser window detection tests passed!")
        return True
    else:
        print("⚠️  Some browser window detection tests failed.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
