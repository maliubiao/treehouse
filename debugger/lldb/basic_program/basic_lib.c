#include "basic_lib.h"
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

int add(int a, int b) {
  asm volatile("nop");
  return a + b;
}

int subtract(int a, int b) {
  asm volatile("nop");
  if (a > b) {
    asm volatile("nop");
    return a - b;
  } else {
    asm volatile("nop");
    return b - a;
  }
}

void syscall_example() {
  asm volatile("nop");
  write(1, "Syscall example\n", 16);
}

void loop_example() {
  asm volatile("nop");
  for (int i = 0; i < 5; i++) {
    asm volatile("nop");
    printf("Loop iteration: %d\n", i);
  }
}

void switch_example(int val) {
  asm volatile("nop");
  switch (val) {
  case 1:
    asm volatile("nop");
    printf("Case 1\n");
    break;
  case 2:
    asm volatile("nop");
    printf("Case 2\n");
    break;
  default:
    asm volatile("nop");
    printf("Default case\n");
  }
}

void recursion_example(int n) {
  asm volatile("nop");
  if (n <= 0) {
    asm volatile("nop");
    return;
  }
  printf("Recursion depth: %d\n", n);
  recursion_example(n - 1);
}

// 增强版参数传递测试函数
__attribute__((used)) void
test_argument_passing(int counter, float f1, double d1, const char *str,
                      TestStruct struct_val, TestStruct *struct_ptr,
                      NestedStruct nested, FloatStruct floats) {
  // 打印参数信息
  printf("Argument passing test (counter=%d):\n", counter);
  printf("  float: %.8f, double: %.15f\n", f1, d1);
  printf("  str: %s\n", str);

  printf("  struct_val: {a=%d, b=%.2f, c=%.4f, str=%s}\n", struct_val.a,
         struct_val.b, struct_val.c, struct_val.str);

  printf("  struct_ptr: {a=%d, b=%.2f, c=%.4f, str=%s}\n", struct_ptr->a,
         struct_ptr->b, struct_ptr->c, struct_ptr->str);

  printf("  nested: {\n");
  printf("    base: {a=%d, b=%.2f, c=%.4f, str=%s},\n", nested.base.a,
         nested.base.b, nested.base.c, nested.base.str);
  printf("    array: [%d, %d, %d]\n", nested.array[0], nested.array[1],
         nested.array[2]);
  printf("  }\n");

  printf("  floats: {\n");
  printf("    f_arr: [%.8f, %.8f],\n", floats.f_arr[0], floats.f_arr[1]);
  printf("    d_arr: [%.15f, %.15f]\n", floats.d_arr[0], floats.d_arr[1]);
  printf("  }\n");
}
