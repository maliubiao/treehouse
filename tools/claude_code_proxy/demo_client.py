#!/usr/bin/env python3
"""
Demo client for testing Anthropic to OpenAI proxy server.

This script demonstrates how to use the official Anthropic Python SDK
to test the proxy server with various scenarios:
- Non-streaming simple messages
- Streaming simple messages
- Tool use (function calling)
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List

import anthropic
from anthropic.types import Message, MessageStreamEvent


def load_openai_config() -> Dict[str, Any]:
    """Load OpenAI service configuration from JSON file."""
    config_path = os.path.join(os.path.dirname(__file__), "openai_service_config.json")
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Configuration file {config_path} not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in configuration file: {e}")
        sys.exit(1)


def setup_anthropic_client(config: Dict[str, Any]) -> anthropic.Anthropic:
    """Configure and return an Anthropic client pointing to the proxy."""
    # Set environment variables for the proxy
    os.environ["ANTHROPIC_BASE_URL"] = config["proxy_base_url"]
    os.environ["ANTHROPIC_API_KEY"] = "dummy_key"  # Not used by proxy

    return anthropic.Anthropic(base_url=config["proxy_base_url"], api_key="dummy_key")


def test_non_streaming_simple(client: anthropic.Anthropic, model: str) -> None:
    """Test non-streaming simple message."""
    print("\n=== Testing Non-Streaming Simple Message ===")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=100,
            messages=[{"role": "user", "content": "Hello! Can you introduce yourself briefly?"}],
        )

        print(f"Response ID: {response.id}")
        print(f"Model: {response.model}")
        print(f"Content: {response.content[0].text}")
        print(f"Usage: {response.usage}")

    except Exception as e:
        print(f"Error: {e}")


def test_streaming_simple(client: anthropic.Anthropic, model: str) -> None:
    """Test streaming simple message."""
    print("\n=== Testing Streaming Simple Message ===")

    try:
        with client.messages.stream(
            model=model,
            max_tokens=100,
            messages=[{"role": "user", "content": "Tell me a short joke about programming."}],
        ) as stream:
            print("Streaming response: ", end="")
            for text in stream.text_stream:
                print(text, end="", flush=True)
            print()

    except Exception as e:
        print(f"Error: {e}")


def test_tool_use(client: anthropic.Anthropic, model: str) -> None:
    """Test tool use (function calling)."""
    print("\n=== Testing Tool Use ===")

    # Define a simple calculator tool
    tools = [
        {
            "name": "calculate",
            "description": "Perform basic arithmetic operations",
            "input_schema": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide"],
                        "description": "The arithmetic operation to perform",
                    },
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"},
                },
                "required": ["operation", "a", "b"],
            },
        }
    ]

    try:
        response = client.messages.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": "What's 15 multiplied by 7?"}],
            tools=tools,
        )

        print(f"Response: {response}")

        # Check if tool was used
        if response.stop_reason == "tool_use":
            tool_use = next(block for block in response.content if block.type == "tool_use")
            print(f"Tool used: {tool_use.name}")
            print(f"Tool input: {tool_use.input}")

            # Simulate tool execution
            tool_result = simulate_tool_execution(tool_use.name, tool_use.input)

            # Continue conversation with tool result
            follow_up = client.messages.create(
                model=model,
                max_tokens=100,
                messages=[
                    {"role": "user", "content": "What's 15 multiplied by 7?"},
                    response,
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": str(tool_result)}],
                    },
                ],
                tools=tools,
            )

            print(f"Final answer: {follow_up.content[0].text}")

    except Exception as e:
        print(f"Error: {e}")


def simulate_tool_execution(tool_name: str, tool_input: Dict[str, Any]) -> Any:
    """Simulate tool execution for demo purposes."""
    if tool_name == "calculate":
        operation = tool_input["operation"]
        a = tool_input["a"]
        b = tool_input["b"]

        if operation == "add":
            return a + b
        elif operation == "subtract":
            return a - b
        elif operation == "multiply":
            return a * b
        elif operation == "divide":
            return a / b if b != 0 else "Error: Division by zero"

    return "Error: Unknown tool"


def test_streaming_tool_use(client: anthropic.Anthropic, model: str) -> None:
    """Test streaming with tool use."""
    print("\n=== Testing Streaming Tool Use ===")

    tools = [
        {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "input_schema": {
                "type": "object",
                "properties": {"location": {"type": "string", "description": "City name"}},
                "required": ["location"],
            },
        }
    ]

    try:
        with client.messages.stream(
            model=model,
            max_tokens=150,
            messages=[{"role": "user", "content": "What's the weather like in San Francisco?"}],
            tools=tools,
        ) as stream:
            print("Streaming response: ", end="")
            for text in stream.text_stream:
                print(text, end="", flush=True)
            print()

    except Exception as e:
        print(f"Error: {e}")


def run_all_tests() -> None:
    """Run all test scenarios."""
    print("Loading configuration...")
    config = load_openai_config()

    print(f"Proxy URL: {config['proxy_base_url']}")
    print(f"OpenAI Base URL: {config['openai_base_url']}")
    print(f"Model: {config['model_name']}")

    client = setup_anthropic_client(config)
    model = config["model_name"]

    # Wait a moment for server to be ready
    print("Waiting for server to be ready...")
    time.sleep(2)

    # Run tests
    test_non_streaming_simple(client, model)
    test_streaming_simple(client, model)
    test_tool_use(client, model)
    test_streaming_tool_use(client, model)

    print("\n=== All tests completed ===")


if __name__ == "__main__":
    run_all_tests()
