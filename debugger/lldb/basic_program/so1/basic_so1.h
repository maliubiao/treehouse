#ifndef BASIC_SO1_H
#define BASIC_SO1_H

int so1_function(int x) __attribute__((visibility("default")));
void so1_init(void) __attribute__((visibility("default")));

// Export different symbol types
extern volatile int so1_global_var __attribute__((visibility("default")));
int __attribute__((weak)) so1_weak_function(void);
void (*so1_func_ptr)(void);

#endif