import logging
from typing import TYPE_CHECKING

from tree_sitter import Node

from tree import dump_tree

from .expr_types import ExprType, ExprTypeHandler

if TYPE_CHECKING:
    from .expr_extractor import ExpressionExtractor

logger = logging.getLogger("ExpressionExtractor")
# don't change this
DEBUG = False


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
            "for_range_loop": self._handle_for_range_statement,
            "call_expression": self._handle_call_expression,
            "function_declarator": self._handle_function_declarator,
            "template_instantiation": self._handle_template_instantiation,
        }

    def get_child_by_type(self, node: Node, child_type: str) -> Node:
        for child in node.children:
            if child.type == child_type:
                return child

    def process(self, node: Node, source: bytes) -> bool:
        """处理节点并返回是否已处理"""
        if DEBUG:
            dump_tree(node, 2)

        # 跳过类型标识符、字段标识符和类成员声明节点
        if node.type in ["type_identifier", "field_identifier", "field_declaration"]:
            return True  # 标记为已处理，跳过后续处理

        handler = self.handlers.get(node.type)
        if handler:
            handler(node, source)
            return True
        if node.type in ("struct_specifier", "union_specifier", "enum_specifier"):
            return False
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
            "pointer_expression": self._handle_pointer_deref,  # 统一处理指针表达式
        }

        handler = handlers.get(node.type)
        if handler:
            handler(node, source)
        else:
            # 默认处理：添加表达式
            self.extractor._add_expression(node, source, expr_type)

    def _handle_template_instantiation(self, node: Node, source: bytes):
        """处理模板实例化节点：跳过整个节点及其子节点"""
        # 标记节点已处理，避免递归子节点
        self.extractor.processed_nodes.add(id(node))
        # 跳过所有子节点
        for child in node.children:
            self.extractor.processed_nodes.add(id(child))
        logger.debug("跳过模板实例化节点: %s", node)

    def _handle_declaration(self, node: Node, source: bytes):
        """处理声明语句中的初始化表达式"""
        for child in node.children:
            if child.type == "init_declarator":
                declarator = self.get_child_by_type(child, "identifier")
                if declarator:
                    # 添加赋值目标类型
                    self.extractor._add_expression(declarator, source, ExprType.ASSIGNMENT_TARGET)
                    # 将声明符节点标记为已处理，避免后续作为变量访问被提取
                    self.extractor.processed_nodes.add(id(declarator))
                # 递归处理初始化表达式
                self.extractor._traverse(child, source)
            elif child.type == "pointer_declarator":
                self._handle_pointer_declarator(child, source)

    def _handle_pointer_declarator(self, node: Node, source: bytes):
        """处理指针声明符"""
        declarator = node.child_by_field_name("declarator")
        if declarator:
            # 添加赋值目标类型
            self.extractor._add_expression(declarator, source, ExprType.ASSIGNMENT_TARGET)
            # 将声明符节点标记为已处理，避免重复提取
            self.extractor.processed_nodes.add(id(declarator))

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
            # 直接添加左侧节点为赋值目标，不再递归遍历
            self.extractor._add_expression(left_node, source, ExprType.ASSIGNMENT_TARGET)

        right_node = node.child_by_field_name("right")
        if right_node:
            self.extractor._traverse(right_node, source)

    def _handle_for_range_statement(self, node: Node, source: bytes):
        """处理范围for循环"""
        # 标记循环变量节点，避免被当作变量访问提取
        for child in node.children:
            # 处理引用声明符中的变量
            if child.type == "reference_declarator":
                # 在reference_declarator中查找标识符
                for subchild in child.children:
                    if subchild.type == "identifier":
                        # 标记节点避免后续处理
                        self.extractor.processed_nodes.add(id(subchild))
            # 处理指针声明符中的变量
            elif child.type == "pointer_declarator":
                # 在pointer_declarator中查找标识符
                for subchild in child.children:
                    if subchild.type == "identifier":
                        self.extractor.processed_nodes.add(id(subchild))
            # 处理直接标识符声明
            elif child.type == "identifier":
                self.extractor.processed_nodes.add(id(child))

        # 处理循环容器和循环体
        # 查找容器表达式（可能是field_expression或pointer_expression）
        container_expr = None
        for child in node.children:
            if child.type in ["field_expression", "pointer_expression"]:
                container_expr = child
                break

        if container_expr:
            # 处理容器表达式
            self.extractor._traverse(container_expr, source)

        # 处理循环体
        compound_expr = self.get_child_by_type(node, "compound_statement")
        if compound_expr:
            self.extractor._traverse(compound_expr, source)

    def _handle_for_statement(self, node: Node, source: bytes):
        """处理for循环语句 (包括常规for和range-based for)"""
        # 遍历for语句的所有子节点
        for child in node.children:
            # 处理初始化部分 (声明或表达式)
            if child.type == "expression_statement":
                self.extractor._traverse(child, source)
            # 处理条件部分 (二元表达式)
            elif child.type == "binary_expression":
                self.extractor._traverse(child, source)
            # 处理更新部分 (更新表达式)
            elif child.type == "update_expression":
                self.extractor._traverse(child, source)
            # 处理循环体
            elif child.type == "compound_statement":
                self.extractor._traverse(child, source)

    def _handle_member_access(self, node: Node, source: bytes, is_target=False):
        """处理成员访问表达式"""
        # 总是添加成员访问类型
        self.extractor._add_expression(node, source, ExprType.MEMBER_ACCESS)

        # 如果是赋值目标，额外添加目标类型
        if is_target:
            self.extractor._add_expression(node, source, ExprType.ASSIGNMENT_TARGET)

        # 递归处理对象节点
        object_node = node.child_by_field_name("object")
        if object_node:
            # 处理对象节点（可能是复杂表达式）
            self.extractor._traverse(object_node, source)

        # 跳过字段标识符节点
        field_identifier = node.child_by_field_name("property")
        if field_identifier:
            self.extractor.processed_nodes.add(id(field_identifier))

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

        # 递归处理操作数以支持多级指针
        operand = node.child_by_field_name("operand")
        if operand:
            self.extractor._traverse(operand, source)

    def _handle_subscript_expression(self, node: Node, source: bytes, is_target=False):
        """处理下标访问表达式"""
        # 总是添加下标访问类型
        self.extractor._add_expression(node, source, ExprType.SUBSCRIPT_EXPRESSION)

        # 如果是赋值目标，额外添加目标类型
        if is_target:
            self.extractor._add_expression(node, source, ExprType.ASSIGNMENT_TARGET)

        # 递归处理数组和索引表达式
        array_node = node.child_by_field_name("array")
        index_node = node.child_by_field_name("index")

        if array_node:
            self.extractor._traverse(array_node, source)
        if index_node:
            self.extractor._traverse(index_node, source)

    def _handle_call_expression(self, node: Node, source: bytes):
        """处理函数调用表达式"""
        # 提取函数名部分（可能包含成员访问等复杂表达式）
        function_node = node.child_by_field_name("function")
        if function_node:
            self.extractor._traverse(function_node, source)

        # 处理参数列表
        argument_list = node.child_by_field_name("arguments")
        if argument_list:
            for arg in argument_list.children:
                if arg.type not in ["(", ")", ","]:
                    # 递归处理参数表达式（不再显式添加，依赖递归处理自动提取）
                    self.extractor._traverse(arg, source)

    def _handle_function_declarator(self, node: Node, source: bytes):
        """处理函数定义"""
        # 处理函数名：标记为已处理，避免提取
        declarator = node.child_by_field_name("declarator")
        if declarator:
            # 将函数名节点标记为已处理
            self.extractor.processed_nodes.add(id(declarator))

        parameter_list = self.get_child_by_type(node, "parameter_list")
        if parameter_list:
            self.extractor._traverse(parameter_list, source)

        compond_statement = self.get_child_by_type(node, "compound_statement")
        if compond_statement:
            self.extractor._traverse(compond_statement, source)
