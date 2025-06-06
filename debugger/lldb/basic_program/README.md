# basic_program 项目说明

## 增强功能：复杂参数传递调试

### 使用示例
```bash
# 编译项目
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Debug
make

# 启动调试
lldb ./basic_program
(lldb) b so1_test_arguments
(lldb) b so2_test_arguments
(lldb) b test_argument_passing
(lldb) run
```

### 调试参数传递
```lldb
# 查看整型参数
frame variable counter

# 查看浮点参数
frame variable f1
frame variable d1

# 查看字符串
frame variable str

# 查看结构体
frame variable struct_val
frame variable *struct_ptr

# 查看嵌套结构体
frame variable nested

# 查看浮点数组结构体
frame variable floats

# 查看浮点寄存器
register read -f float s0 d0 s1 d1

# 查看通用寄存器
register read x0 x1 x2 x3
```

### 测试脚本
```bash
./test_argument_passing.sh
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
```