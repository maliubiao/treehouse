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
from .qwen3coder_tool_parser import Qwen3CoderToolParser

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

        self._next_block_index: int = 0
        self._active_block_type: Optional[Literal["text", "thinking", "tool_use"]] = None
        self._active_block_index: Optional[int] = None
        self._active_block_content: str = ""
        self._active_tool_info: Dict[int, Dict[str, Any]] = {}
        self._active_tool_chunk_index: Optional[int] = None
        self._text_buffer: str = ""

        # Qwen3 Coder tool parser
        self.qwen3_parser = Qwen3CoderToolParser()
        self.anthropic_request: AnthropicRequest

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

        # Handle buffered arguments for escaped JSON string tool calls
        if self._active_block_type == "tool_use" and self._active_tool_chunk_index is not None:
            tool_state = self._active_tool_info.get(self._active_tool_chunk_index)
            if tool_state and tool_state.get("is_escaped_json_string"):
                buffer = tool_state["argument_buffer"]
                if buffer:
                    try:
                        # The buffer contains a JSON string which itself contains stringified JSON.
                        # e.g., "\"{\\\"key\\\": \\\"value\\\"}\""
                        # We need to load it once to get the inner stringified JSON.
                        if buffer.startswith('"'):
                            unquoted_json_text = json.loads(buffer)
                        else:
                            unquoted_json_text = buffer
                        tool_args = json.loads(unquoted_json_text)
                        tool_args = _validate_and_convert_tool_arguments(
                            tool_state["name"], tool_args, self.anthropic_request
                        )
                        unquoted_json_text = json.dumps(tool_args)

                        events.append(
                            ContentBlockDeltaEvent(
                                type="content_block_delta",
                                index=self._active_block_index,
                                delta=InputJsonDelta(type="input_json_delta", partial_json=unquoted_json_text),
                            )
                        )
                    except Exception as e:
                        logger.warning(
                            f"Could not unescape buffered tool arguments for tool {self._active_block_index}: {e}. Buffer: '{buffer}'"
                        )
                # This tool index is now complete, remove its state.
                self._active_tool_info.pop(self._active_tool_chunk_index, None)

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
        self._active_tool_chunk_index = None
        return events

    def _start_new_block(
        self,
        block_type: Literal["text", "thinking", "tool_use"],
        tool_info: Optional[Dict[str, Any]] = None,
        tool_chunk_index: Optional[int] = None,
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
            self._active_tool_chunk_index = tool_chunk_index
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

    def _process_text_buffer(self, anthropic_request: Optional[AnthropicRequest] = None) -> List[BaseModel]:
        """
        Processes the internal text buffer, handling plain text and custom
        embedded tool calls.
        """
        events: List[BaseModel] = []
        start_tags = ["|tool_call_begin|>", "|tool_calls_section_begin|>", "<tool_call>"]
        end_tag = "<|tool_call_end|>"
        arg_split_tag = "<|tool_call_argument_begin|>"
        qwen3_end_tag = "</tool_call>"

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
            end_index = -1
            if found_start_tag == "<tool_call>":
                # Handle Qwen3 Coder format
                end_index = self._text_buffer.find(qwen3_end_tag, first_start_index)
            else:
                # Handle existing custom format
                end_index = self._text_buffer.find(end_tag, first_start_index)

            if end_index == -1:
                # Incomplete tag, leave it in the buffer and wait for more data.
                self._text_buffer = self._text_buffer[first_start_index:]
                break

            # A complete tag is found.
            full_tag_string = ""
            inner_content = ""
            if found_start_tag == "<tool_call>":
                full_tag_string = self._text_buffer[first_start_index : end_index + len(qwen3_end_tag)]
                inner_content = self._text_buffer[first_start_index + len(found_start_tag) : end_index]
            else:
                full_tag_string = self._text_buffer[first_start_index : end_index + len(end_tag)]
                inner_content = self._text_buffer[first_start_index + len(found_start_tag) : end_index]

            tool_call_parsed = False
            try:
                # Try to parse as Qwen3 Coder format first
                if found_start_tag == "<tool_call>" and anthropic_request:
                    # Use Qwen3 parser for this format
                    extracted_info = self.qwen3_parser.extract_tool_calls(full_tag_string, anthropic_request)
                    if extracted_info.tools_called and extracted_info.tool_calls:
                        # Close active text block, then create the full tool block
                        events.extend(self._close_active_block())
                        tool_call = extracted_info.tool_calls[0]
                        tool_info = {
                            "id": tool_call.id or f"custom_tool_{hash(full_tag_string)}",
                            "name": tool_call.function.name,
                        }
                        events.extend(self._start_new_block("tool_use", tool_info=tool_info))

                        if self._active_block_index is not None:
                            # self._active_tool_info is for standard tool calls, but let's be safe
                            self._active_tool_info[self._active_block_index] = tool_info
                            events.append(
                                ContentBlockDeltaEvent(
                                    type="content_block_delta",
                                    index=self._active_block_index,
                                    delta=InputJsonDelta(
                                        type="input_json_delta", partial_json=tool_call.function.arguments
                                    ),
                                )
                            )
                        events.extend(self._close_active_block())
                        tool_call_parsed = True
                elif found_start_tag != "<tool_call>":
                    # Handle existing custom format
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

            self._text_buffer = self._text_buffer[
                end_index + len(qwen3_end_tag if found_start_tag == "<tool_call>" else end_tag) :
            ]
        return events

    def process_chunk(
        self, chunk: OpenAIChatCompletionChunk, anthropic_request: Optional[AnthropicRequest] = None
    ) -> List[BaseModel]:
        """Processes a single OpenAI chunk and returns a list of Anthropic events."""
        events: List[BaseModel] = []

        # Always update token counts if usage is present, as it's often cumulative.
        if chunk.usage:
            if chunk.usage.prompt_tokens is not None:
                self.input_tokens = chunk.usage.prompt_tokens
            if chunk.usage.completion_tokens is not None:
                self.output_tokens = chunk.usage.completion_tokens

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

        if delta.tool_calls:
            for tc_chunk in delta.tool_calls:
                tool_index = tc_chunk.index

                # A new tool call is definitively declared if it has an `id` and `function.name`.
                # This signals the need to start a new tool block.
                if tc_chunk.id and tc_chunk.function and tc_chunk.function.name:
                    # This is a new tool declaration. _start_new_block will close any prior block.
                    tool_info = {
                        "id": tc_chunk.id,
                        "name": tc_chunk.function.name,
                        "argument_buffer": "",
                        "is_escaped_json_string": None,
                    }
                    self._active_tool_info[tool_index] = tool_info
                    events.extend(self._start_new_block("tool_use", tool_info=tool_info, tool_chunk_index=tool_index))

                # Arguments may be present in the same chunk as the declaration, or a subsequent one.
                if tc_chunk.function and tc_chunk.function.arguments:
                    # Check if we are in a valid state to receive arguments for this tool index.
                    if self._active_block_type != "tool_use" or self._active_tool_chunk_index != tool_index:
                        logger.warning(
                            f"Received tool arguments for tool {tool_index} but the active block is type '{self._active_block_type}' for tool index '{self._active_tool_chunk_index}'. This may indicate an unsupported interleaved stream. Ignoring."
                        )
                        continue

                    if tool_index not in self._active_tool_info:
                        logger.warning(
                            f"Received tool arguments for tool {tool_index} before its declaration. Ignoring."
                        )
                        continue

                    tool_state = self._active_tool_info[tool_index]
                    args = tc_chunk.function.arguments

                    # First time seeing args for this tool? Detect if it's an escaped stream.
                    if tool_state.get("is_escaped_json_string") is None and args:
                        # Heuristic: if arguments stream starts with a quote, it's likely an escaped JSON string.
                        # tool_state["is_escaped_json_string"] = args.startswith('"')
                        tool_state["is_escaped_json_string"] = True

                    if tool_state.get("is_escaped_json_string"):
                        tool_state["argument_buffer"] += args
                        # Don't emit delta, just buffer. It will be flushed when the block closes.
                    else:
                        # Standard, non-escaped JSON stream.
                        events.append(
                            ContentBlockDeltaEvent(
                                type="content_block_delta",
                                index=self._active_block_index,
                                delta=InputJsonDelta(
                                    type="input_json_delta",
                                    partial_json=args,
                                ),
                            )
                        )

        # Handle Text Content (including custom embedded tool calls)
        if delta.content:
            # If we receive text content, it must close any open tool calls
            if self._active_block_type == "tool_use":
                events.extend(self._close_active_block())
            self._text_buffer += delta.content
            events.extend(self._process_text_buffer(anthropic_request))

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
            print(data_str)
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
    translator.anthropic_request = anthropic_request
    # 1. Yield start event
    for event_model in translator.start():
        yield _format_sse(event_model)

    # 2. Process the stream chunk by chunk
    async for openai_chunk in _parse_openai_sse_stream(openai_stream):
        print(openai_chunk)
        anthropic_events = translator.process_chunk(openai_chunk, anthropic_request)
        for event_model in anthropic_events:
            event = _format_sse(event_model)
            print(event)
            yield event

    # 3. Yield finalization events
    for event_model in translator.finalize():
        event = _format_sse(event_model)
        print(event)
        yield event


def translate_openai_to_anthropic_non_stream(
    openai_response: OpenAIChatCompletion,
    anthropic_request: Optional[AnthropicRequest] = None,
) -> AnthropicMessageResponse:
    """Translates a non-streaming OpenAI ChatCompletion to an Anthropic Message."""
    message = openai_response.choices[0].message
    content: List[Any] = []

    if hasattr(message, "reasoning_content") and message.reasoning_content:
        content.append(AnthropicThinkingContent(type="thinking", thinking=message.reasoning_content))

    if message.content:
        # Here we must also parse for custom tool calls, even in non-streaming mode.
        text_buffer = message.content
        start_tags = ["|tool_call_begin|>", "|tool_calls_section_begin|>", "<tool_call>"]
        end_tag = "<|tool_call_end|>"
        arg_split_tag = "<|tool_call_argument_begin|>"
        qwen3_end_tag = "</tool_call>"
        qwen3_parser = Qwen3CoderToolParser()

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

            end_index = -1
            if found_start_tag == "<tool_call>":
                # Handle Qwen3 Coder format
                end_index = text_buffer.find(qwen3_end_tag, first_start_index)
            else:
                # Handle existing custom format
                end_index = text_buffer.find(end_tag, first_start_index)

            if end_index == -1:
                # Incomplete tag, treat as text
                content.append(AnthropicTextContent(type="text", text=text_buffer[first_start_index:]))
                break

            inner_content = ""
            if found_start_tag == "<tool_call>":
                inner_content = text_buffer[first_start_index + len(found_start_tag) : end_index]
            else:
                inner_content = text_buffer[first_start_index + len(found_start_tag) : end_index]

            try:
                # Try to parse as Qwen3 Coder format first
                if found_start_tag == "<tool_call>" and anthropic_request:
                    # Use Qwen3 parser for this format
                    extracted_info = qwen3_parser.extract_tool_calls(
                        text_buffer[first_start_index : end_index + len(qwen3_end_tag)], anthropic_request
                    )
                    if extracted_info.tools_called and extracted_info.tool_calls:
                        tool_call = extracted_info.tool_calls[0]
                        tool_arguments = json.loads(tool_call.function.arguments)
                        # 验证和转换工具参数
                        tool_arguments = _validate_and_convert_tool_arguments(
                            tool_call.function.name, tool_arguments, anthropic_request
                        )
                        content.append(
                            AnthropicToolUseContent(
                                type="tool_use",
                                id=tool_call.id or f"custom_tool_{hash(inner_content)}",
                                name=tool_call.function.name,
                                input=tool_arguments,
                            )
                        )
                    else:
                        # Fallback to text if parsing fails
                        content.append(
                            AnthropicTextContent(
                                type="text", text=text_buffer[first_start_index : end_index + len(qwen3_end_tag)]
                            )
                        )
                elif found_start_tag != "<tool_call>":
                    # Handle existing custom format
                    arg_split_index = inner_content.find(arg_split_tag)
                    header = inner_content[:arg_split_index]
                    args_json = inner_content[arg_split_index + len(arg_split_tag) :]
                    args = json.loads(args_json)
                    func_name_part, tool_id_str = header.rsplit(":", 1)
                    func_name = func_name_part.split(".")[-1] if "." in func_name_part else func_name_part
                    tool_id = f"custom_tool_{tool_id_str}"
                    content.append(AnthropicToolUseContent(type="tool_use", id=tool_id, name=func_name, input=args))
                else:
                    # Fallback to text if parsing fails
                    content.append(
                        AnthropicTextContent(
                            type="text",
                            text=text_buffer[
                                first_start_index : end_index
                                + len(qwen3_end_tag if found_start_tag == "<tool_call>" else end_tag)
                            ],
                        )
                    )
            except Exception:
                # Fallback to text if parsing fails
                content.append(
                    AnthropicTextContent(
                        type="text",
                        text=text_buffer[
                            first_start_index : end_index
                            + len(qwen3_end_tag if found_start_tag == "<tool_call>" else end_tag)
                        ],
                    )
                )

            text_buffer = text_buffer[end_index + len(qwen3_end_tag if found_start_tag == "<tool_call>" else end_tag) :]

    if message.tool_calls:
        for tool_call in message.tool_calls:
            try:
                # First, try to load as-is (standard case)
                tool_input = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                # If that fails, it might be the escaped string format
                try:
                    # e.g., arguments = "\"{\\\"key\\\": \\\"value\\\"}\""
                    # The arguments field is a JSON string, which contains another JSON string.
                    # We need to parse it once to get the inner string.
                    tool_input_str = json.loads(tool_call.function.arguments)
                    # Then parse the inner string to get the actual object.
                    tool_input = json.loads(tool_input_str)
                except (json.JSONDecodeError, TypeError, Exception) as e:
                    logger.warning(
                        f"Failed to decode tool call arguments in non-streaming mode: {e}. Raw args: {tool_call.function.arguments}"
                    )
                    tool_input = {"error": "Failed to decode arguments", "raw": tool_call.function.arguments}
            if anthropic_request:
                tool_input = _validate_and_convert_tool_arguments(
                    tool_call.function.name, tool_input, anthropic_request
                )
            content.append(
                AnthropicToolUseContent(
                    type="tool_use",
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=tool_input,
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


def _convert_param_value(param_value: Any, param_name: str, param_schema: dict, tool_name: str) -> Any:
    """Convert parameter value based on JSON schema type, supporting nested schemas."""
    if param_value is None:
        return None

    # Handle direct null string
    if isinstance(param_value, str) and param_value.lower() == "null":
        return None

    # Handle array type
    if param_schema.get("type") == "array":
        items_schema = param_schema.get("items", {})
        if isinstance(param_value, list):
            return [_convert_param_value(item, f"{param_name}[i]", items_schema, tool_name) for item in param_value]
        elif isinstance(param_value, str):
            try:
                parsed = json.loads(param_value)
                if isinstance(parsed, list):
                    return [_convert_param_value(item, f"{param_name}[i]", items_schema, tool_name) for item in parsed]
            except (json.JSONDecodeError, TypeError):
                pass

    # Handle object type
    if param_schema.get("type") == "object":
        properties = param_schema.get("properties", {})
        if isinstance(param_value, dict):
            converted = {}
            for key, value in param_value.items():
                sub_schema = properties.get(key, {})
                converted[key] = _convert_param_value(value, f"{param_name}.{key}", sub_schema, tool_name)
            return converted
        elif isinstance(param_value, str):
            try:
                parsed = json.loads(param_value)
                if isinstance(parsed, dict):
                    converted = {}
                    for key, value in parsed.items():
                        sub_schema = properties.get(key, {})
                        converted[key] = _convert_param_value(value, f"{param_name}.{key}", sub_schema, tool_name)
                    return converted
            except (json.JSONDecodeError, TypeError):
                pass

    # Handle oneOf/anyOf/allOf schemas
    for schema_key in ["oneOf", "anyOf", "allOf"]:
        if schema_key in param_schema:
            for sub_schema in param_schema[schema_key]:
                try:
                    return _convert_param_value(param_value, param_name, sub_schema, tool_name)
                except (ValueError, TypeError):
                    continue

    # Handle basic types
    param_type = param_schema.get("type", "string")

    try:
        if param_type == "number":
            if isinstance(param_value, (int, float)):
                return param_value
            try:
                return int(param_value)
            except ValueError:
                return float(param_value)
        elif param_type == "integer":
            if isinstance(param_value, int):
                return param_value
            return int(param_value)
        elif param_type == "boolean":
            if isinstance(param_value, bool):
                return param_value
            return str(param_value).lower() == "true"
        elif param_type == "string":
            return str(param_value)
        else:
            # For any other type, return as-is
            return param_value
    except (ValueError, TypeError):
        logger.warning(
            "Failed to convert parameter '%s' to type '%s' for tool '%s'. Keeping original value.",
            param_name,
            param_type,
            tool_name,
        )
        return param_value


def _get_tool_arguments_config(tool_name: str, anthropic_request: Optional[AnthropicRequest]) -> dict:
    """
    Retrieves the argument schema for a given tool name from the request tools.
    """
    if not anthropic_request or not anthropic_request.tools:
        return {}

    for tool in anthropic_request.tools:
        if tool.name == tool_name:
            if hasattr(tool, "input_schema") and isinstance(tool.input_schema, dict):
                return tool.input_schema
            # Fallback to original structure check
            elif hasattr(tool, "function"):
                if hasattr(tool.function, "parameters"):
                    params = tool.function.parameters
                    if isinstance(params, dict):
                        return params
            return {}

    logger.warning("Tool '%s' is not defined in the tools list.", tool_name)
    return {}


def _validate_and_convert_tool_arguments(
    tool_name: str, arguments: dict, anthropic_request: Optional[AnthropicRequest]
) -> dict:
    """
    Validates and converts tool arguments based on the tool schema.
    """
    if not anthropic_request:
        return arguments

    tool_schema = _get_tool_arguments_config(tool_name, anthropic_request)
    if not tool_schema:
        return arguments

    properties = tool_schema.get("properties", {})
    converted_arguments = {}

    for param_name, param_value in arguments.items():
        param_schema = properties.get(param_name, {})
        converted_arguments[param_name] = _convert_param_value(param_value, param_name, param_schema, tool_name)

    return converted_arguments
