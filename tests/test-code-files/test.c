#include <stdarg.h>
#include <stdio.h>

extern int printf(const char *format, ...);

int c = 0;

/* 测试不同函数样式 */
int print(const char *format , ...) {
    return 1; 
}

struct file* print1(const char *format , ...) {
    return NULL;
}

#define MAX 1024

/* 静态函数 */
static int multiply(int a, int b) {
    return a * b;
}

/* 递归函数 */
int recursive_factorial(int n) {
    return n <= 1 ? 1 : n * recursive_factorial(n-1);
}

/* 函数指针参数 */
void register_callback(int (*cb)(int)) {
    cb(42);
}

/* 复杂参数列表 */
int variadic_sum(int count, ...) {
    va_list args;
    va_start(args, count);
    int sum = 0;
    for(int i=0; i<count; i++) {
        sum += va_arg(args, int);
    }
    va_end(args);
    return sum;
}

/* 内联函数 */
inline int increment(int x) {
    return x + 1;
}

/* 返回函数指针 */
int (*get_adder(int delta))(int) {
    static int impl(int x) { return x + delta; }
    return impl;
}

/* void返回类型 */
void noop(void) {
    /* 空函数体 */
}

/* 匿名结构参数 */
void handle_anonymous(struct { int id; char *name; } obj) {
    printf("ID: %d\n", obj.id);
}

/* 联合体参数 */
union Value { int i; float f; };
void print_value(union Value v) {
    printf("Value: %d\n", v.i);
}

/* const返回类型 */
const char* get_greeting() {
    return "Hello";
}

/* 复杂指针类型 */
int** allocate_matrix(int rows, int cols) {
    int **matrix = malloc(rows * sizeof(int*));
    for(int i=0; i<rows; i++) {
        matrix[i] = calloc(cols, sizeof(int));
    }
    return matrix;
}

/* 外部函数声明 */
extern void external_api(void);

int add(int a, int b) {
    return a+b;
}

int main(int argc, char **argv) {
    printf("hello %d\n", MAX);
    print("hello: %d\n", add(1, add(1, 2)));
    
    // 调用新函数测试
    multiply(3, 4);
    recursive_factorial(5);
    register_callback(increment);
    variadic_sum(3, 1,2,3);
    get_adder(5)(10);
    noop();
    print_value((union Value){.i=100});
    int **m = allocate_matrix(3,3);
    external_api();
}
