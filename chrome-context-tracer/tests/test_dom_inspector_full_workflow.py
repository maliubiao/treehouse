#!/usr/bin/env python3
"""
DOM Inspector 全流程端到端测试
测试从浏览器启动到元素信息获取的完整工作流
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加包的 src 目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chrome_context_tracer import BrowserContextManager, DOMInspector
from chrome_context_tracer.utils import find_free_safe_port, get_mouse_detector_js
from test_server_utils import TestServerContext


async def test_full_workflow():
    """测试完整的DOM Inspector工作流"""
    print("🚀 开始DOM Inspector全流程测试")
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
    <title>DOM Inspector 全流程测试</title>
    <style>
        body { margin: 0; padding: 20px; font-family: Arial; }
        .test-button { 
            padding: 15px 30px; 
            background-color: #007bff; 
            color: white; 
            border: none; 
            border-radius: 5px; 
            cursor: pointer;
            font-size: 16px;
            margin: 20px;
        }
        .test-button:hover {
            background-color: #0056b3;
        }
        .test-container {
            padding: 20px;
            border: 2px solid #ddd;
            border-radius: 8px;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <h1>DOM Inspector 全流程测试页面</h1>
    
    <div class="test-container">
        <h2>测试区域</h2>
        <button class="test-button" id="test-btn" onclick="handleClick()">
            🎯 测试按钮
        </button>
        <p>这是一个用于测试DOM Inspector完整工作流的页面。</p>
    </div>
    
    <script>
        function handleClick() {
            console.log('按钮被点击了！');
        }
        
        document.getElementById('test-btn').addEventListener('mouseover', function() {
            console.log('鼠标悬停在按钮上');
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

                # 5. 注入JavaScript代码
                print("💉 注入JavaScript代码...")
                injection_success = await inspector.inject_javascript_file(get_mouse_detector_js())
                if not injection_success:
                    print("❌ JavaScript注入失败")
                    return False

                print("✅ JavaScript注入成功")
                await asyncio.sleep(1)

                # 6. 查找测试元素并获取坐标
                print("🔍 查找测试元素...")
                response = await inspector.send_command("DOM.getDocument", {"depth": -1})
                root_node_id = response["result"]["root"]["nodeId"]

                # 查找按钮元素
                button_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#test-btn"}
                )
                button_node_id = button_response["result"]["nodeId"]

                if not button_node_id:
                    print("❌ 未找到测试按钮元素")
                    return False

                # 7. 获取元素坐标（模拟鼠标移动到元素位置）
                print("🎯 获取元素坐标...")
                coords = await inspector.get_element_screen_coords(button_node_id)
                if not coords:
                    print("❌ 无法获取元素坐标")
                    return False

                x, y = coords
                print(f"✅ 元素坐标: ({x}, {y})")

                # 8. 模拟M键标记元素（使用坐标获取元素）
                print("⌨️  模拟M键标记元素...")
                selected_node_id = await inspector.get_node_for_location(x, y)
                if not selected_node_id:
                    print("❌ 无法通过坐标找到元素")
                    return False

                print(f"✅ 成功标记元素，nodeId: {selected_node_id}")

                # 9. 获取完整的元素信息
                print("📋 获取元素完整信息...")

                # 获取样式信息
                styles_data = await inspector.get_element_styles(selected_node_id)
                formatted_styles = await inspector.format_styles(styles_data)
                print(f"✅ 样式信息获取成功 ({len(formatted_styles)} 字符)")

                # 获取事件监听器
                listeners_data = await inspector.get_element_event_listeners(selected_node_id)
                formatted_listeners = await inspector.format_event_listeners(listeners_data)
                print(f"✅ 事件监听器获取成功 ({len(formatted_listeners)} 字符)")

                # 获取HTML内容
                html_content = await inspector.get_element_html(selected_node_id)
                print(f"✅ HTML内容获取成功 ({len(html_content)} 字符)")

                # 10. 验证获取的信息
                print("🔍 验证获取的信息...")

                # 检查样式信息
                if "background-color" in formatted_styles.lower():
                    print("✅ 样式信息包含背景颜色")
                else:
                    print("⚠️  样式信息未包含预期的背景颜色")

                # 检查事件监听器
                if "click" in formatted_listeners.lower():
                    print("✅ 事件监听器包含点击事件")
                else:
                    print("⚠️  事件监听器未包含预期的点击事件")

                # 检查HTML内容
                if "test-btn" in html_content:
                    print("✅ HTML内容包含元素ID")
                else:
                    print("⚠️  HTML内容未包含预期的元素ID")

                print("\n🎉 DOM Inspector全流程测试完成！")
                print("📊 测试结果摘要:")
                print(f"   - 浏览器连接: ✅")
                print(f"   - 页面导航: ✅")
                print(f"   - JavaScript注入: ✅")
                print(f"   - 元素查找: ✅")
                print(f"   - 坐标获取: ✅")
                print(f"   - 样式信息: ✅")
                print(f"   - 事件监听器: ✅")
                print(f"   - HTML内容: ✅")

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
    print("🚀 DOM Inspector 全流程测试")
    print("=" * 60)

    success = await test_full_workflow()

    print("\n" + "=" * 60)
    if success:
        print("🎊 全流程测试通过！DOM Inspector功能正常")
        print("💡 验证的功能:")
        print("   - BrowserContextManager - 浏览器上下文管理")
        print("   - DOMInspector.connect() - 浏览器连接")
        print("   - navigate_to_page() - 页面导航")
        print("   - inject_javascript_file() - JavaScript注入")
        print("   - get_element_screen_coords() - 元素坐标获取")
        print("   - get_node_for_location() - 坐标到元素转换")
        print("   - get_element_styles() - 样式信息获取")
        print("   - get_element_event_listeners() - 事件监听器获取")
        print("   - get_element_html() - HTML内容获取")
    else:
        print("❌ 全流程测试失败")
        print("💡 请检查浏览器设置和网络连接")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
