#include "basic_lib.h"
#include "so1/basic_so1.h"
#include "so2/basic_so2.h"
#include "so3/basic_so3.h"
#include "so4/basic_so4.h" // 添加so4头文件
#include <dlfcn.h>
#include <pthread.h>
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
extern int so2_plt_function(int x);
// 线程参数结构
typedef struct {
  int thread_id;
  const char *marker;
  uint32_t asm_marker;
} ThreadArgs;

// SO4复杂返回值处理函数
void process_complex_returns(int seed) {
  // 调用所有SO4的复杂返回值函数
  ComplexReturn cr = so4_return_struct(seed);
  printf("ComplexReturn: int=%d, float=%.2f, double=%.4f, str=%s\n", cr.int_val,
         cr.float_val, cr.double_val, cr.str_val);

  float f = so4_return_float(seed);
  printf("Float return: %.4f\n", f);

  double d = so4_return_double(seed);
  printf("Double return: %.6f\n", d);

  const char *str = so4_return_string(seed);
  printf("String return: %s\n", str);

  NestedReturn nr = so4_return_nested(seed);
  printf("NestedReturn: base={int=%d, float=%.2f}, array=[%d, %d, %d]\n",
         nr.base.int_val, nr.base.float_val, nr.array[0], nr.array[1],
         nr.array[2]);

  FloatArrayReturn far = so4_return_float_array(seed);
  printf("FloatArray: f_arr=[%.4f, %.4f], d_arr=[%.6f, %.6f]\n", far.f_arr[0],
         far.f_arr[1], far.d_arr[0], far.d_arr[1]);
}

int loop_100() {
  // 循环100次，打印当前循环次数
  for (int i = 0; i < 100; i++) {
    printf("Loop iteration: %d\n", i);
  }
  return 1;
}

// 工作线程1：主逻辑线程
void *work_thread_main(void *arg) {
  ThreadArgs *args = (ThreadArgs *)arg;
  printf("Thread %d (%s) started\n", args->thread_id, args->marker);

  int x = 5;
  int y = 3;
  static int loop_counter = 0;
  // loop_100();
  while (1) {
    loop_counter++;
    // 线程专用标记

    printf("\n--- [Thread %d] Loop iteration %d ---\n", args->thread_id,
           loop_counter);

    // Direct calls
    int so1_res = so1_function(10 + loop_counter);
    int so2_res = so2_function(5 + loop_counter);

    // Function pointer calls (修复函数指针调用语法)
    int fp_res = so2_function(loop_counter);

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

    // 每5次循环处理一次复杂返回值
    if (loop_counter % 5 == 0) {
      printf("\n[Thread %d] Processing complex returns:\n", args->thread_id);
      process_complex_returns(loop_counter);
    }

    printf("Results: SO1=%-4d SO2=%-4d PLT=%-4d WEAK=0x%X\n", so1_res, so2_res,
           fp_res, weak_res);
    printf("Symbols: SO1_GLOBAL=%-6d SO2_DATA=0x%X\n", *so1_global_ptr,
           *so2_data_ptr);

    printf("[Thread %d] Sleeping for 1 second...\n", args->thread_id);

    process_complex_returns(0);
    sleep(1);
  }
  return NULL;
}

// 工作线程2：简单计数线程
void *work_thread_counter(void *arg) {
  ThreadArgs *args = (ThreadArgs *)arg;
  printf("Thread %d (%s) started\n", args->thread_id, args->marker);

  int counter = 0;
  while (1) {
    printf("[Thread %d] Counter: %d\n", args->thread_id, counter++);
    sleep(2);
  }
  return NULL;
}

// 工作线程3：数学计算线程
void *work_thread_math(void *arg) {
  ThreadArgs *args = (ThreadArgs *)arg;
  printf("Thread %d (%s) started\n", args->thread_id, args->marker);

  double pi = 3.1415926535;
  int iteration = 0;

  while (1) {
    double result = pi * iteration * iteration;
    printf("[work_thread_math Thread %d] Math: π * %d^2 = %.2f\n",
           args->thread_id, iteration, result);
    iteration = (iteration + 1) % 10;
    sleep(1);
  }
  return NULL;
}

// SO4复杂返回值专用线程
void *work_thread_so4(void *arg) {
  ThreadArgs *args = (ThreadArgs *)arg;
  printf("Thread %d (%s) started - SO4 complex returns\n", args->thread_id,
         args->marker);

  int seed = 0;
  while (1) {
    seed++;
    printf("\n--- [Thread %d SO4] Processing complex returns (seed=%d) ---\n",
           args->thread_id, seed);
    process_complex_returns(seed);
    sleep(3);
  }
  return NULL;
}

int main() {
  asm volatile("nop");
  loop_100();
  // 运行动态库初始化
  so1_init();
  so2_init();
  so3_init(); // 初始化SO3文件IO库
  so4_init(); // 初始化SO4复杂返回值库

  // 运行动态加载测试
  void *dl_handle = dlopen(NULL, RTLD_NOW);
  init_fn_t so1_dl_init = (init_fn_t)dlsym(dl_handle, "so1_init");
  func_fn_t so2_plt_fn = (func_fn_t)dlsym(dl_handle, "so2_plt_function");

  // 初始化函数指针
  so1_func_ptr = (void (*)())so2_plt_function;
  so1_dl_init(); // 通过动态符号调用

  // 运行ARM64分支指令测试
  printf("\n=== Running ARM64 branch instruction tests ===\n");
  run_branch_tests();
  run_cond_branch_tests();
  printf("=== Branch tests completed ===\n\n");

  so3_file_operations();
  so3_test_file_io();

  // 创建线程参数
  ThreadArgs thread1_args = {1, "MAIN_LOGIC", 0xAA};
  ThreadArgs thread2_args = {2, "COUNTER", 0xBB};
  ThreadArgs thread3_args = {3, "MATH", 0xCC};
  ThreadArgs thread4_args = {4, "SO4_RETURNS", 0xDD}; // SO4专用线程

  // 创建线程
  pthread_t thread1, thread2, thread3, thread4;

  pthread_create(&thread1, NULL, work_thread_main, &thread1_args);
  pthread_create(&thread2, NULL, work_thread_counter, &thread2_args);
  pthread_create(&thread3, NULL, work_thread_math, &thread3_args);
  pthread_create(&thread4, NULL, work_thread_so4, &thread4_args);
  work_thread_main(&thread1_args);

  printf("Main thread: Created 4 worker threads\n");

  // 主线程等待工作线程结束（实际上不会结束）
  // pthread_join(thread1, NULL);
  // pthread_join(thread2, NULL);
  // pthread_join(thread3, NULL);
  // pthread_join(thread4, NULL);

  dlclose(dl_handle);
  return 0;
}