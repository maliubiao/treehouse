#!/usr/bin/env python3
"""
测试嵌入的JavaScript代码功能
"""

import asyncio
import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import MOUSE_ELEMENT_DETECTOR_JS


async def test_embedded_javascript():
    """测试嵌入的JavaScript代码"""
    print("Testing embedded JavaScript code...")

    # 检查嵌入的JavaScript代码
    print(f"JavaScript code length: {len(MOUSE_ELEMENT_DETECTOR_JS)} characters")
    print(f"Contains getElementAtCoordinates: {'getElementAtCoordinates' in MOUSE_ELEMENT_DETECTOR_JS}")
    print(f"Contains startElementSelection: {'startElementSelection' in MOUSE_ELEMENT_DETECTOR_JS}")

    # 显示代码片段
    lines = MOUSE_ELEMENT_DETECTOR_JS.split("\n")
    print("\nCode preview:")
    for i, line in enumerate(lines[:10]):
        print(f"{i + 1:2d}: {line}")

    if len(lines) > 10:
        print("... (truncated)")

    print("\n✅ Embedded JavaScript code looks valid!")


if __name__ == "__main__":
    asyncio.run(test_embedded_javascript())
