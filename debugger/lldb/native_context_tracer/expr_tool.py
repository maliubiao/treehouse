#!/usr/bin/env python3
import argparse
import logging
import sys
import tempfile
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from ..tree import ParserLoader, parse_code_file
from .expr_extractor import ExpressionExtractor
from .expr_types import ExprType

# Configure logging for the tool
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ExpressionTool")


class ExpressionTool:
    """
    A command-line tool and testing utility for the ExpressionExtractor.

    To run this tool, execute it as a module from the project root directory:
    `python -m debugger.lldb.tracer.expr_tool <args>`
    """

    def __init__(self):
        self.extractor = ExpressionExtractor()
        self.parser_loader = ParserLoader()

    def extract_from_source(
        self, source_code: bytes, language: str = "cpp"
    ) -> Dict[int, List[Tuple[ExprType, str, Tuple[int, int, int, int]]]]:
        """Extracts expressions from a given source code string."""
        # Use a temporary file to allow tree-sitter to infer the language
        suffix = ".cpp" if language == "cpp" else ".c"
        with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as temp_file:
            temp_file.write(source_code)
            temp_file.flush()

            parser, _, _ = self.parser_loader.get_parser(temp_file.name)
            tree = parse_code_file(temp_file.name, parser)
            return self.extractor.extract(tree.root_node, source_code)

    def annotate_source(self, source_code: bytes, expressions: Dict[int, List[Tuple[ExprType, str, Any]]]) -> str:
        """Adds comments to the source code showing the extracted expressions."""
        lines = source_code.decode("utf8").splitlines()
        annotated_lines = []

        # Group expressions by line for annotation
        line_comments = defaultdict(list)
        for line_num, expr_list in expressions.items():
            for expr_type, expr_text, _ in expr_list:
                line_comments[line_num].append(f"{expr_type.name}: '{expr_text}'")

        for i, line in enumerate(lines):
            if i in line_comments:
                # Append comments to the end of the line
                comments = " // " + ", ".join(line_comments[i])
                annotated_lines.append(line + comments)
            else:
                annotated_lines.append(line)

        return "\n".join(annotated_lines)

    def run_tests(self):
        """
        Runs a comprehensive set of tests against a predefined C++ code block.
        This validates the accuracy of the expression extractor.
        """
        logger.info("Running built-in test suite...")
        test_code = b"""
        #include <iostream>
        #include <vector>

        struct Point { float x, y; };
        class Tool { public: static int size() { return 1; } };
        int getIndex() { return 0; }

        int main(int argc, char** argv) {
            int a = 5;
            int *ptr = &a;
            int **pptr = &ptr;
            a = 10;
            *ptr += 1;

            Point p1 = {1.0f, 2.0f};
            Point *p_ptr = &p1;
            p1.x = 3.0f;
            p_ptr->y = 4.0f;

            int arr[2];
            arr[0] = **pptr;
            a = p1.x + *ptr;
            int b = (int)p1.x; // Type cast should be ignored

            if (a > 0 && p_ptr != nullptr) {
                printf("Value: %d\\n", a);
            }

            for (int i = 0; i < 2; ++i) {
                arr[i] = i;
            }

            // Function calls where arguments should be extracted, but not the call itself.
            int size = Tool::size();
            int value = arr[getIndex()];
            
            // Range-based for where the container is extracted, but not the loop var.
            std::vector<int> vec = {1, 2, 3};
            for (auto& item : vec) {
                item++;
            }
        }
        """

        expressions = self.extract_from_source(test_code)

        # Flatten the results for easier comparison
        extracted_exprs = set()
        for expr_list in expressions.values():
            for expr_type, expr_text, _ in expr_list:
                extracted_exprs.add((expr_type, expr_text))

        # Define what we expect to find
        expected_exprs = {
            (ExprType.ASSIGNMENT_TARGET, "a"),
            (ExprType.ADDRESS_OF, "&a"),
            (ExprType.ASSIGNMENT_TARGET, "ptr"),
            (ExprType.ASSIGNMENT_TARGET, "pptr"),
            (ExprType.ADDRESS_OF, "&ptr"),
            (ExprType.ASSIGNMENT_TARGET, "*ptr"),
            (ExprType.POINTER_DEREF, "*ptr"),
            (ExprType.ASSIGNMENT_TARGET, "p1"),
            (ExprType.ASSIGNMENT_TARGET, "p_ptr"),
            (ExprType.ADDRESS_OF, "&p1"),
            (ExprType.ASSIGNMENT_TARGET, "p1.x"),
            (ExprType.MEMBER_ACCESS, "p1.x"),
            (ExprType.ASSIGNMENT_TARGET, "p_ptr->y"),
            (ExprType.MEMBER_ACCESS, "p_ptr->y"),
            (ExprType.ASSIGNMENT_TARGET, "arr[0]"),
            (ExprType.SUBSCRIPT_EXPRESSION, "arr[0]"),
            (ExprType.ASSIGNMENT_TARGET, "**pptr"),
            (ExprType.POINTER_DEREF, "**pptr"),
            (ExprType.ASSIGNMENT_TARGET, "b"),
            (ExprType.VARIABLE_ACCESS, "a"),
            (ExprType.VARIABLE_ACCESS, "p_ptr"),
            (ExprType.ASSIGNMENT_TARGET, "arr[i]"),
            (ExprType.SUBSCRIPT_EXPRESSION, "arr[i]"),
            (ExprType.VARIABLE_ACCESS, "i"),
            (ExprType.ASSIGNMENT_TARGET, "size"),
            (ExprType.ASSIGNMENT_TARGET, "value"),
            (ExprType.SUBSCRIPT_EXPRESSION, "arr[getIndex()]"),
            (ExprType.VARIABLE_ACCESS, "vec"),
            (ExprType.ASSIGNMENT_TARGET, "item"),
        }

        # Define what we expect *not* to find
        unexpected_exprs = {"main", "argc", "argv", "printf", "Tool::size", "getIndex", "item"}

        # --- Validation ---
        success = True
        missing = expected_exprs - extracted_exprs
        if missing:
            logger.error("TEST FAILED: The following expressions were NOT found:")
            for expr_type, expr_text in sorted(list(missing)):
                print(f"  - {expr_type.name}: '{expr_text}'")
            success = False

        found_unexpected = set()
        for _, expr_text in extracted_exprs:
            if expr_text in unexpected_exprs:
                found_unexpected.add(expr_text)

        if found_unexpected:
            logger.error("TEST FAILED: The following unexpected expressions WERE found:")
            for expr_text in sorted(list(found_unexpected)):
                print(f"  - '{expr_text}'")
            success = False

        if success:
            logger.info("All tests passed!")

        return success


def main():
    """Command-line interface for the ExpressionTool."""
    parser = argparse.ArgumentParser(
        description="Extracts and analyzes evaluatable expressions from C/C++ source code."
    )
    parser.add_argument("input_file", nargs="?", help="Path to the source code file to analyze.")
    parser.add_argument("--annotate", action="store_true", help="Print the source code with annotations.")
    parser.add_argument("--test", action="store_true", help="Run the built-in test suite.")

    args = parser.parse_args()

    tool = ExpressionTool()

    if args.test:
        sys.exit(0 if tool.run_tests() else 1)

    if not args.input_file:
        parser.print_help()
        sys.exit(1)

    try:
        with open(args.input_file, "rb") as f:
            source_code = f.read()
    except FileNotFoundError:
        logger.error("Input file not found: %s", args.input_file)
        sys.exit(1)

    expressions = tool.extract_from_source(source_code)

    if args.annotate:
        annotated_code = tool.annotate_source(source_code, expressions)
        print(annotated_code)
    else:
        for line_num, expr_list in sorted(expressions.items()):
            print(f"--- Line {line_num + 1} ---")
            for _, expr_text, _ in expr_list:
                print(f"  - Type: {expr_type.name:<20} Text: '{expr_text}'")


if __name__ == "__main__":
    main()
