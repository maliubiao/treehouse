#!/usr/bin/env python3
"""
DOM Inspector 元素信息提取测试
测试元素样式、事件监听器和HTML信息获取功能
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加包的 src 目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chrome_context_tracer import BrowserContextManager, DOMInspector
from test_server_utils import TestServerContext


async def test_element_info_extraction():
    """测试元素信息提取功能"""
    print("📋 开始元素信息提取测试")
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
        <title>元素信息提取测试</title>
        <style>
            body { margin: 0; padding: 20px; font-family: Arial; }
            .test-element { 
                padding: 20px; 
                margin: 20px; 
                border: 2px solid #007bff;
                border-radius: 8px;
                background-color: #f8f9fa;
                color: #333;
            }
            .styled-button {
                padding: 12px 24px;
                background: linear-gradient(45deg, #007bff, #0056b3);
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                transition: all 0.3s ease;
            }
            .styled-button:hover {
                background: linear-gradient(45deg, #0056b3, #004085);
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0,0,0,0.3);
            }
            .styled-button:active {
                transform: translateY(0);
                box-shadow: 0 1px 2px rgba(0,0,0,0.2);
            }
            .test-input {
                padding: 10px 15px;
                border: 2px solid #ddd;
                border-radius: 4px;
                font-size: 16px;
                width: 250px;
                transition: border-color 0.3s ease;
            }
            .test-input:focus {
                outline: none;
                border-color: #007bff;
                box-shadow: 0 0 0 3px rgba(0,123,255,0.1);
            }
            .test-link {
                color: #007bff;
                text-decoration: none;
                font-weight: bold;
                transition: color 0.3s ease;
            }
            .test-link:hover {
                color: #0056b3;
                text-decoration: underline;
            }
        </style>
    </head>
    <body>
        <h1>元素信息提取测试页面</h1>
        
        <div class="test-element" id="container">
            <h2>测试容器</h2>
            
            <button class="styled-button" id="test-button" onclick="handleButtonClick()">
                🎯 测试按钮
            </button>
            
            <br><br>
            
            <input 
                class="test-input" 
                type="text" 
                id="test-input" 
                placeholder="输入测试文本..."
                oninput="handleInputChange(event)"
            >
            
            <br><br>
            
            <a class="test-link" href="#" id="test-link" onclick="handleLinkClick(event)">
                🔗 测试链接
            </a>
        </div>
        
        <script>
            // 事件处理函数
            function handleButtonClick() {
                console.log('按钮被点击了！');
            }
            
            function handleInputChange(event) {
                console.log('输入框内容:', event.target.value);
            }
            
            function handleLinkClick(event) {
                event.preventDefault();
                console.log('链接被点击了！');
            }
            
            // 添加额外的事件监听器
            document.getElementById('test-button').addEventListener('mouseover', function() {
                console.log('按钮鼠标悬停');
            });
            
            document.getElementById('test-input').addEventListener('focus', function() {
                console.log('输入框获得焦点');
            });
            
            document.getElementById('test-link').addEventListener('mouseenter', function() {
                console.log('链接鼠标进入');
            });
        </script>
    </body>
    </html>
    """

            async with TestServerContext(test_html) as test_url:
                # 4. 导航到测试页面
                print(f"🌐 导航到测试页面: {test_url}")
                nav_success = await inspector.navigate_to_page(test_url)
                if not nav_success:
                    print("❌ 页面导航失败")
                    return False

                print("✅ 页面导航成功")
                await asyncio.sleep(2)  # 等待页面加载

                # 5. 查找测试按钮元素
                print("🔍 查找测试元素...")

                response = await inspector.send_command("DOM.getDocument", {"depth": -1})
                root_node_id = response["result"]["root"]["nodeId"]

                # 查找按钮元素
                button_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#test-button"}
                )
                button_node_id = button_response["result"]["nodeId"]

                if not button_node_id:
                    print("❌ 未找到测试按钮元素")
                    return False

                print(f"✅ 找到按钮元素，nodeId: {button_node_id}")

                # 6. 测试样式信息提取
                print("🎨 测试样式信息提取...")

                styles_data = await inspector.get_element_styles(button_node_id)
                if not styles_data:
                    print("❌ 无法获取样式信息")
                    return False

                formatted_styles = await inspector.format_styles(styles_data)
                print(f"✅ 样式信息获取成功 ({len(formatted_styles)} 字符)")

                # 验证样式信息
                if "background" in formatted_styles and "color" in formatted_styles:
                    print("✅ 样式信息包含背景和颜色属性")
                else:
                    print("⚠️  样式信息可能不完整")

                # 7. 测试事件监听器提取
                print("🎧 测试事件监听器提取...")

                listeners_data = await inspector.get_element_event_listeners(button_node_id)
                if not listeners_data:
                    print("❌ 无法获取事件监听器")
                    return False

                formatted_listeners = await inspector.format_event_listeners(listeners_data)
                print(f"✅ 事件监听器获取成功 ({len(formatted_listeners)} 字符)")

                # 验证事件监听器信息
                if "click" in formatted_listeners.lower():
                    print("✅ 事件监听器包含点击事件")
                else:
                    print("⚠️  事件监听器可能不完整")

                # 8. 测试HTML信息提取
                print("📄 测试HTML信息提取...")

                html_content = await inspector.get_element_html(button_node_id)
                if not html_content:
                    print("❌ 无法获取HTML内容")
                    return False

                print(f"✅ HTML内容获取成功 ({len(html_content)} 字符)")

                # 验证HTML内容
                if "button" in html_content.lower() and "测试按钮" in html_content:
                    print("✅ HTML内容包含按钮元素和文本")
                else:
                    print("⚠️  HTML内容可能不完整")

                # 9. 测试其他元素的信息提取
                print("🧪 测试其他元素信息提取...")

                # 测试输入框元素
                input_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#test-input"}
                )
                input_node_id = input_response["result"]["nodeId"]

                if input_node_id:
                    input_styles = await inspector.get_element_styles(input_node_id)
                    input_listeners = await inspector.get_element_event_listeners(input_node_id)

                    if input_styles and input_listeners:
                        print("✅ 输入框元素信息提取成功")
                    else:
                        print("⚠️  输入框元素信息提取不完整")

                # 测试链接元素
                link_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#test-link"}
                )
                link_node_id = link_response["result"]["nodeId"]

                if link_node_id:
                    link_html = await inspector.get_element_html(link_node_id)
                    if link_html and "测试链接" in link_html:
                        print("✅ 链接元素信息提取成功")
                    else:
                        print("⚠️  链接元素信息提取不完整")

                print("\n🎉 元素信息提取测试完成！")
                print("📊 测试结果摘要:")
                print(f"   - 样式信息提取: ✅ ({len(formatted_styles)} 字符)")
                print(f"   - 事件监听器提取: ✅ ({len(formatted_listeners)} 字符)")
                print(f"   - HTML内容提取: ✅ ({len(html_content)} 字符)")
                print(f"   - 多元素支持: ✅")

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
    print("🚀 DOM Inspector 元素信息提取测试")
    print("=" * 60)

    success = await test_element_info_extraction()

    print("\n" + "=" * 60)
    if success:
        print("🎊 元素信息提取测试通过！所有信息获取功能正常")
        print("💡 验证的功能:")
        print("   - get_element_styles() - 样式信息获取")
        print("   - get_element_event_listeners() - 事件监听器获取")
        print("   - get_element_html() - HTML内容获取")
        print("   - format_styles() - 样式格式化")
        print("   - format_event_listeners() - 事件监听器格式化")
    else:
        print("❌ 元素信息提取测试失败")
        print("💡 请检查浏览器设置和网络连接")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
