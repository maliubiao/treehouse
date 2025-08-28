#!/usr/bin/env python3
"""
Simple test to verify async functionality without concurrent requests.
"""

import asyncio
import os

# Add parent directory to path
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tracer_mcp_server import TracerMCPServer


async def test_single_trace():
    """Test a single trace request."""
    server = TracerMCPServer()

    # Test data for a single trace request
    test_request = {
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
    }

    print("Testing single trace request...")

    result = await server._handle_single_request(test_request)
    print("Single trace test completed!")
    print(f"Result: {result}")


async def test_sequential_traces():
    """Test two trace requests sequentially."""
    server = TracerMCPServer()

    # First request
    request1 = {
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "trace_python",
            "arguments": {
                "target": str(Path(__file__).parent / "test_script.py"),
                "target_type": "script",
                "timeout": 3,
            },
        },
    }

    # Second request
    request2 = {
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
    }

    print("Testing sequential trace requests...")

    # Run requests sequentially
    result1 = await server._handle_single_request(request1)
    print("First request completed")

    result2 = await server._handle_single_request(request2)
    print("Second request completed")

    print("Sequential traces test completed!")


if __name__ == "__main__":
    print("Running simple async tests...")

    # Run single test
    asyncio.run(test_single_trace())
    print()

    # Run sequential test
    asyncio.run(test_sequential_traces())

    print("\nAll simple tests completed!")
