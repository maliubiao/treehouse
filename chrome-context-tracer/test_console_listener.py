#!/usr/bin/env python3
"""
测试控制台监听功能
"""

import asyncio
import os
import sys

# 添加当前目录到路径，以便导入dom_inspector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs


async def test_console_listener():
    """测试控制台监听功能"""
    print("🔍 查找浏览器标签页...")

    # 查找浏览器标签页
    websocket_urls = await find_chrome_tabs(port=9222)

    if not websocket_urls:
        print("❌ 未找到浏览器标签页，请确保浏览器以远程调试模式运行:")
        print("Chrome: chrome --remote-debugging-port=9222")
        print("Edge: msedge --remote-debugging-port=9222")
        return

    print(f"✅ 找到 {len(websocket_urls)} 个标签页")

    # 使用第一个标签页
    ws_url = websocket_urls[0]
    print(f"使用标签页: {ws_url}")

    # 创建DOM检查器实例
    inspector = DOMInspector(ws_url)

    try:
        # 连接到浏览器
        await inspector.connect()
        print("✅ 已连接到浏览器")

        # 查找第一个有效的网页标签页
        target_id = await inspector.find_tab_by_url("")
        if not target_id:
            print("❌ 未找到有效的网页标签页")
            return

        # 附加到标签页
        session_id = await inspector.attach_to_tab(target_id)
        print(f"✅ 已附加到标签页，会话ID: {session_id}")

        # 自定义控制台消息处理函数
        async def console_message_handler(message):
            print(f"📋 控制台消息: {message}")

        # 开始监听控制台消息
        print("🎧 开始监听控制台消息...")
        print("💡 请在浏览器控制台中输入一些消息进行测试")
        print("💡 按 Ctrl+C 停止监听")

        await inspector.start_console_listening(console_message_handler)

        # 保持运行，直到用户中断
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n⏹️  停止监听...")

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # 关闭连接
        await inspector.close()
        print("✅ 连接已关闭")


if __name__ == "__main__":
    asyncio.run(test_console_listener())
