from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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
    async def handle_command(console, lsp_client: GenericLSPClient, parts: List[str]):
        if not _validate_args(console, parts, 4):
            return
        _, file_path, line, char = parts

        validation_result = DefinitionPlugin._validate_and_parse_arguments(console, line, char)
        if not validation_result:
            return
        line_num, char_num = validation_result

        abs_file_path = Path(file_path).resolve()
        result = await lsp_client.get_definition(str(abs_file_path), line_num, char_num)

        DefinitionPlugin._handle_definition_result(console, lsp_client, result)

    @staticmethod
    def _validate_and_parse_arguments(console, line: str, char: str) -> Optional[Tuple[int, int]]:
        try:
            line_num = int(line)
            char_num = int(char)
            if line_num < 0 or char_num < 0:
                raise ValueError("Negative value")
            return line_num, char_num
        except ValueError:
            console.print(f"[red]无效的位置参数: 行号({line}) 列号({char}) 必须是自然数[/red]")
            return None

    @staticmethod
    def _handle_definition_result(console, lsp_client: GenericLSPClient, result: Any):
        if not result:
            console.print("[yellow]未找到定义位置[/yellow]")
            return

        if isinstance(result, list):
            tree = build_hierarchy_tree(
                "📌 找到多个定义位置",
                result,
                DefinitionPlugin._build_definition_node,
                lsp_client,
            )
            console.print(tree)
        else:
            console.print(format_response_panel(result, "定义位置", "green", syntax="json", line_numbers=True))

    @staticmethod
    def _build_definition_node(tree, definition: Dict, lsp_client: GenericLSPClient):
        path = DefinitionPlugin._get_definition_path(definition)
        range_info = definition.get("range", {})

        try:
            code_snippet = DefinitionPlugin._read_code_snippet(path, range_info)
            symbol = DefinitionPlugin._extract_symbol(path, range_info)
            location = DefinitionPlugin._build_location_info(path, range_info, code_snippet, symbol)
            tree.add(
                Syntax(
                    location,
                    "python",
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=True,
                )
            )
        except Exception as e:
            tree.add(f"[red]加载定义信息失败: {str(e)}[/red]")

    @staticmethod
    def _get_definition_path(definition: Dict) -> str:
        uri = urlparse(definition.get("uri", "")).path
        return unquote(uri) if uri else "未知文件"

    @staticmethod
    def _read_code_snippet(path: str, range_info: Dict) -> str:
        """读取指定范围的代码片段，带完整错误处理"""
        if not Path(path).exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                start_line = max(0, range_info.get("start", {}).get("line", 0))
                end_line = min(len(lines) - 1, range_info.get("end", {}).get("line", start_line))
                return "".join(lines[start_line : end_line + 1])
        except Exception as e:
            raise RuntimeError(f"读取代码片段失败: {str(e)}") from e

    @staticmethod
    def _extract_symbol(path: str, range_info: Dict) -> str:
        """提取符号名称，改进边界条件处理"""
        if not Path(path).exists():
            return ""

        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                start = range_info.get("start", {})
                line_num = min(max(0, start.get("line", 0)), len(lines) - 1)
                char_num = max(0, start.get("character", 0))

                line_content = lines[line_num]
                if char_num >= len(line_content):
                    return ""

                # 扩展符号识别逻辑
                start_pos = char_num
                while start_pos > 0 and (
                    line_content[start_pos - 1].isidentifier() or line_content[start_pos - 1] == "_"
                ):
                    start_pos -= 1

                end_pos = char_num
                while end_pos < len(line_content) and (
                    line_content[end_pos].isidentifier() or line_content[end_pos] == "_"
                ):
                    end_pos += 1

                return line_content[start_pos:end_pos].strip() or "<无名符号>"
        except Exception as e:
            return f"[符号提取失败: {str(e)}]"

    @staticmethod
    def _build_location_info(path: str, range_info: Dict, code_snippet: str, symbol: str) -> str:
        """构建格式化的位置信息"""
        start = range_info.get("start", {})
        end = range_info.get("end", {})

        base_info = (
            f"[文件] {Path(path).name}\n"
            f"[路径] {path}\n"
            f"[位置] 行: {start.get('line', 0) + 1}:{start.get('character', 0)}"
            f" → 行: {end.get('line', 0) + 1}:{end.get('character', 0)}"
        )

        symbol_info = f"\n[符号] {symbol}" if symbol else ""
        code_info = f"\n\n[代码片段]\n{code_snippet}" if code_snippet else ""

        return f"{base_info}{symbol_info}{code_info}"

    def __str__(self):
        return f"{self.command_name}: {self.description}"
