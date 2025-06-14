import re
from enum import Enum
from typing import Optional


class ExprType(Enum):
    """简化后的表达式类型枚举，只保留核心类型"""

    VARIABLE_ACCESS = 1  # 变量访问 (identifier)
    POINTER_DEREF = 2  # 指针解引用 (*expr)
    ADDRESS_OF = 3  # 取地址 (&expr)
    MEMBER_ACCESS = 4  # 成员访问 (obj.field, ptr->field)
    ASSIGNMENT_TARGET = 5  # 赋值目标 (左侧)
    TEMPLATE_INSTANCE = 6  # 模板实例化
    SUBSCRIPT_EXPRESSION = 7  # 下标访问


class ExprTypeHandler:
    """处理表达式类型映射"""

    EXPR_TYPES = {
        "identifier": ExprType.VARIABLE_ACCESS,
        "field_identifier": ExprType.VARIABLE_ACCESS,
        "pointer_expression": ExprType.POINTER_DEREF,
        "address_expression": ExprType.ADDRESS_OF,
        "field_expression": ExprType.MEMBER_ACCESS,
        "subscript_expression": ExprType.SUBSCRIPT_EXPRESSION,
        "assignment_expression": ExprType.ASSIGNMENT_TARGET,
        "qualified_identifier": ExprType.VARIABLE_ACCESS,
    }

    @staticmethod
    def get_expr_type(node_type: str) -> Optional[ExprType]:
        """获取节点类型对应的表达式类型"""
        return ExprTypeHandler.EXPR_TYPES.get(node_type)
