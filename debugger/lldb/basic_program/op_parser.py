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


class DisasmLine:
    def __init__(self, c_line):
        self.addr = c_line.addr
        self.opcode = ffi.string(c_line.opcode).decode("utf-8")
        self.operands = [Operand(c_line.operands[i]) for i in range(c_line.operand_count)]

    def __repr__(self):
        operands_str = "\n  ".join(str(op) for op in self.operands)
        return f"DisasmLine(addr=0x{self.addr:x}, opcode={self.opcode}, operands=[\n  {operands_str}\n])"


def parse_operands(asm_str, max_ops=4):
    c_ops = ffi.new(f"Operand[{max_ops}]")
    c_str = ffi.new("char[]", asm_str.encode("utf-8"))

    count = op_parser_lib.parse_operands(c_str, c_ops, max_ops)
    return [Operand(c_ops[i]) for i in range(count)]


def parse_disassembly_line(line):
    c_line = ffi.new("DisasmLine *")
    c_str = ffi.new("char[]", line.encode("utf-8"))

    if not op_parser_lib.parse_disassembly_line(c_str, c_line):
        raise ValueError("Failed to parse disassembly line")
    return DisasmLine(c_line)


def parse_disassembly(disassembly, max_lines=10):
    c_lines = ffi.new(f"DisasmLine[{max_lines}]")
    c_str = ffi.new("char[]", disassembly.encode("utf-8"))

    count = op_parser_lib.parse_disassembly(c_str, c_lines, max_lines)
    return [DisasmLine(c_lines[i]) for i in range(count)]


def operand_type_to_str(operand_type):
    return ffi.string(op_parser_lib.operand_type_to_str(operand_type)).decode("utf-8")


if __name__ == "__main__":
    # Test operand parsing
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

    print("Operand parsing test:")
    for case in test_cases:
        print(f"Input: {case}")
        try:
            operands = parse_operands(case)
            for i, op in enumerate(operands):
                print(f"  Operand {i + 1}: {op}")
        except ValueError as e:
            print(f"  Error parsing: {str(e)}")
        print()

    # Test disassembly parsing
    disassembly = """0x100001240 <+0>:   sub    sp, sp, #0x90
0x100001244 <+4>:   stp    x29, x30, [sp, #0x80]
0x100001248 <+8>:   add    x29, sp, #0x80
0x10000124c <+12>:  stur   wzr, [x29, #-0x4]"""

    print("\nDisassembly parsing test:")
    try:
        lines = parse_disassembly(disassembly)
        for line in lines:
            print(f"Addr: 0x{line.addr:x}, Opcode: {line.opcode}")
            for i, op in enumerate(line.operands):
                print(f"  Operand {i + 1}: {op}")
            print()
    except ValueError as e:
        print(f"Error parsing disassembly: {str(e)}")
