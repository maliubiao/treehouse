from rich.panel import Panel
from rich.syntax import Syntax

from ..utils import _validate_args
from . import LSPCommandPlugin


class DefinitionPlugin(LSPCommandPlugin):
    command_name = "definition"
    command_params = ["file_path", "line", "character"]
    description = "获取符号定义位置"

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

        result = await lsp_client.get_definition(file_path, line, char)
        if result:
            console.print(
                Panel(
                    Syntax(str(result), "json"),
                    title="定义结果",
                    border_style="blue",
                )
            )
