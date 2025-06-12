import lldb
from tracer import sb_value_printer

format_sbvalue = sb_value_printer.format_sbvalue


def log_formatted_value(frame, var_name):
    """记录并输出变量的格式化表示"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        print(f"[WARNING] Variable '{var_name}' not found")
        return

    formatted = format_sbvalue(var)
    print(f"\n[FORMATTED VALUE] {var_name}:")
    print("-" * 80)
    print(formatted)
    print("-" * 80)


def get_field_value(struct, field_name):
    """获取结构体字段的值，根据类型智能返回"""
    field = struct.GetChildMemberWithName(field_name)
    if not field.IsValid():
        return None

    # 获取类型信息
    type_class = field.GetType().GetTypeClass()
    basic_type = field.GetType().GetBasicType()

    # 处理字符类型 - 使用基本类型枚举
    if basic_type in (lldb.eBasicTypeChar, lldb.eBasicTypeSignedChar, lldb.eBasicTypeUnsignedChar):
        # 直接获取字符值
        value = field.GetValueAsUnsigned()
        return str(value) if value is not None else None

    # 处理基本类型值
    value = field.GetValue()
    if value is not None:
        return value

    # 默认返回字符串表示
    return field.GetSummary() or str(field)


def verify_basic_type(frame, var_name, expected_type, expected_value):
    """验证基本类型变量"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    var_str = format_sbvalue(var)
    actual_type = var.GetType().GetName()
    if expected_type not in actual_type:
        raise AssertionError(f"Type mismatch for '{var_name}'. Expected '{expected_type}', got '{actual_type}'")

    actual_value = var.GetValue()
    if actual_value != expected_value:
        raise AssertionError(f"Value mismatch for '{var_name}'. Expected '{expected_value}', got '{actual_value}'")
    return var


def verify_pointer(frame, ptr_name, target_var):
    """验证指针变量"""
    ptr = frame.FindVariable(ptr_name)
    if not ptr.IsValid():
        raise AssertionError(f"Failed to find pointer '{ptr_name}'")

    ptr_addr = ptr.GetValueAsUnsigned()
    target_addr = target_var.AddressOf().GetValueAsUnsigned()
    if ptr_addr != target_addr:
        raise AssertionError(
            f"Pointer address mismatch for '{ptr_name}'. Expected {hex(target_addr)}, got {hex(ptr_addr)}"
        )
    return ptr


def verify_struct(frame, struct_name, expected_fields):
    """验证结构体变量"""
    struct = frame.FindVariable(struct_name)
    if not struct.IsValid():
        raise AssertionError(f"Failed to find struct '{struct_name}'")

    for field_name, expected_value in expected_fields.items():
        actual_value = get_field_value(struct, field_name)
        if actual_value != expected_value:
            raise AssertionError(
                f"Field '{field_name}' in struct '{struct_name}' mismatch. "
                f"Expected '{expected_value}', got '{actual_value}'"
            )
    return struct


def verify_circular_ref(frame, var_name):
    """验证循环引用"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    var_str = format_sbvalue(var)
    if "circular reference" not in var_str:
        raise AssertionError(f"Circular reference not detected in '{var_name}'")
    return var


def verify_union(frame, var_name, expected_field, expected_value):
    """验证联合体变量"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    active_field = get_field_value(var, expected_field)
    if active_field != expected_value:
        raise AssertionError(
            f"Union field '{expected_field}' mismatch in '{var_name}'. "
            f"Expected '{expected_value}', got '{active_field}'"
        )
    return var


def verify_string(frame, var_name, expected_value):
    """验证字符串变量"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    summary = var.GetSummary()
    if expected_value not in summary:
        raise AssertionError(f"String mismatch for '{var_name}'. Expected '{expected_value}', got '{summary}'")
    return var


def verify_pointer_array(frame, var_name, expected_values):
    """验证指针数组"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    num_children = var.GetNumChildren()
    if num_children != len(expected_values):
        raise AssertionError(
            f"Array length mismatch for '{var_name}'. Expected {len(expected_values)}, got {num_children}"
        )

    for i in range(num_children):
        element = var.GetChildAtIndex(i)
        actual_value = element.GetValueAsUnsigned()
        if actual_value != expected_values[i]:
            raise AssertionError(
                f"Array element {i} mismatch in '{var_name}'. "
                f"Expected {hex(expected_values[i])}, got {hex(actual_value)}"
            )
    return var


def test_value_printing(context):
    """
    通过步进执行测试变量打印功能
    """
    # 确保程序已停止
    if not context.wait_for_stop():
        raise AssertionError("Process not stopped at breakpoint")

    # 设置断点并继续执行
    context.run_command("b test_value_printing.c:66")
    context.run_command("continue")

    # 获取当前帧
    process = context.process
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # 验证变量前先输出格式化结果
    log_formatted_value(frame, "a")
    log_formatted_value(frame, "ptr")
    log_formatted_value(frame, "s")
    log_formatted_value(frame, "node1")
    log_formatted_value(frame, "u")
    log_formatted_value(frame, "str")
    log_formatted_value(frame, "ptr_arr")
    log_formatted_value(frame, "deep1")

    # 验证变量
    a = verify_basic_type(frame, "a", "int", "42")
    verify_pointer(frame, "ptr", a)
    # 更新字符字段期望值为ASCII数值 (88 = 'X')
    verify_struct(frame, "s", {"x": "10", "y": "2.5", "z": "88"})
    verify_circular_ref(frame, "node1")
    verify_union(frame, "u", "float_val", "1.23")
    verify_string(frame, "str", "Hello, World!")
    verify_pointer_array(frame, "ptr_arr", [a.GetLoadAddress()] * 3)
    verify_circular_ref(frame, "deep1")

    print("Value printing tests passed (stepping method)")


def test_sb_value_printer(context):
    """
    通过直接断点测试变量打印功能
    """
    # 设置断点并继续执行
    context.run_command("b test_value_printing.c:66")
    context.run_command("continue")

    # 确保程序已停止
    if not context.wait_for_stop():
        raise AssertionError("Process not stopped after continue")

    # 获取当前帧
    frame = context.target.GetProcess().GetSelectedThread().GetSelectedFrame()

    # 验证变量前先输出格式化结果
    log_formatted_value(frame, "a")
    log_formatted_value(frame, "ptr")
    log_formatted_value(frame, "s")
    log_formatted_value(frame, "node1")
    log_formatted_value(frame, "u")
    log_formatted_value(frame, "str")
    log_formatted_value(frame, "ptr_arr")
    log_formatted_value(frame, "deep1")

    # 验证变量
    a = verify_basic_type(frame, "a", "int", "42")
    verify_pointer(frame, "ptr", a)
    # 更新字符字段期望值为ASCII数值 (88 = 'X')
    verify_struct(frame, "s", {"x": "10", "y": "2.5", "z": "88"})
    verify_circular_ref(frame, "node1")
    verify_union(frame, "u", "float_val", "1.23")
    verify_string(frame, "str", "Hello, World!")
    verify_pointer_array(frame, "ptr_arr", [a.GetLoadAddress()] * 3)
    verify_circular_ref(frame, "deep1")

    print("Value printing tests passed (breakpoint method)")
