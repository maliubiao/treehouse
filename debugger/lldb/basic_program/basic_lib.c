#include <stdio.h>
#include <unistd.h>
#include "basic_lib.h"

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
    switch(val) {
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
    recursion_example(n-1);
}