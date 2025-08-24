#include "basic_lib.h"
#include "so1/basic_so1.h"
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main() {
  asm volatile("nop");
  int x = 5;
  int y = 3;

  // Initialize SO1
  so1_init();

  // Call SO1 function
  int so_result = so1_function(10);
  printf("Main got result from SO1: %d\n", so_result);

  int sum = add(x, y);
  int diff = subtract(x, y);
  printf("Result: %d\n", sum);
  printf("Difference: %d\n", diff);

  syscall_example();
  loop_example();
  switch_example(2);
  switch_example(3);
  recursion_example(3);

  while (1) {
    asm volatile("nop");
    printf("Sleeping for 1 second...\n");
    sleep(1);
  }
  return 0;
}