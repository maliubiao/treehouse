#!/usr/bin/env python3
"""
测试简单页面的坐标检测
"""

import asyncio
import json
from typing import Dict, Optional

import aiohttp


class SimplePageTester:
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

    async def navigate_to_simple_page(self):
        """导航到一个简单的测试页面"""
        print(f"\n🌐 导航到简单测试页面")
        print("=" * 40)

        try:
            # 导航到data URL包含简单HTML
            simple_html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>测试页面</title>
                <style>
                    body { margin: 0; padding: 20px; font-family: Arial; }
                    .test-div { 
                        width: 200px; 
                        height: 100px; 
                        background-color: lightblue; 
                        margin: 10px; 
                        padding: 10px;
                        border: 2px solid blue;
                    }
                    .test-button {
                        padding: 10px 20px;
                        background-color: #4CAF50;
                        color: white;
                        border: none;
                        cursor: pointer;
                        margin: 10px;
                    }
                </style>
            </head>
            <body>
                <h1>测试页面</h1>
                <div class="test-div">这是一个测试div</div>
                <button class="test-button" onclick="alert('点击!')">测试按钮</button>
                <div class="test-div">另一个测试div</div>
                <input type="text" placeholder="测试输入框" style="margin: 10px; padding: 5px; width: 200px;">
            </body>
            </html>
            """

            data_url = f"data:text/html;charset=utf-8,{simple_html}"

            response = await self.send_command("Page.navigate", {"url": data_url})

            print(f"导航到: {data_url[:100]}...")

            # 等待页面加载
            await asyncio.sleep(2)

            # 检查导航结果
            if "error" in response:
                print(f"❌ 导航错误: {response['error']}")
                return False
            else:
                print("✅ 页面导航成功")
                return True

        except Exception as e:
            print(f"❌ 导航错误: {e}")
            return False

    async def test_coordinates_on_simple_page(self):
        """在简单页面上测试坐标检测"""
        print(f"\n🎯 简单页面坐标测试")
        print("=" * 40)

        # 测试几个已知位置的坐标
        test_coordinates = [
            (100, 100),  # 页面标题附近
            (150, 200),  # 第一个div
            (150, 350),  # 按钮
            (150, 450),  # 第二个div
            (150, 500),  # 输入框
        ]

        for x, y in test_coordinates:
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

                    # 如果是文本节点，获取父元素
                    if node["nodeName"] == "#text":
                        parent_info = await self.send_command("DOM.describeNode", {"nodeId": node["parentId"]})
                        parent_node = parent_info["result"]["node"]
                        print(f"父元素: {parent_node['nodeName']}")

                else:
                    print("❌ 未找到元素")
                    if backend_node_id:
                        print(f"有backendNodeId: {backend_node_id}")

            except Exception as e:
                print(f"❌ 坐标检测错误: {e}")

    async def get_page_content(self):
        """获取页面内容信息"""
        print(f"\n📄 页面内容信息")
        print("=" * 40)

        try:
            # 获取文档信息
            response = await self.send_command("DOM.getDocument", {"depth": 1})
            root = response["result"]["root"]

            print(f"文档节点: nodeId={root['nodeId']}")
            print(f"文档URL: {root.get('documentURL', 'N/A')}")

            # 获取body HTML
            body_response = await self.send_command("DOM.getOuterHTML", {"nodeId": root["nodeId"]})

            html_content = body_response["result"]["outerHTML"]
            print(f"页面HTML长度: {len(html_content)} 字符")
            print(f"HTML预览: {html_content[:200]}...")

        except Exception as e:
            print(f"❌ 获取页面内容错误: {e}")

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
    tester = SimplePageTester(websocket_url)

    try:
        await tester.connect()

        # 导航到简单页面
        success = await tester.navigate_to_simple_page()

        if success:
            # 获取页面内容
            await tester.get_page_content()

            # 测试坐标检测
            await tester.test_coordinates_on_simple_page()
        else:
            print("❌ 无法导航到测试页面")

    except Exception as e:
        print(f"❌ 测试错误: {e}")
    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
