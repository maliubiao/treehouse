# 设计文档

## 地址偏移解析支持

### 需求
增强反汇编行解析功能，支持提取地址后的偏移量（如 `<+16>` 中的16），并将结果存储为数字。

### 实现方案
1. **数据结构扩展**：
   - 在DisasmLine结构体中添加`int offset`字段存储偏移量
   - 初始化为-1表示未设置偏移量

2. **状态机扩展**：
   - 新增`LINE_STATE_IN_OFFSET`状态专门处理偏移量
   - 当在`LINE_STATE_IN_FUNC`状态遇到`+`或`-`时进入此状态
   - 收集数字字符直到遇到`>`结束符

3. **偏移量解析**：
   - 实现`parse_offset`辅助函数将字符串转换为整数
   - 支持正负号前缀（`+`或`-`）
   - 解析失败时保留-1值表示无效偏移

4. **测试增强**：
   - 添加针对偏移量解析的测试用例
   - 验证各种格式的偏移量解析
   - 使用assert确保正确性

## 复杂内存引用支持

### 需求
支持解析`[x17, x16, lsl #3]`格式的复杂内存引用操作数，包含：
- 基址寄存器
- 索引寄存器
- 移位操作（lsl, lsr, asr, ror）
- 移位量

### 实现方案

1. **数据结构扩展**：
   - 在MemRef结构体中添加：
     - `index_reg[32]` 存储索引寄存器
     - `shift_op[8]` 存储移位操作符
     - `shift_amount[16]` 存储移位量

2. **状态机扩展**：
   - 新增状态：
     - `STATE_IN_MEM_INDEX`：解析索引寄存器
     - `STATE_IN_MEM_SHIFT`：解析移位操作符
     - `STATE_IN_MEM_SHIFT_AMOUNT`：解析移位量
   - 状态转移：
     - 从`STATE_IN_MEM_BASE` → `STATE_IN_MEM_INDEX`（检测到逗号后字母）
     - 从`STATE_IN_MEM_INDEX` → `STATE_IN_MEM_SHIFT`（检测到逗号）
     - 在`STATE_IN_MEM_SHIFT`中解析操作符
     - 遇到'#'时进入`STATE_IN_MEM_SHIFT_AMOUNT`解析移位量

3. **解析逻辑**：
   - 基址寄存器后遇到逗号和字母 → 进入索引寄存器解析
   - 索引寄存器后遇到逗号 → 进入移位操作解析
   - 移位操作格式：操作符（lsl等） + "#" + 数字
   - 移位量解析使用独立状态确保正确存储

4. **Python绑定更新**：
   - `Operand`类扩展支持新字段
   - 更新`__repr__`方法显示完整内存引用信息
   - 添加测试用例验证复杂内存引用

5. **测试覆盖**：
   - 添加`[x17, x16, lsl #3]`等测试用例
   - 验证所有字段正确解析
   - 确保向后兼容简单内存引用格式

## 复杂内存引用解析修复

### 问题描述
在解析复杂内存引用（如`[x17, x16, lsl #3]`）时，移位操作符("lsl")和移位量("#3")被错误地存储到了`offset`字段，而不是设计中的`shift_op`和`shift_amount`字段。

### 修复方案
1. 在状态机中增加`STATE_IN_MEM_SHIFT_AMOUNT`状态专门处理移位量
2. 确保移位操作符正确存储到`shift_op`字段
3. 确保移位量正确存储到`shift_amount`字段
4. 更新测试程序验证修复

### 修复结果
- 移位操作符和移位量现在正确存储到对应字段
- 内存引用操作数的offset字段仅用于存储基址偏移量
- 测试用例验证所有字段正确解析

## 内存安全增强

### 需求
在Debug构建中启用AddressSanitizer检测内存问题

### 实现方案
1. **CMake配置**：
   - 为Debug构建添加`-fsanitize=address`编译选项
   - 为测试目标添加ASan链接选项
   - 使用条件检查确保只在Debug构建启用

2. **构建系统**：
   ```cmake
   if(CMAKE_BUILD_TYPE STREQUAL "Debug")
       target_compile_options(op_parser_test PRIVATE -fsanitize=address)
       target_link_options(op_parser_test PRIVATE -fsanitize=address)
   endif()
   ```

3. **文档更新**：
   - README添加ASan使用说明
   - 提供Debug构建和测试示例