#include <stdio.h>

extern int printf(const char *format, ...);

int print(const char *format , ...) {
    printf(format, __VA_ARGS__);
}

#define MAX 1024

int add(int a, int b) {
    return a+b;
}

int main(int argc, char **argv) {
    printf("hello %d\n", MAX);
    print("hello: %d\n", add(1, add(1, 2)));
}
