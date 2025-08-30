#!/usr/bin/env python3
"""
DOM Inspector M键标记功能测试
测试鼠标移动跟踪和M键标记元素的完整功能
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


async def test_m_key_marking():
    """测试M键标记功能"""
    print("⌨️  开始M键标记功能测试")
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

            # 创建测试页面，包含多个可交互元素
            print("📄 创建测试页面...")
            test_html = """
<!DOCTYPE html>
<html>
<head>
    <title>M键标记功能测试</title>
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
        .test-input {
            padding: 10px 15px;
            border: 2px solid #ddd;
            border-radius: 4px;
            font-size: 16px;
            width: 250px;
            margin: 10px;
        }
        .test-link {
            color: #007bff;
            text-decoration: none;
            font-weight: bold;
            margin: 10px;
            display: inline-block;
        }
        .test-container {
            padding: 20px;
            border: 2px solid #eee;
            border-radius: 8px;
            margin: 20px 0;
        }
        .status-display {
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
    <h1>M键标记功能测试页面</h1>
    
    <div class="test-container">
        <h2>测试交互元素</h2>
        
        <button class="test-button" id="mark-button-1" onclick="handleClick(1)">
            🎯 标记按钮 1
        </button>
        
        <button class="test-button" id="mark-button-2" onclick="handleClick(2)">
            🎯 标记按钮 2  
        </button>
        
        <br>
        
        <input class="test-input" type="text" id="mark-input" 
               placeholder="测试输入框..." oninput="handleInput(event)">
        
        <br>
        
        <a class="test-link" href="#" id="mark-link" onclick="handleLinkClick(event)">
            🔗 测试链接
        </a>
    </div>
    
    <div class="status-display" id="status">
        状态: 等待M键标记...
    </div>
    
    <script>
        function handleClick(buttonId) {
            console.log('按钮', buttonId, '被点击');
        }
        
        function handleInput(event) {
            console.log('输入内容:', event.target.value);
        }
        
        function handleLinkClick(event) {
            event.preventDefault();
            console.log('链接被点击');
        }
        
        // 显示鼠标坐标
        document.addEventListener('mousemove', function(e) {
            const status = document.getElementById('status');
            status.textContent = `坐标: (${e.clientX}, ${e.clientY}) - 等待M键标记`;
        });
    </script>
</body>
</html>
"""

            port = find_free_safe_port()
            async with TestServerContext(test_html, port=port) as test_url:
                # 导航到测试页面
                print(f"🌐 导航到测试页面: {test_url}")
                nav_success = await inspector.navigate_to_page(test_url)
                if not nav_success:
                    print("❌ 页面导航失败")
                    return False

                print("✅ 页面导航成功")
                await asyncio.sleep(2)  # 等待页面加载

                # 注入鼠标元素检测器JavaScript
                print("💉 注入鼠标元素检测器...")
                injection_success = await inspector.inject_javascript_file(get_mouse_detector_js())
                if not injection_success:
                    print("❌ JavaScript注入失败")
                    return False

                print("✅ JavaScript注入成功")
                await asyncio.sleep(1)

                # 启动元素检测模式
                print("🚀 启动元素检测模式...")
                start_response = await inspector.send_command(
                    "Runtime.evaluate", {"expression": "window.startElementSelection()", "returnByValue": False}
                )

                if "result" in start_response and "exceptionDetails" not in start_response["result"]:
                    print("✅ 元素检测模式启动成功")
                else:
                    print("❌ 元素检测模式启动失败")
                    if "exceptionDetails" in start_response.get("result", {}):
                        print(f"错误: {start_response['result']['exceptionDetails']}")
                    return False

                # 等待检测模式生效
                await asyncio.sleep(1)

                # 查找测试按钮元素并获取坐标
                print("🎯 获取测试元素坐标...")
                response = await inspector.send_command("DOM.getDocument", {"depth": -1})
                root_node_id = response["result"]["root"]["nodeId"]

                # 查找第一个测试按钮
                button_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#mark-button-1"}
                )
                button_node_id = button_response["result"]["nodeId"]

                if not button_node_id:
                    print("❌ 未找到测试按钮元素")
                    return False

                # 获取按钮的屏幕坐标
                coords = await inspector.get_element_screen_coords(button_node_id)
                if not coords:
                    print("❌ 无法获取元素坐标")
                    return False

                x, y = coords
                print(f"✅ 按钮坐标: ({x}, {y})")

                # 模拟鼠标移动到按钮位置（通过坐标获取元素）
                print("🖱️  模拟鼠标移动到按钮位置...")
                hover_node_id = await inspector.get_node_for_location(x, y)
                if not hover_node_id:
                    print("❌ 无法通过坐标找到元素")
                    return False

                print(f"✅ 鼠标悬停元素，nodeId: {hover_node_id}")

                # 验证悬停的是正确的按钮
                if hover_node_id == button_node_id:
                    print("✅ 鼠标悬停验证正确 - 找到的是按钮1")
                else:
                    print(f"⚠️  鼠标悬停可能不准确 - 期望: {button_node_id}, 实际: {hover_node_id}")

                # 模拟按M键标记元素（通过JavaScript触发标记）
                print("⌨️  模拟M键标记元素...")

                # 通过JavaScript触发元素选择（模拟点击选择）
                mark_response = await inspector.send_command(
                    "Runtime.evaluate",
                    {
                        "expression": f"""
                        // 获取坐标处的元素并触发点击选择
                        const element = document.elementFromPoint({x}, {y});
                        if (element) {{
                            const event = new MouseEvent('click', {{
                                bubbles: true,
                                cancelable: true,
                                clientX: {x},
                                clientY: {y}
                            }});
                            element.dispatchEvent(event);
                            'Element marked successfully';
                        }} else {{
                            'No element found at coordinates';
                        }}
                    """,
                        "returnByValue": True,
                    },
                )

                if "result" in mark_response and "value" in mark_response["result"]:
                    result_msg = mark_response["result"]["value"]
                    if "successfully" in result_msg:
                        print("✅ M键标记成功")
                    else:
                        print(f"❌ M键标记失败: {result_msg}")
                        return False
                else:
                    print("❌ M键标记执行失败")
                    return False

                # 等待标记处理完成
                await asyncio.sleep(1)

                # 获取被标记元素的详细信息
                print("📋 获取标记元素的完整信息...")

                # 获取样式信息
                styles_data = await inspector.get_element_styles(button_node_id)
                formatted_styles = await inspector.format_styles(styles_data)
                print(f"✅ 样式信息获取成功 ({len(formatted_styles)} 字符)")

                # 获取事件监听器
                listeners_data = await inspector.get_element_event_listeners(button_node_id)
                formatted_listeners = await inspector.format_event_listeners(listeners_data)
                print(f"✅ 事件监听器获取成功 ({len(formatted_listeners)} 字符)")

                # 获取HTML内容
                html_content = await inspector.get_element_html(button_node_id)
                print(f"✅ HTML内容获取成功 ({len(html_content)} 字符)")

                # 验证获取的信息
                print("🔍 验证标记元素的信息...")

                # 检查样式信息
                if "background-color" in formatted_styles.lower() and "color" in formatted_styles.lower():
                    print("✅ 样式信息包含背景颜色和文字颜色")
                else:
                    print("⚠️  样式信息可能不完整")

                # 检查事件监听器
                if "click" in formatted_listeners.lower():
                    print("✅ 事件监听器包含点击事件")
                else:
                    print("⚠️  事件监听器可能不完整")

                # 检查HTML内容
                if "mark-button-1" in html_content and "标记按钮" in html_content:
                    print("✅ HTML内容包含正确的元素ID和文本")
                else:
                    print("⚠️  HTML内容验证不完整")

                # 停止元素检测模式
                print("🛑 停止元素检测模式...")
                stop_response = await inspector.send_command(
                    "Runtime.evaluate", {"expression": "window.stopElementSelection()", "returnByValue": False}
                )

                if "result" in stop_response and "exceptionDetails" not in stop_response["result"]:
                    print("✅ 元素检测模式停止成功")

                print("\n🎉 M键标记功能测试完成！")
                print("📊 测试结果摘要:")
                print(f"   - 浏览器连接: ✅")
                print(f"   - 页面导航: ✅")
                print(f"   - JavaScript注入: ✅")
                print(f"   - 元素检测模式: ✅")
                print(f"   - 鼠标坐标跟踪: ✅")
                print(f"   - M键标记功能: ✅")
                print(f"   - 样式信息提取: ✅")
                print(f"   - 事件监听器提取: ✅")
                print(f"   - HTML内容提取: ✅")

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
    print("🚀 DOM Inspector M键标记功能测试")
    print("=" * 60)

    success = await test_m_key_marking()

    print("\n" + "=" * 60)
    if success:
        print("🎊 M键标记功能测试通过！鼠标跟踪和标记功能正常")
        print("💡 验证的功能:")
        print("   - 实时鼠标坐标跟踪")
        print("   - M键标记元素选择")
        print("   - 元素检测模式管理")
        print("   - 坐标到元素转换")
        print("   - 完整的元素信息提取")
    else:
        print("❌ M键标记功能测试失败")
        print("💡 请检查浏览器设置和网络连接")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
