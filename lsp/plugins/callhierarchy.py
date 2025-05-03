import os

from rich.panel import Panel

from .. import GenericLSPClient
from ..utils import _validate_args
from . import LSPCommandPlugin, build_hierarchy_tree


class CallHierarchyPlugin(LSPCommandPlugin):
    command_name = "callhierarchy"
    command_params = ["file_path", "line", "character"]
    description = "获取调用层次结构信息"

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
        # 准备调用层次结构
        prepare_result = await lsp_client.prepare_call_hierarchy(
            abs_file_path, line, char
        )
        if not prepare_result:
            console.print(
                Panel("🕳️ 没有找到调用层次结构", title="空结果", border_style="blue")
            )
            return

        # 处理调用层次结构结果
        if isinstance(prepare_result, list):
            tree = build_hierarchy_tree(
                "📂 调用层次结构",
                prepare_result,
                _build_call_hierarchy_tree,
                lsp_client,
            )
            console.print(
                Panel(
                    tree, title="🌳 调用层次结构", border_style="green", padding=(1, 2)
                )
            )
        else:
            console.print(
                Panel("⚠️ 收到非预期的响应格式", title="解析错误", border_style="red")
            )

    def __str__(self):
        return f"{self.command_name}: {self.description}"


def _build_call_hierarchy_tree(tree_node, item, lsp_client: GenericLSPClient):
    """递归构建调用层次结构树"""
    name = item["name"]
    kind = _symbol_kind_name(item["kind"])
    node = tree_node.add(f"[bold]{name}[/] ({kind})")

    # 获取传入调用
    incoming_calls = lsp_client.get_incoming_calls(item)
    if incoming_calls:
        incoming_node = node.add("📥 传入调用")
        for call in incoming_calls:
            _build_call_hierarchy_tree(incoming_node, call["from"], lsp_client)

    # 获取传出调用
    outgoing_calls = lsp_client.get_outgoing_calls(item)
    if outgoing_calls:
        outgoing_node = node.add("📤 传出调用")
        for call in outgoing_calls:
            _build_call_hierarchy_tree(outgoing_node, call["to"], lsp_client)


def _symbol_kind_name(kind_code):
    kinds = {
        1: "📄文件",
        2: "📦模块",
        3: "🗃️命名空间",
        4: "📦包",
        5: "🏛️类",
        6: "🔧方法",
        7: "🏷️属性",
        8: "📝字段",
        9: "🛠️构造函数",
        10: "🔢枚举",
        11: "📜接口",
        12: "🔌函数",
        13: "📦变量",
        14: "🔒常量",
        15: "🔤字符串",
        16: "🔢数字",
        17: "✅布尔值",
        18: "🗃️数组",
        19: "📦对象",
        20: "🔑键",
        21: "❌空",
        22: "🔢枚举成员",
        23: "🏗️结构体",
        24: "🎫事件",
        25: "⚙️运算符",
        26: "📐类型参数",
    }
    return kinds.get(kind_code, f"未知类型({kind_code})")
