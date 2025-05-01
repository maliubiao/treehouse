import dis
import inspect
from collections import defaultdict


def analyze_variable_ops(func_or_code):
    """
    分析函数或代码对象的字节码，返回按行号组织的变量操作记录
    返回格式：{
       行号: {
           'loads': [变量名1, 变量名2...],
           'stores': [变量名1, 变量名2...]
       }
    }
    """
    # 处理函数或代码对象
    if inspect.iscode(func_or_code):
        code = func_or_code
    else:
        code = func_or_code.__code__

    instructions = dis.get_instructions(code)
    line_ops = defaultdict(lambda: {"loads": set(), "stores": set()})
    current_line = code.co_firstlineno

    for instr in instructions:
        if instr.starts_line is not None:
            current_line = instr.starts_line

        var_name = None
        op_type = None

        # 处理存储操作
        if "STORE" in instr.opname:
            op_type = "stores"
            if instr.opname in ("STORE_FAST", "STORE_DEREF", "STORE_GLOBAL", "STORE_NAME"):
                var_name = instr.argval

        # 处理加载操作
        elif "LOAD" in instr.opname:
            op_type = "loads"
            if instr.opname in ("LOAD_FAST", "LOAD_DEREF", "LOAD_CLOSURE", "LOAD_GLOBAL", "LOAD_NAME"):
                var_name = instr.argval

        if var_name and op_type:
            line_ops[current_line][op_type].add(var_name)

    # 转换数据结构并排序
    return {
        line: {"loads": sorted(ops["loads"]), "stores": sorted(ops["stores"])} for line, ops in sorted(line_ops.items())
    }


def analyze_variable_list(func_or_code):
    """
    分析函数或代码对象的字节码，返回按行号排序的变量操作列表
    返回格式：[['var1','var2'], ['var3'], ...]
    """
    analysis = analyze_variable_ops(func_or_code)
    sorted_lines = sorted(analysis.keys())
    return [sorted(set(analysis[line]["loads"] + analysis[line]["stores"])) for line in sorted_lines]


# 增强的示例用法
if __name__ == "__main__":
    # 测试函数对象
    def test_func():
        a = 1  # 行号 55
        b = 2  # 行号 56
        c = a + b  # 行号 57
        print(c)  # 行号 58
        return c  # 行号 59

    # 测试代码对象
    frame = inspect.currentframe()
    code_obj = frame.f_code

    for target in [test_func, code_obj]:
        analysis = analyze_variable_ops(target)
        list_analysis = analyze_variable_list(target)

        if inspect.iscode(target):
            print(f"\nAnalysis for code object: {target.co_name}")
        else:
            print(f"\nFile: {test_func.__code__.co_filename}, Function: {test_func.__name__}")

        for line, ops in analysis.items():
            print(f"Line {line}:")
            print(f"  STORES: {ops['stores']}")
            print(f"  LOADS: {ops['loads']}")

        print("\nList Analysis:")
        for i, vars in enumerate(list_analysis):
            line = sorted(analysis.keys())[i]
            print(f"Line {line}: {vars}")
