#!/usr/bin/env python3
"""
交互式测试简化的屏幕坐标方法
用户可以通过鼠标点击测试元素检测的准确性
"""

import asyncio
import sys

from dom_inspector import DOMInspector


async def interactive_test():
    """交互式测试简化的坐标方法"""

    if len(sys.argv) > 1:
        websocket_url = sys.argv[1]
    else:
        print("请提供websocket URL:")
        print("例如: python interactive_test_simplified.py ws://localhost:9222/devtools/page/...")
        return

    inspector = DOMInspector(websocket_url)

    try:
        await inspector.connect()
        print("✅ 已连接到Chrome DevTools")
        print("\n=== 交互式测试简化坐标方法 ===")
        print("这个测试将使用新的简化方法:")
        print("- 直接使用window.screenX/screenY")
        print("- 无需窗口检测和DPI计算")
        print("- 使用document.elementFromPoint")

        while True:
            print("\n选择测试模式:")
            print("1. 鼠标选择模式 (按 'm' 选择鼠标位置的元素)")
            print("2. 手动输入坐标测试")
            print("3. 退出")

            choice = input("请选择 (1-3): ").strip()

            if choice == "1":
                print("\n进入鼠标选择模式...")
                print("将鼠标移动到想要检测的元素上，然后按 'm' 键")
                print("按 'q' 键退出选择模式")

                # 使用新的简化鼠标选择模式
                node_id = await inspector.mouse_selection_mode()

                if node_id:
                    print(f"✅ 成功选择元素，nodeId: {node_id}")

                    # 获取元素信息
                    try:
                        html = await inspector.get_outer_html(node_id)
                        print(f"元素HTML: {html[:200]}...")

                        # 测试获取元素的屏幕坐标
                        screen_coords = await inspector.get_element_screen_coords(node_id)
                        if screen_coords:
                            screen_x, screen_y = screen_coords
                            print(f"元素屏幕坐标: ({screen_x}, {screen_y})")

                    except Exception as e:
                        print(f"获取元素信息时出错: {e}")
                else:
                    print("未选择任何元素")

            elif choice == "2":
                try:
                    screen_x = int(input("请输入屏幕X坐标: "))
                    screen_y = int(input("请输入屏幕Y坐标: "))

                    print(f"正在检测屏幕坐标 ({screen_x}, {screen_y}) 处的元素...")

                    # 使用新的简化方法
                    node_id = await inspector.get_element_at_screen_coords(screen_x, screen_y)

                    if node_id:
                        print(f"✅ 找到元素，nodeId: {node_id}")

                        # 获取元素信息
                        try:
                            html = await inspector.get_outer_html(node_id)
                            print(f"元素HTML: {html[:200]}...")

                            # 验证元素的屏幕坐标
                            element_coords = await inspector.get_element_screen_coords(node_id)
                            if element_coords:
                                elem_x, elem_y = element_coords
                                print(f"元素实际屏幕坐标: ({elem_x}, {elem_y})")

                                # 计算坐标差异
                                diff_x = abs(screen_x - elem_x)
                                diff_y = abs(screen_y - elem_y)
                                print(f"坐标差异: X={diff_x}, Y={diff_y}")

                                if diff_x <= 50 and diff_y <= 50:
                                    print("✅ 坐标匹配良好!")
                                else:
                                    print("⚠️  坐标差异较大，可能有偏移")

                        except Exception as e:
                            print(f"获取元素信息时出错: {e}")
                    else:
                        print("❌ 在指定坐标处未找到元素")

                except ValueError:
                    print("❌ 请输入有效的数字坐标")
                except Exception as e:
                    print(f"测试时出错: {e}")

            elif choice == "3":
                print("退出测试")
                break
            else:
                print("无效选择，请重试")

    except Exception as e:
        print(f"测试失败: {e}")
    finally:
        await inspector.disconnect()


if __name__ == "__main__":
    asyncio.run(interactive_test())
