"""
OP Parser package - ARM instruction operand parser with C extensions.
"""

from .op_parser import (
    DisasmLine,
    Operand,
    OperandType,
    parse_disassembly,
    parse_disassembly_line,
    parse_operands,
)

__version__ = "0.1.0"
__all__ = [
    "Operand",
    "OperandType",
    "DisasmLine",
    "parse_operands",
    "parse_disassembly_line",
    "parse_disassembly",
]
