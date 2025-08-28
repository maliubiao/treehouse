#!/usr/bin/env python3
"""
测试第一个div元素的坐标检测
"""

import asyncio
import json
from typing import Dict, Optional

import aiohttp


class FirstDivTester:
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

    async def find_first_div(self):
        """查找页面中的第一个div元素并获取其位置"""
        print(f"\n🔍 查找第一个div元素")
        print("=" * 40)

        try:
            # 获取文档根节点
            response = await self.send_command("DOM.getDocument", {"depth": 1})
            root_node_id = response["result"]["root"]["nodeId"]

            # 查找第一个div元素
            response = await self.send_command("DOM.querySelector", {"nodeId": root_node_id, "selector": "div"})

            div_node_id = response.get("result", {}).get("nodeId")
            if not div_node_id:
                print("❌ 未找到div元素")
                return None

            print(f"✅ 找到div元素，nodeId: {div_node_id}")

            # 获取div元素的详细信息
            div_info = await self.send_command("DOM.describeNode", {"nodeId": div_node_id})

            node = div_info["result"]["node"]
            backend_node_id = node["backendNodeId"]
            node_name = node["nodeName"]

            print(f"div信息: backendNodeId={backend_node_id}, nodeName={node_name}")

            # 获取div元素的边界框
            response = await self.send_command("DOM.getBoxModel", {"nodeId": div_node_id})

            if "result" in response:
                box_model = response["result"]["model"]
                content = box_model["content"]

                # 计算中心点坐标
                center_x = (content[0] + content[2]) // 2
                center_y = (content[1] + content[5]) // 2

                print(f"div边界框: {content}")
                print(f"div中心点: ({center_x}, {center_y})")

                return center_x, center_y, backend_node_id
            else:
                print("❌ 无法获取div元素的边界框")
                return None

        except Exception as e:
            print(f"❌ 查找div元素错误: {e}")
            return None

    async def test_coordinate_at_div(self, x: int, y: int):
        """在div元素的位置测试坐标检测"""
        print(f"\n🎯 在div位置测试坐标检测: ({x}, {y})")
        print("=" * 40)

        try:
            response = await self.send_command(
                "DOM.getNodeForLocation",
                {"x": x, "y": y, "includeUserAgentShadowDOM": False, "ignorePointerEventsNone": True},
            )

            result = response.get("result", {})
            print(f"响应结果: {json.dumps(result, indent=2)}")

            backend_node_id = result.get("backendNodeId")
            node_id = result.get("nodeId")

            if node_id and node_id != 0:
                print(f"✅ 找到有效元素! nodeId: {node_id}, backendNodeId: {backend_node_id}")

                # 获取元素信息
                element_info = await self.send_command("DOM.describeNode", {"nodeId": node_id})

                node = element_info["result"]["node"]
                print(f"元素类型: {node['nodeName']}, 元素名称: {node.get('localName', 'N/A')}")

                # 检查是否是div元素
                if node.get("localName") == "div":
                    print(f"🎯 成功检测到div元素!")

                    # 获取div的HTML内容
                    html_response = await self.send_command("DOM.getOuterHTML", {"nodeId": node_id})
                    html_content = html_response["result"]["outerHTML"]
                    print(f"div HTML: {html_content[:200]}...")

                    return True
                else:
                    print(f"⚠️  找到的元素不是div: {node.get('localName')}")
                    return False

            elif node_id == 0:
                print(f"⚠️  无效的nodeId 0, backendNodeId: {backend_node_id}")

                # 尝试使用backendNodeId获取有效节点
                if backend_node_id and backend_node_id != 0:
                    print(f"尝试使用backendNodeId {backend_node_id} 获取有效节点")
                    push_response = await self.send_command(
                        "DOM.pushNodesByBackendIdsToFrontend", {"backendNodeIds": [backend_node_id]}
                    )

                    push_result = push_response.get("result", {})
                    push_node_ids = push_result.get("nodeIds", [])

                    if push_node_ids and push_node_ids[0] != 0:
                        valid_node_id = push_node_ids[0]
                        print(f"✅ 成功获取有效nodeId: {valid_node_id}")

                        # 获取元素信息
                        element_info = await self.send_command("DOM.describeNode", {"nodeId": valid_node_id})

                        node = element_info["result"]["node"]
                        print(f"元素类型: {node['nodeName']}, 元素名称: {node.get('localName', 'N/A')}")

                        return True
                    else:
                        print(f"❌ 无法从backendNodeId {backend_node_id} 获取有效节点")
                        return False

                return False
            else:
                print("❌ 未找到元素")
                if backend_node_id:
                    print(f"有backendNodeId: {backend_node_id}")

                    # 如果backendNodeId是29（已知问题值），提供额外信息
                    if backend_node_id == 29:
                        print(f"⚠️  已知问题: backendNodeId 29 通常表示无效的DevTools协议响应")
                        print(f"💡 这可能是因为页面内容问题或坐标指向了空白区域")

                return False

        except Exception as e:
            print(f"❌ 坐标检测错误: {e}")
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
    tester = FirstDivTester(websocket_url)

    try:
        await tester.connect()

        # 查找第一个div元素
        div_coords = await tester.find_first_div()

        if div_coords:
            x, y, backend_node_id = div_coords

            # 在div位置测试坐标检测
            success = await tester.test_coordinate_at_div(x, y)
            print(f"测试结果: {'成功' if success else '失败'}")

            # 也在div周围测试几个点
            test_points = [
                (x, y),  # 中心点
                (x + 10, y),  # 右侧
                (x, y + 10),  # 下方
                (x - 10, y),  # 左侧
                (x, y - 10),  # 上方
            ]

            for test_x, test_y in test_points:
                success = await tester.test_coordinate_at_div(test_x, test_y)
                print(f"坐标 ({test_x}, {test_y}) 测试: {'成功' if success else '失败'}")

        else:
            print("❌ 无法找到div元素进行测试")

    except Exception as e:
        print(f"❌ 测试错误: {e}")
    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
