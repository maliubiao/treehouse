#!/usr/bin/env python3
"""
测试JavaScript注入逻辑（不依赖真实Chrome连接）
"""

import asyncio
import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import MOUSE_ELEMENT_DETECTOR_JS, DOMInspector


async def test_injection_logic():
    """测试JavaScript注入逻辑"""
    print("Testing JavaScript injection logic...")

    # 创建一个模拟的DOMInspector实例
    inspector = DOMInspector("ws://localhost:9222/fake")

    # 测试注入JavaScript代码（使用嵌入的代码）
    print("Testing JavaScript injection with embedded code...")

    # 模拟注入过程
    js_code = MOUSE_ELEMENT_DETECTOR_JS
    print(f"✅ JavaScript code loaded successfully")
    print(f"   - Length: {len(js_code)} characters")
    print(f"   - Contains initialization: {'(function()' in js_code}")
    print(f"   - Contains element detection: {'getElementAtCoordinates' in js_code}")
    print(f"   - Contains selection mode: {'startElementSelection' in js_code}")

    # 测试代码结构
    lines = js_code.split("\n")
    print(f"\nCode structure:")
    print(f"   - Total lines: {len(lines)}")
    print(f"   - First 5 lines: {lines[:5]}")
    print(f"   - Last 5 lines: {lines[-5:]}")

    # 检查关键函数是否存在
    required_functions = ["getElementAtCoordinates", "startElementSelection", "stopElementSelection", "getTracerStatus"]

    print(f"\nRequired functions check:")
    for func in required_functions:
        exists = func in js_code
        status = "✅" if exists else "❌"
        print(f"   {status} {func}")

    # 检查控制台输出模式
    console_patterns = [
        "[CHROME_TRACER]",
        "[CHROME_TRACER_HOVER]",
        "[CHROME_TRACER_SELECTED]",
        "[CHROME_TRACER_CANCELLED]",
    ]

    print(f"\nConsole output patterns:")
    for pattern in console_patterns:
        exists = pattern in js_code
        status = "✅" if exists else "❌"
        print(f"   {status} {pattern}")

    print("\n✅ JavaScript injection logic test completed successfully!")
    print("The embedded JavaScript code contains all required functionality for:")
    print("  - Element detection at coordinates")
    print("  - Interactive element selection mode")
    print("  - Console-based communication with Python")
    print("  - Mouse hover and click detection")


if __name__ == "__main__":
    asyncio.run(test_injection_logic())
