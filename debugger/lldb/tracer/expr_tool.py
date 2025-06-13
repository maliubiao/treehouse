#!/usr/bin/env python3
import argparse
import logging
import sys
import tempfile
from typing import Dict, List, Tuple

from expr_extractor import ExpressionExtractor, ExprType

from tree import ParserLoader, parse_code_file

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ExpressionTool")


class ExpressionTool:
    def __init__(self):
        self.extractor = ExpressionExtractor()
        self.parser_loader = ParserLoader()

    def extract_expressions(
        self, source_code: bytes
    ) -> Dict[int, List[Tuple[ExprType, str, Tuple[int, int, int, int]]]]:
        """从源代码中提取表达式"""
        with tempfile.NamedTemporaryFile(delete=True, suffix=".cpp") as temp_file:
            temp_file.write(source_code)
            temp_file.flush()

            parser, _, _ = self.parser_loader.get_parser(temp_file.name)
            tree = parse_code_file(temp_file.name, parser)
            return self.extractor.extract(tree.root_node, source_code)

    def annotate_source(
        self, source_code: bytes, expressions: Dict[int, List[Tuple[ExprType, str, Tuple[int, int, int, int]]]]
    ) -> str:
        """在源代码中添加表达式注释"""
        lines = source_code.decode("utf8").splitlines()
        annotated_lines = []

        for line_num, line in enumerate(lines):
            annotated_line = line
            if line_num in expressions:
                # 收集当前行的所有表达式
                expr_comments = []
                for expr_type, expr_text, _ in expressions[line_num]:
                    expr_comments.append(f"{ExprType(expr_type).name}: {expr_text}")

                # 添加注释
                if expr_comments:
                    annotated_line += " // " + ", ".join(expr_comments)

            annotated_lines.append(annotated_line)

        return "\n".join(annotated_lines)

    def run_tests(self):
        """运行内置测试用例"""
        test_code = """
        #include <iostream>

        template<typename T>
        class MyVector {
        public:
            void push_back(const T& value) {
                data.push_back(value);
            }

            T& operator[](size_t index) {
                return data[index];
            }

        private:
            std::vector<T> data;
        };

        struct Point {
            float x;
            float y;
        };

        int main() {
            // 基础表达式
            int a = 5;
            int *ptr = &a;
            int **pptr = &ptr;

            // 结构体和指针
            Point p1 = {.x=10, .y=20};
            Point *p_ptr = &p1;

            // 复杂表达式
            a = p1.x + *ptr;
            p_ptr->y = 30;
            *pptr = 50;

            // 函数调用参数
            printf("Value: %d\\n", a);

            // 模板实例化
            MyVector<int> vec;
            vec.push_back(42);
            int val = vec[0];

            // 控制流中的表达式
            if (a > 0) {
                return val * 2;
            }

            // 多级成员访问
            Point p2 = {.x=1.5, .y=2.5};
            p_ptr = &p2;
            float result = p_ptr->x + p2.y;

            // 类型转换（应排除）
            int num = (int)(p_ptr->x);

            // 内联汇编（应排除）
            asm volatile("nop");

            return 0;
        }
        """.encode("utf8")

        expressions = self.extract_expressions(test_code)
        extracted_exprs = set()
        for expr_list in expressions.values():
            for expr_type, expr_text, _ in expr_list:
                extracted_exprs.add((expr_type, expr_text))

        # 预期提取的表达式
        expected_exprs = {
            (ExprType.VARIABLE_ACCESS, "a"),
            (ExprType.LITERAL, "5"),
            (ExprType.VARIABLE_ACCESS, "ptr"),
            (ExprType.ADDRESS_OF, "&a"),
            (ExprType.VARIABLE_ACCESS, "pptr"),
            (ExprType.ADDRESS_OF, "&ptr"),
            (ExprType.VARIABLE_ACCESS, "p1"),
            (ExprType.LITERAL, "10"),
            (ExprType.LITERAL, "20"),
            (ExprType.VARIABLE_ACCESS, "p_ptr"),
            (ExprType.ADDRESS_OF, "&p1"),
            (ExprType.ASSIGNMENT_TARGET, "a"),
            (ExprType.MEMBER_ACCESS, "p1.x"),
            (ExprType.POINTER_DEREF, "*ptr"),
            (ExprType.ASSIGNMENT_TARGET, "p_ptr->y"),
            (ExprType.MEMBER_ACCESS, "p_ptr->y"),
            (ExprType.LITERAL, "30"),
            (ExprType.ASSIGNMENT_TARGET, "*pptr"),
            (ExprType.POINTER_DEREF, "*pptr"),
            (ExprType.LITERAL, "50"),
            (ExprType.LITERAL, '"Value: %d\\n"'),
            (ExprType.VARIABLE_ACCESS, "a"),  # printf参数中的a
            (ExprType.VARIABLE_ACCESS, "vec"),
            (ExprType.LITERAL, "42"),
            (ExprType.VARIABLE_ACCESS, "val"),
            (ExprType.VARIABLE_ACCESS, "vec"),  # vec[0]中的vec
            (ExprType.LITERAL, "0"),
            (ExprType.VARIABLE_ACCESS, "a"),  # if条件中的a
            (ExprType.LITERAL, "0"),  # if条件中的0
            (ExprType.VARIABLE_ACCESS, "val"),  # return中的val
            (ExprType.LITERAL, "2"),
            (ExprType.VARIABLE_ACCESS, "p2"),
            (ExprType.LITERAL, "1.5"),
            (ExprType.LITERAL, "2.5"),
            (ExprType.ASSIGNMENT_TARGET, "p_ptr"),
            (ExprType.ADDRESS_OF, "&p2"),
            (ExprType.VARIABLE_ACCESS, "result"),
            (ExprType.MEMBER_ACCESS, "p_ptr->x"),
            (ExprType.MEMBER_ACCESS, "p2.y"),
        }

        # 预期排除的表达式
        excluded_exprs = {
            (ExprType.LITERAL, '"nop"'),  # 内联汇编中的字符串
        }

        # 验证所有预期表达式都被提取到
        missing = expected_exprs - extracted_exprs
        if missing:
            logger.error(f"测试失败: 未提取到预期表达式: {missing}")
            return False

        # 验证排除的表达式没有被提取
        unexpected = set()
        for expr_type, expr_text in excluded_exprs:
            if (expr_type, expr_text) in extracted_exprs:
                unexpected.add((expr_type, expr_text))
        if unexpected:
            logger.error(f"测试失败: 错误提取了排除的表达式: {unexpected}")
            return False

        logger.info("所有测试通过!")
        return True


def main():
    parser = argparse.ArgumentParser(description="表达式提取工具")
    parser.add_argument("--source-comment", action="store_true", help="在源代码中添加表达式注释")
    parser.add_argument("--test", action="store_true", help="运行测试用例")
    parser.add_argument("input_file", nargs="?", help="输入源代码文件路径")

    args = parser.parse_args()

    tool = ExpressionTool()

    if args.test:
        sys.exit(0 if tool.run_tests() else 1)
    elif args.source_comment:
        if not args.input_file:
            logger.error("需要指定输入文件")
            sys.exit(1)

        with open(args.input_file, "rb") as f:
            source_code = f.read()

        expressions = tool.extract_expressions(source_code)
        annotated_source = tool.annotate_source(source_code, expressions)
        print(annotated_source)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
