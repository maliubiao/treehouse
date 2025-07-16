from __future__ import annotations

import hashlib
from typing import List

import pytest
from pydantic import BaseModel

from .models_anthropic import (
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputJsonDelta,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    SignatureDelta,
    TextDelta,
    ThinkingDelta,
)
from .models_openai import (
    OpenAIChatCompletionChunk,
    OpenAIChatMessageDelta,
    OpenAIChoiceDelta,
    OpenAIChunkUsage,
    OpenAIFunctionCallDelta,
    OpenAIToolCallDelta,
)
from .response_translator_v2 import OpenAIToAnthropicStreamTranslator


@pytest.fixture
def translator() -> OpenAIToAnthropicStreamTranslator:
    """Provides a default translator instance for tests."""
    return OpenAIToAnthropicStreamTranslator(response_id="msg_test_123", model="claude-test-model")


def_choice = OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(), finish_reason=None)


def assert_event_types(events: List[BaseModel], expected_types: List[type]):
    """Asserts that the produced events have the expected types in order."""
    assert len(events) == len(expected_types), f"Expected {len(expected_types)} events, but got {len(events)}"
    for i, (event, expected_type) in enumerate(zip(events, expected_types)):
        assert isinstance(event, expected_type), f"Event {i} was {type(event)}, expected {expected_type}"


def test_start_stream(translator: OpenAIToAnthropicStreamTranslator):
    """Test the initial message_start event."""
    events = translator.start()
    assert_event_types(events, [MessageStartEvent])
    start_event = events[0]
    assert start_event.type == "message_start"
    assert start_event.message.id == "msg_test_123"
    assert start_event.message.model == "claude-test-model"
    assert start_event.message.usage.input_tokens == 0


def test_simple_text_generation(translator: OpenAIToAnthropicStreamTranslator):
    """Test a simple stream of text content."""
    # First chunk
    chunk1 = OpenAIChatCompletionChunk(
        id="chunk1",
        choices=[OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(content="Hello,"), finish_reason=None)],
        created=1,
        model="m",
        object="chat.completion.chunk",
    )
    events1 = translator.process_chunk(chunk1)
    assert_event_types(events1, [ContentBlockStartEvent, ContentBlockDeltaEvent])
    assert events1[0].content_block.type == "text"
    assert events1[1].delta.text == "Hello,"

    # Second chunk
    chunk2 = OpenAIChatCompletionChunk(
        id="chunk2",
        choices=[OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(content=" world!"), finish_reason=None)],
        created=2,
        model="m",
        object="chat.completion.chunk",
    )
    events2 = translator.process_chunk(chunk2)
    assert_event_types(events2, [ContentBlockDeltaEvent])
    assert events2[0].delta.text == " world!"

    # Finalize
    translator.finish_reason = "stop"
    final_events = translator.finalize()
    assert_event_types(final_events, [ContentBlockStopEvent, MessageDeltaEvent, MessageStopEvent])
    assert final_events[1].delta.stop_reason == "end_turn"


def test_tool_call_generation(translator: OpenAIToAnthropicStreamTranslator):
    """Test a stream generating a tool call."""
    # Chunk 1: Start of tool call
    chunk1 = OpenAIChatCompletionChunk(
        id="c1",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(
                    tool_calls=[
                        OpenAIToolCallDelta(
                            index=0, id="tool_123", function=OpenAIFunctionCallDelta(name="get_weather")
                        )
                    ]
                ),
            )
        ],
    )
    events1 = translator.process_chunk(chunk1)
    assert_event_types(events1, [ContentBlockStartEvent])
    assert events1[0].content_block.type == "tool_use"
    assert events1[0].content_block.id == "tool_123"
    assert events1[0].content_block.name == "get_weather"

    # Chunk 2: Arguments part 1
    chunk2 = OpenAIChatCompletionChunk(
        id="c2",
        created=2,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(
                    tool_calls=[
                        OpenAIToolCallDelta(index=0, function=OpenAIFunctionCallDelta(arguments='{"location": "S'))
                    ]
                ),
            )
        ],
    )
    events2 = translator.process_chunk(chunk2)
    assert_event_types(events2, [ContentBlockDeltaEvent])
    assert isinstance(events2[0].delta, InputJsonDelta)
    assert events2[0].delta.partial_json == '{"location": "S'

    # Chunk 3: Arguments part 2
    chunk3 = OpenAIChatCompletionChunk(
        id="c3",
        created=3,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(
                    tool_calls=[
                        OpenAIToolCallDelta(index=0, function=OpenAIFunctionCallDelta(arguments='an Francisco"}'))
                    ]
                ),
            )
        ],
    )
    events3 = translator.process_chunk(chunk3)
    assert_event_types(events3, [ContentBlockDeltaEvent])
    assert events3[0].delta.partial_json == 'an Francisco"}'

    # Finalize
    translator.finish_reason = "tool_calls"
    final_events = translator.finalize()
    assert_event_types(final_events, [ContentBlockStopEvent, MessageDeltaEvent, MessageStopEvent])
    assert final_events[1].delta.stop_reason == "tool_use"


def test_thinking_generation(translator: OpenAIToAnthropicStreamTranslator):
    """Test a stream generating thinking content, including the signature."""
    # Chunk 1: Thinking part 1
    chunk1 = OpenAIChatCompletionChunk(
        id="c1",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(reasoning_content="Step 1:"), finish_reason=None)
        ],
    )
    events1 = translator.process_chunk(chunk1)
    assert_event_types(events1, [ContentBlockStartEvent, ContentBlockDeltaEvent])
    assert events1[0].content_block.type == "thinking"
    assert isinstance(events1[1].delta, ThinkingDelta)
    assert events1[1].delta.thinking == "Step 1:"

    # Chunk 2: Thinking part 2
    chunk2 = OpenAIChatCompletionChunk(
        id="c2",
        created=2,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(reasoning_content=" Analyze."), finish_reason=None)
        ],
    )
    events2 = translator.process_chunk(chunk2)
    assert_event_types(events2, [ContentBlockDeltaEvent])
    assert isinstance(events2[0].delta, ThinkingDelta)
    assert events2[0].delta.thinking == " Analyze."

    # Finalize should trigger signature delta and stop event
    translator.finish_reason = "stop"
    final_events = translator.finalize()

    # The finalize() method first closes the active block, then adds message delta/stop.
    assert_event_types(
        final_events, [ContentBlockDeltaEvent, ContentBlockStopEvent, MessageDeltaEvent, MessageStopEvent]
    )

    # Check Signature Delta
    sig_delta_event = final_events[0]
    assert isinstance(sig_delta_event.delta, SignatureDelta)
    expected_content = "Step 1: Analyze."
    expected_signature = hashlib.sha256(expected_content.encode()).hexdigest()
    assert sig_delta_event.delta.signature == expected_signature

    # Check Block Stop
    assert final_events[1].type == "content_block_stop"
    assert final_events[1].index == 0

    # Check Message Delta
    assert final_events[2].delta.stop_reason == "end_turn"


def test_interleaved_content(translator: OpenAIToAnthropicStreamTranslator):
    """Test a stream with text followed by a tool call."""
    # Text part
    text_chunk = OpenAIChatCompletionChunk(
        id="c1",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(content="Thinking... "))],
    )
    text_events = translator.process_chunk(text_chunk)
    assert_event_types(text_events, [ContentBlockStartEvent, ContentBlockDeltaEvent])
    assert text_events[0].content_block.type == "text"
    assert translator._active_block_type == "text"

    # Tool call part
    tool_chunk = OpenAIChatCompletionChunk(
        id="c2",
        created=2,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(
                    tool_calls=[
                        OpenAIToolCallDelta(index=0, id="tool_abc", function=OpenAIFunctionCallDelta(name="run_code"))
                    ]
                ),
            )
        ],
    )
    tool_events = translator.process_chunk(tool_chunk)
    # Should close the text block and start a tool_use block
    assert_event_types(tool_events, [ContentBlockStopEvent, ContentBlockStartEvent])
    assert tool_events[1].content_block.type == "tool_use"
    assert translator._active_block_type == "tool_use"
    assert translator._active_block_index == 1  # Block index should have incremented


def test_usage_reporting(translator: OpenAIToAnthropicStreamTranslator):
    """Test that usage information is correctly captured and reported."""
    usage_chunk = OpenAIChatCompletionChunk(
        id="c_usage",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[def_choice],
        usage=OpenAIChunkUsage(prompt_tokens=50, completion_tokens=100, total_tokens=150),
    )

    translator.process_chunk(usage_chunk)
    assert translator.usage_handled is True
    assert translator.input_tokens == 50
    assert translator.output_tokens == 100

    translator.finish_reason = "stop"
    final_events = translator.finalize()

    # The translator might produce a ContentBlockStopEvent first if a block was open.
    # We need to find the MessageDeltaEvent.
    message_delta_event = None
    for event in final_events:
        if isinstance(event, MessageDeltaEvent):
            message_delta_event = event
            break

    assert message_delta_event is not None, "MessageDeltaEvent not found in final events"
    assert message_delta_event.usage.input_tokens == 50
    assert message_delta_event.usage.output_tokens == 100


if __name__ == "__main__":
    pytest.main([__file__])
