# OP Parser Library

ARM指令操作数解析库，支持解析寄存器、立即数、内存引用和地址等操作数类型。

## 功能特性
- 解析反汇编行中的地址、操作码和操作数
- 提取地址偏移量（如 `<+16>` 中的16）
- 支持简单和复杂内存引用格式：
  - `[base]`
  - `[base, #offset]`
  - `[base, index]`
  - `[base, index, shift_op #shift_amount]` (支持lsl, lsr, asr, ror移位操作)
- 提供C接口和Python绑定
- 支持AddressSanitizer内存检测（Debug构建）

## Python绑定使用

```python
from op_parser import parse_operands, parse_disassembly_line, parse_disassembly

# 解析复杂内存引用
operands = parse_operands("[x17, x16, lsl #3]")
for op in operands:
    print(op)  # 输出: Operand(MEMREF, base=x17, index=x16, shift_op=lsl, shift_amount=3)

# 解析一行反汇编
line = parse_disassembly_line("0x100001250 <+16>:  ldr    x17, [x17, x16, lsl #3]")
print(f"Address: 0x{line.addr:x}, Offset: {line.offset}")  # 输出: Address: 0x100001250, Offset: 16
print(line.opcode)  # 输出: ldr
print(line.operands[0])  # 输出: Operand(MEMREF, base=x17, index=x16, shift_op=lsl, shift_amount=3)

# 解析多行反汇编
disassembly = \"\"\"0x100001240 <+0>:   sub    sp, sp, #0x90
0x100001244 <+4>:   stp    x29, x30, [sp, #0x80]\"\"\"
lines = parse_disassembly(disassembly)
for line in lines:
    print(f"0x{line.addr:x} <+{line.offset}>: {line.opcode}")
```

## 构建说明

```bash
mkdir build
cd build
cmake ..
make
```

## 测试

### 常规测试
运行测试程序：
```bash
./op_parser_test
```

### 内存安全测试（Debug构建）
在Debug构建中自动启用AddressSanitizer：
```bash
cd build
cmake -DCMAKE_BUILD_TYPE=Debug ..
make
./op_parser_test
```

运行Python测试：
```bash
python op_parser.py
```

测试用例覆盖：
- 寄存器操作数
- 立即数操作数
- 地址偏移量解析
- 简单内存引用
- 带索引和移位操作的复杂内存引用
- 完整反汇编解析
- 内存安全检测（Debug构建）