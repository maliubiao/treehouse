import lldb


def format_sbvalue(value, visited=None, depth=0, max_depth=10, max_children=10):
    """
    格式化SBValue对象为结构化字符串表示，使用C/C++风格的类型标注

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

    # 获取类型信息
    type_name = value.GetTypeName() or "<unknown type>"
    type_class = value.GetType().GetTypeClass()

    # 特殊处理字符串类型
    if type_class == lldb.eTypeClassPointer or type_class == lldb.eTypeClassArray:
        # 获取指针指向类型或数组元素类型
        if type_class == lldb.eTypeClassPointer:
            elem_type = value.GetType().GetPointeeType()
        else:
            elem_type = value.GetType().GetArrayElementType()

        elem_type_name = elem_type.GetName() if elem_type.IsValid() else ""

        # 处理C字符串(char指针/数组)
        if elem_type_name in ("char", "const char", "unsigned char", "const unsigned char"):
            summary = value.GetSummary()
            if summary:
                # 区分指针和数组表示法
                if type_class == lldb.eTypeClassPointer:
                    return f"({type_name}) {summary}"
                else:  # 数组类型
                    return f'({type_name}) "{summary}"'

    # 获取地址用于循环检测
    addr = value.GetLoadAddress()

    # 特殊处理指针类型
    if type_class == lldb.eTypeClassPointer:
        pointee = value.Dereference()
        if pointee.IsValid():
            # 指针解引用时传递相同的visited集合
            return f"({type_name}){hex(addr)} -> {format_sbvalue(pointee, visited, depth + 1, max_depth, max_children)}"
        return f"({type_name}){hex(addr)} -> <invalid>"

    # 只对聚合类型进行循环检测(结构体/类/联合/数组)
    AGGREGATE_TYPES = (lldb.eTypeClassStruct, lldb.eTypeClassClass, lldb.eTypeClassUnion, lldb.eTypeClassArray)
    if addr != lldb.LLDB_INVALID_ADDRESS and type_class in AGGREGATE_TYPES:
        # 使用(地址, 类型名)作为唯一标识
        obj_key = (addr, type_name)
        if obj_key in visited:
            return f"<circular reference @ {hex(addr)}, type: {type_name}>"
        visited.add(obj_key)

    # 超过最大深度
    if depth > max_depth:
        return f"... (max depth {max_depth} reached)"

    # 处理基本类型(无子元素)
    num_children = value.GetNumChildren()
    if num_children == 0:
        value_str = value.GetValue()
        summary = value.GetSummary()

        # 优先使用摘要信息
        if summary:
            return f"({type_name}) {summary}"

        # 处理浮点数精度
        if type_name == "float" and value_str:
            try:
                float_val = float(value_str)
                return f"(float) {float_val:.6g}"  # 限制精度
            except ValueError:
                pass
        elif type_name == "double" and value_str:
            try:
                double_val = float(value_str)
                return f"(double) {double_val:.15g}"  # 更高精度
            except ValueError:
                pass

        # 处理布尔类型
        if type_name == "bool" and value_str:
            return f"(bool) {'true' if value_str == '1' else 'false'}"

        # 处理数值类型
        if value_str:
            return f"({type_name}) {value_str}"
        return f"({type_name}) <no value>"

    # 处理聚合类型(结构体/数组等)
    result = [f"({type_name}) {{"]
    indent = "  " * (depth + 1)

    # 限制大型结构体的子元素数量
    display_count = min(num_children, max_children)
    for i in range(display_count):
        child = value.GetChildAtIndex(i)
        # 处理空子元素
        if not child or not child.IsValid():
            continue

        name = child.GetName() or f"[{i}]"
        child_str = format_sbvalue(child, visited, depth + 1, max_depth, max_children)
        result.append(f"{indent}{name}: {child_str}")

    # 添加省略号如果截断了子元素
    if num_children > max_children:
        result.append(f"{indent}... (+{num_children - max_children} more)")

    result.append("  " * depth + "}")
    return "\n".join(result)
