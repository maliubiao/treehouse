#!/usr/bin/env python3
"""
专注测试：多屏幕坐标系统检测和转换
只测试坐标转换逻辑，不涉及完整的DOM检查
"""

import asyncio
import json
from typing import Dict, Optional, Tuple

import aiohttp


class CoordinateTester:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.message_id = 1

    async def connect(self):
        """连接到Chrome DevTools Protocol WebSocket"""
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.websocket_url)

        # 只启用必要的域
        await self.send_command("DOM.enable")
        print("✅ 连接到浏览器 DevTools")

    async def send_command(self, method: str, params: Dict = None) -> Dict:
        """发送CDP命令并等待响应"""
        if params is None:
            params = {}

        message_id = self.message_id
        self.message_id += 1

        message = {"id": message_id, "method": method, "params": params}

        await self.ws.send_str(json.dumps(message))

        # 等待响应
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                response = json.loads(msg.data)
                if response.get("id") == message_id:
                    return response

        raise Exception("WebSocket connection closed")

    async def test_coordinate_conversion(self, screen_x: int, screen_y: int):
        """测试坐标转换和元素检测"""
        print(f"\n🎯 测试坐标转换")
        print("=" * 40)
        print(f"屏幕坐标: ({screen_x}, {screen_y})")

        # 模拟窗口检测（使用已知的窗口位置）
        window_x, window_y, window_width, window_height = 2022, 25, 1920, 997
        scale_factor = 2.0

        print(f"浏览器窗口: 位置 ({window_x}, {window_y}), 大小 {window_width}x{window_height}")
        print(f"DPI缩放因子: {scale_factor}")

        # 计算浏览器UI偏移
        base_ui_height = 120
        if scale_factor >= 2.0:
            browser_ui_offset_y = int(base_ui_height * 1.2)
        elif scale_factor >= 1.5:
            browser_ui_offset_y = int(base_ui_height * 1.1)
        else:
            browser_ui_offset_y = base_ui_height

        print(f"浏览器UI偏移: {browser_ui_offset_y}px")

        # 计算相对坐标
        relative_x = screen_x - window_x
        relative_y = screen_y - window_y - browser_ui_offset_y

        print(f"转换后的浏览器坐标: ({relative_x}, {relative_y})")

        # 检查坐标是否在有效范围内
        if 0 <= relative_x <= window_width and 0 <= relative_y <= window_height:
            print("✅ 坐标在浏览器窗口内")

            # 使用DevTools检测元素
            try:
                response = await self.send_command(
                    "DOM.getNodeForLocation",
                    {
                        "x": relative_x,
                        "y": relative_y,
                        "includeUserAgentShadowDOM": False,
                        "ignorePointerEventsNone": True,
                    },
                )

                result = response.get("result", {})
                node_id = result.get("nodeId")

                if node_id:
                    print(f"✅ 找到元素! nodeId: {node_id}")

                    # 获取元素信息
                    element_info = await self.send_command("DOM.resolveNode", {"nodeId": node_id})

                    print(f"元素信息: {json.dumps(element_info, indent=2)}")
                    return True
                else:
                    print("❌ 未找到元素")

                    # 检查是否有其他信息
                    backend_node_id = result.get("backendNodeId")
                    if backend_node_id:
                        print(f"有backendNodeId: {backend_node_id}")

                    return False

            except Exception as e:
                print(f"❌ 元素检测错误: {e}")
                return False

        else:
            print("❌ 坐标超出浏览器窗口")
            if relative_x < 0:
                print(f"  X坐标太小: {relative_x}")
            elif relative_x > window_width:
                print(f"  X坐标太大: {relative_x} > {window_width}")

            if relative_y < 0:
                print(f"  Y坐标太小: {relative_y}")
            elif relative_y > window_height:
                print(f"  Y坐标太大: {relative_y} > {window_height}")

            return False

    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()


async def main():
    """主测试函数"""

    # 查找浏览器标签页
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("http://localhost:9222/json") as response:
                tabs = await response.json()
                websocket_urls = [tab["webSocketDebuggerUrl"] for tab in tabs if tab.get("webSocketDebuggerUrl")]

                if not websocket_urls:
                    print("❌ 未找到浏览器标签页")
                    return

                # 使用第一个标签页
                websocket_url = websocket_urls[0]
                print(f"使用标签页: {websocket_url}")

        except Exception as e:
            print(f"❌ 连接错误: {e}")
            return

    # 创建测试器
    tester = CoordinateTester(websocket_url)

    try:
        await tester.connect()

        # 测试多个坐标点
        test_coordinates = [
            (2889, 481),  # 之前的失败坐标
            (2500, 300),  # 次级屏幕中间
            (1800, 200),  # 主屏幕右侧边缘
            (2200, 400),  # 次级屏幕
        ]

        for screen_x, screen_y in test_coordinates:
            success = await tester.test_coordinate_conversion(screen_x, screen_y)
            print(f"测试结果: {'成功' if success else '失败'}")
            print("-" * 40)

    except Exception as e:
        print(f"❌ 测试错误: {e}")
    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
