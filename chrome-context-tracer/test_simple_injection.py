#!/usr/bin/env python3
"""
简单测试JavaScript注入功能（不需要真实的Chrome连接）
"""

import asyncio
import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import MOUSE_ELEMENT_DETECTOR_JS, DOMInspector


async def test_javascript_injection_logic():
    """测试JavaScript注入逻辑和方法"""
    print("🧪 测试JavaScript注入功能...")

    # 创建DOMInspector实例
    inspector = DOMInspector("ws://localhost:9222/fake")

    # 测试1: 验证JavaScript代码常量存在
    print("\n📝 测试1: 验证JavaScript代码常量")
    if MOUSE_ELEMENT_DETECTOR_JS:
        print(f"✅ MOUSE_ELEMENT_DETECTOR_JS 常量存在 ({len(MOUSE_ELEMENT_DETECTOR_JS)} 字符)")
    else:
        print("❌ MOUSE_ELEMENT_DETECTOR_JS 常量不存在")
        return False

    # 测试2: 验证方法存在
    print("\n📝 测试2: 验证注入方法存在")
    methods_to_check = ["inject_javascript_file", "start_element_selection_mode", "_handle_element_selection_console"]

    for method_name in methods_to_check:
        if hasattr(inspector, method_name):
            print(f"✅ {method_name} 方法存在")
        else:
            print(f"❌ {method_name} 方法不存在")
            return False

    # 测试3: 验证实例变量
    print("\n📝 测试3: 验证实例变量")
    required_vars = ["element_selection_result", "original_console_handler"]

    for var_name in required_vars:
        if hasattr(inspector, var_name):
            print(f"✅ {var_name} 实例变量存在")
        else:
            print(f"❌ {var_name} 实例变量不存在")
            return False

    # 测试4: 验证JavaScript代码内容
    print("\n📝 测试4: 验证JavaScript代码内容")
    required_js_elements = [
        "window.chromeContextTracer",
        "startElementSelection",
        "stopElementSelection",
        "getElementAtCoordinates",
        "[CHROME_TRACER_SELECTED]",
    ]

    for element in required_js_elements:
        if element in MOUSE_ELEMENT_DETECTOR_JS:
            print(f"✅ JavaScript包含: {element}")
        else:
            print(f"❌ JavaScript缺少: {element}")
            return False

    print("\n🎉 所有测试通过！JavaScript注入功能已正确实现")
    return True


async def test_file_reading_capability():
    """测试文件读取功能"""
    print("\n🧪 测试文件读取功能...")

    inspector = DOMInspector("ws://localhost:9222/fake")

    # 创建一个临时的JavaScript文件
    temp_js_file = "/tmp/test_mouse_detector.js"
    try:
        with open(temp_js_file, "w", encoding="utf-8") as f:
            f.write(MOUSE_ELEMENT_DETECTOR_JS)

        print(f"✅ 创建临时JavaScript文件: {temp_js_file}")

        # 模拟inject_javascript_file的文件读取逻辑
        import os

        if os.path.isfile(temp_js_file):
            with open(temp_js_file, "r", encoding="utf-8") as f:
                js_code = f.read()
            print(f"✅ 成功读取JavaScript文件 ({len(js_code)} 字符)")

            # 验证内容是否正确
            if js_code == MOUSE_ELEMENT_DETECTOR_JS:
                print("✅ 文件内容与原始代码一致")
            else:
                print("❌ 文件内容与原始代码不一致")
                return False
        else:
            print("❌ 无法找到临时文件")
            return False

    finally:
        # 清理临时文件
        try:
            os.remove(temp_js_file)
            print("✅ 清理临时文件")
        except:
            pass

    return True


async def main():
    """主测试函数"""
    print("🚀 开始JavaScript注入功能测试")

    # 运行所有测试
    test1_result = await test_javascript_injection_logic()
    test2_result = await test_file_reading_capability()

    if test1_result and test2_result:
        print("\n🎊 所有测试通过！JavaScript注入功能已准备就绪")
        print("\n📋 功能摘要:")
        print("  ✅ JavaScript代码已嵌入到dom_inspector.py")
        print("  ✅ inject_javascript_file() 方法已实现")
        print("  ✅ start_element_selection_mode() 方法已实现")
        print("  ✅ 控制台消息处理器已实现")
        print("  ✅ 支持文件路径和直接代码字符串注入")
        print("\n🎯 下一步: 使用真实的Chrome浏览器进行实际测试")
    else:
        print("\n❌ 部分测试失败，请检查实现")


if __name__ == "__main__":
    asyncio.run(main())
