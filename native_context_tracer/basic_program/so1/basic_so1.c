#include "basic_so1.h"
#include "so2/basic_so2.h"
#include <stdio.h>

volatile int so1_global_var = 100;
void (*so1_func_ptr)(void) = NULL;

// Weak symbol definition
int __attribute__((weak)) so1_weak_function(void) {
  printf("SO1 weak function default\n");
  return 0xDEAD;
}

// ARM64复杂参数传递测试函数
__attribute__((used)) void
so1_test_arguments(int counter, float f1, double d1, const char *str,
                   TestStruct struct_val, TestStruct *struct_ptr,
                   NestedStruct nested, FloatStruct floats) {

  printf("SO1 received complex arguments:\n");
  printf("  counter: %d, float: %.8f, double: %.15f\n", counter, f1, d1);
  printf("  str: %s\n", str);
  printf("  struct_val: {a=%d, b=%.2f, c=%.4f, str=%s}\n", struct_val.a,
         struct_val.b, struct_val.c, struct_val.str);
  printf("  nested.array[0]: %d\n", nested.array[0]);
  printf("  floats.f_arr[1]: %.8f\n", floats.f_arr[1]);
}

int so1_function(int x) {
  printf("SO1 processing: %d\n", x);
  asm volatile("nop"); // SO1 marker

  // 调用参数测试
  TestStruct ts = {x, x * 0.5f, x * 0.25, "SO1 struct"};
  TestStruct ts_ptr_val = {x * 2, x * 1.5f, x * 0.5, "SO1 struct ptr"};
  NestedStruct ns = {
      .base = {x + 1, (x + 1) * 0.5f, (x + 1) * 0.25, "Nested base"},
      .array = {x, x + 1, x + 2}};
  FloatStruct fs = {.f_arr = {1.234f * x, 5.678f * x},
                    .d_arr = {9.012 * x, 3.456 * x}};

  so1_test_arguments(x, x * 0.123f, x * 0.456, "SO1 test string", ts,
                     &ts_ptr_val, ns, fs);

  int result = so2_function(x * 2);
  printf("SO1 got result from SO2: %d\n", result);

  // Access global variable
  so1_global_var += x;
  printf("SO1 global var: %d\n", so1_global_var);

  // Call function pointer if set
  if (so1_func_ptr) {
    so1_func_ptr();
  }

  return result + 1;
}

void so1_init(void) {
  asm volatile("nop"); // SO1 init marker
  printf("SO1 initialized\n");

  // Prevent optimization
  asm volatile("" : : "r"(so1_weak_function));
}
