#!/usr/bin/env python3
"""
分析视口和页面内容
"""

import asyncio
import json
from typing import Dict, Optional

import aiohttp


class ViewportAnalyzer:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.message_id = 1

    async def connect(self):
        """连接到Chrome DevTools Protocol WebSocket"""
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.websocket_url)

        # 启用必要的域
        await self.send_command("DOM.enable")
        await self.send_command("Page.enable")
        await self.send_command("Runtime.enable")
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

    async def analyze_viewport(self):
        """分析视口信息"""
        print(f"\n📏 视口分析")
        print("=" * 40)

        try:
            # 获取页面布局信息
            response = await self.send_command("Page.getLayoutMetrics")
            result = response.get("result", {})

            print(f"完整布局信息: {json.dumps(result, indent=2)}")

            # 分析CSS视口和实际视口
            css_visual_viewport = result.get("cssVisualViewport", {})
            visual_viewport = result.get("visualViewport", {})

            css_width = css_visual_viewport.get("clientWidth", 0)
            css_height = css_visual_viewport.get("clientHeight", 0)
            actual_width = visual_viewport.get("clientWidth", 0)
            actual_height = visual_viewport.get("clientHeight", 0)

            print(f"CSS视口: {css_width}x{css_height}")
            print(f"实际视口: {actual_width}x{actual_height}")

            # 计算缩放比例
            if css_width > 0 and actual_width > 0:
                scale_x = actual_width / css_width
                scale_y = actual_height / css_height
                print(f"缩放比例: X={scale_x:.2f}, Y={scale_y:.2f}")

            return css_width, css_height, actual_width, actual_height

        except Exception as e:
            print(f"❌ 视口分析错误: {e}")
            return None, None, None, None

    async def analyze_dom_structure(self):
        """分析DOM结构"""
        print(f"\n🌳 DOM结构分析")
        print("=" * 40)

        try:
            # 获取文档信息
            response = await self.send_command("DOM.getDocument", {"depth": 2})
            root = response["result"]["root"]

            print(f"文档节点: nodeId={root['nodeId']}, backendNodeId={root['backendNodeId']}")
            print(f"文档URL: {root.get('documentURL', 'N/A')}")

            # 获取body元素
            body_response = await self.send_command("DOM.querySelector", {"nodeId": root["nodeId"], "selector": "body"})

            body_node_id = body_response.get("result", {}).get("nodeId")
            if body_node_id:
                body_info = await self.send_command("DOM.describeNode", {"nodeId": body_node_id})

                body_node = body_info["result"]["node"]
                print(f"body元素: nodeId={body_node_id}, backendNodeId={body_node['backendNodeId']}")
                print(f"body子节点数量: {body_node.get('childNodeCount', 0)}")

                # 获取body的边界框
                try:
                    body_box = await self.send_command("DOM.getBoxModel", {"nodeId": body_node_id})

                    if "result" in body_box:
                        box_model = body_box["result"]["model"]
                        content = box_model["content"]
                        print(f"body边界框: {content}")

                        # 计算可见区域
                        visible_width = content[2] - content[0]
                        visible_height = content[5] - content[1]
                        print(f"body可见区域: {visible_width}x{visible_height}")

                        return body_node_id, content

                except Exception as box_error:
                    print(f"无法获取body边界框: {box_error}")

            return None, None

        except Exception as e:
            print(f"❌ DOM分析错误: {e}")
            return None, None

    async def test_visible_area_coordinates(self, body_box):
        """在可见区域内测试坐标"""
        print(f"\n🎯 可见区域坐标测试")
        print("=" * 40)

        if not body_box:
            print("❌ 没有body边界框信息")
            return

        left, top, right, bottom = body_box[0], body_box[1], body_box[2], body_box[5]

        # 测试几个关键点
        test_points = [
            (left + 50, top + 50),  # 左上角附近
            (right - 50, top + 50),  # 右上角附近
            (left + 50, bottom - 50),  # 左下角附近
            (right - 50, bottom - 50),  # 右下角附近
            ((left + right) // 2, (top + bottom) // 2),  # 中心点
        ]

        for x, y in test_points:
            print(f"\n测试坐标: ({x}, {y})")
            print("-" * 20)

            try:
                response = await self.send_command(
                    "DOM.getNodeForLocation",
                    {"x": x, "y": y, "includeUserAgentShadowDOM": False, "ignorePointerEventsNone": True},
                )

                result = response.get("result", {})
                backend_node_id = result.get("backendNodeId")
                node_id = result.get("nodeId")

                if node_id:
                    print(f"✅ 找到元素! nodeId: {node_id}, backendNodeId: {backend_node_id}")

                    # 获取元素信息
                    element_info = await self.send_command("DOM.describeNode", {"nodeId": node_id})

                    node = element_info["result"]["node"]
                    print(f"元素类型: {node['nodeName']}")

                else:
                    print("❌ 未找到元素")
                    if backend_node_id:
                        print(f"有backendNodeId: {backend_node_id}")

            except Exception as e:
                print(f"❌ 坐标检测错误: {e}")

    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()


async def main():
    """主分析函数"""

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

    # 创建分析器
    analyzer = ViewportAnalyzer(websocket_url)

    try:
        await analyzer.connect()

        # 分析视口
        css_w, css_h, actual_w, actual_h = await analyzer.analyze_viewport()

        # 分析DOM结构
        body_node_id, body_box = await analyzer.analyze_dom_structure()

        # 在可见区域测试坐标
        await analyzer.test_visible_area_coordinates(body_box)

    except Exception as e:
        print(f"❌ 分析错误: {e}")
    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
