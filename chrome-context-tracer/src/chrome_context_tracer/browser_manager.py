import asyncio
import os
import platform
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp

from .cdp_client import DOMInspector
from .i18n import _


async def _get_browser_tabs_info(port: int = 9222) -> List[Dict[str, Any]]:
    """获取所有可用浏览器标签页的详细信息。"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"http://localhost:{port}/json") as response:
                if response.status == 200:
                    return await response.json()
                return []
        except aiohttp.ClientConnectorError:
            # This is expected if the browser is not running
            return []
        except Exception:
            return []


async def find_chrome_tabs(port: int = 9222, auto_launch: bool = True) -> List[str]:
    """查找所有浏览器标签页的WebSocket URL（Chrome/Edge），支持自动启动浏览器"""
    tabs_info = await _get_browser_tabs_info(port)

    if tabs_info:
        return [tab["webSocketDebuggerUrl"] for tab in tabs_info if tab.get("webSocketDebuggerUrl")]

    if auto_launch:
        print(_("Could not connect to browser DevTools on port {port}, trying to launch automatically...", port=port))

        # 尝试启动Chrome
        success, _ = await launch_browser_with_debugging("chrome", port, return_process_info=True)
        if success:
            print(_("Chrome browser launched, waiting for connection..."))
            await asyncio.sleep(5)  # 等待浏览器完全启动

            # 重试连接
            tabs_info_retry = await _get_browser_tabs_info(port)
            if tabs_info_retry:
                return [tab["webSocketDebuggerUrl"] for tab in tabs_info_retry if tab.get("webSocketDebuggerUrl")]
            else:
                print(_("Failed to reconnect."))
        else:
            print(_("Failed to launch browser automatically."))

    return []


class BrowserContextManager:
    """
    智能浏览器上下文管理器。
    - 如果指定端口上已有浏览器运行，则复用它。
    - 如果没有，则启动一个新实例。
    - 支持在复用的浏览器中打开和关闭临时测试标签页。
    - `auto_cleanup` 会清理此管理器创建的所有资源（新浏览器实例或新标签页）。
    """

    def __init__(
        self,
        browser_type: str = "chrome",
        port: int = 9222,
        auto_cleanup: bool = True,
        start_url: Optional[str] = None,
    ):
        self.browser_type = browser_type
        self.port = port
        self.auto_cleanup = auto_cleanup
        self.start_url = start_url
        self.browser_process: Optional[Dict[str, Any]] = None
        self.websocket_urls: List[str] = []
        self._browser_launched = False
        self._user_data_dir: Optional[str] = None
        self._newly_created_target_id: Optional[str] = None

    async def __aenter__(self) -> "BrowserContextManager":
        """进入上下文，启动或连接浏览器。"""
        cleanup_mode = _("Automatic") if self.auto_cleanup else _("Manual")
        print(
            _(
                "🚀 Initializing browser context (Port: {port}, Cleanup: {cleanup_mode})",
                port=self.port,
                cleanup_mode=cleanup_mode,
            )
        )

        existing_tabs = await _get_browser_tabs_info(self.port)

        if existing_tabs:
            print(_("ℹ️  Detected running browser instance on port {port}.", port=self.port))
            self._browser_launched = False

            if self.start_url:
                await self._create_tab_in_existing_browser(existing_tabs)
            else:
                self.websocket_urls = [
                    tab["webSocketDebuggerUrl"] for tab in existing_tabs if tab.get("webSocketDebuggerUrl")
                ]
        else:
            print(_("ℹ️  No browser instance found on port {port}, launching a new one.", port=self.port))
            await self._launch_new_browser()

        if not self.websocket_urls:
            raise RuntimeError(_("Failed to get any available browser WebSocket URL."))

        print(_("✅ Browser context ready. Target: {url}", url=self.get_main_websocket_url()))
        return self

    async def _create_tab_in_existing_browser(self, existing_tabs: List[Dict[str, Any]]) -> None:
        """在现有浏览器实例中创建一个新标签页。"""
        print(_("   - Opening new tab with URL: {start_url}", start_url=self.start_url))
        # 使用第一个可用的标签页的WebSocket来发送浏览器级命令
        browser_ws_url = next(
            (tab["webSocketDebuggerUrl"] for tab in existing_tabs if tab.get("webSocketDebuggerUrl")), None
        )
        if not browser_ws_url:
            raise RuntimeError(_("Could not find an available WebSocket connection in the existing browser."))

        temp_inspector = DOMInspector(browser_ws_url)
        await temp_inspector.connect()
        try:
            # 创建新目标（标签页），并确保它在前台打开
            response = await temp_inspector.send_command(
                "Target.createTarget",
                {"url": self.start_url or "about:blank", "inBackground": False},
                use_session=False,
            )
            self._newly_created_target_id = response.get("result", {}).get("targetId")
            if not self._newly_created_target_id:
                raise RuntimeError(_("Failed to create new tab: {error}", error=response.get("error")))

            print(
                _(
                    "   - New tab created (TargetID: {target_id}), waiting for WebSocket connection info...",
                    target_id=self._newly_created_target_id,
                )
            )

            # 轮询以获取新标签页的 WebSocket URL
            new_tab_ws_url = await self._poll_for_new_tab_ws_url(self._newly_created_target_id)
            self.websocket_urls = [new_tab_ws_url]

        finally:
            await temp_inspector.close()

    async def _poll_for_new_tab_ws_url(self, target_id: str, timeout: float = 10.0) -> str:
        """轮询 /json 端点以查找新创建的标签页的 WebSocket URL。"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            all_tabs = await _get_browser_tabs_info(self.port)
            new_tab_info = next((tab for tab in all_tabs if tab.get("id") == target_id), None)
            if new_tab_info and "webSocketDebuggerUrl" in new_tab_info:
                print(_("   - Successfully retrieved WebSocket URL for the new tab."))
                return new_tab_info["webSocketDebuggerUrl"]
            await asyncio.sleep(0.5)
        raise RuntimeError(
            _(
                "Failed to find new tab with TargetID {target_id} within {timeout} seconds.",
                target_id=target_id,
                timeout=timeout,
            )
        )

    async def _launch_new_browser(self) -> None:
        """启动一个全新的浏览器实例。"""
        self._browser_launched = True
        result = await launch_browser_with_debugging(
            self.browser_type, self.port, return_process_info=True, start_url=self.start_url or "about:blank"
        )
        success, process_info = result if isinstance(result, tuple) else (result, None)

        if not success or not process_info:
            raise RuntimeError(_("Failed to launch {browser_type} for testing.", browser_type=self.browser_type))

        self.browser_process = process_info
        self._user_data_dir = process_info.get("user_data_dir")
        print(_("✅ New browser instance started (PID: {pid})", pid=self.browser_process.get("pid")))

        await asyncio.sleep(2)  # 等待浏览器稳定

        all_tabs = await _get_browser_tabs_info(self.port)
        if not all_tabs:
            raise RuntimeError(_("Browser started, but no tabs could be found."))

        if self.start_url:
            target_tab = next((tab for tab in all_tabs if tab.get("url") == self.start_url), all_tabs[0])
        else:
            target_tab = all_tabs[0]

        self.websocket_urls = [target_tab["webSocketDebuggerUrl"]]

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出上下文，根据模式决定清理范围。"""
        if self.auto_cleanup:
            if self._browser_launched and self.browser_process:
                print(
                    _(
                        "🧹 Auto-cleanup: Closing launched browser process (PID: {pid})...",
                        pid=self.browser_process.get("pid"),
                    )
                )
                await cleanup_browser(self.browser_process)
                if self._user_data_dir:
                    await cleanup_temp_directory(self._user_data_dir)
            elif self._newly_created_target_id:
                print(
                    _(
                        "🧹 Auto-cleanup: Closing created tab (TargetID: {target_id})...",
                        target_id=self._newly_created_target_id,
                    )
                )
                try:
                    await self._close_tab(self._newly_created_target_id)
                except Exception as e:
                    print(_("⚠️  Warning: Error closing tab: {e}", e=e))
            else:
                print(_("ℹ️  No auto-cleanup needed."))
        else:
            print(_("💾 Preserving browser state (manual cleanup mode)."))

    async def _close_tab(self, target_id: str) -> None:
        """连接到浏览器并关闭指定的标签页。"""
        tabs_info = await _get_browser_tabs_info(self.port)
        if not tabs_info:
            print(_("   - Could not connect to browser to close tab."))
            return

        browser_ws_url = tabs_info[0]["webSocketDebuggerUrl"]
        temp_inspector = DOMInspector(browser_ws_url)
        await temp_inspector.connect()
        try:
            await temp_inspector.send_command("Target.closeTarget", {"targetId": target_id}, use_session=False)
            print(_("   - Close tab command sent."))
        finally:
            await temp_inspector.close()

    def get_websocket_urls(self) -> List[str]:
        """获取WebSocket URL列表"""
        return self.websocket_urls

    def get_main_websocket_url(self) -> Optional[str]:
        """获取主WebSocket URL"""
        return self.websocket_urls[0] if self.websocket_urls else None


async def launch_browser_with_debugging(
    browser_type: str = "chrome",
    port: int = 9222,
    user_data_dir: Optional[str] = None,
    return_process_info: bool = False,
    start_url: Optional[str] = None,
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
        # 在临时目录中创建子目录，以避免权限问题和文件名过长
        temp_dir_base = tempfile.gettempdir()
        user_data_dir = tempfile.mkdtemp(prefix="chrome_profile_", dir=temp_dir_base)

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
                "chrome": ["Google Chrome", "Chrome"],
                "edge": ["Microsoft Edge", "Edge"],
            }

            browser_launched = False

            for chrome_name in browser_names.get(browser_type.lower(), []):
                try:
                    cmd = ["open", "-n", "-a", chrome_name]
                    if start_url:
                        cmd.append(start_url)
                    cmd.extend(
                        [
                            "--args",
                            f"--remote-debugging-port={port}",
                            f"--user-data-dir={user_data_dir}",
                            "--no-first-run",
                            "--no-default-browser-check",
                        ]
                    )
                    process_info["command"] = " ".join(cmd)
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(2)

                    # 使用重试循环来可靠地找到进程PID
                    for _ in range(10):  # 重试5秒
                        try:
                            pgrep_result = subprocess.run(
                                ["pgrep", "-f", f"user-data-dir={user_data_dir}"],
                                capture_output=True,
                                text=True,
                                check=True,
                            )
                            pids = pgrep_result.stdout.strip().split("\n")
                            if pids and pids[0]:
                                process_info["pid"] = int(pids[0])
                                browser_launched = True
                                break  # 成功找到PID，跳出重试循环
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            await asyncio.sleep(0.5)  # 等待并重试

                    if browser_launched:
                        break  # 成功启动，跳出浏览器名称循环
                except (FileNotFoundError, OSError):
                    continue

            if not browser_launched:
                print(
                    _(
                        "Could not find or launch {browser_type}. Please ensure it is installed.",
                        browser_type=browser_type,
                    )
                )
                if return_process_info:
                    return False, process_info
                return False

        elif system == "Windows":
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
            if start_url:
                cmd.append(start_url)
            process_info["command"] = " ".join(cmd)
            process = subprocess.Popen(cmd)
            process_info["pid"] = process.pid

        elif system == "Linux":
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
                "--no-sandbox",
            ]
            if start_url:
                cmd.append(start_url)
            process_info["command"] = " ".join(cmd)
            process = subprocess.Popen(cmd)
            process_info["pid"] = process.pid

        else:
            if return_process_info:
                return False, process_info
            return False

        print(_("Launching browser with temporary profile: {user_data_dir}", user_data_dir=user_data_dir))
        await asyncio.sleep(2)

        if return_process_info:
            return True, process_info
        return True

    except Exception as e:
        print(_("Failed to launch browser: {e}", e=e))
        await cleanup_temp_directory(user_data_dir)
        if return_process_info:
            return False, process_info
        return False


async def cleanup_browser(process_info: dict):
    """清理浏览器进程"""
    import os
    import platform
    import signal
    import subprocess

    if not process_info:
        return

    system = platform.system()
    pid = process_info.get("pid")

    if not pid:
        print(_("⚠️  Warning: Failed to clean up browser, process PID not found."))
        return

    print(_("🧹 Cleaning up browser process (PID: {pid})", pid=pid))

    try:
        if system in ["Darwin", "Linux"]:
            os.kill(pid, signal.SIGTERM)  # 先尝试优雅关闭
            await asyncio.sleep(1)
            try:
                os.kill(pid, 0)
                print(_("Process {pid} did not exit gracefully, forcing termination...", pid=pid))
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass  # 进程已退出
        elif system == "Windows":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        print(_("✅ Browser process {pid} cleaned up.", pid=pid))
    except Exception as e:
        print(_("Error cleaning up browser process: {e}", e=e))


async def cleanup_temp_directory(user_data_dir: Optional[str]):
    """清理临时目录"""
    import shutil

    if user_data_dir and os.path.exists(user_data_dir):
        try:
            # 使用 ignore_errors=True 增加删除的鲁棒性
            shutil.rmtree(user_data_dir, ignore_errors=True)
            print(_("✅ Cleaned up temporary profile directory: {user_data_dir}", user_data_dir=user_data_dir))
        except Exception as e:
            print(_("Failed to clean up temporary directory: {e}", e=e))


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
        print(_("Failed to get browser process info: {e}", e=e))

    return processes
