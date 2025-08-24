# basic_program 项目说明

## 增强功能：复杂参数传递调试

### 使用示例
```bash
# 编译项目
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Debug
make
cd ..

# 启动LLDB测试
lldb --batch -o "b so1_test_arguments" \
          -o "b so2_test_arguments" \
          -o "b test_argument_passing" \
          -o "run" \
          -o "frame variable" \
          -o "register read -f float" \
          -o "continue" \
          -o "exit" \
          ./build/basic_program

echo "复杂参数传递测试完成"
```

## SO4复杂返回值调试

### 调试示例
```lldb
# 设置复杂返回值断点
b so4_return_struct
b so4_return_nested
b so4_return_float_array

# 查看返回值
# 结构体返回值存储在x0寄存器指向的内存
frame variable *((ComplexReturn *)x0)
frame variable *((NestedReturn *)x0)
frame variable *((FloatArrayReturn *)x0)

# 浮点返回值存储在s0寄存器
register read -f float s0

# 双精度返回值存储在d0寄存器
register read -f float d0

# 字符串返回值存储在x0寄存器
memory read -s1 -c32 -f A x0
```

## 文件IO调试功能

### 调试文件操作
```bash
lldb ./basic_program
(lldb) b write
(lldb) b read
(lldb) b fwrite
(lldb) b fread
(lldb) run
```

### 调试技巧
```lldb
# 查看文件描述符
frame variable fd

# 查看读写缓冲区
memory read --size 1 --format c --count 32 buffer

# 查看文件位置
p (long)lseek(fd, 0, SEEK_CUR)

# 查看FILE结构体
frame variable *fp
```

## 新增的复杂参数类型
```c
// 基础结构体
typedef struct {
    int a;
    float b;
    double c;
    const char* str;
} TestStruct;

// 嵌套结构体
typedef struct {
    TestStruct base;
    int array[3];
} NestedStruct;

// 浮点数组结构体
typedef struct {
    float f_arr[2];
    double d_arr[2];
} FloatStruct;

// SO4复杂返回值类型
typedef struct {
    int int_val;
    float float_val;
    double double_val;
    const char *str_val;
} ComplexReturn;

typedef struct {
    ComplexReturn base;
    int array[3];
} NestedReturn;

typedef struct {
    float f_arr[2];
    double d_arr[2];
} FloatArrayReturn;
```