import sys
from enum import IntEnum
from pathlib import Path

import cffi

ffi = cffi.FFI()

# Load C definitions from header
current_dir = Path(__file__).parent
header_path = current_dir / "op_parser/include" / "op_parser_ffi.h"
with open(header_path, encoding="utf-8") as f:
    ffi.cdef(f.read())


# Define Python-side OperandType enum to match C definition
class OperandType(IntEnum):
    REGISTER = 0  # xN or wN register
    IMMEDIATE = 1  # #immediate value
    MEMREF = 2  # [memory reference]
    ADDRESS = 3  # 0x prefixed address
    OTHER = 4  # unclassified


# Determine library path based on build type
LIB_NAME = "libop_parser.so" if sys.platform != "darwin" else "libop_parser.dylib"
LIB_PATH = current_dir / f"{LIB_NAME}"

if not LIB_PATH.exists():
    raise RuntimeError(f"Shared library not found at {LIB_PATH}. Please build the project first.")

op_parser_lib = ffi.dlopen(str(LIB_PATH))


class Operand:
    def __init__(self, c_operand):
        self.type = OperandType(c_operand.type)
        if self.type == OperandType.MEMREF:
            self.value = {
                "base_reg": ffi.string(c_operand.memref.base_reg).decode("utf-8"),
                "index_reg": ffi.string(c_operand.memref.index_reg).decode("utf-8"),
                "shift_op": ffi.string(c_operand.memref.shift_op).decode("utf-8"),
                "shift_amount": ffi.string(c_operand.memref.shift_amount).decode("utf-8"),
                "offset": ffi.string(c_operand.memref.offset).decode("utf-8"),
            }
        else:
            self.value = ffi.string(c_operand.value).decode("utf-8")

    def is_register(self):
        return self.type == OperandType.REGISTER

    def is_immediate(self):
        return self.type == OperandType.IMMEDIATE

    def is_memref(self):
        return self.type == OperandType.MEMREF

    def is_address(self):
        return self.type == OperandType.ADDRESS

    def __repr__(self):
        if self.type == OperandType.MEMREF:
            parts = []
            if self.value["base_reg"]:
                parts.append(f"base={self.value['base_reg']}")
            if self.value["index_reg"]:
                parts.append(f"index={self.value['index_reg']}")
            if self.value["shift_op"]:
                parts.append(f"shift_op={self.value['shift_op']}")
            if self.value["shift_amount"]:
                parts.append(f"shift_amount={self.value['shift_amount']}")
            if self.value["offset"]:
                parts.append(f"offset={self.value['offset']}")
            return f"Operand(MEMREF, {', '.join(parts)})"
        return f"Operand({self.type.name}, {self.value})"


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
        # 复杂内存引用测试用例
        "[x17, x16, lsl #3]",
        "[x1, x2, lsl #1]",
        "[x3, x4, lsr #2]",
        "[x5, x6, asr #3]",
        "[x7, x8, ror #4]",
    ]

    print("Operand parsing test:")
    for case in test_cases:
        print(f"Input: {case}")
        try:
            operands = parse_operands(case)
            for i, op in enumerate(operands):
                print(f"  Operand {i + 1}: {op}")
                print(f"    is_register: {op.is_register()}")
                print(f"    is_immediate: {op.is_immediate()}")
                print(f"    is_memref: {op.is_memref()}")
                print(f"    is_address: {op.is_address()}")
        except ValueError as e:
            print(f"  Error parsing: {str(e)}")
        print()

    # Test disassembly parsing
    disassembly = """0x100001240 <+0>:   sub    sp, sp, #0x90
0x100001244 <+4>:   stp    x29, x30, [sp, #0x80]
0x100001248 <+8>:   add    x29, sp, #0x80
0x10000124c <+12>:  stur   wzr, [x29, #-0x4]
0x100001250 <+16>:  ldr    x17, [x17, x16, lsl #3]"""

    print("\nDisassembly parsing test:")
    try:
        lines = parse_disassembly(disassembly)
        for line in lines:
            print(f"Addr: 0x{line.addr:x}, Opcode: {line.opcode}")
            for i, op in enumerate(line.operands):
                print(f"  Operand {i + 1}: {op}")
                print(f"    Type: {op.type.name}")
            print()
    except ValueError as e:
        print(f"Error parsing disassembly: {str(e)}")
