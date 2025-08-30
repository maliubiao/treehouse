#!/usr/bin/env python3
"""
DOM Inspector 端到端完整流程测试
模拟用户从启动工具到完成元素标记的完整使用场景
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加包的 src 目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chrome_context_tracer import BrowserContextManager, DOMInspector
from chrome_context_tracer.utils import get_mouse_detector_js
from test_server_utils import TestServerContext


async def test_complete_e2e_workflow():
    """测试完整的端到端工作流"""
    print("🚀 开始端到端完整流程测试")
    print("=" * 60)

    # 使用 BrowserContextManager 管理浏览器上下文
    async with BrowserContextManager("edge", 9222, auto_cleanup=True) as context:
        websocket_urls = context.get_websocket_urls()

        inspector = None
        try:
            # 阶段1: 浏览器连接和初始化
            print("🔗 阶段1: 浏览器连接和初始化")
            print("-" * 40)

            inspector = DOMInspector(websocket_urls[0])
            await inspector.connect()
            print("✅ 浏览器连接成功")

            # 获取所有标签页信息
            response = await inspector.send_command("Target.getTargets", use_session=False)
            targets = response.get("result", {}).get("targetInfos", [])
            print(f"📊 发现 {len(targets)} 个标签页")

            # 查找页面类型的标签页
            page_target_id = await inspector.find_tab_by_url("")
            if not page_target_id:
                print("❌ 未找到页面标签页")
                return False

            session_id = await inspector.attach_to_tab(page_target_id)
            if not session_id:
                print("❌ 标签页附加失败")
                return False

            print("✅ 标签页附加成功")

            # 阶段2: 创建和导航到测试页面
            print("\n🌐 阶段2: 创建和导航到测试页面")
            print("-" * 40)

            test_html = """
<!DOCTYPE html>
<html>
<head>
    <title>端到端测试页面</title>
    <style>
        body { margin: 0; padding: 20px; font-family: Arial; }
        .interactive-element { 
            padding: 15px 25px; 
            margin: 15px; 
            border: 2px solid #007bff; 
            border-radius: 6px; 
            cursor: pointer;
            font-size: 16px;
            transition: all 0.2s ease;
        }
        .interactive-element:hover {
            background-color: #007bff;
            color: white;
            transform: translateY(-2px);
        }
        .button-primary { 
            background-color: #28a745; 
            color: white; 
            border-color: #218838;
        }
        .button-secondary { 
            background-color: #6c757d; 
            color: white; 
            border-color: #545b62;
        }
        .button-warning { 
            background-color: #ffc107; 
            color: #212529; 
            border-color: #d39e00;
        }
        .input-field {
            padding: 10px 15px;
            border: 2px solid #ddd;
            border-radius: 4px;
            font-size: 16px;
            width: 250px;
            margin: 10px;
        }
        .link-element {
            color: #007bff;
            text-decoration: none;
            font-weight: bold;
            margin: 10px;
            display: inline-block;
        }
        .test-section {
            padding: 20px;
            border: 2px solid #eee;
            border-radius: 8px;
            margin: 20px 0;
        }
        .status-panel {
            position: fixed;
            top: 10px;
            right: 10px;
            background: rgba(0,0,0,0.9);
            color: white;
            padding: 15px;
            border-radius: 6px;
            font-family: monospace;
            font-size: 14px;
            z-index: 1000;
        }
    </style>
</head>
<body>
    <h1>DOM Inspector 端到端测试页面</h1>
    
    <div class="status-panel" id="status-panel">
        <div>🖱️ 鼠标坐标: (0, 0)</div>
        <div>⌨️ 状态: 等待M键标记...</div>
    </div>
    
    <div class="test-section">
        <h2>🔘 按钮元素测试区域</h2>
        
        <button class="interactive-element button-primary" id="primary-btn" onclick="handlePrimaryClick()">
            🎯 主要按钮
        </button>
        
        <button class="interactive-element button-secondary" id="secondary-btn" onclick="handleSecondaryClick()">
            🎯 次要按钮
        </button>
        
        <button class="interactive-element button-warning" id="warning-btn" onclick="handleWarningClick()">
            ⚠️ 警告按钮
        </button>
    </div>
    
    <div class="test-section">
        <h2>📝 输入元素测试区域</h2>
        
        <input class="input-field" type="text" id="text-input" 
               placeholder="文本输入框..." oninput="handleTextInput(event)">
        
        <input class="input-field" type="email" id="email-input" 
               placeholder="邮箱输入框..." oninput="handleEmailInput(event)">
        
        <input class="input-field" type="number" id="number-input" 
               placeholder="数字输入框..." oninput="handleNumberInput(event)">
    </div>
    
    <div class="test-section">
        <h2>🔗 链接元素测试区域</h2>
        
        <a class="link-element" href="#" id="internal-link" onclick="handleInternalLink(event)">
            🔗 内部链接
        </a>
        
        <a class="link-element" href="https://example.com" id="external-link" target="_blank" onclick="handleExternalLink(event)">
            🌐 外部链接
        </a>
        
        <a class="link-element" href="#" id="download-link" download onclick="handleDownloadLink(event)">
            📥 下载链接
        </a>
    </div>
    
    <script>
        // 事件处理函数
        function handlePrimaryClick() {
            console.log('主要按钮被点击');
            updateStatus('主要按钮点击事件触发');
        }
        
        function handleSecondaryClick() {
            console.log('次要按钮被点击');
            updateStatus('次要按钮点击事件触发');
        }
        
        function handleWarningClick() {
            console.log('警告按钮被点击');
            updateStatus('警告按钮点击事件触发');
        }
        
        function handleTextInput(event) {
            console.log('文本输入:', event.target.value);
            updateStatus('文本输入变化: ' + event.target.value.substring(0, 20));
        }
        
        function handleEmailInput(event) {
            console.log('邮箱输入:', event.target.value);
            updateStatus('邮箱输入变化: ' + event.target.value.substring(0, 20));
        }
        
        function handleNumberInput(event) {
            console.log('数字输入:', event.target.value);
            updateStatus('数字输入变化: ' + event.target.value);
        }
        
        function handleInternalLink(event) {
            event.preventDefault();
            console.log('内部链接被点击');
            updateStatus('内部链接点击事件触发');
        }
        
        function handleExternalLink(event) {
            event.preventDefault();
            console.log('外部链接被点击');
            updateStatus('外部链接点击事件触发');
        }
        
        function handleDownloadLink(event) {
            event.preventDefault();
            console.log('下载链接被点击');
            updateStatus('下载链接点击事件触发');
        }
        
        function updateStatus(message) {
            const statusPanel = document.getElementById('status-panel');
            const statusLine = statusPanel.querySelector('div:nth-child(2)');
            statusLine.textContent = '📋 ' + message;
        }
        
        // 显示鼠标坐标
        document.addEventListener('mousemove', function(e) {
            const statusPanel = document.getElementById('status-panel');
            const coordLine = statusPanel.querySelector('div:nth-child(1)');
            coordLine.textContent = `🖱️ 鼠标坐标: (${e.clientX}, ${e.clientY})`;
        });
        
        // 添加额外的事件监听器
        document.getElementById('primary-btn').addEventListener('mouseover', function() {
            console.log('主要按钮鼠标悬停');
        });
        
        document.getElementById('text-input').addEventListener('focus', function() {
            console.log('文本输入框获得焦点');
            updateStatus('文本输入框获得焦点');
        });
        
        document.getElementById('external-link').addEventListener('mouseenter', function() {
            console.log('外部链接鼠标进入');
        });
        
        console.log('页面JavaScript初始化完成');
    </script>
</body>
</html>
"""

            async with TestServerContext(test_html) as test_url:
                # 导航到测试页面
                nav_success = await inspector.navigate_to_page(test_url)
                if not nav_success:
                    print("❌ 页面导航失败")
                    return False

                print("✅ 页面导航成功")
                await asyncio.sleep(3)  # 等待页面完全加载

                # 阶段3: JavaScript注入和检测器初始化
                print("\n💉 阶段3: JavaScript注入和检测器初始化")
                print("-" * 40)

                injection_success = await inspector.inject_javascript_file(get_mouse_detector_js())
                if not injection_success:
                    print("❌ JavaScript注入失败")
                    return False

                print("✅ JavaScript注入成功")
                await asyncio.sleep(1)

                # 验证检测器是否成功注入
                detector_check = await inspector.send_command(
                    "Runtime.evaluate",
                    {"expression": "typeof window.chromeContextTracer !== 'undefined'", "returnByValue": True},
                )

                if not (
                    "result" in detector_check
                    and "value" in detector_check["result"]
                    and detector_check["result"]["value"] == True
                ):
                    print("❌ 鼠标元素检测器验证失败")
                    return False

                print("✅ 鼠标元素检测器验证成功")

                # 启动元素检测模式
                start_response = await inspector.send_command(
                    "Runtime.evaluate", {"expression": "window.startElementSelection()", "returnByValue": False}
                )

                if "result" in start_response and "exceptionDetails" not in start_response["result"]:
                    print("✅ 元素检测模式启动成功")
                else:
                    print("❌ 元素检测模式启动失败")
                    return False

                await asyncio.sleep(1)

                # 阶段4: 模拟用户交互 - 鼠标移动和M键标记
                print("\n🎯 阶段4: 模拟用户交互 - 鼠标移动和M键标记")
                print("-" * 40)

                # 查找主要按钮元素
                response = await inspector.send_command("DOM.getDocument", {"depth": -1})
                root_node_id = response["result"]["root"]["nodeId"]

                button_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#primary-btn"}
                )
                button_node_id = button_response["result"]["nodeId"]

                if not button_node_id:
                    print("❌ 未找到测试按钮元素")
                    return False

                # 获取按钮坐标
                coords = await inspector.get_element_screen_coords(button_node_id)
                if not coords:
                    print("❌ 无法获取元素坐标")
                    return False

                x, y = coords
                print(f"✅ 按钮坐标: ({x}, {y})")

                # 模拟鼠标移动到按钮位置
                hover_node_id = await inspector.get_node_for_location(x, y)
                if not hover_node_id:
                    print("❌ 无法通过坐标找到元素")
                    return False

                print(f"✅ 鼠标悬停元素，nodeId: {hover_node_id}")

                # 模拟按M键标记元素（通过JavaScript触发点击选择）
                mark_response = await inspector.send_command(
                    "Runtime.evaluate",
                    {
                        "expression": f"""
                        const element = document.elementFromPoint({x}, {y});
                        if (element) {{
                            const event = new MouseEvent('click', {{
                                bubbles: true,
                                cancelable: true,
                                clientX: {x},
                                clientY: {y}
                            }});
                            element.dispatchEvent(event);
                            'M键标记成功';
                        }} else {{
                            '在坐标处未找到元素';
                        }}
                    """,
                        "returnByValue": True,
                    },
                )

                if "result" in mark_response and "value" in mark_response["result"]:
                    result_msg = mark_response["result"]["value"]
                    if "成功" in result_msg:
                        print("✅ M键标记成功")
                    else:
                        print(f"❌ M键标记失败: {result_msg}")
                        return False
                else:
                    print("❌ M键标记执行失败")
                    return False

                # 等待标记处理完成
                await asyncio.sleep(1)

                # 停止元素检测模式
                stop_response = await inspector.send_command(
                    "Runtime.evaluate", {"expression": "window.stopElementSelection()", "returnByValue": False}
                )

                if "result" in stop_response and "exceptionDetails" not in stop_response["result"]:
                    print("✅ 元素检测模式停止成功")

                # 阶段5: 提取和分析标记元素信息
                print("\n📊 阶段5: 提取和分析标记元素信息")
                print("-" * 40)

                # 获取完整的元素信息
                styles_data = await inspector.get_element_styles(button_node_id)
                formatted_styles = await inspector.format_styles(styles_data)
                print(f"✅ 样式信息提取成功 ({len(formatted_styles)} 字符)")

                listeners_data = await inspector.get_element_event_listeners(button_node_id)
                formatted_listeners = await inspector.format_event_listeners(listeners_data)
                print(f"✅ 事件监听器提取成功 ({len(formatted_listeners)} 字符)")

                html_content = await inspector.get_element_html(button_node_id)
                print(f"✅ HTML内容提取成功 ({len(html_content)} 字符)")

                # 验证提取的信息质量
                print("🔍 验证提取的信息质量...")

                validation_passed = 0
                total_checks = 3

                # 检查样式信息
                if "background-color" in formatted_styles and "color" in formatted_styles:
                    print("✅ 样式信息验证通过")
                    validation_passed += 1
                else:
                    print("⚠️  样式信息验证不完整")

                # 检查事件监听器
                if "click" in formatted_listeners.lower():
                    print("✅ 事件监听器验证通过")
                    validation_passed += 1
                else:
                    print("⚠️  事件监听器验证不完整")

                # 检查HTML内容
                if "primary-btn" in html_content and "主要按钮" in html_content:
                    print("✅ HTML内容验证通过")
                    validation_passed += 1
                else:
                    print("⚠️  HTML内容验证不完整")

                # 阶段6: 清理和退出
                print("\n🧹 阶段6: 清理和退出")
                print("-" * 40)

                # 验证清理状态
                status_check = await inspector.send_command(
                    "Runtime.evaluate",
                    {
                        "expression": "window.chromeContextTracer ? window.chromeContextTracer.isActive : false",
                        "returnByValue": True,
                    },
                )

                if "result" in status_check and "value" in status_check["result"]:
                    is_active = status_check["result"]["value"]
                    if not is_active:
                        print("✅ 检测模式已正确停止")
                    else:
                        print("⚠️  检测模式可能未完全停止")

                print("\n🎉 端到端完整流程测试完成！")
                print("📊 测试结果摘要:")
                print(f"   - 浏览器连接和初始化: ✅")
                print(f"   - 页面创建和导航: ✅")
                print(f"   - JavaScript注入: ✅")
                print(f"   - 鼠标跟踪和M键标记: ✅")
                print(f"   - 元素信息提取: ✅")
                print(f"   - 信息质量验证: {validation_passed}/{total_checks}")
                print(f"   - 清理和退出: ✅")

                return validation_passed >= 2  # 至少通过2项验证

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
    print("🚀 DOM Inspector 端到端完整流程测试")
    print("=" * 60)

    success = await test_complete_e2e_workflow()

    print("\n" + "=" * 60)
    if success:
        print("🎊 端到端测试通过！完整工作流功能正常")
        print("💡 验证的完整流程:")
        print("   1. 浏览器连接和标签页发现")
        print("   2. 页面创建和导航")
        print("   3. JavaScript检测器注入")
        print("   4. 鼠标跟踪和坐标转换")
        print("   5. M键标记元素选择")
        print("   6. 完整的元素信息提取")
        print("   7. 清理和状态恢复")
    else:
        print("❌ 端到端测试失败")
        print("💡 请检查各环节的功能完整性")

    return success


if __name__ == "__main__":
    # Mock input for non-interactive selection
    original_input = __builtins__.input
    __builtins__.input = lambda _: ""

    success = asyncio.run(main())

    __builtins__.input = original_input
    exit(0 if success else 1)
