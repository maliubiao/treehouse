#!/usr/bin/env python3
"""
测试坐标转换逻辑
"""


def test_coordinate_conversion():
    """测试坐标转换计算"""

    # 从实际运行中获取的数据
    screen_x, screen_y = 2889, 481  # 鼠标位置
    window_x, window_y, window_width, window_height = 2022, 25, 1920, 997  # 窗口信息
    scale_factor = 2.0  # DPI缩放

    print("🔢 坐标转换测试")
    print("=" * 30)
    print(f"鼠标位置: ({screen_x}, {screen_y})")
    print(f"窗口位置: ({window_x}, {window_y}), 大小: {window_width}x{window_height}")
    print(f"DPI缩放: {scale_factor}")

    # 计算浏览器UI偏移
    base_ui_height = 120
    if scale_factor >= 2.0:
        browser_ui_offset_y = int(base_ui_height * 1.2)
    elif scale_factor >= 1.5:
        browser_ui_offset_y = int(base_ui_height * 1.1)
    else:
        browser_ui_offset_y = base_ui_height

    print(f"浏览器UI偏移: {browser_ui_offset_y}px")

    # 计算相对坐标
    relative_x = screen_x - window_x
    relative_y = screen_y - window_y - browser_ui_offset_y

    print(f"相对坐标: ({relative_x}, {relative_y})")

    # 检查坐标是否在有效范围内
    if 0 <= relative_x <= window_width and 0 <= relative_y <= window_height:
        print("✅ 坐标在浏览器窗口内")
        print(f"X范围: 0 - {window_width}, Y范围: 0 - {window_height}")
    else:
        print("❌ 坐标超出浏览器窗口")
        if relative_x < 0:
            print(f"X坐标太小: {relative_x} < 0")
        elif relative_x > window_width:
            print(f"X坐标太大: {relative_x} > {window_width}")

        if relative_y < 0:
            print(f"Y坐标太小: {relative_y} < 0")
        elif relative_y > window_height:
            print(f"Y坐标太大: {relative_y} > {window_height}")


if __name__ == "__main__":
    test_coordinate_conversion()
