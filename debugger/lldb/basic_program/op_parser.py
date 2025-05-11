import sys
from pathlib import Path
import cffi

ffi = cffi.FFI()

# Load C definitions from header
current_dir = Path(__file__).parent
header_path = current_dir / "include" / "op_parser_ffi.h"
with open(header_path, encoding="utf-8") as f:
    ffi.cdef(f.read())

# Determine library path based on build type
LIB_NAME = "libop_parser.so" if sys.platform != "darwin" else "libop_parser.dylib"
LIB_PATH = current_dir.parent / f"build/{LIB_NAME}"

if not LIB_PATH.exists():
    raise RuntimeError(f"Shared library not found at {LIB_PATH}. Please build the project first.")

op_parser_lib = ffi.dlopen(str(LIB_PATH))


class Operand:
    def __init__(self, c_operand):
        self.type = c_operand.type
        if self.type == op_parser_lib.OPERAND_MEMREF:
            self.value = {
                "base_reg": ffi.string(c_operand.memref.base_reg).decode("utf-8"),
                "offset": ffi.string(c_operand.memref.offset).decode("utf-8"),
            }
        else:
            self.value = ffi.string(c_operand.value).decode("utf-8")

    def __repr__(self):
        type_str = op_parser_lib.operand_type_to_str(self.type)
        if self.type == op_parser_lib.OPERAND_MEMREF:
            return f"Operand({type_str}, base={self.value['base_reg']}, offset={self.value['offset']})"
        return f"Operand({type_str}, {self.value})"


def parse_operands(asm_str, max_ops=4):
    c_ops = ffi.new(f"Operand[{max_ops}]")
    c_str = ffi.new("char[]", asm_str.encode("utf-8"))

    count = op_parser_lib.parse_operands(c_str, c_ops, max_ops)
    return [Operand(c_ops[i]) for i in range(count)]


def operand_type_to_str(operand_type):
    return ffi.string(op_parser_lib.operand_type_to_str(operand_type)).decode("utf-8")


if __name__ == "__main__":
    # Example usage
    test_cases = [
        "sp",
        "[x29, #-0x4]",
        "#0x90",
        "0x10000140c",
        "x8",
        "#5",
        "[sp]",
        "stp    x29, x30, [sp, #0x80]",
        "blr    x8",
        "0x10000140c",
        "[x0, x1]",
        "[#0x20]",
        "[, #0x30]",
        "x8, [x8, #0x8]",
    ]

    for case in test_cases:
        print(f"Input: {case}")
        try:
            operands = parse_operands(case)
            for i, op in enumerate(operands):
                print(f"  Operand {i + 1}: {op}")
        except ValueError as e:
            print(f"  Error parsing: {str(e)}")
        print()
