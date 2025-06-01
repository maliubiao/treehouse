#!/bin/bash

# 测试LLDB测试框架

# 准备测试环境
mkdir -p test_programs test_scripts

# 编译测试程序
cat >test_programs/example.c <<'EOF'
#include <stdio.h>

void test_function() {
    printf("This is a test function\n");
}

int main() {
    test_function();
    return 0;
}
EOF

gcc -g test_programs/example.c -o test_programs/example

# 创建测试脚本
cat >test_scripts/test_example.py <<'EOF'
def run_test(lldb_instance):
    # 设置断点
    lldb_instance.HandleCommand("breakpoint set --name test_function")
    lldb_instance.HandleCommand("continue")
    
    # 验证断点
    frame = lldb_instance.GetSelectedTarget().GetProcess().GetSelectedThread().GetSelectedFrame()
    if frame.GetFunctionName() != "test_function":
        raise AssertionError("Failed to stop at test_function")
EOF

# 创建配置文件
cat >config.json <<'EOF'
{
    "test_program": "test_programs/example"
}
EOF

# 运行测试
echo "Running all tests..."
python3 lldb_tester.py -c config.json

echo "Running single test..."
python3 lldb_tester.py -c config.json -t test_scripts/test_example.py

echo "Listing tests..."
python3 lldb_tester.py -c config.json --list-tests

# 清理
rm -rf test_programs test_scripts config.json
