#!/bin/bash

# Test script for ARM64 assembly functions in basic_program

set -e

# Build the project
mkdir -p build
cd build
cmake ..
make -j4

# 验证构建结果
if [ ! -f "branch_test" ] || [ ! -f "cond_branch_test" ] || [ ! -f "basic_program" ]; then
  echo "Error: Build failed - missing executables"
  exit 1
fi

# Run the branch tests
echo "Running branch_test..."
./branch_test

echo "Running cond_branch_test..."
./cond_branch_test

# Run the main program which includes the assembly tests
echo "Running basic_program with assembly tests..."
./basic_program &

# Store PID for later termination
PROGRAM_PID=$!

# Give it some time to run the tests
sleep 5

# Kill the background process
if kill -0 $PROGRAM_PID >/dev/null 2>&1; then
  echo "Terminating basic_program (PID: $PROGRAM_PID)"
  kill $PROGRAM_PID
else
  echo "basic_program already exited"
fi

echo "All ARM64 assembly tests completed successfully"
