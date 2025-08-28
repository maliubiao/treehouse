#!/usr/bin/env python3
"""
Enhanced Coordinate Conversion Test
用于精确测试和验证屏幕坐标到浏览器坐标转换的准确性
特别关注high-DPI环境下的坐标转换问题
"""

import asyncio
import os
import sys
import tempfile
import time

import aiohttp

# Import the functions from the local dom_inspector file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dom_inspector import DOMInspector, find_chrome_tabs, launch_browser_with_debugging
from test_server_utils import TestServerContext, cleanup_temp_dir


def get_coordinate_test_html():
    """获取包含精确定位元素的测试页面HTML内容"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>坐标转换测试页面</title>
    <meta charset="utf-8">
    <style>
        body {
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
            background-color: #f0f0f0;
        }
        
        .test-container {
            position: relative;
            width: 100vw;
            height: 100vh;
            background: linear-gradient(45deg, #e0e0e0 25%, transparent 25%), 
                        linear-gradient(-45deg, #e0e0e0 25%, transparent 25%), 
                        linear-gradient(45deg, transparent 75%, #e0e0e0 75%), 
                        linear-gradient(-45deg, transparent 75%, #e0e0e0 75%);
            background-size: 20px 20px;
        }
        
        .coordinate-marker {
            position: absolute;
            width: 40px;
            height: 40px;
            border: 2px solid #007bff;
            background-color: rgba(0, 123, 255, 0.1);
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            font-weight: bold;
            color: #007bff;
            box-sizing: border-box;
        }
        
        .coordinate-marker:hover {
            background-color: rgba(0, 123, 255, 0.3);
            border-color: #0056b3;
        }
        
        #marker-50-50 {
            left: 50px;
            top: 50px;
        }
        
        #marker-100-100 {
            left: 100px;
            top: 100px;
        }
        
        #marker-200-150 {
            left: 200px;
            top: 150px;
        }
        
        #marker-300-200 {
            left: 300px;
            top: 200px;
        }
        
        #marker-400-250 {
            left: 400px;
            top: 250px;
        }
        
        #marker-500-300 {
            left: 500px;
            top: 300px;
        }
        
        #marker-600-350 {
            left: 600px;
            top: 350px;
        }
        
        .info-panel {
            position: fixed;
            top: 10px;
            right: 10px;
            background: white;
            border: 1px solid #ccc;
            padding: 15px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            font-size: 12px;
            max-width: 300px;
        }
        
        .coordinate-info {
            margin: 5px 0;
            padding: 3px;
            background: #f8f9fa;
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <div class="test-container">
        <div class="coordinate-marker" id="marker-50-50" data-x="50" data-y="50">50,50</div>
        <div class="coordinate-marker" id="marker-100-100" data-x="100" data-y="100">100,100</div>
        <div class="coordinate-marker" id="marker-200-150" data-x="200" data-y="150">200,150</div>
        <div class="coordinate-marker" id="marker-300-200" data-x="300" data-y="200">300,200</div>
        <div class="coordinate-marker" id="marker-400-250" data-x="400" data-y="250">400,250</div>
        <div class="coordinate-marker" id="marker-500-300" data-x="500" data-y="300">500,300</div>
        <div class="coordinate-marker" id="marker-600-350" data-x="600" data-y="350">600,350</div>
        
        <div class="info-panel">
            <h3>坐标转换测试</h3>
            <div class="coordinate-info">页面包含7个精确定位的测试元素</div>
            <div class="coordinate-info">每个元素显示其CSS坐标位置</div>
            <div class="coordinate-info">用于验证屏幕坐标到浏览器坐标的转换准确性</div>
            <div class="coordinate-info" style="margin-top: 10px;">
                <strong>测试说明:</strong><br>
                1. 获取元素在页面中的位置<br>
                2. 计算对应的屏幕坐标<br>
                3. 验证反向转换的准确性
            </div>
        </div>
    </div>
    
    <script>
        // 添加点击事件监听器
        document.querySelectorAll('.coordinate-marker').forEach(marker => {
            marker.addEventListener('click', function(e) {
                const rect = this.getBoundingClientRect();
                const x = this.dataset.x;
                const y = this.dataset.y;
                
                console.log(`Element clicked:`, {
                    id: this.id,
                    cssPosition: { x: x, y: y },
                    boundingRect: {
                        left: rect.left,
                        top: rect.top,
                        right: rect.right,
                        bottom: rect.bottom,
                        width: rect.width,
                        height: rect.height
                    },
                    screenPosition: {
                        screenX: e.screenX,
                        screenY: e.screenY,
                        clientX: e.clientX,
                        clientY: e.clientY
                    }
                });
            });
        });
        
        // 页面加载完成后打印所有元素位置信息
        window.addEventListener('load', function() {
            console.log('=== 坐标测试页面加载完成 ===');
            console.log('Page dimensions:', {
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                devicePixelRatio: window.devicePixelRatio
            });
            
            document.querySelectorAll('.coordinate-marker').forEach(marker => {
                const rect = marker.getBoundingClientRect();
                console.log(`Marker ${marker.id}:`, {
                    cssPosition: {
                        x: marker.dataset.x,
                        y: marker.dataset.y
                    },
                    boundingRect: {
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height
                    }
                });
            });
        });
    </script>
</body>
</html>
"""


async def get_element_bounding_rect(inspector: DOMInspector, node_id: int):
    """获取元素的边界框信息"""
    try:
        # 获取元素的边界框
        response = await inspector.send_command("DOM.getBoxModel", {"nodeId": node_id})

        if "result" in response and "model" in response["result"]:
            model = response["result"]["model"]
            # content box: [x1, y1, x2, y2, x3, y3, x4, y4]
            content = model.get("content", [])
            if len(content) >= 4:
                # 获取左上角坐标
                x = content[0]
                y = content[1]
                # 计算宽度和高度
                width = content[2] - content[0]
                height = content[5] - content[1]

                return {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "centerX": x + width / 2,
                    "centerY": y + height / 2,
                }

        return None

    except Exception as e:
        print(f"获取元素边界框失败: {e}")
        return None


async def test_coordinate_conversion_accuracy():
    """测试坐标转换的准确性"""
    print("🎯 开始精确坐标转换测试...")

    try:
        # 使用已启动的浏览器（不自动启动）
        print("🔍 使用已启动的浏览器进行测试...")

        # 获取浏览器标签
        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ 没有可用的浏览器标签")
            return False

        # 连接到浏览器
        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()
        print("✅ 已连接到浏览器")

        # 启动HTTP服务器提供测试页面
        test_html = get_coordinate_test_html()
        async with TestServerContext(test_html) as test_url:
            print(f"📄 创建测试页面: {test_url}")

            # 导航到测试页面
            nav_success = await inspector.navigate_to_page(test_url)
            if not nav_success:
                print("❌ 导航到测试页面失败")
                await inspector.close()
                return False

        # 等待页面完全加载
        await asyncio.sleep(3)
        print("✅ 测试页面加载完成")

        # 获取文档根节点
        response = await inspector.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        # 测试元素列表
        test_markers = [
            ("marker-50-50", 50, 50),
            ("marker-100-100", 100, 100),
            ("marker-200-150", 200, 150),
            ("marker-300-200", 300, 200),
            ("marker-400-250", 400, 250),
            ("marker-500-300", 500, 300),
            ("marker-600-350", 600, 350),
        ]

        print("\n🔍 开始测试每个坐标标记...")

        # 获取浏览器窗口信息
        window_info = inspector.find_chrome_window()
        scale_factor = inspector.get_display_scale_factor()

        print(f"🖥️  浏览器窗口信息: {window_info}")
        print(f"📏 显示缩放因子: {scale_factor}")

        successful_tests = 0
        total_tests = len(test_markers)

        for marker_id, expected_x, expected_y in test_markers:
            print(f"\n📍 测试标记 {marker_id} (期望位置: {expected_x}, {expected_y})")

            try:
                # 查找元素
                response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": f"#{marker_id}"}
                )
                node_id = response["result"]["nodeId"]

                if not node_id:
                    print(f"❌ 未找到元素 {marker_id}")
                    continue

                # 获取元素边界框
                bounding_rect = await get_element_bounding_rect(inspector, node_id)
                if not bounding_rect:
                    print(f"❌ 无法获取元素 {marker_id} 的边界框")
                    continue

                print(f"📦 元素边界框: {bounding_rect}")

                # 计算元素中心点的屏幕坐标
                browser_center_x = int(bounding_rect["centerX"])
                browser_center_y = int(bounding_rect["centerY"])

                print(f"🎯 浏览器内坐标 (中心点): ({browser_center_x}, {browser_center_y})")

                # 验证坐标是否接近期望值 (考虑元素大小的偏移)
                expected_center_x = expected_x + 20  # 元素宽度40px，中心点偏移20px
                expected_center_y = expected_y + 20  # 元素高度40px，中心点偏移20px

                x_diff = abs(browser_center_x - expected_center_x)
                y_diff = abs(browser_center_y - expected_center_y)

                print(f"📏 坐标偏差: X轴 {x_diff}px, Y轴 {y_diff}px")

                # 如果有窗口信息，计算对应的屏幕坐标
                if window_info:
                    window_x, window_y, window_width, window_height = window_info
                    ui_offset = inspector.get_browser_ui_offset(scale_factor)

                    # 计算屏幕坐标
                    screen_x = window_x + browser_center_x
                    screen_y = window_y + ui_offset + browser_center_y

                    print(f"🖥️  计算的屏幕坐标: ({screen_x}, {screen_y})")

                    # 测试反向转换
                    converted_x, converted_y = await inspector.convert_screen_to_browser_coords(screen_x, screen_y)

                    if converted_x is not None and converted_y is not None:
                        conversion_x_diff = abs(converted_x - browser_center_x)
                        conversion_y_diff = abs(converted_y - browser_center_y)

                        print(f"🔄 反向转换结果: ({converted_x}, {converted_y})")
                        print(f"📏 转换偏差: X轴 {conversion_x_diff}px, Y轴 {conversion_y_diff}px")

                        # 判断转换是否成功 (允许小的误差)
                        if conversion_x_diff <= 5 and conversion_y_diff <= 5:
                            print(f"✅ {marker_id} 坐标转换测试通过")
                            successful_tests += 1
                        else:
                            print(f"❌ {marker_id} 坐标转换精度不足")
                    else:
                        print(f"❌ {marker_id} 反向坐标转换失败")
                else:
                    print("⚠️  无法获取窗口信息，跳过屏幕坐标计算")
                    # 只验证元素位置的准确性
                    if x_diff <= 5 and y_diff <= 5:
                        print(f"✅ {marker_id} 元素位置验证通过")
                        successful_tests += 1
                    else:
                        print(f"❌ {marker_id} 元素位置偏差过大")

            except Exception as e:
                print(f"❌ 测试标记 {marker_id} 时发生错误: {e}")

            print(f"\n📊 测试结果: {successful_tests}/{total_tests} 通过")

            await inspector.close()

            return successful_tests >= (total_tests * 0.7)  # 70%通过率认为测试成功

    except Exception as e:
        print(f"❌ 坐标转换测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_dpi_scaling_detection():
    """测试DPI缩放检测的准确性"""
    print("\n📏 测试DPI缩放检测...")

    try:
        # 使用已启动的浏览器（不自动启动）
        print("🔍 使用已启动的浏览器进行测试...")

        websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
        if not websocket_urls:
            print("❌ 没有可用的浏览器标签")
            print("请先手动启动浏览器: open -a 'Microsoft Edge' --args --remote-debugging-port=9222")
            return False

        inspector = DOMInspector(websocket_urls[0])
        await inspector.connect()

        # 测试缩放因子检测
        scale_factor = inspector.get_display_scale_factor()
        print(f"🔍 检测到的缩放因子: {scale_factor}")

        # 验证缩放因子是否合理
        if 0.5 <= scale_factor <= 4.0:
            print("✅ 缩放因子在合理范围内")
            scale_success = True
        else:
            print(f"⚠️  缩放因子似乎异常: {scale_factor}")
            scale_success = False

        # 通过浏览器API获取设备像素比例进行对比
        try:
            # 导航到一个简单页面获取devicePixelRatio
            await inspector.navigate_to_page(
                "data:text/html,<script>console.log('devicePixelRatio:', window.devicePixelRatio)</script>"
            )
            await asyncio.sleep(1)

            # 执行JavaScript获取devicePixelRatio
            response = await inspector.send_command("Runtime.evaluate", {"expression": "window.devicePixelRatio"})

            if "result" in response and "value" in response["result"]:
                browser_dpr = response["result"]["value"]
                print(f"🌐 浏览器报告的devicePixelRatio: {browser_dpr}")

                # 比较两个值
                dpr_diff = abs(scale_factor - browser_dpr)
                print(f"📏 缩放因子差异: {dpr_diff}")

                if dpr_diff <= 0.1:  # 允许小的差异
                    print("✅ 缩放因子检测与浏览器DPR一致")
                else:
                    print("⚠️  缩放因子检测与浏览器DPR存在差异")
                    scale_success = False

        except Exception as e:
            print(f"⚠️  无法获取浏览器devicePixelRatio: {e}")

        await inspector.close()
        return scale_success

    except Exception as e:
        print(f"❌ DPI缩放检测测试失败: {e}")
        return False


async def main():
    """运行增强的坐标转换测试"""
    print("🚀 增强坐标转换测试")
    print("=" * 60)

    # 检查浏览器是否可用
    websocket_urls = await find_chrome_tabs(9222, auto_launch=False)
    if not websocket_urls:
        print("❌ 没有可用的浏览器。请先启动浏览器。")
        print("启动命令: open -a 'Google Chrome' --args --remote-debugging-port=9222")
        return False

    print(f"✅ 找到 {len(websocket_urls)} 个浏览器标签")

    test_results = {}

    # 运行所有测试
    test_results["coordinate_conversion"] = await test_coordinate_conversion_accuracy()
    test_results["dpi_scaling"] = await test_dpi_scaling_detection()

    # 打印总结
    print("\n" + "=" * 60)
    print("📊 增强坐标转换测试总结:")
    print("=" * 60)

    total_tests = len(test_results)
    passed_tests = sum(test_results.values())

    for test_name, result in test_results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} {test_name}")

    print(f"\n📈 结果: {passed_tests}/{total_tests} 测试通过")

    if passed_tests == total_tests:
        print("🎉 所有坐标转换测试通过!")
        return True
    else:
        print("⚠️  部分坐标转换测试失败，需要进一步调试。")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
