import os
from collections import defaultdict

from rich.console import Console
from rich.text import Text
from rich.tree import Tree


class TreeNode:
    """树节点表示目录（不再包含文件节点）"""

    __slots__ = ("name", "symbol_count", "children", "path")

    def __init__(self, name, path=""):
        self.name = name
        self.symbol_count = 0
        self.children = {}
        self.path = path  # 存储完整路径用于缓存


class SourceTreeBuilder:
    """构建源文件树并生成统计报告"""

    def __init__(self):
        self.root = TreeNode("")
        self.total_symbols = 0
        self.console = Console()
        self.path_cache = {}  # 路径缓存：文件路径 -> 目录路径列表

    def add_symbol(self, file_path):
        """添加一个符号到树结构中"""
        # 使用缓存避免重复拆分路径
        if file_path not in self.path_cache:
            # 获取目录部分（去掉文件名）
            dir_path = os.path.dirname(file_path)
            # 拆分路径为目录层级
            parts = []
            current = dir_path
            while current and current != os.sep:
                current, tail = os.path.split(current)
                if tail:
                    parts.insert(0, tail)
            self.path_cache[file_path] = parts

        parts = self.path_cache[file_path]
        current = self.root
        self.total_symbols += 1

        # 遍历路径的每个目录部分
        for part in parts:
            # 如果节点不存在则创建
            if part not in current.children:
                # 构建当前节点的完整路径
                new_path = os.path.join(current.path, part) if current.path else part
                current.children[part] = TreeNode(part, new_path)

            current = current.children[part]
            current.symbol_count += 1  # 每层目录都增加符号计数

    def generate_markdown(self, output_path):
        """生成Markdown格式的树状报告"""
        markdown_content = "# Source Directory Symbol Distribution\n\n"
        markdown_content += f"**Total Symbols:** {self.total_symbols}\n\n"
        markdown_content += "```mermaid\ngraph TD\n"

        # 递归生成Mermaid图
        markdown_content += self._generate_mermaid(self.root, "root")

        markdown_content += "```\n\n"
        markdown_content += "## Detailed Breakdown\n\n"
        markdown_content += self._generate_tree_text(self.root)

        # 写入文件
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return markdown_content

    def _generate_mermaid(self, node, node_id, parent_id=None):
        """递归生成Mermaid图语法"""
        content = ""

        # 生成当前节点
        label = f"{node.name}\\n({node.symbol_count} symbols)"
        content += f'{node_id}("{label}")\n'

        # 添加与父节点的连接
        if parent_id:
            content += f"{parent_id} --> {node_id}\n"

        # 处理子节点
        for i, (name, child) in enumerate(node.children.items()):
            child_id = f"{node_id}_{i}"
            content += self._generate_mermaid(child, child_id, node_id)

        return content

    def _generate_tree_text(self, node, depth=0, prefix=""):
        """生成树状文本表示"""
        content = ""
        indent = "    " * depth
        is_last = depth == 0  # 根节点特殊处理

        # 节点显示（所有节点都是目录）
        symbol_percent = f"({node.symbol_count}/{self.total_symbols}, {node.symbol_count / self.total_symbols:.1%})"
        content += f"{indent}{prefix}📁 {node.name} {symbol_percent}\n"

        # 处理子节点
        child_count = len(node.children)
        for i, (name, child) in enumerate(sorted(node.children.items())):
            is_last_child = i == child_count - 1
            child_prefix = "└── " if is_last_child else "├── "
            content += self._generate_tree_text(child, depth + 1, child_prefix)

        return content

    def print_tree(self):
        """在控制台打印树状结构"""
        tree = Tree(f"📁 Source Tree ({self.total_symbols} symbols total)")
        self._build_rich_tree(self.root, tree)
        self.console.print(tree)

    def _build_rich_tree(self, node, parent_node):
        """构建Rich库的树结构"""
        for name, child in sorted(node.children.items()):
            # 节点显示（所有节点都是目录）
            percent = child.symbol_count / self.total_symbols
            color = "green" if percent > 0.1 else "yellow" if percent > 0.01 else "red"

            label = Text(f"📁 {child.name} ", style="bold")
            label.append(f"({child.symbol_count} symbols, {percent:.1%})", style=color)

            # 添加到树
            child_node = parent_node.add(label)

            # 递归处理子节点
            self._build_rich_tree(child, child_node)
