import logging
from enum import Enum

from tree_sitter import Node

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ExpressionExtractor")


class ExprType(Enum):
    """表达式类型枚举"""

    VARIABLE_ACCESS = 1  # 变量访问 (identifier)
    POINTER_DEREF = 2  # 指针解引用 (*expr)
    ADDRESS_OF = 3  # 取地址 (&expr)
    MEMBER_ACCESS = 4  # 成员访问 (obj.field, ptr->field)
    ASSIGNMENT_TARGET = 5  # 赋值目标 (左侧)
    ARITHMETIC_OPERAND = 6  # 算术操作数
    LITERAL = 7  # 字面量
    CALL_ARGUMENT = 8  # 函数调用参数
    TEMPLATE_INSTANCE = 9  # 模板实例化
    POINTER_DEREF_MULTI = 10  # 多级指针解引用
    MEMBER_ACCESS_MULTI = 11  # 多级成员访问
    CONDITIONAL_EXPR = 12  # 条件表达式
    OPERATOR = 13  # 操作符 (如 . ->)


class ExpressionExtractor:
    def __init__(self):
        self.expr_types = {
            "identifier": ExprType.VARIABLE_ACCESS,
            "field_identifier": ExprType.VARIABLE_ACCESS,
            "pointer_expression": ExprType.POINTER_DEREF,  # 默认处理，实际会根据操作符区分
            "address_expression": ExprType.ADDRESS_OF,
            "field_expression": ExprType.MEMBER_ACCESS,
            "subscript_expression": ExprType.VARIABLE_ACCESS,
            "assignment_expression": ExprType.ASSIGNMENT_TARGET,
            "number_literal": ExprType.LITERAL,
            "string_literal": ExprType.LITERAL,
            "char_literal": ExprType.LITERAL,
            "null": ExprType.LITERAL,
            "true": ExprType.LITERAL,
            "false": ExprType.LITERAL,
            "template_type": ExprType.VARIABLE_ACCESS,
            "template_function": ExprType.VARIABLE_ACCESS,
            "operator_name": ExprType.VARIABLE_ACCESS,
            "template_instantiation": ExprType.TEMPLATE_INSTANCE,
            "qualified_identifier": ExprType.VARIABLE_ACCESS,
            "binary_expression": ExprType.ARITHMETIC_OPERAND,
            "condition": ExprType.CONDITIONAL_EXPR,
            ".": ExprType.OPERATOR,
            "->": ExprType.OPERATOR,
        }

        self.current_line_exprs = {}

    def extract(self, node: Node, source: bytes) -> dict:
        self.current_line_exprs = {}
        self._traverse(node, source)
        return self.current_line_exprs

    def _traverse(self, node: Node, source: bytes):
        if not node:
            return

        # 跳过内联汇编表达式及其所有子节点
        if node.type == "gnu_asm_expression":
            logger.debug("跳过内联汇编表达式: %s", node)
            return

        # 处理当前节点
        self._process_node(node, source)

        # 递归处理子节点
        for child in node.children:
            self._traverse(child, source)

    def _process_node(self, node: Node, source: bytes):
        # 处理声明语句中的初始化表达式
        if node.type == "declaration":
            self._handle_declaration(node, source)
            return

        # 处理表达式语句
        if node.type == "expression_statement":
            self._handle_expression_statement(node, source)
            return

        # 处理赋值表达式
        if node.type == "assignment_expression":
            self._handle_assignment(node, source)
            return

        # 检查是否为可提取的表达式类型
        expr_type = self.expr_types.get(node.type)
        if expr_type:
            self._handle_expression_node(node, source, expr_type)

    def _handle_expression_node(self, node: Node, source: bytes, expr_type: ExprType):
        """处理表达式节点"""
        # 特殊处理指针表达式（可能是解引用或取地址）
        if node.type == "pointer_expression":
            self._handle_pointer_expression(node, source)
            return

        # 特殊处理取地址表达式
        if node.type == "address_expression":
            self._handle_address_of(node, source)
            return

        # 特殊处理成员访问表达式
        if node.type == "field_expression":
            self._handle_member_access(node, source)
            return

        # 特殊处理下标访问
        if node.type == "subscript_expression":
            self._handle_subscript_expression(node, source)
            return

        # 处理操作符（避免递归自身）
        if node.type in [".", "->"]:
            self._add_expression(node, source, expr_type)
            return

        # 默认处理：添加表达式
        self._add_expression(node, source, expr_type)

    def _handle_pointer_expression(self, node: Node, source: bytes):
        """统一处理指针表达式（可能是解引用或取地址）"""
        # 获取操作符节点
        operator_node = next((child for child in node.children if child.type in ["*", "&"]), None)

        if operator_node and operator_node.type == "&":
            # 处理取地址操作
            self._handle_address_of(node, source)
        else:
            # 默认处理指针解引用
            self._handle_pointer_deref(node, source)

    def _handle_declaration(self, node: Node, source: bytes):
        """处理声明语句中的初始化表达式"""
        # 遍历声明中的子节点，查找init_declarator
        for child in node.children:
            if child.type == "init_declarator":
                # 提取初始化表达式
                value_node = child.child_by_field_name("value")
                if value_node:
                    self._traverse(value_node, source)
                # 提取被声明的标识符
                declarator = child.child_by_field_name("declarator")
                if declarator:
                    self._extract_identifier(declarator, source)
            elif child.type == "identifier":
                # 处理简单声明 (如: int a;)
                self._add_expression(child, source, ExprType.VARIABLE_ACCESS)

    def _handle_expression_statement(self, node: Node, source: bytes):
        """处理表达式语句"""
        # 提取表达式语句中的表达式（跳过结束分号）
        for child in node.children:
            if child.type != ";":
                self._traverse(child, source)

    def _extract_identifier(self, node: Node, source: bytes):
        """递归提取标识符节点"""
        if node.type == "identifier":
            self._add_expression(node, source, ExprType.VARIABLE_ACCESS)
        else:
            # 处理复杂的声明符 (如指针声明: int *ptr)
            for child in node.children:
                self._extract_identifier(child, source)

    def _handle_assignment(self, node: Node, source: bytes):
        """处理赋值表达式"""
        # 提取赋值目标（左侧）
        left_node = node.child_by_field_name("left")
        if left_node:
            # 深入处理左侧表达式及其子节点
            self._traverse(left_node, source)
            # 将整个左侧表达式标记为赋值目标
            self._add_expression(left_node, source, ExprType.ASSIGNMENT_TARGET)

        # 递归处理右侧表达式
        right_node = node.child_by_field_name("right")
        if right_node:
            self._traverse(right_node, source)

    def _handle_member_access(self, node: Node, source: bytes):
        """处理成员访问表达式"""
        # 添加整个成员访问表达式
        self._add_expression(node, source, ExprType.MEMBER_ACCESS)

        # 提取操作符
        operator = node.child_by_field_name("operator")
        if operator and operator.type in [".", "->"]:
            self._add_expression(operator, source, ExprType.OPERATOR)

        # 提取字段标识符
        field = node.child_by_field_name("field")
        if field and field.type == "field_identifier":
            self._add_expression(field, source, ExprType.VARIABLE_ACCESS)

        # 递归处理基对象
        base_node = node.child_by_field_name("argument") or node.child_by_field_name("object")
        if base_node:
            self._traverse(base_node, source)

    def _handle_pointer_deref(self, node: Node, source: bytes, is_target=False):
        """处理指针解引用（支持多级）"""
        # 检查是否为多级解引用
        if node.parent and node.parent.type == "pointer_expression":
            expr_type = ExprType.POINTER_DEREF_MULTI
        else:
            expr_type = ExprType.POINTER_DEREF

        if is_target:
            expr_type = ExprType.ASSIGNMENT_TARGET

        self._add_expression(node, source, expr_type)

        # 添加解引用操作符
        operator = node.child_by_field_name("operator")
        if operator and operator.type == "*":
            self._add_expression(operator, source, ExprType.OPERATOR)

        # 递归处理子表达式
        operand = node.child_by_field_name("operand")
        if operand:
            self._traverse(operand, source)

    def _handle_address_of(self, node: Node, source: bytes, is_target=False):
        """处理取地址表达式"""
        expr_type = ExprType.ADDRESS_OF
        if is_target:
            expr_type = ExprType.ASSIGNMENT_TARGET

        self._add_expression(node, source, expr_type)

        # 添加取地址操作符
        operator = node.child_by_field_name("operator")
        if operator and operator.type == "&":
            self._add_expression(operator, source, ExprType.OPERATOR)
        else:
            # 对于pointer_expression类型的取地址，手动添加操作符
            operator_node = next((child for child in node.children if child.type == "&"), None)
            if operator_node:
                self._add_expression(operator_node, source, ExprType.OPERATOR)

        # 递归处理操作数
        operand = node.child_by_field_name("operand")
        if operand:
            self._traverse(operand, source)

    def _handle_subscript_expression(self, node: Node, source: bytes):
        """处理下标访问表达式"""
        # 添加整个下标访问表达式
        self._add_expression(node, source, ExprType.VARIABLE_ACCESS)

        # 递归处理基对象和索引
        for child in node.children:
            if child.type in ["[", "]"]:
                continue
            self._traverse(child, source)

    def _add_expression(self, node: Node, source: bytes, expr_type: ExprType):
        """添加表达式到结果集"""
        try:
            expr_text = source[node.start_byte : node.end_byte].decode("utf8")
        except UnicodeDecodeError:
            expr_text = str(source[node.start_byte : node.end_byte])

        start_row, start_col = node.start_point
        end_row, end_col = node.end_point
        pos = (start_row, start_col, end_row, end_col)

        if start_row not in self.current_line_exprs:
            self.current_line_exprs[start_row] = []

        self.current_line_exprs[start_row].append((expr_type, expr_text, pos))
        logger.debug("提取表达式: 行号=%d, 类型=%s, 内容='%s'", start_row, ExprType(expr_type).name, expr_text)
