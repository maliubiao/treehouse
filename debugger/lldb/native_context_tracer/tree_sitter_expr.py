from pathlib import Path

from tree_sitter import Parser

import_path = Path(__file__).parent.parent
import sys

print(import_path)
sys.path.append(str(import_path))
import os

from expr_extractor import ExpressionExtractor, ExprType
from tracer import expr_extractor


def parse_code_file(file_path: str, parser: Parser) -> any:
    with open(file_path, "rb") as file:
        source = file.read()
    return parser.parse(source)


def extract_expressions(tree, source: bytes) -> dict:
    extractor = ExpressionExtractor()
    return extractor.extract(tree.root_node, source)


def print_expressions(expr_dict):
    for line, expr_list in sorted(expr_dict.items()):
        print(f"行号 {line}:")
        for expr_type, expr_text, pos in expr_list:
            print(f"  {ExprType(expr_type).name}: '{expr_text}' 位置: {pos}")
