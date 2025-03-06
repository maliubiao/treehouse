from rich.panel import Panel
from rich.tree import Tree

from ..utils import (
    _build_symbol_tree,
    _create_symbol_table,
    _validate_args,
)
from . import LSPCommandPlugin


class SymbolsPlugin(LSPCommandPlugin):
    command_name = "symbols"
    command_params = ["file_path"]
    description = "获取文档符号列表"

    @staticmethod
    async def handle_command(console, lsp_client, parts):
        if not _validate_args(console, parts, 2):
            return
        result = await lsp_client.get_document_symbols(parts[1])
        if not result:
            console.print("[yellow]没有找到文档符号[/yellow]")
            return

        if isinstance(result, list) and len(result) > 0:
            if "location" in result[0]:
                console.print(_create_symbol_table(result))
            else:
                tree = Tree("文档符号层次结构", highlight=True)
                for sym in result:
                    _build_symbol_tree(sym, tree)
                console.print(Panel(tree, title="文档符号", border_style="yellow"))
