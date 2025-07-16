from __future__ import annotations

import hashlib
import json
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

from pydantic import BaseModel

from .logger import get_logger
from .models_anthropic import (
    AnthropicMessageResponse,
    AnthropicRequest,
    AnthropicTextContent,
    AnthropicThinkingContent,
    AnthropicToolUseContent,
    ContentBlock,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputJsonDelta,
    MessageDelta,
    MessageDeltaEvent,
    MessageDeltaUsage,
    MessageStartEvent,
    MessageStopEvent,
    SignatureDelta,
    TextDelta,
    ThinkingDelta,
    Usage,
)
from .models_openai import OpenAIChatCompletion, OpenAIChatCompletionChunk

logger = get_logger("response_translator_v2")


def _format_sse(event: BaseModel) -> str:
    """Format Pydantic model into an SSE message string."""
    event_name_mapping = {
        "MessageStartEvent": "message_start",
        "ContentBlockStartEvent": "content_block_start",
        "ContentBlockDeltaEvent": "content_block_delta",
        "ContentBlockStopEvent": "content_block_stop",
        "MessageDeltaEvent": "message_delta",
        "MessageStopEvent": "message_stop",
    }
    event_name = event_name_mapping.get(event.__class__.__name__, "message_stop")
    json_data = event.model_dump_json(exclude_none=True)
    return f"event: {event_name}\ndata: {json_data}\n\n"


class OpenAIToAnthropicStreamTranslator:
    """
    A synchronous, stateful translator for converting a stream of OpenAI Chunks
    into Anthropic-compliant SSE events.

    This class encapsulates the complex state management of the translation process,
    making it easy to test and reason about. It processes one OpenAI chunk at a
    time and produces a list of corresponding Anthropic event models.
    """

    def __init__(self, *, response_id: str, model: str):
        self.response_id = response_id
        self.model = model

        # State
        self.output_tokens: int = 0
        # self.input_tokens will be set when the first usage data is received from the stream.
        # We initialize to 0 for the initial message_start event, as it's a required field.
        self.input_tokens: int = 0
        self.cache_creation_input_tokens: Optional[int] = None
        self.cache_read_input_tokens: Optional[int] = None
        self.finish_reason: Optional[str] = None
        self.usage_handled: bool = False

        self._next_block_index: int = 0
        self._active_block_type: Optional[Literal["text", "thinking", "tool_use"]] = None
        self._active_block_index: Optional[int] = None
        self._active_block_content: str = ""
        self._active_tool_info: Dict[int, Dict[str, Any]] = {}
        self._text_buffer: str = ""

    def start(self) -> List[BaseModel]:
        """Generates the initial message_start event."""
        return [
            MessageStartEvent(
                type="message_start",
                message=AnthropicMessageResponse(
                    id=self.response_id,
                    type="message",
                    role="assistant",
                    model=self.model,
                    content=[],
                    usage=Usage(
                        input_tokens=self.input_tokens,
                        output_tokens=0,
                    ),
                ),
            )
        ]

    def _close_active_block(self) -> List[BaseModel]:
        """Generates events to close the currently active content block."""
        events: List[BaseModel] = []
        if self._active_block_index is None:
            return events

        if self._active_block_type == "thinking":
            signature = hashlib.sha256(self._active_block_content.encode()).hexdigest()
            events.append(
                ContentBlockDeltaEvent(
                    type="content_block_delta",
                    index=self._active_block_index,
                    delta=SignatureDelta(type="signature_delta", signature=signature),
                )
            )

        events.append(ContentBlockStopEvent(type="content_block_stop", index=self._active_block_index))
        self._active_block_type = None
        self._active_block_index = None
        self._active_block_content = ""
        return events

    def _start_new_block(
        self,
        block_type: Literal["text", "thinking", "tool_use"],
        tool_info: Optional[Dict[str, Any]] = None,
    ) -> List[BaseModel]:
        """Starts a new content block, closing any previous one."""
        events = self._close_active_block()
        self._active_block_type = block_type
        self._active_block_index = self._next_block_index
        self._next_block_index += 1

        content_block: ContentBlock
        if block_type == "text":
            content_block = ContentBlock(type="text", text="")
        elif block_type == "thinking":
            content_block = ContentBlock(type="thinking", thinking="")
        elif block_type == "tool_use" and tool_info:
            content_block = ContentBlock(type="tool_use", id=tool_info["id"], name=tool_info["name"], input={})
        else:
            # This should ideally not be reached with proper logic
            raise ValueError(f"Cannot start invalid block type: {block_type}")

        events.append(
            ContentBlockStartEvent(
                type="content_block_start",
                index=self._active_block_index,
                content_block=content_block,
            )
        )
        return events

    def _process_text_buffer(self) -> List[BaseModel]:
        """
        Processes the internal text buffer, handling plain text and custom
        embedded tool calls.
        """
        events: List[BaseModel] = []
        start_tags = ["|tool_call_begin|>", "|tool_calls_section_begin|>"]
        end_tag = "<|tool_call_end|>"
        arg_split_tag = "<|tool_call_argument_begin|>"

        while True:
            # Find the earliest occurrence of any start tag
            first_start_index = -1
            found_start_tag = None
            for tag in start_tags:
                index = self._text_buffer.find(tag)
                if index != -1 and (first_start_index == -1 or index < first_start_index):
                    first_start_index = index
                    found_start_tag = tag

            if first_start_index == -1:
                # No more custom tool calls found, process remaining buffer as plain text.
                if self._text_buffer:
                    if self._active_block_type != "text":
                        events.extend(self._start_new_block("text"))
                    self._active_block_content += self._text_buffer
                    if self._active_block_index is not None:
                        events.append(
                            ContentBlockDeltaEvent(
                                type="content_block_delta",
                                index=self._active_block_index,
                                delta=TextDelta(type="text_delta", text=self._text_buffer),
                            )
                        )
                    self._text_buffer = ""
                break  # Exit loop

            # Process text before the custom tool call tag.
            text_before = self._text_buffer[:first_start_index]
            if text_before:
                if self._active_block_type != "text":
                    events.extend(self._start_new_block("text"))
                self._active_block_content += text_before
                if self._active_block_index is not None:
                    events.append(
                        ContentBlockDeltaEvent(
                            type="content_block_delta",
                            index=self._active_block_index,
                            delta=TextDelta(type="text_delta", text=text_before),
                        )
                    )

            # Check for a complete custom tool call tag.
            end_index = self._text_buffer.find(end_tag, first_start_index)
            if end_index == -1:
                # Incomplete tag, leave it in the buffer and wait for more data.
                self._text_buffer = self._text_buffer[first_start_index:]
                break

            # A complete tag is found.
            assert found_start_tag is not None
            full_tag_string = self._text_buffer[first_start_index : end_index + len(end_tag)]
            inner_content = self._text_buffer[first_start_index + len(found_start_tag) : end_index]

            tool_call_parsed = False
            try:
                arg_split_index = inner_content.find(arg_split_tag)
                if arg_split_index != -1:
                    header = inner_content[:arg_split_index]
                    args_json = inner_content[arg_split_index + len(arg_split_tag) :]

                    func_name_part, tool_id_str = header.rsplit(":", 1)
                    func_name = func_name_part.split(".")[-1] if "." in func_name_part else func_name_part
                    tool_id = f"custom_tool_{tool_id_str}"

                    # Close active text block, then create the full tool block
                    events.extend(self._close_active_block())
                    tool_info = {"id": tool_id, "name": func_name}
                    events.extend(self._start_new_block("tool_use", tool_info=tool_info))

                    if self._active_block_index is not None:
                        # self._active_tool_info is for standard tool calls, but let's be safe
                        self._active_tool_info[self._active_block_index] = tool_info
                        events.append(
                            ContentBlockDeltaEvent(
                                type="content_block_delta",
                                index=self._active_block_index,
                                delta=InputJsonDelta(type="input_json_delta", partial_json=args_json),
                            )
                        )
                    events.extend(self._close_active_block())
                    tool_call_parsed = True
            except Exception as e:
                logger.warning(f"Could not parse custom tool call: '{inner_content}'. Error: {e}. Treating as text.")

            if not tool_call_parsed:
                if self._active_block_type != "text":
                    events.extend(self._start_new_block("text"))
                self._active_block_content += full_tag_string
                if self._active_block_index is not None:
                    events.append(
                        ContentBlockDeltaEvent(
                            type="content_block_delta",
                            index=self._active_block_index,
                            delta=TextDelta(type="text_delta", text=full_tag_string),
                        )
                    )

            self._text_buffer = self._text_buffer[end_index + len(end_tag) :]
        return events

    def process_chunk(self, chunk: OpenAIChatCompletionChunk) -> List[BaseModel]:
        """Processes a single OpenAI chunk and returns a list of Anthropic events."""
        events: List[BaseModel] = []

        if chunk.usage and not self.usage_handled:
            self.output_tokens = chunk.usage.completion_tokens or 0
            self.input_tokens = chunk.usage.prompt_tokens or 0
            self.usage_handled = True

        if not chunk.choices:
            return []

        choice = chunk.choices[0]
        if choice.finish_reason:
            self.finish_reason = choice.finish_reason

        delta = choice.delta
        if not delta:
            return []

        # Handle Reasoning Content (Custom Field)
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            if self._active_block_type != "thinking":
                events.extend(self._start_new_block("thinking"))
            self._active_block_content += delta.reasoning_content
            if self._active_block_index is not None:
                events.append(
                    ContentBlockDeltaEvent(
                        type="content_block_delta",
                        index=self._active_block_index,
                        delta=ThinkingDelta(type="thinking_delta", thinking=delta.reasoning_content),
                    )
                )

        # Handle Standard Tool Calls
        if delta.tool_calls:
            # A standard tool call implies any previous block should be closed.
            if self._active_block_type is not None and self._active_block_type != "tool_use":
                events.extend(self._close_active_block())

            for tc_chunk in delta.tool_calls:
                tool_index = tc_chunk.index
                # Is this the start of a new tool call?
                if self._active_tool_info.get(tool_index) is None:
                    if tc_chunk.id and tc_chunk.function and tc_chunk.function.name:
                        tool_info = {"id": tc_chunk.id, "name": tc_chunk.function.name}
                        self._active_tool_info[tool_index] = tool_info
                        events.extend(self._start_new_block("tool_use", tool_info=tool_info))

                if tc_chunk.function and tc_chunk.function.arguments:
                    if self._active_block_type != "tool_use":
                        # This can happen if a new tool call arrives but we are in text/thinking.
                        # The block was already closed above, so we might need to find the right one.
                        # For now, we assume sequential, non-interleaved standard tool calls.
                        logger.warning("Received tool arguments for non-active tool block.")
                        continue
                    if self._active_block_index is not None:
                        events.append(
                            ContentBlockDeltaEvent(
                                type="content_block_delta",
                                index=self._active_block_index,
                                delta=InputJsonDelta(
                                    type="input_json_delta",
                                    partial_json=tc_chunk.function.arguments,
                                ),
                            )
                        )

        # Handle Text Content (including custom embedded tool calls)
        if delta.content:
            # If we receive text content, it must close any open tool calls
            if self._active_block_type == "tool_use":
                events.extend(self._close_active_block())
            self._text_buffer += delta.content
            events.extend(self._process_text_buffer())

        return events

    def finalize(self) -> List[BaseModel]:
        """Generates the final events to properly close the stream."""
        events: List[BaseModel] = []
        # If stream ends with data in buffer (e.g., incomplete custom tag), flush as text.
        if self._text_buffer:
            logger.warning(f"Flushing text buffer with unprocessed content at end of stream: '{self._text_buffer}'")
            if self._active_block_type != "text":
                events.extend(self._start_new_block("text"))
            if self._active_block_index is not None:
                events.append(
                    ContentBlockDeltaEvent(
                        type="content_block_delta",
                        index=self._active_block_index,
                        delta=TextDelta(type="text_delta", text=self._text_buffer),
                    )
                )
            self._active_block_content += self._text_buffer
            self._text_buffer = ""

        events.extend(self._close_active_block())

        stop_reason_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
        final_reason = stop_reason_map.get(self.finish_reason or "", "end_turn")

        # Anthropic's "tool_use" is for when the model's turn ends with one or more tool_use blocks.
        if self._next_block_index > 0:  # if any blocks were created
            last_block_was_tool = any(
                isinstance(e, ContentBlockStartEvent) and e.content_block.type == "tool_use" for e in reversed(events)
            )
            if last_block_was_tool and final_reason != "max_tokens":
                final_reason = "tool_use"

        if self.finish_reason == "tool_calls":
            final_reason = "tool_use"

        events.append(
            MessageDeltaEvent(
                type="message_delta",
                delta=MessageDelta(stop_reason=final_reason),
                usage=MessageDeltaUsage(
                    output_tokens=self.output_tokens,
                    input_tokens=self.input_tokens,
                    cache_creation_input_tokens=self.cache_creation_input_tokens,
                    cache_read_input_tokens=self.cache_read_input_tokens,
                ),
            )
        )
        events.append(MessageStopEvent(type="message_stop"))
        return events


async def _parse_openai_sse_stream(
    stream: AsyncGenerator[bytes, None],
) -> AsyncGenerator[OpenAIChatCompletionChunk, None]:
    """Parses an SSE byte stream, yielding validated OpenAIChatCompletionChunk models."""
    buffer = ""
    async for byte_chunk in stream:
        buffer += byte_chunk.decode("utf-8")
        while "\n\n" in buffer:
            message, buffer = buffer.split("\n\n", 1)
            data_str = ""
            for line in message.splitlines():
                if line.startswith("data:"):
                    data_str = line[len("data:") :].strip()

            if not data_str:
                continue
            if data_str == "[DONE]":
                return

            try:
                yield OpenAIChatCompletionChunk.model_validate_json(data_str)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse SSE chunk: {e}", extra={"chunk": data_str})


async def translate_openai_to_anthropic_stream(
    openai_stream: AsyncGenerator[bytes, None],
    anthropic_request: AnthropicRequest,
    response_id: str,
) -> AsyncGenerator[str, None]:
    """
    Translates an OpenAI streaming response to a compliant Anthropic SSE stream.
    This is a thin async wrapper around the synchronous OpenAIToAnthropicStreamTranslator.
    """
    translator = OpenAIToAnthropicStreamTranslator(response_id=response_id, model=anthropic_request.model)

    # 1. Yield start event
    for event_model in translator.start():
        yield _format_sse(event_model)

    # 2. Process the stream chunk by chunk
    async for openai_chunk in _parse_openai_sse_stream(openai_stream):
        anthropic_events = translator.process_chunk(openai_chunk)
        for event_model in anthropic_events:
            yield _format_sse(event_model)

    # 3. Yield finalization events
    for event_model in translator.finalize():
        yield _format_sse(event_model)


def translate_openai_to_anthropic_non_stream(
    openai_response: OpenAIChatCompletion,
) -> AnthropicMessageResponse:
    """Translates a non-streaming OpenAI ChatCompletion to an Anthropic Message."""
    message = openai_response.choices[0].message
    content: List[Any] = []

    if hasattr(message, "reasoning_content") and message.reasoning_content:
        content.append(AnthropicThinkingContent(type="thinking", thinking=message.reasoning_content))

    if message.content:
        # Here we must also parse for custom tool calls, even in non-streaming mode.
        text_buffer = message.content
        start_tags = ["|tool_call_begin|>", "|tool_calls_section_begin|>"]
        end_tag = "<|tool_call_end|>"
        arg_split_tag = "<|tool_call_argument_begin|>"

        while text_buffer:
            first_start_index = -1
            found_start_tag = None
            for tag in start_tags:
                index = text_buffer.find(tag)
                if index != -1 and (first_start_index == -1 or index < first_start_index):
                    first_start_index = index
                    found_start_tag = tag

            if first_start_index == -1:
                if text_buffer:
                    content.append(AnthropicTextContent(type="text", text=text_buffer))
                break

            text_before = text_buffer[:first_start_index]
            if text_before:
                content.append(AnthropicTextContent(type="text", text=text_before))

            end_index = text_buffer.find(end_tag, first_start_index)
            if end_index == -1:
                # Incomplete tag, treat as text
                content.append(AnthropicTextContent(type="text", text=text_buffer[first_start_index:]))
                break

            assert found_start_tag is not None
            inner_content = text_buffer[first_start_index + len(found_start_tag) : end_index]

            try:
                arg_split_index = inner_content.find(arg_split_tag)
                header = inner_content[:arg_split_index]
                args_json = inner_content[arg_split_index + len(arg_split_tag) :]
                args = json.loads(args_json)
                func_name_part, tool_id_str = header.rsplit(":", 1)
                func_name = func_name_part.split(".")[-1] if "." in func_name_part else func_name_part
                tool_id = f"custom_tool_{tool_id_str}"
                content.append(AnthropicToolUseContent(type="tool_use", id=tool_id, name=func_name, input=args))
            except Exception:
                # Fallback to text if parsing fails
                content.append(
                    AnthropicTextContent(type="text", text=text_buffer[first_start_index : end_index + len(end_tag)])
                )

            text_buffer = text_buffer[end_index + len(end_tag) :]

    if message.tool_calls:
        for tool_call in message.tool_calls:
            content.append(
                AnthropicToolUseContent(
                    type="tool_use",
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=json.loads(tool_call.function.arguments),
                )
            )

    usage = Usage(
        input_tokens=openai_response.usage.prompt_tokens,
        output_tokens=openai_response.usage.completion_tokens,
    )

    stop_reason_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
    stop_reason = stop_reason_map.get(openai_response.choices[0].finish_reason, "end_turn")

    return AnthropicMessageResponse(
        id=openai_response.id,
        type="message",
        role="assistant",
        model=openai_response.model,
        content=content,  # type: ignore
        stop_reason=stop_reason,
        usage=usage,
    )
