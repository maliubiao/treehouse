#include "test_entry_point.h"
#include <stdio.h>

int main() {
  printf("=== Starting ARM64 Branch Instruction Tests ===\n");
  run_branch_tests();
  printf("=== Branch Tests Completed ===\n");
  return 0;
}
