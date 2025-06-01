#ifndef BASIC_LIB_H
#define BASIC_LIB_H

#include <stddef.h>
#include <time.h>

// 参数测试结构体
typedef struct {
  int a;
  float b;
  double c;
  const char *str;
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

int add(int a, int b);
int subtract(int a, int b);
void syscall_example();
void loop_example();
void switch_example(int val);
void recursion_example(int n);
void test_argument_passing(int counter, float f1, double d1, const char *str,
                           TestStruct struct_val, TestStruct *struct_ptr,
                           NestedStruct nested, FloatStruct floats);

#endif