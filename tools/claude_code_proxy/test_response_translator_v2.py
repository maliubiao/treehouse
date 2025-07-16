from __future__ import annotations

import hashlib
import json
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
    assert len(events) == len(expected_types), (
        f"Expected {len(expected_types)} events, but got {len(events)}: {[type(e) for e in events]}"
    )
    for i, (event, expected_type) in enumerate(zip(events, expected_types)):
        assert isinstance(event, expected_type), f"Event {i} was {type(event)}, expected {expected_type}"


def test_start_stream(translator: OpenAIToAnthropicStreamTranslator):  # pylint: disable=redefined-outer-name
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


def test_escaped_json_string_tool_call(translator: OpenAIToAnthropicStreamTranslator):
    """Test a tool call stream where arguments are an escaped JSON string."""
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
                        OpenAIToolCallDelta(index=0, id="tool_esc", function=OpenAIFunctionCallDelta(name="search"))
                    ]
                ),
            )
        ],
    )
    events1 = translator.process_chunk(chunk1)
    assert_event_types(events1, [ContentBlockStartEvent])
    assert events1[0].content_block.type == "tool_use"
    assert events1[0].content_block.id == "tool_esc"

    whole = json.dumps(json.dumps({"query": ""}))
    # Chunk 2: First part of escaped arguments. This should trigger the detection.
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
                        OpenAIToolCallDelta(index=0, function=OpenAIFunctionCallDelta(arguments=whole[:2])),
                    ]
                ),
            )
        ],
    )
    events2 = translator.process_chunk(chunk2)
    # No events should be emitted, as arguments are being buffered.
    assert_event_types(events2, [])
    assert translator._active_tool_info[0]["is_escaped_json_string"] is True
    assert translator._active_tool_info[0]["argument_buffer"] == whole[:2]

    # Chunk 3: Second part of escaped arguments.
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
                        OpenAIToolCallDelta(index=0, function=OpenAIFunctionCallDelta(arguments=whole[2:])),
                    ]
                ),
            )
        ],
    )
    events3 = translator.process_chunk(chunk3)
    assert_event_types(events3, [])
    assert translator._active_tool_info[0]["argument_buffer"] == whole

    # Finalize the stream. This should trigger _close_active_block and flush the buffer.
    translator.finish_reason = "tool_calls"
    final_events = translator.finalize()

    # Expect [ContentBlockDelta, ContentBlockStop, MessageDelta, MessageStop]
    assert_event_types(
        final_events, [ContentBlockDeltaEvent, ContentBlockStopEvent, MessageDeltaEvent, MessageStopEvent]
    )

    # Check the flushed delta event
    delta_event = final_events[0]
    assert isinstance(delta_event, ContentBlockDeltaEvent)
    assert delta_event.index == 0
    assert isinstance(delta_event.delta, InputJsonDelta)
    assert delta_event.delta.partial_json == json.dumps({"query": ""})


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
    """Test a stream with text followed by a standard tool call, including arguments."""
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
    assert translator._active_block_index == 0

    # Tool call part - name and id
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
    # Should close the text block (index 0) and start a tool_use block (index 1)
    assert_event_types(tool_events, [ContentBlockStopEvent, ContentBlockStartEvent])
    assert tool_events[0].index == 0
    assert tool_events[1].index == 1
    assert tool_events[1].content_block.type == "tool_use"
    assert translator._active_block_type == "tool_use"
    assert translator._active_block_index == 1

    # Tool call part - arguments
    args_chunk = OpenAIChatCompletionChunk(
        id="c3",
        created=3,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(
                    tool_calls=[
                        OpenAIToolCallDelta(index=0, function=OpenAIFunctionCallDelta(arguments='{"file": "a.py"}'))
                    ]
                ),
            )
        ],
    )
    args_events = translator.process_chunk(args_chunk)
    # This should succeed and produce a delta for block 1
    assert_event_types(args_events, [ContentBlockDeltaEvent])
    delta_event = args_events[0]
    assert delta_event.index == 1  # Check it's for the correct (tool) block
    assert isinstance(delta_event.delta, InputJsonDelta)
    assert delta_event.delta.partial_json == '{"file": "a.py"}'


def test_custom_tool_call_in_text_stream(translator: OpenAIToAnthropicStreamTranslator):
    """Tests parsing of custom tool call format embedded in text."""
    # Chunk 1: Text before and start of custom tool call
    chunk1_content = 'Here is the tool: |tool_call_begin|>functions.MyTool:1<|tool_call_argument_begin|>{"arg":'
    chunk1 = OpenAIChatCompletionChunk(
        id="c1",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(content=chunk1_content), finish_reason=None)],
    )
    events1 = translator.process_chunk(chunk1)
    # Emits text part immediately, buffers the partial tool call
    assert_event_types(events1, [ContentBlockStartEvent, ContentBlockDeltaEvent])
    assert events1[1].delta.text == "Here is the tool: "
    assert translator._text_buffer == '|tool_call_begin|>functions.MyTool:1<|tool_call_argument_begin|>{"arg":'

    # Chunk 2: End of custom tool call and more text
    chunk2_content = ' "value"}<|tool_call_end|>And here is more text.'
    chunk2 = OpenAIChatCompletionChunk(
        id="c2",
        created=2,
        model="m",
        object="chat.completion.chunk",
        choices=[OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(content=chunk2_content), finish_reason=None)],
    )
    events2 = translator.process_chunk(chunk2)
    # Text block stop, tool start, tool delta, tool stop, text start, text delta
    assert_event_types(
        events2,
        [
            ContentBlockStopEvent,
            ContentBlockStartEvent,
            ContentBlockDeltaEvent,
            ContentBlockStopEvent,
            ContentBlockStartEvent,
            ContentBlockDeltaEvent,
        ],
    )
    # Tool block events
    assert events2[1].content_block.type == "tool_use"
    assert events2[1].content_block.id == "custom_tool_1"
    assert events2[1].content_block.name == "MyTool"
    assert isinstance(events2[2].delta, InputJsonDelta)
    assert events2[2].delta.partial_json == '{"arg": "value"}'
    # Final text block events
    assert events2[4].content_block.type == "text"
    assert events2[5].delta.text == "And here is more text."
    assert translator._text_buffer == ""


def test_finalize_with_incomplete_custom_tool_call(translator: OpenAIToAnthropicStreamTranslator):
    """Tests that an incomplete custom tool tag is flushed as text on finalization."""
    chunk = OpenAIChatCompletionChunk(
        id="c1",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(content="|tool_call_begin|>incomplete..."),
                finish_reason=None,
            )
        ],
    )
    # process_chunk will buffer this, as it looks like a partial tag
    translator.process_chunk(chunk)
    assert translator._text_buffer == "|tool_call_begin|>incomplete..."

    final_events = translator.finalize()
    # Expect: new text block, text delta, stop block, message delta, message stop
    assert_event_types(
        final_events,
        [ContentBlockStartEvent, ContentBlockDeltaEvent, ContentBlockStopEvent, MessageDeltaEvent, MessageStopEvent],
    )
    assert final_events[0].content_block.type == "text"
    assert final_events[1].delta.text == "|tool_call_begin|>incomplete..."


def test_usage_reporting(translator: OpenAIToAnthropicStreamTranslator):
    """Test that usage information is correctly captured and reported, handling cumulative updates."""
    # First chunk with initial usage, potentially zero completion tokens
    usage_chunk1 = OpenAIChatCompletionChunk(
        id="c_usage1",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[def_choice],
        usage=OpenAIChunkUsage(prompt_tokens=50, completion_tokens=0, total_tokens=50),
    )
    translator.process_chunk(usage_chunk1)
    assert translator.input_tokens == 50
    assert translator.output_tokens == 0

    # Second chunk with updated usage
    usage_chunk2 = OpenAIChatCompletionChunk(
        id="c_usage2",
        created=2,
        model="m",
        object="chat.completion.chunk",
        choices=[def_choice],
        usage=OpenAIChunkUsage(prompt_tokens=50, completion_tokens=100, total_tokens=150),
    )
    translator.process_chunk(usage_chunk2)
    assert translator.input_tokens == 50
    assert translator.output_tokens == 100

    translator.finish_reason = "stop"
    final_events = translator.finalize()

    # The translator might produce a ContentBlockStopEvent first if a block was open.
    # We need to find the MessageDeltaEvent.
    message_delta_event = next((e for e in final_events if isinstance(e, MessageDeltaEvent)), None)

    assert message_delta_event is not None, "MessageDeltaEvent not found in final events"
    assert message_delta_event.usage.input_tokens == 50
    assert message_delta_event.usage.output_tokens == 100


if __name__ == "__main__":
    pytest.main([__file__])
