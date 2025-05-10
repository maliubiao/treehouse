#include <stdio.h>
#include "basic_lib.h"
#include "basic_so2.h"

volatile int so2_data_symbol = 0xABCD;

int so2_plt_function(int x) {
    printf("SO2 PLT function called: %d\n", x);
    return x * 3;
}

int so2_function(int y) {
    printf("SO2 processing: %d\n", y);
    asm volatile("nop"); // SO2 marker
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
    int (* volatile plt_ptr)(int) = so2_plt_function;
    plt_ptr(0x123);
    
    // Prevent optimization of data symbols
    asm volatile("" : : "r"(so2_data_symbol));
}