"""
Benchmark tests for performance validation.
Tests response time, throughput, and resource usage.
"""

import asyncio
import json
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_code_proxy.models_anthropic import AnthropicRequest
from claude_code_proxy.models_openai import OpenAIChatCompletion, OpenAIChoice, OpenAIResponseMessage, OpenAIUsage
from claude_code_proxy.response_translator_v2 import (
    OpenAIToAnthropicStreamTranslator,
    translate_openai_to_anthropic_non_stream,
)
from claude_code_proxy.server import app
from fastapi.testclient import TestClient


class TestPerformanceBenchmarks:
    """Performance benchmark tests."""

    def test_translation_latency_benchmark(self):
        """Benchmark translation latency for non-streaming responses."""
        # Create test data
        request = AnthropicRequest(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Test message"}],
            tools=[
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
                }
            ],
        )

        openai_response = OpenAIChatCompletion(
            id="benchmark-test",
            object="chat.completion",
            created=1234567890,
            model="gpt-4",
            choices=[
                OpenAIChoice(
                    index=0,
                    message=OpenAIResponseMessage(
                        role="assistant",
                        content="I'll calculate the area for you.",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "calculate_area",
                                    "arguments": '{"shape": "rectangle", "width": "15.5", "height": "10", "active": "true"}',
                                },
                            }
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=OpenAIUsage(prompt_tokens=20, completion_tokens=50, total_tokens=70),
        )

        # Benchmark translation
        times = []
        for _ in range(100):
            start = time.perf_counter()
            result = translate_openai_to_anthropic_non_stream(openai_response, request)
            end = time.perf_counter()
            times.append(end - start)

        avg_latency = sum(times) / len(times)
        p95_latency = sorted(times)[int(len(times) * 0.95)]

        # Assert performance requirements
        assert avg_latency < 0.01  # 10ms average
        assert p95_latency < 0.05  # 50ms 95th percentile

        print(f"Average translation latency: {avg_latency:.4f}s")
        print(f"95th percentile latency: {p95_latency:.4f}s")

    def test_streaming_throughput_benchmark(self):
        """Benchmark streaming translation throughput."""
        request = AnthropicRequest(
            model="claude-3-5-sonnet-20240620", max_tokens=1024, messages=[{"role": "user", "content": "Test message"}]
        )

        translator = OpenAIToAnthropicStreamTranslator(response_id="throughput-test", model=request.model)
        translator.anthropic_request = request

        # Create streaming chunks
        chunks = []
        for i in range(1000):
            chunk_data = {
                "id": f"chunk-{i}",
                "object": "chat.completion.chunk",
                "created": 1234567890 + i,
                "model": "gpt-4",
                "choices": [{"index": 0, "delta": {"content": f"word{i} "}, "finish_reason": None}],
            }
            chunks.append(chunk_data)

        # Benchmark streaming processing
        start = time.perf_counter()
        for chunk_data in chunks:
            from claude_code_proxy.models_openai import OpenAIChatCompletionChunk

            chunk = OpenAIChatCompletionChunk(**chunk_data)
            translator.process_chunk(chunk, request)

        translator.finish_reason = "stop"
        final_events = translator.finalize()
        end = time.perf_counter()

        total_time = end - start
        throughput = len(chunks) / total_time

        # Assert performance requirements
        assert throughput > 100  # 100 chunks per second
        assert total_time < 10  # 10 seconds max

        print(f"Streaming throughput: {throughput:.2f} chunks/second")
        print(f"Total processing time: {total_time:.4f}s")

    @pytest.mark.asyncio
    async def test_concurrent_request_benchmark(self):
        """Benchmark concurrent request handling."""
        with TestClient(app) as client:
            # Mock provider setup
            with patch("claude_code_proxy.server.provider_router") as mock_router:
                mock_provider = MagicMock()
                mock_provider.timeout = 30.0
                mock_provider.model_dump.return_value = {"name": "test-provider"}

                mock_router.route_request.return_value = "test-provider"
                mock_router.get_provider_by_key.return_value = mock_provider
                mock_router.get_target_model.return_value = "gpt-4"

                # Mock HTTP client
                mock_client = AsyncMock()
                mock_response = AsyncMock()
                mock_response.json.return_value = {
                    "id": "concurrent-test",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Concurrent response"},
                            "finish_reason": "stop",
                        }
                    ],
                    "created": 1234567890,
                    "model": "gpt-4",
                    "object": "chat.completion",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                }
                mock_response.raise_for_status.return_value = None
                mock_client.post.return_value = mock_response
                mock_router.get_client.return_value = mock_client

                # Create concurrent requests
                request_data = {
                    "model": "claude-3-sonnet",
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": "Concurrent test"}],
                }

                # Run concurrent requests
                import concurrent.futures

                def make_request():
                    return client.post("/v1/messages", json=request_data)

                start = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(make_request) for _ in range(100)]
                    results = [f.result() for f in futures]
                end = time.perf_counter()

                # Verify all requests succeeded
                assert all(r.status_code == 200 for r in results)

                total_time = end - start
                avg_time = total_time / 100
                throughput = 100 / total_time

                # Assert performance requirements
                assert avg_time < 0.1  # 100ms average per request
                assert throughput > 50  # 50 requests per second

                print(f"Concurrent requests: 100 in {total_time:.4f}s")
                print(f"Average request time: {avg_time:.4f}s")
                print(f"Throughput: {throughput:.2f} requests/second")

    def test_memory_usage_benchmark(self):
        """Benchmark memory usage during translation."""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Create large request/response
        large_request = AnthropicRequest(
            model="claude-3-5-sonnet-20240620",
            max_tokens=4000,
            messages=[{"role": "user", "content": "x" * 10000}],  # 10KB message
            tools=[
                {
                    "name": f"tool_{i}",
                    "description": f"Tool {i} description",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "param1": {"type": "string"},
                            "param2": {"type": "number"},
                            "param3": {"type": "boolean"},
                        },
                    },
                }
                for i in range(100)  # 100 tools
            ],
        )

        large_response = OpenAIChatCompletion(
            id="memory-test",
            object="chat.completion",
            created=1234567890,
            model="gpt-4",
            choices=[
                OpenAIChoice(
                    index=0,
                    message=OpenAIResponseMessage(
                        role="assistant",
                        content="y" * 50000,  # 50KB response
                        tool_calls=[
                            {
                                "id": f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": f"tool_{i}",
                                    "arguments": json.dumps(
                                        {"param1": "a" * 1000, "param2": str(i), "param3": str(i % 2 == 0)}
                                    ),
                                },
                            }
                            for i in range(50)  # 50 tool calls
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=OpenAIUsage(prompt_tokens=1000, completion_tokens=2000, total_tokens=3000),
        )

        # Perform translation
        result = translate_openai_to_anthropic_non_stream(large_response, large_request)

        # Check memory usage
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        # Assert memory requirements
        assert memory_increase < 100  # Less than 100MB increase

        print(f"Initial memory: {initial_memory:.2f} MB")
        print(f"Final memory: {final_memory:.2f} MB")
        print(f"Memory increase: {memory_increase:.2f} MB")

    def test_schema_validation_performance(self):
        """Benchmark schema validation performance."""
        from claude_code_proxy.models_anthropic import AnthropicRequest

        # Test various schema sizes
        schema_sizes = [1, 10, 50, 100]

        for size in schema_sizes:
            tools = [
                {
                    "name": f"tool_{i}",
                    "description": f"Tool {i}",
                    "input_schema": {
                        "type": "object",
                        "properties": {f"param_{j}": {"type": "string"} for j in range(10)},
                        "required": [f"param_{j}" for j in range(5)],
                    },
                }
                for i in range(size)
            ]

            request_data = {
                "model": "claude-3-sonnet",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": "test"}],
                "tools": tools,
            }

            # Benchmark validation
            times = []
            for _ in range(50):
                start = time.perf_counter()
                request = AnthropicRequest(**request_data)
                end = time.perf_counter()
                times.append(end - start)

            avg_time = sum(times) / len(times)

            # Assert validation performance
            assert avg_time < 0.1  # 100ms per validation

            print(f"Schema validation for {size} tools: {avg_time:.4f}s average")


class TestLoadBenchmarks:
    """Load testing benchmarks."""

    @pytest.mark.asyncio
    async def test_sustained_load_benchmark(self):
        """Test sustained load over time."""
        with TestClient(app) as client:
            with patch("claude_code_proxy.server.provider_router") as mock_router:
                # Setup mock
                mock_provider = MagicMock()
                mock_provider.timeout = 30.0
                mock_router.get_provider_by_key.return_value = mock_provider
                mock_router.get_target_model.return_value = "gpt-4"

                mock_client = AsyncMock()
                mock_response = AsyncMock()
                mock_response.json.return_value = {
                    "id": "load-test",
                    "choices": [{"message": {"content": "Load test response"}}],
                }
                mock_response.raise_for_status.return_value = None
                mock_client.post.return_value = mock_response
                mock_router.get_client.return_value = mock_client

                # Sustained load for 30 seconds
                request_data = {
                    "model": "claude-3-sonnet",
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": "Load test"}],
                }

                start = time.perf_counter()
                success_count = 0

                import concurrent.futures

                def make_request():
                    nonlocal success_count
                    response = client.post("/v1/messages", json=request_data)
                    if response.status_code == 200:
                        success_count += 1
                    return response

                # Run requests for 30 seconds
                end_time = start + 30
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = []
                    while time.perf_counter() < end_time:
                        futures.append(executor.submit(make_request))
                        if len(futures) >= 100:
                            concurrent.futures.wait(futures, timeout=1)
                            futures = []

                    # Wait for remaining
                    if futures:
                        concurrent.futures.wait(futures)

                total_time = time.perf_counter() - start
                success_rate = success_count / (success_count + len(futures))

                # Assert load test requirements
                assert success_rate > 0.95  # 95% success rate
                assert success_count > 100  # At least 100 successful requests

                print(f"Sustained load: {success_count} requests in {total_time:.2f}s")
                print(f"Success rate: {success_rate:.2%}")
                print(f"Average rate: {success_count / total_time:.2f} requests/second")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
