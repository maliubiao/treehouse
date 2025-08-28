#!/usr/bin/env python3
"""
Comprehensive test client for the HTTP MCP server.
This script tests the HTTP version of the tracer MCP server with detailed validation.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
try:
    import httpx
except ImportError:
    print("httpx is required for HTTP MCP client")
    print("Install with: pip install httpx")
    sys.exit(1)


class HTTPMCPClient:
    """Comprehensive HTTP client for MCP server testing with detailed validation."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.mcp_endpoint = f"{self.base_url}/jsonrpc"
        self.request_id = 1
        self.client = httpx.AsyncClient(timeout=30.0)

    def _get_next_id(self) -> int:
        """Get next request ID."""
        current_id = self.request_id
        self.request_id += 1
        return current_id

    async def send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request to the MCP server with proper error handling."""
        request_data = {"jsonrpc": "2.0", "id": self._get_next_id(), "method": method, "params": params or {}}

        try:
            response = await self.client.post(
                self.mcp_endpoint, json=request_data, headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": {"code": -32000, "message": f"HTTP request failed: {str(e)}"}}
        except json.JSONDecodeError as e:
            return {"error": {"code": -32700, "message": f"Invalid JSON response: {str(e)}"}}

    async def test_server_health(self) -> bool:
        """Test server health endpoint."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            response.raise_for_status()
            data = response.json()
            print(f"✅ Health check: {data}")
            return True
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            return False

    async def test_initialize(self) -> bool:
        """Test MCP initialize method with detailed validation."""
        print("🧪 Testing initialize method...")
        response = await self.send_request("initialize", {"protocolVersion": "2024-11-05"})

        if "error" in response:
            print(f"❌ Initialize failed: {response['error']['message']}")
            return False

        result = response.get("result", {})
        if result.get("protocolVersion") == "2024-11-05":
            print("✅ Initialize successful - protocol version validated")
            return True
        else:
            print(f"❌ Initialize failed: Unexpected result {result}")
            return False

    async def test_tools_list(self) -> bool:
        """Test MCP tools/list method with tool validation."""
        print("🧪 Testing tools/list method...")
        response = await self.send_request("tools/list")

        if "error" in response:
            print(f"❌ Tools list failed: {response['error']['message']}")
            return False

        result = response.get("result", {})
        tools = result.get("tools", [])

        expected_tools = ["trace_python", "import_path_finder"]
        tool_names = [tool["name"] for tool in tools]

        if all(tool in tool_names for tool in expected_tools):
            print(f"✅ Tools list successful: Found {len(tools)} tools including {expected_tools}")
            return True
        else:
            print(f"❌ Tools list failed. Expected {expected_tools}, got {tool_names}")
            return False

    async def test_trace_python_script(self) -> bool:
        """Test trace_python with a script target."""
        print("🧪 Testing trace_python with script target...")

        # Create a simple test script
        test_script = """
print("Hello from test script!")
result = 2 + 2
print(f"2 + 2 = {result}")
"""

        script_path = Path("/tmp/test_script.py")
        script_path.write_text(test_script)

        params = {
            "name": "trace_python",
            "arguments": {"target": str(script_path), "target_type": "script", "args": [], "timeout": 10},
        }

        response = await self.send_request("tools/call", params)

        if "error" in response:
            print(f"❌ Trace python failed: {response['error']['message']}")
            script_path.unlink(missing_ok=True)
            return False

        result = response.get("result", {})
        content = result.get("content", [{}])[0].get("text", "")

        # Cleanup
        script_path.unlink(missing_ok=True)

        if "Hello from test script!" in content and "2 + 2 = 4" in content:
            print("✅ Trace python script successful")
            return True
        else:
            print(f"❌ Trace python script failed. Output: {content[:200]}...")
            return False

    async def test_trace_python_module(self) -> bool:
        """Test trace_python with a module target."""
        print("🧪 Testing trace_python with module target...")

        params = {
            "name": "trace_python",
            "arguments": {"target": "json", "target_type": "module", "args": [], "timeout": 10},
        }

        response = await self.send_request("tools/call", params)

        if "error" in response:
            print(f"❌ Trace python module failed: {response['error']['message']}")
            return False

        result = response.get("result", {})
        content = result.get("content", [{}])[0].get("text", "")

        if "Trace completed" in content:
            print("✅ Trace python module successful")
            return True
        else:
            print(f"❌ Trace python module failed. Output: {content[:200]}...")
            return False

    async def test_import_path_finder(self) -> bool:
        """Test import_path_finder tool with validation."""
        print("🧪 Testing import_path_finder...")

        params = {"name": "import_path_finder", "arguments": {"max_depth": 2}}

        response = await self.send_request("tools/call", params)

        if "error" in response:
            print(f"❌ Import path finder failed: {response['error']['message']}")
            return False

        result = response.get("result", {})
        content = result.get("content", [{}])[0].get("text", "")

        if "import_suggestions" in content and "current_directory" in content:
            print("✅ Import path finder successful")
            return True
        else:
            print(f"❌ Import path finder failed. Output: {content[:200]}...")
            return False

    async def test_error_handling(self) -> bool:
        """Test error handling with invalid requests."""
        print("🧪 Testing error handling...")

        # Test unknown method
        response = await self.send_request("unknown_method")
        if "error" in response and response["error"].get("code") == -32601:
            print("✅ Unknown method error handling successful")
        else:
            print(f"❌ Unknown method error handling failed: {response}")
            return False

        # Test invalid trace_python parameters
        params = {"name": "trace_python", "arguments": {"target": "/nonexistent/path.py", "target_type": "script"}}

        response = await self.send_request("tools/call", params)
        if "error" in response or (
            "result" in response and "Error" in response["result"].get("content", [{}])[0].get("text", "")
        ):
            print("✅ Invalid parameters error handling successful")
            return True
        else:
            print(f"❌ Invalid parameters error handling failed: {response}")
            return False

    async def run_all_tests(self) -> Dict[str, bool]:
        """Run all tests and return detailed results."""
        print(f"🚀 Starting HTTP MCP server tests against {self.base_url}")
        print("=" * 60)

        results = {}

        # Test initialize
        results["initialize"] = await self.test_initialize()

        # Test tools list
        results["tools_list"] = await self.test_tools_list()

        # Test trace_python with script
        results["trace_python_script"] = await self.test_trace_python_script()

        # Test trace_python with module
        results["trace_python_module"] = await self.test_trace_python_module()

        # Test import_path_finder
        results["import_path_finder"] = await self.test_import_path_finder()

        # Test error handling
        results["error_handling"] = await self.test_error_handling()

        return results

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


async def main():
    """Main test function."""
    # Get server URL from command line or use default
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

    client = HTTPMCPClient(base_url)

    try:
        start_time = time.time()
        results = await client.run_all_tests()
        end_time = time.time()

        print("\n" + "=" * 60)
        print("📊 TEST RESULTS:")
        print("=" * 60)

        total_tests = len(results)
        passed_tests = sum(results.values())
        failed_tests = total_tests - passed_tests

        for test_name, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status} {test_name}")

        print(f"\n📈 Summary: {passed_tests}/{total_tests} tests passed")
        print(f"⏱️  Time taken: {end_time - start_time:.2f} seconds")

        if failed_tests == 0:
            print("\n🎉 All tests passed! HTTP MCP server is working correctly.")
            return 0
        else:
            print(f"\n💥 {failed_tests} test(s) failed. Please check the server implementation.")
            return 1

    except Exception as e:
        print(f"\n🔥 Unexpected error during testing: {e}")
        import traceback

        traceback.print_exc()
        return 2
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
