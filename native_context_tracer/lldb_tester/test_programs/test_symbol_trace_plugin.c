#include <stdio.h>

// 带参数的函数
int parameterized_function(int a, int b) { return a + b; }

// 递归函数
int recursive_function(int n) {
  if (n <= 0)
    return 0;
  return n + recursive_function(n - 1);
}

// 测试函数1
void test_function_1() { printf("Inside test_function_1\n"); }

// 测试函数2
void test_function_2() { printf("Inside test_function_2\n"); }

// 嵌套调用测试
void nested_function() {
  test_function_1();
  test_function_2();
}

// 返回值的函数
int function_with_return() { return 42; }

int main() {
  printf("Starting symbol trace test program\n");

  // 调用测试函数
  test_function_1();
  test_function_2();
  nested_function();

  // 测试带参数函数
  int sum = parameterized_function(5, 7);
  printf("Parameterized function result: %d\n", sum);

  // 测试递归函数
  int recursive_sum = recursive_function(3);
  printf("Recursive function result: %d\n", recursive_sum);

  // 测试返回值函数
  int ret_value = function_with_return();
  printf("Function with return: %d\n", ret_value);

  printf("Program completed\n");
  return 0;
}