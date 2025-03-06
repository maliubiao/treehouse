# 包初始化文件
import os
from typing import Callable, Dict, List, Optional, Type

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
        return {cmd: {"params": cls.command_params, "desc": cls.description} for cmd, cls in self._command_map.items()}

    def get_command_handler(self, command: str) -> Optional[Callable]:
        """获取命令处理函数"""
        self._ensure_plugins_loaded()
        cls = self._command_map.get(command.lower())
        return cls.handle_command if cls else None
