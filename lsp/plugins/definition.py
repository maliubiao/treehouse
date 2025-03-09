import os

from .. import GenericLSPClient
from ..utils import _create_json_table, _create_symbol_table, _validate_args
from . import LSPCommandPlugin, format_response_panel


class DefinitionPlugin(LSPCommandPlugin):
    command_name = "definition"
    command_params = ["file_path", "line", "character"]
    description = "获取符号定义位置"

    @staticmethod
    async def handle_command(console, lsp_client: GenericLSPClient, parts):
        if not _validate_args(console, parts, 4):
            return
        _, file_path, line, char = parts
        try:
            line = int(line)
            char = int(char)
        except ValueError:
            console.print("[red]行号和列号必须是数字[/red]")
            return

        abs_file_path = os.path.abspath(file_path)
        result = await lsp_client.get_definition(abs_file_path, line, char)
        if result:
            if isinstance(result, list):
                table = _create_symbol_table(result)
                console.print(table)
            else:
                table = _create_json_table(result)
                console.print(table)

    def __str__(self):
        return f"{self.command_name}: {self.description}"
