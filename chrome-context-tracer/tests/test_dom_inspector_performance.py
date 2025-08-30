#!/usr/bin/env python3
"""
DOM Inspector 性能和兼容性测试
测试工具的性能表现和不同环境下的兼容性
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# 添加包的 src 目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chrome_context_tracer import BrowserContextManager, DOMInspector
from test_server_utils import TestServerContext


async def test_performance():
    """测试性能表现"""
    print("⚡ 开始性能测试")
    print("=" * 60)

    # 使用 BrowserContextManager 管理浏览器上下文
    async with BrowserContextManager("edge", 9222, auto_cleanup=True) as context:
        websocket_urls = context.get_websocket_urls()

        inspector = None
        try:
            # 连接到浏览器
            print("🔗 连接到浏览器...")
            inspector = DOMInspector(websocket_urls[0])
            await inspector.connect()
            print("✅ 浏览器连接成功")

            # 创建包含大量元素的测试页面
            print("📄 创建性能测试页面...")

            # 生成包含大量元素的HTML
            elements_html = ""
            for i in range(100):  # 创建100个测试元素
                elements_html += f"""
                <div class="perf-element" id="element-{i}">
                    <h3>性能测试元素 {i}</h3>
                    <p>这是第 {i} 个性能测试元素</p>
                    <button onclick="handleClick({i})">点击我 {i}</button>
                    <input type="text" placeholder="输入 {i}">
                </div>
                """

            test_html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>性能测试页面</title>
    <style>
        body {{ margin: 0; padding: 20px; font-family: Arial; }}
        .perf-element {{ 
            padding: 15px; 
            margin: 10px; 
            border: 1px solid #ccc;
            border-radius: 4px;
            background-color: #f8f9fa;
        }}
        .perf-element button {{
            padding: 8px 16px;
            background-color: #007bff;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            margin: 5px 0;
        }}
        .perf-element input {{
            padding: 5px 10px;
            border: 1px solid #ddd;
            border-radius: 3px;
            width: 150px;
        }}
    </style>
</head>
<body>
    <h1>性能测试页面</h1>
    <p>包含大量元素用于性能测试</p>
    
    <div id="performance-container">
        {elements_html}
    </div>
    
    <script>
        function handleClick(index) {{
            console.log('元素', index, '被点击');
        }}
        
        // 性能测试：大量事件监听器
        const elements = document.querySelectorAll('.perf-element');
        elements.forEach((el, index) => {{
            el.addEventListener('mouseover', () => {{
                el.style.backgroundColor = '#e9ecef';
            }});
            el.addEventListener('mouseout', () => {{
                el.style.backgroundColor = '#f8f9fa';
            }});
        }});
    </script>
</body>
</html>
"""

            async with TestServerContext(test_html) as test_url:
                # 性能测试1: 页面导航时间
                print("\n⏱️  性能测试1: 页面导航时间")
                print("-" * 30)

                start_time = time.time()
                nav_success = await inspector.navigate_to_page(test_url)
                nav_time = time.time() - start_time

                if not nav_success:
                    print("❌ 页面导航失败")
                    return False

                print(f"✅ 页面导航成功: {nav_time:.3f} 秒")
                await asyncio.sleep(3)  # 等待页面完全加载

                # 性能测试2: DOM查询性能
                print("\n⏱️  性能测试2: DOM查询性能")
                print("-" * 30)

                # 测试获取整个文档
                start_time = time.time()
                response = await inspector.send_command("DOM.getDocument", {"depth": -1})
                dom_query_time = time.time() - start_time

                if "result" not in response:
                    print("❌ DOM查询失败")
                    return False

                root_node_id = response["result"]["root"]["nodeId"]
                print(f"✅ DOM查询成功: {dom_query_time:.3f} 秒")

                # 性能测试3: 元素查找性能
                print("\n⏱️  性能测试3: 元素查找性能")
                print("-" * 30)

                # 查找特定元素
                start_time = time.time()
                element_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#element-50"}
                )
                element_find_time = time.time() - start_time

                if "result" not in element_response or element_response["result"]["nodeId"] == 0:
                    print("❌ 元素查找失败")
                    return False

                element_node_id = element_response["result"]["nodeId"]
                print(f"✅ 元素查找成功: {element_find_time:.3f} 秒")

                # 性能测试4: 样式获取性能
                print("\n⏱️  性能测试4: 样式获取性能")
                print("-" * 30)

                start_time = time.time()
                styles_data = await inspector.get_element_styles(element_node_id)
                styles_time = time.time() - start_time

                if not styles_data:
                    print("❌ 样式获取失败")
                    return False

                print(f"✅ 样式获取成功: {styles_time:.3f} 秒")

                # 性能测试5: 事件监听器获取性能
                print("\n⏱️  性能测试5: 事件监听器获取性能")
                print("-" * 30)

                start_time = time.time()
                listeners_data = await inspector.get_element_event_listeners(element_node_id)
                listeners_time = time.time() - start_time

                if not listeners_data:
                    print("❌ 事件监听器获取失败")
                    return False

                print(f"✅ 事件监听器获取成功: {listeners_time:.3f} 秒")

                # 性能测试6: 批量操作性能
                print("\n⏱️  性能测试6: 批量操作性能")
                print("-" * 30)

                batch_times = []
                successful_ops = 0

                # 测试多个快速操作
                for i in range(10):  # 执行10个快速操作
                    try:
                        start_time = time.time()
                        response = await inspector.send_command(
                            "Runtime.evaluate",
                            {"expression": f"console.log('Batch operation {i}')", "returnByValue": True},
                        )
                        op_time = time.time() - start_time

                        if "result" in response:
                            batch_times.append(op_time)
                            successful_ops += 1
                    except Exception:
                        pass

                avg_time = sum(batch_times) / len(batch_times) if batch_times else 0
                if successful_ops > 0:
                    print(f"✅ 批量操作性能: {successful_ops}/10 成功, 平均时间: {avg_time:.3f} 秒")
                else:
                    print("❌ 批量操作全部失败")
                    return False

                # 性能基准评估
                print("\n📊 性能基准评估")
                print("-" * 30)

                performance_metrics = {
                    "页面导航": nav_time,
                    "DOM查询": dom_query_time,
                    "元素查找": element_find_time,
                    "样式获取": styles_time,
                    "事件监听器获取": listeners_time,
                    "批量操作平均": avg_time,
                }

                print("性能指标:")
                for metric, time_taken in performance_metrics.items():
                    status = "✅" if time_taken < 1.0 else "⚠️ "
                    print(f"   {status} {metric}: {time_taken:.3f} 秒")

                # 兼容性测试
                print("\n🔧 兼容性测试")
                print("-" * 30)

                # 测试不同的DOM命令
                compatibility_commands = [
                    ("DOM.getDocument", {"depth": 1}, True),
                    ("Runtime.evaluate", {"expression": "1 + 1", "returnByValue": True}, True),
                    ("Page.getNavigationHistory", {}, True),
                    ("Target.getTargets", {}, False),
                ]

                compatible_commands = 0
                for cmd, params, use_session in compatibility_commands:
                    try:
                        response = await inspector.send_command(cmd, params, use_session=use_session)
                        if "error" not in response:
                            compatible_commands += 1
                            print(f"   ✅ {cmd}: 兼容")
                        else:
                            print(f"   ❌ {cmd}: 不兼容 - {response['error']}")
                    except Exception:
                        print(f"   ❌ {cmd}: 执行错误")

                compatibility_score = compatible_commands / len(compatibility_commands)
                print(f"兼容性得分: {compatibility_score:.1%}")

                print("\n🎉 性能和兼容性测试完成！")
                print("📊 测试结果摘要:")
                print(f"   - 页面导航时间: {nav_time:.3f}s")
                print(f"   - DOM查询时间: {dom_query_time:.3f}s")
                print(f"   - 元素查找时间: {element_find_time:.3f}s")
                print(f"   - 样式获取时间: {styles_time:.3f}s")
                print(f"   - 事件监听器时间: {listeners_time:.3f}s")
                print(f"   - 批量操作性能: {successful_ops}/10")
                print(f"   - 兼容性: {compatibility_score:.1%}")

                # 总体性能评估
                slow_operations = [t for t in performance_metrics.values() if t > 2.0]
                if len(slow_operations) == 0 and compatibility_score >= 0.8:
                    print("\n🏆 性能表现: 优秀")
                    return True
                elif len(slow_operations) <= 1 and compatibility_score >= 0.6:
                    print("\n👍 性能表现: 良好")
                    return True
                else:
                    print("\n⚠️  性能表现: 需要优化")
                    return False

        except Exception as e:
            print(f"❌ 测试过程中发生错误: {e}")
            import traceback

            traceback.print_exc()
            return False

        finally:
            if inspector:
                await inspector.close()
                print("🔐 连接已关闭")


async def main():
    """主测试函数"""
    print("🚀 DOM Inspector 性能和兼容性测试")
    print("=" * 60)

    success = await test_performance()

    print("\n" + "=" * 60)
    if success:
        print("🎊 性能测试通过！工具性能表现良好")
        print("💡 验证的性能指标:")
        print("   - 页面加载和导航速度")
        print("   - DOM操作响应时间")
        print("   - 元素信息提取效率")
        print("   - 批量操作处理能力")
        print("   - 浏览器兼容性")
    else:
        print("❌ 性能测试失败")
        print("💡 需要优化性能或兼容性")

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
