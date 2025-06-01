#ifndef BASIC_SO2_H
#define BASIC_SO2_H

#include "basic_lib.h"

int so2_function(int y);
void so2_init();
void so2_test_arguments(int counter, float f1, double d1, const char *str,
                        TestStruct struct_val, TestStruct *struct_ptr,
                        NestedStruct nested, FloatStruct floats)
    __attribute__((visibility("default")));

// Export data symbol
extern volatile int so2_data_symbol;
int so2_plt_function(int) __attribute__((visibility("default")));

#endif