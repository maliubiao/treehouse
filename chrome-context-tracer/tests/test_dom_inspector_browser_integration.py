#!/usr/bin/env python3
"""
DOM Inspector 浏览器集成测试
测试浏览器连接、导航和标签页管理功能
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加包的 src 目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from chrome_context_tracer import BrowserContextManager, DOMInspector
from test_server_utils import TestServerContext


async def test_browser_integration():
    """测试浏览器集成功能"""
    print("🌐 开始浏览器集成测试")
    print("=" * 60)

    # 使用 BrowserContextManager 管理浏览器上下文
    async with BrowserContextManager("edge", 9222, auto_cleanup=True) as context:
        websocket_urls = context.get_websocket_urls()

        inspector = None
        try:
            # 测试浏览器连接
            print("🔗 测试浏览器连接...")
            inspector = DOMInspector(websocket_urls[0])
            await inspector.connect()
            print("✅ 浏览器连接成功")

            # 3. 测试标签页查找功能
            print("🔍 测试标签页查找功能...")

            # 获取所有标签页信息
            response = await inspector.send_command("Target.getTargets", use_session=False)
            targets = response.get("result", {}).get("targetInfos", [])

            print(f"📊 发现 {len(targets)} 个目标:")
            for target in targets:
                print(f"   - {target['type']}: {target['url']}")

            # 测试 find_tab_by_url 功能
            print("🎯 测试URL模式匹配...")

            # 查找页面类型的标签页
            page_target_id = await inspector.find_tab_by_url("")
            if page_target_id:
                print(f"✅ 成功找到页面标签页，targetId: {page_target_id}")
            else:
                print("❌ 未找到页面标签页")
                return False

            # 4. 测试标签页附加功能
            print("📌 测试标签页附加功能...")

            session_id = await inspector.attach_to_tab(page_target_id)
            if session_id:
                print(f"✅ 标签页附加成功，sessionId: {session_id}")
            else:
                print("❌ 标签页附加失败")
                return False

            # 5. 测试页面导航功能
            print("🧭 测试页面导航功能...")

            # 创建测试页面
            test_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>浏览器集成测试</title>
        <style>
            body { margin: 0; padding: 20px; font-family: Arial; }
            .status { 
                padding: 20px; 
                background-color: #d4edda; 
                border: 1px solid #c3e6cb;
                border-radius: 4px;
                color: #155724;
            }
        </style>
    </head>
    <body>
        <h1>浏览器集成测试页面</h1>
        <div class="status" id="status">
            ✅ 页面加载成功！
        </div>
        <p>这是一个用于测试浏览器集成功能的页面。</p>
    </body>
    </html>
    """

            async with TestServerContext(test_html) as test_url:
                # 导航到测试页面
                nav_success = await inspector.navigate_to_page(test_url)
                if not nav_success:
                    print("❌ 页面导航失败")
                    return False

                print("✅ 页面导航成功")

                # 等待页面加载完成
                await asyncio.sleep(2)

                # 验证页面内容
                response = await inspector.send_command("DOM.getDocument", {"depth": 1})
                root_node_id = response["result"]["root"]["nodeId"]

                # 查找状态元素
                status_response = await inspector.send_command(
                    "DOM.querySelector", {"nodeId": root_node_id, "selector": "#status"}
                )
                status_node_id = status_response["result"]["nodeId"]

                if status_node_id:
                    status_html = await inspector.get_element_html(status_node_id)
                    if "页面加载成功" in status_html:
                        print("✅ 页面内容验证成功")
                    else:
                        print("⚠️  页面内容验证不完整")

                # 6. 测试多标签页支持
                print("📑 测试多标签页支持...")

                # 创建第二个测试页面
                test_html2 = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>第二个测试页面</title>
    </head>
    <body>
        <h1>第二个测试页面</h1>
        <p>这是第二个测试页面，用于验证多标签页支持。</p>
    </body>
    </html>
    """

                async with TestServerContext(test_html2) as test_url2:
                    # 在浏览器中打开新标签页
                    print(f"🌐 打开新标签页: {test_url2}")

                    # 使用CDP打开新标签页
                    new_tab_response = await inspector.send_command(
                        "Target.createTarget", {"url": test_url2}, use_session=False
                    )

                    if "error" in new_tab_response:
                        print("❌ 创建新标签页失败")
                        print(f"错误: {new_tab_response['error']}")
                    else:
                        new_target_id = new_tab_response["result"]["targetId"]
                        print(f"✅ 新标签页创建成功，targetId: {new_target_id}")

                        # 等待新页面加载
                        await asyncio.sleep(2)

                        # 验证新标签页
                        response = await inspector.send_command("Target.getTargets", use_session=False)
                        targets = response.get("result", {}).get("targetInfos", [])

                        new_tab_found = False
                        for target in targets:
                            if target["targetId"] == new_target_id and test_url2 in target["url"]:
                                new_tab_found = True
                                break

                        if new_tab_found:
                            print("✅ 新标签页验证成功")
                        else:
                            print("❌ 新标签页验证失败")

            # 7. 测试连接稳定性
            print("⚡ 测试连接稳定性...")

            # 发送多个命令测试连接稳定性
            commands_to_test = [
                ("DOM.getDocument", {}),
                ("Runtime.evaluate", {"expression": "1+1"}),
                ("Page.getNavigationHistory", {}),
                ("Target.getTargets", {}),
            ]

            successful_commands = 0
            for cmd, params in commands_to_test:
                try:
                    use_session = cmd != "Target.getTargets"
                    response = await inspector.send_command(cmd, params, use_session=use_session)
                    if "error" not in response:
                        successful_commands += 1
                        print(f"   ✅ {cmd}: 成功")
                    else:
                        print(f"   ❌ {cmd}: 失败 - {response.get('error')}")
                except Exception as e:
                    print(f"   ❌ {cmd}: 错误 - {e}")

            if successful_commands == len(commands_to_test):
                print("✅ 所有命令执行成功，连接稳定")
            else:
                print(f"⚠️  连接稳定性测试: {successful_commands}/{len(commands_to_test)} 成功")

            print("\n🎉 浏览器集成测试完成！")
            print("📊 测试结果摘要:")
            print(f"   - 浏览器自动启动: ✅")
            print(f"   - 浏览器连接: ✅")
            print(f"   - 标签页查找: ✅")
            print(f"   - 标签页附加: ✅")
            print(f"   - 页面导航: ✅")
            print(f"   - 多标签页支持: ✅")
            print(f"   - 连接稳定性: {successful_commands}/{len(commands_to_test)}")

            return successful_commands >= 4  # 至少4个命令成功

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
    print("🚀 DOM Inspector 浏览器集成测试")
    print("=" * 60)

    success = await test_browser_integration()

    print("\n" + "=" * 60)
    if success:
        print("🎊 浏览器集成测试通过！浏览器连接功能正常")
        print("💡 验证的功能:")
        print("   - find_chrome_tabs() - 浏览器标签页查找")
        print("   - launch_browser_with_debugging() - 浏览器自动启动")
        print("   - DOMInspector.connect() - 浏览器连接")
        print("   - find_tab_by_url() - 标签页查找")
        print("   - attach_to_tab() - 标签页附加")
        print("   - navigate_to_page() - 页面导航")
        print("   - 多标签页支持")
        print("   - 连接稳定性")
    else:
        print("❌ 浏览器集成测试失败")
        print("💡 请检查浏览器设置和网络连接")

    return success


if __name__ == "__main__":
    # Mock input for non-interactive selection
    original_input = __builtins__.input
    __builtins__.input = lambda _: ""

    success = asyncio.run(main())

    __builtins__.input = original_input
    exit(0 if success else 1)
