#!/usr/bin/env python3
"""
Manual browser test - start Chrome manually and test connection
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


async def test_browser_connection_manual():
    """Test browser connection manually (assumes Chrome is already running)"""
    print("🧪 Testing browser connection (manual mode)...")
    print("Please ensure Chrome is running with: chrome --remote-debugging-port=9222")

    try:
        # Try to find Chrome tabs
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)

        if not websocket_urls:
            print("❌ No browser tabs found")
            print("Make sure Chrome is running with: chrome --remote-debugging-port=9222")
            return False

        print(f"✅ Found {len(websocket_urls)} browser tab(s)")
        for url in websocket_urls:
            print(f"  - {url}")

        return True

    except Exception as e:
        print(f"❌ Browser connection test failed: {e}")
        return False


async def test_dom_inspector_basic():
    """Test basic DOMInspector functionality"""
    print("\n🧪 Testing DOMInspector basic functionality...")

    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ No browser tabs available")
        return False

    try:
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # Test basic CDP commands
        response = await inspector.send_command("Target.getTargets")
        targets = response.get("result", {}).get("targetInfos", [])

        print(f"✅ Connected successfully, found {len(targets)} targets")

        # Test getting document
        response = await inspector.send_command("DOM.getDocument", {"depth": 0})
        if "result" in response and "root" in response["result"]:
            print("✅ Document retrieval successful")
        else:
            print("❌ Document retrieval failed")

        await inspector.close()
        return True

    except Exception as e:
        print(f"❌ DOMInspector test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run manual tests"""
    print("🚀 Manual DOM Inspector Tests")
    print("=" * 50)
    print("Please start Chrome manually with:")
    print("  chrome --remote-debugging-port=9222")
    print("or")
    print("  open -a 'Google Chrome' --args --remote-debugging-port=9222")
    print("=" * 50)

    # Wait a moment for user to read instructions
    await asyncio.sleep(2)

    test_results = {}

    # Run tests
    test_results["browser_connection"] = await test_browser_connection_manual()

    if test_results["browser_connection"]:
        test_results["dom_inspector_basic"] = await test_dom_inspector_basic()
    else:
        test_results["dom_inspector_basic"] = False

    # Print summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY:")
    print("=" * 50)

    for test_name, result in test_results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")

    total_tests = len(test_results)
    passed_tests = sum(test_results.values())

    print(f"\n📈 Results: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed.")

    return passed_tests == total_tests


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
