import asyncio
from logging import getLogger

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from lsp.completer import LSPCompleter
from lsp.plugins import PluginManager
from lsp.utils import _dispatch_command

logger = getLogger(__name__)


async def debug_console(lsp_client):
    console = Console()
    plugin_manager = PluginManager()
    session = PromptSession(
        history=FileHistory(".lsp_debug_history"),
        auto_suggest=AutoSuggestFromHistory(),
        completer=LSPCompleter(plugin_manager),
    )

    commands_meta = plugin_manager.get_commands_meta()
    help_lines = ["\n可用命令："]
    for cmd, meta in commands_meta.items():
        params = " ".join(meta["params"])
        help_lines.append(f"    {cmd} {params.ljust(30)} {meta['desc']}")
    help_lines.extend(
        [
            "    exit                                       退出",
            "    help                                       显示帮助信息",
        ]
    )
    help_text = "\n".join(help_lines)

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

            if cmd == "help":
                console.print(Panel(help_text, title="帮助", border_style="green"))
                continue

            handled = await _dispatch_command(console, lsp_client, plugin_manager, text)
            if not handled:
                console.print(f"[red]未知命令: {cmd}，输入help查看帮助[/red]")

        except (KeyboardInterrupt, EOFError):
            await lsp_client.shutdown()
            break
        except (RuntimeError, OSError) as e:
            console.print(f"[red]错误: {str(e)}[/red]")
