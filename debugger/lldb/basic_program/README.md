# basic_program 项目说明

这是一个用于LLDB调试练习的基础C程序项目，包含多种调试场景的示例代码。

## 项目结构

```
basic_program/
├── arm64_asm/            # ARM64汇编测试代码
│   ├── branch_test.s     # 分支指令测试
│   └── cond_branch_test.s # 条件分支测试
├── basic_lib.c           # 基础库实现
├── basic_lib.h           # 基础库头文件
├── basic_main.c          # 主程序入口
├── branch_test_main.c    # 分支测试入口
├── cond_branch_test_main.c # 条件分支测试入口
├── test_entry_point.h    # 测试函数声明
├── basic.c               # 简单测试程序
├── CMakeLists.txt        # 构建配置
├── so1/                  # 动态库1
│   ├── basic_so1.c
│   └── basic_so1.h
└── so2/                  # 动态库2
    ├── basic_so2.c
    └── basic_so2.h
```

## 功能特性

1. **基础调试功能**:
   - 函数调用跟踪
   - 系统调用示例
   - 循环和条件语句
   - 递归调用

2. **动态库交互**:
   - 两个动态库(so1, so2)互相调用
   - 全局变量访问
   - 弱符号处理
   - PLT/GOT表调用

3. **ARM64指令测试**:
   - 无条件分支(B, BR)
   - 条件分支(B.eq, B.ne等)
   - 链接分支(BL, BLR)
   - 测试分支(CBZ, TBZ)
   - 主程序集成汇编测试函数

4. **独立测试程序**:
   - `branch_test`: 独立分支测试程序
   - `cond_branch_test`: 独立条件分支测试程序

## 构建说明

```bash
mkdir build && cd build
cmake ..
make
```

构建产物:
- `basic_program`: 主可执行文件(包含ARM64汇编测试)
- `branch_test`: **独立分支测试程序**
- `cond_branch_test`: **独立条件分支测试程序**
- `libso1.so`: 动态库1
- `libso2.so`: 动态库2

## 调试示例

1. 启动调试:
```bash
lldb ./basic_program
```

2. 常用调试命令:
- 在NOP指令处设置断点: `b basic_main.c:30` (第30行的nop)
- 跟踪动态库调用: `b so1_function`
- 查看全局变量: `p so1_global_var`
- 反汇编当前函数: `disassemble -f`
- 调试ARM64汇编: `b _run_branch_tests`

3. 测试脚本:
```bash
./test_arm64_asm.sh  # 测试ARM64汇编功能

# 单独运行分支测试
./build/branch_test

# 单独运行条件分支测试
./build/cond_branch_test
```

## 设计文档

更多实现细节请参考[DESIGN.md](DESIGN.md)

## 已知问题

当前存在的问题记录在[BUG.md](BUG.md)