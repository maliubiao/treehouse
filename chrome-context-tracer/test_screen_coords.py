#!/usr/bin/env python3
"""
测试脚本：检测多屏幕坐标系统和浏览器窗口位置
用于诊断和修复多屏幕坐标转换问题
"""

import json
import platform
import re
import subprocess


def get_global_screen_info():
    """获取所有屏幕的全局坐标信息"""
    try:
        # 尝试使用pyautogui获取屏幕信息
        import pyautogui

        screens = []

        # 获取屏幕数量和信息
        try:
            # pyautogui.size() 返回主屏幕大小
            screen_size = pyautogui.size()
            screens.append(
                {
                    "index": 0,
                    "frame": (0, 0, screen_size.width, screen_size.height),
                    "global_frame": (0, 0, screen_size.width, screen_size.height),
                    "is_primary": True,
                }
            )

            # 对于多屏幕，可能需要其他方法
            print(f"主屏幕大小: {screen_size.width}x{screen_size.height}")

        except Exception as e:
            print(f"pyautogui屏幕检测错误: {e}")

        return screens

    except ImportError:
        print("请安装 pyautogui: pip install pyautogui")
        return []
    except Exception as e:
        print(f"获取全局屏幕信息错误: {e}")
        return []


def get_browser_window_info(app_name="Microsoft Edge"):
    """获取浏览器窗口信息"""
    try:
        # 方法1: 直接使用应用程序
        applescript_code1 = f'''
tell application "{app_name}"
    set windowBounds to bounds of front window
    return windowBounds
end tell
'''

        # 方法2: 使用System Events作为回退
        applescript_code2 = f'''
tell application "System Events"
    tell process "{app_name}"
        set frontmost to true
        set windowBounds to bounds of front window
        return windowBounds
    end tell
end tell
'''

        # 首先尝试直接方法
        result = subprocess.run(["osascript", "-e", applescript_code1], capture_output=True, text=True, timeout=10)

        # 如果直接方法失败，尝试System Events方法
        if result.returncode != 0 or not result.stdout.strip():
            result = subprocess.run(["osascript", "-e", applescript_code2], capture_output=True, text=True, timeout=10)

        if result.returncode == 0 and result.stdout.strip():
            # 解析AppleScript输出格式: "左, 上, 右, 下"
            bounds = result.stdout.strip().split(", ")
            if len(bounds) == 4:
                left, top, right, bottom = map(int, bounds)
                width = right - left
                height = bottom - top
                return (left, top, width, height)

    except Exception as e:
        print(f"获取浏览器窗口信息错误: {e}")

    return None


def get_mouse_position():
    """获取当前鼠标位置"""
    try:
        import pyautogui

        return pyautogui.position()
    except ImportError:
        print("请安装 pyautogui: pip install pyautogui")
        return None
    except Exception as e:
        print(f"获取鼠标位置错误: {e}")
        return None


def main():
    print("🔍 多屏幕坐标检测工具")
    print("=" * 50)

    # 检查系统
    system = platform.system()
    print(f"操作系统: {system}")

    if system != "Darwin":
        print("此工具目前仅支持 macOS")
        return

    # 获取屏幕信息
    print("\n📺 屏幕信息:")
    screens = get_global_screen_info()
    if screens:
        for screen in screens:
            left, top, width, height = screen["frame"]
            print(f"  屏幕 {screen['index']}: 位置 ({left}, {top}), 大小 {width}x{height}")
    else:
        print("  无法获取屏幕信息")

    # 获取浏览器窗口信息
    print("\n🌐 浏览器窗口信息:")
    browsers = ["Microsoft Edge", "Google Chrome", "Safari"]
    for browser in browsers:
        window_info = get_browser_window_info(browser)
        if window_info:
            x, y, width, height = window_info
            print(f"  {browser}: 位置 ({x}, {y}), 大小 {width}x{height}")

            # 检查窗口在哪个屏幕上
            if screens:
                for screen in screens:
                    s_left, s_top, s_width, s_height = screen["frame"]
                    s_right = s_left + s_width
                    s_bottom = s_top + s_height

                    if s_left <= x <= s_right and s_top <= y <= s_bottom:
                        print(f"    → 在屏幕 {screen['index']} 上")
                        break
            break
    else:
        print("  未找到浏览器窗口")

    # 获取鼠标位置
    print("\n🖱️  鼠标位置:")
    mouse_pos = get_mouse_position()
    if mouse_pos:
        mouse_x, mouse_y = mouse_pos
        print(f"  当前鼠标位置: ({mouse_x}, {mouse_y})")

        # 检查鼠标在哪个屏幕上
        if screens:
            for screen in screens:
                s_left, s_top, s_width, s_height = screen["frame"]
                s_right = s_left + s_width
                s_bottom = s_top + s_height

                if s_left <= mouse_x <= s_right and s_top <= mouse_y <= s_bottom:
                    print(f"    → 在屏幕 {screen['index']} 上")
                    break
    else:
        print("  无法获取鼠标位置")

    print("\n💡 诊断信息:")
    if screens and len(screens) > 1:
        print("  ✅ 检测到多屏幕配置")

    # 检查浏览器窗口和鼠标是否在同一屏幕
    if window_info and mouse_pos:
        wx, wy, ww, wh = window_info
        mx, my = mouse_pos

        window_on_screen = None
        mouse_on_screen = None

        for screen in screens:
            s_left, s_top, s_width, s_height = screen["frame"]
            s_right = s_left + s_width
            s_bottom = s_top + s_height

            if s_left <= wx <= s_right and s_top <= wy <= s_bottom:
                window_on_screen = screen["index"]

            if s_left <= mx <= s_right and s_top <= my <= s_bottom:
                mouse_on_screen = screen["index"]

        if window_on_screen is not None and mouse_on_screen is not None:
            if window_on_screen == mouse_on_screen:
                print(f"  ✅ 浏览器窗口和鼠标在同一屏幕 ({window_on_screen})")
            else:
                print(f"  ⚠️  浏览器窗口在屏幕 {window_on_screen}，鼠标在屏幕 {mouse_on_screen}")
                print(f"  💡 请将鼠标移动到包含浏览器窗口的屏幕上")


if __name__ == "__main__":
    main()
