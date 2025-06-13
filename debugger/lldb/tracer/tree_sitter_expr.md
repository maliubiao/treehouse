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

下面这个是个一个C代码的这个样本啊，请在处理这个呃呃去节点的时候注意, 节点的命名。
translation_unit (Point(row=0, column=0) -> Point(row=183, column=0)): #include "basic_lib.h"
  preproc_include (Point(row=0, column=0) -> Point(row=1, column=0)): #include "basic_lib.h"

    #include (Point(row=0, column=0) -> Point(row=0, column=8)): #include
    string_literal (Point(row=0, column=9) -> Point(row=0, column=22)): "basic_lib.h"
      " (Point(row=0, column=9) -> Point(row=0, column=10)): "
      string_content (Point(row=0, column=10) -> Point(row=0, column=21)): basic_lib.h
      " (Point(row=0, column=21) -> Point(row=0, column=22)): "
  preproc_include (Point(row=1, column=0) -> Point(row=2, column=0)): #include "so1/basic_so1.h"
 comment (Point(row=10, column=0) -> Point(row=10, column=39)): // Define strong version of weak symbol
  function_definition (Point(row=11, column=0) -> Point(row=14, column=1)): int so1_weak_function(void) {
  printf("Main strong weak function\n");
  return 0xBEEF;
}
    primitive_type (Point(row=11, column=0) -> Point(row=11, column=3)): int
    function_declarator (Point(row=11, column=4) -> Point(row=11, column=27)): so1_weak_function(void)
      identifier (Point(row=11, column=4) -> Point(row=11, column=21)): so1_weak_function
      parameter_list (Point(row=11, column=21) -> Point(row=11, column=27)): (void)
        ( (Point(row=11, column=21) -> Point(row=11, column=22)): (
        parameter_declaration (Point(row=11, column=22) -> Point(row=11, column=26)): void
          primitive_type (Point(row=11, column=22) -> Point(row=11, column=26)): void
        ) (Point(row=11, column=26) -> Point(row=11, column=27)): )
    compound_statement (Point(row=11, column=28) -> Point(row=14, column=1)): {
  printf("Main strong weak function\n");
  return 0xBEEF;
}
      { (Point(row=134, column=11) -> Point(row=134, column=12)): {
      expression_statement (Point(row=135, column=2) -> Point(row=135, column=22)): asm volatile("nop");
        gnu_asm_expression (Point(row=135, column=2) -> Point(row=135, column=21)): asm volatile("nop")
          asm (Point(row=135, column=2) -> Point(row=135, column=5)): asm
          gnu_asm_qualifier (Point(row=135, column=6) -> Point(row=135, column=14)): volatile
            volatile (Point(row=135, column=6) -> Point(row=135, column=14)): volatile
          ( (Point(row=135, column=14) -> Point(row=135, column=15)): (
          string_literal (Point(row=135, column=15) -> Point(row=135, column=20)): "nop"
            " (Point(row=135, column=15) -> Point(row=135, column=16)): "
            string_content (Point(row=135, column=16) -> Point(row=135, column=19)): nop
            " (Point(row=135, column=19) -> Point(row=135, column=20)): "
          ) (Point(row=135, column=20) -> Point(row=135, column=21)): )
        ; (Point(row=135, column=21) -> Point(row=135, column=22)): ;
      comment (Point(row=137, column=2) -> Point(row=137, column=29)): // 运行动态库初始化
      expression_statement (Point(row=138, column=2) -> Point(row=138, column=13)): so1_init();
        call_expression (Point(row=138, column=2) -> Point(row=138, column=12)): so1_init()
          identifier (Point(row=138, column=2) -> Point(row=138, column=10)): so1_init
          argument_list (Point(row=138, column=10) -> Point(row=138, column=12)): ()
            ( (Point(row=138, column=10) -> Point(row=138, column=11)): (
            ) (Point(row=138, column=11) -> Point(row=138, column=12)): )
        ; (Point(row=138, column=12) -> Point(row=138, column=13)): ;
      expression_statement (Point(row=139, column=2) -> Point(row=139, column=13)): so2_init();
        call_expression (Point(row=139, column=2) -> Point(row=139, column=12)): so2_init()
          identifier (Point(row=139, column=2) -> Point(row=139, column=10)): so2_init
          argument_list (Point(row=139, column=10) -> Point(row=139, column=12)): ()
            ( (Point(row=139, column=10) -> Point(row=139, column=11)): (
            ) (Point(row=139, column=11) -> Point(row=139, column=12)): )
        ; (Point(row=139, column=12) -> Point(row=139, column=13)): ;
      expression_statement (Point(row=140, column=2) -> Point(row=140, column=13)): so3_init();
        call_expression (Point(row=140, column=2) -> Point(row=140, column=12)): so3_init()
          identifier (Point(row=140, column=2) -> Point(row=140, column=10)): so3_init
          argument_list (Point(row=140, column=10) -> Point(row=140, column=12)): ()
            ( (Point(row=140, column=10) -> Point(row=140, column=11)): (
            ) (Point(row=140, column=11) -> Point(row=140, column=12)): )
        ; (Point(row=140, column=12) -> Point(row=140, column=13)): ;
      comment (Point(row=140, column=14) -> Point(row=140, column=40)): // 初始化SO3文件IO库
      comment (Point(row=142, column=2) -> Point(row=142, column=29)): // 运行动态加载测试
      declaration (Point(row=143, column=2) -> Point(row=143, column=43)): void *dl_handle = dlopen(NULL, RTLD_NOW);
        primitive_type (Point(row=143, column=2) -> Point(row=143, column=6)): void
        init_declarator (Point(row=143, column=7) -> Point(row=143, column=42)): *dl_handle = dlopen(NULL, RTLD_NOW)
          pointer_declarator (Point(row=143, column=7) -> Point(row=143, column=17)): *dl_handle
            * (Point(row=143, column=7) -> Point(row=143, column=8)): *
            identifier (Point(row=143, column=8) -> Point(row=143, column=17)): dl_handle
          = (Point(row=143, column=18) -> Point(row=143, column=19)): =
          call_expression (Point(row=143, column=20) -> Point(row=143, column=42)): dlopen(NULL, RTLD_NOW)
            identifier (Point(row=143, column=20) -> Point(row=143, column=26)): dlopen
            argument_list (Point(row=143, column=26) -> Point(row=143, column=42)): (NULL, RTLD_NOW)
              ( (Point(row=143, column=26) -> Point(row=143, column=27)): (
              null (Point(row=143, column=27) -> Point(row=143, column=31)): NULL
                NULL (Point(row=143, column=27) -> Point(row=143, column=31)): NULL
              , (Point(row=143, column=31) -> Point(row=143, column=32)): ,
              identifier (Point(row=143, column=33) -> Point(row=143, column=41)): RTLD_NOW
              ) (Point(row=143, column=41) -> Point(row=143, column=42)): )
        ; (Point(row=143, column=42) -> Point(row=143, column=43)): ;
      declaration (Point(row=144, column=2) -> Point(row=144, column=66)): init_fn_t so1_dl_init = (init_fn_t)dlsym(dl_handle, "so1_init");
        type_identifier (Point(row=144, column=2) -> Point(row=144, column=11)): init_fn_t
        init_declarator (Point(row=144, column=12) -> Point(row=144, column=65)): so1_dl_init = (init_fn_t)dlsym(dl_handle, "so1_init")
          identifier (Point(row=144, column=12) -> Point(row=144, column=23)): so1_dl_init
          = (Point(row=144, column=24) -> Point(row=144, column=25)): =
          cast_expression (Point(row=144, column=26) -> Point(row=144, column=65)): (init_fn_t)dlsym(dl_handle, "so1_init")
            ( (Point(row=144, column=26) -> Point(row=144, column=27)): (
            type_descriptor (Point(row=144, column=27) -> Point(row=144, column=36)): init_fn_t
              type_identifier (Point(row=144, column=27) -> Point(row=144, column=36)): init_fn_t
            ) (Point(row=144, column=36) -> Point(row=144, column=37)): )
            call_expression (Point(row=144, column=37) -> Point(row=144, column=65)): dlsym(dl_handle, "so1_init")
              identifier (Point(row=144, column=37) -> Point(row=144, column=42)): dlsym
              argument_list (Point(row=144, column=42) -> Point(row=144, column=65)): (dl_handle, "so1_init")
                ( (Point(row=144, column=42) -> Point(row=144, column=43)): (
                identifier (Point(row=144, column=43) -> Point(row=144, column=52)): dl_handle
                , (Point(row=144, column=52) -> Point(row=144, column=53)): ,
                string_literal (Point(row=144, column=54) -> Point(row=144, column=64)): "so1_init"
                  " (Point(row=144, column=54) -> Point(row=144, column=55)): "
                  string_content (Point(row=144, column=55) -> Point(row=144, column=63)): so1_init
                  " (Point(row=144, column=63) -> Point(row=144, column=64)): "
                ) (Point(row=144, column=64) -> Point(row=144, column=65)): )
        ; (Point(row=144, column=65) -> Point(row=144, column=66)): ;
      declaration (Point(row=145, column=2) -> Point(row=145, column=73)): func_fn_t so2_plt_fn = (func_fn_t)dlsym(dl_handle, "so2_plt_function");
        type_identifier (Point(row=145, column=2) -> Point(row=145, column=11)): func_fn_t
        init_declarator (Point(row=145, column=12) -> Point(row=145, column=72)): so2_plt_fn = (func_fn_t)dlsym(dl_handle, "so2_plt_function")
          identifier (Point(row=145, column=12) -> Point(row=145, column=22)): so2_plt_fn
          = (Point(row=145, column=23) -> Point(row=145, column=24)): =
          cast_expression (Point(row=145, column=25) -> Point(row=145, column=72)): (func_fn_t)dlsym(dl_handle, "so2_plt_function")
            ( (Point(row=145, column=25) -> Point(row=145, column=26)): (
            type_descriptor (Point(row=145, column=26) -> Point(row=145, column=35)): func_fn_t
              type_identifier (Point(row=145, column=26) -> Point(row=145, column=35)): func_fn_t
            ) (Point(row=145, column=35) -> Point(row=145, column=36)): )
            call_expression (Point(row=145, column=36) -> Point(row=145, column=72)): dlsym(dl_handle, "so2_plt_function")
              identifier (Point(row=145, column=36) -> Point(row=145, column=41)): dlsym
              argument_list (Point(row=145, column=41) -> Point(row=145, column=72)): (dl_handle, "so2_plt_function")
                ( (Point(row=145, column=41) -> Point(row=145, column=42)): (
                identifier (Point(row=145, column=42) -> Point(row=145, column=51)): dl_handle
                , (Point(row=145, column=51) -> Point(row=145, column=52)): ,
                string_literal (Point(row=145, column=53) -> Point(row=145, column=71)): "so2_plt_function"
                  " (Point(row=145, column=53) -> Point(row=145, column=54)): "
                  string_content (Point(row=145, column=54) -> Point(row=145, column=70)): so2_plt_function
                  " (Point(row=145, column=70) -> Point(row=145, column=71)): "
                ) (Point(row=145, column=71) -> Point(row=145, column=72)): )
        ; (Point(row=145, column=72) -> Point(row=145, column=73)): ;
      comment (Point(row=147, column=2) -> Point(row=147, column=26)): // 初始化函数指针
      expression_statement (Point(row=148, column=2) -> Point(row=148, column=46)): so1_func_ptr = (void (*)())so2_plt_function;
        assignment_expression (Point(row=148, column=2) -> Point(row=148, column=45)): so1_func_ptr = (void (*)())so2_plt_function
          identifier (Point(row=148, column=2) -> Point(row=148, column=14)): so1_func_ptr
          = (Point(row=148, column=15) -> Point(row=148, column=16)): =
          cast_expression (Point(row=148, column=17) -> Point(row=148, column=45)): (void (*)())so2_plt_function
            ( (Point(row=148, column=17) -> Point(row=148, column=18)): (
            type_descriptor (Point(row=148, column=18) -> Point(row=148, column=28)): void (*)()
              primitive_type (Point(row=148, column=18) -> Point(row=148, column=22)): void
              abstract_function_declarator (Point(row=148, column=23) -> Point(row=148, column=28)): (*)()
                abstract_parenthesized_declarator (Point(row=148, column=23) -> Point(row=148, column=26)): (*)
                  ( (Point(row=148, column=23) -> Point(row=148, column=24)): (
                  abstract_pointer_declarator (Point(row=148, column=24) -> Point(row=148, column=25)): *
                    * (Point(row=148, column=24) -> Point(row=148, column=25)): *
                  ) (Point(row=148, column=25) -> Point(row=148, column=26)): )
                parameter_list (Point(row=148, column=26) -> Point(row=148, column=28)): ()
                  ( (Point(row=148, column=26) -> Point(row=148, column=27)): (
                  ) (Point(row=148, column=27) -> Point(row=148, column=28)): )
            ) (Point(row=148, column=28) -> Point(row=148, column=29)): )
            identifier (Point(row=148, column=29) -> Point(row=148, column=45)): so2_plt_function
        ; (Point(row=148, column=45) -> Point(row=148, column=46)): ;
      expression_statement (Point(row=149, column=2) -> Point(row=149, column=16)): so1_dl_init();
        call_expression (Point(row=149, column=2) -> Point(row=149, column=15)): so1_dl_init()
          identifier (Point(row=149, column=2) -> Point(row=149, column=13)): so1_dl_init
          argument_list (Point(row=149, column=13) -> Point(row=149, column=15)): ()
            ( (Point(row=149, column=13) -> Point(row=149, column=14)): (
            ) (Point(row=149, column=14) -> Point(row=149, column=15)): )
        ; (Point(row=149, column=15) -> Point(row=149, column=16)): ;
      comment (Point(row=149, column=17) -> Point(row=149, column=44)): // 通过动态符号调用
      comment (Point(row=151, column=2) -> Point(row=151, column=34)): // 运行ARM64分支指令测试
      expression_statement (Point(row=152, column=2) -> Point(row=152, column=63)): printf("\n=== Running ARM64 branch instruction tests ===\n");
        call_expression (Point(row=152, column=2) -> Point(row=152, column=62)): printf("\n=== Running ARM64 branch instruction tests ===\n")
          identifier (Point(row=152, column=2) -> Point(row=152, column=8)): printf
          argument_list (Point(row=152, column=8) -> Point(row=152, column=62)): ("\n=== Running ARM64 branch instruction tests ===\n")
            ( (Point(row=152, column=8) -> Point(row=152, column=9)): (
            string_literal (Point(row=152, column=9) -> Point(row=152, column=61)): "\n=== Running ARM64 branch instruction tests ===\n"
              " (Point(row=152, column=9) -> Point(row=152, column=10)): "
              escape_sequence (Point(row=152, column=10) -> Point(row=152, column=12)): \n
              string_content (Point(row=152, column=12) -> Point(row=152, column=58)): === Running ARM64 branch instruction tests ===
              escape_sequence (Point(row=152, column=58) -> Point(row=152, column=60)): \n
              " (Point(row=152, column=60) -> Point(row=152, column=61)): "
            ) (Point(row=152, column=61) -> Point(row=152, column=62)): )
        ; (Point(row=152, column=62) -> Point(row=152, column=63)): ;
      expression_statement (Point(row=153, column=2) -> Point(row=153, column=21)): run_branch_tests();
        call_expression (Point(row=153, column=2) -> Point(row=153, column=20)): run_branch_tests()
          identifier (Point(row=153, column=2) -> Point(row=153, column=18)): run_branch_tests
          argument_list (Point(row=153, column=18) -> Point(row=153, column=20)): ()
            ( (Point(row=153, column=18) -> Point(row=153, column=19)): (
            ) (Point(row=153, column=19) -> Point(row=153, column=20)): )
        ; (Point(row=153, column=20) -> Point(row=153, column=21)): ;
      expression_statement (Point(row=154, column=2) -> Point(row=154, column=26)): run_cond_branch_tests();
        call_expression (Point(row=154, column=2) -> Point(row=154, column=25)): run_cond_branch_tests()
          identifier (Point(row=154, column=2) -> Point(row=154, column=23)): run_cond_branch_tests
          argument_list (Point(row=154, column=23) -> Point(row=154, column=25)): ()
            ( (Point(row=154, column=23) -> Point(row=154, column=24)): (
            ) (Point(row=154, column=24) -> Point(row=154, column=25)): )
        ; (Point(row=154, column=25) -> Point(row=154, column=26)): ;
      expression_statement (Point(row=155, column=2) -> Point(row=155, column=47)): printf("=== Branch tests completed ===\n\n");
        call_expression (Point(row=155, column=2) -> Point(row=155, column=46)): printf("=== Branch tests completed ===\n\n")
          identifier (Point(row=155, column=2) -> Point(row=155, column=8)): printf
          argument_list (Point(row=155, column=8) -> Point(row=155, column=46)): ("=== Branch tests completed ===\n\n")
            ( (Point(row=155, column=8) -> Point(row=155, column=9)): (
            string_literal (Point(row=155, column=9) -> Point(row=155, column=45)): "=== Branch tests completed ===\n\n"
              " (Point(row=155, column=9) -> Point(row=155, column=10)): "
              string_content (Point(row=155, column=10) -> Point(row=155, column=40)): === Branch tests completed ===
              escape_sequence (Point(row=155, column=40) -> Point(row=155, column=42)): \n
              escape_sequence (Point(row=155, column=42) -> Point(row=155, column=44)): \n
              " (Point(row=155, column=44) -> Point(row=155, column=45)): "
            ) (Point(row=155, column=45) -> Point(row=155, column=46)): )
        ; (Point(row=155, column=46) -> Point(row=155, column=47)): ;
      expression_statement (Point(row=157, column=2) -> Point(row=157, column=24)): so3_file_operations();
        call_expression (Point(row=157, column=2) -> Point(row=157, column=23)): so3_file_operations()
          identifier (Point(row=157, column=2) -> Point(row=157, column=21)): so3_file_operations
          argument_list (Point(row=157, column=21) -> Point(row=157, column=23)): ()
            ( (Point(row=157, column=21) -> Point(row=157, column=22)): (
            ) (Point(row=157, column=22) -> Point(row=157, column=23)): )
        ; (Point(row=157, column=23) -> Point(row=157, column=24)): ;
      expression_statement (Point(row=158, column=2) -> Point(row=158, column=21)): so3_test_file_io();
        call_expression (Point(row=158, column=2) -> Point(row=158, column=20)): so3_test_file_io()
          identifier (Point(row=158, column=2) -> Point(row=158, column=18)): so3_test_file_io
          argument_list (Point(row=158, column=18) -> Point(row=158, column=20)): ()
            ( (Point(row=158, column=18) -> Point(row=158, column=19)): (
            ) (Point(row=158, column=19) -> Point(row=158, column=20)): )
        ; (Point(row=158, column=20) -> Point(row=158, column=21)): ;
      comment (Point(row=160, column=2) -> Point(row=160, column=23)): // 创建线程参数
      declaration (Point(row=161, column=2) -> Point(row=161, column=52)): ThreadArgs thread1_args = {1, "MAIN_LOGIC", 0xAA};
        type_identifier (Point(row=161, column=2) -> Point(row=161, column=12)): ThreadArgs
        init_declarator (Point(row=161, column=13) -> Point(row=161, column=51)): thread1_args = {1, "MAIN_LOGIC", 0xAA}
          identifier (Point(row=161, column=13) -> Point(row=161, column=25)): thread1_args
          = (Point(row=161, column=26) -> Point(row=161, column=27)): =
          initializer_list (Point(row=161, column=28) -> Point(row=161, column=51)): {1, "MAIN_LOGIC", 0xAA}
            { (Point(row=161, column=28) -> Point(row=161, column=29)): {
            number_literal (Point(row=161, column=29) -> Point(row=161, column=30)): 1
            , (Point(row=161, column=30) -> Point(row=161, column=31)): ,
            string_literal (Point(row=161, column=32) -> Point(row=161, column=44)): "MAIN_LOGIC"
              " (Point(row=161, column=32) -> Point(row=161, column=33)): "
              string_content (Point(row=161, column=33) -> Point(row=161, column=43)): MAIN_LOGIC
              " (Point(row=161, column=43) -> Point(row=161, column=44)): "
            , (Point(row=161, column=44) -> Point(row=161, column=45)): ,
            number_literal (Point(row=161, column=46) -> Point(row=161, column=50)): 0xAA
            } (Point(row=161, column=50) -> Point(row=161, column=51)): }
        ; (Point(row=161, column=51) -> Point(row=161, column=52)): ;
      declaration (Point(row=162, column=2) -> Point(row=162, column=49)): ThreadArgs thread2_args = {2, "COUNTER", 0xBB};
        type_identifier (Point(row=162, column=2) -> Point(row=162, column=12)): ThreadArgs
        init_declarator (Point(row=162, column=13) -> Point(row=162, column=48)): thread2_args = {2, "COUNTER", 0xBB}
          identifier (Point(row=162, column=13) -> Point(row=162, column=25)): thread2_args
          = (Point(row=162, column=26) -> Point(row=162, column=27)): =
          initializer_list (Point(row=162, column=28) -> Point(row=162, column=48)): {2, "COUNTER", 0xBB}
            { (Point(row=162, column=28) -> Point(row=162, column=29)): {
            number_literal (Point(row=162, column=29) -> Point(row=162, column=30)): 2
            , (Point(row=162, column=30) -> Point(row=162, column=31)): ,
            string_literal (Point(row=162, column=32) -> Point(row=162, column=41)): "COUNTER"
              " (Point(row=162, column=32) -> Point(row=162, column=33)): "
              string_content (Point(row=162, column=33) -> Point(row=162, column=40)): COUNTER
              " (Point(row=162, column=40) -> Point(row=162, column=41)): "
            , (Point(row=162, column=41) -> Point(row=162, column=42)): ,
            number_literal (Point(row=162, column=43) -> Point(row=162, column=47)): 0xBB
            } (Point(row=162, column=47) -> Point(row=162, column=48)): }
        ; (Point(row=162, column=48) -> Point(row=162, column=49)): ;
      declaration (Point(row=163, column=2) -> Point(row=163, column=46)): ThreadArgs thread3_args = {3, "MATH", 0xCC};
        type_identifier (Point(row=163, column=2) -> Point(row=163, column=12)): ThreadArgs
        init_declarator (Point(row=163, column=13) -> Point(row=163, column=45)): thread3_args = {3, "MATH", 0xCC}
          identifier (Point(row=163, column=13) -> Point(row=163, column=25)): thread3_args
          = (Point(row=163, column=26) -> Point(row=163, column=27)): =
          initializer_list (Point(row=163, column=28) -> Point(row=163, column=45)): {3, "MATH", 0xCC}
            { (Point(row=163, column=28) -> Point(row=163, column=29)): {
            number_literal (Point(row=163, column=29) -> Point(row=163, column=30)): 3
            , (Point(row=163, column=30) -> Point(row=163, column=31)): ,
            string_literal (Point(row=163, column=32) -> Point(row=163, column=38)): "MATH"
              " (Point(row=163, column=32) -> Point(row=163, column=33)): "
              string_content (Point(row=163, column=33) -> Point(row=163, column=37)): MATH
              " (Point(row=163, column=37) -> Point(row=163, column=38)): "
            , (Point(row=163, column=38) -> Point(row=163, column=39)): ,
            number_literal (Point(row=163, column=40) -> Point(row=163, column=44)): 0xCC
            } (Point(row=163, column=44) -> Point(row=163, column=45)): }
        ; (Point(row=163, column=45) -> Point(row=163, column=46)): ;
      comment (Point(row=165, column=2) -> Point(row=165, column=17)): // 创建线程
      declaration (Point(row=166, column=2) -> Point(row=166, column=38)): pthread_t thread1, thread2, thread3;
        type_identifier (Point(row=166, column=2) -> Point(row=166, column=11)): pthread_t
        identifier (Point(row=166, column=12) -> Point(row=166, column=19)): thread1
        , (Point(row=166, column=19) -> Point(row=166, column=20)): ,
        identifier (Point(row=166, column=21) -> Point(row=166, column=28)): thread2
        , (Point(row=166, column=28) -> Point(row=166, column=29)): ,
        identifier (Point(row=166, column=30) -> Point(row=166, column=37)): thread3
        ; (Point(row=166, column=37) -> Point(row=166, column=38)): ;
      comment (Point(row=168, column=2) -> Point(row=168, column=69)): // pthread_create(&thread1, NULL, work_thread_main, &thread1_args);
      expression_statement (Point(row=169, column=2) -> Point(row=169, column=69)): pthread_create(&thread2, NULL, work_thread_counter, &thread2_args);
        call_expression (Point(row=169, column=2) -> Point(row=169, column=68)): pthread_create(&thread2, NULL, work_thread_counter, &thread2_args)
          identifier (Point(row=169, column=2) -> Point(row=169, column=16)): pthread_create
          argument_list (Point(row=169, column=16) -> Point(row=169, column=68)): (&thread2, NULL, work_thread_counter, &thread2_args)
            ( (Point(row=169, column=16) -> Point(row=169, column=17)): (
            pointer_expression (Point(row=169, column=17) -> Point(row=169, column=25)): &thread2
              & (Point(row=169, column=17) -> Point(row=169, column=18)): &
              identifier (Point(row=169, column=18) -> Point(row=169, column=25)): thread2
            , (Point(row=169, column=25) -> Point(row=169, column=26)): ,
            null (Point(row=169, column=27) -> Point(row=169, column=31)): NULL
              NULL (Point(row=169, column=27) -> Point(row=169, column=31)): NULL
            , (Point(row=169, column=31) -> Point(row=169, column=32)): ,
            identifier (Point(row=169, column=33) -> Point(row=169, column=52)): work_thread_counter
            , (Point(row=169, column=52) -> Point(row=169, column=53)): ,
            pointer_expression (Point(row=169, column=54) -> Point(row=169, column=67)): &thread2_args
              & (Point(row=169, column=54) -> Point(row=169, column=55)): &
              identifier (Point(row=169, column=55) -> Point(row=169, column=67)): thread2_args
            ) (Point(row=169, column=67) -> Point(row=169, column=68)): )
        ; (Point(row=169, column=68) -> Point(row=169, column=69)): ;
      expression_statement (Point(row=170, column=2) -> Point(row=170, column=66)): pthread_create(&thread3, NULL, work_thread_math, &thread3_args);
        call_expression (Point(row=170, column=2) -> Point(row=170, column=65)): pthread_create(&thread3, NULL, work_thread_math, &thread3_args)
          identifier (Point(row=170, column=2) -> Point(row=170, column=16)): pthread_create
          argument_list (Point(row=170, column=16) -> Point(row=170, column=65)): (&thread3, NULL, work_thread_math, &thread3_args)
            ( (Point(row=170, column=16) -> Point(row=170, column=17)): (
            pointer_expression (Point(row=170, column=17) -> Point(row=170, column=25)): &thread3
              & (Point(row=170, column=17) -> Point(row=170, column=18)): &
              identifier (Point(row=170, column=18) -> Point(row=170, column=25)): thread3
            , (Point(row=170, column=25) -> Point(row=170, column=26)): ,
            null (Point(row=170, column=27) -> Point(row=170, column=31)): NULL
              NULL (Point(row=170, column=27) -> Point(row=170, column=31)): NULL
            , (Point(row=170, column=31) -> Point(row=170, column=32)): ,
            identifier (Point(row=170, column=33) -> Point(row=170, column=49)): work_thread_math
            , (Point(row=170, column=49) -> Point(row=170, column=50)): ,
            pointer_expression (Point(row=170, column=51) -> Point(row=170, column=64)): &thread3_args
              & (Point(row=170, column=51) -> Point(row=170, column=52)): &
              identifier (Point(row=170, column=52) -> Point(row=170, column=64)): thread3_args
            ) (Point(row=170, column=64) -> Point(row=170, column=65)): )
        ; (Point(row=170, column=65) -> Point(row=170, column=66)): ;
      expression_statement (Point(row=171, column=2) -> Point(row=171, column=34)): work_thread_main(&thread1_args);
        call_expression (Point(row=171, column=2) -> Point(row=171, column=33)): work_thread_main(&thread1_args)
          identifier (Point(row=171, column=2) -> Point(row=171, column=18)): work_thread_main
          argument_list (Point(row=171, column=18) -> Point(row=171, column=33)): (&thread1_args)
            ( (Point(row=171, column=18) -> Point(row=171, column=19)): (
            pointer_expression (Point(row=171, column=19) -> Point(row=171, column=32)): &thread1_args
              & (Point(row=171, column=19) -> Point(row=171, column=20)): &
              identifier (Point(row=171, column=20) -> Point(row=171, column=32)): thread1_args
            ) (Point(row=171, column=32) -> Point(row=171, column=33)): )
        ; (Point(row=171, column=33) -> Point(row=171, column=34)): ;
      expression_statement (Point(row=173, column=2) -> Point(row=173, column=52)): printf("Main thread: Created 3 worker threads\n");
        call_expression (Point(row=173, column=2) -> Point(row=173, column=51)): printf("Main thread: Created 3 worker threads\n")
          identifier (Point(row=173, column=2) -> Point(row=173, column=8)): printf
          argument_list (Point(row=173, column=8) -> Point(row=173, column=51)): ("Main thread: Created 3 worker threads\n")
            ( (Point(row=173, column=8) -> Point(row=173, column=9)): (
            string_literal (Point(row=173, column=9) -> Point(row=173, column=50)): "Main thread: Created 3 worker threads\n"
              " (Point(row=173, column=9) -> Point(row=173, column=10)): "
              string_content (Point(row=173, column=10) -> Point(row=173, column=47)): Main thread: Created 3 worker threads
              escape_sequence (Point(row=173, column=47) -> Point(row=173, column=49)): \n
              " (Point(row=173, column=49) -> Point(row=173, column=50)): "
            ) (Point(row=173, column=50) -> Point(row=173, column=51)): )
        ; (Point(row=173, column=51) -> Point(row=173, column=52)): ;
      comment (Point(row=175, column=2) -> Point(row=175, column=65)): // 主线程等待工作线程结束（实际上不会结束）
      comment (Point(row=176, column=2) -> Point(row=176, column=33)): // pthread_join(thread1, NULL);
      expression_statement (Point(row=177, column=2) -> Point(row=177, column=30)): pthread_join(thread2, NULL);
        call_expression (Point(row=177, column=2) -> Point(row=177, column=29)): pthread_join(thread2, NULL)
          identifier (Point(row=177, column=2) -> Point(row=177, column=14)): pthread_join
          argument_list (Point(row=177, column=14) -> Point(row=177, column=29)): (thread2, NULL)
            ( (Point(row=177, column=14) -> Point(row=177, column=15)): (
            identifier (Point(row=177, column=15) -> Point(row=177, column=22)): thread2
            , (Point(row=177, column=22) -> Point(row=177, column=23)): ,
            null (Point(row=177, column=24) -> Point(row=177, column=28)): NULL
              NULL (Point(row=177, column=24) -> Point(row=177, column=28)): NULL
            ) (Point(row=177, column=28) -> Point(row=177, column=29)): )
        ; (Point(row=177, column=29) -> Point(row=177, column=30)): ;
      expression_statement (Point(row=178, column=2) -> Point(row=178, column=30)): pthread_join(thread3, NULL);
        call_expression (Point(row=178, column=2) -> Point(row=178, column=29)): pthread_join(thread3, NULL)
          identifier (Point(row=178, column=2) -> Point(row=178, column=14)): pthread_join
          argument_list (Point(row=178, column=14) -> Point(row=178, column=29)): (thread3, NULL)
            ( (Point(row=178, column=14) -> Point(row=178, column=15)): (
            identifier (Point(row=178, column=15) -> Point(row=178, column=22)): thread3
            , (Point(row=178, column=22) -> Point(row=178, column=23)): ,
            null (Point(row=178, column=24) -> Point(row=178, column=28)): NULL
              NULL (Point(row=178, column=24) -> Point(row=178, column=28)): NULL
            ) (Point(row=178, column=28) -> Point(row=178, column=29)): )
        ; (Point(row=178, column=29) -> Point(row=178, column=30)): ;
      expression_statement (Point(row=180, column=2) -> Point(row=180, column=21)): dlclose(dl_handle);
        call_expression (Point(row=180, column=2) -> Point(row=180, column=20)): dlclose(dl_handle)
          identifier (Point(row=180, column=2) -> Point(row=180, column=9)): dlclose
          argument_list (Point(row=180, column=9) -> Point(row=180, column=20)): (dl_handle)
            ( (Point(row=180, column=9) -> Point(row=180, column=10)): (
            identifier (Point(row=180, column=10) -> Point(row=180, column=19)): dl_handle
            ) (Point(row=180, column=19) -> Point(row=180, column=20)): )
        ; (Point(row=180, column=20) -> Point(row=180, column=21)): ;
      return_statement (Point(row=181, column=2) -> Point(row=181, column=11)): return 0;
        return (Point(row=181, column=2) -> Point(row=181, column=8)): return
        number_literal (Point(row=181, column=9) -> Point(row=181, column=10)): 0
        ; (Point(row=181, column=10) -> Point(row=181, column=11)): ;
      } (Point(row=182, column=0) -> Point(row=182, column=1)): }