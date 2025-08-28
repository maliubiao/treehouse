#!/usr/bin/env python3
"""
测试AppleScript坐标系统
"""

import subprocess

import pyautogui


def test_applescript_coordinates():
    """测试AppleScript返回的坐标系统"""

    # 获取鼠标全局位置
    mouse_x, mouse_y = pyautogui.position()
    print(f"鼠标全局位置: ({mouse_x}, {mouse_y})")

    # 测试不同的AppleScript方法
    methods = [
        {
            "name": "System Events - process bounds",
            "script": """
tell application "System Events"
    tell process "Microsoft Edge"
        set frontmost to true
        set windowBounds to bounds of front window
        return windowBounds
    end tell
end tell
""",
        },
        {
            "name": "Direct application bounds",
            "script": """
tell application "Microsoft Edge"
    set windowBounds to bounds of front window
    return windowBounds
end tell
""",
        },
        {
            "name": "Window position only",
            "script": """
tell application "Microsoft Edge"
    set windowPosition to position of front window
    return windowPosition
end tell
""",
        },
    ]

    for method in methods:
        try:
            result = subprocess.run(["osascript", "-e", method["script"]], capture_output=True, text=True, timeout=10)

            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                print(f"\n{method['name']}:")
                print(f"  输出: {output}")

                # 解析坐标
                if "," in output:
                    coords = output.split(", ")
                    if len(coords) == 4:  # bounds: left, top, right, bottom
                        left, top, right, bottom = map(int, coords)
                        width = right - left
                        height = bottom - top
                        print(f"  窗口位置: ({left}, {top}), 大小: {width}x{height}")

                        # 检查是否在全局坐标系统内
                        if left >= 1728:  # 主屏幕宽度
                            print(f"  ✅ 窗口在次级屏幕上 (X ≥ 1728)")
                        else:
                            print(f"  ⚠️  窗口坐标可能不是全局坐标")

                    elif len(coords) == 2:  # position: x, y
                        x, y = map(int, coords)
                        print(f"  窗口位置: ({x}, {y})")

            else:
                print(f"\n{method['name']}: 失败 (返回码: {result.returncode})")
                print(f"  错误: {result.stderr}")

        except Exception as e:
            print(f"\n{method['name']}: 错误 - {e}")


if __name__ == "__main__":
    test_applescript_coordinates()
