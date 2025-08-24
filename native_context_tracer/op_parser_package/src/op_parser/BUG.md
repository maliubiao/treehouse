# 已知问题记录

## 复杂内存引用解析字段错误

### 问题描述
在解析复杂内存引用（如`[x17, x16, lsl #3]`）时，移位操作符("lsl")和移位量("#3")被错误地存储到了`offset`字段，而不是设计中的`shift_op`和`shift_amount`字段。

### 影响
- 测试输出显示不正确，移位信息被归入offset字段
- 使用解析结果的代码无法正确获取移位信息

### 修复方案
1. 在状态机中增加`STATE_IN_MEM_SHIFT_AMOUNT`状态，专门处理移位量
2. 确保移位操作符正确存储到`shift_op`字段
3. 确保移位量正确存储到`shift_amount`字段
4. 更新测试程序验证修复

### 修复提交
修复在提交 [commit hash] 中实现

## 内存安全增强

### 增强描述
为测试程序添加AddressSanitizer支持以检测内存问题

### 实现方案
1. 在CMake中为Debug构建添加ASan编译选项
2. 为测试目标链接ASan运行时库
3. 更新构建文档说明ASan使用方法

### 测试验证
1. 使用Debug构建测试程序：
   ```bash
   cmake -DCMAKE_BUILD_TYPE=Debug ..
   make
   ```
2. 运行测试程序验证内存安全
3. 检查ASan输出报告内存问题