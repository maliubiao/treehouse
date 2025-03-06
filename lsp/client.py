import asyncio
import atexit
import json
import os
import subprocess
import threading
from logging import getLogger
from urllib.parse import unquote, urlparse

logger = getLogger(__name__)


class GenericLSPClient:
    def __init__(self, lsp_command, workspace_path, init_params=None):
        self.workspace_path = os.path.abspath(workspace_path)
        self.lsp_command = lsp_command
        self.init_params = init_params or {}
        self.process = None
        self.stdin = None
        self.stdout = None
        self.request_id = 1
        self.response_futures = {}
        self.running = False
        self._lock = threading.Lock()
        atexit.register(self._cleanup)

    def start(self):
        """启动LSP服务器进程"""
        try:
            self.process = subprocess.Popen(  # pylint: disable=consider-using-with
                self.lsp_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.workspace_path,
                bufsize=0,
            )
            self.stdin = self.process.stdin
            self.stdout = self.process.stdout
            self.running = True

            threading.Thread(target=self._read_responses, daemon=True).start()
            self.initialize()

        except (subprocess.SubprocessError, OSError) as e:
            self._cleanup()
            logger.error("Failed to start LSP: %s", str(e))
            raise

    def initialize(self):
        """发送初始化请求"""
        init_params = {
            "processId": os.getpid(),
            "rootUri": f"file://{self.workspace_path}",
            "capabilities": {"textDocument": {"hover": {"contentFormat": ["markdown", "plaintext"]}}},
            **self.init_params,
        }
        self.send_request("initialize", init_params)

    def send_request(self, method, params):
        """发送JSON-RPC请求"""
        with self._lock:
            request_id = self.request_id
            self.request_id += 1

        future = asyncio.get_event_loop().create_future()
        with self._lock:
            self.response_futures[request_id] = future

        request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}

        self._send_message(request)
        return future

    def send_notification(self, method, params):
        """发送JSON-RPC通知"""
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        self._send_message(notification)

    def _send_message(self, message):
        """发送原始消息"""
        try:
            message_str = json.dumps(message)
            content = f"Content-Length: {len(message_str)}\r\n\r\n{message_str}"
            self.stdin.write(content)
            self.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.error("Failed to send message: %s", str(e))
            self._cleanup()

    def _read_responses(self):
        """持续读取服务器响应"""
        try:
            while self.running:
                headers = {}
                while True:
                    line = self.stdout.readline().strip()
                    if not line:
                        break
                    if ": " in line:
                        name, value = line.split(": ", 1)
                        headers[name.lower()] = value

                if "content-length" not in headers:
                    break
                content_length = int(headers["content-length"])
                content = self.stdout.read(content_length)
                try:
                    msg = json.loads(content)
                    print(msg)
                    self._handle_response(msg)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse JSON response: %s", str(e))

        except (OSError, RuntimeError) as e:
            logger.error("Response reading thread crashed: %s", str(e))
            self._cleanup()

    def _handle_response(self, response):
        """处理服务器响应"""
        if "id" in response:
            request_id = response["id"]
            with self._lock:
                future = self.response_futures.pop(request_id, None)
            if future:
                if not future.done():
                    if "result" in response:
                        future.get_loop().call_soon_threadsafe(future.set_result, response["result"])
                    elif "error" in response:
                        future.get_loop().call_soon_threadsafe(
                            future.set_exception, Exception(json.dumps(response["error"]))
                        )
        else:
            logger.debug("Received notification: %s", response.get("method"))

    async def shutdown(self):
        """优雅关闭LSP连接"""
        if not self.running:
            return

        try:
            await self.send_request("shutdown", None)
            self.send_notification("exit", None)

            if self.process:
                await asyncio.get_event_loop().run_in_executor(None, self.process.wait)
        except (OSError, RuntimeError) as e:
            logger.error("Shutdown failed: %s", str(e))
        finally:
            self._cleanup()

    def _cleanup(self):
        """清理资源"""
        self.running = False
        if self.process:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except (OSError, RuntimeError) as e:
                logger.error("Cleanup error: %s", str(e))
            finally:
                self.process = None

        for pipe in [self.stdin, self.stdout, self.process.stderr if self.process else None]:
            try:
                if pipe:
                    pipe.close()
            except (OSError, RuntimeError) as e:
                logger.debug("Error closing pipe: %s", str(e))

        with self._lock:
            for future in self.response_futures.values():
                if not future.done():
                    future.get_loop().call_soon_threadsafe(
                        future.set_exception, asyncio.CancelledError("LSP client shutdown")
                    )
            self.response_futures.clear()

    async def get_document_symbols(self, file_path):
        """获取文档符号"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except IOError as e:
            logger.error("Failed to read file: %s", str(e))
            return None

        self.send_notification(
            "textDocument/didOpen",
            {"textDocument": {"uri": f"file://{file_path}", "languageId": "python", "version": 1, "text": text}},
        )

        try:
            return await self.send_request(
                "textDocument/documentSymbol", {"textDocument": {"uri": f"file://{file_path}"}}
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get document symbols: %s", str(e))
            return None

    async def get_hover_info(self, file_path, line, character):
        """获取悬停信息"""
        try:
            return await self.send_request(
                "textDocument/hover",
                {
                    "textDocument": {"uri": f"file://{file_path}"},
                    "position": {"line": line - 1, "character": character},
                },
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get hover info: %s", str(e))
            return None

    async def get_completion(self, file_path, line, character, context=None):
        """获取代码补全（增强元数据解析）"""
        try:
            return await self.send_request(
                "textDocument/completion",
                {
                    "textDocument": {"uri": f"file://{file_path}"},
                    "position": {"line": line - 1, "character": character},
                    "context": context or {},
                },
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get completion: %s", str(e))
            return None

    async def _read_source_context(self, file_path, start_line):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                return "".join(lines[max(0, start_line - 2) : start_line + 3])
        except (OSError, RuntimeError) as e:
            logger.debug("Failed to read source: %s", str(e))
            return ""

    async def get_definition(self, file_path, line, character):
        """获取符号定义位置及源码信息"""
        try:
            definition = await self.send_request(
                "textDocument/definition",
                {
                    "textDocument": {"uri": f"file://{file_path}"},
                    "position": {"line": line - 1, "character": character},
                },
            )

            if not definition:
                return None

            locations = definition if isinstance(definition, list) else [definition]
            results = []

            for loc in locations:
                parsed_uri = urlparse(loc["uri"])
                file_path = unquote(parsed_uri.path)
                if os.name == "nt" and len(file_path) >= 3 and file_path[0] == "/" and file_path[2] == ":":
                    file_path = file_path[1:]
                file_path = os.path.normpath(file_path)

                start_line = loc["range"]["start"]["line"] + 1
                start_char = loc["range"]["start"]["character"]

                context = await self._read_source_context(file_path, start_line)
                results.append(
                    {
                        "file_path": file_path,
                        "line": start_line,
                        "character": start_char,
                        "source_context": context.strip(),
                    }
                )

            return results[0] if len(results) == 1 else results

        except (OSError, RuntimeError) as e:
            logger.error("Failed to get definition: %s", str(e))
            return None
