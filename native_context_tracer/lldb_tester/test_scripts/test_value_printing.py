import statistics
import time

import lldb
from tracer import sb_value_printer

format_sbvalue = sb_value_printer.format_sbvalue
PERF_RUNS = 100  # Number of times to run each formatter for performance measurement


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
        if actual_value is None:
            raise AssertionError(f"Field '{field_name}' not found in struct '{struct_name}'")

        # 检查是否为浮点数值
        try:
            expected_float = float(expected_value)
            actual_float = float(actual_value)
            # 使用容差比较浮点数
            if abs(expected_float - actual_float) > 1e-6:
                raise AssertionError(
                    f"Field '{field_name}' in struct '{struct_name}' mismatch. "
                    f"Expected float value {expected_float}, got {actual_float}"
                )
        except (ValueError, TypeError):
            # 非浮点数，进行直接比较
            if actual_value != expected_value:
                raise AssertionError(
                    f"Field '{field_name}' in struct '{struct_name}' mismatch. "
                    f"Expected '{expected_value}', got '{actual_value}'"
                )
    return struct


def verify_struct_pointer(frame, ptr_name, struct_name):
    """验证结构体指针变量"""
    ptr = frame.FindVariable(ptr_name)
    if not ptr.IsValid():
        raise AssertionError(f"Failed to find pointer '{ptr_name}'")

    # 验证指针类型
    if "SimpleStruct *" in ptr.GetTypeName().lower():
        raise AssertionError(f"Expected pointer type for '{ptr_name}', got '{ptr.GetTypeName()}'")

    # 验证指向的结构体
    struct = frame.FindVariable(struct_name)
    if not struct.IsValid():
        raise AssertionError(f"Failed to find struct '{struct_name}'")

    ptr_addr = ptr.GetValueAsUnsigned()
    struct_addr = struct.GetLoadAddress()
    if ptr_addr != struct_addr:
        raise AssertionError(
            f"Pointer address mismatch for '{ptr_name}'. Expected {hex(struct_addr)}, got {hex(ptr_addr)}"
        )

    # 验证解引用后的值
    deref = ptr.Dereference()
    if not deref.IsValid():
        raise AssertionError(f"Failed to dereference pointer '{ptr_name}'")

    # 比较结构体字段
    for i in range(struct.GetNumChildren()):
        field_name = struct.GetChildAtIndex(i).GetName()
        if not field_name:
            continue

        expected_value = get_field_value(struct, field_name)
        actual_value = get_field_value(deref, field_name)

        if expected_value != actual_value:
            raise AssertionError(
                f"Field '{field_name}' mismatch for '{ptr_name}->{field_name}'. "
                f"Expected '{expected_value}', got '{actual_value}'"
            )

    return ptr


def verify_circular_ref(frame, var_name):
    """验证循环引用"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    var_str = format_sbvalue(var, max_depth=20)
    if "circular reference" not in var_str:
        raise AssertionError(f"Circular reference not detected in '{var_name}'")
    return var


def verify_union(frame, var_name, expected_field, expected_value):
    """验证联合体变量"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Failed to find variable '{var_name}'")

    active_field = get_field_value(var, expected_field)
    if active_field is None:
        raise AssertionError(f"Field '{expected_field}' not found in union '{var_name}'")

    # 检查是否为浮点数值
    try:
        expected_float = float(expected_value)
        actual_float = float(active_field)
        # 使用容差比较浮点数
        if abs(expected_float - actual_float) > 1e-6:
            raise AssertionError(
                f"Union field '{expected_field}' mismatch in '{var_name}'. "
                f"Expected float value {expected_float}, got {actual_float}"
            )
    except (ValueError, TypeError):
        # 非浮点数，进行直接比较
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
    context.run_command("b test_value_printing.c:70")
    context.run_command("continue")

    # 获取当前帧
    process = context.process
    thread = process.GetSelectedThread()
    frame = thread.GetSelectedFrame()

    # 验证变量前先输出格式化结果
    log_formatted_value(frame, "a")
    log_formatted_value(frame, "ptr")
    log_formatted_value(frame, "s")
    log_formatted_value(frame, "s_ptr")
    log_formatted_value(frame, "node1")
    log_formatted_value(frame, "u")
    log_formatted_value(frame, "str")
    log_formatted_value(frame, "ptr_arr")
    log_formatted_value(frame, "deep1")

    # 验证变量
    a = verify_basic_type(frame, "a", "int", "42")
    verify_pointer(frame, "ptr", a)
    # 更新字符字段期望值为ASCII数值 (88 = 'X')
    # 浮点数字段使用字符串表示进行比较
    s = verify_struct(frame, "s", {"x": "10", "y": "2.5", "z": "88"})
    verify_struct_pointer(frame, "s_ptr", "s")
    verify_circular_ref(frame, "node1")
    # 浮点数字段使用字符串表示进行比较
    verify_union(frame, "u", "float_val", "1.23")
    verify_string(frame, "str", "Hello, World!")
    verify_pointer_array(frame, "ptr_arr", [a.GetLoadAddress()] * 3)
    verify_circular_ref(frame, "deep1")

    print("Value printing tests passed (stepping method)")


def benchmark_formatting(context, var_name):
    """Benchmark the formatting performance for a specific variable"""
    if not context.wait_for_stop():
        raise AssertionError("Process not stopped at breakpoint")

    frame = context.target.GetProcess().GetSelectedThread().GetSelectedFrame()
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        raise AssertionError(f"Variable '{var_name}' not found")

    # Get the raw value for reference
    raw_value = var.GetValue()
    type_name = var.GetTypeName()

    # Run formatting multiple times for accurate measurement
    durations = []
    for _ in range(PERF_RUNS):
        start_time = time.perf_counter()
        formatted = sb_value_printer.format_sbvalue(var)
        end_time = time.perf_counter()
        durations.append(end_time - start_time)

    # Calculate performance metrics
    avg_time = statistics.mean(durations) * 1000  # Convert to milliseconds
    min_time = min(durations) * 1000
    max_time = max(durations) * 1000
    std_dev = statistics.stdev(durations) * 1000 if len(durations) > 1 else 0

    # Return the first formatted result and performance metrics
    return {
        "name": var_name,
        "type": type_name,
        "raw_value": raw_value,
        "formatted_value": formatted,
        "avg_time": avg_time,
        "min_time": min_time,
        "max_time": max_time,
        "std_dev": std_dev,
        "runs": PERF_RUNS,
    }


def test_sb_value_printer(context):
    """
    通过直接断点测试变量打印功能
    """
    # 设置断点并继续执行
    context.run_command("b test_value_printing.c:70")
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
    log_formatted_value(frame, "s_ptr")
    log_formatted_value(frame, "node1")
    log_formatted_value(frame, "u")
    log_formatted_value(frame, "str")
    log_formatted_value(frame, "ptr_arr")
    log_formatted_value(frame, "deep1")

    # 验证变量
    a = verify_basic_type(frame, "a", "int", "42")
    verify_pointer(frame, "ptr", a)
    # 更新字符字段期望值为ASCII数值 (88 = 'X')
    # 浮点数字段使用字符串表示进行比较
    s = verify_struct(frame, "s", {"x": "10", "y": "2.5", "z": "88"})
    verify_struct_pointer(frame, "s_ptr", "s")
    verify_circular_ref(frame, "node1")
    # 浮点数字段使用字符串表示进行比较
    verify_union(frame, "u", "float_val", "1.23")
    verify_string(frame, "str", "Hello, World!")
    verify_pointer_array(frame, "ptr_arr", [a.GetLoadAddress()] * 3)
    verify_circular_ref(frame, "deep1")

    print("Value printing tests passed (breakpoint method)")
    # List of variables to benchmark
    test_vars = ["a", "ptr", "s", "s_ptr", "node1", "u", "str", "ptr_arr", "deep1"]
    results = []

    print("\n=== Running Performance Benchmarks ===")
    print(f"Each formatter will be executed {PERF_RUNS} times\n")

    # Run benchmarks for each variable
    for var_name in test_vars:
        print(f"Benchmarking: {var_name}")
        result = benchmark_formatting(context, var_name)
        results.append(result)

    # Sort by average time (descending)
    results.sort(key=lambda x: x["avg_time"], reverse=True)

    # Print summary
    print("\n=== Performance Test Summary ===")
    print("Variables sorted by average formatting time (slowest first):")
    for result in results:
        print(
            f"{result['name']} ({result['type']}): "
            f"avg={result['avg_time']:.4f}ms, "
            f"min={result['min_time']:.4f}ms, "
            f"max={result['max_time']:.4f}ms, "
            f"stddev={result['std_dev']:.4f}ms"
        )

    # Print example formatted value (the slowest one)
    slowest = results[0]
    print(f"\nExample formatted value ({slowest['name']}):")
    print("-" * 80)
    print(slowest["formatted_value"])
    print("-" * 80)

    print("\nPerformance tests completed")
