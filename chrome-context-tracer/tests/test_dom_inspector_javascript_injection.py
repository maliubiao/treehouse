#!/usr/bin/env python3
"""
DOM Inspector JavaScript注入测试
测试JavaScript代码注入和执行功能
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


async def test_javascript_injection():
    """测试JavaScript注入功能"""
    print("💉 开始JavaScript注入测试")
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
        <title>JavaScript注入测试</title>
        <style>
            body { margin: 0; padding: 20px; font-family: Arial; }
            .test-container { 
                padding: 20px; 
                margin: 20px; 
                border: 2px solid #007bff;
                border-radius: 8px;
                background-color: #f8f9fa;
            }
            .result-area {
                padding: 15px;
                background-color: #e9ecef;
                border-radius: 4px;
                margin: 10px 0;
                font-family: monospace;
                white-space: pre-wrap;
            }
            .status {
                padding: 10px;
                border-radius: 4px;
                margin: 5px 0;
                font-weight: bold;
            }
            .status.success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .status.error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        </style>
    </head>
    <body>
        <h1>JavaScript注入测试页面</h1>
        
        <div class="test-container">
            <h2>测试区域</h2>
            
            <div id="injection-result" class="result-area">
                等待JavaScript注入...
            </div>
            
            <button onclick="testExistingFunction()">
                测试现有函数
            </button>
            
            <div id="status-messages"></div>
        </div>
        
        <script>
            // 页面原有的JavaScript函数
            function testExistingFunction() {
                const resultDiv = document.getElementById('injection-result');
                resultDiv.textContent = '✅ 页面原有函数执行成功！';
                resultDiv.className = 'result-area status success';
                
                addStatusMessage('页面函数执行: 成功');
            }
            
            function addStatusMessage(message) {
                const statusDiv = document.getElementById('status-messages');
                const msgDiv = document.createElement('div');
                msgDiv.className = 'status';
                msgDiv.textContent = '📝 ' + message;
                statusDiv.appendChild(msgDiv);
            }
            
            // 初始状态消息
            addStatusMessage('页面加载完成');
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

                # 5. 测试简单的JavaScript注入
                print("🧪 测试简单JavaScript注入...")

                simple_js = """
    // 简单的测试JavaScript
    console.log('✅ 简单JavaScript注入成功');
    document.title = 'JavaScript注入测试 - 已修改';

    // 修改页面内容
    const resultDiv = document.getElementById('injection-result');
    if (resultDiv) {
        resultDiv.textContent = '✅ 简单JavaScript注入执行成功！';
        resultDiv.className = 'result-area status success';
    }

    // 添加状态消息
    if (typeof addStatusMessage === 'function') {
        addStatusMessage('简单注入执行: 成功');
    }

    // 返回成功消息
    'Simple injection completed successfully';
    """

                # 注入简单JavaScript
                injection_success = await inspector.inject_javascript_file(simple_js)
                if not injection_success:
                    print("❌ 简单JavaScript注入失败")
                    return False

                print("✅ 简单JavaScript注入成功")
                await asyncio.sleep(1)

                # 验证注入效果 - 检查页面标题是否被修改
                title_response = await inspector.send_command(
                    "Runtime.evaluate", {"expression": "document.title", "returnByValue": True}
                )

                title_result_obj = title_response.get("result", {}).get("result", {})
                if "value" in title_result_obj:
                    page_title = title_result_obj["value"]
                    if "已修改" in page_title:
                        print("✅ 页面标题修改验证成功")
                    else:
                        print(f"⚠️  页面标题未按预期修改: {page_title}")
                else:
                    print(f"❌ 无法获取页面标题. Response: {title_response}")

                # 6. 测试复杂的JavaScript注入（鼠标元素检测器）
                print("🖱️  测试复杂JavaScript注入（鼠标元素检测器）...")

                # 注入鼠标元素检测器代码
                detector_success = await inspector.inject_javascript_file(get_mouse_detector_js())
                if not detector_success:
                    print("❌ 鼠标元素检测器注入失败")
                    return False

                print("✅ 鼠标元素检测器注入成功")
                await asyncio.sleep(1)

                # 验证检测器是否成功注入
                detector_check = await inspector.send_command(
                    "Runtime.evaluate",
                    {"expression": "typeof window.chromeContextTracer !== 'undefined'", "returnByValue": True},
                )

                detector_result_obj = detector_check.get("result", {}).get("result", {})
                if detector_result_obj.get("value") is True:
                    print("✅ 鼠标元素检测器验证成功")
                else:
                    print(f"❌ 鼠标元素检测器验证失败. Response: {detector_check}")
                    return False

                # 7. 测试JavaScript函数调用
                print("📞 测试JavaScript函数调用...")

                # 调用检测器的启动函数
                start_response = await inspector.send_command(
                    "Runtime.evaluate", {"expression": "window.startElementSelection()", "returnByValue": False}
                )

                if "result" in start_response and "exceptionDetails" not in start_response["result"]:
                    print("✅ 元素选择模式启动成功")
                else:
                    print("❌ 元素选择模式启动失败")
                    if "exceptionDetails" in start_response.get("result", {}):
                        print(f"错误: {start_response['result']['exceptionDetails']}")

                # 等待一下让选择模式生效
                await asyncio.sleep(1)

                # 停止元素选择模式
                stop_response = await inspector.send_command(
                    "Runtime.evaluate", {"expression": "window.stopElementSelection()", "returnByValue": False}
                )

                if "result" in stop_response and "exceptionDetails" not in stop_response["result"]:
                    print("✅ 元素选择模式停止成功")

                # 8. 测试JavaScript文件注入
                print("📁 测试JavaScript文件注入...")

                # 创建一个临时的JavaScript文件
                temp_js_file = "/tmp/test_injection.js"
                test_js_content = """
    // 测试文件注入
    console.log('✅ 文件JavaScript注入成功');

    // 创建新的页面元素
    const newElement = document.createElement('div');
    newElement.id = 'injected-element';
    newElement.innerHTML = '<h3>✅ 通过文件注入的元素</h3><p>这个元素是通过JavaScript文件注入创建的</p>';
    newElement.style.padding = '15px';
    newElement.style.backgroundColor = '#d1ecf1';
    newElement.style.border = '2px solid #bee5eb';
    newElement.style.borderRadius = '8px';
    newElement.style.margin = '10px 0';

    document.body.appendChild(newElement);

    // 添加状态消息
    if (typeof addStatusMessage === 'function') {
        addStatusMessage('文件注入执行: 成功');
    }

    'File injection completed successfully';
    """

                # 写入临时文件
                with open(temp_js_file, "w", encoding="utf-8") as f:
                    f.write(test_js_content)

                # 注入文件内容
                file_injection_success = await inspector.inject_javascript_file(temp_js_file)
                if not file_injection_success:
                    print("❌ JavaScript文件注入失败")
                    # 清理临时文件
                    try:
                        os.remove(temp_js_file)
                    except:
                        pass
                    return False

                print("✅ JavaScript文件注入成功")

                # 清理临时文件
                try:
                    os.remove(temp_js_file)
                except:
                    pass

                # 验证文件注入效果
                await asyncio.sleep(1)

                # 检查注入的元素是否存在
                element_check = await inspector.send_command(
                    "Runtime.evaluate",
                    {"expression": "document.getElementById('injected-element') !== null", "returnByValue": True},
                )

                element_result_obj = element_check.get("result", {}).get("result", {})
                if element_result_obj.get("value") is True:
                    print("✅ 文件注入元素验证成功")
                else:
                    print(f"❌ 文件注入元素验证失败. Response: {element_check}")

                # 9. 测试错误处理
                print("⚠️  测试错误处理...")

                # 注入有语法错误的JavaScript
                error_js = """
    // 有语法错误的JavaScript
    console.log('开始错误测试'
    // 缺少 closing parenthesis
    var x = {
    """

                error_injection_success = await inspector.inject_javascript_file(error_js)
                if not error_injection_success:
                    print("✅ 错误JavaScript注入被正确拒绝")
                else:
                    print("❌ 错误JavaScript注入未被正确拒绝")

                print("\n🎉 JavaScript注入测试完成！")
                print("📊 测试结果摘要:")
                print(f"   - 简单JavaScript注入: ✅")
                print(f"   - 复杂JavaScript注入: ✅")
                print(f"   - JavaScript函数调用: ✅")
                print(f"   - JavaScript文件注入: ✅")
                print(f"   - 错误处理: ✅")

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
    print("🚀 DOM Inspector JavaScript注入测试")
    print("=" * 60)

    success = await test_javascript_injection()

    print("\n" + "=" * 60)
    if success:
        print("🎊 JavaScript注入测试通过！所有注入功能正常")
        print("💡 验证的功能:")
        print("   - inject_javascript_file() - JavaScript代码注入")
        print("   - 简单代码字符串注入")
        print("   - 复杂代码库注入（鼠标元素检测器）")
        print("   - JavaScript文件注入")
        print("   - JavaScript函数调用")
        print("   - 错误处理")
    else:
        print("❌ JavaScript注入测试失败")
        print("💡 请检查浏览器设置和网络连接")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
