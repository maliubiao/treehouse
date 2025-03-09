import os
from urllib.parse import unquote, urlparse

from rich.syntax import Syntax

from .. import GenericLSPClient
from ..utils import _validate_args
from . import LSPCommandPlugin, build_hierarchy_tree, format_response_panel


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

        if not result:
            console.print("[yellow]未找到定义位置[/yellow]")
            return

        if isinstance(result, list):
            tree = build_hierarchy_tree(
                "📌 找到多个定义位置", result, DefinitionPlugin._build_definition_node, lsp_client
            )
            console.print(tree)
        else:
            console.print(format_response_panel(result, "定义位置", "green", syntax="json", line_numbers=True))

    @staticmethod
    def _build_definition_node(tree, definition, _):
        uri = urlparse(definition.get("uri")).path
        path = unquote(uri) if uri else "未知文件"
        range_info = definition.get("range", {})
        start = range_info.get("start", {})
        end = range_info.get("end", {})

        location = (
            f"[文件] {os.path.basename(path)}\n"
            f"[路径] {path}\n"
            f"行: {start.get('line', 0)+1} 列: {start.get('character', 0)}"
            f" → 行: {end.get('line', 0)+1} 列: {end.get('character', 0)}"
        )

        tree.add(Syntax(location, "json", theme="monokai", line_numbers=False, word_wrap=True))

    def __str__(self):
        return f"{self.command_name}: {self.description}"
