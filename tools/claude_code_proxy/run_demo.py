#!/usr/bin/env python3
"""
run_demo.py
A correct demo that tests the Anthropic → OpenAI proxy server (server.py)
using the official Anthropic Python client.
"""

import logging
import sys
import time

import anthropic

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("demo")

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
PROXY_BASE_URL = "http://127.0.0.1:8084"  # Adjusted port
MODEL = "claude-3-5-sonnet-20240620"  # A generic model name to be mapped by the proxy


# -----------------------------------------------------------------------------
# Test functions
# -----------------------------------------------------------------------------
def test_non_streaming_simple_message(client: anthropic.Anthropic) -> None:
    """Test a simple non-streaming chat completion."""
    logger.info("=== Testing Non-Streaming Simple Message ===")
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=50,
            messages=[{"role": "user", "content": "Hello, world!"}],
        )
        logger.info("Response ID: %s", response.id)
        logger.info("Model: %s", response.model)
        logger.info("Content: %s", response.content[0].text)
        logger.info("Usage: %s", response.usage)
    except Exception as e:
        logger.exception("Non-streaming test failed: %s", e)
        raise


def test_streaming_simple_message(client: anthropic.Anthropic) -> None:
    """Test a simple streaming chat completion."""
    logger.info("=== Testing Streaming Simple Message ===")
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=50,
            messages=[{"role": "user", "content": "Count from 1 to 5 slowly."}],
        ) as stream:
            logger.info("Streaming response: ")
            for text in stream.text_stream:
                print(text, end="", flush=True)
            print()
        logger.info("Streaming test completed.")
    except Exception as e:
        logger.exception("Streaming test failed: %s", e)
        raise


def test_tool_use(client: anthropic.Anthropic) -> None:
    """Test tool/function calling."""
    logger.info("=== Testing Tool Use ===")
    tools = [
        {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "input_schema": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        }
    ]
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
            tools=tools,
        )
        logger.info("Response: %s", response)
        if response.stop_reason == "tool_use":
            tool_use = next(block for block in response.content if block.type == "tool_use")
            logger.info("Tool call detected: %s", tool_use.name)
            logger.info("Tool input: %s", tool_use.input)
    except Exception as e:
        logger.exception("Tool use test failed: %s", e)
        raise


def test_streaming_reasoning_model(client: anthropic.Anthropic) -> None:
    """Test routing to and streaming from a reasoning-enabled provider."""
    logger.info("=== Testing Streaming Reasoning Model Routing ===")
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": "Explain quantum entanglement step by step."}],
            thinking={"type": "enabled", "budget_tokens": 1024},
        ) as stream:
            logger.info("Streaming reasoning response: ")
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "thinking_delta":
                        # Use a different color or marker for thinking
                        print(f"\033[92m{event.delta.thinking}\033[0m", end="", flush=True)
                    elif event.delta.type == "text_delta":
                        print(event.delta.text, end="", flush=True)
            print()
        logger.info("Streaming reasoning test completed.")
    except Exception as e:
        logger.exception("Streaming reasoning test failed: %s", e)
        raise


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> None:
    """Run all tests."""
    logger.info("=== Anthropic to OpenAI Proxy Demo ===")
    logger.info("Connecting to proxy at: %s", PROXY_BASE_URL)

    # Configure Anthropic client to use our proxy
    client = anthropic.Anthropic(base_url=PROXY_BASE_URL, api_key="dummy_key")

    logger.info("Waiting for server to be ready...")
    time.sleep(2)

    try:
        test_non_streaming_simple_message(client)
        test_streaming_simple_message(client)
        test_tool_use(client)
        test_streaming_reasoning_model(client)
        logger.info("Demo client completed successfully")
    except KeyboardInterrupt:
        logger.info("Demo interrupted by user")
    except (anthropic.APIError, ConnectionError, TimeoutError):
        # The logger.exception in each function already logs details
        logger.error("Demo failed. See exceptions above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
