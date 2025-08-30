#!/usr/bin/env python3
"""
DOM Inspector 前台网页自动检测测试
测试自动识别当前在前台的网页和标签页功能
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加包的 src 目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chrome_context_tracer import BrowserContextManager, DOMInspector
from test_server_utils import TestServerContext


async def test_active_tab_detection():
    """测试前台网页自动检测功能"""
    print("🌐 开始前台网页自动检测测试")
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

            # 测试1: 获取所有标签页信息
            print("📊 测试获取所有标签页信息...")

            response = await inspector.send_command("Target.getTargets", use_session=False)
            targets = response.get("result", {}).get("targetInfos", [])

            print(f"发现 {len(targets)} 个目标:")
            for target in targets:
                print(f"   - {target['type']}: {target['url']} (targetId: {target['targetId']})")

            if len(targets) == 0:
                print("❌ 未找到任何标签页")
                return False

            # 测试2: 查找页面类型的标签页
            print("🔍 测试查找页面类型标签页...")

            page_targets = [t for t in targets if t["type"] == "page"]
            print(f"找到 {len(page_targets)} 个页面标签页")

            if len(page_targets) == 0:
                print("❌ 未找到页面类型标签页")
                return False

            # 测试3: 测试 find_tab_by_url 功能
            print("🎯 测试URL模式匹配功能...")

            # 查找空白页或特定模式的标签页
            blank_target_id = await inspector.find_tab_by_url("")
            if blank_target_id:
                print(f"✅ 成功找到标签页，targetId: {blank_target_id}")

                # 验证找到的标签页确实是页面类型
                found_target = next((t for t in targets if t["targetId"] == blank_target_id), None)
                if found_target and found_target["type"] == "page":
                    print("✅ 标签页类型验证正确")
                else:
                    print("❌ 标签页类型验证失败")
                    return False
            else:
                print("❌ 未找到匹配的标签页")
                return False

            # 测试4: 标签页附加功能
            print("📌 测试标签页附加功能...")

            session_id = await inspector.attach_to_tab(blank_target_id)
            if session_id:
                print(f"✅ 标签页附加成功，sessionId: {session_id}")
            else:
                print("❌ 标签页附加失败")
                return False

            # 创建测试页面
            print("📄 创建测试页面...")
            test_html = """
<!DOCTYPE html>
<html>
<head>
    <title>前台网页检测测试</title>
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
    <h1>前台网页检测测试页面</h1>
    <div class="status" id="status">
        ✅ 页面加载成功！
    </div>
    <p>这是一个用于测试前台网页检测功能的页面。</p>
</body>
</html>
"""

            async with TestServerContext(test_html, port=0) as test_url:
                # 导航到测试页面
                print(f"🌐 导航到测试页面: {test_url}")
                nav_success = await inspector.navigate_to_page(test_url)
                if not nav_success:
                    print("❌ 页面导航失败")
                    return False

                print("✅ 页面导航成功")
                await asyncio.sleep(2)

                # 测试5: 再次获取标签页信息，验证新页面
                print("🔄 重新获取标签页信息验证新页面...")

                response = await inspector.send_command("Target.getTargets", use_session=False)
                targets_after_nav = response.get("result", {}).get("targetInfos", [])

                # 查找包含测试URL的标签页
                test_page_targets = [t for t in targets_after_nav if test_url in t["url"]]

                if len(test_page_targets) > 0:
                    print(f"✅ 成功找到测试页面标签页: {test_page_targets[0]['url']}")
                else:
                    print("❌ 未找到测试页面标签页")
                    return False

                # 测试6: 多标签页环境测试
                print("📑 测试多标签页环境...")

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

                async with TestServerContext(test_html2, port=0) as test_url2:
                    # 在浏览器中打开新标签页
                    print(f"🌐 打开新标签页: {test_url2}")

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
                        targets_with_new = response.get("result", {}).get("targetInfos", [])

                        new_tab_found = False
                        for target in targets_with_new:
                            if target["targetId"] == new_target_id and test_url2 in target["url"]:
                                new_tab_found = True
                                print(f"✅ 新标签页验证成功: {target['url']}")
                                break

                        if not new_tab_found:
                            print("❌ 新标签页验证失败")
                            return False

                        # 测试7: 在多标签页环境中查找特定页面
                        print("🔍 在多标签页环境中查找特定页面...")

                        # 查找第一个测试页面
                        found_target_id = await inspector.find_tab_by_url(test_url)
                        if found_target_id:
                            print(f"✅ 在多标签页环境中成功找到目标页面，targetId: {found_target_id}")

                            # 验证找到的是正确的页面
                            found_target = next((t for t in targets_with_new if t["targetId"] == found_target_id), None)
                            if found_target and test_url in found_target["url"]:
                                print("✅ 目标页面验证正确")
                            else:
                                print("❌ 目标页面验证失败")
                                return False
                        else:
                            print("❌ 在多标签页环境中未找到目标页面")
                            return False

                # 测试8: 连接稳定性测试
                print("⚡ 测试连接稳定性...")

                commands_to_test = [
                    "DOM.getDocument",
                    "Runtime.evaluate",
                    "Page.getNavigationHistory",
                    "Target.getTargets",
                ]

                successful_commands = 0
                for cmd in commands_to_test:
                    try:
                        params = {}
                        use_session = True
                        if cmd == "Target.getTargets":
                            use_session = False
                        elif cmd == "Runtime.evaluate":
                            params = {"expression": "1+1"}

                        response = await inspector.send_command(cmd, params, use_session=use_session)
                        if "error" not in response:
                            successful_commands += 1
                            print(f"   ✅ {cmd}: 成功")
                        else:
                            print(f"   ❌ {cmd}: 失败")
                    except Exception as e:
                        print(f"   ❌ {cmd}: 错误 - {e}")

                if successful_commands >= 3:
                    print("✅ 连接稳定性测试通过")
                else:
                    print(f"⚠️  连接稳定性: {successful_commands}/{len(commands_to_test)} 成功")
                    return False

                print("\n🎉 前台网页自动检测测试完成！")
                print("📊 测试结果摘要:")
                print(f"   - 浏览器连接: ✅")
                print(f"   - 标签页发现: ✅ ({len(targets)} 个目标)")
                print(f"   - URL模式匹配: ✅")
                print(f"   - 标签页附加: ✅")
                print(f"   - 页面导航: ✅")
                print(f"   - 多标签页支持: ✅")
                print(f"   - 连接稳定性: {successful_commands}/{len(commands_to_test)}")

                return successful_commands >= 3

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
    print("🚀 DOM Inspector 前台网页自动检测测试")
    print("=" * 60)

    success = await test_active_tab_detection()

    print("\n" + "=" * 60)
    if success:
        print("🎊 前台网页检测测试通过！自动识别功能正常")
        print("💡 验证的功能:")
        print("   - Target.getTargets() - 获取所有标签页")
        print("   - find_tab_by_url() - URL模式匹配")
        print("   - attach_to_tab() - 标签页附加")
        print("   - navigate_to_page() - 页面导航")
        print("   - 多标签页环境支持")
        print("   - 连接稳定性")
    else:
        print("❌ 前台网页检测测试失败")
        print("💡 请检查浏览器设置和网络连接")

    return success


if __name__ == "__main__":
    # Mock input for non-interactive selection
    print(__builtins__)
    original_input = __builtins__.input
    __builtins__.input = lambda _: ""

    success = asyncio.run(main())

    __builtins__.input = original_input
    exit(0 if success else 1)
