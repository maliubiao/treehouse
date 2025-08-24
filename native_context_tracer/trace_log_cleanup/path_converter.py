import argparse
import os
import re
import sys
from collections import defaultdict
from typing import List, Set, Union


class PathTrieNode:
    """Trie节点类，存储路径段和子节点"""

    __slots__ = ("children", "count")

    def __init__(self):
        self.children = defaultdict(PathTrieNode)
        self.count = 0


class PathTrie:
    """路径前缀树实现"""

    def __init__(self):
        self.root = PathTrieNode()
        self.total_paths = 0
        self.min_depth = float("inf")
        self.inserted_paths = set()  # 存储所有插入的完整路径

    def insert(self, path: str) -> None:
        """插入路径到Trie"""
        # 跳过空路径
        if not path or not os.path.isabs(path):
            return

        # 归一化路径格式
        clean_path = re.sub(r":\d+$", "", path).replace("\\", "/")
        # 再次检查归一化后是否为绝对路径
        if not os.path.isabs(clean_path):
            return

        # 存储归一化后的路径
        self.inserted_paths.add(clean_path)

        node = self.root
        parts = [p for p in clean_path.split("/") if p]
        # 跳过无效路径
        if not parts:
            return

        self.min_depth = min(self.min_depth, len(parts))

        for part in parts:
            node = node.children[part]
            node.count += 1
        self.total_paths += 1

    def find_common_prefix(self) -> str:
        """查找最长公共路径前缀"""
        if self.total_paths == 0 or self.min_depth == 0:
            return ""

        common_parts: List[str] = []
        node = self.root
        depth = 0

        while depth < self.min_depth:
            if len(node.children) == 1:
                part, next_node = next(iter(node.children.items()))
                if next_node.count == self.total_paths:
                    common_parts.append(part)
                    node = next_node
                    depth += 1
                else:
                    break
            else:
                break

        return os.path.sep + os.path.sep.join(common_parts) if common_parts else ""

    @staticmethod
    def _normalize_path(path: str) -> List[str]:
        """统一处理路径格式并分割，保留绝对路径的根目录"""
        clean_path = re.sub(r":\d+$", "", path).replace("\\", "/")
        parts = [p for p in clean_path.split("/") if p]
        return parts


def extract_at_paths(text: str) -> Set[str]:
    """从文本中提取路径（优化性能版）"""
    # 新正则：匹配分号后或行首，后跟可选"at"关键字的路径
    pattern = re.compile(
        r"""
        (?:^|;)                 # 行首或分号
        \s*                     # 任意空格
        (?:at\s+)?              # 可选的"at"关键字
        (                       # 捕获组1：路径
            (?:[a-zA-Z]:)?      # Windows盘符（可选）
            (?:/|\\|/)          # 路径分隔符
            (?:[^/\s:]+[/\\])*  # 路径主体
            [^/\s:]+            # 文件名
        )
        (?::\d+)?               # 可选行号
        (?=[\s;.,]|$)           # 边界检查
    """,
        re.VERBOSE | re.IGNORECASE,
    )

    paths = set()
    for match in pattern.finditer(text):
        path_str = match.group(1).replace("\\", "/")  # 统一路径格式

        # 清理路径末尾的标点
        while path_str and path_str[-1] in ",;.:":
            path_str = path_str[:-1]

        if os.path.isabs(path_str):
            paths.add(path_str)

    return paths


def convert_at_paths(text: str, base_path: Union[str, None]) -> str:
    """将文本中的绝对路径转换为相对路径"""
    if not base_path:
        return text

    base_path = base_path.rstrip("/")

    def replace_match(match: re.Match) -> str:
        full_match = match.group(0)
        path_part = match.group(1)

        # 检查是否有行号后缀
        line_num_match = re.search(r":(\d+)$", full_match)
        line_part = f":{line_num_match.group(1)}" if line_num_match else ""

        # 统一处理base_path前缀格式
        normalized_base = base_path.replace("\\", "/").rstrip("/")
        normalized_path = path_part.replace("\\", "/")

        if normalized_path.startswith(normalized_base):
            rel_path = os.path.relpath(normalized_path, normalized_base)
            rel_path = f"./{rel_path}" if not rel_path.startswith(".") else rel_path
            # 构造新路径（保留原始前缀/后缀）
            new_path = full_match.replace(path_part, rel_path)
            # 移除可能重复的行号
            return re.sub(r":\d+$", "", new_path) + line_part
        return full_match

    # 更新后的转换模式，与提取模式保持一致
    pattern = r"""
        (?:^|;)                 # 行首或分号
        \s*                     # 任意空格
        (?:at\s+)?              # 可选的"at"关键字
        (                       # 捕获组1：路径
            (?:[a-zA-Z]:)?      # Windows盘符（可选）
            (?:/|\\|/)          # 路径分隔符
            (?:[^/\s:]+[/\\])*  # 路径主体
            [^/\s:]+            # 文件名
        )
        (?::\d+)?               # 可选行号
        (?=[\s;.,]|$)           # 边界检查
    """
    return re.sub(pattern, replace_match, text, flags=re.VERBOSE | re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser(
        description="Convert absolute paths to relative paths in trace logs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", nargs="?", help="Input file (default: stdin)")
    parser.add_argument("--base", help="Specify custom base path")
    parser.add_argument("--depth", type=int, default=10, help="Number of path segments to preserve in common prefix")
    args = parser.parse_args()

    if not args.input:
        content = sys.stdin.read()
    else:
        with open(args.input, encoding="utf-8") as f:
            content = f.read()

    found_paths = extract_at_paths(content)
    if not found_paths:
        print(content, end="")
        return

    path_trie = PathTrie()
    for path in found_paths:
        path_trie.insert(path)

    base_path = args.base or path_trie.find_common_prefix()

    # 未指定base且未找到公共前缀时导出所有路径
    if not args.base and not base_path and path_trie.inserted_paths:
        sorted_paths = sorted(path_trie.inserted_paths)
        with open("debug.log", "w", encoding="utf-8") as f:
            f.write("All extracted absolute paths:\n")
            f.write("\n".join(sorted_paths))
        sys.stderr.write("Warning: No common prefix found. Dumped all paths to debug.log for debugging.\n")

    if not args.base and base_path:
        # 计算需要保留的路径段数
        segments = base_path.strip("/").split("/")
        if len(segments) > args.depth:
            base_path = "/" + "/".join(segments[: args.depth])

    converted_content = convert_at_paths(content, base_path)
    print(converted_content, end="")


if __name__ == "__main__":
    main()
