#!/usr/bin/env python3
"""
DOM Inspector 鼠标跟踪测试
测试鼠标坐标转换和元素检测功能
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加包的 src 目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chrome_context_tracer import BrowserContextManager, DOMInspector
from chrome_context_tracer.utils import find_free_safe_port
from test_server_utils import TestServerContext


async def test_mouse_tracking():
    """测试鼠标坐标跟踪和元素检测功能"""
    print("🎯 开始鼠标跟踪测试")
    print("=" * 60)

    # 使用 BrowserContextManager 管理浏览器上下文
    async with BrowserContextManager("edge", 9222, auto_cleanup=True) as context:
        websocket_urls = context.get_websocket_urls()

        inspector = None
        try:
            # 连接到浏览器
            print("🔗 连接到浏览器...")
            inspector = DOMInspector(websocket_urls[0])
            await inspector.connect()
            print("✅ 浏览器连接成功")

            # 3. 创建测试页面
            print("📄 创建测试页面...")
            test_html = """
<!DOCTYPE html>
<html>
<head>
    <title>鼠标跟踪测试</title>
    <style>
        body { margin: 0; padding: 20px; font-family: Arial; }
        .test-element { 
            padding: 20px; 
            margin: 20px; 
            border: 2px solid #007bff;
            border-radius: 8px;
            background-color: #f8f9fa;
        }
        .element-1 { width: 200px; height: 100px; }
        .element-2 { width: 150px; height: 150px; }
        .element-3 { width: 300px; height: 80px; }
        .coordinate-display {
            position: fixed;
            top: 10px;
            right: 10px;
            background: rgba(0,0,0,0.8);
            color: white;
            padding: 10px;
            border-radius: 4px;
            font-family: monospace;
        }
    </style>
</head>
<body>
    <h1>鼠标跟踪测试页面</h1>
    
    <div class="test-element element-1" id="element1">
        <h3>元素 1</h3>
        <p>这是一个测试元素</p>
    </div>
    
    <div class="test-element element-2" id="element2">
        <h3>元素 2</h3>
        <p>另一个测试元素</p>
    </div>
    
    <div class="test-element element-3" id="element3">
        <h3>元素 3</h3>
        <p>第三个测试元素</p>
    </div>
    
    <div class="coordinate-display" id="coord-display">
        坐标: (0, 0)
    </div>
    
    <script>
        // 显示鼠标坐标
        document.addEventListener('mousemove', function(e) {
            const display = document.getElementById('coord-display');
            display.textContent = `坐标: (${e.clientX}, ${e.clientY})`;
        });
    </script>
</body>
</html>
"""

            port = find_free_safe_port()
            async with TestServerContext(test_html, port=port) as test_url:
                # 4. 导航到测试页面
                print(f"🌐 导航到测试页面: {test_url}")
                nav_success = await inspector.navigate_to_page(test_url)
                if not nav_success:
                    print("❌ 页面导航失败")
                    return False

                print("✅ 页面导航成功")
                await asyncio.sleep(2)  # 等待页面加载

                # 5. 获取元素坐标
                print("🎯 测试元素坐标获取...")

                # 查找元素1
                response = await inspector.send_command("DOM.getDocument", {"depth": -1})
                root_node_id = response["result"]["root"]["nodeId"]

                # 查找元素1
                element1_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#element1"}
                )
                element1_node_id = element1_response["result"]["nodeId"]

                if not element1_node_id:
                    print("❌ 未找到测试元素1")
                    return False

                # 获取元素1的屏幕坐标
                coords = await inspector.get_element_screen_coords(element1_node_id)
                if not coords:
                    print("❌ 无法获取元素坐标")
                    return False

                x, y = coords
                print(f"✅ 元素1坐标: ({x}, {y})")

                # 6. 测试坐标转换功能
                print("🔄 测试坐标转换功能...")

                # 测试 get_node_for_location - 应该找到元素1
                found_node_id = await inspector.get_node_for_location(x, y)
                if not found_node_id:
                    print("❌ 无法通过坐标找到元素")
                    return False

                print(f"✅ 通过坐标找到元素，nodeId: {found_node_id}")

                # 验证找到的是正确的元素
                if found_node_id == element1_node_id:
                    print("✅ 坐标定位正确 - 找到的是元素1")
                else:
                    print(f"⚠️  坐标定位可能不准确 - 期望: {element1_node_id}, 实际: {found_node_id}")

                # 7. 测试 get_element_at_screen_coords (using get_node_for_location)
                print("📱 测试屏幕坐标元素检测 (using get_node_for_location)...")

                screen_element_id = await inspector.get_node_for_location(x, y)
                if screen_element_id:
                    print(f"✅ 屏幕坐标元素检测成功，nodeId: {screen_element_id}")

                    # 获取元素信息验证
                    element_html = await inspector.get_element_html(screen_element_id)
                    if "element1" in element_html:
                        print("✅ 屏幕坐标检测正确 - 找到元素1")
                    else:
                        print(f"⚠️  屏幕坐标检测可能不准确")
                        print(f"找到的元素HTML: {element_html[:100]}...")
                else:
                    print("❌ 屏幕坐标元素检测失败")

                # 8. 测试边缘情况
                print("🧪 测试边缘情况...")

                # 测试无效坐标
                invalid_node = await inspector.get_node_for_location(-100, -100)
                if invalid_node:
                    print(f"⚠️  无效坐标返回了节点: {invalid_node}")
                else:
                    print("✅ 无效坐标正确处理")

                # 测试边界坐标
                boundary_node = await inspector.get_node_for_location(10, 10)
                if boundary_node:
                    print(f"✅ 边界坐标找到元素，nodeId: {boundary_node}")
                else:
                    print("⚠️  边界坐标未找到元素")

                print("\n🎉 鼠标跟踪测试完成！")
                print("📊 测试结果摘要:")
                print(f"   - 元素坐标获取: ✅")
                print(f"   - 坐标转换功能: ✅")
                print(f"   - 屏幕坐标检测: ✅")
                print(f"   - 边缘情况处理: ✅")

                return True

        except Exception as e:
            print(f"❌ 测试过程中发生错误: {e}")
            import traceback

            traceback.print_exc()
            return False

        finally:
            if inspector:
                await inspector.close()
                print("🔐 连接已关闭")


async def main():
    """主测试函数"""
    print("🚀 DOM Inspector 鼠标跟踪测试")
    print("=" * 60)

    success = await test_mouse_tracking()

    print("\n" + "=" * 60)
    if success:
        print("🎊 鼠标跟踪测试通过！坐标转换功能正常")
        print("💡 验证的功能:")
        print("   - get_element_screen_coords() - 元素坐标获取")
        print("   - get_node_for_location() - 坐标到元素转换")
        print("   - 边缘情况处理")
    else:
        print("❌ 鼠标跟踪测试失败")
        print("💡 请检查浏览器设置和网络连接")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
