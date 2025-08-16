import dis
import inspect
import sys
import types
from collections import defaultdict
from typing import Any, Callable, DefaultDict, Dict, List, Set, Union

# 定义Python版本常量
PYTHON_VERSION = sys.version_info
PYTHON_311_OR_LATER = PYTHON_VERSION >= (3, 11)
PYTHON_312_OR_LATER = PYTHON_VERSION >= (3, 12)
PYTHON_313_OR_LATER = PYTHON_VERSION >= (3, 13)


def analyze_variable_ops(func_or_code: Union[types.CodeType, Callable[..., Any]]) -> DefaultDict[int, Set[str]]:
    """
    分析函数或代码对象的字节码，返回按行号组织的变量访问记录。

    Args:
        func_or_code: 要分析的函数或代码对象。

    Returns:
        一个默认字典，将行号映射到在该行访问的变量名集合。
        例如: {97: {'a'}, 99: {'a', 'b', 'c'}}
    """
    # 处理函数或代码对象
    if inspect.iscode(func_or_code):
        code = func_or_code
    else:
        code = func_or_code.__code__

    instructions = list(dis.get_instructions(code))  # 转换为列表以便索引访问
    line_vars: DefaultDict[int, Set[str]] = defaultdict(set)
    current_line = code.co_firstlineno

    for i, instr in enumerate(instructions):
        # Python 3.11+ (not 3.12) uses starts_line. 3.12+ uses positions.
        if PYTHON_312_OR_LATER and hasattr(instr, "positions"):
            if instr.positions and instr.positions.lineno is not None:
                current_line = instr.positions.lineno
        elif instr.starts_line is not None:
            current_line = instr.starts_line

        var_name: Union[str, None] = None
        opname: str = instr.opname

        # --- 分类处理操作码 ---

        # 简单存储操作
        if opname in ("STORE_FAST", "STORE_DEREF", "STORE_GLOBAL", "STORE_NAME"):
            var_name = instr.argval

        # 属性存储操作 (STORE_ATTR)
        elif opname == "STORE_ATTR":
            # 启发式方法: 检查前一条指令以构建 `obj.attr` 形式。
            if i > 0:
                prev_instr = instructions[i - 1]
                obj_name: Union[str, None] = None

                load_opnames = {"LOAD_FAST", "LOAD_GLOBAL", "LOAD_NAME"}
                if PYTHON_312_OR_LATER:
                    load_opnames.add("LOAD_FAST_CHECK")

                if prev_instr.opname in load_opnames:
                    obj_name = prev_instr.argval
                elif PYTHON_313_OR_LATER and prev_instr.opname == "LOAD_FAST_LOAD_FAST":
                    # 对于 `obj.attr = val`, 字节码为 `LOAD_FAST_LOAD_FAST (val, obj)`, 然后 `STORE_ATTR attr`。
                    # 对象是第二个加载的。
                    if isinstance(prev_instr.argval, (list, tuple)) and len(prev_instr.argval) == 2:
                        obj_name = prev_instr.argval[1]

                if obj_name:
                    attr_name = instr.argval
                    var_name = f"{obj_name}.{attr_name}"
                    # 对象本身已被加载，我们用更具体的属性访问替换它。
                    if obj_name in line_vars[current_line]:
                        line_vars[current_line].remove(obj_name)

        # Python 3.13+ 多变量存储操作
        elif PYTHON_313_OR_LATER and opname in (
            "STORE_FAST_STORE_FAST",
            "STORE_FAST_LOAD_FAST",
        ):
            if isinstance(instr.argval, (list, tuple)):
                line_vars[current_line].update(instr.argval)
            continue  # 已处理，跳到下一条指令

        # 简单加载操作
        elif opname in ("LOAD_FAST", "LOAD_DEREF", "LOAD_CLOSURE", "LOAD_GLOBAL", "LOAD_NAME"):
            var_name = instr.argval

        # Python 3.12+ 新增加载操作
        elif PYTHON_312_OR_LATER and opname in ("LOAD_FAST_AND_CLEAR", "LOAD_FAST_CHECK"):
            var_name = instr.argval

        # Python 3.13+ 多变量加载操作
        elif PYTHON_313_OR_LATER and opname == "LOAD_FAST_LOAD_FAST":
            if isinstance(instr.argval, (list, tuple)):
                line_vars[current_line].update(instr.argval)
            continue  # 已处理，跳到下一条指令

        # 属性加载操作 (LOAD_ATTR)
        elif opname == "LOAD_ATTR":
            # 启发式方法: 检查前一条指令以构建 `obj.attr` 形式。
            if i > 0:
                prev_instr = instructions[i - 1]
                load_opnames = {"LOAD_FAST", "LOAD_GLOBAL", "LOAD_NAME"}
                if PYTHON_312_OR_LATER:
                    load_opnames.add("LOAD_FAST_CHECK")

                if prev_instr.opname in load_opnames:
                    obj_name = prev_instr.argval
                    attr_name = instr.argval
                    var_name = f"{obj_name}.{attr_name}"
                    # 对象本身已被加载，我们用更具体的属性访问替换它。
                    if obj_name in line_vars[current_line]:
                        line_vars[current_line].remove(obj_name)

        # # super() 属性加载
        # elif opname == "LOAD_SUPER_ATTR":
        #     attr_name = instr.argval
        #     var_name = f"super().{attr_name}"
        #     # super() 调用会隐式加载 'super', '__class__', 和 'self'。
        #     # 为了提供更清晰、更符合源代码意图的分析，我们移除这些实现细节。
        #     line_vars[current_line].discard("super")
        #     line_vars[current_line].discard("__class__")
        #     line_vars[current_line].discard("self")

        if var_name:
            line_vars[current_line].add(var_name)

    return line_vars


if __name__ == "__main__":
    # --- Test Functions and Classes ---

    def test_func():
        a = 1
        b = 2
        c = a + b
        print(c)
        return c

    def test_attr():
        # This weird definition is to avoid `obj` having `__code__`
        obj = type("Test", (), {"x": 1, "y": 2})()
        a = obj.x
        b = obj.y
        return a + b

    def test_store_attr():
        # This weird definition is to avoid `obj` having `__code__`
        obj = type("Test", (), {"z": 0})()
        val = 3
        obj.z = val  # This should generate STORE_ATTR
        return obj.z

    class Base:
        def __init__(self) -> None:
            self.x = 10

        def get_x(self) -> int:
            return self.x

    # class Derived(Base):
    #     def __init__(self) -> None:
    #         super().__init__()
    #         self.y = 20

    #     def get_x_from_super(self) -> int:
    #         return super().x  # Generates LOAD_SUPER_ATTR

    #     def get_x_method_from_super(self) -> int:
    #         return super().get_x()  # Generates LOAD_SUPER_ATTR

    # def test_super_attr():
    #     d = Derived()
    #     a = d.get_x_from_super()
    #     b = d.get_x_method_from_super()
    #     return a, b

    # --- Assertion-based Test Suite ---
    print("\n--- Running Automated Tests ---")

    all_tests_passed = True

    def run_test(func: Callable[..., Any], expected: Dict[str, List[str]]) -> None:
        global all_tests_passed
        print(f"\n--- Testing function: {func.__name__} ---")
        analysis = analyze_variable_ops(func)
        try:
            source_lines, start_line = inspect.getsourcelines(func)
            line_mapping = {line.strip(): start_line + i for i, line in enumerate(source_lines)}

            for code_line, variables in expected.items():
                target_line_no = line_mapping[code_line]
                analyzed_vars = sorted(list(analysis.get(target_line_no, set())))
                expected_vars = sorted(variables)
                assert analyzed_vars == expected_vars, (
                    f"Failed on line '{code_line}'\n  Expected: {expected_vars}\n  Got:      {analyzed_vars}"
                )
            print(f"PASS: {func.__name__}")
        except (AssertionError, KeyError) as e:
            print(f"FAIL: {func.__name__}")
            print(f"  Error: {e}")
            print("  Full analysis result:")
            for line, variables in sorted(analysis.items()):
                print(f"    Line {line}: {sorted(list(variables))}")
            all_tests_passed = False

    # Test case definitions
    run_test(
        test_func,
        {
            "a = 1": ["a"],
            "b = 2": ["b"],
            "c = a + b": ["a", "b", "c"],
            "print(c)": ["c", "print"],
            "return c": ["c"],
        },
    )

    run_test(
        test_attr,
        {
            'obj = type("Test", (), {"x": 1, "y": 2})()': ["obj", "type"],
            "a = obj.x": ["a", "obj.x"],
            "b = obj.y": ["b", "obj.y"],
            "return a + b": ["a", "b"],
        },
    )

    # This is the key test for the fix in Python 3.13
    run_test(
        test_store_attr,
        {
            'obj = type("Test", (), {"z": 0})()': ["obj", "type"],
            "val = 3": ["val"],
            "obj.z = val  # This should generate STORE_ATTR": ["obj.z", "val"],
            "return obj.z": ["obj.z"],
        },
    )

    # run_test(
    #     Derived.get_x_from_super,
    #     {
    #         "return super().x  # Generates LOAD_SUPER_ATTR": ["super().x"],
    #     },
    # )

    # run_test(
    #     Derived.get_x_method_from_super,
    #     {
    #         "return super().get_x()  # Generates LOAD_SUPER_ATTR": ["super().get_x"],
    #     },
    # )

    # if PYTHON_312_OR_LATER:
    #     run_test(
    #         test_super_attr,
    #         {
    #             "d = Derived()": ["d", "Derived"],
    #             "a = d.get_x_from_super()": ["a", "d.get_x_from_super"],
    #             "b = d.get_x_method_from_super()": ["b", "d.get_x_method_from_super"],
    #             "return a, b": ["a", "b"],
    #         },
    #     )

    print("\n--- Test Summary ---")
    if all_tests_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed.")
        sys.exit(1)
