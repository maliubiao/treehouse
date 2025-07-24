"""
Unit tests for server.py - testing individual components and functions.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_code_proxy.models_anthropic import AnthropicRequest
from claude_code_proxy.server import _create_error_response, _handle_downstream_error, app
from fastapi.testclient import TestClient
from pydantic import ValidationError


class TestErrorResponses:
    """Test error response creation functions."""

    def test_create_error_response_basic(self):
        """Test basic error response creation."""
        response = _create_error_response("Test error message")

        assert response.status_code == 400
        assert response.body is not None

        body = json.loads(response.body)
        assert body["type"] == "error"
        assert body["error"]["type"] == "invalid_request_error"
        assert body["error"]["message"] == "Test error message"

    def test_create_error_response_custom(self):
        """Test error response with custom parameters."""
        response = _create_error_response("Custom error", error_type="api_error", status_code=500)

        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"]["type"] == "api_error"
        assert body["error"]["message"] == "Custom error"


class TestRequestValidation:
    """Test request validation and parsing."""

    def test_valid_anthropic_request(self, sample_anthropic_request):
        """Test valid Anthropic request parsing."""
        request = AnthropicRequest.model_validate(sample_anthropic_request)

        assert request.model == "claude-3-sonnet"
        assert request.max_tokens == 1000
        assert len(request.messages) == 1
        assert request.messages[0].role == "user"
        assert request.messages[0].content == "Hello, how are you?"
        assert request.stream is False

    def test_invalid_json_handling(self, test_client):
        """Test handling of invalid JSON."""
        response = test_client.post(
            "/v1/messages", content="invalid json", headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 400
        assert "Invalid request body" in response.json()["error"]["message"]

    def test_missing_required_fields(self, test_client):
        """Test handling of missing required fields."""
        invalid_request = {
            "model": "claude-3-sonnet"
            # Missing required fields like max_tokens, messages
        }

        response = test_client.post("/v1/messages", json=invalid_request)

        assert response.status_code == 400
        assert "Invalid request body" in response.json()["error"]["message"]


class TestProviderRouting:
    """Test provider routing logic."""

    @patch("claude_code_proxy.server.provider_router")
    def test_no_provider_found(self, mock_router, test_client, sample_anthropic_request):
        """Test when no provider can be found for a model."""
        mock_router.route_request.return_value = None

        response = test_client.post("/v1/messages", json=sample_anthropic_request)

        assert response.status_code == 404
        assert "No provider could be determined" in response.json()["error"]["message"]
        mock_router.route_request.assert_called_once()

    @patch("claude_code_proxy.server.provider_router")
    def test_provider_not_found_in_config(self, mock_router, test_client, sample_anthropic_request):
        """Test when provider key is not found in configuration."""
        mock_router.route_request.return_value = "non-existent-provider"
        mock_router.get_provider_by_key.return_value = None

        response = test_client.post("/v1/messages", json=sample_anthropic_request)

        assert response.status_code == 500
        assert "not found in configuration" in response.json()["error"]["message"]

    @patch("claude_code_proxy.server.provider_router")
    def test_invalid_model_mapping(self, mock_router, test_client, sample_anthropic_request):
        """Test invalid model mapping."""
        mock_router.route_request.return_value = "test-provider"
        mock_router.get_provider_by_key.return_value = MagicMock(name="test-provider")
        mock_router.get_target_model.return_value = "INVALID_mapping"

        response = test_client.post("/v1/messages", json=sample_anthropic_request)

        assert response.status_code == 400
        assert "Invalid model mapping" in response.json()["error"]["message"]


class TestHTTPClientHandling:
    """Test HTTP client initialization and handling."""

    @patch("claude_code_proxy.server.provider_router")
    def test_http_client_not_found(self, mock_router, test_client, sample_anthropic_request):
        """Test when HTTP client is not found."""
        mock_provider = MagicMock(name="test-provider")
        mock_router.route_request.return_value = "test-provider"
        mock_router.get_provider_by_key.return_value = mock_provider
        mock_router.get_target_model.return_value = "gpt-4"
        mock_router.get_client.return_value = None

        response = test_client.post("/v1/messages", json=sample_anthropic_request)

        assert response.status_code == 500
        assert "HTTP client for provider key" in response.json()["error"]["message"]


class TestBatchRequestValidation:
    """Test batch request validation."""

    def test_empty_batch_request(self, test_client):
        """Test empty batch request."""
        response = test_client.post("/v1/messages/batches", json={"requests": []})

        assert response.status_code == 400
        assert "Batch request cannot be empty" in response.json()["error"]["message"]

    def test_streaming_in_batch(self, test_client):
        """Test that streaming is not allowed in batch requests."""
        batch_request = {
            "requests": [
                {
                    "custom_id": "test-1",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": "test"}],
                        "stream": True,  # This should fail
                    },
                }
            ]
        }

        response = test_client.post("/v1/messages/batches", json=batch_request)

        assert response.status_code == 400
        assert "Streaming is not supported" in response.json()["error"]["message"]

    def test_invalid_batch_json(self, test_client):
        """Test invalid JSON in batch request."""
        response = test_client.post(
            "/v1/messages/batches", content="invalid json", headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 400
        assert "Invalid batch request" in response.json()["error"]["message"]
