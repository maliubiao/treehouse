#include "test_entry_point.h"
#include <stdio.h>

int main() {
  printf("=== Starting ARM64 Conditional Branch Tests ===\n");
  run_cond_branch_tests();
  printf("=== Conditional Branch Tests Completed ===\n");
  return 0;
}
