# OP Parser 测试机制

## 概述

OP Parser 包提供了多种测试机制来验证功能正确性和内存安全性：

1. **C 测试程序** - 测试核心解析库功能
2. **Python 测试** - 测试 Python 绑定接口  
3. **内存安全测试** - 使用 AddressSanitizer 检测内存问题

## 1. C 测试程序

### 测试内容
C 测试程序 (`test/op_parser_main.c`) 测试核心解析功能：
- 寄存器操作数解析 (`sp`, `x8`, `w0`)
- 立即数操作数解析 (`#0x90`, `#5`)
- 内存引用解析 (`[x29, #-0x4]`, `[sp]`)
- 复杂内存引用解析 (`[x17, x16, lsl #3]`)
- 地址解析 (`0x10000140c`)
- 完整反汇编行解析

### 运行方法

#### 直接构建和运行：
```bash
cd src/op_parser
mkdir build
cd build
cmake ..
make
./op_parser_test
```

#### 使用 setup.py 构建后运行：
```bash
python setup.py build_ext --inplace
cd src/op_parser
./op_parser_test
```

### 预期输出
```
Input: [x17, x16, lsl #3]
  Operand: MEMREF (base: x17, index: x16, shift: lsl #3, offset: )

Input: [x1, x2, lsl #1]  
  Operand: MEMREF (base: x1, index: x2, shift: lsl #1, offset: )

Disassembly parsing test:
Addr: 0x100001240, Offset: 0, Opcode: sub
  Operand 1: REGISTER  (sp)
  Operand 2: REGISTER  (sp) 
  Operand 3: IMMEDIATE (#0x90)

Addr: 0x100001250, Offset: 16, Opcode: ldr
  Operand 1: REGISTER  (x17)
  Operand 2: MEMREF    (base: x17, index: x16, shift: lsl #3, offset: )

All tests passed!
```

## 2. Python 测试

### 测试内容
Python 测试 (`op_parser.py` 中的 `__main__` 部分) 测试：
- Python 绑定接口正确性
- 操作数类型检测方法
- 复杂内存引用的 Python 表示
- 多行反汇编解析

### 运行方法

#### 直接运行模块：
```bash
python -m op_parser.op_parser
```

#### 导入后交互测试：
```bash
python
>>> from op_parser import parse_operands, parse_disassembly_line
>>> operands = parse_operands("[x17, x16, lsl #3]")
>>> for op in operands:
...     print(op)
Operand(MEMREF, base=x17, index=x16, shift_op=lsl, shift_amount=3)
```

### 预期输出
```
Operand parsing test:
Input: [x17, x16, lsl #3]
  Operand 1: Operand(MEMREF, base=x17, index=x16, shift_op=lsl, shift_amount=3)
    is_register: False
    is_immediate: False
    is_memref: True
    is_address: False

Disassembly parsing test:
Addr: 0x100001240, Offset: 0, Opcode: sub
  Operand 1: Operand(REGISTER, sp)
  Operand 2: Operand(REGISTER, sp)
  Operand 3: Operand(IMMEDIATE, #0x90)

Addr: 0x100001250, Offset: 16, Opcode: ldr  
  Operand 1: Operand(REGISTER, x17)
  Operand 2: Operand(MEMREF, base=x17, index=x16, shift_op=lsl, shift_amount=3)
```

## 3. 内存安全测试 (AddressSanitizer)

### 测试内容
在 Debug 构建中启用 AddressSanitizer 检测：
- 内存越界访问
- 使用未初始化内存
- 内存泄漏
- 重复释放等问题

### 运行方法

#### 启用 ASan 构建：
```bash
cd src/op_parser
mkdir build
cd build
cmake -DCMAKE_BUILD_TYPE=Debug ..
make
```

#### 运行 ASan 测试：
```bash
./op_parser_test
```

### 预期行为
- 测试通过时无额外输出（与正常测试相同）
- 如果检测到内存问题，ASan 会输出详细的错误报告：
```
==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x60200000eff0
READ of size 1 at 0x60200000eff0 thread T0
    #0 0x55a5b0b5a1a2 in parse_operands op_parser.c:123
    #1 0x55a5b0b5b5c3 in test_operand_parsing op_parser_main.c:45
```

## 4. 测试用例覆盖

### 操作数类型测试
- ✅ 寄存器: `sp`, `x8`, `w0`
- ✅ 立即数: `#0x90`, `#5`  
- ✅ 内存引用: `[sp]`, `[x29, #-0x4]`
- ✅ 地址: `0x10000140c`
- ✅ 复杂内存引用: `[x17, x16, lsl #3]`

### 移位操作测试
- ✅ LSL (逻辑左移): `lsl #1`, `lsl #3`
- ✅ LSR (逻辑右移): `lsr #2`
- ✅ ASR (算术右移): `asr #3`  
- ✅ ROR (循环右移): `ror #4`

### 反汇编行解析测试
- ✅ 地址解析: `0x100001240`
- ✅ 偏移量解析: `<+0>`, `<+16>`
- ✅ 操作码解析: `sub`, `ldr`, `stp`
- ✅ 多操作数解析

## 5. 完整测试流程

### 开发环境测试
```bash
# 1. 构建和测试 C 库
cd src/op_parser
mkdir build && cd build
cmake .. && make
./op_parser_test

# 2. 构建 Python 扩展
cd ../..
python setup.py build_ext --inplace

# 3. 测试 Python 绑定
python -m op_parser.op_parser

# 4. 内存安全测试 (可选)
cd src/op_parser/build
rm -rf * && cmake -DCMAKE_BUILD_TYPE=Debug .. && make
./op_parser_test
```

### 安装后测试
```bash
# 安装包
pip install .

# 测试导入和基本功能
python -c "
from op_parser import parse_operands, parse_disassembly_line
ops = parse_operands('[x17, x16, lsl #3]')
print('Complex memref:', ops[0])
line = parse_disassembly_line('0x100001250 <+16>: ldr x17, [x17, x16, lsl #3]')
print('Disasm line offset:', line.offset)
"
```

## 6. 测试失败处理

如果测试失败：

1. **检查构建日志**：确保没有编译错误
2. **验证测试用例**：查看 `test/op_parser_main.c` 和 `op_parser.py` 中的测试用例
3. **运行单个测试**：可以修改测试程序来单独运行特定用例
4. **启用详细输出**：在 CMake 中使用 `-DCMAKE_VERBOSE_MAKEFILE=ON` 查看详细构建过程
5. **检查内存问题**：使用 Debug 构建和 ASan 检测内存错误

## 总结

OP Parser 提供了完整的测试机制，包括：
- ✅ 核心功能的 C 测试程序
- ✅ Python 绑定的集成测试  
- ✅ 内存安全的 AddressSanitizer 检测
- ✅ 全面覆盖各种操作数类型和复杂内存引用
- ✅ 简单易用的测试命令和流程

测试设计确保了代码质量、功能正确性和内存安全性。