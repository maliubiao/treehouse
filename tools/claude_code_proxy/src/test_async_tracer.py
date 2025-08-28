#!/usr/bin/env python3
"""
Test script to verify async tracer functionality.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tracer_mcp_server import TracerMCPServer


async def test_async_tracer():
    """Test that the async tracer can handle concurrent requests."""
    server = TracerMCPServer()

    # Test data for multiple concurrent trace requests
    test_requests = [
        {
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "trace_python",
                "arguments": {
                    "target": str(Path(__file__).parent / "test_script.py"),
                    "target_type": "script",
                    "timeout": 5,
                },
            },
        },
        {
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "trace_python",
                "arguments": {
                    "target": str(Path(__file__).parent / "test_script2.py"),
                    "target_type": "script",
                    "timeout": 3,
                },
            },
        },
    ]

    print("Testing async tracer with concurrent requests...")

    # Test handling multiple requests concurrently
    start_time = time.time()

    # Create tasks for concurrent request processing
    tasks = []
    for i, request in enumerate(test_requests):
        # Create a deep copy of the request to avoid any shared state
        request_copy = json.loads(json.dumps(request))
        # Ensure each request has unique parameters by modifying the target
        if i == 1:  # Second request
            request_copy["params"]["arguments"]["target"] = str(Path(__file__).parent / "test_script2.py")
        task = asyncio.create_task(server._handle_single_request(request_copy))
        tasks.append(task)

    # Wait for all tasks to complete
    await asyncio.gather(*tasks)

    end_time = time.time()
    total_time = end_time - start_time

    print(f"Completed {len(test_requests)} requests in {total_time:.2f} seconds")
    print("Async tracer test completed successfully!")


if __name__ == "__main__":
    # Create simple test scripts
    test_script_content = """
print("Hello from test script!")
for i in range(3):
    print(f"Counting: {i}")
"""

    test_script2_content = """
print("Hello from test script 2!")
import time
time.sleep(1)  # Short delay
print("Done with script 2")
"""

    # Write test scripts
    with open(Path(__file__).parent / "test_script.py", "w") as f:
        f.write(test_script_content)

    with open(Path(__file__).parent / "test_script2.py", "w") as f:
        f.write(test_script2_content)

    # Run the test
    asyncio.run(test_async_tracer())
