"""
Integration tests for server.py - testing complete API flows.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_code_proxy.server import app
from fastapi.testclient import TestClient


class TestMessagesEndpointIntegration:
    """Integration tests for /v1/messages endpoint."""

    @patch("claude_code_proxy.server.provider_router")
    def test_successful_non_streaming_request(
        self, mock_router, test_client, sample_anthropic_request, sample_openai_response
    ):
        """Test successful non-streaming request flow."""
        # Setup mocks
        mock_provider = MagicMock(name="test-provider")
        mock_provider.timeout = 30.0
        mock_provider.model_dump.return_value = {"name": "test-provider"}

        mock_router.route_request.return_value = "test-provider"
        mock_router.get_provider_by_key.return_value = mock_provider
        mock_router.get_target_model.return_value = "gpt-4"

        # Mock HTTP client and response
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        # Ensure json() returns the actual data, not a coroutine
        mock_response.json = AsyncMock(return_value=sample_openai_response)
        mock_response.raise_for_status = AsyncMock(return_value=None)
        mock_response.status_code = 200
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_router.get_client.return_value = mock_client

        response = test_client.post("/v1/messages", json=sample_anthropic_request)

        assert response.status_code == 200
        response_data = response.json()

        # Verify the response is in Anthropic format
        assert "content" in response_data
        assert response_data["content"][0]["type"] == "text"
        assert "I'm doing well" in response_data["content"][0]["text"]

        # Verify the HTTP client was called correctly
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/chat/completions"
        assert "gpt-4" in str(call_args[1]["json"])

    @patch("claude_code_proxy.server.provider_router")
    def test_successful_streaming_request(
        self, mock_router, test_client, sample_anthropic_stream_request, sample_openai_stream_chunks
    ):
        """Test successful streaming request flow."""
        # Setup mocks
        mock_provider = MagicMock(name="test-provider")
        mock_provider.timeout = 30.0
        mock_provider.model_dump.return_value = {"name": "test-provider"}

        mock_router.route_request.return_value = "test-provider"
        mock_router.get_provider_by_key.return_value = mock_provider
        mock_router.get_target_model.return_value = "gpt-4"

        # Mock HTTP client and streaming response
        mock_client = AsyncMock()
        mock_response = AsyncMock()

        # Create async generator for streaming chunks
        async def mock_aiter_bytes():
            for chunk in sample_openai_stream_chunks:
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        mock_response.aiter_bytes = mock_aiter_bytes
        mock_response.raise_for_status = AsyncMock(return_value=None)

        mock_build_request = AsyncMock()
        mock_build_request.return_value = AsyncMock()
        mock_client.build_request = mock_build_request
        mock_client.send = AsyncMock(return_value=mock_response)

        mock_router.get_client.return_value = mock_client

        response = test_client.post("/v1/messages", json=sample_anthropic_stream_request)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Read streaming response
        lines = response.text.strip().split("\n")
        assert len(lines) > 0
        assert any("data:" in line for line in lines)

    @patch("claude_code_proxy.server.provider_router")
    def test_downstream_api_error(self, mock_router, test_client, sample_anthropic_request):
        """Test handling of downstream API errors."""
        # Setup mocks
        mock_provider = MagicMock(name="test-provider")
        mock_provider.timeout = 30.0
        mock_provider.model_dump.return_value = {"name": "test-provider"}

        mock_router.route_request.return_value = "test-provider"
        mock_router.get_provider_by_key.return_value = mock_provider
        mock_router.get_target_model.return_value = "gpt-4"

        # Mock HTTP client to raise an error
        mock_client = AsyncMock()
        from httpx import HTTPStatusError, Response

        error_response = Response(400, content=b'{"error": {"message": "Bad request"}}')
        error_response._request = AsyncMock()

        http_error = HTTPStatusError("Bad request", request=error_response._request, response=error_response)
        mock_client.post.side_effect = http_error

        mock_router.get_client.return_value = mock_client

        response = test_client.post("/v1/messages", json=sample_anthropic_request)

        assert response.status_code == 400
        assert "Error from provider" in response.json()["error"]["message"]
        assert "Bad request" in response.json()["error"]["message"]


class TestBatchEndpointIntegration:
    """Integration tests for /v1/messages/batches endpoint."""

    @patch("claude_code_proxy.server.provider_router")
    def test_successful_batch_request(self, mock_router, test_client):
        """Test successful batch request flow."""
        # Setup mocks
        mock_provider = MagicMock(name="test-provider")
        mock_provider.timeout = 30.0
        mock_provider.model_dump.return_value = {"name": "test-provider"}

        mock_router.route_request.return_value = "test-provider"
        mock_router.get_provider_by_key.return_value = mock_provider
        mock_router.get_target_model.return_value = "gpt-4"

        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"status": "success"})
        mock_response.raise_for_status = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_router.get_client.return_value = mock_client

        batch_request = {
            "requests": [
                {
                    "custom_id": "test-1",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": "Hello"}],
                    },
                },
                {
                    "custom_id": "test-2",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": "World"}],
                    },
                },
            ]
        }

        response = test_client.post("/v1/messages/batches", json=batch_request)

        assert response.status_code == 200
        assert response.json()["status"] == "Batch request sent successfully to provider"
        assert response.json()["provider"] == "test-provider"

    @patch("claude_code_proxy.server.provider_router")
    def test_batch_partial_failure_handling(self, mock_router, test_client):
        """Test handling of partial failures in batch requests."""
        mock_provider = MagicMock()
        mock_provider.timeout = 30.0
        mock_provider.model_dump.return_value = {"name": "test-provider"}

        mock_router.route_request.return_value = "test-provider"
        mock_router.get_provider_by_key.return_value = mock_provider
        mock_router.get_target_model.return_value = "gpt-4"

        # Mock HTTP client with mixed response
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "responses": [
                {"custom_id": "test-1", "status": "success", "result": {"content": "Hello"}},
                {"custom_id": "test-2", "status": "error", "error": {"message": "Timeout", "type": "timeout"}},
            ]
        }
        mock_response.raise_for_status = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_router.get_client.return_value = mock_client

        batch_request = {
            "requests": [
                {
                    "custom_id": "test-1",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": "Hello"}],
                    },
                },
                {
                    "custom_id": "test-2",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": "World"}],
                    },
                },
            ]
        }

        response = test_client.post("/v1/messages/batches", json=batch_request)

        assert response.status_code == 207  # Partial success
        response_data = response.json()
        assert response_data["status"] == "partial_failure"
        assert len(response_data["results"]) == 2
        assert response_data["results"][0]["status"] == "success"
        assert response_data["results"][1]["status"] == "error"

    @patch("claude_code_proxy.server.provider_router")
    def test_batch_empty_custom_id_handling(self, mock_router, test_client):
        """Test handling of empty custom_id in batch requests."""
        mock_provider = MagicMock()
        mock_router.get_provider_by_key.return_value = mock_provider
        mock_router.route_request.return_value = "test-provider"
        mock_router.get_target_model.return_value = "gpt-4"
        mock_router.get_client.return_value = MagicMock()

        batch_request = {
            "requests": [
                {
                    "custom_id": "",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": "Hello"}],
                    },
                }
            ]
        }

        response = test_client.post("/v1/messages/batches", json=batch_request)

        assert response.status_code == 400
        assert "custom_id" in response.json()["error"]["message"]

    @patch("claude_code_proxy.server.provider_router")
    def test_batch_multiple_providers_error(self, mock_router, test_client):
        """Test batch request with multiple providers (should fail)."""

        # Setup mocks to return different providers
        def mock_route_side_effect(request):
            # Return different providers based on model
            return "provider-1" if request.model == "claude-3-sonnet" else "provider-2"

        mock_router.route_request.side_effect = mock_route_side_effect
        mock_router.get_provider_by_key.return_value = MagicMock(name="test-provider")
        mock_router.get_target_model.return_value = "gpt-4"

        batch_request = {
            "requests": [
                {
                    "custom_id": "test-1",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": "Hello"}],
                    },
                },
                {
                    "custom_id": "test-2",
                    "params": {
                        "model": "claude-3-opus",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": "World"}],
                    },
                },
            ]
        }

        response = test_client.post("/v1/messages/batches", json=batch_request)

        assert response.status_code == 422
        assert "multiple providers" in response.json()["error"]["message"]


class TestServerLifecycle:
    """Test server startup and shutdown lifecycle."""

    def test_server_startup(self, test_client):
        """Test that the server starts up correctly."""
        response = test_client.get("/docs")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_server_health_check(self, test_client):
        """Test basic server health check."""
        # FastAPI automatically provides /docs and /openapi.json
        response = test_client.get("/openapi.json")
        assert response.status_code == 200

        openapi = response.json()
        assert "/v1/messages" in openapi["paths"]
        assert "/v1/messages/batches" in openapi["paths"]
