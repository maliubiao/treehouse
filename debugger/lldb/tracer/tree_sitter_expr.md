in llm_query.py，  import llm_query
ParserLoader
parse_code_file
        # 获取解析器和查询对象
        parser, _, _ = ParserLoader().get_parser(str(file_path))
        print("[DEBUG] 开始解析文件: {file_path}")

        # 解析文件并获取语法树
        tree = parse_code_file(file_path, parser)
        print("[DEBUG] 文件解析完成，开始打印语法树")


获取tree的正确api使用时， 我们对tree sitter 的api做了封装，自动支持多语言
    from tree import ParserLoader, parse_code_file
    import tempfile as tmpfile
    # 加载语法解析器
    with tmpfile.NamedTemporaryFile(delete=True, suffix='.c') as temp_file:
        file_path = temp_file.name
        test_code = b"""
        int main() {
            int a = 5;
            int *ptr = &a;
            return a + *ptr;
        }
        """
        temp_file.write(test_code)
        parser, _, _ = ParserLoader().get_parser(str(file_path))
        tree = parse_code_file(file_path, parser)
可以用以下方法遍历树
        def print_tree(node, indent=0):
            # 获取节点文本内容
            node_text = node.text.decode("utf-8") if node.text else ""
            # 打印节点类型、位置和内容
            print(" " * indent + f"{node.type} ({node.start_point} -> {node.end_point}): {node_text}")
            for child in node.children:
                print_tree(child, indent + 2)

        # 从根节点开始打印
        print_tree(tree.root_node)


### 核心原则
1. **只提取可求值表达式**：
   - 变量访问（标识符）
   - 指针解引用（`*ptr`）
   - 取地址（`&var`）
   - 结构体/指针成员访问（`struct.field`, `ptr->field`, 可能串起起来，一级，二级，三级
   - 赋值操作（包括复合赋值）
   - 字面量（但通常无调试价值）
   - 函数调用**的参数**（不调用函数本身）
   - if, while, for, switch，return 使用的变量，也是正常提取提取的目标

2. **排除场景**：
   - 函数调用本身（如 `so1_init()`）
   - 类型转换（如 `(init_fn_t)...`）
   - 纯声明语句（如 `pthread_t thread1`）
   - 纯控制流语句，无变量涉及（如 `return`）
   - 编译器内置指令（如 `asm volatile`）
   - 除了地址引用，数组下标，取地址，解引用，其它操作符的表达式都不行，cpp可能有side affect

算术运算符不包括啊，不能写在这个里边去啊，只包括算术运算符的这个成员。比如a +b 提取的是a, b


需要记住提取内容的row, column , 做分类
分类用enum
比如 变量访问， 指针解引用...

最后按start line分类

{
    line1 :  [
        [type_1,  expr, (start_line, start_column, end_line, end_column)],
        [type_2,  expr, ...],
    ]
}

# 原行的需求
如何从tree sitter 结构里取出每行, lldb里expr自动求值的语句， 我想做个每行变量自动输出， 哪些语句可以用expr, 不expr函数调用, 可以考虑expr它的参数，只关心load store, 包括指针引用，解指针，结构成员偏移，等等可以expr执行的东西

按照这个文档的需求定义实现一个代码文件，  然后要编写测试脚本， 这个测试脚本可以放在呃这个源代码文件里啊，因为它只需要包含各种各样的这个语句，跨行的不跨行的语句就可以了。 嗯，这是请实现我这个目标。
这个文档就不要修改了。
这是个原始的原始的收集材料的文档。

然后请实现我这个源代码。
务必考虑到各种各样复杂的情况。
而且针对性的要把测试写好。

另外也需要支持这个cpp的情况，c++会有模板，模板类，模板函数