#!/usr/bin/env python3
"""
Chrome DevTools Protocol DOM Inspector
获取元素样式和事件监听器信息，格式与Chrome DevTools完全一致

Dependencies:
- aiohttp: pip install aiohttp

Element selection is handled via JavaScript injection for cross-platform compatibility.
"""

import argparse
import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

# JavaScript代码：鼠标元素检测器
MOUSE_ELEMENT_DETECTOR_JS = """
/**
 * Chrome Context Tracer - Mouse Element Detector
 * 纯JavaScript实现的鼠标元素检测器
 * 通过控制台输出与Python端通信
 */

(function() {
    'use strict';
    
    // 防止重复注入
    if (window.chromeContextTracer) {
        console.log('[CHROME_TRACER] Already initialized');
        return;
    }
    
    window.chromeContextTracer = {
        version: '1.0.0',
        isActive: false,
        lastElement: null,
        overlay: null
    };
    
    const tracer = window.chromeContextTracer;
    
    /**
     * 生成元素的唯一CSS选择器路径
     */
    function getElementPath(element) {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) {
            return null;
        }
        
        if (element.id) {
            return '#' + element.id;
        }
        
        if (element === document.body) {
            return 'body';
        }
        
        const path = [];
        while (element && element.parentNode) {
            if (element.id) {
                path.unshift('#' + element.id);
                break;
            }
            
            let selector = element.tagName.toLowerCase();
            const siblings = Array.from(element.parentNode.children);
            const index = siblings.indexOf(element);
            
            if (index > 0) {
                selector += ':nth-child(' + (index + 1) + ')';
            }
            
            path.unshift(selector);
            element = element.parentNode;
        }
        
        return path.join(' > ');
    }
    
    /**
     * 获取元素的详细信息
     */
    function getElementInfo(element, mouseX, mouseY) {
        if (!element) return null;
        
        const rect = element.getBoundingClientRect();
        const computedStyle = window.getComputedStyle(element);
        
        return {
            // 基本信息
            tagName: element.tagName,
            id: element.id || '',
            className: element.className || '',
            textContent: element.textContent ? element.textContent.substring(0, 100) : '',
            
            // 位置信息
            mouse: {
                x: mouseX,
                y: mouseY
            },
            rect: {
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            },
            
            // 选择器信息
            path: getElementPath(element),
            
            // 样式信息
            style: {
                display: computedStyle.display,
                position: computedStyle.position,
                zIndex: computedStyle.zIndex,
                backgroundColor: computedStyle.backgroundColor,
                cursor: computedStyle.cursor
            },
            
            // 属性信息
            attributes: Array.from(element.attributes).reduce((acc, attr) => {
                acc[attr.name] = attr.value;
                return acc;
            }, {}),
            
            // 时间戳
            timestamp: Date.now()
        };
    }

    /**
     * 获取指定坐标处的元素信息
     */
    function getElementAtCoordinates(x, y) {
        const element = document.elementFromPoint(x, y);
        if (!element) {
            return {
                found: false,
                message: `No element found at coordinates (${x}, ${y})`
            };
        }
        
        const elementInfo = getElementInfo(element, x, y);
        return {
            found: true,
            element: elementInfo,
            coordinates: { x, y }
        };
    }
    
    /**
     * 创建高亮覆盖层
     */
    function createOverlay() {
        if (tracer.overlay) return tracer.overlay;
        
        const overlay = document.createElement('div');
        overlay.id = 'chrome-tracer-overlay';
        overlay.style.cssText = `
            position: fixed;
            pointer-events: none;
            z-index: 10000;
            border: 2px solid #ff4444;
            background-color: rgba(255, 68, 68, 0.1);
            transition: all 0.1s ease;
            display: none;
        `;
        
        document.body.appendChild(overlay);
        tracer.overlay = overlay;
        return overlay;
    }
    
    /**
     * 更新覆盖层位置
     */
    function updateOverlay(element) {
        if (!tracer.overlay || !element) return;
        
        const rect = element.getBoundingClientRect();
        const overlay = tracer.overlay;
        
        overlay.style.left = rect.left + 'px';
        overlay.style.top = rect.top + 'px';
        overlay.style.width = rect.width + 'px';
        overlay.style.height = rect.height + 'px';
        overlay.style.display = 'block';
    }
    
    /**
     * 隐藏覆盖层
     */
    function hideOverlay() {
        if (tracer.overlay) {
            tracer.overlay.style.display = 'none';
        }
    }
    
    /**
     * 鼠标移动事件处理器
     */
    function handleMouseMove(event) {
        if (!tracer.isActive) return;
        
        const element = event.target;
        if (element === tracer.lastElement) return;
        
        tracer.lastElement = element;
        updateOverlay(element);
        
        // 输出元素信息到控制台
        const elementInfo = getElementInfo(element, event.clientX, event.clientY);
        console.log('[CHROME_TRACER_HOVER]', JSON.stringify(elementInfo));
    }
    
    /**
     * 鼠标点击事件处理器
     */
    function handleMouseClick(event) {
        if (!tracer.isActive) return;
        
        // 阻止默认行为
        event.preventDefault();
        event.stopPropagation();
        
        const element = event.target;
        const elementInfo = getElementInfo(element, event.clientX, event.clientY);
        
        // 输出选中的元素信息
        console.log('[CHROME_TRACER_SELECTED]', JSON.stringify(elementInfo));
        
        // 停止检测模式
        tracer.stop();
        
        return false;
    }
    
    /**
     * 键盘事件处理器
     */
    function handleKeyDown(event) {
        if (!tracer.isActive) return;
        
        // ESC键退出检测模式
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            
            console.log('[CHROME_TRACER_CANCELLED]', JSON.stringify({
                action: 'cancelled',
                timestamp: Date.now()
            }));
            
            tracer.stop();
        }
    }
    
    /**
     * 启动元素检测模式
     */
    tracer.start = function() {
        if (tracer.isActive) {
            console.log('[CHROME_TRACER] Already active');
            return;
        }
        
        tracer.isActive = true;
        tracer.lastElement = null;
        
        // 创建覆盖层
        createOverlay();
        
        // 添加事件监听器
        document.addEventListener('mousemove', handleMouseMove, true);
        document.addEventListener('click', handleMouseClick, true);
        document.addEventListener('keydown', handleKeyDown, true);
        
        // 改变鼠标样式
        document.body.style.cursor = 'crosshair';
        
        console.log('[CHROME_TRACER_STARTED]', JSON.stringify({
            action: 'started',
            timestamp: Date.now(),
            message: 'Element selection mode activated. Click to select, ESC to cancel.'
        }));
    };
    
    /**
     * 停止元素检测模式
     */
    tracer.stop = function() {
        if (!tracer.isActive) {
            return;
        }
        
        tracer.isActive = false;
        tracer.lastElement = null;
        
        // 移除事件监听器
        document.removeEventListener('mousemove', handleMouseMove, true);
        document.removeEventListener('click', handleMouseClick, true);
        document.removeEventListener('keydown', handleKeyDown, true);
        
        // 恢复鼠标样式
        document.body.style.cursor = '';
        
        // 隐藏覆盖层
        hideOverlay();
        
        console.log('[CHROME_TRACER_STOPPED]', JSON.stringify({
            action: 'stopped',
            timestamp: Date.now()
        }));
    };
    
    /**
     * 获取当前状态
     */
    tracer.getStatus = function() {
        return {
            isActive: tracer.isActive,
            version: tracer.version,
            lastElement: tracer.lastElement ? getElementPath(tracer.lastElement) : null
        };
    };
    
    // 暴露全局控制方法
    window.startElementSelection = tracer.start;
    window.stopElementSelection = tracer.stop;
    window.getTracerStatus = tracer.getStatus;
    window.getElementAtCoordinates = getElementAtCoordinates;
    
    console.log('[CHROME_TRACER] Initialized successfully');
    console.log('[CHROME_TRACER] Available commands:');
    console.log('[CHROME_TRACER]   - startElementSelection(): Start element detection');
    console.log('[CHROME_TRACER]   - stopElementSelection(): Stop element detection');
    console.log('[CHROME_TRACER]   - getTracerStatus(): Get current status');
    console.log('[CHROME_TRACER]   - getElementAtCoordinates(x, y): Get element at specific coordinates');
    
})();
"""


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
        self.console_listening = False  # 控制台监听状态
        self.console_message_handler = None  # 控制台消息处理回调
        self.element_selection_result = None  # 元素选择结果
        self.original_console_handler = None  # 保存原始的控制台处理器

    async def connect(self):
        """连接到Chrome DevTools Protocol WebSocket"""
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.websocket_url)

        # 启用必要的域（处理可能不存在的命令）
        await self.send_command("DOM.enable")
        await self.send_command("CSS.enable")
        await self.send_command("Runtime.enable")
        await self.send_command("Page.enable")

        # 启用控制台监听
        await self.start_console_listening()

        # 启用Debugger域以支持脚本源信息获取
        try:
            await self.send_command("Debugger.enable")
        except Exception:
            print("警告: Debugger.enable 不可用，脚本源信息功能可能受限")

        # 监听样式表添加事件以收集头部信息
        try:
            await self.collect_stylesheet_headers()
        except Exception:
            print("警告: 无法收集样式表头部信息")

        print(f"Connected to Browser DevTools: {self.websocket_url}")

        # 添加连接后的等待时间，让浏览器稳定
        await asyncio.sleep(1)

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

                        # 处理控制台消息事件（无需response id）
                        if response.get("method") == "Runtime.consoleAPICalled":
                            if self.console_listening and self.console_message_handler:
                                await self.console_message_handler(
                                    {
                                        "type": response.get("params", {}).get("type", ""),
                                        "message": response.get("params", {}),
                                        "raw": response,
                                    }
                                )
                            elif self.console_listening:
                                await self._handle_console_api_called(response.get("params", {}))
                        elif response.get("method") == "Console.messageAdded":
                            if self.console_listening and self.console_message_handler:
                                await self.console_message_handler(
                                    {
                                        "type": response.get("params", {}).get("message", {}).get("level", ""),
                                        "message": response.get("params", {}),
                                        "raw": response,
                                    }
                                )
                            elif self.console_listening:
                                await self._handle_console_message_added(response.get("params", {}))

                        # 处理命令响应（有response id）
                        if response.get("id") == message_id:
                            return response
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        raise Exception(f"WebSocket error: {msg.data}")
                    elif msg.type == aiohttp.WSMsgType.CLOSE:
                        raise Exception("WebSocket connection closed by remote")
                raise Exception("WebSocket connection closed")

            result = await asyncio.wait_for(wait_for_response(), timeout=30.0)
            # 检查响应中是否有错误
            if "error" in result:
                error_info = result["error"]
                raise Exception(f"Command {method} failed: {error_info.get('message', 'Unknown error')}")

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

    async def find_tab_by_url(self, url_pattern: Optional[str] = None) -> Optional[str]:
        """查找匹配URL模式的标签页，如果未指定URL则返回最上层/当前显示的标签页"""
        # 添加获取目标前的等待时间
        await asyncio.sleep(0.5)
        response = await self.send_command("Target.getTargets")
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

            # 多个标签页，让用户选择
            for i, target in enumerate(valid_targets, 1):
                print(f"  {i}. {target['url']}")

            while True:
                try:
                    choice = input(f"\n请选择标签页 (1-{len(valid_targets)}): ").strip()
                    choice_num = int(choice)
                    if 1 <= choice_num <= len(valid_targets):
                        selected_target = valid_targets[choice_num - 1]
                        print(f"✅ 选择标签页: {selected_target['url']}")
                        return selected_target["targetId"]
                    else:
                        print(f"请输入 1 到 {len(valid_targets)} 之间的数字")
                except (ValueError, KeyboardInterrupt):
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
            js_file_path = "/Users/richard/code/terminal-llm/chrome-context-tracer/mouse_element_detector.js"
            try:
                with open(js_file_path, "r", encoding="utf-8") as f:
                    js_code = f.read()
                print(f"✅ 从文件加载JavaScript代码: {js_file_path}")
            except Exception as e:
                print(f"❌ 无法读取JavaScript文件: {e}")
                return None

            if not await self.inject_javascript_file(js_code):
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
            # 使用单独的 Runtime.getProperties 或从源码中推断信息
            try:
                # 先尝试从源码注释中提取URL信息（如Raven.js的情况）
                script_url = ""
                filename = f"script_{script_id[-8:]}.js"

                # 检查源码开头是否包含URL信息
                source_lines = script_source.split("\n")[:5]  # 检查前5行
                for line in source_lines:
                    line = line.strip()
                    if "://" in line and ("http" in line or "github.com" in line):
                        # 尝试提取URL
                        import re

                        url_match = re.search(r'(https?://[^\s\'"]+)', line)
                        if url_match:
                            script_url = url_match.group(1)
                            break

                # 如果找到了URL，从中提取文件名
                if script_url:
                    from urllib.parse import urlparse

                    parsed_url = urlparse(script_url)
                    if parsed_url.path:
                        filename = parsed_url.path.split("/")[-1]
                        if not filename.endswith(".js"):
                            filename = filename + ".js"

                    # 缓存脚本源码和元数据
                    self.script_cache[script_id] = {
                        "source": script_source,
                        "filename": filename,
                        "url": script_url,
                        "scriptInfo": {},
                    }

                    return {
                        "scriptId": script_id,
                        "lineNumber": line_number,
                        "columnNumber": column_number,
                        "source": script_source,
                        "filename": filename,
                        "url": script_url,
                        "scriptInfo": {},
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
        """格式化事件监听器输出，按脚本位置分组去重"""
        if not listeners_data:
            return "无事件监听器"

        output = []

        # 按脚本位置分组 (scriptId, lineNumber, columnNumber)
        script_groups = {}
        for listener in listeners_data:
            script_id = listener.get("scriptId")
            line_number = listener.get("lineNumber", 0)
            column_number = listener.get("columnNumber", 0)

            # 生成分组键
            if script_id:
                group_key = (script_id, line_number, column_number)
            else:
                # 对于没有脚本信息的监听器，单独处理
                group_key = ("no_script", listener.get("backendNodeId", 0))

            if group_key not in script_groups:
                script_groups[group_key] = {
                    "listeners": [],
                    "event_types": set(),
                    "backend_node_ids": set(),
                    "script_info": None,
                }

            script_groups[group_key]["listeners"].append(listener)
            script_groups[group_key]["event_types"].add(listener["type"])
            if listener.get("backendNodeId"):
                script_groups[group_key]["backend_node_ids"].add(listener["backendNodeId"])

        # 输出分组结果
        group_count = 0
        for group_key, group_data in script_groups.items():
            group_count += 1
            script_id, line_number, column_number = group_key if len(group_key) == 3 else (None, None, None)

            # 汇总信息
            event_types = sorted(group_data["event_types"])
            node_ids = sorted(group_data["backend_node_ids"])
            listeners = group_data["listeners"]

            if script_id and script_id != "no_script":
                # 有脚本信息的监听器组
                output.append(f"📍 脚本位置组 #{group_count}")
                output.append("=" * 50)

                # 获取脚本信息（只获取一次）
                script_info = await self.get_script_source_info(script_id, line_number, column_number)

                # 显示脚本基本信息
                output.append(f"🎯 事件类型: {', '.join(event_types)} ({len(event_types)}个)")
                output.append(f"🔗 绑定节点: {', '.join(map(str, node_ids))} ({len(node_ids)}个节点)")
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
                    if 0 <= line_number < len(source_lines):
                        output.append(f"📝 相关代码:")
                        start_line = max(0, line_number - 2)
                        end_line = min(len(source_lines), line_number + 3)
                        for i in range(start_line, end_line):
                            line_prefix = "→ " if i == line_number else "  "
                            line_content = source_lines[i]
                            if len(line_content) > 200:
                                line_content = line_content[:200] + "... [截断]"
                            output.append(f"    {line_prefix}{i + 1}: {line_content}")

            else:
                # 没有脚本信息的监听器组
                output.append(f"📍 无脚本信息监听器组 #{group_count}")
                output.append("=" * 50)
                output.append(f"🎯 事件类型: {', '.join(event_types)} ({len(event_types)}个)")
                output.append(f"🔗 绑定节点: {', '.join(map(str, node_ids))} ({len(node_ids)}个节点)")

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

    async def inject_javascript_file(self, file_path_or_code: str) -> bool:
        """注入JavaScript代码到当前页面

        Args:
            file_path_or_code: JavaScript文件路径或直接的JavaScript代码字符串

        Returns:
            bool: 注入是否成功
        """
        try:
            # 判断是文件路径还是代码字符串
            if "\n" not in file_path_or_code and len(file_path_or_code) < 1000:
                # 可能是文件路径，尝试读取
                try:
                    import os

                    if os.path.isfile(file_path_or_code):
                        with open(file_path_or_code, "r", encoding="utf-8") as f:
                            js_code = f.read()
                        print(f"✅ 从文件加载JavaScript代码: {file_path_or_code}")
                    else:
                        # 不是有效文件路径，当作代码字符串处理
                        js_code = file_path_or_code
                except Exception:
                    # 读取文件失败，当作代码字符串处理
                    js_code = file_path_or_code
            else:
                # 直接是代码字符串
                js_code = file_path_or_code

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
        # 首先注入JavaScript代码 - 读取外部文件内容
        js_file_path = "/Users/richard/code/terminal-llm/chrome-context-tracer/mouse_element_detector.js"
        try:
            with open(js_file_path, "r", encoding="utf-8") as f:
                js_code = f.read()
            print(f"✅ 从文件加载JavaScript代码: {js_file_path}")
        except Exception as e:
            print(f"❌ 无法读取JavaScript文件: {e}")
            return None

        if not await self.inject_javascript_file(js_code):
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

    async def _handle_element_selection_console(self, console_data: Dict):
        """处理元素选择过程中的控制台消息"""
        try:
            message_text = console_data.get("message", "")

            if "[CHROME_TRACER_SELECTED]" in message_text:
                # 提取JSON数据部分
                json_start = message_text.find("{")
                if json_start != -1:
                    json_str = message_text[json_start:]
                    try:
                        element_data = json.loads(json_str)
                        self.element_selection_result = element_data
                        print(
                            f"✅ 已选择元素: {element_data.get('tagName', 'Unknown')} - {element_data.get('path', 'No path')}"
                        )
                    except json.JSONDecodeError:
                        print("❌ 解析选择的元素数据失败")

            elif "[CHROME_TRACER_CANCELLED]" in message_text:
                print("🚫 用户取消了元素选择")
                self.element_selection_result = "cancelled"

            elif "[CHROME_TRACER_STARTED]" in message_text:
                print("🚀 元素选择模式已激活")

            elif "[CHROME_TRACER_STOPPED]" in message_text:
                print("🛑 元素选择模式已停止")

        except Exception as e:
            print(f"❌ 处理元素选择控制台消息时发生错误: {e}")

    async def close(self):
        """关闭连接"""
        # 停止控制台监听
        await self.stop_console_listening()

        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

    async def start_console_listening(self, message_handler=None):
        """开始监听控制台消息"""
        if self.console_listening:
            print("控制台监听已启动")
            return

        self.console_message_handler = message_handler
        self.console_listening = True

        # 启用控制台域
        try:
            await self.send_command("Console.enable")
            print("✅ 控制台监听已启用")
        except Exception as e:
            print(f"❌ 启用控制台监听失败: {e}")
            self.console_listening = False
            return

        # 控制台监听已通过统一的消息处理机制实现

    async def stop_console_listening(self):
        """停止监听控制台消息"""
        if not self.console_listening:
            return

        self.console_listening = False

        # 禁用控制台域
        try:
            await self.send_command("Console.disable")
            print("✅ 控制台监听已禁用")
        except Exception as e:
            print(f"❌ 禁用控制台监听失败: {e}")

    async def _console_message_loop(self):
        """控制台消息监听循环"""
        while self.console_listening and self.ws and not self.ws.closed:
            try:
                async for msg in self.ws:
                    if not self.console_listening:
                        break

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        message = json.loads(msg.data)

                        # 处理控制台消息事件
                        if message.get("method") == "Runtime.consoleAPICalled":
                            await self._handle_console_api_called(message.get("params", {}))

                        # 处理控制台消息事件（Console.messageAdded）
                        elif message.get("method") == "Console.messageAdded":
                            await self._handle_console_message_added(message.get("params", {}))

            except Exception as e:
                if self.console_listening:
                    print(f"控制台消息监听错误: {e}")
                    await asyncio.sleep(1)  # 错误后等待1秒再重试

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

            # 连接后等待一下再查找标签页
            await asyncio.sleep(1)

            # 使用已修复的方法查找标签页
            target_id = await inspector.find_tab_by_url(url_pattern)
            if target_id:
                # 获取所有目标信息以找到匹配的标签页详情
                response = await inspector.send_command("Target.getTargets")
                targets = response.get("result", {}).get("targetInfos", [])

                for target in targets:
                    if target["targetId"] == target_id:
                        matched_tab = target
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
