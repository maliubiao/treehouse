# pylint: skip-file
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合语法分析测试样本，包含：
- 多种变量声明方式
- 复杂函数参数类型
- 装饰器应用
- 类方法与属性
- 作用域链引用
- 类型注解
- 异常处理中的变量
"""

import math
from typing import Callable, Dict, List, Optional


def a():
    f().b()
    f.b()
    f()
    f(1)
    f(b())


# 全局变量声明
global_var = 42
_GLOBAL_DICT: Dict[str, int] = {"default": 0}
__magic__ = 3.14


def decorator(func: Callable) -> Callable:
    """简单装饰器"""

    def wrapper(*args, **kwargs):
        print(f"Calling {func.__name__}")
        return func(*args, **kwargs)

    return wrapper


@decorator
@decorator
def complex_function(
    param1: int, param2: str = "default", *args: List[float], **kwargs: Dict[str, bool]
) -> Optional[float]:
    """复杂参数声明的测试函数"""
    local_var = param1 * 2
    (a, (b, c)) = (1, (2, 3))  # 嵌套解包赋值
    d, e = [4, 5]
    f: List[int] = []
    g = h = 10  # 链式赋值

    try:
        result = local_var / global_var
    except ZeroDivisionError as e:
        print(f"Error: {e}")
        result = None

    # 列表推导式
    squares = [i**2 for i in range(10)]

    # 使用全局变量
    _GLOBAL_DICT["new"] = len(param2)

    return result if result else __magic__


class SampleClass:
    """测试类定义"""

    class_attr: int = 100
    _protected_attr: str = "protected"

    def __init__(self, value: float):
        self.instance_attr = value
        self.__dict__["dynamic_attr"] = 42  # 特殊属性设置方式

    @classmethod
    def class_method(cls) -> None:
        """类方法测试"""
        cls.class_attr += 1

    @decorator
    def instance_method(self, x: int, y: int = 10) -> int:
        """实例方法测试"""
        new_var = x + y + self.class_attr
        # 使用数学模块
        return math.isqrt(new_var)  # Python 3.8+ 特性

    @staticmethod
    def static_method() -> dict:
        """静态方法测试"""
        return {"key": _GLOBAL_DICT.copy()}


# 异步函数测试
async def async_example():
    """异步函数定义"""
    future = asyncio.Future()
    await future


# lambda表达式
lambda_expr = lambda x: x**2

# 类型注解的特殊用法
x: int
y: List[float] = [1.0, 2.0]

if __name__ == "__main__":
    obj = SampleClass(3.14)
    print(complex_function(10, "test"))
