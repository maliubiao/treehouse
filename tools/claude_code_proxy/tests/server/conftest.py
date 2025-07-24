"""
Pytest configuration and fixtures for server tests.
"""

import asyncio
from typing import Any, AsyncGenerator, Dict, List
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from claude_code_proxy.config_manager import ProviderConfig
from claude_code_proxy.server import app
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_app() -> FastAPI:
    """Create a test instance of the FastAPI application."""
    return app


@pytest.fixture
def test_client(test_app: FastAPI) -> TestClient:
    """Create a test client for the FastAPI application."""
    return TestClient(test_app)


@pytest.fixture
def mock_provider_config() -> ProviderConfig:
    """Create a mock provider configuration."""
    return ProviderConfig(
        name="test-provider",
        api_key="test-key",
        base_url="https://api.test.com",
        timeout=30.0,
        model_mappings={"claude-3-sonnet": "gpt-4", "claude-3-opus": "gpt-4-turbo"},
    )


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Create a mock HTTP client."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def sample_anthropic_request() -> Dict[str, Any]:
    """Sample Anthropic request payload."""
    return {
        "model": "claude-3-sonnet",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "stream": False,
    }


@pytest.fixture
def multilingual_requests() -> List[Dict[str, Any]]:
    """Multilingual test requests."""
    from tests.factories import EdgeCaseFactory

    contents = EdgeCaseFactory.create_multilingual_content()
    return [
        {"model": "claude-3-sonnet", "max_tokens": 1000, "messages": [{"role": "user", "content": content}]}
        for content in contents
    ]


@pytest.fixture
def malicious_requests() -> List[Dict[str, Any]]:
    """Malicious request test cases."""
    from tests.factories import EdgeCaseFactory

    return EdgeCaseFactory.create_malicious_requests()


@pytest.fixture
def batch_requests() -> Dict[str, Any]:
    """Various batch request test cases."""
    from tests.factories import BatchRequestFactory

    return {
        "valid": BatchRequestFactory.create_valid_batch_request(),
        "large": BatchRequestFactory.create_large_batch_request(),
        "invalid": BatchRequestFactory.create_invalid_batch_requests(),
    }


@pytest.fixture
def sample_anthropic_stream_request() -> Dict[str, Any]:
    """Sample Anthropic stream request payload."""
    return {
        "model": "claude-3-sonnet",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "stream": True,
    }


@pytest.fixture
def sample_openai_response() -> Dict[str, Any]:
    """Sample OpenAI response payload."""
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677858242,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "I'm doing well, thank you for asking!",
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"completion_tokens": 8, "prompt_tokens": 10, "total_tokens": 18},
    }


@pytest.fixture
def sample_openai_stream_chunks() -> list[Dict[str, Any]]:
    """Sample OpenAI stream response chunks."""
    return [
        {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 1677858242,
            "model": "gpt-4",
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 1677858242,
            "model": "gpt-4",
            "choices": [{"index": 0, "delta": {"content": "I'm"}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 1677858242,
            "model": "gpt-4",
            "choices": [{"index": 0, "delta": {"content": " doing well"}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 1677858242,
            "model": "gpt-4",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]
