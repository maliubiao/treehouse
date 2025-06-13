import logging
from typing import TYPE_CHECKING

from tree_sitter import Node

from .expr_types import ExprType, ExprTypeHandler

if TYPE_CHECKING:
    from .expr_extractor import ExpressionExtractor

logger = logging.getLogger("ExpressionExtractor")


class NodeProcessor:
    """处理语法树节点，只提取基本表达式类型"""

    def __init__(self, extractor: "ExpressionExtractor"):
        self.extractor = extractor
        # 初始化处理器字典
        self.handlers = {
            "declaration": self._handle_declaration,
            "expression_statement": self._handle_expression_statement,
            "assignment_expression": self._handle_assignment,
            "for_statement": self._handle_for_statement,
            "call_expression": self._handle_call_expression,
            "range_based_for_statement": self._handle_range_based_for_statement,
        }

    def process(self, node: Node, source: bytes) -> bool:
        """处理节点并返回是否已处理"""
        # 首先检查特定节点类型
        handler = self.handlers.get(node.type)
        if handler:
            handler(node, source)
            return True

        # 检查是否为可提取的表达式类型
        expr_type = ExprTypeHandler.get_expr_type(node.type)
        if expr_type:
            self._handle_expression_node(node, source, expr_type)
            return True

        return False

    def _handle_expression_node(self, node: Node, source: bytes, expr_type: ExprType):
        """处理表达式节点"""
        handlers = {
            "field_expression": self._handle_member_access,
            "subscript_expression": self._handle_subscript_expression,
            "template_instantiation": self._handle_template_instantiation,
            "pointer_expression": self._handle_pointer_deref,  # 统一处理指针表达式
        }

        handler = handlers.get(node.type)
        if handler:
            handler(node, source)
        else:
            # 默认处理：添加表达式
            self.extractor._add_expression(node, source, expr_type)

    def _handle_declaration(self, node: Node, source: bytes):
        """处理声明语句中的初始化表达式"""
        for child in node.children:
            if child.type == "init_declarator":
                declarator = child.child_by_field_name("declarator")
                if declarator:
                    # 添加变量访问类型
                    self.extractor._add_expression(declarator, source, ExprType.VARIABLE_ACCESS)

                    if declarator.type == "pointer_declarator":
                        self._handle_pointer_declarator(declarator, source)
                    else:
                        # 添加赋值目标类型
                        self.extractor._add_expression(declarator, source, ExprType.ASSIGNMENT_TARGET)
                        self._extract_identifier(declarator, source)

                value_node = child.child_by_field_name("value")
                if value_node:
                    self.extractor._traverse(value_node, source)
            elif child.type == "identifier":
                # 处理简单标识符声明
                self.extractor._add_expression(child, source, ExprType.VARIABLE_ACCESS)
                self.extractor._add_expression(child, source, ExprType.ASSIGNMENT_TARGET)
            elif child.type == "pointer_declarator":
                self._handle_pointer_declarator(child, source)

    def _handle_pointer_declarator(self, node: Node, source: bytes):
        """处理指针声明符"""
        declarator = node.child_by_field_name("declarator")
        if declarator:
            # 添加变量访问类型
            self.extractor._add_expression(declarator, source, ExprType.VARIABLE_ACCESS)

            if declarator.type == "identifier":
                # 添加赋值目标类型
                self.extractor._add_expression(declarator, source, ExprType.ASSIGNMENT_TARGET)
            else:
                self._extract_identifier(declarator, source)

    def _handle_expression_statement(self, node: Node, source: bytes):
        """处理表达式语句"""
        for child in node.children:
            if child.type != ";":
                self.extractor._traverse(child, source)

    def _extract_identifier(self, node: Node, source: bytes):
        """递归提取标识符节点"""
        if node.type == "identifier":
            self.extractor._add_expression(node, source, ExprType.VARIABLE_ACCESS)
        else:
            for child in node.children:
                self._extract_identifier(child, source)

    def _handle_assignment(self, node: Node, source: bytes):
        """处理赋值表达式"""
        left_node = node.child_by_field_name("left")
        if left_node:
            # 首先处理左侧表达式的本质类型
            self.extractor._traverse(left_node, source)

            # 然后添加赋值目标类型
            self.extractor._add_expression(left_node, source, ExprType.ASSIGNMENT_TARGET)

        right_node = node.child_by_field_name("right")
        if right_node:
            self.extractor._traverse(right_node, source)

    def _handle_for_statement(self, node: Node, source: bytes):
        """处理for循环语句"""
        init_node = node.child_by_field_name("initializer")
        if init_node:
            self.extractor._traverse(init_node, source)

        condition_node = node.child_by_field_name("condition")
        if condition_node:
            self.extractor._traverse(condition_node, source)

        update_node = node.child_by_field_name("update")
        if update_node:
            self.extractor._traverse(update_node, source)

        body_node = node.child_by_field_name("body")
        if body_node:
            self.extractor._traverse(body_node, source)

    def _handle_range_based_for_statement(self, node: Node, source: bytes):
        """处理C++ range-based for语句"""
        # 处理范围表达式
        range_node = node.child_by_field_name("range")
        if range_node:
            self.extractor._traverse(range_node, source)

        # 处理循环体
        body_node = node.child_by_field_name("body")
        if body_node:
            self.extractor._traverse(body_node, source)

    def _handle_member_access(self, node: Node, source: bytes, is_target=False):
        """处理成员访问表达式"""
        # 总是添加成员访问类型
        self.extractor._add_expression(node, source, ExprType.MEMBER_ACCESS)

        # 如果是赋值目标，额外添加目标类型
        if is_target:
            self.extractor._add_expression(node, source, ExprType.ASSIGNMENT_TARGET)

        field = node.child_by_field_name("field")
        if field and field.type == "field_identifier":
            self.extractor.processed_nodes.add(id(field))

        object_node = node.child_by_field_name("object")
        if object_node:
            self.extractor._traverse(object_node, source)

    def _handle_pointer_deref(self, node: Node, source: bytes, is_target=False):
        """处理指针解引用（支持多级）"""
        # 检查是否是取地址操作
        try:
            expr_text = source[node.start_byte : node.end_byte].decode("utf8").strip()
            if expr_text.startswith("&"):
                # 处理为取地址操作
                self.extractor._add_expression(node, source, ExprType.ADDRESS_OF)
                if is_target:
                    self.extractor._add_expression(node, source, ExprType.ASSIGNMENT_TARGET)
            else:
                # 处理为指针解引用
                self.extractor._add_expression(node, source, ExprType.POINTER_DEREF)
                if is_target:
                    self.extractor._add_expression(node, source, ExprType.ASSIGNMENT_TARGET)
        except UnicodeDecodeError:
            # 默认当作解引用处理
            self.extractor._add_expression(node, source, ExprType.POINTER_DEREF)
            if is_target:
                self.extractor._add_expression(node, source, ExprType.ASSIGNMENT_TARGET)

        operand = node.child_by_field_name("argument")
        if operand:
            self.extractor._traverse(operand, source)

    def _handle_subscript_expression(self, node: Node, source: bytes, is_target=False):
        """处理下标访问表达式"""
        # 总是添加下标访问类型
        self.extractor._add_expression(node, source, ExprType.SUBSCRIPT_EXPRESSION)

        # 如果是赋值目标，额外添加目标类型
        if is_target:
            self.extractor._add_expression(node, source, ExprType.ASSIGNMENT_TARGET)

        array_node = node.child_by_field_name("array")
        if array_node:
            self.extractor._traverse(array_node, source)

        index_node = node.child_by_field_name("index")
        if index_node:
            self.extractor._traverse(index_node, source)

    def _handle_template_instantiation(self, node: Node, source: bytes):
        """处理模板实例化表达式"""
        self.extractor._add_expression(node, source, ExprType.TEMPLATE_INSTANCE)

        name_node = node.child_by_field_name("name")
        if name_node:
            self.extractor._traverse(name_node, source)

        parameters_node = node.child_by_field_name("parameters")
        if parameters_node:
            for param in parameters_node.children:
                if param.type not in ["<", ">", ","]:
                    self.extractor._traverse(param, source)

    def _handle_call_expression(self, node: Node, source: bytes):
        """处理函数调用表达式"""
        function_node = node.child_by_field_name("function")
        if function_node:
            self.extractor._traverse(function_node, source)

        arguments_node = node.child_by_field_name("arguments")
        if arguments_node:
            for arg in arguments_node.children:
                if arg.type not in ["(", ")", ","]:
                    self.extractor._traverse(arg, source)
