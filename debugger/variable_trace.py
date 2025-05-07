import dis
import inspect
import sys
from collections import defaultdict

# 定义Python版本常量
PYTHON_VERSION = sys.version_info
PYTHON_311_OR_LATER = PYTHON_VERSION >= (3, 11)
PYTHON_312_OR_LATER = PYTHON_VERSION >= (3, 12)
PYTHON_313_OR_LATER = PYTHON_VERSION >= (3, 13)


def analyze_variable_ops(func_or_code):
    """
    分析函数或代码对象的字节码，返回按行号组织的变量访问记录
    返回格式：{
       行号: [变量名1, 变量名2...],
    }
    """
    # 处理函数或代码对象
    if inspect.iscode(func_or_code):
        code = func_or_code
    else:
        code = func_or_code.__code__

    instructions = list(dis.get_instructions(code))  # 转换为列表以便索引访问
    line_vars = defaultdict(set)
    current_line = code.co_firstlineno

    for i, instr in enumerate(instructions):
        # Python 3.12+ 使用 positions 属性而不是 starts_line
        if PYTHON_312_OR_LATER and hasattr(instr, "positions"):
            if instr.positions.lineno is not None:
                current_line = instr.positions.lineno
        elif instr.starts_line is not None:
            current_line = instr.starts_line

        var_name = None

        # 处理变量操作
        if "STORE" in instr.opname:
            if instr.opname in (
                "STORE_FAST",
                "STORE_DEREF",
                "STORE_GLOBAL",
                "STORE_NAME",
            ):
                var_name = instr.argval
            # 处理 Python 3.11+ 的新操作码
            elif PYTHON_311_OR_LATER and instr.opname in (
                "STORE_FAST_LOAD_FAST",
                "STORE_FAST_STORE_FAST",
            ):
                var_name = instr.argval
                line_vars[current_line].add(var_name[0])
                line_vars[current_line].add(var_name[1])
                continue
            # 处理 Python 3.13 的新操作码
            elif PYTHON_313_OR_LATER and instr.opname in (
                "STORE_FAST_LOAD_FAST",
                "LOAD_FAST_LOAD_FAST",
                "STORE_FAST_STORE_FAST",
            ):
                var_name = instr.argval
                line_vars[current_line].add(var_name[0])
                line_vars[current_line].add(var_name[1])
                continue

        elif "LOAD" in instr.opname:
            if instr.opname in (
                "LOAD_FAST",
                "LOAD_DEREF",
                "LOAD_CLOSURE",
                "LOAD_GLOBAL",
                "LOAD_NAME",
            ):
                var_name = instr.argval
            # 处理 Python 3.11+ 的新操作码
            elif PYTHON_311_OR_LATER and instr.opname in (
                "LOAD_FAST_AND_CLEAR",
                "LOAD_FAST_CHECK",
            ):
                var_name = instr.argval
            # 处理 Python 3.13 的新操作码
            elif PYTHON_313_OR_LATER and instr.opname in (
                "LOAD_FAST_LOAD_FAST",
                "LOAD_FAST_AND_CLEAR",
                "LOAD_FAST_CHECK",
            ):
                var_name = instr.argval
                line_vars[current_line].add(var_name[0])
                line_vars[current_line].add(var_name[1])
                continue
            # 处理 LOAD_ATTR
            elif instr.opname == "LOAD_ATTR":
                # 检查前一条指令是否是 LOAD_FAST 或其他加载指令
                if i > 0 and instructions[i - 1].opname in ("LOAD_FAST", "LOAD_GLOBAL", "LOAD_NAME"):
                    obj_name = instructions[i - 1].argval
                    attr_name = instr.argval
                    var_name = f"{obj_name}.{attr_name}"
                    if attr_name in line_vars[current_line]:
                        line_vars[current_line].remove(attr_name)
                    if obj_name in line_vars[current_line]:
                        line_vars[current_line].remove(obj_name)

        if var_name:
            line_vars[current_line].add(var_name)

    # 转换数据结构并排序
    return line_vars


if __name__ == "__main__":
    # 测试函数对象
    def test_func():
        a = 1  # 行号 97
        b = 2  # 行号 98
        c = a + b  # 行号 99
        print(c)  # 行号 100
        return c  # 行号 101

    # 测试属性访问
    def test_attr():
        obj = type("Test", (), {"x": 1, "y": 2})()  # 行号 105
        a = obj.x  # 行号 106
        b = obj.y  # 行号 107
        return a + b  # 行号 108

    # 测试代码对象
    frame = inspect.currentframe()
    code_obj = frame.f_code

    for target in [test_func, test_attr, code_obj]:
        var_analysis = analyze_variable_ops(target)

        if inspect.iscode(target):
            print(f"\nAnalysis for code object: {target.co_name}")
        else:
            print(f"\nFile: {target.__code__.co_filename}, Function: {target.__name__}")

        for line, variables in sorted(var_analysis.items()):
            print(f"Line {line}: {variables}")
