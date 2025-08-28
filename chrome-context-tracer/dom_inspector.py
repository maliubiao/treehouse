#!/usr/bin/env python3
"""
Chrome DevTools Protocol DOM Inspector
获取元素样式和事件监听器信息，格式与Chrome DevTools完全一致

Dependencies:
- aiohttp: pip install aiohttp
- pyautogui: pip install pyautogui (for mouse position capture)
- pynput: pip install pynput (for hotkey listening)
- pygetwindow: pip install pygetwindow (for Windows window detection)

Optional dependencies for enhanced DPI support:
- pyobjc-framework-Cocoa: pip install pyobjc-framework-Cocoa (for macOS Retina detection)
"""

import argparse
import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp


class DOMInspector:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.message_id = 1
        self.stylesheet_cache: Dict[str, str] = {}
        self.stylesheet_headers: Dict[str, Dict] = {}
        self.script_cache: Dict[str, Dict] = {}  # 脚本源缓存 - 按 script_id 存储源码和元数据
        self.connection_errors = 0  # 连接错误计数器
        self.max_connection_errors = 5  # 最大连接错误次数
        self.calibrated_ui_offset_y: Optional[int] = None

    async def connect(self):
        """连接到Chrome DevTools Protocol WebSocket"""
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.websocket_url)

        # 启用必要的域（处理可能不存在的命令）
        await self.send_command("DOM.enable")
        await self.send_command("CSS.enable")
        await self.send_command("Runtime.enable")
        await self.send_command("Page.enable")

        # 启用Debugger域以支持脚本源信息获取
        try:
            await self.send_command("Debugger.enable")
        except Exception:
            print("警告: Debugger.enable 不可用，脚本源信息功能可能受限")

        # 尝试启用DOMDebugger（某些浏览器版本可能不支持）
        try:
            await self.send_command("DOMDebugger.enable")
        except Exception:
            print("警告: DOMDebugger.enable 不可用，事件监听器功能可能受限")

        # 监听样式表添加事件以收集头部信息
        try:
            await self.collect_stylesheet_headers()
        except Exception:
            print("警告: 无法收集样式表头部信息")

        print(f"Connected to Browser DevTools: {self.websocket_url}")

    async def send_command(self, method: str, params: Dict = None) -> Dict:
        """发送CDP命令并等待响应"""
        if params is None:
            params = {}

        # 检查WebSocket连接状态
        if not self.ws or self.ws.closed:
            raise Exception("WebSocket connection is closed")

        # 检查连接错误次数，如果太多则拒绝请求
        if self.connection_errors >= self.max_connection_errors:
            raise Exception(f"Too many WebSocket errors ({self.connection_errors}), refusing further requests")

        message_id = self.message_id
        self.message_id += 1

        message = {"id": message_id, "method": method, "params": params}

        try:
            await self.ws.send_str(json.dumps(message))
        except Exception as e:
            raise Exception(f"Failed to send WebSocket message: {str(e)}")

        # 等待响应，添加超时机制
        try:

            async def wait_for_response():
                async for msg in self.ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        response = json.loads(msg.data)
                        if response.get("id") == message_id:
                            return response
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        raise Exception(f"WebSocket error: {msg.data}")
                    elif msg.type == aiohttp.WSMsgType.CLOSE:
                        raise Exception("WebSocket connection closed by remote")
                raise Exception("WebSocket connection closed")

            result = await asyncio.wait_for(wait_for_response(), timeout=30.0)
            # 成功时重置错误计数器
            self.connection_errors = 0
            return result
        except asyncio.TimeoutError:
            raise Exception(f"Command {method} timed out after 30 seconds")
        except asyncio.CancelledError:
            self.connection_errors += 1
            raise Exception(f"Command {method} was cancelled")
        except Exception as e:
            self.connection_errors += 1
            if "WebSocket" in str(e):
                raise e
            else:
                raise Exception(f"Command {method} failed: {str(e)}")

    async def find_tab_by_url(self, url_pattern: Optional[str] = None) -> Optional[str]:
        """查找匹配URL模式的标签页，如果未指定URL则返回最上层/当前显示的标签页"""
        response = await self.send_command("Target.getTargets")
        targets = response.get("result", {}).get("targetInfos", [])

        # 如果未指定URL模式，返回第一个页面标签页（通常是最上层/当前显示的）
        if not url_pattern:
            for target in targets:
                if target["type"] == "page":
                    print(f"选择默认标签页: {target['url']}")
                    return target["targetId"]
            return None

        # 查找匹配URL模式的标签页
        for target in targets:
            if target["type"] == "page" and url_pattern in target["url"]:
                return target["targetId"]

        return None

    async def attach_to_tab(self, target_id: str):
        """附加到指定的标签页"""
        response = await self.send_command("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        return response.get("result", {}).get("sessionId")

    async def find_element(self, selector: str) -> Optional[int]:
        """通过CSS选择器查找元素，返回nodeId"""
        # 获取文档根节点
        response = await self.send_command("DOM.getDocument", {"depth": -1})
        root_node_id = response["result"]["root"]["nodeId"]

        # 查询元素
        response = await self.send_command("DOM.querySelector", {"nodeId": root_node_id, "selector": selector})

        return response["result"]["nodeId"]

    async def get_element_styles(self, node_id: int) -> Dict:
        """获取元素的完整样式信息"""
        response = await self.send_command("CSS.getMatchedStylesForNode", {"nodeId": node_id})

        # 检查响应是否包含错误或缺少result字段
        if "error" in response:
            print(f"CSS.getMatchedStylesForNode 错误: {response['error']}")
            return {}

        return response.get("result", {})

    async def get_element_event_listeners(self, node_id: int) -> List[Dict]:
        """获取元素的事件监听器信息"""
        # 首先将DOM节点转换为Runtime对象
        response = await self.send_command("DOM.resolveNode", {"nodeId": node_id})

        remote_object = response["result"]["object"]
        object_id = remote_object["objectId"]

        # 获取事件监听器
        response = await self.send_command(
            "DOMDebugger.getEventListeners",
            {
                "objectId": object_id,
                "depth": -1,  # 包含所有祖先节点的监听器
                "pierce": True,  # 穿透shadow DOM获取所有监听器
            },
        )

        return response["result"]["listeners"]

    async def get_element_html(self, node_id: int) -> str:
        """获取元素的HTML表示（标签和属性，不包括子元素）"""
        response = await self.send_command("DOM.getOuterHTML", {"nodeId": node_id})

        return response["result"]["outerHTML"]

    async def get_node_for_location(self, x: int, y: int) -> Optional[int]:
        """根据坐标获取DOM节点ID"""
        try:
            response = await self.send_command(
                "DOM.getNodeForLocation",
                {"x": x, "y": y, "includeUserAgentShadowDOM": False, "ignorePointerEventsNone": True},
            )

            result = response.get("result", {})
            node_id = result.get("nodeId")
            backend_node_id = result.get("backendNodeId")

            if node_id:
                print(f"Found element at coordinates ({x}, {y}), nodeId: {node_id}")

                # 检查nodeId是否有效（不为0）
                if node_id == 0:
                    print(f"⚠️  警告: 无效的nodeId 0，可能是DevTools协议错误")

                    # 尝试使用backendNodeId获取有效节点
                    if backend_node_id and backend_node_id != 0:
                        print(f"尝试使用backendNodeId {backend_node_id} 获取有效节点")
                        try:
                            push_response = await self.send_command(
                                "DOM.pushNodesByBackendIdsToFrontend", {"backendNodeIds": [backend_node_id]}
                            )

                            push_result = push_response.get("result", {})
                            push_node_ids = push_result.get("nodeIds", [])

                            if push_node_ids and push_node_ids[0] != 0:
                                valid_node_id = push_node_ids[0]
                                print(f"✅ 成功获取有效nodeId: {valid_node_id}")
                                return valid_node_id
                            else:
                                print(f"❌ 无法从backendNodeId {backend_node_id} 获取有效节点")
                        except Exception as push_error:
                            print(f"backendNodeId转换错误: {push_error}")

                    return None

                return node_id
            else:
                print(f"No element found at coordinates ({x}, {y})")

                # 添加调试信息：检查是否有其他信息
                if "error" in response:
                    print(f"Error: {response['error']}")

                # 检查是否有backendNodeId或其他信息
                if backend_node_id:
                    print(f"Found backendNodeId: {backend_node_id}")

                    # 如果backendNodeId是29（已知问题值），提供额外信息
                    if backend_node_id == 29:
                        print(f"⚠️  已知问题: backendNodeId 29 通常表示无效的DevTools协议响应")
                        print(f"💡 这可能是因为页面内容问题或坐标指向了空白区域")

                # 如果坐标在浏览器窗口内但找不到元素，尝试获取文档根节点作为备选
                try:
                    doc_response = await self.send_command("DOM.getDocument", {"depth": 0})
                    if "result" in doc_response and "root" in doc_response["result"]:
                        root_node_id = doc_response["result"]["root"]["nodeId"]
                        print(f"⚠️  警告: 坐标 ({x}, {y}) 处无元素，但文档存在，返回根节点: {root_node_id}")
                        return root_node_id
                except Exception as doc_error:
                    print(f"获取文档根节点失败: {doc_error}")

                return None

        except Exception as e:
            print(f"Error getting node for location ({x}, {y}): {e}")
            return None

    async def format_html(self, html_content: str) -> str:
        """格式化HTML输出，直接返回完整的HTML内容"""
        return html_content

    async def navigate_to_page(self, url: str, wait_for_load: bool = True) -> bool:
        """Navigate to a specific page and optionally wait for it to load"""
        try:
            # First, find the current page target and attach to it
            response = await self.send_command("Target.getTargets")
            targets = response.get("result", {}).get("targetInfos", [])

            # Find the first page target (should be the main browser tab)
            page_target = None
            for target in targets:
                if target["type"] == "page":
                    page_target = target
                    break

            if not page_target:
                print("No page target found for navigation")
                return False

            # Attach to the page target
            session_id = await self.attach_to_tab(page_target["targetId"])
            if not session_id:
                print("Failed to attach to page target")
                return False

            # Enable page domain for navigation
            await self.send_command("Page.enable")

            # Navigate to the URL
            response = await self.send_command("Page.navigate", {"url": url})

            # Check if navigation was successful
            if "error" in response:
                print(f"Navigation failed: {response['error']}")
                return False

            if wait_for_load:
                # Wait for page to load by listening for load event
                print(f"Navigating to: {url}")
                await self.wait_for_page_load()
                print(f"Page loaded successfully: {url}")

            return True

        except Exception as e:
            print(f"Error during navigation to {url}: {e}")
            return False

    async def wait_for_page_load(self, timeout: float = 10.0) -> bool:
        """Wait for page load event with timeout"""
        import asyncio

        try:
            # Use a more robust approach to wait for DOM readiness
            # For file:// URLs, we need to ensure the DOM is fully loaded

            # Wait for DOM content to be loaded
            start_time = time.time()

            while time.time() - start_time < timeout:
                try:
                    # Check if document is available and has content
                    response = await self.send_command("DOM.getDocument", {"depth": 0})
                    if "result" in response and "root" in response["result"]:
                        # Check if we can find basic HTML elements to confirm DOM is ready
                        root_node_id = response["result"]["root"]["nodeId"]

                        # Try to find the html element as a basic check
                        html_response = await self.send_command(
                            "DOM.querySelector", {"nodeId": root_node_id, "selector": "html"}
                        )

                        if html_response.get("result", {}).get("nodeId"):
                            print("DOM is ready")
                            return True

                    await asyncio.sleep(0.5)

                except Exception as check_error:
                    # If there's an error checking DOM, wait and retry
                    await asyncio.sleep(0.5)

            print(f"Warning: Page load timeout after {timeout} seconds")
            return False

        except Exception as e:
            print(f"Error waiting for page load: {e}")
            # Fallback: wait a short time
            await asyncio.sleep(2.0)
            return True

    async def wait_for_pointer_selection(self) -> Optional[int]:
        """等待用户通过鼠标指针选择元素"""
        try:
            import asyncio
            from queue import Empty, Queue

            import pyautogui
            from pynput import keyboard

            print("\n🎯 鼠标选择模式已启用")
            print("请将鼠标移动到目标元素上，然后按 'm' 键选择")
            print("按 'q' 键退出选择模式\n")

            # 使用标准线程安全队列来同步键盘监听线程和主asyncio循环
            key_queue: Queue[str] = Queue()

            def on_key_press(key: Any) -> None:
                """pynput的回调函数，运行在单独的线程中"""
                try:
                    if hasattr(key, "char") and key.char in ["m", "q"]:
                        # 这是线程安全的
                        key_queue.put_nowait(key.char)
                except AttributeError:
                    # 忽略非字符键
                    pass

            # 启动键盘监听器
            listener = keyboard.Listener(on_press=on_key_press)
            listener.start()

            try:
                while True:
                    try:
                        # 以非阻塞方式从队列中获取按键
                        selected_key = key_queue.get_nowait()
                    except Empty:
                        # 队列为空时，短暂休眠以让出CPU，避免100%占用
                        await asyncio.sleep(0.05)
                        continue

                    if selected_key == "m":
                        # 获取当前鼠标位置
                        mouse_x, mouse_y = pyautogui.position()
                        print(f"鼠标位置: ({mouse_x}, {mouse_y})")

                        # 转换坐标并获取节点
                        browser_x, browser_y = await self.convert_screen_to_browser_coords(mouse_x, mouse_y)
                        if browser_x is not None and browser_y is not None:
                            node_id = await self.get_node_for_location(browser_x, browser_y)
                            if node_id:
                                return node_id

                        print("未找到有效元素，请重新选择")

                    elif selected_key == "q":
                        print("退出选择模式")
                        return None
            finally:
                listener.stop()

        except ImportError as e:
            print(f"缺少必要的依赖库: {e}")
            print("请安装: pip install pyautogui pynput")
            return None
        except Exception as e:
            print(f"鼠标选择模式错误: {e}")
            return None

    async def _calibrate_ui_offset(self) -> None:
        """
        通过比较窗口大小和视口大小来计算浏览器的UI偏移量（标签页、地址栏等）。
        """
        print("📏 正在校准浏览器UI偏移量...")
        try:
            # 1. 确保Page域已启用 (在connect中已做)

            # 2. 从操作系统获取窗口几何信息 (返回逻辑像素)
            chrome_window = self.find_chrome_window()
            if not chrome_window:
                print("⚠️  校准失败：未能找到浏览器窗口。")
                return

            _, _, window_width, window_height = chrome_window

            # 3. 从CDP获取视口度量
            metrics_response = await self.send_command("Page.getLayoutMetrics")
            if "error" in metrics_response:
                print(f"⚠️  校准失败: {metrics_response['error'].get('message')}")
                return

            # 使用 visualViewport 获取可见区域的大小 (逻辑像素)
            viewport_height = metrics_response["result"]["visualViewport"]["clientHeight"]

            print(f"校准调试：窗口逻辑高度={window_height}, 视口逻辑高度={viewport_height}")

            # 5. 计算偏移量
            # 窗口高度 (从 find_chrome_window) 和视口高度 (从 CDP) 都应该是逻辑像素 (CSS像素)。
            offset = window_height - viewport_height

            # 偏移量应该是一个正整数
            if offset > 0:
                self.calibrated_ui_offset_y = int(offset)
                print(f"✅ 校准成功。检测到的UI偏移量: {self.calibrated_ui_offset_y}px")
            else:
                print(f"⚠️  校准警告：计算出的偏移量为非正数 ({offset})。将使用备用值。")
        except Exception as e:
            print(f"⚠️  校准因错误失败: {e}。将使用备用值。")

    async def convert_screen_to_browser_coords(
        self, screen_x: int, screen_y: int
    ) -> Tuple[Optional[int], Optional[int]]:
        """将屏幕坐标转换为浏览器坐标（考虑DPI缩放和多屏幕支持）"""
        try:
            import pyautogui

            # 检测浏览器窗口
            chrome_window = self.find_chrome_window()
            if not chrome_window:
                print("警告：未找到浏览器窗口（Chrome/Edge），使用屏幕坐标")
                # 即使没有窗口信息，也要考虑DPI缩放
                scale_factor = self.get_display_scale_factor()
                return int(screen_x / scale_factor), int(screen_y / scale_factor)

            window_x, window_y, window_width, window_height = chrome_window

            # 获取显示器缩放因子
            scale_factor = self.get_display_scale_factor()
            print(f"DPI缩放因子: {scale_factor}")

            # 关键修复：窗口坐标已经是逻辑坐标，不需要再次除以缩放因子
            # 屏幕坐标是物理像素，窗口坐标是逻辑坐标

            # 多屏幕支持：检查鼠标是否在浏览器窗口内（考虑多屏幕坐标空间）
            window_right = window_x + window_width
            window_bottom = window_y + window_height

            # 打印调试信息以帮助诊断多屏幕问题
            print(f"窗口位置: ({window_x}, {window_y}) - ({window_right}, {window_bottom})")
            print(f"鼠标位置: ({screen_x}, {screen_y})")

            # 检查鼠标是否在浏览器窗口内
            if not (window_x <= screen_x <= window_right and window_y <= screen_y <= window_bottom):
                print(f"警告：鼠标位置 ({screen_x}, {screen_y}) 不在浏览器窗口内")
                print(f"      窗口范围: ({window_x}, {window_y}) - ({window_right}, {window_bottom})")

                # 多屏幕处理：尝试检测是否在不同屏幕上
                # 如果鼠标和窗口不在同一屏幕，可能需要特殊的坐标转换
                if self._is_macos():
                    # 在macOS上，尝试获取所有屏幕信息来正确处理多屏幕
                    screen_info = self._get_macos_global_screen_info()
                    if screen_info:
                        print(f"检测到 {len(screen_info)} 个屏幕")
                        for i, screen in enumerate(screen_info):
                            left, top, width, height = screen["frame"]
                            print(f"屏幕 {i}: 位置 ({left}, {top}, {width}, {height})")

                        # 尝试确定浏览器窗口在哪个屏幕上
                        window_screen_index = None
                        for i, screen in enumerate(screen_info):
                            s_left, s_top, s_width, s_height = screen["frame"]
                            s_right = s_left + s_width
                            s_bottom = s_top + s_height

                            # 检查窗口是否在这个屏幕上
                            if s_left <= window_x <= s_right and s_top <= window_y <= s_bottom:
                                window_screen_index = i
                                print(f"浏览器窗口在屏幕 {i} 上")
                                break

                        # 尝试确定鼠标在哪个屏幕上
                        mouse_screen_index = None
                        for i, screen in enumerate(screen_info):
                            s_left, s_top, s_width, s_height = screen["frame"]
                            s_right = s_left + s_width
                            s_bottom = s_top + s_height

                            # 检查鼠标是否在这个屏幕上
                            if s_left <= screen_x <= s_right and s_top <= screen_y <= s_bottom:
                                mouse_screen_index = i
                                print(f"鼠标在屏幕 {i} 上")
                                break

                        # 如果窗口和鼠标在不同屏幕上，提供提示
                        if window_screen_index is not None and mouse_screen_index is not None:
                            if window_screen_index != mouse_screen_index:
                                print(
                                    f"⚠️  警告：浏览器窗口在屏幕 {window_screen_index}，但鼠标在屏幕 {mouse_screen_index}"
                                )
                                print(f"💡 请将鼠标移动到包含浏览器窗口的屏幕上")

                return None, None

            # 转换为相对于浏览器窗口的坐标
            # 考虑浏览器UI的偏移（地址栏、工具栏等）
            if self.calibrated_ui_offset_y is not None:
                browser_ui_offset_y = self.calibrated_ui_offset_y
                print(f"信息：使用校准后的浏览器UI偏移: {browser_ui_offset_y}px")
            else:
                browser_ui_offset_y = self._get_fallback_ui_offset()
                print(f"警告：校准失败，使用备用UI偏移: {browser_ui_offset_y}px")

            # 屏幕坐标 (screen_x, screen_y) 是物理像素.
            # 窗口坐标 (window_x, window_y) 是逻辑像素.
            # 必须先将屏幕坐标转换为逻辑像素再进行计算.
            logical_screen_x = screen_x / scale_factor
            logical_screen_y = screen_y / scale_factor

            # 现在所有单位都是逻辑像素 (CSS像素)
            relative_x = int(logical_screen_x - window_x)
            relative_y = int(logical_screen_y - window_y - browser_ui_offset_y)

            # 确保坐标在视口范围内。如果计算出的坐标为负，
            # 说明点击位置在浏览器UI栏中（视口上方或左方）。
            # 在这种情况下，我们将坐标修正为0，以查询视口边缘的元素。
            if relative_x < 0:
                print(f"信息：相对X坐标 ({relative_x}) 为负，修正为 0。")
                relative_x = 0
            if relative_y < 0:
                print(f"信息：相对Y坐标 ({relative_y}) 为负，修正为 0 (可能点击了浏览器UI栏)。")
                relative_y = 0

            print(f"坐标转换 (物理->逻辑): 屏幕({screen_x}, {screen_y}) -> 浏览器视口({relative_x}, {relative_y})")
            return relative_x, relative_y

        except Exception as e:
            print(f"坐标转换错误: {e}")
            # fallback: 考虑DPI缩放的屏幕坐标
            try:
                scale_factor = self.get_display_scale_factor()
                return int(screen_x / scale_factor), int(screen_y / scale_factor)
            except:
                return screen_x, screen_y

    def find_chrome_window(self) -> Optional[Tuple[int, int, int, int]]:
        """查找浏览器窗口的位置和大小（支持Chrome和Edge）"""
        try:
            import platform

            import pyautogui

            system = platform.system()

            if system == "Darwin":  # macOS
                return self._find_browser_window_macos()
            elif system == "Windows":
                return self._find_browser_window_windows()
            elif system == "Linux":
                return self._find_browser_window_linux()
            else:
                print(f"不支持的操作系统: {system}")
                return None

        except Exception as e:
            print(f"查找浏览器窗口错误: {e}")
            return None

    def _find_browser_window_macos(self) -> Optional[Tuple[int, int, int, int]]:
        """在macOS上查找浏览器窗口（Chrome或Edge）使用Objective-C/Cocoa API"""
        try:
            import os
            import subprocess
            import tempfile

            # 尝试查找浏览器
            browsers = [("Google Chrome", "Chrome"), ("Microsoft Edge", "Edge")]

            for process_name, display_name in browsers:
                # 首先尝试AppleScript方法（不受sandbox限制）
                applescript_result = self._get_window_info_via_applescript(process_name)
                if applescript_result:
                    print(f"✅ {display_name}窗口位置 (AppleScript): {applescript_result}")
                    return applescript_result

                # Objective-C代码使用Cocoa API - 改进版本，查找主浏览器窗口
                objc_code = f'''
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>

int main() {{
    @autoreleasepool {{
        // 获取所有运行的应用
        NSArray *runningApps = [[NSWorkspace sharedWorkspace] runningApplications];
        
        // 查找目标浏览器（精确匹配）
        printf("Looking for browser: %s\\n", "{process_name}");
        for (NSRunningApplication *app in runningApps) {{
            NSString *appName = [app localizedName];
            if ([appName isEqualToString:@"{process_name}"]) {{
                // 找到浏览器应用
                pid_t pid = [app processIdentifier];
                
                // 使用Accessibility API获取应用窗口
                AXUIElementRef appElement = AXUIElementCreateApplication(pid);
                
                if (appElement) {{
                    CFArrayRef windows;
                    AXError result = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute, (CFTypeRef *)&windows);
                    
                    printf("Accessibility API result: %d\\n", result);
                    
                    if (result == kAXErrorSuccess && windows) {{
                        CFIndex windowCount = CFArrayGetCount(windows);
                        printf("Number of windows: %ld\\n", windowCount);
                        
                        // 查找主浏览器窗口（最大、可见、非工具窗口）
                        AXUIElementRef bestWindow = NULL;
                        CGSize bestWindowSize = {{0, 0}};
                        
                        for (CFIndex i = 0; i < windowCount; i++) {{
                            AXUIElementRef window = (AXUIElementRef)CFArrayGetValueAtIndex(windows, i);
                            
                            // 检查窗口是否可见
                            CFTypeRef visibleRef;
                            Boolean isVisible = false;
                            if (AXUIElementCopyAttributeValue(window, CFSTR("AXVisible"), (CFTypeRef *)&visibleRef) == kAXErrorSuccess) {{
                                isVisible = CFBooleanGetValue(visibleRef);
                                CFRelease(visibleRef);
                                printf("Window %ld visibility: %s\\n", i, isVisible ? "YES" : "NO");
                            }}
                            
                            if (!isVisible) {{
                                continue;  // 跳过不可见窗口
                            }}
                            
                            // 检查窗口是否为主窗口
                            CFTypeRef mainWindowRef;
                            Boolean isMainWindow = false;
                            if (AXUIElementCopyAttributeValue(window, CFSTR("AXMain"), (CFTypeRef *)&mainWindowRef) == kAXErrorSuccess) {{
                                isMainWindow = CFBooleanGetValue(mainWindowRef);
                                CFRelease(mainWindowRef);
                                printf("Window %ld is main: %s\\n", i, isMainWindow ? "YES" : "NO");
                            }}
                            
                            // 获取窗口大小
                            CFTypeRef sizeRef;
                            CGSize size = {{0, 0}};
                            if (AXUIElementCopyAttributeValue(window, kAXSizeAttribute, &sizeRef) == kAXErrorSuccess) {{
                                AXValueGetValue(sizeRef, kAXValueCGSizeType, &size);
                                CFRelease(sizeRef);
                                printf("Window %ld size: %.0fx%.0f\\n", i, size.width, size.height);
                            }}
                            
                            // 窗口选择策略：优先选择主窗口，然后选择最大的可见窗口
                            // 排除小窗口（如开发工具、扩展等）
                            if (size.width > 400 && size.height > 300) {{  // 最小合理浏览器窗口大小
                                printf("Window %ld meets size criteria\\n", i);
                                if (isMainWindow) {{
                                    // 找到主窗口，立即返回
                                    bestWindow = window;
                                    bestWindowSize = size;
                                    printf("Selected window %ld as main window\\n", i);
                                    break;
                                }}
                                
                                // 选择最大的窗口
                                if (size.width * size.height > bestWindowSize.width * bestWindowSize.height) {{
                                    bestWindow = window;
                                    bestWindowSize = size;
                                    printf("Selected window %ld as largest window\\n", i);
                                }}
                            }} else {{
                                printf("Window %ld rejected due to size (%.0fx%.0f)\\n", i, size.width, size.height);
                            }}
                        }}
                        
                        if (bestWindow) {{
                            // 获取最佳窗口的位置
                            CFTypeRef positionRef;
                            CGPoint position = {{0, 0}};
                            if (AXUIElementCopyAttributeValue(bestWindow, kAXPositionAttribute, &positionRef) == kAXErrorSuccess) {{
                                AXValueGetValue(positionRef, kAXValueCGPointType, &position);
                                CFRelease(positionRef);
                            }}
                            
                            printf("SUCCESS:%d,%d,%d,%d\\n", 
                                   (int)position.x, (int)position.y, 
                                   (int)bestWindowSize.width, (int)bestWindowSize.height);
                            
                            CFRelease(windows);
                            CFRelease(appElement);
                            return 0;
                        }}
                        
                        CFRelease(windows);
                    }} else {{
                        printf("Accessibility API failed or no windows (error: %d)\\n", result);
                        if (result == kAXErrorAPIDisabled) {{
                            printf("⚠️  Accessibility API disabled. Please enable in System Settings > Privacy & Security > Accessibility\\n");
                        }}
                    }}
                    
                    CFRelease(appElement);
                }}
                
                printf("NO_WINDOWS\\n");
                return 1;
            }}
        }}
        
        printf("NO_PROCESS\\n");
        return 2;
    }}
    return 3;
}}
'''

                # 编译并运行Objective-C代码
                try:
                    # 写入临时文件
                    with tempfile.NamedTemporaryFile(suffix=".m", delete=False) as temp_file:
                        temp_file.write(objc_code.encode("utf-8"))
                        temp_path = temp_file.name

                    # 编译
                    compile_result = subprocess.run(
                        [
                            "clang",
                            "-framework",
                            "Cocoa",
                            "-framework",
                            "ApplicationServices",
                            "-o",
                            "/tmp/browser_detector",
                            temp_path,
                        ],
                        capture_output=True,
                        text=True,
                    )

                    print(f"Debug: Compilation return code: {compile_result.returncode}")
                    if compile_result.stderr:
                        print(f"Debug: Compilation stderr: {compile_result.stderr}")

                    if compile_result.returncode != 0:
                        continue

                    # 运行
                    result = subprocess.run(["/tmp/browser_detector"], capture_output=True, text=True, timeout=10)

                    print(f"Debug: Objective-C return code: {result.returncode}")
                    print(f"Debug: Objective-C stdout: {result.stdout}")
                    print(f"Debug: Objective-C stderr: {result.stderr}")

                    if result.returncode == 0 and result.stdout.strip():
                        output = result.stdout.strip()
                        if output.startswith("SUCCESS:"):
                            coords = output.replace("SUCCESS:", "").split(",")
                            if len(coords) == 4:
                                x, y, width, height = map(int, coords)
                                print(
                                    f"✅ {display_name}窗口位置 (Accessibility API): ({x}, {y}), 大小: {width}x{height}"
                                )
                                return (x, y, width, height)

                except Exception as e:
                    print(f"Objective-C execution error: {e}")
                    continue
                finally:
                    # 清理临时文件
                    try:
                        os.unlink(temp_path)
                        os.unlink("/tmp/browser_detector")
                    except:
                        pass

            print("⚠️  所有窗口检测方法都失败了，请检查Accessibility权限设置")
            print("💡 请在系统设置 > 隐私与安全性 > 辅助功能中授予终端或Python访问权限")
            return None

        except Exception as e:
            print(f"macOS 浏览器窗口检测错误: {e}")
            return None

    def _get_window_info_via_applescript(self, app_name: str) -> Optional[Tuple[int, int, int, int]]:
        """使用AppleScript获取窗口信息（不受sandbox限制）"""
        try:
            import subprocess

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
                result = subprocess.run(
                    ["osascript", "-e", applescript_code2], capture_output=True, text=True, timeout=10
                )

            if result.returncode == 0 and result.stdout.strip():
                # 解析AppleScript输出格式: "左, 上, 右, 下"
                bounds = result.stdout.strip().split(", ")
                if len(bounds) == 4:
                    left, top, right, bottom = map(int, bounds)
                    width = right - left
                    height = bottom - top
                    return (left, top, width, height)

            return None

        except Exception as e:
            print(f"AppleScript窗口检测错误: {e}")
            return None

    def _find_browser_window_windows(self) -> Optional[Tuple[int, int, int, int]]:
        """在Windows上查找浏览器窗口（Chrome或Edge）"""
        try:
            import pygetwindow as gw

            # 按优先级查找浏览器窗口
            browser_searches = [
                # Chrome
                ["Chrome", "Google Chrome"],
                # Edge
                ["Microsoft Edge", "Edge", "Microsoft​ Edge"],
            ]

            for search_terms in browser_searches:
                for term in search_terms:
                    try:
                        windows = gw.getWindowsWithTitle(term)
                        if windows:
                            # 选择第一个可见的窗口
                            window = windows[0]
                            if window.isMinimized:
                                window.restore()

                            browser_name = "Chrome" if "Chrome" in term else "Edge"
                            print(
                                f"{browser_name}窗口位置: ({window.left}, {window.top}), 大小: {window.width}x{window.height}"
                            )
                            return (window.left, window.top, window.width, window.height)
                    except Exception:
                        continue

            return None

        except ImportError:
            print("警告：请安装 pygetwindow: pip install pygetwindow")
            return None
        except Exception as e:
            print(f"Windows 浏览器窗口检测错误: {e}")
            return None

    def _find_browser_window_linux(self) -> Optional[Tuple[int, int, int, int]]:
        """在Linux上查找浏览器窗口（Chrome或Edge）"""
        try:
            import subprocess

            # 使用wmctrl查找浏览器窗口
            result = subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True)

            if result.returncode == 0:
                browser_keywords = [("Google Chrome", "chrome"), ("Microsoft Edge", "edge"), ("Chromium", "chromium")]

                for line in result.stdout.split("\n"):
                    line_lower = line.lower()
                    for display_name, keyword in browser_keywords:
                        if keyword in line_lower or display_name.lower() in line_lower:
                            parts = line.split()
                            if len(parts) >= 6:
                                x, y, width, height = map(int, parts[2:6])
                                browser_name = display_name.split()[0] if " " in display_name else display_name
                                print(f"{browser_name}窗口位置: ({x}, {y}), 大小: {width}x{height}")
                                return (x, y, width, height)

            return None

        except Exception as e:
            print(f"Linux 浏览器窗口检测错误: {e}")
            print("请安装 wmctrl: sudo apt-get install wmctrl")
            return None

    def get_display_scale_factor(self) -> float:
        """获取显示器DPI缩放因子"""
        try:
            import platform

            system = platform.system()

            if system == "Darwin":  # macOS
                return self._get_scale_factor_macos()
            elif system == "Windows":
                return self._get_scale_factor_windows()
            elif system == "Linux":
                return self._get_scale_factor_linux()
            else:
                print(f"未知操作系统，使用默认缩放因子 1.0")
                return 1.0

        except Exception as e:
            print(f"获取DPI缩放因子错误: {e}，使用默认值 1.0")
            return 1.0

    def _get_scale_factor_macos(self) -> float:
        """获取macOS的显示器缩放因子"""
        try:
            import subprocess

            # 使用system_profiler获取显示器信息
            result = subprocess.run(["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True)

            if result.returncode == 0:
                # 查找缩放因子信息
                for line in result.stdout.split("\n"):
                    if "UI Looks like" in line or "Retina" in line:
                        # Retina显示器通常是2x缩放
                        return 2.0

            # 如果没有检测到Retina，尝试使用Cocoa API
            try:
                import Cocoa

                screen = Cocoa.NSScreen.mainScreen()
                if screen:
                    scale = screen.backingScaleFactor()
                    return float(scale)
            except ImportError:
                pass

            return 1.0

        except Exception as e:
            print(f"macOS DPI检测错误: {e}")
            return 2.0 if "retina" in str(e).lower() else 1.0

    def _get_scale_factor_windows(self) -> float:
        """获取Windows的显示器缩放因子"""
        try:
            import ctypes
            from ctypes import wintypes

            # 使用Windows API获取DPI
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()

            # 获取主显示器的DPI
            hdc = user32.GetDC(0)
            dpi_x = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            user32.ReleaseDC(0, hdc)

            # 标准DPI是96，计算缩放因子
            scale_factor = dpi_x / 96.0

            # 常见的缩放因子值：1.0, 1.25, 1.5, 2.0
            if scale_factor <= 1.125:
                return 1.0
            elif scale_factor <= 1.375:
                return 1.25
            elif scale_factor <= 1.75:
                return 1.5
            elif scale_factor <= 2.25:
                return 2.0
            else:
                return scale_factor

        except Exception as e:
            print(f"Windows DPI检测错误: {e}")
            return 1.0

    def _get_scale_factor_linux(self) -> float:
        """获取Linux的显示器缩放因子"""
        try:
            import os
            import subprocess

            # 尝试从环境变量获取
            gdk_scale = os.environ.get("GDK_SCALE")
            if gdk_scale:
                return float(gdk_scale)

            qt_scale = os.environ.get("QT_SCALE_FACTOR")
            if qt_scale:
                return float(qt_scale)

            # 尝试使用xrandr获取显示器信息
            result = subprocess.run(["xrandr", "--query"], capture_output=True, text=True)

            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if " connected " in line and "primary" in line:
                        # 解析分辨率信息
                        import re

                        match = re.search(r"(\d+)x(\d+)", line)
                        if match:
                            width = int(match.group(1))
                            # 如果宽度超过3000，很可能是高DPI显示器
                            if width >= 3000:
                                return 2.0

            # 尝试使用gsettings获取GNOME设置
            try:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "scaling-factor"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    scale = result.stdout.strip()
                    if scale != "uint32 0":
                        return float(scale.split()[-1])
            except:
                pass

            return 1.0

        except Exception as e:
            print(f"Linux DPI检测错误: {e}")
            return 1.0

    def _get_fallback_ui_offset(self) -> int:
        """估算浏览器UI（地址栏、标签栏等）的垂直偏移量（单位：逻辑像素）。"""
        # 这是一个启发式方法，作为校准失败时的备用方案。
        # 现代浏览器的UI高度（逻辑像素）通常在75-100之间（取决于是否有书签栏）。
        # 我们使用一个更现实、更保守的固定值。
        return 90

    def _is_macos(self) -> bool:
        """检查当前系统是否为macOS"""
        import platform

        return platform.system() == "Darwin"

    def _get_macos_screen_info(self) -> List[Dict]:
        """获取macOS屏幕信息（多屏幕支持）"""
        try:
            import json
            import subprocess

            # 使用system_profiler获取屏幕信息
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"], capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                screens = []

                # 解析屏幕信息
                for item in data.get("SPDisplaysDataType", []):
                    for display in item.get("spdisplays_ndrvs", []):
                        screen_info = {
                            "name": display.get("_name", ""),
                            "resolution": display.get("spdisplays_pixels", ""),
                            "scale": 2.0 if "Retina" in str(display) else 1.0,
                        }
                        screens.append(screen_info)

                return screens

        except Exception as e:
            print(f"获取屏幕信息错误: {e}")

        return []

    def _get_macos_global_screen_info(self) -> List[Dict]:
        """获取macOS全局屏幕信息（包括多屏幕坐标）"""
        try:
            import re
            import subprocess

            # 使用AppleScript获取所有屏幕的全局坐标信息
            applescript = """
tell application "System Events"
    set screenFrames to {}
    repeat with i from 1 to (count of desktops)
        set desktopBounds to bounds of desktop i
        copy desktopBounds to end of screenFrames
    end repeat
    return screenFrames
end tell
"""

            result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                # 解析AppleScript输出格式: {{x1, y1, x2, y2}, {x1, y1, x2, y2}, ...}
                output = result.stdout.strip()
                screens = []

                # 使用正则表达式解析屏幕坐标
                pattern = r"\{(\d+), (\d+), (\d+), (\d+)\}"
                matches = re.findall(pattern, output)

                for i, match in enumerate(matches):
                    left, top, right, bottom = map(int, match)
                    width = right - left
                    height = bottom - top

                    screens.append(
                        {"index": i, "frame": (left, top, width, height), "global_frame": (left, top, right, bottom)}
                    )

                return screens

        except Exception as e:
            print(f"获取全局屏幕信息错误: {e}")

        return []

    async def get_script_source_info(self, script_id: str, line_number: int, column_number: int) -> Dict:
        """获取脚本源信息"""
        # 检查缓存

        # 检查缓存 - 只按 script_id 缓存源码，动态构建结果
        if script_id in self.script_cache:
            cached_data = self.script_cache[script_id]
            # 动态构建包含具体行列信息的结果
            return {
                "scriptId": script_id,
                "lineNumber": line_number,
                "columnNumber": column_number,
                "source": cached_data["source"],
                "filename": cached_data.get("filename", f"script_{script_id[-8:]}.js"),
                "url": cached_data.get("url", ""),
                "scriptInfo": cached_data.get("scriptInfo", {}),
            }

        try:
            # 获取脚本源码
            try:
                response = await self.send_command("Debugger.getScriptSource", {"scriptId": script_id})
            except Exception as ws_error:
                # WebSocket错误时返回错误信息，不要让整个流程崩溃
                return {
                    "scriptId": script_id,
                    "lineNumber": line_number,
                    "columnNumber": column_number,
                    "source": None,
                    "error": f"WebSocket error: {str(ws_error)}",
                }
            # 检查响应是否包含错误
            if "error" in response:
                # 错误情况不缓存，直接返回
                return {
                    "scriptId": script_id,
                    "lineNumber": line_number,
                    "columnNumber": column_number,
                    "source": None,
                    "error": response["error"].get("message", "Unknown error"),
                }

            script_source = response["result"]["scriptSource"]

            # 尝试获取脚本元数据（文件名/URL信息）
            # 使用 Debugger.getScripts 获取所有脚本信息，然后匹配 scriptId
            try:
                scripts = response.get("result", {}).get("scripts", [])

                script_info = None
                for script in scripts:
                    if script.get("scriptId") == script_id:
                        script_info = script
                        break

                if script_info:
                    # 提取文件名/URL信息
                    script_url = script_info.get("url", "")
                    if script_url:
                        # 从URL中提取文件名
                        from urllib.parse import urlparse

                        parsed_url = urlparse(script_url)
                        filename = parsed_url.path.split("/")[-1] if parsed_url.path else "script.js"

                        # 如果是内联脚本或data URL，使用其他标识
                        if script_url.startswith("data:") or not script_url.strip():
                            filename = f"inline_script_{script_id[-8:]}"

                        # 缓存脚本源码和元数据
                        self.script_cache[script_id] = {
                            "source": script_source,
                            "filename": filename,
                            "url": script_url,
                            "scriptInfo": script_info,
                        }

                        return {
                            "scriptId": script_id,
                            "lineNumber": line_number,
                            "columnNumber": column_number,
                            "source": script_source,
                            "filename": filename,
                            "url": script_url,
                            "scriptInfo": script_info,
                        }
            except Exception as meta_error:
                # 如果获取脚本元数据失败，继续使用基本信息
                print(f"警告: 无法获取脚本元数据: {meta_error}")

            # 回退方案：使用scriptId作为标识
            filename = f"script_{script_id[-8:]}.js"  # 使用后8位作为简写

            # 缓存脚本源码和基本信息
            self.script_cache[script_id] = {"source": script_source, "filename": filename, "url": "", "scriptInfo": {}}

            return {
                "scriptId": script_id,
                "lineNumber": line_number,
                "columnNumber": column_number,
                "source": script_source,
                "filename": filename,
            }
        except Exception as e:
            # 异常情况不缓存，直接返回
            return {
                "scriptId": script_id,
                "lineNumber": line_number,
                "columnNumber": column_number,
                "source": None,
                "error": str(e),
            }

    async def get_stylesheet_text(self, style_sheet_id: str) -> str:
        """获取样式表的完整文本"""
        if style_sheet_id in self.stylesheet_cache:
            return self.stylesheet_cache[style_sheet_id]

        response = await self.send_command("CSS.getStyleSheetText", {"styleSheetId": style_sheet_id})

        text = response["result"]["text"]
        self.stylesheet_cache[style_sheet_id] = text
        return text

    async def collect_stylesheet_headers(self):
        """收集所有样式表的头部信息"""
        try:
            response = await self.send_command("CSS.getAllStyleSheets")
            headers = response.get("result", {}).get("headers", [])

            for header in headers:
                self.stylesheet_headers[header["styleSheetId"]] = header
        except Exception as e:
            print(f"Warning: Could not collect style sheet headers: {e}")

    async def format_styles(self, styles_data: Dict) -> str:
        """格式化样式输出，模仿DevTools显示格式"""
        output = []

        # 内联样式
        if styles_data.get("inlineStyle"):
            inline_style = styles_data["inlineStyle"]
            if inline_style.get("cssProperties"):
                output.append("element.style {")
                for prop in inline_style["cssProperties"]:
                    if prop.get("value"):
                        output.append(f"    {prop['name']}: {prop['value']};")
                output.append("}")
                output.append("")

        # 匹配的CSS规则
        if styles_data.get("matchedCSSRules"):
            for rule_match in styles_data["matchedCSSRules"]:
                rule = rule_match["rule"]
                selector_text = rule["selectorList"]["text"]

                # 获取样式表源信息
                style_sheet_id = rule.get("styleSheetId")
                source_info = ""

                if style_sheet_id:
                    source_info = self._get_source_info(rule, style_sheet_id)

                # 添加源信息（在规则上方显示）
                if source_info:
                    output.append(source_info)

                output.append(f"{selector_text} {{")

                # 添加样式属性
                if rule["style"].get("cssProperties"):
                    for prop in rule["style"]["cssProperties"]:
                        if prop.get("value"):
                            # 处理重要标志
                            important = " !important" if prop.get("important") else ""

                            # 处理被覆盖的样式
                            disabled = ""
                            if prop.get("disabled"):
                                disabled = " /* disabled */"

                            # 行号信息
                            line_info = ""
                            if prop.get("range"):
                                line_num = prop["range"]["startLine"] + 1
                                line_info = f" /* line: {line_num} */"

                            output.append(f"    {prop['name']}: {prop['value']}{important};{disabled}{line_info}")

                output.append("}")
                output.append("")

        # 处理继承的样式
        if styles_data.get("inherited"):
            output.append("")
            output.append("继承的样式:")

            for inherited_entry in styles_data["inherited"]:
                if inherited_entry.get("inlineStyle") and inherited_entry["inlineStyle"].get("cssProperties"):
                    output.append("从父元素继承的内联样式:")
                    inline_style = inherited_entry["inlineStyle"]
                    for prop in inline_style["cssProperties"]:
                        if prop.get("value"):
                            output.append(f"    {prop['name']}: {prop['value']};")
                    output.append("")

                if inherited_entry.get("matchedCSSRules"):
                    output.append("从父元素继承的CSS规则:")
                    for rule_match in inherited_entry["matchedCSSRules"]:
                        rule = rule_match["rule"]
                        selector_text = rule["selectorList"]["text"]

                        style_sheet_id = rule.get("styleSheetId")
                        source_info = self._get_source_info(rule, style_sheet_id) if style_sheet_id else ""

                        if source_info:
                            output.append(source_info)

                        output.append(f"{selector_text} {{")
                        if rule["style"].get("cssProperties"):
                            for prop in rule["style"]["cssProperties"]:
                                if prop.get("value"):
                                    important = " !important" if prop.get("important") else ""
                                    output.append(f"    {prop['name']}: {prop['value']}{important};")
                        output.append("}")
                        output.append("")

        return "\n".join(output)

    async def format_event_listeners(self, listeners_data: List[Dict]) -> str:
        """格式化事件监听器输出，模仿DevTools显示格式"""
        if not listeners_data:
            return "无事件监听器"

        output = []

        # 按事件类型分组
        events_by_type = {}
        for listener in listeners_data:
            event_type = listener["type"]
            if event_type not in events_by_type:
                events_by_type[event_type] = []
            events_by_type[event_type].append(listener)

        for event_type, listeners in events_by_type.items():
            output.append(f"事件类型: {event_type}")
            output.append("-" * 40)

            for listener in listeners:
                # 基本信息
                use_capture = "是" if listener.get("useCapture", False) else "否"
                passive = "是" if listener.get("passive", False) else "否"
                once = "是" if listener.get("once", False) else "否"

                output.append(f"  捕获阶段: {use_capture}")
                output.append(f"  被动监听: {passive}")
                output.append(f"  仅触发一次: {once}")

                # 源位置信息
                if listener.get("scriptId"):
                    script_id = listener["scriptId"]
                    line_number = listener.get("lineNumber", 0)
                    column_number = listener.get("columnNumber", 0)

                    # 获取脚本源信息以获取文件名/URL
                    script_info = await self.get_script_source_info(script_id, line_number, column_number)

                    output.append(f"  脚本ID: {script_id}")
                    output.append(f"  位置: 行 {line_number + 1}, 列 {column_number + 1}")

                    # 显示脚本来源信息（如果有）
                    if script_info.get("source"):
                        # 显示脚本来源（文件名/URL）
                        if script_info.get("filename"):
                            output.append(f"  脚本来源: {script_info['filename']}")
                            if script_info.get("url") and not script_info["url"].startswith("data:"):
                                # 显示完整URL（如果不是data URL）
                                output.append(f"  脚本URL: {script_info['url']}")

                        # 显示相关代码行（限制压缩脚本的显示长度）
                        source_lines = script_info["source"].split("\n")
                        if 0 <= line_number < len(source_lines):
                            output.append(f"  相关代码:")
                            start_line = max(0, line_number - 2)
                            end_line = min(len(source_lines), line_number + 3)
                            for i in range(start_line, end_line):
                                line_prefix = "→ " if i == line_number else "  "
                                line_content = source_lines[i]
                                # 限制单行显示长度，避免压缩脚本过长
                                if len(line_content) > 200:
                                    line_content = line_content[:200] + "... [截断]"
                                output.append(f"    {line_prefix}{i + 1}: {line_content}")
                        else:
                            # 即使行号超出范围，也显示脚本文件信息
                            output.append(
                                f"  脚本源码已获取 (总行数: {len(source_lines)}, 请求行号: {line_number + 1})"
                            )
                            # 显示前几行作为预览
                            if source_lines:
                                output.append(f"  源码预览:")
                                preview_lines = min(5, len(source_lines))
                                for i in range(preview_lines):
                                    if source_lines[i].strip():  # 跳过空行
                                        output.append(f"    {i + 1}: {source_lines[i]}")
                                if len(source_lines) > preview_lines:
                                    output.append(f"    ... (还有 {len(source_lines) - preview_lines} 行)")
                    elif script_info.get("error"):
                        output.append(f"  脚本源获取错误: {script_info['error']}")

                # 处理函数信息
                if listener.get("handler"):
                    handler = listener["handler"]
                    if handler.get("description"):
                        output.append(f"  函数: {handler['description']}")
                    elif handler.get("className"):
                        output.append(f"  类型: {handler['className']}")

                # 原始处理器信息
                if listener.get("originalHandler"):
                    original_handler = listener["originalHandler"]
                    if original_handler.get("description"):
                        output.append(f"  原始函数: {original_handler['description']}")

                # 绑定的节点信息
                if listener.get("backendNodeId"):
                    output.append(f"  绑定节点ID: {listener['backendNodeId']}")

                output.append("")

        return "\n".join(output)

    def _get_source_info(self, rule: Dict, style_sheet_id: str) -> str:
        """获取样式规则的源文件信息"""
        style = rule.get("style", {})

        # 检查是否有范围信息
        if style.get("range"):
            range_info = style["range"]
            line_num = range_info["startLine"] + 1  # 转换为1-based

            # 尝试获取样式表URL
            if style_sheet_id in self.stylesheet_headers:
                header = self.stylesheet_headers[style_sheet_id]

                # 确定样式表来源类型
                origin = header.get("origin", "")
                source_url = header.get("sourceURL", "")

                if origin == "user-agent":
                    return "用户代理样式表"
                elif origin == "inspector":
                    return "检查器样式表"
                elif origin == "injected":
                    return "注入的样式表"
                elif source_url:
                    # 提取文件名
                    filename = source_url.split("/")[-1] if "/" in source_url else source_url
                    return f"{filename}:{line_num}"
                else:
                    return f"line: {line_num}"

            return f"line: {line_num}"

        # 如果没有范围信息，检查样式表来源
        if style_sheet_id in self.stylesheet_headers:
            header = self.stylesheet_headers[style_sheet_id]
            origin = header.get("origin", "")

            if origin == "user-agent":
                return "用户代理样式表"
            elif origin == "inspector":
                return "检查器样式表"
            elif origin == "injected":
                return "注入的样式表"

        return ""

    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()


async def launch_browser_with_debugging(
    browser_type: str = "chrome", port: int = 9222, user_data_dir: str = None
) -> bool:
    """自动启动浏览器并启用远程调试模式，使用临时配置文件"""
    import atexit
    import os
    import platform
    import shutil
    import subprocess
    import tempfile
    import time

    system = platform.system()

    # 创建临时配置文件目录（如果未提供）
    if user_data_dir is None:
        user_data_dir = tempfile.mkdtemp(prefix="chrome_profile_")

        # 注册退出时清理临时目录
        def cleanup_temp_dir():
            try:
                if os.path.exists(user_data_dir):
                    shutil.rmtree(user_data_dir)
                    print(f"清理临时配置文件目录: {user_data_dir}")
            except Exception as e:
                print(f"清理临时目录失败: {e}")

        atexit.register(cleanup_temp_dir)

    try:
        if system == "Darwin":  # macOS
            if browser_type.lower() == "chrome":
                # 尝试不同的Chrome应用名称
                chrome_names = ["Google Chrome", "Google Chrome", "Chrome"]
                browser_launched = False
                for chrome_name in chrome_names:
                    try:
                        # 使用check_output来验证浏览器是否存在
                        subprocess.check_output(["which", "open"], stderr=subprocess.DEVNULL)
                        # 尝试启动浏览器
                        process = subprocess.Popen(
                            [
                                "open",
                                "-n",
                                "-a",
                                chrome_name,
                                "--args",
                                f"--remote-debugging-port={port}",
                                f"--user-data-dir={user_data_dir}",
                                "--no-first-run",
                                "--no-default-browser-check",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        # 等待open命令完成，然后检查浏览器是否启动
                        process.wait()  # 等待open命令完成
                        if process.returncode == 0:  # open命令成功执行
                            # 等待一点时间让浏览器启动
                            time.sleep(2)
                            # 检查浏览器进程是否存在
                            try:
                                check_result = subprocess.run(
                                    ["pgrep", "-f", f"remote-debugging-port={port}"], capture_output=True, text=True
                                )
                                if check_result.returncode == 0:
                                    browser_launched = True
                                    break
                            except:
                                pass
                        continue
                    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
                        continue

                if not browser_launched:
                    print("无法找到或启动Chrome浏览器，请确保已安装Google Chrome")
                    return False

            elif browser_type.lower() == "edge":
                # 尝试不同的Edge应用名称
                edge_names = ["Microsoft Edge", "Microsoft Edge", "Edge"]
                browser_launched = False
                for edge_name in edge_names:
                    try:
                        subprocess.check_output(["which", "open"], stderr=subprocess.DEVNULL)
                        process = subprocess.Popen(
                            [
                                "open",
                                "-n",
                                "-a",
                                edge_name,
                                "--args",
                                f"--remote-debugging-port={port}",
                                f"--user-data-dir={user_data_dir}",
                                "--no-first-run",
                                "--no-default-browser-check",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        # 等待open命令完成，然后检查浏览器是否启动
                        process.wait()  # 等待open命令完成
                        if process.returncode == 0:  # open命令成功执行
                            # 等待一点时间让浏览器启动
                            time.sleep(2)
                            # 检查浏览器进程是否存在
                            try:
                                check_result = subprocess.run(
                                    ["pgrep", "-f", f"remote-debugging-port={port}"], capture_output=True, text=True
                                )
                                if check_result.returncode == 0:
                                    browser_launched = True
                                    break
                            except:
                                pass
                        continue
                    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
                        continue

                if not browser_launched:
                    print("无法找到或启动Edge浏览器，请确保已安装Microsoft Edge")
                    return False
            else:
                return False
        elif system == "Windows":
            if browser_type.lower() == "chrome":
                subprocess.Popen(
                    [
                        "chrome.exe",
                        f"--remote-debugging-port={port}",
                        f"--user-data-dir={user_data_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ]
                )
            elif browser_type.lower() == "edge":
                subprocess.Popen(
                    [
                        "msedge.exe",
                        f"--remote-debugging-port={port}",
                        f"--user-data-dir={user_data_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ]
                )
            else:
                return False
        elif system == "Linux":
            if browser_type.lower() == "chrome":
                subprocess.Popen(
                    [
                        "google-chrome",
                        f"--remote-debugging-port={port}",
                        f"--user-data-dir={user_data_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ]
                )
            elif browser_type.lower() == "edge":
                subprocess.Popen(
                    [
                        "microsoft-edge",
                        f"--remote-debugging-port={port}",
                        f"--user-data-dir={user_data_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ]
                )
            else:
                return False
        else:
            return False

        print(f"使用临时配置文件启动浏览器: {user_data_dir}")
        # 等待浏览器启动
        time.sleep(5)  # 增加等待时间确保浏览器完全启动
        return True
    except Exception as e:
        print(f"启动浏览器失败: {e}")
        # 清理临时目录
        try:
            if os.path.exists(user_data_dir):
                shutil.rmtree(user_data_dir)
        except:
            pass
        return False


async def find_chrome_tabs(port: int = 9222, auto_launch: bool = True) -> List[str]:
    """查找所有浏览器标签页的WebSocket URL（Chrome/Edge），支持自动启动浏览器"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"http://localhost:{port}/json") as response:
                tabs = await response.json()
                return [tab["webSocketDebuggerUrl"] for tab in tabs if tab.get("webSocketDebuggerUrl")]
        except Exception as e:
            if auto_launch:
                print(f"无法连接到浏览器 DevTools: {e}")
                print("尝试自动启动浏览器...")

                # 尝试启动Chrome
                if await launch_browser_with_debugging("chrome", port):
                    print("Chrome浏览器已启动，等待连接...")
                    # 等待浏览器完全启动
                    import time

                    time.sleep(5)

                    # 重试连接
                    try:
                        async with session.get(f"http://localhost:{port}/json") as response:
                            tabs = await response.json()
                            return [tab["webSocketDebuggerUrl"] for tab in tabs if tab.get("webSocketDebuggerUrl")]
                    except Exception as retry_error:
                        print(f"重试连接失败: {retry_error}")
                else:
                    print("自动启动浏览器失败")

            return []


async def inspect_element_styles(
    url_pattern: str,
    selector: str = None,
    port: int = 9222,
    show_events: bool = False,
    show_html: bool = False,
    from_pointer: bool = False,
):
    """主函数：检查元素的样式和事件监听器"""
    # 查找所有Chrome标签页
    websocket_urls = await find_chrome_tabs(port)

    if not websocket_urls:
        print("未找到浏览器标签页，请确保浏览器以远程调试模式运行:")
        print("Chrome: chrome --remote-debugging-port=9222")
        print("Edge: msedge --remote-debugging-port=9222")
        print("或者指定正确的端口: --port <port_number>")
        return

    # 查找匹配URL的标签页
    matched_tab = None
    inspector = None

    for ws_url in websocket_urls:
        try:
            inspector = DOMInspector(ws_url)
            await inspector.connect()

            # 获取所有目标并查找匹配的标签页
            response = await inspector.send_command("Target.getTargets")
            targets = response.get("result", {}).get("targetInfos", [])

            # 如果URL模式为空，选择第一个页面标签页（最上层/当前显示的）
            if not url_pattern:
                for target in targets:
                    if target["type"] == "page":
                        matched_tab = target
                        print(f"选择默认标签页: {target['url']}")
                        break
            else:
                # 查找匹配URL模式的标签页
                for target in targets:
                    if target["type"] == "page" and url_pattern in target["url"]:
                        matched_tab = target
                        print(f"找到匹配的标签页: {target['url']}")
                        break

            if matched_tab:
                break

            await inspector.close()
            inspector = None

        except Exception as e:
            print(f"连接错误: {e}")
            if inspector:
                await inspector.close()
                inspector = None

    if not matched_tab:
        if not url_pattern:
            print("未找到任何页面标签页")
        else:
            print(f"未找到匹配URL模式 '{url_pattern}' 的标签页")
        print("可用标签页:")
        for ws_url in websocket_urls:
            try:
                temp_inspector = DOMInspector(ws_url)
                await temp_inspector.connect()
                response = await temp_inspector.send_command("Target.getTargets")
                targets = response.get("result", {}).get("targetInfos", [])
                for target in targets:
                    if target["type"] == "page":
                        print(f"  - {target['url']}")
                await temp_inspector.close()
            except:
                pass
        return

    try:
        # 附加到目标标签页
        await inspector.attach_to_tab(matched_tab["targetId"])

        # 为指针模式校准UI偏移量
        if from_pointer:
            await inspector._calibrate_ui_offset()

        # 根据模式选择元素
        node_id = None

        if from_pointer:
            # 鼠标指针选择模式
            node_id = await inspector.wait_for_pointer_selection()
            if not node_id:
                print("未选择元素，退出")
                return
        else:
            # CSS选择器模式
            if not selector:
                print("错误：必须提供 --selector 或使用 --from-pointer")
                return

            node_id = await inspector.find_element(selector)
            if not node_id:
                print(f"未找到选择器 '{selector}' 匹配的元素")
                return

        print(f"找到元素，nodeId: {node_id}")

        # 获取样式信息
        styles_data = await inspector.get_element_styles(node_id)

        # 格式化并输出样式
        formatted_styles = await inspector.format_styles(styles_data)
        print("\n元素样式信息:")
        print("=" * 60)
        print(formatted_styles)

        # 如果需要，获取并显示事件监听器
        if show_events:
            try:
                listeners_data = await inspector.get_element_event_listeners(node_id)
                formatted_listeners = await inspector.format_event_listeners(listeners_data)
                print("\n事件监听器信息:")
                print("=" * 60)
                print(formatted_listeners)
            except Exception as e:
                print(f"\n获取事件监听器失败: {e}")

        # 如果需要，获取并显示元素HTML表示
        if show_html:
            try:
                html_content = await inspector.get_element_html(node_id)
                formatted_html = await inspector.format_html(html_content)
                print("\n元素HTML表示:")
                print("=" * 60)
                print(formatted_html)
            except Exception as e:
                print(f"\n获取元素HTML失败: {e}")

    except Exception as e:
        print(f"错误: {e}")
        import traceback

        traceback.print_exc()
    finally:
        if inspector:
            await inspector.close()


def main():
    parser = argparse.ArgumentParser(description="浏览器元素DOM检查工具 - 样式和事件监听器（支持Chrome/Edge）")
    parser.add_argument("--url", help="要匹配的URL模式（可选，如未指定则选择最上层标签页）")
    parser.add_argument("--selector", help="CSS选择器（如使用 --from-pointer 则可选）")
    parser.add_argument("--port", type=int, default=9222, help="浏览器调试端口（Chrome默认9222，Edge默认9222）")
    parser.add_argument("--events", action="store_true", help="同时显示事件监听器信息")
    parser.add_argument("--html", action="store_true", help="同时显示元素HTML表示（标签和属性）")
    parser.add_argument("--from-pointer", action="store_true", help="使用鼠标指针选择元素（按 m 键选择）")

    args = parser.parse_args()

    # 如果未指定URL，使用空字符串表示默认选择最上层标签页
    url_pattern = args.url if args.url else ""

    asyncio.run(
        inspect_element_styles(url_pattern, args.selector, args.port, args.events, args.html, args.from_pointer)
    )


if __name__ == "__main__":
    main()
