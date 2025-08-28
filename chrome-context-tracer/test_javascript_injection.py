#!/usr/bin/env python3
"""
测试JavaScript注入功能的简单脚本
"""

import asyncio
import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import MOUSE_ELEMENT_DETECTOR_JS, DOMInspector, find_chrome_tabs


async def test_javascript_injection():
    """测试JavaScript注入功能"""
    print("Testing JavaScript injection functionality...")

    # 查找Chrome标签页
    try:
        websocket_urls = await asyncio.wait_for(find_chrome_tabs(9222), timeout=5.0)
    except asyncio.TimeoutError:
        print("Timeout: Could not connect to Chrome DevTools")
        print("Please start Chrome with remote debugging:")
        print("chrome --remote-debugging-port=9222")
        return

    if not websocket_urls:
        print("No Chrome tabs found. Please start Chrome with remote debugging:")
        print("chrome --remote-debugging-port=9222")
        return

    print(f"Found {len(websocket_urls)} Chrome tabs")

    inspector = None
    try:
        # 连接到第一个标签页
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        print("Connected to Chrome DevTools")

        # 测试JavaScript代码注入（使用嵌入的代码）
        success = await inspector.inject_javascript_file(MOUSE_ELEMENT_DETECTOR_JS)

        if success:
            print("✓ JavaScript injection successful")

            # 测试启动元素选择模式
            print("Testing element selection mode...")
            result = await inspector.start_element_selection_mode()

            if result:
                print(f"✓ Element selection returned: {result.get('tagName', 'Unknown')}")
                print(f"Element path: {result.get('path', 'N/A')}")
            else:
                print("✗ Element selection failed or was cancelled")
        else:
            print("✗ JavaScript injection failed")

    except Exception as e:
        print(f"Error during testing: {e}")
        import traceback

        traceback.print_exc()

    finally:
        if inspector:
            await inspector.close()
            print("Connection closed")


if __name__ == "__main__":
    asyncio.run(test_javascript_injection())
