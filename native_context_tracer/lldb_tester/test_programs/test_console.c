#include <stdio.h>

void my_test_function_for_console() {
  printf("This is a test function for the console.\n");
}

int main() {
  int my_local_variable = 42;
  printf("Console test program started. my_local_variable = %d\n",
         my_local_variable);
  my_test_function_for_console();
  printf("Console test program finished.\n");
  return 0;
}