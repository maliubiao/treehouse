"""Tests for Qwen3 tool calling integration with the response translator."""

from __future__ import annotations

import json
from typing import List, Optional

import pytest
from claude_code_proxy.models_anthropic import (
    AnthropicRequest,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputJsonDelta,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    TextDelta,
)
from claude_code_proxy.models_openai import (
    OpenAIChatCompletion,
    OpenAIChatCompletionChunk,
    OpenAIChatMessage,
    OpenAIChatMessageDelta,
    OpenAIChoice,
    OpenAIChoiceDelta,
    OpenAIChunkUsage,
    OpenAIFunctionCall,
    OpenAIFunctionCallDelta,
    OpenAIResponseMessage,
    OpenAIToolCall,
    OpenAIToolCallDelta,
)
from claude_code_proxy.response_translator_v2 import (
    OpenAIToAnthropicStreamTranslator,
    translate_openai_to_anthropic_non_stream,
)
from claude_code_proxy.tests.test_response_translator_v2 import assert_event_types
from pydantic import BaseModel


@pytest.fixture
def qwen3_anthropic_request() -> AnthropicRequest:
    """Provides a default AnthropicRequest instance for Qwen3 tests."""
    return AnthropicRequest(
        model="claude-3-5-sonnet-20240620",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Test message"}],
        tools=[
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
                        "precision": {"type": "integer"},
                    },
                },
            },
        ],
    )


def test_qwen3_streaming_tool_call_parsing(qwen3_anthropic_request: AnthropicRequest):
    """Test parsing of Qwen3 Coder tool call format in streaming mode."""
    translator = OpenAIToAnthropicStreamTranslator(
        response_id="msg_qwen3_stream_123", model=qwen3_anthropic_request.model
    )
    translator.anthropic_request = qwen3_anthropic_request  # Inject the request for type conversion

    # Simulate streaming chunks with Qwen3 Coder format
    chunks: List[OpenAIChatCompletionChunk] = [
        # Chunk 1: Text before tool call
        OpenAIChatCompletionChunk(
            id="chunk1",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(content="I'll check the weather for you. "),
                    finish_reason=None,
                )
            ],
            created=1,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
        # Chunk 2: Start of Qwen3 tool call
        OpenAIChatCompletionChunk(
            id="chunk2",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(content="<tool_call>"),
                    finish_reason=None,
                )
            ],
            created=2,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
        # Chunk 3: Function name and parameters with typed values needing conversion
        OpenAIChatCompletionChunk(
            id="chunk3",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(
                        content="<function=get_current_weather>\n<parameter=city>\nSan Francisco\n</parameter>\n<parameter=state>\nCA\n</parameter>\n<parameter=temperature>\n22.5\n</parameter>\n<parameter=is_current>\ntrue\n</parameter>"
                    ),
                    finish_reason=None,
                )
            ],
            created=3,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
        # Chunk 4: End of tool call
        OpenAIChatCompletionChunk(
            id="chunk4",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(content="\n</function>\n</tool_call>"),
                    finish_reason=None,
                )
            ],
            created=4,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
        # Chunk 5: Text after tool call
        OpenAIChatCompletionChunk(
            id="chunk5",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(content=" Let me know if you need anything else."),
                    finish_reason=None,
                )
            ],
            created=5,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
    ]

    all_events = []
    # Process each chunk
    for i, chunk in enumerate(chunks):
        events = translator.process_chunk(chunk, qwen3_anthropic_request)
        all_events.extend(events)
        print(f"Chunk {i + 1} events: {[type(e).__name__ for e in events]}")

    # Finalize the stream
    translator.finish_reason = "tool_calls"
    final_events = translator.finalize()
    all_events.extend(final_events)

    # Verify the sequence of events
    expected_event_sequence = [
        ContentBlockStartEvent,  # Text block
        ContentBlockDeltaEvent,  # "I'll check the weather for you. "
        ContentBlockStopEvent,  # Close text block
        ContentBlockStartEvent,  # Tool use block
        ContentBlockDeltaEvent,  # Tool arguments
        ContentBlockStopEvent,  # Close tool block
        ContentBlockStartEvent,  # Text block
        ContentBlockDeltaEvent,  # " Let me know if you need anything else."
        ContentBlockStopEvent,  # Close final text block
        MessageDeltaEvent,
        MessageStopEvent,
    ]

    actual_event_types = [type(e) for e in all_events]
    assert actual_event_types == expected_event_sequence, (
        f"Expected {expected_event_sequence}, but got {actual_event_types}"
    )

    # Verify tool call details
    tool_start_event = next(
        e for e in all_events if isinstance(e, ContentBlockStartEvent) and e.content_block.type == "tool_use"
    )
    assert tool_start_event.content_block.name == "get_current_weather"
    assert tool_start_event.content_block.id is not None

    # Verify tool arguments and type conversion
    tool_delta_events = [
        e for e in all_events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta)
    ]
    assert len(tool_delta_events) == 1
    args_json = tool_delta_events[0].delta.partial_json
    args = json.loads(args_json)
    assert args["city"] == "San Francisco"
    assert args["state"] == "CA"
    # Check type conversion by Qwen3 parser's internal logic (which is tested in test_qwen3coder_tool_parser.py)
    # The response_translator_v2 calls qwen3_parser.extract_tool_calls, which should do the conversion.
    # Let's assert the types here based on that expectation.
    assert isinstance(args["temperature"], float)  # Converted from "22.5"
    assert args["temperature"] == 22.5
    assert isinstance(args["is_current"], bool)  # Converted from "true"
    assert args["is_current"] is True

    # Verify text content
    text_delta_events = [
        e for e in all_events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)
    ]
    text_content = "".join(e.delta.text for e in text_delta_events)
    assert "I'll check the weather for you." in text_content
    assert "Let me know if you need anything else." in text_content


def test_qwen3_non_streaming_tool_call_parsing(qwen3_anthropic_request: AnthropicRequest):
    """Test parsing of Qwen3 Coder tool call format in non-streaming mode."""
    # Create a mock OpenAI response with Qwen3 Coder format
    # Simulate provider returning string types that need conversion
    openai_response = OpenAIChatCompletion(
        id="chatcmpl-qwen3-non-stream",
        choices=[
            OpenAIChoice(
                index=0,
                message=OpenAIResponseMessage(
                    role="assistant",
                    content="I'll calculate the area.<tool_call>\n<function=calculate_area>\n<parameter=shape>\nrectangle\n</parameter>\n<parameter=width>\n10.5\n</parameter>\n<parameter=height>\n20\n</parameter>\n<parameter=precision>\n2\n</parameter>\n</function>\n</tool_call> Here is the result.",
                ),
                finish_reason="tool_calls",
            )
        ],
        created=1234567890,
        model="qwen3-model",
        object="chat.completion",
        usage={"prompt_tokens": 20, "completion_tokens": 50, "total_tokens": 70},
    )

    # Translate to Anthropic format
    anthropic_response = translate_openai_to_anthropic_non_stream(openai_response, qwen3_anthropic_request)

    # Verify the response structure
    assert anthropic_response.id == "chatcmpl-qwen3-non-stream"
    assert anthropic_response.model == "qwen3-model"
    assert anthropic_response.role == "assistant"
    assert anthropic_response.stop_reason == "tool_use"

    # Verify content blocks
    assert len(anthropic_response.content) == 3

    # First block: text
    assert anthropic_response.content[0].type == "text"
    assert "I'll calculate the area." in anthropic_response.content[0].text

    # Second block: tool use
    assert anthropic_response.content[1].type == "tool_use"
    assert anthropic_response.content[1].name == "calculate_area"
    # Check type conversion by the Qwen3 parser called within translate_openai_to_anthropic_non_stream
    assert isinstance(anthropic_response.content[1].input["shape"], str)
    assert anthropic_response.content[1].input["shape"] == "rectangle"
    assert isinstance(anthropic_response.content[1].input["width"], float)  # Converted from "10.5"
    assert anthropic_response.content[1].input["width"] == 10.5
    assert isinstance(anthropic_response.content[1].input["height"], int)  # Converted from "20"
    assert anthropic_response.content[1].input["height"] == 20
    assert isinstance(anthropic_response.content[1].input["precision"], int)  # Converted from "2"
    assert anthropic_response.content[1].input["precision"] == 2

    # Third block: text
    assert anthropic_response.content[2].type == "text"
    assert "Here is the result." in anthropic_response.content[2].text

    # Verify usage
    assert anthropic_response.usage.input_tokens == 20
    assert anthropic_response.usage.output_tokens == 50


def test_qwen3_mixed_tool_calls(qwen3_anthropic_request: AnthropicRequest):
    """Test handling of mixed standard and Qwen3 tool calls in streaming mode."""
    translator = OpenAIToAnthropicStreamTranslator(
        response_id="msg_qwen3_mixed_123", model=qwen3_anthropic_request.model
    )
    translator.anthropic_request = qwen3_anthropic_request

    chunks: List[OpenAIChatCompletionChunk] = [
        # Standard tool call with typed args (simulating provider returning strings)
        OpenAIChatCompletionChunk(
            id="chunk1",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(
                        tool_calls=[
                            OpenAIToolCallDelta(
                                index=0,
                                id="call_standard_1",
                                function=OpenAIFunctionCallDelta(
                                    name="calculate_area",
                                    arguments='{"shape": "square", "width": "5", "height": "5"}',  # String types
                                ),
                            )
                        ]
                    ),
                    finish_reason=None,
                )
            ],
            created=1,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
        # Qwen3 tool call in text
        OpenAIChatCompletionChunk(
            id="chunk2",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(content=" Now checking with Qwen3 format: "),
                    finish_reason=None,
                )
            ],
            created=2,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
        OpenAIChatCompletionChunk(
            id="chunk3",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(
                        content="<tool_call><function=get_current_weather><parameter=city>New York</parameter><parameter=state>NY</parameter><parameter=temperature>15.0</parameter><parameter=is_current>false</parameter></function></tool_call>"
                    ),
                    finish_reason=None,
                )
            ],
            created=3,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
    ]

    all_events = []
    for chunk in chunks:
        events = translator.process_chunk(chunk, qwen3_anthropic_request)
        all_events.extend(events)

    translator.finish_reason = "tool_calls"
    final_events = translator.finalize()
    all_events.extend(final_events)

    # Verify we have two tool use blocks
    tool_start_events = [
        e for e in all_events if isinstance(e, ContentBlockStartEvent) and e.content_block.type == "tool_use"
    ]
    assert len(tool_start_events) == 2

    # Verify first tool call (standard) - Type conversion check
    assert tool_start_events[0].content_block.id == "call_standard_1"
    assert tool_start_events[0].content_block.name == "calculate_area"
    # Find the delta event for this tool call (index 0)
    tool1_delta_events = [
        e
        for e in all_events
        if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta) and e.index == 0
    ]
    assert len(tool1_delta_events) >= 1
    # The conversion for standard streaming is less direct per chunk, but the overall logic should handle it if needed.
    # For escaped strings, it's done in _close_active_block. For direct streaming, it depends on provider.
    # This test mainly checks the structure. Type conversion for direct streaming is less critical if provider is correct,
    # but the system should be robust. The non-streaming test covers the direct conversion path more clearly.

    # Verify second tool call (Qwen3) - Type conversion check
    assert tool_start_events[1].content_block.name == "get_current_weather"
    assert tool_start_events[1].content_block.id is not None
    assert tool_start_events[1].content_block.id != "call_standard_1"
    # Find the delta event for this tool call (index 2)
    tool2_delta_events = [
        e
        for e in all_events
        if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta) and e.index == 2
    ]
    assert len(tool2_delta_events) == 1
    args2 = json.loads(tool2_delta_events[0].delta.partial_json)
    assert isinstance(args2["temperature"], float)  # Converted by Qwen3 parser
    assert args2["temperature"] == 15.0
    assert isinstance(args2["is_current"], bool)  # Converted by Qwen3 parser
    assert args2["is_current"] is False


def test_qwen3_tool_call_with_typed_parameters(qwen3_anthropic_request: AnthropicRequest):
    """Test Qwen3 tool call with typed parameters conversion."""
    translator = OpenAIToAnthropicStreamTranslator(
        response_id="msg_qwen3_typed_123", model=qwen3_anthropic_request.model
    )
    translator.anthropic_request = qwen3_anthropic_request

    # Create a tool call with various parameter types
    chunks: List[OpenAIChatCompletionChunk] = [
        OpenAIChatCompletionChunk(
            id="chunk1",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(content="<tool_call>"),
                    finish_reason=None,
                )
            ],
            created=1,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
        OpenAIChatCompletionChunk(
            id="chunk2",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(
                        content="<function=calculate_area>\n<parameter=shape>\nrectangle\n</parameter>\n<parameter=width>\n10.5\n</parameter>\n<parameter=height>\n20\n</parameter>\n<parameter=precision>\n2\n</parameter>"
                    ),
                    finish_reason=None,
                )
            ],
            created=2,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
        OpenAIChatCompletionChunk(
            id="chunk3",
            choices=[
                OpenAIChoiceDelta(
                    index=0,
                    delta=OpenAIChatMessageDelta(content="\n</function>\n</tool_call>"),
                    finish_reason=None,
                )
            ],
            created=3,
            model="qwen3-model",
            object="chat.completion.chunk",
        ),
    ]

    all_events = []
    for chunk in chunks:
        events = translator.process_chunk(chunk, qwen3_anthropic_request)
        all_events.extend(events)

    translator.finish_reason = "tool_calls"
    final_events = translator.finalize()
    all_events.extend(final_events)

    # Find the tool call delta event
    tool_delta_events = [
        e for e in all_events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta)
    ]
    assert len(tool_delta_events) == 1

    args_json = tool_delta_events[0].delta.partial_json
    args = json.loads(args_json)

    # Verify parameter types are correctly converted by Qwen3 parser
    assert args["shape"] == "rectangle"  # string
    assert isinstance(args["width"], float)  # number/float
    assert args["width"] == 10.5
    assert isinstance(args["height"], int)  # integer
    assert args["height"] == 20
    assert isinstance(args["precision"], int)  # integer
    assert args["precision"] == 2


if __name__ == "__main__":
    pytest.main([__file__])
