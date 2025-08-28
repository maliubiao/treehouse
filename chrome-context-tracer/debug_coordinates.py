#!/usr/bin/env python3
"""
调试脚本：理解多屏幕坐标系统
"""

import platform

import pyautogui


def main():
    print("🔍 坐标系统调试工具")
    print("=" * 50)

    # 获取鼠标位置
    mouse_x, mouse_y = pyautogui.position()
    print(f"鼠标全局位置: ({mouse_x}, {mouse_y})")

    # 获取屏幕大小
    screen_width, screen_height = pyautogui.size()
    print(f"主屏幕大小: {screen_width}x{screen_height}")

    # 检查鼠标是否在主屏幕内
    if 0 <= mouse_x <= screen_width and 0 <= mouse_y <= screen_height:
        print("✅ 鼠标在主屏幕内")
    else:
        print("⚠️  鼠标不在主屏幕内")

        # 尝试估计次级屏幕的位置
        if mouse_x > screen_width:
            print(f"鼠标在主屏幕右侧，X偏移: +{mouse_x - screen_width}")
        elif mouse_x < 0:
            print(f"鼠标在主屏幕左侧，X偏移: {mouse_x}")

        if mouse_y > screen_height:
            print(f"鼠标在主屏幕下方，Y偏移: +{mouse_y - screen_height}")
        elif mouse_y < 0:
            print(f"鼠标在主屏幕上方，Y偏移: {mouse_y}")

    print("\n💡 多屏幕坐标系统说明:")
    print("在macOS上，多屏幕使用全局坐标系统:")
    print("- 主屏幕: (0, 0) 到 (width, height)")
    print("- 右侧屏幕: (width, 0) 到 (width*2, height)")
    print("- 左侧屏幕: (-width, 0) 到 (0, height)")
    print("- 上方屏幕: (0, -height) 到 (width, 0)")
    print("- 下方屏幕: (0, height) 到 (width, height*2)")

    # 基于鼠标位置估计屏幕配置
    if mouse_x > screen_width:
        secondary_width = mouse_x - screen_width
        print(f"\n📊 估计的屏幕配置:")
        print(f"主屏幕: (0, 0) - ({screen_width}, {screen_height})")
        print(f"右侧屏幕: ({screen_width}, 0) - ({screen_width + secondary_width}, {screen_height})")


if __name__ == "__main__":
    main()
