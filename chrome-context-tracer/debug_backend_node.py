#!/usr/bin/env python3
"""
调试 backendNodeId 29 问题
"""

import asyncio
import json
from typing import Dict, Optional

import aiohttp


class BackendNodeDebugger:
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

    async def debug_backend_node(self, backend_node_id: int):
        """调试 backendNodeId"""
        print(f"\n🔍 调试 backendNodeId: {backend_node_id}")
        print("=" * 40)

        try:
            # 尝试将backendNodeId转换为nodeId
            response = await self.send_command(
                "DOM.pushNodesByBackendIdsToFrontend", {"backendNodeIds": [backend_node_id]}
            )

            result = response.get("result", {})
            node_ids = result.get("nodeIds", [])

            if node_ids:
                print(f"✅ 转换成功! nodeIds: {node_ids}")

                # 获取节点信息
                for node_id in node_ids:
                    if node_id == 0:
                        print(f"⚠️  节点ID 0 是无效的，可能是DevTools协议错误")
                        continue

                    node_info = await self.send_command("DOM.describeNode", {"nodeId": node_id})
                    print(f"节点 {node_id} 信息: {json.dumps(node_info, indent=2)}")

            else:
                print("❌ 无法转换 backendNodeId 到 nodeId")

        except Exception as e:
            print(f"❌ 调试错误: {e}")

    async def test_coordinate_detection(self, x: int, y: int):
        """测试坐标检测"""
        print(f"\n🎯 测试坐标检测: ({x}, {y})")
        print("=" * 40)

        try:
            response = await self.send_command(
                "DOM.getNodeForLocation",
                {"x": x, "y": y, "includeUserAgentShadowDOM": False, "ignorePointerEventsNone": True},
            )

            result = response.get("result", {})
            print(f"响应结果: {json.dumps(result, indent=2)}")

            # 检查是否有错误
            if "error" in response:
                print(f"❌ 错误: {response['error']}")

        except Exception as e:
            print(f"❌ 坐标检测错误: {e}")

    async def get_viewport_info(self):
        """获取视口信息"""
        print(f"\n📏 获取视口信息")
        print("=" * 40)

        try:
            # 获取页面布局信息
            response = await self.send_command("Page.getLayoutMetrics")
            result = response.get("result", {})

            print(f"布局信息: {json.dumps(result, indent=2)}")

            # 获取可视区域信息
            visual_viewport = result.get("visualViewport", {})
            if visual_viewport:
                client_width = visual_viewport.get("clientWidth", 0)
                client_height = visual_viewport.get("clientHeight", 0)
                offset_x = visual_viewport.get("pageX", 0)
                offset_y = visual_viewport.get("pageY", 0)

                print(f"可视区域: {client_width}x{client_height}, 偏移: ({offset_x}, {offset_y})")

        except Exception as e:
            print(f"❌ 获取视口信息错误: {e}")

    async def get_document_info(self):
        """获取文档信息"""
        print(f"\n📄 获取文档信息")
        print("=" * 40)

        try:
            # 获取文档根节点
            response = await self.send_command("DOM.getDocument", {"depth": 0})
            result = response.get("result", {})

            root = result.get("root", {})
            node_id = root.get("nodeId")
            backend_node_id = root.get("backendNodeId")

            print(f"文档根节点: nodeId={node_id}, backendNodeId={backend_node_id}")
            print(f"节点类型: {root.get('nodeType')}, 节点名称: {root.get('nodeName')}")

            # 获取body元素
            body_response = await self.send_command("DOM.querySelector", {"nodeId": node_id, "selector": "body"})

            body_node_id = body_response.get("result", {}).get("nodeId")
            if body_node_id:
                body_info = await self.send_command("DOM.describeNode", {"nodeId": body_node_id})
                body_backend_id = body_info.get("result", {}).get("node", {}).get("backendNodeId")
                print(f"body元素: nodeId={body_node_id}, backendNodeId={body_backend_id}")

            return backend_node_id

        except Exception as e:
            print(f"❌ 获取文档信息错误: {e}")
            return None

    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()


async def main():
    """主调试函数"""

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

    # 创建调试器
    debugger = BackendNodeDebugger(websocket_url)

    try:
        await debugger.connect()

        # 获取文档信息
        doc_backend_id = await debugger.get_document_info()

        # 调试 backendNodeId 29
        await debugger.debug_backend_node(29)

        # 如果文档backendNodeId不同，也调试它
        if doc_backend_id and doc_backend_id != 29:
            await debugger.debug_backend_node(doc_backend_id)

        # 测试坐标检测
        test_coordinates = [
            (867, 312),  # 原始问题坐标
            (500, 300),  # 中间位置
            (100, 100),  # 左上角
            (50, 50),  # 更靠近角落
            (200, 200),  # 中间偏左
            (800, 400),  # 右侧
            (900, 100),  # 右上角
        ]
        for x, y in test_coordinates:
            await debugger.test_coordinate_detection(x, y)

        # 获取视口信息
        await debugger.get_viewport_info()

    except Exception as e:
        print(f"❌ 调试错误: {e}")
    finally:
        await debugger.close()


if __name__ == "__main__":
    asyncio.run(main())
