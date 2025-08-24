import os
import sys
from enum import IntEnum
from pathlib import Path

import cffi

ffi = cffi.FFI()

# Try to load the shared library from package location first
try:
    from importlib.resources import as_file, files
except ImportError:
    # Fallback for Python < 3.9
    from importlib_resources import as_file, files


# Load C definitions from header
def load_header():
    try:
        # Try to get header from package resources
        header_resource = files("op_parser").joinpath("include/op_parser_ffi.h")
        with as_file(header_resource) as header_path:
            if header_path.exists():
                with open(header_path, encoding="utf-8") as f:
                    return f.read()
    except (ImportError, FileNotFoundError):
        # Fallback to direct file access for development
        current_dir = Path(__file__).parent
        header_path = current_dir / "include" / "op_parser_ffi.h"
        if header_path.exists():
            with open(header_path, encoding="utf-8") as f:
                return f.read()

    raise RuntimeError("Could not find op_parser_ffi.h header file")


ffi.cdef(load_header())


# Define Python-side OperandType enum to match C definition
class OperandType(IntEnum):
    REGISTER = 0  # xN or wN register
    IMMEDIATE = 1  # #immediate value
    MEMREF = 2  # [memory reference]
    ADDRESS = 3  # 0x prefixed address
    OTHER = 4  # unclassified


def load_library():
    """Load the shared library from the package installation"""
    lib_name = "libop_parser.so" if sys.platform != "darwin" else "libop_parser.dylib"

    # First try to load from package resources
    try:
        lib_resource = files("op_parser").joinpath(lib_name)
        with as_file(lib_resource) as lib_path:
            if lib_path.exists():
                return ffi.dlopen(str(lib_path))
    except (ImportError, FileNotFoundError, OSError):
        pass

    # Fallback: try relative to current file (for development)
    current_dir = Path(__file__).parent
    lib_path = current_dir / lib_name
    if lib_path.exists():
        return ffi.dlopen(str(lib_path))

    # Fallback: try in the parent directory (for egg installs)
    parent_dir = current_dir.parent
    lib_path = parent_dir / lib_name
    if lib_path.exists():
        return ffi.dlopen(str(lib_path))

    # Fallback: try system paths
    try:
        return ffi.dlopen(lib_name)
    except OSError:
        raise RuntimeError(
            f"Shared library '{lib_name}' not found. Please ensure the package is properly installed and built."
        )


op_parser_lib = load_library()


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
        self.offset = c_line.offset  # 新增offset字段支持
        self.opcode = ffi.string(c_line.opcode).decode("utf-8")
        self.operands = [Operand(c_line.operands[i]) for i in range(c_line.operand_count)]

    def __repr__(self):
        operands_str = "\n  ".join(str(op) for op in self.operands)
        return (
            f"DisasmLine(addr=0x{self.addr:x}, offset={self.offset}, "
            f"opcode={self.opcode}, operands=[\n  {operands_str}\n])"
        )


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
            print(f"Addr: 0x{line.addr:x}, Offset: {line.offset}, Opcode: {line.opcode}")
            for i, op in enumerate(line.operands):
                print(f"  Operand {i + 1}: {op}")
                print(f"    Type: {op.type.name}")
            print()
    except ValueError as e:
        print(f"Error parsing disassembly: {str(e)}")
