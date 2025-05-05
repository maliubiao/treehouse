import logging
from pathlib import Path

from rich.console import Console

from .. import GenericLSPClient
from ..utils import _validate_args
from . import LSPCommandPlugin

logger = logging.getLogger(__name__)


class LoadPlugin(LSPCommandPlugin):
    command_name = "load"
    command_params = ["file_path"]
    description = "加载源代码文件到LSP服务器"

    @staticmethod
    async def handle_command(console: Console, lsp_client: GenericLSPClient, parts: list):
        if not _validate_args(console, parts, 2):
            return

        file_path = Path(parts[1]).expanduser().resolve()
        if not file_path.exists():
            console.print(f"[red]文件不存在: {file_path}[/red]")
            return
        if not file_path.is_file():
            console.print(f"[red]路径不是文件: {file_path}[/red]")
            return

        try:
            text = file_path.read_text(encoding="utf-8")
            uri = f"file://{file_path}"

            # 发送textDocument/didOpen通知
            lsp_client.send_notification(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "python",
                        "version": 1,
                        "text": text,
                    }
                },
            )

            # 发送textDocument/didChange通知（全量更新）
            lsp_client.send_notification(
                "textDocument/didChange",
                {"textDocument": {"uri": uri}, "contentChanges": [{"text": text}]},
            )

            console.print(f"[green]成功加载文件: {file_path}[/green]")
            logger.debug("Loaded %s to LSP server", file_path)

        except Exception as e:
            console.print(f"[red]加载文件失败: {str(e)}[/red]")
            logger.exception("Failed to load file %s", file_path)
