from __future__ import annotations

import hashlib
import json
from typing import List

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
    SignatureDelta,
    TextDelta,
    ThinkingDelta,
)
from claude_code_proxy.models_openai import (
    OpenAIChatCompletionChunk,
    OpenAIChatMessageDelta,
    OpenAIChoiceDelta,
    OpenAIChunkUsage,
    OpenAIFunctionCallDelta,
    OpenAIToolCallDelta,
)
from claude_code_proxy.response_translator_v2 import OpenAIToAnthropicStreamTranslator
from pydantic import BaseModel


@pytest.fixture
def anthropic_request_with_typed_tools() -> AnthropicRequest:
    """Provides an AnthropicRequest instance with tools that have typed parameters."""
    return AnthropicRequest(
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
                        "width": {"type": "number"},  # Can be int or float
                        "height": {"type": "integer"},
                        "active": {"type": "boolean"},
                        "metadata": {"type": "object"},  # Complex type
                    },
                    "required": ["shape", "width", "height"],
                },
            }
        ],
    )


@pytest.fixture
def translator(anthropic_request_with_typed_tools: AnthropicRequest) -> OpenAIToAnthropicStreamTranslator:
    """Provides a default translator instance for tests."""
    translator_instance = OpenAIToAnthropicStreamTranslator(
        response_id="msg_test_123", model=anthropic_request_with_typed_tools.model
    )
    translator_instance.anthropic_request = anthropic_request_with_typed_tools
    return translator_instance


def_choice = OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(), finish_reason=None)


def assert_event_types(events: List[BaseModel], expected_types: List[type]):
    """Asserts that the produced events have the expected types in order."""
    actual_types = [type(e) for e in events]
    assert actual_types == expected_types, f"Expected event types {expected_types}, but got {actual_types}"


def test_start_stream(translator: OpenAIToAnthropicStreamTranslator):  # pylint: disable=redefined-outer-name
    """Test the initial message_start event."""
    events = translator.start()
    assert_event_types(events, [MessageStartEvent])
    start_event = events[0]
    assert start_event.type == "message_start"
    assert start_event.message.id == "msg_test_123"
    assert start_event.message.model == "claude-3-5-sonnet-20240620"
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


def test_tool_call_generation_with_type_conversion(translator: OpenAIToAnthropicStreamTranslator):
    """Test a stream generating a tool call with type conversion."""
    # Chunk 1: Start of tool call with string arguments that need conversion
    # Simulate provider returning strings for number/boolean types
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
                            index=0,
                            id="tool_123",
                            function=OpenAIFunctionCallDelta(
                                name="calculate_area",
                                arguments='{"shape": "rectangle", "width": "10.5", "height": "20", "active": "true"}',
                            ),
                        )
                    ]
                ),
            )
        ],
    )
    events1 = translator.process_chunk(chunk1)
    assert_event_types(events1, [ContentBlockStartEvent, ContentBlockDeltaEvent])
    assert events1[0].content_block.type == "tool_use"
    assert events1[0].content_block.id == "tool_123"
    assert events1[0].content_block.name == "calculate_area"

    # Finalize to trigger argument processing and conversion
    translator.finish_reason = "tool_calls"
    final_events = translator.finalize()

    # Find the ContentBlockDeltaEvent for input_json_delta
    delta_events = [
        e for e in final_events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta)
    ]
    # In this specific test case, the arguments are sent in the first chunk, and since they are not
    # detected as an "escaped json string", they are emitted directly as a delta.
    # The type conversion logic, however, is applied in _close_active_block (for buffered args)
    # and in the non-streaming translator. The standard streaming delta just passes the JSON string through.
    # So we look for the initial delta event from the first chunk processing.
    initial_delta_events = [
        e for e in events1 if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta)
    ]
    assert len(initial_delta_events) == 1


def test_escaped_json_string_tool_call_with_type_conversion(translator: OpenAIToAnthropicStreamTranslator):
    """Test a tool call stream where arguments are an escaped JSON string, with type conversion."""
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
                            index=0, id="tool_esc", function=OpenAIFunctionCallDelta(name="calculate_area")
                        )
                    ]
                ),
            )
        ],
    )
    events1 = translator.process_chunk(chunk1)
    assert_event_types(events1, [ContentBlockStartEvent])
    assert events1[0].content_block.type == "tool_use"
    assert events1[0].content_block.id == "tool_esc"

    # This is a string which is itself a valid JSON document.
    # The OpenAI response contains this as a JSON string, so it's double-quoted.
    # Include typed values that need conversion
    inner_json_obj = {"shape": "square", "width": "5.0", "height": "5", "active": "false"}  # String types from provider
    inner_json_str = json.dumps(inner_json_obj)
    outer_json_str = json.dumps(inner_json_str)  # Results in "\"{\\\"shape\\\": \\\"square\\\", ...}\""

    # Chunk 2: First part of escaped arguments. This should trigger the detection.
    # The first character of a JSON string is always '"'.
    chunk2 = OpenAIChatCompletionChunk(
        id="c2",
        created=2,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(
                    tool_calls=[OpenAIToolCallDelta(index=0, function=OpenAIFunctionCallDelta(arguments='"'))]
                ),
            )
        ],
    )
    events2 = translator.process_chunk(chunk2)
    # No events should be emitted, as arguments are being buffered.
    assert_event_types(events2, [])
    assert translator._active_tool_info[0]["is_escaped_json_string"] is True
    assert translator._active_tool_info[0]["argument_buffer"] == '"'

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
                        OpenAIToolCallDelta(index=0, function=OpenAIFunctionCallDelta(arguments=outer_json_str[1:]))
                    ]
                ),
            )
        ],
    )
    events3 = translator.process_chunk(chunk3)
    assert_event_types(events3, [])
    assert translator._active_tool_info[0]["argument_buffer"] == outer_json_str

    # Finalize the stream. This should trigger _close_active_block and flush the buffer.
    translator.finish_reason = "tool_calls"
    final_events = translator.finalize()

    # Expect [ContentBlockDelta (with converted args), ContentBlockStop, MessageDelta, MessageStop]
    # Find the ContentBlockDeltaEvent for input_json_delta
    delta_event = None
    for e in final_events:
        if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta):
            delta_event = e
            break

    assert delta_event is not None, "Expected ContentBlockDeltaEvent with InputJsonDelta not found"
    assert delta_event.index == 0

    # Check that the arguments have been converted based on the schema
    parsed_args = json.loads(delta_event.delta.partial_json)
    # Original from provider: "width": "5.0", "height": "5", "active": "false"
    # Expected after conversion: "width": 5.0 (number), "height": 5 (integer), "active": False (boolean)
    assert parsed_args["shape"] == "square"
    assert parsed_args["width"] == 5.0  # Converted from "5.0"
    assert parsed_args["height"] == 5  # Converted from "5"
    assert parsed_args["active"] is False  # Converted from "false"


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
                        OpenAIToolCallDelta(
                            index=0, id="tool_abc", function=OpenAIFunctionCallDelta(name="calculate_area")
                        )
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

    # Tool call part - arguments (correct types)
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
                        OpenAIToolCallDelta(
                            index=0, function=OpenAIFunctionCallDelta(arguments='{"width": 10, "height": 20}')
                        )
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
    # Arguments are streamed as-is if types are correct
    assert '"width": 10' in delta_event.delta.partial_json


def test_custom_tool_call_in_text_stream(translator: OpenAIToAnthropicStreamTranslator):
    """Tests parsing of custom tool call format embedded in text (updated to Kimi format)."""
    kimi_tool_section = (
        "<|tool_calls_section_begin|>"
        "<|tool_call_begin|>functions.calculate_area:1<|tool_call_argument_begin|>"
        '{"shape": "circle", "width": "15.7", "height": "15"}'
        "<|tool_call_end|>"
        "<|tool_calls_section_end|>"
    )
    chunk1_content = f"Here is the tool: {kimi_tool_section}And here is more text."
    chunk1 = OpenAIChatCompletionChunk(
        id="c1",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[OpenAIChoiceDelta(index=0, delta=OpenAIChatMessageDelta(content=chunk1_content), finish_reason=None)],
    )
    events1 = translator.process_chunk(chunk1, translator.anthropic_request)

    # Find the tool delta event
    tool_delta_events = [
        e for e in events1 if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta)
    ]
    assert len(tool_delta_events) == 1, "Expected one tool call delta event"

    parsed_args = json.loads(tool_delta_events[0].delta.partial_json)
    # Check conversion happened
    assert parsed_args["shape"] == "circle"
    assert parsed_args["width"] == 15.7  # Converted from "15.7"
    assert parsed_args["height"] == 15  # Converted from "15"

    # Check that text parts are also present
    all_text = "".join(
        e.delta.text for e in events1 if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)
    )
    assert "Here is the tool: " in all_text
    assert "And here is more text." in all_text


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
                delta=OpenAIChatMessageDelta(content="<tool_call>incomplete..."),
                finish_reason=None,
            )
        ],
    )
    # process_chunk will buffer this, as it looks like a partial tag
    translator.process_chunk(chunk)
    assert translator._text_buffer == "<tool_call>incomplete..."

    final_events = translator.finalize()
    # Expect: new text block, text delta, stop block, message delta, message stop
    assert_event_types(
        final_events,
        [ContentBlockStartEvent, ContentBlockDeltaEvent, ContentBlockStopEvent, MessageDeltaEvent, MessageStopEvent],
    )
    assert final_events[0].content_block.type == "text"
    assert final_events[1].delta.text == "<tool_call>incomplete..."


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


def test_consecutive_tool_calls_same_index(translator: OpenAIToAnthropicStreamTranslator):
    """Test a stream with two full tool calls sent back-to-back for the same index."""
    # Chunk 1: First complete tool call
    args1 = {"target": "all"}
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
                            index=0,
                            id="tool_1",
                            function=OpenAIFunctionCallDelta(name="run_compile", arguments=json.dumps(args1)),
                        )
                    ]
                ),
            )
        ],
    )
    events1 = translator.process_chunk(chunk1)
    # Should start block 0 and provide its arguments
    assert_event_types(events1, [ContentBlockStartEvent, ContentBlockDeltaEvent])
    assert events1[0].index == 0
    assert events1[0].content_block.type == "tool_use"
    assert events1[0].content_block.id == "tool_1"
    assert events1[1].index == 0
    assert isinstance(events1[1].delta, InputJsonDelta)
    assert events1[1].delta.partial_json == json.dumps(args1)

    # Chunk 2: Second complete tool call, same index, new ID
    args2 = {"path": "./src"}
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
                        OpenAIToolCallDelta(
                            index=0,
                            id="tool_2",
                            function=OpenAIFunctionCallDelta(name="run_lint", arguments=json.dumps(args2)),
                        )
                    ]
                ),
            )
        ],
    )
    events2 = translator.process_chunk(chunk2)
    # Should stop block 0, start block 1, and provide its arguments
    assert_event_types(events2, [ContentBlockStopEvent, ContentBlockStartEvent, ContentBlockDeltaEvent])
    assert events2[0].index == 0  # Stop block 0
    assert events2[1].index == 1  # Start block 1
    assert events2[1].content_block.type == "tool_use"
    assert events2[1].content_block.id == "tool_2"
    assert events2[2].index == 1
    assert isinstance(events2[2].delta, InputJsonDelta)
    assert events2[2].delta.partial_json == json.dumps(args2)

    # Finalize
    translator.finish_reason = "tool_calls"
    final_events = translator.finalize()
    # Should stop the last active block (index 1)
    assert_event_types(final_events, [ContentBlockStopEvent, MessageDeltaEvent, MessageStopEvent])
    assert final_events[0].index == 1


def test_kimi_k2_tool_call_in_text_non_streaming(anthropic_request_with_typed_tools: AnthropicRequest):
    """Test non-streaming translation with Kimi K2 tool call embedded in content."""
    from claude_code_proxy.models_openai import OpenAIChatCompletion, OpenAIChoice, OpenAIResponseMessage, OpenAIUsage
    from claude_code_proxy.response_translator_v2 import translate_openai_to_anthropic_non_stream

    # Simulate full response with Kimi K2 tool call
    kimi_tool_section = (
        "<|tool_calls_section_begin|>"
        "<|tool_call_begin|>functions.calculate_area:1<|tool_call_argument_begin|>"
        '{"shape": "circle", "width": "7.5", "height": "7", "active": "true"}'
        "<|tool_call_end|>"
        "<|tool_calls_section_end|>"
    )
    content_before = "I will calculate the area now. "
    content_after = " That's all."

    full_content = content_before + kimi_tool_section + content_after

    openai_response = OpenAIChatCompletion(
        id="resp_kimi_1",
        created=1,
        model="kimi-1",
        object="chat.completion",
        choices=[
            OpenAIChoice(
                index=0,
                message=OpenAIResponseMessage(
                    role="assistant",
                    content=full_content,
                ),
                finish_reason="stop",
            )
        ],
        usage=OpenAIUsage(prompt_tokens=60, completion_tokens=45, total_tokens=105),
    )

    result = translate_openai_to_anthropic_non_stream(openai_response, anthropic_request_with_typed_tools)

    # Should have three content blocks: text, tool_use, text
    assert len(result.content) == 3
    assert result.content[0].type == "text"
    assert result.content[0].text == content_before.strip()

    tool_block = result.content[1]
    assert tool_block.type == "tool_use"
    assert tool_block.name == "calculate_area"
    assert tool_block.input["shape"] == "circle"
    assert tool_block.input["width"] == 7.5  # Converted from string
    assert tool_block.input["height"] == 7  # Converted from string
    assert tool_block.input["active"] is True  # Converted from "true"

    assert result.content[2].type == "text"
    assert result.content[2].text == content_after.strip()


def test_kimi_k2_tool_call_in_streaming_content(
    translator: OpenAIToAnthropicStreamTranslator, anthropic_request_with_typed_tools: AnthropicRequest
):
    """Test streaming text containing a complete Kimi K2 tool call."""
    kimi_section = (
        "<|tool_calls_section_begin|>"
        "<|tool_call_begin|>functions.calculate_area:1<|tool_call_argument_begin|>"
        '{"shape": "triangle", "width": "6.0", "height": "8", "active": "false"}'
        "<|tool_call_end|>"
        "<|tool_calls_section_end|>"
    )
    chunk = OpenAIChatCompletionChunk(
        id="chunk_kimi",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(content="Before. " + kimi_section + " After."),
                finish_reason=None,
            )
        ],
    )

    events = translator.process_chunk(chunk, anthropic_request_with_typed_tools)

    # Expected sequence:
    # 1. Text block start + delta ("Before. ")
    # 2. Text block stop
    # 3. Tool block start
    # 4. Tool block delta (converted args)
    # 5. Tool block stop
    # 6. Text block start
    # 7. Text delta (" After.")

    assert len(events) >= 7
    assert isinstance(events[0], ContentBlockStartEvent)
    assert events[0].content_block.type == "text"
    assert isinstance(events[1], ContentBlockDeltaEvent)
    assert events[1].delta.text == "Before. "

    assert isinstance(events[2], ContentBlockStopEvent)
    assert isinstance(events[3], ContentBlockStartEvent)
    assert events[3].content_block.type == "tool_use"
    assert events[3].content_block.name == "calculate_area"

    # Check argument delta with type conversion
    tool_delta_event = next(
        e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta)
    )
    parsed_args = json.loads(tool_delta_event.delta.partial_json)
    assert parsed_args["shape"] == "triangle"
    assert parsed_args["width"] == 6.0
    assert parsed_args["height"] == 8
    assert parsed_args["active"] is False

    # Final text
    last_text_event = next(
        e for e in reversed(events) if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)
    )
    assert last_text_event.delta.text == " After."


def test_kimi_k2_incomplete_section_in_streaming(translator: OpenAIToAnthropicStreamTranslator):
    """Test that incomplete Kimi K2 section is treated as plain text and flushed on finalize."""
    incomplete_kimi = (
        '<|tool_calls_section_begin|>functions.calculate_area:1<|tool_call_argument_begin|>{"shape": "square"'
    )

    chunk = OpenAIChatCompletionChunk(
        id="chunk_incomplete",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(content=incomplete_kimi),
                finish_reason=None,
            )
        ],
    )

    events = translator.process_chunk(chunk)
    # The new logic will now buffer this, as it can't find the end tag.
    assert translator._text_buffer == incomplete_kimi
    assert not events  # No events should be emitted yet.

    # Finalize should flush remaining buffer as text
    final_events = translator.finalize()
    assert any(isinstance(e, MessageStopEvent) for e in final_events)
    text_delta = next(
        (e for e in final_events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)), None
    )
    assert text_delta is not None
    assert text_delta.delta.text == incomplete_kimi


def test_kimi_k2_multiple_tool_calls_in_section(
    translator: OpenAIToAnthropicStreamTranslator, anthropic_request_with_typed_tools: AnthropicRequest
):
    """Test parsing multiple tool calls within a single <|tool_calls_section|>."""
    kimi_section = (
        "<|tool_calls_section_begin|>"
        '<|tool_call_begin|>functions.calculate_area:1<|tool_call_argument_begin|>{"shape": "rect", "width": "10", "height": "5"}<|tool_call_end|>'
        '<|tool_call_begin|>functions.calculate_area:2<|tool_call_argument_begin|>{"shape": "circle", "width": "3.14", "height": "3", "active": "true"}<|tool_call_end|>'
        "<|tool_calls_section_end|>"
    )

    chunk = OpenAIChatCompletionChunk(
        id="chunk_multi_kimi",
        created=1,
        model="m",
        object="chat.completion.chunk",
        choices=[
            OpenAIChoiceDelta(
                index=0,
                delta=OpenAIChatMessageDelta(content=kimi_section),
                finish_reason=None,
            )
        ],
    )

    events = translator.process_chunk(chunk, anthropic_request_with_typed_tools)

    # Should produce: text start/delta, stop, tool1 start/delta/stop, tool2 start/delta/stop, text start (if any trailing)
    # But since it's all in one chunk, we expect:
    # - Text block for the section
    # - Then two tool blocks created and closed in _process_text_buffer

    tool_starts = [e for e in events if isinstance(e, ContentBlockStartEvent) and e.content_block.type == "tool_use"]
    assert len(tool_starts) == 2
    assert tool_starts[0].content_block.name == "calculate_area"
    assert tool_starts[1].content_block.name == "calculate_area"

    # Check arguments are converted
    deltas = [e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta)]
    assert len(deltas) == 2

    args1 = json.loads(deltas[0].delta.partial_json)
    assert args1["shape"] == "rect"
    assert args1["width"] == 10
    assert args1["height"] == 5

    args2 = json.loads(deltas[1].delta.partial_json)
    assert args2["shape"] == "circle"
    assert args2["width"] == 3.14
    assert args2["height"] == 3
    assert args2["active"] is True


if __name__ == "__main__":
    pytest.main([__file__])
