#include <stdio.h>
#include "basic_so1.h"
#include "so2/basic_so2.h"

volatile int so1_global_var = 100;
void (*so1_func_ptr)(void) = NULL;

// Weak symbol definition
int __attribute__((weak)) so1_weak_function(void) {
    printf("SO1 weak function default\n");
    return 0xDEAD;
}

int so1_function(int x) {
    printf("SO1 processing: %d\n", x);
    asm volatile("nop"); // SO1 marker
    int result = so2_function(x * 2);
    printf("SO1 got result from SO2: %d\n", result);
    
    // Access global variable
    so1_global_var += x;
    printf("SO1 global var: %d\n", so1_global_var);
    
    // Call function pointer if set
    if(so1_func_ptr) {
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