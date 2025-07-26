from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List

import respx
from fastapi.testclient import TestClient
from httpx import Response

from tools.claude_code_proxy.config_manager import (
    AppConfig,
    ProviderConfig,
    config_manager,
)
from tools.claude_code_proxy.provider_router import provider_router
from tools.claude_code_proxy.server import app

# --- Mock Data Generators ---


def _create_openai_chunk(
    delta: Dict[str, Any],
    finish_reason: str | None = None,
    model: str = "gpt-4o",
    id: str = "chatcmpl-mock-id",
) -> str:
    """Helper to create a standard OpenAI SSE chunk string."""
    chunk = {
        "id": id,
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


async def mock_openai_stream_for_sse0() -> AsyncGenerator[bytes, None]:
    """Generates a mock OpenAI stream that produces a simple text response."""
    yield _create_openai_chunk({"role": "assistant"}).encode("utf-8")
    yield _create_openai_chunk({"content": '{"isNewTopic":"true","title":"程序功能解析"}'}).encode("utf-8")
    yield _create_openai_chunk({}, finish_reason="stop").encode("utf-8")
    yield "data: [DONE]\n\n".encode("utf-8")


async def mock_openai_stream_for_sse1() -> AsyncGenerator[bytes, None]:
    """Generates a mock OpenAI stream for a complex response with tool calls."""
    yield _create_openai_chunk({"role": "assistant"}).encode("utf-8")
    yield _create_openai_chunk(
        {"content": "Let me examine the main entry point and key files to understand the program's purpose:"}
    ).encode("utf-8")

    # Tool Call 1: Read entrypoint.py
    yield _create_openai_chunk(
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "Read_1",
                    "type": "function",
                    "function": {"name": "Read", "arguments": ""},
                }
            ]
        }
    ).encode("utf-8")
    argument_chunks = [
        '{"file_path": "/Users/richard/code/terminal-llm/debugger/lldb/ai/entrypoint.py"}'[i : i + 5]
        for i in range(0, 90, 5)
    ]
    for arg_chunk in argument_chunks:
        yield _create_openai_chunk({"tool_calls": [{"index": 0, "function": {"arguments": arg_chunk}}]}).encode("utf-8")

    # Tool Call 2: Read README.md
    yield _create_openai_chunk(
        {
            "tool_calls": [
                {
                    "index": 1,
                    "id": "Read_2",
                    "type": "function",
                    "function": {"name": "Read", "arguments": '{"file_path":'},
                }
            ]
        }
    ).encode("utf-8")
    yield _create_openai_chunk(
        {
            "tool_calls": [
                {
                    "index": 1,
                    "function": {"arguments": ' "/Users/richard/code/terminal-llm/debugger/lldb/ai/README.md"}'},
                }
            ]
        }
    ).encode("utf-8")

    # Tool Call 3: Read treehouse_lldb.py
    yield _create_openai_chunk(
        {
            "tool_calls": [
                {
                    "index": 2,
                    "id": "Read_3",
                    "type": "function",
                    "function": {
                        "name": "Read",
                        "arguments": '{"file_path": "/Users/richard/code/terminal-llm/debugger/lldb/ai/treehouse_lldb.py"}',
                    },
                }
            ]
        }
    ).encode("utf-8")

    yield _create_openai_chunk({}, finish_reason="tool_calls").encode("utf-8")
    yield "data: [DONE]\n\n".encode("utf-8")


async def _parse_sse_stream(stream: AsyncGenerator[str, None]) -> List[Dict[str, Any]]:
    """Helper to parse an SSE stream into a list of events."""
    events = []
    async for line in stream:
        if not line.startswith("data:"):
            continue
        data_str = line.split("data:", 1)[1].strip()
        try:
            events.append(json.loads(data_str))
        except json.JSONDecodeError:
            # Handle the [DONE] message or other non-json data
            pass
    return events


# --- Test Cases ---


class TestServer(unittest.IsolatedAsyncioTestCase):
    """Integration tests for the FastAPI server."""

    mock_config: AppConfig

    async def asyncSetUp(self) -> None:
        """Set up the test environment for async tests."""
        self.tests_root = Path(__file__).parent
        self.client = TestClient(app)

        self.mock_config = AppConfig(
            providers={
                "anthropic": {
                    "name": "Anthropic",
                    "default_provider": "test-key",
                    "model_providers": {
                        # Map specific models used in test requests to our mock provider
                        "claude-3-opus-20240229": "test-key",
                        "claude-3-sonnet-20240229": "test-key",
                        "claude-sonnet-4-20250514": "test-key",
                    },
                },
                "openai_providers": {
                    "test-key": {
                        "name": "test-config",
                        "base_url": "https://test.api",
                        "api_key": "test-key-secret",
                        "timeout": 30.0,
                        "default_models": {},
                        "default_model": "gpt-4o",
                        "extra_headers": {},
                        "supports_reasoning": False,
                        "reasoning_config": {},
                        "max_tokens_override": None,
                    }
                },
            }
        )
        # Inject the mock config into the global config manager
        config_manager._config = self.mock_config

        # FIX: Initialize the provider router with the mock config directly
        # Instead of relying on config_manager, pass the config explicitly
        await provider_router.initialize(config=self.mock_config)

        # No need to re-inject the config after initialization since it's already set
        # provider_router._config = self.mock_config
        # config_manager._config = self.mock_config

    async def asyncTearDown(self) -> None:
        """Clean up resources after tests."""
        await provider_router.cleanup()

    @property
    def mock_provider(self) -> ProviderConfig:
        """Convenience property to access the mock provider's config."""
        return self.mock_config.openai_providers["test-key"]

    @respx.mock
    async def test_downstream_api_error(self) -> None:
        """
        Tests that the proxy correctly handles and forwards a 5xx error
        from the downstream OpenAI API.
        """
        request_data = json.loads((self.tests_root / "request_one.json").read_text())
        error_data = json.loads((self.tests_root / "response_error.json").read_text())

        # Mock the downstream API to return an error
        mock_url = f"{self.mock_provider.base_url}/chat/completions"
        respx.post(mock_url).mock(return_value=Response(status_code=500, json=error_data))

        response = self.client.post("/v1/messages", json=request_data)

        self.assertEqual(response.status_code, 500)
        # Verify that the error message is correctly formatted and names the provider
        self.assertIn(f"Error from provider '{self.mock_provider.name}'", response.json()["error"]["message"])

    def test_bad_request_body(self) -> None:
        """
        Tests that the proxy returns a 400 error for an invalid request body.
        """
        response = self.client.post("/v1/messages", content="this is not json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request body", response.json()["error"]["message"])

    @respx.mock
    async def test_streaming_translation_simple(self) -> None:
        """
        Tests streaming translation for a simple text response.
        """
        request_file = "request_simple_stream.json"
        mock_openai_stream_fn = mock_openai_stream_for_sse0
        expected_anthropic_stream_file = "response-sse-0.txt"

        request_data = json.loads((self.tests_root / request_file).read_text())
        mock_url = f"{self.mock_provider.base_url}/chat/completions"
        respx.post(mock_url).mock(return_value=Response(200, content=mock_openai_stream_fn()))

        response = self.client.post("/v1/messages", json=request_data, timeout=30)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])

        # Compare the full streamed content against the expected output file
        expected_content = (self.tests_root / expected_anthropic_stream_file).read_text()
        self.assertEqual(response.text, expected_content)

    @respx.mock
    async def test_streaming_translation_complex(self) -> None:
        """
        Tests streaming translation for a complex response with tool calls.
        """
        request_file = "request_stream.json"
        mock_openai_stream_fn = mock_openai_stream_for_sse1
        expected_anthropic_stream_file = "response-sse-1.txt"

        request_data = json.loads((self.tests_root / request_file).read_text())
        mock_url = f"{self.mock_provider.base_url}/chat/completions"
        respx.post(mock_url).mock(return_value=Response(200, content=mock_openai_stream_fn()))

        response = self.client.post("/v1/messages", json=request_data, timeout=30)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])

        # Compare the full streamed content against the expected output file
        expected_content = (self.tests_root / expected_anthropic_stream_file).read_text()
        self.assertEqual(response.text, expected_content)


if __name__ == "__main__":
    unittest.main()
