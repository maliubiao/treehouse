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

    instructions = dis.get_instructions(code)
    line_vars = defaultdict(set)
    current_line = code.co_firstlineno

    for instr in instructions:
        # Python 3.12+ 使用 positions 属性而不是 starts_line
        if PYTHON_312_OR_LATER and hasattr(instr, "positions"):
            if instr.positions.lineno is not None:
                current_line = instr.positions.lineno
        elif instr.starts_line is not None:
            current_line = instr.starts_line

        var_name = None

        # 处理变量操作
        if "STORE" in instr.opname:
            if instr.opname in ("STORE_FAST", "STORE_DEREF", "STORE_GLOBAL", "STORE_NAME"):
                var_name = instr.argval
            # 处理 Python 3.11+ 的新操作码
            elif PYTHON_311_OR_LATER and instr.opname in ("STORE_FAST_LOAD_FAST", "STORE_FAST_STORE_FAST"):
                var_name = instr.argval
                line_vars[current_line].add(var_name)
                continue
            # 处理 Python 3.13 的新操作码
            elif PYTHON_313_OR_LATER and instr.opname in (
                "STORE_FAST_LOAD_FAST",
                "LOAD_FAST_LOAD_FAST",
                "STORE_FAST_STORE_FAST",
            ):
                var_name = instr.argval
                line_vars[current_line].update([var_name])
                continue

        elif "LOAD" in instr.opname:
            if instr.opname in ("LOAD_FAST", "LOAD_DEREF", "LOAD_CLOSURE", "LOAD_GLOBAL", "LOAD_NAME"):
                var_name = instr.argval
            # 处理 Python 3.11+ 的新操作码
            elif PYTHON_311_OR_LATER and instr.opname in ("LOAD_FAST_AND_CLEAR", "LOAD_FAST_CHECK"):
                var_name = instr.argval
            # 处理 Python 3.13 的新操作码
            elif PYTHON_313_OR_LATER and instr.opname in (
                "LOAD_FAST_LOAD_FAST",
                "LOAD_FAST_AND_CLEAR",
                "LOAD_FAST_CHECK",
            ):
                var_name = instr.argval
                line_vars[current_line].update([var_name])
                continue

        if var_name:
            line_vars[current_line].add(var_name)

    # 转换数据结构并排序
    return dict(sorted(line_vars.items()))


def analyze_variable_list(func_or_code):
    """
    分析函数或代码对象的字节码，返回按行号排序的变量访问列表
    返回格式：[['var1','var2'], ['var3'], ...]
    """
    var_analysis = analyze_variable_ops(func_or_code)
    return [var_analysis[line] for line in sorted(var_analysis.keys())]


# 增强的示例用法
if __name__ == "__main__":
    # 测试函数对象
    def test_func():
        a = 1  # 行号 97
        b = 2  # 行号 98
        c = a + b  # 行号 99
        print(c)  # 行号 100
        return c  # 行号 101

    # 测试代码对象
    frame = inspect.currentframe()
    code_obj = frame.f_code

    for target in [test_func, code_obj]:
        var_analysis = analyze_variable_ops(target)
        list_analysis = analyze_variable_list(target)

        if inspect.iscode(target):
            print(f"\nAnalysis for code object: {target.co_name}")
        else:
            print(f"\nFile: {test_func.__code__.co_filename}, Function: {test_func.__name__}")

        for line, variables in var_analysis.items():
            print(f"Line {line}: {variables}")

        print("\nList Analysis:")
        for i, variables in enumerate(list_analysis):
            line = sorted(var_analysis.keys())[i]
            print(f"Line {line}: {variables}")
