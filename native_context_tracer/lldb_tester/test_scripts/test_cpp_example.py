import lldb
from tracer import sb_value_printer

format_sbvalue = sb_value_printer.format_sbvalue


def log_cpp_value(frame, var_name):
    """专门用于记录C++类型变量的格式化表示"""
    var = frame.FindVariable(var_name)
    if not var.IsValid():
        print(f"[WARNING] Variable '{var_name}' not found")
        return

    formatted = format_sbvalue(var)
    print(f"\n[C++ VALUE] {var_name} ({var.GetTypeName()}):")
    print("-" * 80)
    print(formatted)
    print("-" * 80)


def log_cpp_types(context):
    """记录各种C++类型的格式化值"""
    # 确保程序已停止
    if not context.wait_for_stop():
        print("[WARNING] Process not stopped at breakpoint")
        return

    # 获取当前帧
    frame = context.target.GetProcess().GetSelectedThread().GetSelectedFrame()

    # 基本类型
    log_cpp_value(frame, "a")
    log_cpp_value(frame, "b")

    # STL容器
    log_cpp_value(frame, "numbers")
    log_cpp_value(frame, "words")
    log_cpp_value(frame, "idToName")
    log_cpp_value(frame, "uniqueValues")
    log_cpp_value(frame, "nestedContainer")
    log_cpp_value(frame, "wordCount")
    log_cpp_value(frame, "uniqueNumbers")

    # 适配器容器
    log_cpp_value(frame, "numberQueue")
    log_cpp_value(frame, "wordStack")

    # 智能指针
    log_cpp_value(frame, "sharedObj")
    log_cpp_value(frame, "uniqueObj")
    log_cpp_value(frame, "weakObj")

    # 元组和pair
    log_cpp_value(frame, "person")
    log_cpp_value(frame, "complexTuple")

    # 线程相关
    log_cpp_value(frame, "mtx")
    log_cpp_value(frame, "atomicCounter")

    # 模板类
    log_cpp_value(frame, "doubleTemplate")
    log_cpp_value(frame, "stringTemplate")

    # 类对象
    log_cpp_value(frame, "obj")
    log_cpp_value(frame, "complexObj")

    # 深层嵌套结构体
    log_cpp_value(frame, "deepNested")
    log_cpp_value(frame, "deepNonCircular")


def run_test(context):
    """
    主测试函数 - 设置断点并记录C++类型值
    """
    # 设置断点
    context.run_command("b debug_break")
    context.run_command("continue")
    context.run_command("thread step-out")
    # 记录所有C++类型值
    log_cpp_types(context)
