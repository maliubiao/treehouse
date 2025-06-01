#include "basic_lib.h"
#include "so1/basic_so1.h"
#include "so2/basic_so2.h"
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

// Define strong version of weak symbol
int so1_weak_function(void) {
  printf("Main strong weak function\n");
  return 0xBEEF;
}

// Function pointer types
typedef void (*init_fn_t)(void);
typedef int (*func_fn_t)(int);

// Global variables for relocation types
volatile int *so1_global_ptr = &so1_global_var;
volatile int *so2_data_ptr = &so2_data_symbol;

// Declare assembly test functions
extern void run_branch_tests(void) __asm__("_run_branch_tests");
extern void run_cond_branch_tests(void) __asm__("_run_cond_branch_tests");

int main() {
  asm volatile("nop");
  int x = 5;
  int y = 3;
  static int loop_counter = 0;

  // Run ARM64 branch instruction tests
  printf("\n=== Running ARM64 branch instruction tests ===\n");
  run_branch_tests();
  run_cond_branch_tests();
  printf("=== Branch tests completed ===\n\n");

  // Dynamic loading test
  void *dl_handle = dlopen(NULL, RTLD_NOW);
  init_fn_t so1_dl_init = (init_fn_t)dlsym(dl_handle, "so1_init");
  func_fn_t so2_plt_fn = (func_fn_t)dlsym(dl_handle, "so2_plt_function");

  // Initialize libraries
  so1_init();
  so2_init();
  so1_dl_init(); // Call through dynamic symbol

  // Setup function pointers
  so1_func_ptr = (void (*)())so2_plt_function;

  while (1) {
    loop_counter++;
    asm volatile("nop");
    printf("\n--- Loop iteration %d ---\n", loop_counter);

    // Direct calls
    int so1_res = so1_function(10 + loop_counter);
    int so2_res = so2_function(5 + loop_counter);

    // Function pointer calls
    int fp_res = so2_plt_fn(loop_counter);

    // Access data symbols
    (*so1_global_ptr)++;
    (*so2_data_ptr) ^= loop_counter;

    // Call weak symbol
    int weak_res = so1_weak_function();

    // 准备复杂参数
    TestStruct ts = {loop_counter, loop_counter * 0.5f, loop_counter * 0.25,
                     "Main string"};

    TestStruct ts_ptr_val = {loop_counter * 2, loop_counter * 1.5f,
                             loop_counter * 0.5, "Main struct ptr"};

    NestedStruct ns = {
        .base = {loop_counter + 1, (loop_counter + 1) * 0.5f,
                 (loop_counter + 1) * 0.25, "Nested base"},
        .array = {loop_counter, loop_counter + 1, loop_counter + 2}};

    FloatStruct fs = {
        .f_arr = {3.14159f * loop_counter, 2.71828f * loop_counter},
        .d_arr = {1.61803 * loop_counter, 0.57721 * loop_counter}};

    // 调用动态库参数测试函数（交替调用）
    if (loop_counter % 2 == 0) {
      so1_test_arguments(loop_counter, loop_counter * 0.123f,
                         loop_counter * 0.456, "Main to SO1", ts, &ts_ptr_val,
                         ns, fs);
    } else {
      so2_test_arguments(loop_counter, loop_counter * 0.789f,
                         loop_counter * 1.234, "Main to SO2", ts, &ts_ptr_val,
                         ns, fs);
    }

    printf("Results: SO1=%-4d SO2=%-4d PLT=%-4d WEAK=0x%X\n", so1_res, so2_res,
           fp_res, weak_res);
    printf("Symbols: SO1_GLOBAL=%-6d SO2_DATA=0x%X\n", *so1_global_ptr,
           *so2_data_ptr);

    printf("Sleeping for 1 second...\n");
    sleep(1);
  }

  dlclose(dl_handle);
  return 0;
}