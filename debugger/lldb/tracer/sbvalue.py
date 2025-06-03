from typing import Optional, Union

import lldb


def explore_sbvalue(value: lldb.SBValue, target: Optional[lldb.SBTarget] = None) -> str:
    """
    探索SBValue对象的所有API方法并返回结果表格

    参数:
        value (lldb.SBValue): 要探索的SBValue对象
        target (lldb.SBTarget, optional): 用于地址计算的目标对象，当需要GetAddress时使用

    返回:
        str: 包含所有方法调用结果的Markdown表格

    示例:
        >>> value = frame.FindVariable("my_var")
        >>> print(explore_sbvalue(value, target))
    """
    # 定义要探索的方法列表（无参数方法）
    methods = [
        ("GetByteSize", "size_t"),
        ("GetValue", "const char*"),
        ("GetValueType", "ValueType"),
        ("GetTypeName", "const char*"),
        ("GetDisplayTypeName", "const char*"),
        ("GetSummary", "const char*"),
        ("GetObjectDescription", "const char*"),
        ("GetLocation", "const char*"),
        ("IsValid", "bool"),
        ("MightHaveChildren", "bool"),
        ("GetNumChildren", "uint32_t"),
        ("GetName", "const char*"),
        ("GetType", "SBType"),
        ("GetLoadAddress", "addr_t"),
        ("GetAddress", "SBAddress"),
        ("GetFrame", "SBFrame"),
        ("GetProcess", "SBProcess"),
        ("GetThread", "SBThread"),
        ("GetTarget", "SBTarget"),
        ("GetData", "SBData"),
        ("GetError", "SBError"),
        ("GetValueDidChange", "bool"),
        ("GetValueAsSigned", "int64_t"),
        ("GetValueAsUnsigned", "uint64_t"),
        ("GetValueAsAddress", "addr_t"),
        ("GetDynamicValue", "SBValue"),
        ("GetStaticValue", "SBValue"),
        ("GetNonSyntheticValue", "SBValue"),
        ("GetPreferDynamicValue", "DynamicValueType"),
        ("GetPreferSyntheticValue", "bool"),
        ("IsDynamic", "bool"),
        ("IsSynthetic", "bool"),
        ("IsSyntheticChildrenGenerated", "bool"),
        ("IsInScope", "bool"),
    ]

    # 构建结果表格
    table = "| Method | Return Type | Return Value |\n"
    table += "|--------|-------------|--------------|\n"

    for method_name, return_type in methods:
        try:
            # 获取方法对象
            method = getattr(value, method_name)
            # 调用方法
            result = method()

            # 特殊处理某些类型的返回值
            if result is None:
                result_str = "None"
            elif method_name == "GetType" and result.IsValid():
                result_str = result.GetName()
            elif method_name == "GetAddress" and result.IsValid():
                if target is not None:
                    result_str = f"addr = {result.GetLoadAddress(target)}"
                else:
                    result_str = "Valid (no target provided for address)"
            elif method_name in ["GetFrame", "GetProcess", "GetThread", "GetTarget"]:
                result_str = "Valid" if result.IsValid() else "Invalid"
            elif method_name == "GetData" and result.IsValid():
                result_str = f"data[{result.GetByteSize()} bytes]"
            elif method_name == "GetError" and result.Fail():
                result_str = f"Error: {result.GetCString()}"
            elif isinstance(result, lldb.SBValue) and result.IsValid():
                result_str = f"{result.GetName()} ({result.GetTypeName()})"
            else:
                result_str = str(result)

            # 截断过长的结果
            if len(result_str) > 100:
                result_str = result_str[:100] + "..."
        except Exception as e:
            result_str = f"Error: {str(e)}"

        table += f"| {method_name} | {return_type} | {result_str} |\n"

    return table
