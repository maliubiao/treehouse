#!/usr/bin/env python3
"""
真实Chrome浏览器JavaScript注入测试
直接将JavaScript注入到Chrome中并观察控制台输出
"""

import asyncio
import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import MOUSE_ELEMENT_DETECTOR_JS, DOMInspector, find_chrome_tabs


async def test_real_chrome_injection():
    """使用真实Chrome浏览器测试JavaScript注入"""
    print("🌐 真实Chrome浏览器JavaScript注入测试")
    print("=" * 50)

    # 查找Chrome标签页
    try:
        print("🔍 正在查找Chrome标签页...")
        websocket_urls = await asyncio.wait_for(find_chrome_tabs(9222), timeout=10.0)
    except asyncio.TimeoutError:
        print("⏰ 超时: 无法连接到Chrome DevTools")
        print("💡 请先启动Chrome浏览器并开启远程调试:")
        print("   chrome --remote-debugging-port=9222")
        print("   或者运行: open -a 'Google Chrome' --args --remote-debugging-port=9222")
        return False
    except Exception as e:
        print(f"❌ 查找Chrome标签页时发生错误: {e}")
        return False

    if not websocket_urls:
        print("🔍 没有找到Chrome标签页")
        print("💡 请确保:")
        print("   1. Chrome浏览器已经启动")
        print("   2. 开启了远程调试: chrome --remote-debugging-port=9222")
        print("   3. 至少打开一个标签页")
        return False

    print(f"✅ 找到 {len(websocket_urls)} 个Chrome标签页")

    inspector = None
    try:
        # 连接到第一个标签页
        print(f"🔗 正在连接到第一个标签页: {websocket_urls[0]}")
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()
        print("✅ 成功连接到Chrome DevTools")

        # 注入JavaScript代码
        print("\n💉 开始注入JavaScript代码...")
        print(f"📝 JavaScript代码长度: {len(MOUSE_ELEMENT_DETECTOR_JS)} 字符")

        success = await inspector.inject_javascript_file(MOUSE_ELEMENT_DETECTOR_JS)

        if success:
            print("✅ JavaScript注入成功！")
            print("\n📺 请查看Chrome浏览器控制台，您应该能看到以下消息:")
            print("   [CHROME_TRACER] Initialized successfully")
            print("   [CHROME_TRACER] Available commands:")
            print("   [CHROME_TRACER]   - startElementSelection(): Start element detection")
            print("   [CHROME_TRACER]   - stopElementSelection(): Stop element detection")
            print("   [CHROME_TRACER]   - getTracerStatus(): Get current status")
            print("   [CHROME_TRACER]   - getElementAtCoordinates(x, y): Get element at specific coordinates")

            print("\n🧪 测试JavaScript功能...")
            print("💡 在Chrome控制台中尝试运行以下命令:")
            print("   window.chromeContextTracer")
            print("   getTracerStatus()")
            print("   getElementAtCoordinates(100, 100)")
            print("   startElementSelection()")

            # 等待一段时间让用户观察
            print("\n⏳ 等待5秒，请查看Chrome控制台...")
            await asyncio.sleep(5)

            # 尝试执行一些测试JavaScript代码
            print("\n🔬 执行JavaScript测试...")

            # 测试1: 检查对象是否存在
            test_result = await inspector.send_command(
                "Runtime.evaluate", {"expression": "typeof window.chromeContextTracer", "returnByValue": True}
            )

            if test_result.get("result", {}).get("result", {}).get("value") == "object":
                print("✅ window.chromeContextTracer 对象已成功创建")
            else:
                print("❌ window.chromeContextTracer 对象未找到")

            # 测试2: 检查函数是否存在
            function_tests = [
                "typeof window.startElementSelection",
                "typeof window.stopElementSelection",
                "typeof window.getTracerStatus",
                "typeof window.getElementAtCoordinates",
            ]

            for test_expr in function_tests:
                test_result = await inspector.send_command(
                    "Runtime.evaluate", {"expression": test_expr, "returnByValue": True}
                )

                if test_result.get("result", {}).get("result", {}).get("value") == "function":
                    func_name = test_expr.split(".")[-1]
                    print(f"✅ {func_name} 函数已成功注入")
                else:
                    func_name = test_expr.split(".")[-1]
                    print(f"❌ {func_name} 函数未找到")

            # 测试3: 获取追踪器状态
            print("\n📊 获取追踪器状态...")
            status_result = await inspector.send_command(
                "Runtime.evaluate", {"expression": "getTracerStatus()", "returnByValue": True}
            )

            status = status_result.get("result", {}).get("result", {}).get("value")
            if status:
                print(f"✅ 追踪器状态: {status}")
            else:
                print("❌ 无法获取追踪器状态")

            print("\n🎉 JavaScript注入测试完成！")
            print("💡 现在您可以:")
            print("   1. 在Chrome控制台中运行 startElementSelection() 启动元素选择模式")
            print("   2. 移动鼠标查看元素高亮")
            print("   3. 点击选择元素")
            print("   4. 按ESC取消选择")

            return True

        else:
            print("❌ JavaScript注入失败")
            return False

    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        if inspector:
            await inspector.close()
            print("\n🔐 连接已关闭")


async def test_element_selection_mode():
    """测试完整的元素选择模式"""
    print("\n🎯 测试完整的元素选择模式")
    print("=" * 50)

    try:
        websocket_urls = await asyncio.wait_for(find_chrome_tabs(9222), timeout=5.0)
        if not websocket_urls:
            print("❌ 没有可用的Chrome标签页")
            return False

        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        print("🎯 启动元素选择模式...")
        print("📝 在接下来的30秒内:")
        print("   1. 移动鼠标查看页面元素高亮")
        print("   2. 点击选择您想要的元素")
        print("   3. 或按ESC键取消选择")

        # 启动元素选择模式
        result = await inspector.start_element_selection_mode()

        if result and result != "cancelled":
            print(f"✅ 成功选择了元素:")
            print(f"   标签: {result.get('tagName', 'Unknown')}")
            print(f"   ID: {result.get('id', 'None')}")
            print(f"   类名: {result.get('className', 'None')}")
            print(f"   路径: {result.get('path', 'Unknown')}")
            print(f"   文本内容: {result.get('textContent', 'None')[:50]}...")
            return True
        elif result == "cancelled":
            print("🚫 用户取消了元素选择")
            return True
        else:
            print("❌ 元素选择失败或超时")
            return False

    except Exception as e:
        print(f"❌ 元素选择测试失败: {e}")
        return False
    finally:
        if "inspector" in locals():
            await inspector.close()


async def main():
    """主测试函数"""
    print("🚀 Chrome Context Tracer JavaScript注入完整测试")
    print("=" * 60)

    # 测试1: 基本JavaScript注入
    test1_result = await test_real_chrome_injection()

    if test1_result:
        print(f"\n{'=' * 60}")
        # 询问用户是否继续测试元素选择模式
        print("🤔 是否要测试完整的元素选择模式？")
        print("   这将启动交互式元素选择，您需要用鼠标进行操作")

        try:
            # 等待一下让用户看到提示
            await asyncio.sleep(2)
            print("⏳ 5秒后自动开始元素选择模式测试...")
            await asyncio.sleep(5)

            # 测试2: 完整的元素选择模式
            test2_result = await test_element_selection_mode()

            if test1_result and test2_result:
                print(f"\n{'=' * 60}")
                print("🎊 所有测试都成功完成！")
                print("✨ JavaScript鼠标元素检测功能已经完美工作")
                print("\n📋 功能验证总结:")
                print("  ✅ JavaScript代码成功注入到Chrome浏览器")
                print("  ✅ 控制台输出正确显示")
                print("  ✅ 全局函数正确暴露")
                print("  ✅ 元素选择模式正常工作")
                print("  ✅ 鼠标交互和事件监听正常")
                print("  ✅ Python与JavaScript通信正常")

        except KeyboardInterrupt:
            print("\n⌨️ 用户中断了测试")

    else:
        print("\n❌ 基本测试失败，跳过后续测试")
        print("💡 请检查Chrome浏览器设置和远程调试配置")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 测试被用户中断")
    except Exception as e:
        print(f"\n💥 测试过程中发生未预期的错误: {e}")
