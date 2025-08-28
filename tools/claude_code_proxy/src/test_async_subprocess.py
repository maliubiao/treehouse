#!/usr/bin/env python3
"""
Test script to verify async subprocess functionality.
"""

import asyncio
import os

# Add parent directory to path
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tracer_mcp_server import TracerMCPServer


async def test_async_subprocess():
    """Test that async subprocess execution works correctly."""
    server = TracerMCPServer()

    # Create a simple Python script to test
    test_script = """
import time
print("Starting test script")
for i in range(3):
    print(f"Iteration {i}")
    time.sleep(0.1)
print("Test script completed")
"""

    # Write test script to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_script)
        script_path = f.name

    try:
        # Build command args
        command_args = [sys.executable, script_path]

        # Test async execution
        print("Testing async subprocess execution...")

        start_time = asyncio.get_event_loop().time()

        exit_code, stdout, stderr, killed = await server._execute_tracer_process_async(
            command_args, tempfile.gettempdir(), timeout=10
        )

        end_time = asyncio.get_event_loop().time()
        execution_time = end_time - start_time

        print(f"Execution completed in {execution_time:.2f} seconds")
        print(f"Exit code: {exit_code}")
        print(f"Killed: {killed}")
        print("STDOUT:")
        print(stdout)

        if stderr:
            print("STDERR:")
            print(stderr)

        # Verify the results
        assert exit_code == 0, f"Expected exit code 0, got {exit_code}"
        assert not killed, "Process should not have been killed"
        assert "Test script completed" in stdout, "Script completion message not found"

        print("Async subprocess test passed!")

    finally:
        # Clean up
        try:
            os.unlink(script_path)
        except:
            pass


async def test_concurrent_subprocesses():
    """Test that multiple subprocesses can run concurrently."""
    server = TracerMCPServer()

    # Create multiple test scripts
    scripts = []
    for i in range(3):
        script_content = f"""
import time
print("Script {i} starting")
time.sleep(1)  # All scripts sleep for 1 second
print("Script {i} completed")
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=f"_{i}.py", delete=False) as f:
            f.write(script_content)
            scripts.append(f.name)

    try:
        print("Testing concurrent subprocess execution...")

        # Create tasks for concurrent execution
        tasks = []
        for i, script_path in enumerate(scripts):
            command_args = [sys.executable, script_path]
            task = server._execute_tracer_process_async(command_args, tempfile.gettempdir(), timeout=5)
            tasks.append(task)

        start_time = asyncio.get_event_loop().time()

        # Run all tasks concurrently
        results = await asyncio.gather(*tasks)

        end_time = asyncio.get_event_loop().time()
        total_time = end_time - start_time

        print(f"Completed {len(scripts)} concurrent processes in {total_time:.2f} seconds")

        # Verify all completed successfully
        for i, (exit_code, stdout, stderr, killed) in enumerate(results):
            assert exit_code == 0, f"Script {i} failed with exit code {exit_code}"
            assert not killed, f"Script {i} was killed"
            assert f"Script {i} completed" in stdout, f"Script {i} completion message not found"

        print("Concurrent subprocess test passed!")

    finally:
        # Clean up
        for script_path in scripts:
            try:
                os.unlink(script_path)
            except:
                pass


if __name__ == "__main__":
    print("Running async subprocess tests...")

    # Run individual test
    asyncio.run(test_async_subprocess())
    print()

    # Run concurrent test
    asyncio.run(test_concurrent_subprocesses())

    print("\nAll tests passed! Async subprocess functionality is working correctly.")
