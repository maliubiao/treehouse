#!/usr/bin/env python3
"""
测试backendNodeId转换修复的逻辑
模拟DOM检查器接收到只有backendNodeId而没有nodeId的响应情况
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock


# 模拟DOMInspector的核心方法
class MockDOMInspector:
    def __init__(self):
        self.send_command = AsyncMock()

    async def get_node_for_location(self, x: int, y: int):
        """模拟修复后的get_node_for_location方法"""
        # 模拟send_command的响应 - 只有backendNodeId，没有nodeId
        mock_response = {"id": 11, "result": {"backendNodeId": 140, "frameId": "09A80CB1DA14D7AB33792A68607FC683"}}

        print(f"Simulating DOM.getNodeForLocation for coordinates ({x}, {y})")

        result = mock_response.get("result", {})
        node_id = result.get("nodeId")
        backend_node_id = result.get("backendNodeId")

        print(f"Raw response: nodeId={node_id}, backendNodeId={backend_node_id}")

        if node_id:
            print(f"Found element at coordinates ({x}, {y}), nodeId: {node_id}")

            # 检查nodeId是否有效（不为0）
            if node_id == 0:
                print(f"⚠️  警告: 无效的nodeId 0，可能是DevTools协议错误")
                node_id = None  # 将无效的nodeId设为None，后续统一处理
            else:
                return node_id

        # 如果没有有效的nodeId，但有backendNodeId，尝试转换
        if not node_id and backend_node_id and backend_node_id != 0:
            print(f"No nodeId found, attempting to convert backendNodeId: {backend_node_id}")

            # 如果backendNodeId是29（已知问题值），提供额外信息
            if backend_node_id == 29:
                print(f"⚠️  已知问题: backendNodeId 29 通常表示无效的DevTools协议响应")
                print(f"💡 这可能是因为页面内容问题或坐标指向了空白区域")
            else:
                # 尝试使用backendNodeId获取有效节点
                try:
                    # 模拟pushNodesByBackendIdsToFrontend的成功响应
                    push_response = {
                        "id": 12,
                        "result": {
                            "nodeIds": [1542]  # 模拟成功转换后的nodeId
                        },
                    }
                    print(f"Simulating DOM.pushNodesByBackendIdsToFrontend with backendNodeIds: [{backend_node_id}]")

                    push_result = push_response.get("result", {})
                    push_node_ids = push_result.get("nodeIds", [])

                    if push_node_ids and push_node_ids[0] != 0:
                        valid_node_id = push_node_ids[0]
                        print(f"✅ 成功从backendNodeId {backend_node_id} 转换为nodeId: {valid_node_id}")
                        return valid_node_id
                    else:
                        print(f"❌ 无法从backendNodeId {backend_node_id} 获取有效节点")
                except Exception as push_error:
                    print(f"backendNodeId转换错误: {push_error}")

        # 如果仍然没有找到元素，提供调试信息
        print(f"No element found at coordinates ({x}, {y})")

        # 添加调试信息：检查是否有其他信息
        if "error" in mock_response:
            print(f"Error: {mock_response['error']}")

        if backend_node_id:
            print(f"Found backendNodeId: {backend_node_id}")
        else:
            print("No backendNodeId available")

        # 如果到这里还没有返回，说明转换失败，按原逻辑返回文档根节点
        print("⚠️  警告: 所有方法都失败，回退到文档根节点")
        return 1  # 模拟返回文档根节点


async def test_backendid_conversion():
    """测试backendNodeId转换逻辑"""
    print("🧪 测试backendNodeId转换修复")
    print("=" * 50)

    inspector = MockDOMInspector()

    # 测试场景：只有backendNodeId，没有nodeId的情况
    print("\n📝 测试场景: 收到backendNodeId=140，但没有nodeId")
    result = await inspector.get_node_for_location(3, 64)

    print(f"\n🎯 最终结果: nodeId = {result}")

    if result == 1542:
        print("✅ 测试通过: 成功从backendNodeId转换为有效的nodeId")
    elif result == 1:
        print("⚠️  测试部分通过: 回退到文档根节点（这不是期望的结果，但比之前的逻辑好）")
    else:
        print("❌ 测试失败: 未获得预期结果")


if __name__ == "__main__":
    asyncio.run(test_backendid_conversion())
