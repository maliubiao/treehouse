#!/usr/bin/env python3
"""
Test script to verify MCP server functionality with the tracer.
This script creates a simple MCP server instance and tests its tools.
"""

import json
import sys
from pathlib import Path

# Add parent directory for imports (avoiding relative imports as per CLAUDE.md)
current_file = Path(__file__).absolute()
parent_dir = current_file.parent.parent
sys.path.insert(0, str(parent_dir))

# Import the MCP server
from src.tracer_mcp_server import TracerMCPServer


def test_mcp_server_initialization():
    """Test that the MCP server initializes correctly."""
    print("Testing MCP server initialization...")
    server = TracerMCPServer()

    # Test initialize method
    init_result = server.handle_initialize({})
    print(f"Initialize result: {json.dumps(init_result, indent=2)}")

    # Test tools list
    tools_result = server.handle_tools_list()
    print(f"Tools list: {json.dumps(tools_result, indent=2)}")

    return server


def test_import_path_finder(server):
    """Test the import_path_finder tool."""
    print("\nTesting import_path_finder tool...")

    params = {"name": "import_path_finder", "arguments": {}}

    result = server.handle_tools_call(params)
    print(f"Import path finder result: {json.dumps(result, indent=2)}")

    return result


def test_trace_python_with_simple_script(server):
    """Test the trace_python tool with a simple script."""
    print("\nTesting trace_python tool...")

    # Create a simple test script
    test_script_path = Path(__file__).parent / "simple_test_target.py"
    test_script_content = '''#!/usr/bin/env python3
"""Simple test script for tracing."""

def add_numbers(a, b):
    result = a + b
    print(f"Adding {a} + {b} = {result}")
    return result

def multiply_numbers(x, y):
    result = x * y
    print(f"Multiplying {x} * {y} = {result}")
    return result

if __name__ == "__main__":
    # Simple calculations to trace
    sum_result = add_numbers(5, 3)
    product_result = multiply_numbers(4, 7)
    
    print(f"Final results: sum={sum_result}, product={product_result}")
'''

    with open(test_script_path, "w") as f:
        f.write(test_script_content)

    print(f"Created test script at: {test_script_path}")

    # Test tracing the script
    params = {
        "name": "trace_python",
        "arguments": {
            "target": str(test_script_path),
            "target_type": "script",
            "enable_var_trace": True,
            "timeout": 10,
        },
    }

    result = server.handle_tools_call(params)
    print(f"Trace result preview (first 500 chars): {str(result)[:500]}...")

    # Cleanup
    test_script_path.unlink()

    return result


def main():
    """Main test function."""
    print("Starting MCP server tests...")

    try:
        # Test server initialization
        server = test_mcp_server_initialization()

        # Test import path finder
        import_result = test_import_path_finder(server)

        # Test trace python with simple script
        trace_result = test_trace_python_with_simple_script(server)

        print("\n" + "=" * 50)
        print("All MCP server tests completed successfully!")
        print("=" * 50)

        return True

    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
