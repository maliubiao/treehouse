import lldb
from tracer import sb_value_printer

format_sbvalue = sb_value_printer.format_sbvalue


def verify_basic_type(frame, var_name, expected_value):
    """验证基本类型变量"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    var_str = format_sbvalue(var)
    if expected_value not in var_str:
        raise AssertionError(f"Basic type formatting failed. Expected '{expected_value}', got: {var_str}")
    return var


def verify_pointer(frame, ptr_name, target_var):
    """验证指针变量"""
    ptr = frame.FindVariable(ptr_name)
    if not ptr.IsValid():
        raise AssertionError(f"Failed to find pointer '{ptr_name}'")

    ptr_addr = ptr.GetValueAsUnsigned()
    target_addr = target_var.AddressOf().GetValueAsUnsigned()
    if ptr_addr != target_addr:
        raise AssertionError(f"Pointer address mismatch. Expected {hex(target_addr)}, got {hex(ptr_addr)}")

    ptr_str = format_sbvalue(ptr)
    if "->" not in ptr_str:
        raise AssertionError(f"Pointer formatting failed. Expected '->', got: {ptr_str}")
    return ptr


def verify_struct(frame, struct_name, expected_fields):
    """验证结构体变量"""
    struct = frame.FindVariable(struct_name)
    if not struct.IsValid():
        raise AssertionError(f"Failed to find struct '{struct_name}'")

    struct_str = format_sbvalue(struct)
    for field in expected_fields:
        if field not in struct_str:
            raise AssertionError(f"Struct field missing: {field} in {struct_str}")
    return struct


def verify_circular_ref(frame, var_name):
    """验证循环引用"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    var_str = format_sbvalue(var)
    if "circular reference" not in var_str:
        raise AssertionError("Circular reference not detected")
    return var


def verify_union(frame, var_name, expected_field, expected_value):
    """验证联合体变量"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    var_str = format_sbvalue(var)
    if expected_field not in var_str or expected_value not in var_str:
        raise AssertionError(f"Union formatting failed: {var_str}")
    return var


def verify_string(frame, var_name, expected_value):
    """验证字符串变量"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    var_str = format_sbvalue(var)
    if expected_value not in var_str:
        raise AssertionError(f"String formatting failed: {var_str}")
    return var


def verify_pointer_array(frame, var_name, expected_index, expected_value):
    """验证指针数组"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    var_str = format_sbvalue(var)
    if expected_index not in var_str or expected_value not in var_str:
        raise AssertionError(f"Pointer array formatting failed: {var_str}")
    return var


def test_value_printing(context):
    """
    通过步进执行测试变量打印功能
    """
    # 确保程序已停止
    if not context.wait_for_stop():
        raise AssertionError("Process not stopped at breakpoint")

    # 设置断点并继续执行
    context.run_command("b test_value_printing.c:49")
    context.run_command("continue")

    # 获取当前帧
    process = context.process
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # 验证变量
    a = verify_basic_type(frame, "a", "(int) 42")
    verify_pointer(frame, "ptr", a)
    verify_struct(frame, "s", ["x: (int) 10", "y: (float) 2.5", "z: (char) 'X'"])
    verify_circular_ref(frame, "node1")
    verify_union(frame, "u", "float_val", "1.23")
    verify_string(frame, "str", '"Hello, World!"')
    verify_pointer_array(frame, "ptr_arr", "[0]: (int *)", "-> (int) 42")

    print("Value printing tests passed (stepping method)")


def test_sb_value_printer(context):
    """
    通过直接断点测试变量打印功能
    """
    # 设置断点并继续执行
    context.run_command("b test_value_printing.c:49")
    context.run_command("continue")

    # 确保程序已停止
    if not context.wait_for_stop():
        raise AssertionError("Process not stopped after continue")

    # 获取当前帧
    frame = context.target.GetProcess().GetSelectedThread().GetSelectedFrame()

    # 验证变量
    a = verify_basic_type(frame, "a", "(int) 42")
    verify_pointer(frame, "ptr", a)
    verify_struct(frame, "s", ["x: (int) 10", "y: (float) 2.5", "z: (char) 'X'"])
    verify_circular_ref(frame, "node1")
    verify_union(frame, "u", "float_val: (float) 1.23", "1.23")
    verify_string(frame, "str", '"Hello, World!"')
    verify_pointer_array(frame, "ptr_arr", "[0]: (int *)", "-> (int) 42")

    print("Value printing tests passed (breakpoint method)")
