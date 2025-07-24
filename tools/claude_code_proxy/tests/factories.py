"""
Test data factories for consistent test data generation.
Provides factory functions for creating test requests, responses, and fixtures.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from claude_code_proxy.models_anthropic import AnthropicRequest
from claude_code_proxy.models_openai import (
    OpenAIChatCompletion,
    OpenAIChatCompletionChunk,
    OpenAIChatMessageDelta,
    OpenAIChoice,
    OpenAIChoiceDelta,
    OpenAIFunctionCallDelta,
    OpenAIResponseMessage,
    OpenAIToolCallDelta,
    OpenAIUsage,
)


class RequestFactory:
    """Factory for creating test requests."""

    @staticmethod
    def create_basic_anthropic_request(
        model: str = "claude-3-sonnet",
        max_tokens: int = 1000,
        messages: Optional[List[Dict[str, str]]] = None,
        stream: bool = False,
    ) -> AnthropicRequest:
        """Create a basic Anthropic request."""
        if messages is None:
            messages = [{"role": "user", "content": "Hello, how are you?"}]

        return AnthropicRequest(model=model, max_tokens=max_tokens, messages=messages, stream=stream)

    @staticmethod
    def create_anthropic_request_with_tools(
        model: str = "claude-3-5-sonnet-20240620", max_tokens: int = 1024, tools: Optional[List[Dict[str, Any]]] = None
    ) -> AnthropicRequest:
        """Create an Anthropic request with tools."""
        if tools is None:
            tools = [
                {
                    "name": "get_current_weather",
                    "description": "Get the current weather in a given location",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string", "description": "The city name"},
                            "state": {"type": "string", "description": "The state code"},
                            "temperature": {"type": "number", "description": "Temperature in Celsius"},
                            "is_current": {"type": "boolean", "description": "Is this the current weather?"},
                        },
                        "required": ["city", "state"],
                    },
                },
                {
                    "name": "calculate_area",
                    "description": "Calculate area of a shape",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "shape": {"type": "string"},
                            "width": {"type": "number"},
                            "height": {"type": "integer"},
                            "active": {"type": "boolean"},
                        },
                        "required": ["shape", "width", "height"],
                    },
                },
            ]

        return AnthropicRequest(
            model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": "Test message"}], tools=tools
        )

    @staticmethod
    def create_multilingual_request(
        content: str, language: str = "en", model: str = "claude-3-sonnet"
    ) -> AnthropicRequest:
        """Create a request with multilingual content."""
        return AnthropicRequest(model=model, max_tokens=1000, messages=[{"role": "user", "content": content}])


class ResponseFactory:
    """Factory for creating test responses."""

    @staticmethod
    def create_basic_openai_response(
        content: str = "I'm doing well, thank you!", model: str = "gpt-4", finish_reason: str = "stop"
    ) -> OpenAIChatCompletion:
        """Create a basic OpenAI response."""
        return OpenAIChatCompletion(
            id="chatcmpl-test-123",
            object="chat.completion",
            created=int(datetime.now().timestamp()),
            model=model,
            choices=[
                OpenAIChoice(
                    index=0,
                    message=OpenAIResponseMessage(role="assistant", content=content),
                    finish_reason=finish_reason,
                )
            ],
            usage=OpenAIUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )

    @staticmethod
    def create_openai_response_with_tools(
        tool_calls: Optional[List[Dict[str, Any]]] = None, model: str = "gpt-4"
    ) -> OpenAIChatCompletion:
        """Create an OpenAI response with tool calls."""
        if tool_calls is None:
            tool_calls = [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "calculate_area",
                        "arguments": json.dumps(
                            {"shape": "rectangle", "width": "15.5", "height": "10", "active": "true"}
                        ),
                    },
                }
            ]

        return OpenAIChatCompletion(
            id="chatcmpl-test-tools-123",
            object="chat.completion",
            created=int(datetime.now().timestamp()),
            model=model,
            choices=[
                OpenAIChoice(
                    index=0,
                    message=OpenAIResponseMessage(
                        role="assistant", content="I'll calculate the area for you.", tool_calls=tool_calls
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=OpenAIUsage(prompt_tokens=20, completion_tokens=50, total_tokens=70),
        )

    @staticmethod
    def create_streaming_chunks(
        content: Optional[str] = None, tool_calls: Optional[List[Dict[str, Any]]] = None
    ) -> List[OpenAIChatCompletionChunk]:
        """Create streaming chunks for testing."""
        chunks = []

        if content:
            # Text streaming
            words = content.split()
            for i, word in enumerate(words):
                chunks.append(
                    OpenAIChatCompletionChunk(
                        id=f"chunk-{i}",
                        object="chat.completion.chunk",
                        created=int(datetime.now().timestamp()),
                        model="gpt-4",
                        choices=[
                            OpenAIChoiceDelta(
                                index=0, delta=OpenAIChatMessageDelta(content=f"{word} "), finish_reason=None
                            )
                        ],
                    )
                )

        if tool_calls:
            # Tool call streaming
            for tool_call in tool_calls:
                chunks.append(
                    OpenAIChatCompletionChunk(
                        id="chunk-tool",
                        object="chat.completion.chunk",
                        created=int(datetime.now().timestamp()),
                        model="gpt-4",
                        choices=[
                            OpenAIChoiceDelta(
                                index=0,
                                delta=OpenAIChatMessageDelta(
                                    tool_calls=[
                                        OpenAIToolCallDelta(
                                            index=0,
                                            id=tool_call["id"],
                                            function=OpenAIFunctionCallDelta(
                                                name=tool_call["function"]["name"],
                                                arguments=tool_call["function"]["arguments"],
                                            ),
                                        )
                                    ]
                                ),
                                finish_reason=None,
                            )
                        ],
                    )
                )

        return chunks


class EdgeCaseFactory:
    """Factory for creating edge case test data."""

    @staticmethod
    def create_malicious_requests() -> List[Dict[str, Any]]:
        """Create malicious request test cases."""
        return [
            {
                "model": "claude-3-sonnet'; DROP TABLE users;--",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": "test"}],
            },
            {"model": "claude-3-sonnet", "max_tokens": 1000, "messages": [{"role": "user", "content": "'; rm -rf /;"}]},
            {
                "model": "claude-3-sonnet",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": "<script>alert('xss')</script>"}],
            },
            {
                "model": "claude-3-sonnet",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": "../../../etc/passwd"}],
            },
        ]

    @staticmethod
    def create_multilingual_content() -> List[str]:
        """Create multilingual content test cases."""
        return [
            "你好，世界",  # Chinese
            "こんにちは世界",  # Japanese
            "Привет мир",  # Russian
            "مرحبا بالعالم",  # Arabic
            "안녕하세요 세계",  # Korean
            "Hola mundo",  # Spanish
            "Bonjour le monde",  # French
            "Hallo Welt",  # German
            "Ciao mondo",  # Italian
            "Olá mundo",  # Portuguese
        ]

    @staticmethod
    def create_type_conversion_edge_cases() -> List[Dict[str, Any]]:
        """Create edge cases for type conversion."""
        return [
            {"width": "", "height": "0", "active": "null"},
            {"width": "NaN", "height": "", "active": "true"},
            {"width": "-15.7", "height": "-10", "active": "false"},
            {"width": "15.0", "height": "10.5", "active": "1"},
            {"width": "0", "height": "0", "active": "0"},
            {"width": "1e3", "height": "1.5e2", "active": "True"},
            {"width": "Infinity", "height": "-Infinity", "active": "false"},
        ]


class BatchRequestFactory:
    """Factory for creating batch request test data."""

    @staticmethod
    def create_valid_batch_request(num_requests: int = 2) -> Dict[str, Any]:
        """Create a valid batch request."""
        return {
            "requests": [
                {
                    "custom_id": f"test-{i}",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": f"Request {i}"}],
                    },
                }
                for i in range(num_requests)
            ]
        }

    @staticmethod
    def create_large_batch_request(num_requests: int = 1000) -> Dict[str, Any]:
        """Create a large batch request for testing limits."""
        return {
            "requests": [
                {
                    "custom_id": f"test-{i}",
                    "params": {
                        "model": "claude-3-sonnet",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": f"Large request {i}"}],
                    },
                }
                for i in range(num_requests)
            ]
        }

    @staticmethod
    def create_invalid_batch_requests() -> List[Dict[str, Any]]:
        """Create invalid batch requests for error testing."""
        return [
            {"requests": []},  # Empty batch
            {"requests": [{"custom_id": "", "params": {"model": "test"}}]},  # Empty custom_id
            {"requests": [{"custom_id": "test", "params": {"stream": True}}]},  # Streaming in batch
            {"requests": [{"custom_id": "test"}]},  # Missing params
            {"requests": [{"params": {"model": "test"}}]},  # Missing custom_id
        ]


# Convenience aliases
RequestFactory.create = RequestFactory.create_basic_anthropic_request
ResponseFactory.create = ResponseFactory.create_basic_openai_response
