import logging
import re
from typing import Any, Dict, List, Set

from tree_sitter import Node

from tracer.expr_types import ExprType
from tracer.node_processor import NodeProcessor
from tree import dump_tree

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ExpressionExtractor")


class ExpressionExtractor:
    def __init__(self, language_mode: str = "c"):
        self.current_line_exprs: Dict[int, List[Any]] = {}
        self.processed_nodes: Set[int] = set()
        self.added_nodes: Dict[int, Set[ExprType]] = {}
        self.node_processor = NodeProcessor(self)
        self.language_mode = language_mode  # 'c' 或 'cpp'

    def extract(self, node: Node, source: bytes) -> dict:
        self.current_line_exprs = {}
        self.processed_nodes.clear()
        self.added_nodes.clear()
        self._traverse(node, source)
        return self.current_line_exprs

    def _traverse(self, node: Node, source: bytes):
        if not node:
            return

        node_id = id(node)
        if node_id in self.processed_nodes:
            return
        self.processed_nodes.add(node_id)

        # 跳过内联汇编表达式及其所有子节点
        if node.type == "gnu_asm_expression":
            logger.debug("跳过内联汇编表达式: %s", node)
            return

        # 处理当前节点
        processed = self.node_processor.process(node, source)
        if processed:
            return

        # 递归处理子节点
        for child in node.children:
            self._traverse(child, source)

    def _add_expression(self, node: Node, source: bytes, expr_type: ExprType):
        """添加表达式到结果集，支持同一节点添加多个类型"""
        node_id = id(node)

        # 检查该节点是否已经以相同的类型添加过
        if node_id in self.added_nodes and expr_type in self.added_nodes[node_id]:
            return

        if node_id not in self.added_nodes:
            self.added_nodes[node_id] = set()
        self.added_nodes[node_id].add(expr_type)

        try:
            expr_text = source[node.start_byte : node.end_byte].decode("utf8")
        except UnicodeDecodeError:
            expr_text = str(source[node.start_byte : node.end_byte])
        if not expr_text:
            return

        # 跳过全大写标识符（可能是宏）
        if expr_text.strip() and all(c.isupper() or c == "_" for c in expr_text.strip()):
            logger.debug("跳过全大写标识符（可能是宏）: 行号=%d, 内容='%s'", node.start_point[0], expr_text)
            return
        # 跳过包含斜杠的表达式
        if "/" in expr_text:
            logger.debug("跳过包含斜杠的表达式: 行号=%d, 内容='%s'", node.start_point[0], expr_text)
            return

        # 跳过标准类型
        std_types = {
            # C 基本类型
            "int",
            "char",
            "float",
            "double",
            "void",
            "bool",
            "short",
            "long",
            "unsigned",
            "signed",
            "size_t",
            "ptrdiff_t",
            "wchar_t",
            "nullptr_t",
            # 有符号类型
            "int8_t",
            "int16_t",
            "int32_t",
            "int64_t",
            # 无符号类型
            "uint8_t",
            "uint16_t",
            "uint32_t",
            "uint64_t",
            # 类型修饰符组合
            "unsigned int",
            "unsigned char",
            "unsigned long",
            "unsigned short",
            "signed int",
            "signed char",
            "signed long",
            "signed short",
            "long int",
            "long long",
            "long double",
            "unsigned long long",
            # C++ 标准类型
            "string",
            "wstring",
            "nullptr",
            "byte",
        }
        if expr_text.strip() in std_types:
            logger.debug("跳过标准类型: 行号=%d, 内容='%s'", node.start_point[0], expr_text)
            return

        # 过滤模板实例化表达式
        if "<" in expr_text and ">" in expr_text:
            logger.debug("跳过模板实例表达式: 行号=%d, 内容='%s'", node.start_point[0], expr_text)
            return

        # 防御层：过滤包含函数调用的表达式
        # 允许模板实例化中的尖括号，但过滤其他括号
        # 对于赋值目标类型，跳过函数调用过滤
        if expr_type != ExprType.TEMPLATE_INSTANCE and expr_type != ExprType.ASSIGNMENT_TARGET:
            # 修改正则表达式：允许[]下标表达式和{}初始化，只过滤()函数调用
            # 特别允许成员访问表达式（包含点或箭头操作符）和下标表达式
            if re.search(r"[\(\)]", expr_text) and not re.search(r"\.|->|\[", expr_text):
                logger.debug(
                    "跳过包含函数调用的表达式: 行号=%d, 类型=%s, 内容='%s'",
                    node.start_point[0],
                    expr_type.name,
                    expr_text,
                )
                return

        start_row, start_col = node.start_point
        end_row, end_col = node.end_point
        pos = (start_row, start_col, end_row, end_col)

        # 初始化当前行表达式列表
        if start_row not in self.current_line_exprs:
            self.current_line_exprs[start_row] = []

        # 去重检查：同一行中相同内容的表达式只记录一次
        existing_exprs = {(et, text) for et, text, _ in self.current_line_exprs[start_row]}
        if (expr_type, expr_text) in existing_exprs:
            logger.debug("跳过重复表达式: 行号=%d, 类型=%s, 内容='%s'", start_row, expr_type.name, expr_text)
            return

        # 添加表达式
        self.current_line_exprs[start_row].append((expr_type, expr_text, pos))
        logger.debug("提取表达式: 行号=%d, 类型=%s, 内容='%s'", start_row, expr_type.name, expr_text)
