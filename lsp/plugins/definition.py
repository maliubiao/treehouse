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

        validation_result = DefinitionPlugin._validate_and_parse_arguments(console, line, char)
        if not validation_result:
            return
        line_num, char_num = validation_result

        abs_file_path = os.path.abspath(file_path)
        result = await lsp_client.get_definition(abs_file_path, line_num, char_num)

        DefinitionPlugin._handle_definition_result(console, lsp_client, result)

    @staticmethod
    def _validate_and_parse_arguments(console, line, char):
        try:
            return int(line), int(char)
        except ValueError:
            console.print("[red]行号和列号必须是数字[/red]")
            return None

    @staticmethod
    def _handle_definition_result(console, lsp_client, result):
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
    def _build_definition_node(tree, definition, lsp_client):
        path = DefinitionPlugin._get_definition_path(definition)
        range_info = definition.get("range", {})
        code_snippet = DefinitionPlugin._read_code_snippet(path, range_info)
        location = DefinitionPlugin._build_location_info(path, range_info, code_snippet)

        tree.add(Syntax(location, "python", theme="monokai", line_numbers=False, word_wrap=True))

    @staticmethod
    def _get_definition_path(definition):
        uri = urlparse(definition.get("uri")).path
        return unquote(uri) if uri else "未知文件"

    @staticmethod
    def _read_code_snippet(path, range_info):
        if not os.path.exists(path):
            return ""

        try:
            with open(path, "rb") as f:
                lines = f.readlines()
                start_line = range_info.get("start", {}).get("line", 0)
                end_line = range_info.get("end", {}).get("line", start_line)
                return b"".join(lines[start_line : end_line + 1]).decode("utf-8", errors="replace")
        except Exception as e:
            return f"\n[red]无法读取源代码: {str(e)}[/red]"

    @staticmethod
    def _build_location_info(path, range_info, code_snippet):
        start = range_info.get("start", {})
        end = range_info.get("end", {})

        location = (
            f"[文件] {os.path.basename(path)}\n"
            f"[路径] {path}\n"
            f"行: {start.get('line', 0)+1} 列: {start.get('character', 0)}"
            f" → 行: {end.get('line', 0)+1} 列: {end.get('character', 0)}"
        )

        if code_snippet:
            location += f"\n[代码片段]\n{code_snippet}"

        return location

    def __str__(self):
        return f"{self.command_name}: {self.description}"
