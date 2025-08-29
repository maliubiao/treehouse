#!/usr/bin/env python3
"""
Chrome DevTools Protocol DOM Inspector & Debugger
- Inspect: 获取元素样式和事件监听器信息，格式与Chrome DevTools完全一致
- Trace: 监听JavaScript断点(debugger;)，并打印包含变量值的调用栈信息

Dependencies:
- aiohttp: pip install aiohttp

Element selection is handled via JavaScript injection for cross-platform compatibility.
"""

import argparse
import asyncio
import json
import os
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import aiohttp

# --- JavaScript Loader ---
# Memoize the file content to avoid repeated disk reads
_MOUSE_DETECTOR_JS_CODE: Optional[str] = None


def get_mouse_detector_js() -> str:
    """Reads and caches the mouse detector JavaScript code from its file."""
    global _MOUSE_DETECTOR_JS_CODE
    if _MOUSE_DETECTOR_JS_CODE is None:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            js_path = os.path.join(script_dir, "mouse_element_detector.js")
            with open(js_path, "r", encoding="utf-8") as f:
                _MOUSE_DETECTOR_JS_CODE = f.read()
        except FileNotFoundError:
            print(f"FATAL: JavaScript file not found at {js_path}")
            raise
    return _MOUSE_DETECTOR_JS_CODE


class DOMInspector:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session_id: Optional[str] = None
        self.message_id = 1
        self.stylesheet_cache: Dict[str, str] = {}
        self.stylesheet_headers: Dict[str, Dict] = {}
        self.script_cache: Dict[str, Dict] = {}  # 脚本源缓存 - 按 script_id 存储源码和元数据
        self.connection_errors = 0  # 连接错误计数器
        self.max_connection_errors = 5  # 最大连接错误次数
        self.console_listening = False  # 控制台监听状态
        self.console_message_handler: Optional[Callable] = None  # 控制台消息处理回调
        self.element_selection_result: Optional[Any] = None  # 元素选择结果
        self.original_console_handler: Optional[Callable] = None  # 保存原始的控制台处理器

        self._message_handler_task: Optional[asyncio.Task] = None
        self._pending_responses: Dict[int, asyncio.Future] = {}

    async def connect(self) -> None:
        """连接到Chrome DevTools Protocol WebSocket并启动后台消息监听器"""
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.websocket_url)
        self._message_handler_task = asyncio.create_task(self._message_listener())
        print(f"Connected to Browser DevTools: {self.websocket_url}")

    async def _message_listener(self) -> None:
        """后台任务，持续监听并分发所有WebSocket消息"""
        if not self.ws:
            return
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    response = json.loads(msg.data)

                    # 分发消息：检查是命令响应还是事件
                    if "id" in response:  # 命令响应
                        future = self._pending_responses.pop(response["id"], None)
                        if future and not future.done():
                            if "error" in response:
                                error_info = response["error"]
                                future.set_exception(
                                    Exception(f"Command failed: {error_info.get('message', 'Unknown error')}")
                                )
                            else:
                                future.set_result(response)
                    elif "method" in response:  # 事件
                        await self._handle_event(response)

                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    break
        except asyncio.CancelledError:
            pass  # 任务被取消，正常关闭
        except Exception as e:
            print(f"WebSocket listener error: {e}")
            traceback.print_exc()
        finally:
            # 清理所有待处理的响应，以防监听器异常退出
            for future in self._pending_responses.values():
                if not future.done():
                    future.set_exception(Exception("WebSocket connection closed unexpectedly."))

    async def _handle_event(self, event: Dict[str, Any]) -> None:
        """处理从浏览器接收到的事件"""
        method = event.get("method")
        params = event.get("params", {})

        if method == "Runtime.consoleAPICalled":
            if self.console_listening and self.console_message_handler:
                await self.console_message_handler({"type": params.get("type", ""), "message": params, "raw": event})
            elif self.console_listening:
                await self._handle_console_api_called(params)
        elif method == "Console.messageAdded":
            if self.console_listening and self.console_message_handler:
                await self.console_message_handler(
                    {"type": params.get("message", {}).get("level", ""), "message": params, "raw": event}
                )
            elif self.console_listening:
                await self._handle_console_message_added(params)
        elif method == "CSS.styleSheetAdded":
            await self._handle_style_sheet_added(params)
        elif method == "Debugger.scriptParsed":
            await self._handle_script_parsed(params)
        elif method == "Debugger.paused":
            await self._handle_debugger_paused(params)

    async def _handle_debugger_paused(self, params: Dict[str, Any]) -> None:
        """处理 Debugger.paused 事件，打印调用栈和变量信息"""
        print("\n" + "=" * 20 + " Paused on debugger statement " + "=" * 20)
        reason = params.get("reason")
        call_frames = params.get("callFrames", [])
        print(f"Reason: {reason}\n")

        # 打印简化的堆栈轨迹
        print("--- Stack Trace ---")
        for i, frame in enumerate(call_frames):
            func_name = frame.get("functionName") or "(anonymous)"
            location = frame.get("location", {})
            script_id = location.get("scriptId")
            line = location.get("lineNumber", 0) + 1
            col = location.get("columnNumber", 0) + 1

            script_info = self.script_cache.get(script_id, {})
            filename = script_info.get("filename", f"scriptId:{script_id}")

            print(f"  [{i}] {func_name} at {filename}:{line}:{col}")
        print("")

        # 详细处理每个调用帧
        for i, frame in enumerate(call_frames):
            await self._process_and_print_call_frame(frame, i)

        print("=" * 66)
        print("Resuming execution...")

        # 处理完后恢复执行
        try:
            await self.send_command("Debugger.resume")
        except Exception as e:
            print(f"Error resuming debugger: {e}")

    async def _get_variables_from_scope_chain(self, scope_chain: List[Dict[str, Any]]) -> Dict[str, str]:
        """从作用域链中提取局部和闭包变量"""
        variables: Dict[str, str] = {}
        for scope in scope_chain:
            # 我们只关心 local 和 closure 作用域，以避免全局变量污染
            scope_type = scope.get("type")
            if scope_type in ["local", "closure"]:
                scope_object = scope.get("object", {})
                object_id = scope_object.get("objectId")
                if object_id:
                    try:
                        props_response = await self.send_command(
                            "Runtime.getProperties", {"objectId": object_id, "ownProperties": True}
                        )
                        for prop in props_response.get("result", {}).get("result", []):
                            name = prop.get("name")
                            value_obj = prop.get("value", {})
                            # 使用 description 字段来获得一个可读的表示
                            description = value_obj.get("description", str(value_obj.get("value", "N/A")))
                            if name:
                                variables[name] = description
                    except Exception as e:
                        print(f"Warning: Could not get variables for scope {scope_type}: {e}")
        return variables

    async def _process_and_print_call_frame(self, frame: Dict[str, Any], frame_index: int) -> None:
        """处理单个调用帧：获取源码、变量并格式化输出"""
        func_name = frame.get("functionName") or "(anonymous)"
        location = frame.get("location", {})
        script_id = location.get("scriptId")
        line_number = location.get("lineNumber", 0)
        column_number = location.get("columnNumber", 0)

        script_info = self.script_cache.get(script_id, {})
        filename = script_info.get("filename", f"scriptId:{script_id}")

        print(f"--- Frame {frame_index}: {func_name} ({filename}:{line_number + 1}:{column_number + 1}) ---")
        print("Source Context:")

        # 获取变量
        variables = await self._get_variables_from_scope_chain(frame.get("scopeChain", []))
        variables_str = ", ".join(f"{name}: {value}" for name, value in variables.items())

        # 获取并打印源码
        source_info = await self.get_script_source_info(script_id, line_number, column_number)
        source_code = source_info.get("source")

        if source_code:
            lines = source_code.split("\n")
            start = max(0, line_number - 2)
            end = min(len(lines), line_number + 3)

            for i in range(start, end):
                prefix = "->" if i == line_number else "  "
                line_content = lines[i]

                # 在断点行附加变量信息
                if i == line_number:
                    # 找到一个好的位置插入注释，或者直接附加
                    if len(line_content.strip()) > 0:
                        line_content += f"    // {variables_str}"
                    else:
                        line_content += f"// {variables_str}"

                print(f" {prefix} {i + 1: >4} | {line_content}")
        else:
            print("  [Source code not available]")
        print("")

    async def _handle_style_sheet_added(self, params: Dict[str, Any]) -> None:
        """处理 CSS.styleSheetAdded 事件，缓存样式表头部信息"""
        header = params.get("header")
        if header and "styleSheetId" in header:
            self.stylesheet_headers[header["styleSheetId"]] = header

    async def _handle_script_parsed(self, params: Dict[str, Any]) -> None:
        """处理 Debugger.scriptParsed 事件，缓存脚本元数据"""
        script_id = params.get("scriptId")
        if not script_id:
            return

        url = params.get("url", "")
        # 从URL中提取文件名，如果URL为空则生成一个
        filename = url.split("/")[-1].split("?")[0] if url else f"script_{script_id[-8:]}.js"
        if not filename:
            filename = f"script_{script_id[-8:]}.js"

        # 确保缓存中有该script_id的条目
        self.script_cache.setdefault(script_id, {})

        # 更新元数据，但不覆盖已有的源码
        self.script_cache[script_id].update(
            {
                "url": url,
                "filename": filename,
                "scriptInfo": params,
            }
        )

    async def enable_domains(self) -> None:
        """为当前会话启用所有必需的域"""
        if not self.session_id:
            print("警告: 无法在没有会话ID的情况下启用域")
            return

        # 启用必要的域
        await self.send_command("DOM.enable")
        await self.send_command("CSS.enable")
        await self.send_command("Runtime.enable")
        await self.send_command("Page.enable")

        # 启用控制台监听
        await self.start_console_listening()

        # 启用Debugger域，这是使用DOMDebugger（事件监听器）和获取脚本源的前提
        try:
            await self.send_command("Debugger.enable")
        except Exception:
            print("警告: Debugger.enable 不可用，脚本源和事件监听器功能可能受限")

        print("✅ Domains enabled for the new session.")
        await asyncio.sleep(1)

    async def send_command(
        self, method: str, params: Optional[Dict[str, Any]] = None, use_session: bool = True
    ) -> Dict[str, Any]:
        """发送CDP命令并等待响应"""
        if params is None:
            params = {}

        if not self.ws or self.ws.closed:
            raise Exception("WebSocket connection is closed")

        if self.connection_errors >= self.max_connection_errors:
            raise Exception(f"Too many WebSocket errors ({self.connection_errors}), refusing further requests")

        message_id = self.message_id
        self.message_id += 1

        message: Dict[str, Any] = {"id": message_id, "method": method, "params": params}
        if self.session_id and use_session:
            message["sessionId"] = self.session_id

        future = asyncio.get_running_loop().create_future()
        self._pending_responses[message_id] = future

        try:
            await self.ws.send_str(json.dumps(message))
        except Exception as e:
            self._pending_responses.pop(message_id, None)
            raise Exception(f"Failed to send WebSocket message: {str(e)}")

        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            self.connection_errors = 0
            return result
        except asyncio.TimeoutError:
            self.connection_errors += 1
            self._pending_responses.pop(message_id, None)
            raise Exception(f"Command {method} timed out after 30 seconds")
        except Exception as e:
            self.connection_errors += 1
            self._pending_responses.pop(message_id, None)
            raise e

    def _is_valid_web_page(self, url: str) -> bool:
        """检查URL是否是有效的网页，过滤掉内部页面和DevTools页面"""
        # 过滤掉的URL类型
        invalid_prefixes = [
            "devtools://",
            "chrome://",
            "edge://",
            "chrome-extension://",
            "about:",
            "moz-extension://",
            "safari-extension://",
        ]

        url_lower = url.lower()
        for prefix in invalid_prefixes:
            if url_lower.startswith(prefix):
                return False

        # 优先选择HTTP(S)页面
        return url_lower.startswith(("http://", "https://", "file://", "ftp://"))

    def _find_default_tab(self, valid_targets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """通过启发式方法找到最可能的活动标签页作为默认选项。"""
        if not valid_targets:
            return None

        # 启发式方法1：一个已经被开发者工具附加的标签页是强烈的候选者。
        attached_targets = [t for t in valid_targets if t.get("attached")]
        if len(attached_targets) == 1:
            return attached_targets[0]

        # 启发式方法2：列表中的最后一个标签页通常是最近打开或聚焦的。
        # 这不是一个保证，但是一个合理的回退策略。
        return valid_targets[-1]

    async def find_tab_by_url(self, url_pattern: Optional[str] = None) -> Optional[str]:
        """查找匹配URL模式的标签页，如果未指定URL则返回最上层/当前显示的标签页"""
        # 添加获取目标前的等待时间
        await asyncio.sleep(0.5)
        response = await self.send_command("Target.getTargets", use_session=False)
        targets = response.get("result", {}).get("targetInfos", [])

        # 过滤出有效的网页标签页
        valid_targets = []
        for target in targets:
            if target["type"] == "page" and self._is_valid_web_page(target["url"]):
                valid_targets.append(target)

        # 如果未指定URL模式，让用户选择标签页
        if not url_pattern:
            print(f"🔍 发现 {len(valid_targets)} 个有效的网页标签页")

            if not valid_targets:
                print("❌ 未找到有效的网页标签页")
                print("💡 请确保浏览器中打开了网页，而不仅仅是开发者工具")
                return None

            if len(valid_targets) == 1:
                # 只有一个标签页，直接选择
                selected_target = valid_targets[0]
                print(f"✅ 自动选择唯一标签页: {selected_target['url']}")
                return selected_target["targetId"]

            # 多个标签页，提供带默认值的选择
            default_target = self._find_default_tab(valid_targets)
            default_index = -1

            print("\n请选择要检查的标签页:")
            for i, target in enumerate(valid_targets, 1):
                if default_target and target["targetId"] == default_target["targetId"]:
                    default_index = i
                    print(f"  * {i}. {target['url']} (默认)")
                else:
                    print(f"  {i}. {target['url']}")

            while True:
                try:
                    prompt = f"\n请选择标签页 (1-{len(valid_targets)}) [回车使用默认值: {default_index}]: "
                    choice_str = input(prompt).strip()
                    if not choice_str:
                        choice_num = default_index
                    else:
                        choice_num = int(choice_str)

                    if 1 <= choice_num <= len(valid_targets):
                        selected_target = valid_targets[choice_num - 1]
                        print(f"✅ 选择标签页: {selected_target['url']}")
                        return selected_target["targetId"]
                    else:
                        print(f"请输入 1 到 {len(valid_targets)} 之间的数字")
                except ValueError:
                    print("无效输入，请输入一个数字。")
                except (KeyboardInterrupt, EOFError):
                    print("\n已取消选择")
                    return None

        # 查找匹配URL模式的标签页
        for target in valid_targets:
            if url_pattern in target["url"]:
                print(f"✅ 找到匹配的标签页: {target['url']}")
                return target["targetId"]

        print(f"❌ 未找到匹配 '{url_pattern}' 的标签页")
        if valid_targets:
            print("💡 可用的标签页:")
            for i, target in enumerate(valid_targets, 1):
                print(f"  {i}. {target['url']}")

        return None

    async def attach_to_tab(self, target_id: str) -> Optional[str]:
        """附加到指定的标签页"""
        response = await self.send_command(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}, use_session=False
        )
        session_id = response.get("result", {}).get("sessionId")
        if session_id:
            self.session_id = session_id
            await self.enable_domains()
        return session_id

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

    def _format_node_description(self, node_data: Dict[str, Any], is_target: bool = False) -> str:
        """格式化DOM节点的可读描述"""
        if is_target:
            return "Selected Element"
        if not node_data:
            return "unknown ancestor"

        node_name = node_data.get("localName", node_data.get("nodeName", "unknown")).lower()
        if node_name.startswith("#"):  # #document, #text, etc.
            return node_name

        attributes = node_data.get("attributes", [])
        attrs_dict = dict(zip(attributes[::2], attributes[1::2]))

        desc = node_name
        if "id" in attrs_dict and attrs_dict["id"]:
            desc += f"#{attrs_dict['id']}"
        if "class" in attrs_dict and attrs_dict["class"]:
            class_list = attrs_dict["class"].strip().split()
            if class_list:
                desc += "." + ".".join(class_list)

        return desc

    async def get_element_event_listeners(self, node_id: int) -> List[Dict[str, Any]]:
        """获取元素的事件监听器信息, 包括其所有祖先节点以及window对象"""
        all_listeners: List[Dict[str, Any]] = []
        object_ids_to_release: List[str] = []

        try:
            # Phase 1: 使用JS向上遍历祖先节点并收集监听器
            resolve_response = await self.send_command("DOM.resolveNode", {"nodeId": node_id})
            current_object_id = resolve_response.get("result", {}).get("object", {}).get("objectId")
            is_target_node = True

            while current_object_id:
                object_ids_to_release.append(current_object_id)

                # 1.1: 获取当前节点的事件监听器
                try:
                    listeners_response = await self.send_command(
                        "DOMDebugger.getEventListeners", {"objectId": current_object_id}
                    )
                    listeners = listeners_response.get("result", {}).get("listeners", [])

                    if listeners:
                        # 如果有监听器，才需要获取节点描述
                        node_response = await self.send_command("DOM.requestNode", {"objectId": current_object_id})
                        current_node_id = node_response.get("result", {}).get("nodeId")
                        if current_node_id:
                            describe_response = await self.send_command("DOM.describeNode", {"nodeId": current_node_id})
                            node_data = describe_response.get("result", {}).get("node", {})
                            source_description = self._format_node_description(node_data, is_target_node)

                            for listener in listeners:
                                listener["sourceNodeDescription"] = source_description
                            all_listeners.extend(listeners)
                except Exception:
                    # 对于某些节点（如非元素节点），获取监听器可能会失败，这没关系
                    pass

                is_target_node = False

                # 1.2: 使用JS获取父元素的objectId
                get_parent_js = "function() { return this.parentElement; }"
                parent_response = await self.send_command(
                    "Runtime.callFunctionOn",
                    {
                        "objectId": current_object_id,
                        "functionDeclaration": get_parent_js,
                        "returnByValue": False,  # 确保返回objectId
                    },
                )
                parent_object = parent_response.get("result", {}).get("result", {})

                # 如果父元素为null或不是对象，则停止遍历
                if not parent_object or parent_object.get("subtype") == "null":
                    break

                current_object_id = parent_object.get("objectId")
                if not current_object_id:
                    break

        except Exception as e:
            print(f"Warning: 遍历祖先节点时发生错误。事件监听器列表可能不完整。错误: {e}")
        finally:
            # Phase 2: 释放所有为遍历而创建的远程对象，防止内存泄漏
            for obj_id in object_ids_to_release:
                try:
                    await self.send_command("Runtime.releaseObject", {"objectId": obj_id})
                except Exception:
                    pass  # 忽略清理过程中的错误

        # Phase 3: 获取`window`对象的监听器
        try:
            eval_response = await self.send_command("Runtime.evaluate", {"expression": "window"})
            window_object_id = eval_response.get("result", {}).get("result", {}).get("objectId")

            if window_object_id:
                listeners_response = await self.send_command(
                    "DOMDebugger.getEventListeners", {"objectId": window_object_id}
                )
                listeners = listeners_response.get("result", {}).get("listeners", [])
                for listener in listeners:
                    listener["sourceNodeDescription"] = "window"
                all_listeners.extend(listeners)
        except Exception as e:
            print(f"Warning: 无法获取window事件监听器: {e}")

        return all_listeners

    async def get_element_html(self, node_id: int) -> str:
        """获取元素的HTML表示（标签和属性，不包括子元素）"""
        response = await self.send_command("DOM.getOuterHTML", {"nodeId": node_id})

        return response["result"]["outerHTML"]

    async def get_element_screen_coords(self, node_id: int) -> Optional[Tuple[int, int]]:
        """获取DOM元素在屏幕上的坐标（使用JavaScript的getBoundingClientRect和screen相关属性）"""
        try:
            # 解析节点为远程对象
            response = await self.send_command("DOM.resolveNode", {"nodeId": node_id})
            remote_object = response["result"]["object"]
            object_id = remote_object["objectId"]

            # 执行JavaScript获取元素的屏幕坐标
            js_code = """
            (function(element) {
                if (!element) return null;
                
                const rect = element.getBoundingClientRect();
                if (!rect) return null;
                
                // 计算元素中心点在屏幕上的坐标
                // rect.left + rect.width/2 是元素中心的viewport坐标
                // window.screenX/screenY 是浏览器窗口在屏幕上的坐标
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;
                
                return {
                    screenX: Math.round(window.screenX + centerX),
                    screenY: Math.round(window.screenY + centerY),
                    viewportX: Math.round(centerX),
                    viewportY: Math.round(centerY),
                    rect: {
                        left: rect.left,
                        top: rect.top,
                        width: rect.width,
                        height: rect.height
                    }
                };
            })(this)
            """

            response = await self.send_command(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "functionDeclaration": js_code,
                    "returnByValue": True,
                },
            )

            # 检查是否有JS执行异常
            exception_details = response.get("result", {}).get("exceptionDetails")
            if exception_details:
                error_message = exception_details.get("exception", {}).get("description", "Unknown JavaScript error")
                print(f"JavaScript execution failed in get_element_screen_coords: {error_message}")
                return None

            result = response.get("result", {}).get("result", {})
            if result.get("type") == "object" and "value" in result:
                coords = result["value"]
                if coords and "screenX" in coords and "screenY" in coords:
                    return (coords["screenX"], coords["screenY"])

            return None

        except Exception as e:
            print(f"获取元素屏幕坐标失败: {e}")
            return None

    async def get_element_at_screen_coords(self, screen_x: int, screen_y: int) -> Optional[int]:
        """使用JavaScript方法获取屏幕坐标处的元素

        通过注入JavaScript代码，直接使用document.elementFromPoint和坐标转换
        避免了复杂的屏幕坐标到viewport坐标的转换
        """
        try:
            # 首先注入JavaScript代码
            if not await self.inject_javascript(get_mouse_detector_js()):
                print("❌ JavaScript注入失败")
                return None

            # 使用JavaScript函数获取元素信息（处理屏幕坐标）
            js_get_element = f"""
            (function() {{
                const result = window.getElementAtScreenCoordinates({screen_x}, {screen_y});
                if (result && result.found) {{
                    return {{
                        found: true,
                        element: result.element,
                        screenCoordinates: result.screenCoordinates,
                        viewportCoordinates: result.viewportCoordinates
                    }};
                }} else {{
                    return {{
                        found: false,
                        message: result ? result.message : 'Unknown error',
                        viewportCoordinates: result ? result.viewportCoordinates : null
                    }};
                }}
            }})()
            """

            response = await self.send_command(
                "Runtime.evaluate", {"expression": js_get_element, "returnByValue": True, "awaitPromise": True}
            )

            # 检查响应
            if "result" in response:
                result = response["result"]
                if "exceptionDetails" in result:
                    exception = result["exceptionDetails"]["exception"]
                    error_msg = exception.get("description", "Unknown JavaScript error")
                    print(f"❌ JavaScript执行失败: {error_msg}")
                    return None

                if "value" in result:
                    element_data = result["value"]
                    if element_data and element_data.get("found"):
                        element_info = element_data["element"]
                        print(
                            f"✅ 找到元素: {element_info.get('tagName', 'Unknown')} - {element_info.get('path', 'No path')}"
                        )

                        # 使用选择器获取节点ID
                        element_path = element_info.get("path")
                        if element_path:
                            node_id = await self.get_node_by_selector(element_path)
                            if node_id:
                                return node_id

                        # 如果选择器方法失败，使用坐标方法
                        return await self.get_node_for_location(screen_x, screen_y)
                    else:
                        print(f"❌ 未找到元素: {element_data.get('message', 'Unknown reason')}")
                        return None

            print("❌ 获取元素信息失败: 无效响应")
            return None

        except Exception as e:
            print(f"❌ 获取屏幕坐标元素失败: {e}")
            return None

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
                    node_id = None  # 将无效的nodeId设为None，后续统一处理
                else:
                    return node_id

            # 如果没有有效的nodeId，但有backendNodeId，尝试转换
            if not node_id and backend_node_id and backend_node_id != 0:
                print(f"No nodeId found, attempting to convert backendNodeId: {backend_node_id}")

                # 尝试使用backendNodeId获取有效节点
                try:
                    # 首先确保文档已被请求，这是pushNodesByBackendIdsToFrontend的前置条件
                    try:
                        doc_response = await self.send_command("DOM.getDocument", {"depth": 0})
                        if "error" not in doc_response:
                            print(f"✅ 文档请求成功，准备转换backendNodeId")
                        else:
                            print(f"⚠️  文档请求失败: {doc_response.get('error', {}).get('message', 'Unknown error')}")
                    except Exception as doc_error:
                        print(f"⚠️  文档请求异常: {doc_error}")

                    # 现在尝试转换backendNodeId
                    push_response = await self.send_command(
                        "DOM.pushNodesByBackendIdsToFrontend", {"backendNodeIds": [backend_node_id]}
                    )

                    # 检查是否有错误
                    if "error" in push_response:
                        error_msg = push_response["error"].get("message", "Unknown error")
                        print(f"❌ pushNodesByBackendIdsToFrontend失败: {error_msg}")
                        return None

                    push_result = push_response.get("result", {})
                    push_node_ids = push_result.get("nodeIds", [])

                    if push_node_ids and push_node_ids[0] != 0:
                        valid_node_id = push_node_ids[0]
                        print(f"✅ 成功从backendNodeId {backend_node_id} 转换为nodeId: {valid_node_id}")
                        return valid_node_id
                    else:
                        print(f"❌ 无法从backendNodeId {backend_node_id} 获取有效节点")
                except Exception as push_error:
                    print(f"backendNodeId转换错误: {push_error}")

            # 如果仍然没有找到元素，提供调试信息
            print(f"No element found at coordinates ({x}, {y})")

            # 添加调试信息：检查是否有其他信息
            if "error" in response:
                print(f"Error: {response['error']}")

            if backend_node_id:
                print(f"Found backendNodeId: {backend_node_id}")
            else:
                print("No backendNodeId available")

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
            response = await self.send_command("Target.getTargets", use_session=False)
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
        """等待用户通过鼠标指针选择元素（使用JavaScript元素选择模式）"""
        print("\n🎯 鼠标选择模式已启用")
        print("请将鼠标移动到目标元素上，然后点击选择")
        print("按ESC键取消选择模式\n")

        # 直接使用JavaScript元素选择模式
        element_info = await self.start_element_selection_mode()
        if element_info and element_info != "cancelled":
            print(f"✅ 选择的元素: {element_info.get('tagName', 'Unknown')}")
            print(f"   ID: {element_info.get('id', 'None')}")
            print(f"   类: {element_info.get('className', 'None')}")
            # 通过元素路径获取实际nodeId
            element_path = element_info.get("path")
            if element_path:
                node_id = await self.get_node_by_selector(element_path)
                if node_id:
                    return node_id
        elif element_info == "cancelled":
            print("退出选择模式")
        else:
            print("未选择有效元素")

        return None

    async def get_node_by_selector(self, selector: str) -> Optional[int]:
        """通过CSS选择器获取DOM节点ID"""
        try:
            # 首先获取根文档
            doc_response = await self.send_command("DOM.getDocument", {"depth": 1})
            root_node_id = doc_response.get("result", {}).get("root", {}).get("nodeId")

            if not root_node_id:
                print("无法获取根文档节点")
                return None

            # 使用CSS选择器查找元素
            response = await self.send_command("DOM.querySelector", {"nodeId": root_node_id, "selector": selector})

            node_id = response.get("result", {}).get("nodeId")
            if node_id and node_id != 0:
                print(f"通过选择器 '{selector}' 找到节点ID: {node_id}")
                return node_id
            else:
                print(f"选择器 '{selector}' 未找到匹配的元素")
                return None

        except Exception as e:
            print(f"通过选择器查找元素失败: {e}")
            return None

    async def get_script_source_info(self, script_id: str, line_number: int, column_number: int) -> Dict:
        """获取脚本源信息，优先使用缓存"""
        cached_data = self.script_cache.get(script_id, {})

        base_info = {
            "scriptId": script_id,
            "lineNumber": line_number,
            "columnNumber": column_number,
        }

        # Step 1: Check if source is already cached. None is a valid cached value for a failed fetch.
        if "source" in cached_data:
            return {**base_info, **cached_data}

        # Step 2: Source not in cache, fetch it
        try:
            response = await self.send_command("Debugger.getScriptSource", {"scriptId": script_id})
            if "error" in response:
                error_msg = response["error"].get("message", "Unknown error")
                self.script_cache.setdefault(script_id, {}).update({"error": error_msg, "source": None})
                return {**base_info, **cached_data, "source": None, "error": error_msg}

            script_source = response["result"]["scriptSource"]

            # Step 3: Update cache with new source
            self.script_cache.setdefault(script_id, {}).update({"source": script_source})

            # Re-fetch from cache to get merged view
            final_data = self.script_cache.get(script_id, {})

            # Step 4: Construct and return the result
            return {**base_info, **final_data}

        except Exception as e:
            error_str = str(e)
            self.script_cache.setdefault(script_id, {}).update({"error": error_str, "source": None})
            return {**base_info, **cached_data, "source": None, "error": error_str}

    async def get_stylesheet_text(self, style_sheet_id: str) -> str:
        """获取样式表的完整文本"""
        if style_sheet_id in self.stylesheet_cache:
            return self.stylesheet_cache[style_sheet_id]

        response = await self.send_command("CSS.getStyleSheetText", {"styleSheetId": style_sheet_id})

        text = response["result"]["text"]
        self.stylesheet_cache[style_sheet_id] = text
        return text

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
        """格式化事件监听器输出，按脚本位置分组去重"""
        if not listeners_data:
            return "无事件监听器"

        output = []

        # 按脚本位置分组 (scriptId, lineNumber, columnNumber)
        script_groups: Dict[Tuple, Dict[str, Any]] = {}
        for listener in listeners_data:
            script_id = listener.get("scriptId")
            line_number = listener.get("lineNumber", 0)
            column_number = listener.get("columnNumber", 0)

            # 生成分组键
            if script_id:
                group_key = (script_id, line_number, column_number)
            else:
                # 对于没有脚本信息的监听器，单独处理, 使用type区分不同的原生监听器
                group_key = ("no_script", listener.get("backendNodeId", 0), listener.get("type"))

            if group_key not in script_groups:
                script_groups[group_key] = {
                    "listeners": [],
                    "event_types": set(),
                    "source_descriptions": set(),
                    "script_info": None,
                }

            group = script_groups[group_key]
            group["listeners"].append(listener)
            group["event_types"].add(listener["type"])

            if listener.get("sourceNodeDescription"):
                group["source_descriptions"].add(listener["sourceNodeDescription"])

        # 输出分组结果
        group_count = 0
        for group_key, group_data in script_groups.items():
            group_count += 1
            script_id = group_key[0] if group_key[0] != "no_script" else None
            line_number = group_key[1] if script_id else 0
            column_number = group_key[2] if script_id else 0

            # 汇总信息
            event_types = sorted(list(group_data["event_types"]))
            source_descs = sorted(list(group_data["source_descriptions"]))
            listeners = group_data["listeners"]

            if script_id:
                # 有脚本信息的监听器组
                output.append(f"📍 脚本位置组 #{group_count}")
                output.append("=" * 50)

                # 获取脚本信息（只获取一次）
                script_info = await self.get_script_source_info(str(script_id), int(line_number), int(column_number))

                # 显示脚本基本信息
                output.append(f"🎯 事件类型: {', '.join(event_types)} ({len(event_types)}个)")

                if source_descs:
                    output.append(f"🔗 绑定对象: {', '.join(source_descs)}")

                output.append(f"📄 脚本ID: {script_id}")
                output.append(f"📍 位置: 行 {line_number + 1}, 列 {column_number + 1}")

                # 显示脚本来源信息 - 优先显示URL
                if script_info.get("url") and not script_info["url"].startswith("data:"):
                    output.append(f"🌐 脚本URL: {script_info['url']}")
                elif script_info.get("filename") and not script_info["filename"].startswith("script_"):
                    # 只有当filename不是临时生成的时候才显示
                    output.append(f"📁 脚本文件: {script_info['filename']}")
                else:
                    # 对于没有URL的情况，明确标示
                    output.append(f"📄 内联/动态脚本 (ID: {script_id})")

                # 显示详细属性（仅对第一个监听器）
                first_listener = listeners[0]
                use_capture = "是" if first_listener.get("useCapture", False) else "否"
                passive = "是" if first_listener.get("passive", False) else "否"
                once = "是" if first_listener.get("once", False) else "否"

                output.append(f"⚙️  监听属性: 捕获={use_capture}, 被动={passive}, 一次={once}")

                # 显示相关代码（只显示一次）
                if script_info.get("source"):
                    source_lines = script_info["source"].split("\n")
                    output.append(f"📝 相关代码:")

                    if len(source_lines) == 1:
                        line_content = source_lines[0]
                        if len(line_content) > 200:
                            line_content = line_content[:200] + "... [截断]"
                        output.append(f"    {line_content}")

                    elif 0 <= line_number < len(source_lines):
                        start_line = max(0, line_number - 2)
                        end_line = min(len(source_lines), line_number + 3)
                        for i in range(start_line, end_line):
                            line_prefix = "→ " if i == line_number else "  "
                            line_content = source_lines[i]
                            if len(line_content) > 200:
                                line_content = line_content[:200] + "... [截断]"
                            output.append(f"    {line_prefix}{i + 1}: {line_content}")
                    else:
                        output.append(
                            f"    [警告: 行号 {line_number + 1} 超出脚本范围 (共 {len(source_lines)} 行)，显示脚本开头]"
                        )
                        for i, line in enumerate(source_lines[:5]):
                            line_content = line
                            if len(line_content) > 200:
                                line_content = line_content[:200] + "... [截断]"
                            output.append(f"      {i + 1}: {line_content}")

            else:
                # 没有脚本信息的监听器组
                output.append(f"📍 无脚本信息监听器组 #{group_count}")
                output.append("=" * 50)
                output.append(f"🎯 事件类型: {', '.join(event_types)} ({len(event_types)}个)")

                if source_descs:
                    output.append(f"🔗 绑定对象: {', '.join(source_descs)}")

                # 显示详细属性
                first_listener = listeners[0]
                use_capture = "是" if first_listener.get("useCapture", False) else "否"
                passive = "是" if first_listener.get("passive", False) else "否"
                once = "是" if first_listener.get("once", False) else "否"
                output.append(f"⚙️  监听属性: 捕获={use_capture}, 被动={passive}, 一次={once}")

                # 显示处理函数信息
                if first_listener.get("handler"):
                    handler = first_listener["handler"]
                    if handler.get("description"):
                        output.append(f"📋 函数: {handler['description']}")
                    elif handler.get("className"):
                        output.append(f"📋 类型: {handler['className']}")

            output.append("")

        # 添加汇总统计
        total_listeners = len(listeners_data)
        total_groups = len(script_groups)
        output.append(f"📊 统计: 共 {total_listeners} 个监听器，合并为 {total_groups} 组")

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

    async def inject_javascript(self, js_code: str) -> bool:
        """将JavaScript代码字符串注入到当前页面

        Args:
            js_code: 要注入的JavaScript代码.

        Returns:
            bool: 注入是否成功.
        """
        try:
            # 使用Runtime.evaluate执行JavaScript代码
            response = await self.send_command(
                "Runtime.evaluate",
                {"expression": js_code, "returnByValue": False, "awaitPromise": True, "userGesture": False},
            )

            # 检查是否有异常
            if "result" in response:
                result = response["result"]
                if "exceptionDetails" in result:
                    exception = result["exceptionDetails"]["exception"]
                    error_msg = exception.get("description", "Unknown JavaScript error")
                    print(f"❌ JavaScript注入失败: {error_msg}")
                    return False
                else:
                    print("✅ JavaScript代码注入成功")
                    return True
            else:
                print("❌ JavaScript注入失败: 无效响应")
                return False

        except Exception as e:
            print(f"❌ JavaScript注入过程中发生错误: {e}")
            return False

    async def start_element_selection_mode(self) -> Optional[Dict]:
        """启动元素选择模式，返回用户选择的元素信息

        Returns:
            Optional[Dict]: 选择的元素信息，如果取消或超时则返回None
        """
        # 从文件加载JS代码并注入
        try:
            js_code = get_mouse_detector_js()
        except FileNotFoundError:
            return None

        if not await self.inject_javascript(js_code):
            print("❌ JavaScript注入失败，无法启动元素选择模式")
            return None

        # 存储元素选择结果
        self.element_selection_result = None
        self.original_console_handler = self.console_message_handler

        # 设置临时控制台消息处理器
        self.console_message_handler = self._handle_element_selection_console

        try:
            # 启动元素选择模式
            await self.send_command(
                "Runtime.evaluate", {"expression": "window.startElementSelection();", "returnByValue": False}
            )

            print("🎯 元素选择模式已启动")
            print("   - 移动鼠标查看元素高亮")
            print("   - 点击选择元素")
            print("   - 按ESC键取消")

            # 等待用户选择（最多30秒）
            timeout = 30.0
            start_time = time.time()

            while time.time() - start_time < timeout:
                if self.element_selection_result is not None:
                    break
                await asyncio.sleep(0.1)

            if self.element_selection_result is None:
                print("⏰ 元素选择超时")
                # 停止选择模式
                await self.send_command(
                    "Runtime.evaluate", {"expression": "window.stopElementSelection();", "returnByValue": False}
                )

            return self.element_selection_result

        except asyncio.CancelledError:
            print("🚫 元素选择被取消")
            return None
        except Exception as e:
            print(f"❌ 元素选择过程中发生错误: {e}")
            return None
        finally:
            # 恢复原来的控制台消息处理器
            self.console_message_handler = self.original_console_handler
            self.element_selection_result = None

    async def _handle_element_selection_console(self, console_data: Dict[str, Any]) -> None:
        """
        处理元素选择过程中的控制台消息。
        此处理器专门用于解析由注入的JS脚本通过 `console.log` 发送的信令。
        """
        try:
            params = console_data.get("message", {})
            message_text = ""

            # 尝试从 Console.messageAdded 事件中提取文本
            # 结构: {'message': {'source': ..., 'level': ..., 'text': '...'}}
            if isinstance(params, dict) and "message" in params and "text" in params["message"]:
                message_text = params["message"]["text"]
            # 尝试从 Runtime.consoleAPICalled 事件中提取文本
            # 结构: {'type': 'log', 'args': [{'type': 'string', 'value': '...'}]}
            elif isinstance(params, dict) and "args" in params:
                message_parts: List[str] = []
                for arg in params.get("args", []):
                    if arg.get("type") == "string":
                        message_parts.append(arg.get("value", ""))
                message_text = " ".join(message_parts)

            if not message_text:
                return  # 未找到有效的消息文本

            if "[CHROME_TRACER_SELECTED]" in message_text:
                json_start = message_text.find("{")
                if json_start != -1:
                    json_str = message_text[json_start:]
                    try:
                        element_data = json.loads(json_str)
                        self.element_selection_result = element_data
                    except json.JSONDecodeError:
                        print("❌ 解析选择的元素数据失败")
                        self.element_selection_result = "error"

            elif "[CHROME_TRACER_CANCELLED]" in message_text:
                self.element_selection_result = "cancelled"

        except Exception as e:
            print(f"❌ 处理元素选择控制台消息时发生错误: {e}")
            self.element_selection_result = "error"

    async def close(self):
        """关闭连接"""
        # 停止控制台监听
        await self.stop_console_listening()

        if self._message_handler_task:
            self._message_handler_task.cancel()
            await asyncio.gather(self._message_handler_task, return_exceptions=True)

        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

    async def start_console_listening(self, message_handler: Optional[Callable] = None):
        """开始监听控制台消息"""
        if self.console_listening:
            print("控制台监听已启动")
            return

        self.console_message_handler = message_handler
        self.console_listening = True

        try:
            await self.send_command("Console.enable")
            print("✅ 控制台监听已启用")
        except Exception as e:
            print(f"❌ 启用控制台监听失败: {e}")
            self.console_listening = False

    async def stop_console_listening(self):
        """停止监听控制台消息"""
        if not self.console_listening:
            return

        self.console_listening = False

        try:
            await self.send_command("Console.disable")
            print("✅ 控制台监听已禁用")
        except Exception as e:
            print(f"❌ 禁用控制台监听失败: {e}")

    async def _handle_console_api_called(self, params: Dict):
        """处理Runtime.consoleAPICalled事件"""
        try:
            call_type = params.get("type", "")
            args = params.get("args", [])
            timestamp = params.get("timestamp")
            stack_trace = params.get("stackTrace")
            execution_context_id = params.get("executionContextId")
            context = params.get("context", "")

            # 格式化消息内容
            message_parts = []
            for arg in args:
                if arg.get("type") == "string":
                    message_parts.append(arg.get("value", ""))
                elif arg.get("type") == "number":
                    message_parts.append(str(arg.get("value", "")))
                elif arg.get("type") == "boolean":
                    message_parts.append(str(arg.get("value", "")))
                elif arg.get("type") == "undefined":
                    message_parts.append("undefined")
                elif arg.get("type") == "null":
                    message_parts.append("null")
                elif arg.get("type") == "object":
                    message_parts.append(f"[object {arg.get('className', 'Object')}]")
                else:
                    message_parts.append(str(arg))

            message_text = " ".join(message_parts)

            # 格式化时间戳（Chrome使用毫秒，需要转换为秒）
            if timestamp:
                from datetime import datetime

                dt = datetime.fromtimestamp(timestamp / 1000.0)
                time_str = dt.strftime("%H:%M:%S.%f")[:-3]
            else:
                time_str = ""

            # 格式化堆栈信息
            stack_info = ""
            if stack_trace and stack_trace.get("callFrames"):
                frames = stack_trace["callFrames"]
                if frames:
                    frame = frames[0]  # 取第一个调用帧
                    function_name = frame.get("functionName", "anonymous")
                    url = frame.get("url", "")
                    line_number = frame.get("lineNumber", 0) + 1
                    column_number = frame.get("columnNumber", 0) + 1

                    if url:
                        filename = url.split("/")[-1] if "/" in url else url
                        stack_info = f" at {function_name} ({filename}:{line_number}:{column_number})"
                    else:
                        stack_info = f" at {function_name} (line {line_number}:{column_number})"

            # 构建完整的输出消息
            output_message = f"[{time_str}] {call_type.upper()}: {message_text}{stack_info}"

            # 调用自定义处理函数或默认输出
            if self.console_message_handler:
                await self.console_message_handler(
                    {
                        "type": call_type,
                        "message": message_text,
                        "timestamp": timestamp,
                        "stack_trace": stack_trace,
                        "execution_context_id": execution_context_id,
                        "context": context,
                        "raw": params,
                    }
                )
            else:
                print(output_message)

        except Exception as e:
            print(f"处理控制台消息错误: {e}")

    async def _handle_console_message_added(self, params: Dict):
        """处理Console.messageAdded事件"""
        try:
            message = params.get("message", {})
            message_text = message.get("text", "")
            level = message.get("level", "")
            source = message.get("source", "")
            url = message.get("url", "")
            line = message.get("line", 0)

            # 格式化输出
            output_message = f"[{level.upper()}] {source}: {message_text}"
            if url:
                output_message += f" ({url}:{line})"

            # 调用自定义处理函数或默认输出
            if self.console_message_handler:
                await self.console_message_handler(
                    {"type": level, "message": message_text, "source": source, "url": url, "line": line, "raw": params}
                )
            else:
                print(output_message)

        except Exception as e:
            print(f"处理控制台消息错误: {e}")


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
                success, _ = await launch_browser_with_debugging("chrome", port, return_process_info=True)
                if success:
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
    selector: str,
    port: int,
    show_events: bool,
    show_html: bool,
    from_pointer: bool,
):
    """主函数：检查元素的样式和事件监听器"""
    websocket_urls = await find_chrome_tabs(port)
    if not websocket_urls:
        print("未找到浏览器标签页，请确保浏览器以远程调试模式运行:")
        print("Chrome: chrome --remote-debugging-port=9222")
        print("Edge: msedge --remote-debugging-port=9222")
        print("或者指定正确的端口: --port <port_number>")
        return

    inspector = DOMInspector(websocket_urls[0])
    await inspector.connect()

    try:
        target_id = await inspector.find_tab_by_url(url_pattern)
        if not target_id:
            print(f"未找到匹配URL '{url_pattern}' 的标签页或用户取消选择")
            return

        session_id = await inspector.attach_to_tab(target_id)
        if not session_id:
            print("附加到标签页失败")
            return

        node_id = None
        if from_pointer:
            node_id = await inspector.wait_for_pointer_selection()
            if not node_id:
                print("未选择元素，退出")
                return
        elif selector:
            node_id = await inspector.find_element(selector)
            if not node_id:
                print(f"未找到选择器 '{selector}' 匹配的元素")
                return
        else:
            print("错误：必须提供 --selector 或使用 --from-pointer")
            return

        print(f"找到元素，nodeId: {node_id}")

        styles_data = await inspector.get_element_styles(node_id)
        formatted_styles = await inspector.format_styles(styles_data)
        print("\n元素样式信息:")
        print("=" * 60)
        print(formatted_styles)

        if show_events:
            listeners_data = await inspector.get_element_event_listeners(node_id)
            formatted_listeners = await inspector.format_event_listeners(listeners_data)
            print("\n事件监听器信息:")
            print("=" * 60)
            print(formatted_listeners)

        if show_html:
            html_content = await inspector.get_element_html(node_id)
            formatted_html = await inspector.format_html(html_content)
            print("\n元素HTML表示:")
            print("=" * 60)
            print(formatted_html)

    finally:
        await inspector.close()


async def run_debugger_trace(url_pattern: str, port: int):
    """主函数：运行调试追踪器模式"""
    websocket_urls = await find_chrome_tabs(port)
    if not websocket_urls:
        print("未找到浏览器标签页，请确保浏览器以远程调试模式运行。")
        return

    inspector = DOMInspector(websocket_urls[0])
    await inspector.connect()

    stop_event = asyncio.Event()

    try:
        target_id = await inspector.find_tab_by_url(url_pattern)
        if not target_id:
            print(f"未找到匹配URL '{url_pattern}' 的标签页或用户取消选择")
            return

        session_id = await inspector.attach_to_tab(target_id)
        if not session_id:
            print("附加到标签页失败")
            return

        print("\n✅ Debugger trace mode activated.")
        print("Waiting for 'debugger;' statements in the attached page.")
        print("Press Ctrl+C to exit.")

        await stop_event.wait()

    except asyncio.CancelledError:
        print("\nExiting debugger trace mode.")
    finally:
        await inspector.close()


def main():
    parser = argparse.ArgumentParser(description="浏览器DOM检查与调试追踪工具 (支持Chrome/Edge)")
    parser.add_argument("--port", type=int, default=9222, help="浏览器调试端口")

    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # --- Inspect command ---
    parser_inspect = subparsers.add_parser("inspect", help="检查元素的样式和事件监听器")
    parser_inspect.add_argument("--url", help="要匹配的URL模式 (可选，如未指定则提供选择)")
    parser_inspect.add_argument("--selector", help="CSS选择器 (如果使用 --from-pointer 则可选)")
    parser_inspect.add_argument("--events", action="store_true", help="显示事件监听器信息")
    parser_inspect.add_argument("--html", action="store_true", help="显示元素HTML表示")
    parser_inspect.add_argument("--from-pointer", action="store_true", help="使用鼠标指针选择元素")

    # --- Trace command ---
    parser_trace = subparsers.add_parser("trace", help="追踪JS 'debugger;' 语句并显示调用栈")
    parser_trace.add_argument("--url", help="要匹配的URL模式 (可选，如未指定则提供选择)")

    args = parser.parse_args()
    url_pattern = args.url if args.url else ""

    try:
        if args.command == "inspect":
            if not args.selector and not args.from_pointer:
                parser_inspect.error("必须提供 --selector 或使用 --from-pointer")
            asyncio.run(
                inspect_element_styles(url_pattern, args.selector, args.port, args.events, args.html, args.from_pointer)
            )
        elif args.command == "trace":
            asyncio.run(run_debugger_trace(url_pattern, args.port))
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")


class BrowserContextManager:
    """浏览器上下文管理器，支持自动清理和保持存活两种模式"""

    def __init__(self, browser_type: str = "edge", port: int = 9222, auto_cleanup: bool = True):
        self.browser_type = browser_type
        self.port = port
        self.auto_cleanup = auto_cleanup
        self.browser_process = None
        self.websocket_urls = []
        self._browser_launched = False
        self._user_data_dir = None

    async def __aenter__(self):
        """进入上下文，启动或连接浏览器"""
        print(f"🚀 初始化浏览器上下文 (模式: {'自动清理' if self.auto_cleanup else '保持存活'})")

        # 查找现有浏览器标签页
        self.websocket_urls = await find_chrome_tabs(self.port, auto_launch=False)

        if not self.websocket_urls:
            print(f"⚠️  未找到浏览器标签页，启动 {self.browser_type}...")
            # 启动浏览器
            result = await launch_browser_with_debugging(self.browser_type, self.port, return_process_info=True)
            if isinstance(result, tuple):
                success, process_info = result
            else:
                success, process_info = result, None
            if not success:
                raise Exception(f"无法启动 {self.browser_type} 浏览器")

            self.browser_process = process_info
            self._browser_launched = True
            self._user_data_dir = process_info.get("user_data_dir")

            # 等待浏览器启动
            await asyncio.sleep(3)
            self.websocket_urls = await find_chrome_tabs(self.port, auto_launch=False)
            if not self.websocket_urls:
                raise Exception("启动后仍未找到浏览器标签页")

        print(f"✅ 找到 {len(self.websocket_urls)} 个浏览器标签页")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出上下文，根据模式决定是否清理浏览器"""
        if self.auto_cleanup and self._browser_launched:
            print("🧹 自动清理浏览器进程...")
            await cleanup_browser(self.browser_process)
        else:
            print("💾 保持浏览器存活")

        # 清理临时目录（如果存在且需要清理）
        if self.auto_cleanup and self._user_data_dir:
            await cleanup_temp_directory(self._user_data_dir)

    def get_websocket_urls(self):
        """获取WebSocket URL列表"""
        return self.websocket_urls

    def get_main_websocket_url(self):
        """获取主WebSocket URL"""
        return self.websocket_urls[0] if self.websocket_urls else None


async def launch_browser_with_debugging(
    browser_type: str = "chrome",
    port: int = 9222,
    user_data_dir: Optional[str] = None,
    return_process_info: bool = False,
) -> Union[bool, Tuple[bool, Dict[str, Any]]]:
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

    process_info: Dict[str, Any] = {
        "browser_type": browser_type,
        "port": port,
        "user_data_dir": user_data_dir,
        "pid": None,
        "command": None,
    }

    try:
        if system == "Darwin":  # macOS
            browser_names = {
                "chrome": ["Google Chrome", "Google Chrome", "Chrome"],
                "edge": ["Microsoft Edge", "Microsoft Edge", "Edge"],
            }

            browser_process = None
            browser_launched = False

            for chrome_name in browser_names.get(browser_type.lower(), []):
                try:
                    # 构建启动命令
                    cmd = [
                        "open",
                        "-n",
                        "-a",
                        chrome_name,
                        "--args",
                        f"--remote-debugging-port={port}",
                        f"--user-data-dir={user_data_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ]

                    process_info["command"] = " ".join(cmd)

                    # 启动浏览器
                    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    process.wait()  # 等待open命令完成

                    if process.returncode == 0:
                        # 等待浏览器启动
                        time.sleep(2)

                        # 查找浏览器进程
                        try:
                            pgrep_result = subprocess.run(
                                ["pgrep", "-f", f"remote-debugging-port={port}"], capture_output=True, text=True
                            )
                            if pgrep_result.returncode == 0:
                                pids = pgrep_result.stdout.strip().split("\n")
                                if pids and pids[0]:
                                    process_info["pid"] = int(pids[0])
                                    browser_launched = True
                                    browser_process = process
                                    break
                        except:
                            continue
                except (subprocess.CalledProcessError, FileNotFoundError, OSError):
                    continue

            if not browser_launched:
                print(f"无法找到或启动{browser_type}浏览器，请确保已安装")
                if return_process_info:
                    return False, process_info
                return False

        elif system == "Windows":
            # Windows实现（简化版）
            browser_exes = {"chrome": "chrome.exe", "edge": "msedge.exe"}

            exe_name = browser_exes.get(browser_type.lower())
            if not exe_name:
                if return_process_info:
                    return False, process_info
                return False

            cmd = [
                exe_name,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
            ]

            process_info["command"] = " ".join(cmd)

            process = subprocess.Popen(cmd)
            process_info["pid"] = process.pid
            browser_process = process
            browser_launched = True

        elif system == "Linux":
            # Linux实现（简化版）
            browser_commands = {"chrome": "google-chrome", "edge": "microsoft-edge"}

            cmd_name = browser_commands.get(browser_type.lower())
            if not cmd_name:
                if return_process_info:
                    return False, process_info
                return False

            cmd = [
                cmd_name,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
            ]

            process_info["command"] = " ".join(cmd)

            process = subprocess.Popen(cmd)
            process_info["pid"] = process.pid
            browser_process = process
            browser_launched = True

        else:
            if return_process_info:
                return False, process_info
            return False

        print(f"使用临时配置文件启动浏览器: {user_data_dir}")

        # 等待浏览器完全启动
        time.sleep(5)

        if return_process_info:
            return True, process_info
        return True

    except Exception as e:
        print(f"启动浏览器失败: {e}")
        # 清理临时目录
        try:
            if user_data_dir and os.path.exists(user_data_dir):
                shutil.rmtree(user_data_dir)
        except:
            pass

        if return_process_info:
            return False, process_info
        return False


async def cleanup_browser(process_info: dict):
    """清理浏览器进程"""
    import os
    import platform
    import signal
    import subprocess
    import time

    if not process_info:
        return

    system = platform.system()
    pid = process_info.get("pid")
    user_data_dir = process_info.get("user_data_dir")

    print(f"🧹 清理浏览器进程 (PID: {pid})")

    try:
        if pid:
            if system == "Darwin" or system == "Linux":
                # Unix系统使用kill命令
                os.kill(pid, signal.SIGTERM)  # 先尝试优雅关闭
                time.sleep(1)

                # 检查进程是否还存在
                try:
                    os.kill(pid, 0)  # 检查进程是否存在
                    # 如果还存在，强制杀死
                    subprocess.run(["kill", "-9", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    # 进程已经退出
                    pass

            elif system == "Windows":
                # Windows使用taskkill
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )

        # 清理使用相同端口的其他浏览器进程
        if system == "Darwin" or system == "Linux":
            subprocess.run(
                ["pkill", "-f", f"remote-debugging-port={process_info.get('port', 9222)}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Windows":
            subprocess.run(
                ["taskkill", "/FI", f"WINDOWTITLE eq *remote-debugging-port*", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    except Exception as e:
        print(f"清理浏览器进程时发生错误: {e}")

    # 清理临时目录
    await cleanup_temp_directory(user_data_dir)


async def cleanup_temp_directory(user_data_dir: str):
    """清理临时目录"""
    import os
    import shutil

    if user_data_dir and os.path.exists(user_data_dir):
        try:
            shutil.rmtree(user_data_dir)
            print(f"✅ 清理临时配置文件目录: {user_data_dir}")
        except Exception as e:
            print(f"清理临时目录失败: {e}")


async def get_browser_processes(port: int = None):
    """获取浏览器进程信息"""
    import platform
    import subprocess

    system = platform.system()
    processes = []

    try:
        if system == "Darwin" or system == "Linux":
            # Unix系统使用pgrep
            cmd = ["pgrep", "-f", "remote-debugging-port"]
            if port:
                cmd = ["pgrep", "-f", f"remote-debugging-port={port}"]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    if pid.strip():
                        processes.append({"pid": int(pid.strip()), "system": system})

        elif system == "Windows":
            # Windows使用tasklist
            cmd = ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FI", "IMAGENAME eq msedge.exe", "/FO", "CSV"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")[1:]  # 跳过标题行
                for line in lines:
                    if line.strip():
                        parts = line.strip().split(",")
                        if len(parts) >= 2:
                            processes.append(
                                {"name": parts[0].strip('"'), "pid": int(parts[1].strip('"')), "system": system}
                            )

    except Exception as e:
        print(f"获取浏览器进程信息失败: {e}")

    return processes


if __name__ == "__main__":
    main()
