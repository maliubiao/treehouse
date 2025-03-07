from urllib.parse import unquote, urlparse

from rich.table import Table


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
    name = symbol["name"]
    deprecated = (
        "[strike red]DEPRECATED[/] " if symbol.get("deprecated") or (symbol.get("tags") and 1 in symbol["tags"]) else ""
    )
    node = tree_node.add(f"{deprecated}[bold]{name}[/] ({_symbol_kind_name(symbol['kind'])})")

    if symbol.get("detail"):
        node.add(f"[dim]详情: {symbol['detail']}[/]")
    node.add(f"[blue]范围: {_format_range(symbol['range'])}[/]")

    if symbol.get("tags"):
        tags = ", ".join(["Deprecated" if t == 1 else f"Unknown({t})" for t in symbol["tags"]])
        node.add(f"[yellow]标签: {tags}[/]")

    for child in symbol.get("children", []):
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
    start = range_dict["start"]
    end = range_dict["end"]
    return f"{start['line']+1}:{start['character']} - {end['line']+1}:{end['character']}"


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
        loc = sym["location"]
        uri = urlparse(loc["uri"]).path
        position = f"{loc['range']['start']['line']+1}:{loc['range']['start']['character']}"

        tags = []
        if sym.get("tags"):
            tags += ["Deprecated" if t == 1 else f"Unknown({t})" for t in sym["tags"]]
        if sym.get("deprecated"):
            tags.append("Deprecated")

        table.add_row(
            sym["name"],
            _symbol_kind_name(sym["kind"]),
            f"{unquote(uri)} {position}",
            sym.get("containerName", ""),
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
