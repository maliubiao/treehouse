# 包初始化文件
import os
from typing import Callable, Dict, List, Optional, Type
from urllib.parse import unquote, urlparse

from rich.panel import Panel
from rich.syntax import Syntax
from rich.tree import Tree

# 自动导入所有子模块
__all__ = []


def load_submodules():
    _pkg_dir = os.path.dirname(__file__)
    for _file in os.listdir(_pkg_dir):
        if _file.endswith(".py") and not _file.startswith("__"):
            _module_name = os.path.splitext(_file)[0]
            __all__.append(_module_name)
            __import__(f"{__package__}.{_module_name}", fromlist=[""])


class LSPCommandPlugin:
    """LSP命令插件基类"""

    command_name: str = ""
    command_params: List[str] = []
    description: str = ""

    @staticmethod
    async def handle_command(console, lsp_client, parts: List[str]):
        """命令处理方法"""
        raise NotImplementedError("子类必须实现handle_command方法")

    def __str__(self):
        return f"{self.command_name}: {self.description}"


class PluginManager:
    """插件管理器"""

    def __init__(self):
        self._command_map: Dict[str, Type[LSPCommandPlugin]] = {}
        self._plugins_loaded = False

    def _discover_plugins(self):
        """自动发现所有插件"""
        load_submodules()
        for plugin_class in LSPCommandPlugin.__subclasses__():
            if plugin_class.command_name:
                self._command_map[plugin_class.command_name.lower()] = plugin_class
        self._plugins_loaded = True

    def _ensure_plugins_loaded(self):
        """确保插件已加载"""
        if not self._plugins_loaded:
            self._discover_plugins()

    def get_commands_meta(self) -> Dict[str, dict]:
        """获取所有命令元数据"""
        self._ensure_plugins_loaded()
        return {
            cmd: {"params": cls.command_params, "desc": cls.description}
            for cmd, cls in self._command_map.items()
        }

    def get_command_handler(self, command: str) -> Optional[Callable]:
        """获取命令处理函数"""
        self._ensure_plugins_loaded()
        cls = self._command_map.get(command.lower())
        return cls.handle_command if cls else None


def parse_position_args(console, parts):
    """解析位置参数（文件路径、行号、列号）"""
    if len(parts) != 4:
        console.print("[red]参数错误，需要3个参数：文件路径 行号 列号[/red]")
        return None, None, None

    try:
        line = int(parts[2])
        char = int(parts[3])
        return parts[1], line, char
    except ValueError:
        console.print("[red]行号和列号必须是数字[/red]")
        return None, None, None


def format_response_panel(
    response, title, border_style="blue", syntax="json", line_numbers=False
):
    """格式化响应面板"""
    return Panel(
        Syntax(
            str(response),
            syntax,
            theme="monokai",
            line_numbers=line_numbers,
            word_wrap=True,
        ),
        title=title,
        border_style=border_style,
        expand=False,
    )


def build_hierarchy_tree(title, items, build_func, lsp_client):
    """构建层次结构树"""
    tree = Tree(title, highlight=True, guide_style="dim")
    for item in items:
        build_func(tree, item, lsp_client)
    return tree
