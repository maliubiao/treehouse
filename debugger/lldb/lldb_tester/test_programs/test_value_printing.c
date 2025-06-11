#include <stdio.h>

typedef struct {
  int x;
  float y;
  char z;
} SimpleStruct;

typedef struct Node {
  int value;
  struct Node *next;
} Node;

typedef union {
  int int_val;
  float float_val;
  char char_val;
} SampleUnion;

int main() {
  // 基本类型
  int a = 42;
  float b = 3.14f;
  char c = 'A';

  // 指针
  int *ptr = &a;

  // 结构体
  SimpleStruct s = {10, 2.5f, 'X'};

  // 链表（带循环引用）
  Node node1 = {100, NULL};
  Node node2 = {200, NULL};
  node1.next = &node2;
  node2.next = &node1; // 循环引用

  // 联合体
  SampleUnion u;
  u.float_val = 1.23f;

  // 字符数组
  char str[] = "Hello, World!";

  // 指针数组
  int *ptr_arr[3] = {&a, &a, &a};

  // 打印所有变量以避免未使用警告
  printf("Basic types:\n");
  printf("a = %d\n", a);
  printf("b = %f\n", b);
  printf("c = %c\n", c);

  printf("\nPointers:\n");
  printf("ptr = %p\n", (void *)ptr);

  printf("\nStructures:\n");
  printf("s.x = %d, s.y = %f, s.z = %c\n", s.x, s.y, s.z);

  printf("\nLinked list nodes:\n");
  printf("node1.value = %d, node1.next = %p\n", node1.value,
         (void *)node1.next);
  printf("node2.value = %d, node2.next = %p\n", node2.value,
         (void *)node2.next);

  printf("\nUnion:\n");
  printf("u.float_val = %f\n", u.float_val);

  printf("\nString:\n");
  printf("str = %s\n", str);

  printf("\nPointer array:\n");
  for (int i = 0; i < 3; i++) {
    printf("ptr_arr[%d] = %p, *ptr_arr[%d] = %d\n", i, (void *)ptr_arr[i], i,
           *ptr_arr[i]);
  }

  printf("\nAll variables initialized and printed\n");
  return 0;
}