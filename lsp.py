import argparse
import asyncio
import atexit
import json
import os
import pdb
import subprocess
import threading
from logging import getLogger

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

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
            self.process = subprocess.Popen(
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

            # 启动响应读取线程
            threading.Thread(target=self._read_responses, daemon=True).start()

            # 发送初始化请求
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
                # 读取头部信息
                headers = {}
                while True:
                    line = self.stdout.readline().strip()
                    if not line:  # 遇到空行表示头部结束
                        break
                    if ": " in line:  # 确保是有效的头部字段
                        name, value = line.split(": ", 1)
                        headers[name.lower()] = value

                # 检查必须的Content-Length字段
                if "content-length" not in headers:
                    break
                # 读取消息体
                content_length = int(headers["content-length"])
                content = self.stdout.read(content_length)
                try:
                    # 处理消息体
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
            # 发送shutdown请求并等待响应
            await self.send_request("shutdown", None)
            self.send_notification("exit", None)

            # 等待进程结束
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

        # 关闭管道
        for pipe in [self.stdin, self.stdout, self.process.stderr if self.process else None]:
            try:
                if pipe:
                    pipe.close()
            except (OSError, RuntimeError) as e:
                logger.debug("Error closing pipe: %s", str(e))

        # 清理未完成的future
        with self._lock:
            for future in self.response_futures.values():
                if not future.done():
                    future.get_loop().call_soon_threadsafe(
                        future.set_exception, asyncio.CancelledError("LSP client shutdown")
                    )
            self.response_futures.clear()

    # 以下是通用LSP方法
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
                    "position": {"line": line - 1, "character": character},  # LSP使用0-based索引
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

    async def get_definition(self, file_path, line, character):
        """获取符号定义位置及源码信息"""
        try:
            definition = await self.send_request(
                "textDocument/definition",
                {
                    "textDocument": {"uri": f"file://{file_path}"},
                    "position": {"line": line - 1, "character": character},  # LSP使用0-based索引
                },
            )

            if not definition:
                return None

            # 处理多位置情况（如重载函数）
            locations = definition if isinstance(definition, list) else [definition]
            results = []

            for loc in locations:
                # 解析定义位置
                uri = loc["uri"].replace("file://", "", 1)
                start_line = loc["range"]["start"]["line"] + 1  # 转回1-based
                start_char = loc["range"]["start"]["character"]

                # 读取定义文件内容
                try:
                    with open(uri, "r") as f:
                        lines = f.readlines()
                        # 提取完整符号定义范围（示例取前后5行）
                        context = "".join(lines[max(0, start_line - 2) : start_line + 3])
                except Exception as e:
                    logger.debug(f"Failed to read source: {str(e)}")
                    context = ""

                results.append(
                    {"file_path": uri, "line": start_line, "character": start_char, "source_context": context.strip()}
                )

            return results[0] if len(results) == 1 else results

        except Exception as e:
            logger.error(f"Failed to get definition: {str(e)}")
            return None


class LSPCompleter(Completer):
    def __init__(self, lsp_client):
        self.lsp_client = lsp_client
        self.commands = {
            "definition": ["file_path", "line", "character"],
            "hover": ["file_path", "line", "character"],
            "completion": ["file_path", "line", "character"],
            "symbols": ["file_path"],
        }

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.split()
        if len(text) == 0:
            return

        # 命令补全
        if len(text) == 1:
            for cmd in self.commands:
                if cmd.startswith(text[0].lower()):
                    yield Completion(
                        cmd, start_position=-len(text[0]), display_meta=f"参数: {' '.join(self.commands[cmd])}"
                    )
            return

        # 参数值补全
        cmd = text[0].lower()
        if cmd not in self.commands:
            return

        param_index = len(text) - 2
        if param_index >= len(self.commands[cmd]):
            return

        param_name = self.commands[cmd][param_index]

        # 文件路径补全
        if param_name == "file_path":
            cwd = os.getcwd()
            for f in os.listdir(cwd):
                if f.startswith(text[-1]):
                    yield Completion(
                        f, start_position=-len(text[-1]), display_meta="文件" if os.path.isfile(f) else "目录"
                    )


def format_completion_item(item):
    """格式化补全项为完整信息"""
    return {
        "label": item.get("label"),
        "kind": item.get("kind"),
        "detail": item.get("detail") or "",
        "documentation": item.get("documentation") or "",
        "parameters": item.get("parameters", []),
        "text_edit": item.get("textEdit"),
    }


async def debug_console(lsp_client):
    """启动交互式调试控制台"""

    console = Console()
    session = PromptSession(
        history=FileHistory(".lsp_debug_history"),
        auto_suggest=AutoSuggestFromHistory(),
        completer=LSPCompleter(lsp_client),
    )

    help_text = """\n可用命令：
    definition <file_path> <line> <character>  获取符号定义
    hover <file_path> <line> <character>       获取悬停信息
    symbols <file_path>                        获取文档符号
    completion <file_path> <line> <character>  获取代码补全
    exit                                       退出
    """

    console.print(Panel(Text("LSP 调试控制台", style="bold blue"), width=80))
    console.print(Panel(help_text, title="帮助", border_style="green"))

    while True:
        try:
            text = await session.prompt_async("LSP> ")
            parts = text.strip().split()
            if not parts:
                continue

            cmd = parts[0].lower()

            if cmd == "exit":
                await lsp_client.shutdown()
                break

            elif cmd == "help":
                console.print(Panel(help_text, title="帮助", border_style="green"))

            elif cmd in ("definition", "hover", "completion"):
                if len(parts) != 4:
                    console.print("[red]参数错误，需要: <file_path> <line> <character>[/red]")
                    continue

                _, file_path, line, char = parts
                try:
                    line = int(line)
                    char = int(char)
                except ValueError:
                    console.print("[red]行号和列号必须是数字[/red]")
                    continue

                method = {
                    "definition": lsp_client.get_definition,
                    "hover": lsp_client.get_hover_info,
                    "completion": lsp_client.get_completion,
                }[cmd]

                result = await method(file_path, line, char)
                if cmd == "completion" and isinstance(result, dict):
                    items = result.get("items", [])
                    formatted = [format_completion_item(item) for item in items]

                    table = Table(title="补全建议", show_header=True, header_style="bold magenta")
                    table.add_column("标签", style="cyan")
                    table.add_column("类型", style="green")
                    table.add_column("详情")
                    table.add_column("文档")

                    for item in formatted:
                        table.add_row(item["label"], str(item["kind"]), item["detail"], item["documentation"])
                    console.print(table)
                else:
                    console.print(
                        Panel(
                            Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"),
                            title="结果",
                            border_style="blue",
                        )
                    )

            elif cmd == "symbols":
                if len(parts) != 2:
                    console.print("[red]参数错误，需要: <file_path>[/red]")
                    continue

                result = await lsp_client.get_document_symbols(parts[1])
                console.print(
                    Panel(
                        Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"),
                        title="文档符号",
                        border_style="yellow",
                    )
                )

            else:
                console.print(f"[red]未知命令: {cmd}，输入help查看帮助[/red]")

        except (KeyboardInterrupt, EOFError):
            await lsp_client.shutdown()
            break
        except Exception as e:
            console.print(f"[red]错误: {str(e)}[/red]")


def main():
    parser = argparse.ArgumentParser(description="LSP调试工具")
    parser.add_argument("--lsp", required=True, help="LSP服务器启动命令，例如：pylsp")
    parser.add_argument("--workspace", default=".", help="工作区路径（默认当前目录）")
    args = parser.parse_args()

    lsp_client = GenericLSPClient(lsp_command=args.lsp.split(), workspace_path=args.workspace)
    lsp_client.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(debug_console(lsp_client))
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(lsp_client.shutdown())
        loop.close()


if __name__ == "__main__":
    main()
