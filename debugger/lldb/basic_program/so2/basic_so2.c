#include "basic_so2.h"
#include "basic_lib.h"
#include <stdio.h>

volatile int so2_data_symbol = 0xABCD;

// ARM64复杂参数传递测试函数
__attribute__((used)) void
so2_test_arguments(int counter, float f1, double d1, const char *str,
                   TestStruct struct_val, TestStruct *struct_ptr,
                   NestedStruct nested, FloatStruct floats) {
  printf("SO2 received complex arguments:\n");
  printf("  counter: %d, float: %.8f, double: %.15f\n", counter, f1, d1);
  printf("  str: %s\n", str);
  printf("  struct_ptr: {a=%d, b=%.2f, c=%.4f}\n", struct_ptr->a, struct_ptr->b,
         struct_ptr->c);
  printf("  nested.base.str: %s\n", nested.base.str);
  printf("  floats.d_arr[0]: %.15f\n", floats.d_arr[0]);
}

int so2_plt_function(int x) {
  printf("SO2 PLT function called: %d\n", x);
  return x * 3;
}

int so2_function(int y) {
  printf("SO2 processing: %d\n", y);
  asm volatile("nop"); // SO2 marker

  // 调用参数测试
  TestStruct ts = {y, y * 0.75f, y * 0.125, "SO2 struct"};
  TestStruct ts_ptr_val = {y * 3, y * 2.5f, y * 0.75, "SO2 struct ptr"};
  NestedStruct ns = {
      .base = {y - 1, (y - 1) * 0.75f, (y - 1) * 0.125, "Nested base SO2"},
      .array = {y, y - 1, y - 2}};
  FloatStruct fs = {.f_arr = {0.123f * y, 0.456f * y},
                    .d_arr = {0.789 * y, 1.234 * y}};

  so2_test_arguments(y, y * 0.789f, y * 1.234, "SO2 test string", ts,
                     &ts_ptr_val, ns, fs);

  int result = add(y, 10);
  printf("SO2 got result from main: %d\n", result);

  // Access data symbol
  so2_data_symbol ^= result;
  printf("SO2 data symbol: 0x%X\n", so2_data_symbol);

  return result * 2;
}

void so2_init() {
  asm volatile("nop"); // SO2 init marker
  printf("SO2 initialized\n");

  // Force PLT entry usage with volatile pointer
  int (*volatile plt_ptr)(int) = so2_plt_function;
  plt_ptr(0x123);

  // Prevent optimization of data symbols
  asm volatile("" : : "r"(so2_data_symbol));
}
