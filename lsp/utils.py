from urllib.parse import unquote, urlparse

from rich.table import Table
from rich.tree import Tree


def _get_symbol_attr(symbol, attr, default=None):
    """统一获取符号属性，兼容字典和对象"""
    if isinstance(symbol, dict):
        return symbol.get(attr, default)
    return getattr(symbol, attr, default)


def format_completion_item(item):
    return {
        "label": item.get("label"),
        "kind": item.get("kind"),
        "detail": item.get("detail") or "",
        "documentation": item.get("documentation") or "",
        "parameters": item.get("parameters", []),
        "text_edit": item.get("textEdit"),
    }


def _build_symbol_tree(symbol, tree_node):
    """递归构建符号树结构"""
    name = _get_symbol_attr(symbol, "name", "未知名称")
    deprecated = (
        "[strike red]DEPRECATED[/] "
        if _get_symbol_attr(symbol, "deprecated") or (1 in _get_symbol_attr(symbol, "tags", []))
        else ""
    )
    kind_name = _symbol_kind_name(_get_symbol_attr(symbol, "kind"))

    # 处理范围信息
    symbol_range = _get_symbol_attr(symbol, "range")
    location = _get_symbol_attr(symbol, "location")
    if not symbol_range and location:
        symbol_range = _get_symbol_attr(location, "range")

    range_str = f"[blue]{_format_range(symbol_range)}[/]" if symbol_range else "[yellow]未知范围[/]"
    node_line = f"{deprecated}[bold]{name}[/] ({kind_name}) ⏱️{range_str}"
    node = tree_node.add(node_line)

    if _get_symbol_attr(symbol, "detail"):
        node.add(f"[dim]详情: {_get_symbol_attr(symbol, 'detail')}[/]")

    if _get_symbol_attr(symbol, "tags"):
        tags = ", ".join(["Deprecated" if t == 1 else f"Unknown({t})" for t in _get_symbol_attr(symbol, "tags")])
        node.add(f"[yellow]标签: {tags}")

    for child in _get_symbol_attr(symbol, "children", []):
        _build_symbol_tree(child, node)


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


def _format_range(range_dict):
    start = _get_symbol_attr(range_dict, "start")
    end = _get_symbol_attr(range_dict, "end")
    if start and end:
        start_line = _get_symbol_attr(start, "line", 0) + 1
        start_char = _get_symbol_attr(start, "character", 0)
        end_line = _get_symbol_attr(end, "line", 0) + 1
        end_char = _get_symbol_attr(end, "character", 0)
        return f"{start_line}:{start_char}→{end_line}:{end_char}"
    return "无效范围"


def _create_completion_table(items):
    """创建补全建议表格"""
    table = Table(title="补全建议", show_header=True, header_style="bold magenta")
    table.add_column("标签", style="cyan")
    table.add_column("类型", style="green")
    table.add_column("详情")
    table.add_column("文档")
    for item in items:
        table.add_row(item["label"], str(item["kind"]), item["detail"], item["documentation"])
    return table


def _create_symbol_table(symbols):
    """创建符号信息表格"""
    table = Table(title="文档符号", show_header=True, header_style="bold yellow", expand=True)
    table.add_column("名称", style="cyan", no_wrap=True)
    table.add_column("类型", style="green", width=12)
    table.add_column("位置", width=20)
    table.add_column("容器", style="dim")
    table.add_column("标签/状态", width=15)

    for sym in symbols:
        loc = _get_symbol_attr(sym, "location")
        uri = urlparse(_get_symbol_attr(loc, "uri", "")).path
        position = f"{_get_symbol_attr(loc['range']['start'], 'line', 0)+1}:{_get_symbol_attr(loc['range']['start'], 'character', 0)}"

        tags = []
        if _get_symbol_attr(sym, "tags"):
            tags += ["Deprecated" if t == 1 else f"Unknown({t})" for t in _get_symbol_attr(sym, "tags")]
        if _get_symbol_attr(sym, "deprecated"):
            tags.append("Deprecated")

        table.add_row(
            _get_symbol_attr(sym, "name"),
            _symbol_kind_name(_get_symbol_attr(sym, "kind")),
            f"{unquote(uri)} {position}",
            _get_symbol_attr(sym, "containerName", ""),
            ", ".join(tags) or "N/A",
        )
    return table


def _validate_args(console, parts, required_count):
    """验证参数数量"""
    if len(parts) != required_count:
        console.print(f"[red]参数错误，需要{required_count-1}个参数[/red]")
        return False
    return True


async def _dispatch_command(console, lsp_client, plugin_manager, text):
    """分发处理用户命令"""
    parts = text.strip().split()
    if not parts:
        return False

    cmd = parts[0].lower()
    handler = plugin_manager.get_command_handler(cmd)

    if handler:
        await handler(console, lsp_client, parts)
        return True
    return False


def _build_container_tree(symbols):
    """根据containerName构建符号树"""
    container_map = {}
    for sym in symbols:
        container = _get_symbol_attr(sym, "containerName", "")
        if container not in container_map:
            container_map[container] = []
        container_map[container].append(sym)

    tree = Tree("📂 符号容器树", highlight=True, guide_style="dim")
    for container, symbols_in_container in container_map.items():
        if container:
            node = tree.add(f"[bold]{container}[/]")
        else:
            node = tree
        for sym in symbols_in_container:
            # 添加location到符号数据以兼容处理
            if not _get_symbol_attr(sym, "location") and _get_symbol_attr(sym, "range"):
                sym["location"] = {"uri": "", "range": _get_symbol_attr(sym, "range")}
            _build_symbol_tree(sym, node)
    return tree


def _create_json_table(data):
    """将JSON数据美化成表格"""
    table = Table(title="JSON 数据", show_header=True, header_style="bold blue", expand=True)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    for key, value in data.items():
        if isinstance(value, (dict, list)):
            value = str(value)
        table.add_row(key, str(value))
    return table
