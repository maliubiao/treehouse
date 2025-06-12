import lldb

# Debug flag - set to True to enable type class logging
DEBUG_TYPECLASS = True

# Mapping from lldb type class enums to human-readable strings
TYPECLASS_MAP = {
    lldb.eTypeClassInvalid: "eTypeClassInvalid",
    lldb.eTypeClassArray: "eTypeClassArray",
    lldb.eTypeClassBlockPointer: "eTypeClassBlockPointer",
    lldb.eTypeClassBuiltin: "eTypeClassBuiltin",
    lldb.eTypeClassClass: "eTypeClassClass",
    lldb.eTypeClassComplexInteger: "eTypeClassComplexInteger",
    lldb.eTypeClassComplexFloat: "eTypeClassComplexFloat",
    lldb.eTypeClassFunction: "eTypeClassFunction",
    lldb.eTypeClassMemberPointer: "eTypeClassMemberPointer",
    lldb.eTypeClassObjCObject: "eTypeClassObjCObject",
    lldb.eTypeClassObjCInterface: "eTypeClassObjCInterface",
    lldb.eTypeClassObjCObjectPointer: "eTypeClassObjCObjectPointer",
    lldb.eTypeClassPointer: "eTypeClassPointer",
    lldb.eTypeClassReference: "eTypeClassReference",
    lldb.eTypeClassStruct: "eTypeClassStruct",
    lldb.eTypeClassTypedef: "eTypeClassTypedef",
    lldb.eTypeClassUnion: "eTypeClassUnion",
    lldb.eTypeClassVector: "eTypeClassVector",
    lldb.eTypeClassOther: "eTypeClassOther",
    lldb.eTypeClassAny: "eTypeClassAny",
}

# List of smart pointer type prefixes
SMART_POINTER_PREFIXES = (
    "std::unique_ptr",
    "std::shared_ptr",
    "std::weak_ptr",
    "std::__1::unique_ptr",
    "std::__1::shared_ptr",
    "std::__1::weak_ptr",
)


def is_stl_container(type_name: str):
    """Check if type is an STL container (any type starting with 'std::')"""
    return type_name.startswith("std::") and not type_name.startswith(SMART_POINTER_PREFIXES)


def is_smart_pointer(type_name: str):
    """Check if type is a smart pointer"""
    return type_name.startswith(SMART_POINTER_PREFIXES)


def get_type_info(value: lldb.SBValue):
    """
    获取值的详细类型信息

    返回:
        (type_class, basic_type, type_name)
    """
    if not value or not value.IsValid():
        return (None, None, "<invalid type>")

    type_obj: lldb.SBType = value.GetType()
    type_class = type_obj.GetTypeClass()
    basic_type = type_obj.GetBasicType()
    type_name = type_obj.GetName() or "<unknown type>"

    return (type_class, basic_type, type_name)


def format_sbvalue(value: lldb.SBValue, visited=None, depth=0, max_depth=5, max_children=10):
    """
    格式化SBValue对象为结构化字符串表示，使用C/C++风格的类型标注
    全面支持LLDB的类型系统

    参数:
        value: 要格式化的SBValue对象
        visited: 已访问地址集合(用于循环检测)
        depth: 当前递归深度
        max_depth: 最大递归深度
        max_children: 最大子元素显示数量

    返回:
        格式化后的字符串
    """
    if visited is None:
        visited = set()

    # 检查无效值
    if not value or not value.IsValid():
        return "<invalid value>"

    # 获取详细类型信息
    type_class, basic_type, type_name = get_type_info(value)
    addr = value.GetLoadAddress()

    # 调试日志：打印类型信息
    if DEBUG_TYPECLASS:
        type_class_str = TYPECLASS_MAP.get(type_class, f"Unknown({type_class})")
        print(
            f"[DEBUG] TypeClass: {type_class_str}, TypeName: {type_name}, "
            f"Address: {hex(addr) if addr != lldb.LLDB_INVALID_ADDRESS else 'N/A'}, "
            f"Depth: {depth} Value: {value}"
        )

    # 处理STL容器类型 - 直接使用LLDB的默认格式化输出
    if is_stl_container(type_name):
        return repr(value)
    # 处理智能指针类型
    if is_smart_pointer(type_name):
        pointee = value.Dereference()
        if pointee and pointee.IsValid():
            pointee_str = format_sbvalue(pointee, visited, depth, max_depth, max_children)
            return f"({type_name}) -> {pointee_str}"

        # 如果无法解析，返回基本表示
        return f"({type_name}) <smart pointer at {hex(addr) if addr != lldb.LLDB_INVALID_ADDRESS else 'N/A'}>"

    # 定义聚合类型集合
    AGGREGATE_TYPES = (
        lldb.eTypeClassStruct,
        lldb.eTypeClassClass,
        lldb.eTypeClassUnion,
        lldb.eTypeClassArray,
        lldb.eTypeClassVector,
        lldb.eTypeClassTypedef,
        lldb.eTypeClassPointer,
    )

    # 处理循环引用检测
    obj_key = None

    # 如果是聚合类型且地址有效，进行循环检测
    if addr != lldb.LLDB_INVALID_ADDRESS and type_class in AGGREGATE_TYPES:
        obj_key = (addr, type_name)
        if obj_key in visited:
            return f"<circular reference @ {hex(addr)}, type: {type_name}>"
        visited.add(obj_key)

    # 检查深度限制（在循环引用检测之后）
    if depth >= max_depth:
        return f"<max depth reached>"

    # 特殊处理字符串类型 (char指针/数组)
    if type_class in (lldb.eTypeClassPointer, lldb.eTypeClassArray, lldb.eTypeClassVector):
        # 获取元素类型
        if type_class == lldb.eTypeClassPointer:
            elem_type = value.GetType().GetPointeeType()
        elif type_class == lldb.eTypeClassVector:
            elem_type = value.GetType().GetVectorElementType()
        else:
            elem_type = value.GetType().GetArrayElementType()

        elem_basic_type = elem_type.GetBasicType() if elem_type.IsValid() else lldb.eBasicTypeInvalid

        # 处理字符类型: char, unsigned char, wchar_t等
        char_types = {
            lldb.eBasicTypeChar,
            lldb.eBasicTypeSignedChar,
            lldb.eBasicTypeUnsignedChar,
            lldb.eBasicTypeWChar,
            lldb.eBasicTypeSignedWChar,
            lldb.eBasicTypeUnsignedWChar,
            lldb.eBasicTypeChar16,
            lldb.eBasicTypeChar32,
            lldb.eBasicTypeChar8,
        }

        if elem_basic_type in char_types:
            summary = value.GetSummary()
            if summary:
                if type_class == lldb.eTypeClassPointer:
                    return f"({type_name}) {summary}"
                elif type_class == lldb.eTypeClassVector:
                    return f"({type_name}) <vector of characters>"
                else:  # 数组类型
                    return f'({type_name}) "{summary}"'

    # 特殊处理指针类型
    if type_class == lldb.eTypeClassPointer:
        pointee = value.Dereference()
        if pointee.IsValid():
            # 处理指针指向的聚合类型
            pointee_addr = pointee.GetLoadAddress()
            pointee_type = pointee.GetType().GetName() or "<unknown type>"
            pointee_key = (pointee_addr, pointee_type)

            # 检查指针指向的对象是否已访问
            if pointee_addr != lldb.LLDB_INVALID_ADDRESS and pointee_key in visited:
                return f"({type_name}){hex(addr)} -> <circular reference @ {hex(pointee_addr)}, type: {pointee_type}>"

            # 递归格式化指针指向的对象
            pointee_str = format_sbvalue(pointee, visited, depth + 1, max_depth, max_children)
            return f"({type_name}){hex(addr)} -> {pointee_str}"
        return f"({type_name}){hex(addr)} -> <invalid>"

    # 处理引用类型
    if type_class == lldb.eTypeClassReference:
        referenced = value.Dereference()
        if referenced.IsValid():
            ref_addr = referenced.GetLoadAddress()
            ref_type = referenced.GetType().GetName() or "<unknown type>"
            ref_key = (ref_addr, ref_type)

            if ref_addr != lldb.LLDB_INVALID_ADDRESS and ref_key in visited:
                return f"({type_name})& -> <circular reference @ {hex(ref_addr)}, type: {ref_type}>"

            ref_str = format_sbvalue(referenced, visited, depth + 1, max_depth, max_children)
            return f"({type_name})& -> {ref_str}"
        return f"({type_name})& -> <invalid>"

    # 处理函数类型
    if type_class == lldb.eTypeClassFunction:
        name = value.GetName()
        if name:
            return f"({type_name}) {name}"
        return f"({type_name}) <unnamed function>"

    # 处理块指针类型
    if type_class == lldb.eTypeClassBlockPointer:
        return f"({type_name}) <block at {hex(addr)}>"

    # 处理成员指针类型
    if type_class == lldb.eTypeClassMemberPointer:
        return f"({type_name}) <member pointer at {hex(addr)}>"

    # 处理复杂浮点数类型
    if type_class == lldb.eTypeClassComplexFloat:
        real = value.GetChildMemberWithName("real")
        imag = value.GetChildMemberWithName("imag")
        if real.IsValid() and imag.IsValid():
            return f"({type_name}) {real.GetValue()} + {imag.GetValue()}i"
        return f"({type_name}) <complex float>"

    # 处理复杂整数类型
    if type_class == lldb.eTypeClassComplexInteger:
        real = value.GetChildMemberWithName("real")
        imag = value.GetChildMemberWithName("imag")
        if real.IsValid() and imag.IsValid():
            return f"({type_name}) {real.GetValue()} + {imag.GetValue()}i"
        return f"({type_name}) <complex integer>"

    # 处理基本类型(无子元素)
    num_children = value.GetNumChildren()
    if num_children == 0:
        summary = value.GetSummary()
        value_str = value.GetValue()
        error = lldb.SBError()
        value_data: lldb.SBData = value.GetData()

        # 布尔类型特殊处理
        if basic_type == lldb.eBasicTypeBool:
            if value_data.GetByteSize() > 0:
                bool_val = value_data.GetUnsignedInt8(error, 0)
                if not error.Fail():
                    return f"(bool) {'true' if bool_val else 'false'}"
            return f"(bool) {'true' if value_str == '1' else 'false'}"

        # 字符类型特殊处理
        char_types = {
            lldb.eBasicTypeChar: "char",
            lldb.eBasicTypeSignedChar: "signed char",
            lldb.eBasicTypeUnsignedChar: "unsigned char",
            lldb.eBasicTypeWChar: "wchar_t",
            lldb.eBasicTypeSignedWChar: "signed wchar_t",
            lldb.eBasicTypeUnsignedWChar: "unsigned wchar_t",
            lldb.eBasicTypeChar16: "char16_t",
            lldb.eBasicTypeChar32: "char32_t",
            lldb.eBasicTypeChar8: "char8_t",
        }

        if basic_type in char_types:
            if value_data.GetByteSize() > 0:
                char_val = value_data.GetUnsignedInt8(error, 0)
                if not error.Fail():
                    # 可打印字符处理
                    if 32 <= char_val <= 126:
                        return f"({char_types[basic_type]}) '{chr(char_val)}'"
                    # 非打印字符处理
                    return f"({char_types[basic_type]}) '\\x{char_val:02x}'"

        # 枚举类型特殊处理
        if type_class == lldb.eTypeClassEnumeration:
            if summary:
                return f"({type_name}) {summary}"
            if value_str:
                return f"({type_name}) {value_str}"
            return f"({type_name}) <no value>"

        # 浮点类型特殊处理
        float_types = {
            lldb.eBasicTypeHalf: "half",
            lldb.eBasicTypeFloat: "float",
            lldb.eBasicTypeDouble: "double",
            lldb.eBasicTypeLongDouble: "long double",
        }

        if basic_type in float_types:
            if value_str:
                return f"({float_types[basic_type]}) {value_str}"
            if summary:
                return f"({float_types[basic_type]}) {summary}"

        # 其他基本类型处理
        if summary:
            return f"({type_name}) {summary}"

        if value_str:
            return f"({type_name}) {value_str}"

        return f"({type_name}) <no value>"

    # 处理聚合类型(结构体/数组/向量等)
    items = []

    # 限制大型结构体的子元素数量
    display_count = min(num_children, max_children)
    for i in range(display_count):
        child = value.GetChildAtIndex(i)
        # 处理空子元素
        if not child or not child.IsValid():
            continue

        name = child.GetName() or f"[{i}]"
        child_str = format_sbvalue(child, visited, depth + 1, max_depth, max_children)

        # 对于结构体/类/联合体，使用字段名:值格式
        if type_class in (lldb.eTypeClassStruct, lldb.eTypeClassClass, lldb.eTypeClassUnion):
            items.append(f"{name}: {child_str}")
        # 对于数组和向量，只显示值
        else:
            items.append(child_str)

    # 添加省略号如果截断了子元素
    if num_children > max_children:
        items.append(f"... (+{num_children - max_children} more)")

    # 紧凑格式输出
    if type_class == lldb.eTypeClassArray:
        return f"({type_name}) [{', '.join(items)}]"
    elif type_class == lldb.eTypeClassVector:
        return f"({type_name}) <{', '.join(items)}>"
    else:
        return f"({type_name}) {{{', '.join(items)}}}"
