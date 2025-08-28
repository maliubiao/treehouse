#!/usr/bin/env python3
"""
简单的Chrome连接和JavaScript注入测试
"""

import asyncio
import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import MOUSE_ELEMENT_DETECTOR_JS, DOMInspector, find_chrome_tabs


async def quick_test():
    """快速测试Chrome连接和JavaScript注入"""
    print("🔍 查找Chrome标签页...")

    try:
        # 设置较短的超时
        websocket_urls = await asyncio.wait_for(find_chrome_tabs(9222), timeout=3.0)
        print(f"✅ 找到 {len(websocket_urls)} 个标签页")

        if not websocket_urls:
            print("❌ 没有找到Chrome标签页")
            print("💡 请启动Chrome: chrome --remote-debugging-port=9222")
            return

        # 连接到第一个标签页
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()
        print("✅ 连接成功")

        # 注入JavaScript
        print("💉 注入JavaScript...")
        success = await inspector.inject_javascript_file(MOUSE_ELEMENT_DETECTOR_JS)

        if success:
            print("✅ JavaScript注入成功")

            # 测试一个简单的JavaScript表达式
            result = await inspector.send_command(
                "Runtime.evaluate", {"expression": "typeof window.chromeContextTracer", "returnByValue": True}
            )

            obj_type = result.get("result", {}).get("result", {}).get("value")
            print(f"🔍 window.chromeContextTracer 类型: {obj_type}")

        else:
            print("❌ JavaScript注入失败")

        await inspector.close()
        print("✅ 连接关闭")

    except asyncio.TimeoutError:
        print("⏰ 超时: 无法连接到Chrome")
        print("💡 请确保Chrome运行在端口9222")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    asyncio.run(quick_test())
