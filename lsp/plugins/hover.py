import json

from rich.panel import Panel
from rich.syntax import Syntax

from ..utils import _validate_args
from . import LSPCommandPlugin


class HoverPlugin(LSPCommandPlugin):
    command_name = "hover"
    command_params = ["file_path", "line", "character"]
    description = "获取悬停信息"

    @staticmethod
    async def handle_command(console, lsp_client, parts):
        if not _validate_args(console, parts, 4):
            return
        _, file_path, line, char = parts
        try:
            line = int(line)
            char = int(char)
        except ValueError:
            console.print("[red]行号和列号必须是数字[/red]")
            return

        result = await lsp_client.get_hover_info(file_path, line, char)
        if result:
            console.print(
                Panel(
                    Syntax(json.dumps(result, indent=2, ensure_ascii=False), "json"),
                    title="悬停信息",
                    border_style="green",
                )
            )
