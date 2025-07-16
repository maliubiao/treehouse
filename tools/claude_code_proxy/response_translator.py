from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

import aiofiles
from pydantic import BaseModel

from .logger import SSEDebugLogger, get_logger
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
from .models_openai import OpenAIChatCompletion, OpenAIChatCompletionChunk, OpenAIToolCallDelta

logger = get_logger("response_translator")


async def _sse_parser(stream: AsyncGenerator[bytes, None]) -> AsyncGenerator[str, None]:
    """Robust SSE parser handling arbitrary data chunking."""
    buffer = b""
    async for chunk in stream:
        buffer += chunk
        while b"\n\n" in buffer:
            message, buffer = buffer.split(b"\n\n", 1)
            for line in message.splitlines():
                if line.startswith(b"data:"):
                    data_str = line[len(b"data:") :].strip()
                    if data_str:
                        yield data_str.decode("utf-8")


def _format_sse(event: BaseModel) -> str:
    """Format Pydantic model into SSE message string."""
    event_type_mapping = {
        "MessageStartEvent": "message_start",
        "ContentBlockStartEvent": "content_block_start",
        "ContentBlockDeltaEvent": "content_block_delta",
        "ContentBlockStopEvent": "content_block_stop",
        "MessageDeltaEvent": "message_delta",
        "MessageStopEvent": "message_stop",
    }
    event_name = event_type_mapping.get(event.__class__.__name__, "message_stop")
    json_data = event.model_dump_json(exclude_none=True)
    return f"event: {event_name}\ndata: {json_data}\n\n"


def _generate_signature(content: str) -> str:
    """Generate mock signature for thinking blocks (simulates Anthropic behavior)."""
    return hashlib.sha256(content.encode()).hexdigest()


def translate_openai_to_anthropic_non_stream(
    openai_response: OpenAIChatCompletion,
) -> AnthropicMessageResponse:
    """Translates non-streaming OpenAI ChatCompletion to Anthropic Message."""
    message = openai_response.choices[0].message
    content: List[Any] = []

    if hasattr(message, "reasoning_content") and message.reasoning_content:
        content.append(AnthropicThinkingContent(type="thinking", thinking=message.reasoning_content))

    if message.content:
        content.append(AnthropicTextContent(type="text", text=message.content))

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

    # 处理cache相关字段 - 从OpenAI的详细结构映射
    cache_creation_input_tokens = None
    cache_read_input_tokens = None

    # 从OpenAI新的token结构映射
    input_tokens = getattr(openai_response.usage, "input_tokens", openai_response.usage.prompt_tokens)
    output_tokens = getattr(openai_response.usage, "output_tokens", openai_response.usage.completion_tokens)

    # 处理OpenAI的cached_tokens
    if hasattr(openai_response.usage, "input_tokens_details") and openai_response.usage.input_tokens_details:
        details = openai_response.usage.input_tokens_details
        if hasattr(details, "cached_tokens"):
            cache_read_input_tokens = details.cached_tokens

    return AnthropicMessageResponse(
        id=openai_response.id,
        type="message",
        role="assistant",
        model=openai_response.model,
        content=content,
        stop_reason=openai_response.choices[0].finish_reason,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        ),
    )


def map_finish_reason(openai_finish_reason: Optional[str]) -> str:
    """Maps OpenAI finish_reason to Anthropic stop_reason."""
    return {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
    }.get(openai_finish_reason or "", "end_turn")


class BlockTracker:
    """Tracks state for a single content block."""

    def __init__(
        self,
        index: int,
        block_type: Literal["text", "thinking", "tool_use"],
        tool_info: Optional[Dict[str, Any]] = None,
    ):
        self.index: int = index
        self.block_type: Literal["text", "thinking", "tool_use"] = block_type
        self.content: str = ""
        self.tool_info: Optional[Dict[str, Any]] = tool_info
        self.openai_tool_index: Optional[int] = tool_info.get("openai_tool_index") if tool_info else None

    def update(self, delta: str) -> None:
        """Appends delta to block content."""
        self.content += delta


class StreamingState:
    """Manages streaming state with strict Anthropic event sequencing."""

    def __init__(self):
        self.output_tokens: int = 0
        self.input_tokens: int = 0
        self.cache_creation_input_tokens: Optional[int] = None
        self.cache_read_input_tokens: Optional[int] = None
        self.next_block_index: int = 0
        self.active_block: Optional[BlockTracker] = None
        self.tool_calls: Dict[int, Dict[str, Any]] = {}
        self.finish_reason: Optional[str] = None
        self.usage_handled: bool = False

    def close_active_block(self) -> List[str]:
        """Closes active block and returns SSE events."""
        events: List[str] = []
        if not self.active_block:
            return events

        # For thinking blocks: append signature before closing
        if self.active_block.block_type == "thinking":
            signature = _generate_signature(self.active_block.content)
            events.append(
                _format_sse(
                    ContentBlockDeltaEvent(
                        type="content_block_delta",
                        index=self.active_block.index,
                        delta=SignatureDelta(type="signature_delta", signature=signature),
                    )
                )
            )

        events.append(_format_sse(ContentBlockStopEvent(type="content_block_stop", index=self.active_block.index)))
        self.active_block = None
        return events

    def start_new_block(
        self,
        block_type: Literal["text", "thinking", "tool_use"],
        tool_info: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Starts new block, closing previous if needed. Returns SSE events."""
        events = self.close_active_block()
        self.active_block = BlockTracker(self.next_block_index, block_type, tool_info)
        self.next_block_index += 1

        content_block: ContentBlock
        if block_type == "text":
            content_block = ContentBlock(type="text", text="")
        elif block_type == "thinking":
            content_block = ContentBlock(type="thinking", thinking="")
        elif block_type == "tool_use" and tool_info:
            content_block = ContentBlock(type="tool_use", id=tool_info["id"], name=tool_info["name"], input={})
        else:
            raise ValueError(f"Invalid block type: {block_type}")

        events.append(
            _format_sse(
                ContentBlockStartEvent(
                    type="content_block_start",
                    index=self.active_block.index,
                    content_block=content_block,
                )
            )
        )
        return events

    def finalize(
        self,
        input_tokens: int = 0,
        output_tokens: int = None,
        cache_creation_input_tokens: Optional[int] = None,
        cache_read_input_tokens: Optional[int] = None,
    ) -> List[str]:
        """Generates final events to close stream with proper usage."""
        events = self.close_active_block()
        final_reason = map_finish_reason(self.finish_reason)
        if self.tool_calls and self.finish_reason != "length":
            final_reason = "tool_use"

        # Use provided tokens or fallback to internal state
        final_output_tokens = output_tokens if output_tokens is not None else self.output_tokens
        final_input_tokens = input_tokens or 0
        final_cache_creation = cache_creation_input_tokens or self.cache_creation_input_tokens
        final_cache_read = cache_read_input_tokens or self.cache_read_input_tokens

        events.append(
            _format_sse(
                MessageDeltaEvent(
                    type="message_delta",
                    delta=MessageDelta(stop_reason=final_reason),
                    usage=MessageDeltaUsage(
                        output_tokens=final_output_tokens,
                        input_tokens=final_input_tokens,
                        cache_creation_input_tokens=final_cache_creation,
                        cache_read_input_tokens=final_cache_read,
                    ),
                )
            )
        )
        events.append(_format_sse(MessageStopEvent(type="message_stop")))
        return events


from debugger import tracer


async def translate_openai_to_anthropic_stream(
    openai_stream: AsyncGenerator[bytes, None],
    anthropic_request: AnthropicRequest,
    response_id: str,
    input_tokens: int,
    sse_debugger: SSEDebugLogger = None,
) -> AsyncGenerator[str, None]:
    """Translates OpenAI streaming response to compliant Anthropic SSE with debug logging."""
    t = tracer.start_trace(config=tracer.TraceConfig(target_files=["*.py"], enable_var_trace=True))
    try:
        state = StreamingState()
        logger.info("Starting streaming response translation", extra={"response_id": response_id})

        # Initialize SSE debugging
        # if sse_debugger:
        #     sse_debugger.start_batch(
        #         response_id, {"type": "translation", "model": anthropic_request.model, "input_tokens": input_tokens}
        #     )

        # 1. Send message_start event
        message_start_event = _format_sse(
            MessageStartEvent(
                type="message_start",
                message=AnthropicMessageResponse(
                    id=response_id,
                    type="message",
                    role="assistant",
                    model=anthropic_request.model,
                    content=[],
                    usage=Usage(
                        input_tokens=input_tokens,
                        output_tokens=0,
                        cache_creation_input_tokens=None,
                        cache_read_input_tokens=None,
                    ),
                ),
            )
        )
        yield message_start_event
        # if sse_debugger:
        #     sse_debugger.log_translated_sse(response_id, "message_start", message_start_event.strip())

        # 2. Process stream
        async for data_str in _sse_parser(openai_stream):
            if data_str == "[DONE]":
                break

            # Log raw SSE event
            # event_type = "data" if data_str.startswith("{") else "keepalive"
            # if sse_debugger:
            #     sse_debugger.log_raw_sse(response_id, event_type, data_str)

            try:
                chunk = OpenAIChatCompletionChunk.model_validate_json(data_str)

                # Handle final usage chunks - collect complete OpenAI usage data
                if chunk.usage and not state.usage_handled:
                    # Map OpenAI usage fields to state
                    state.output_tokens = getattr(
                        chunk.usage, "output_tokens", getattr(chunk.usage, "completion_tokens", 0)
                    )
                    state.input_tokens = getattr(chunk.usage, "input_tokens", getattr(chunk.usage, "prompt_tokens", 0))

                    # Handle cached tokens from detailed usage
                    if hasattr(chunk.usage, "input_tokens_details") and chunk.usage.input_tokens_details:
                        details = chunk.usage.input_tokens_details
                        state.cache_read_input_tokens = getattr(details, "cached_tokens", 0)
                    elif hasattr(chunk.usage, "cached_tokens"):
                        state.cache_read_input_tokens = chunk.usage.cached_tokens

                    # Mark usage as handled to prevent duplication
                    state.usage_handled = True

                    # Don't yield anything for usage-only chunks, just capture data
                    if not chunk.choices:
                        continue

                if not chunk.choices:
                    continue

                # Update state from chunk
                choice = chunk.choices[0]
                if choice.finish_reason:
                    state.finish_reason = choice.finish_reason

                delta = choice.delta

                # --- Handle Reasoning Content (thinking block) ---
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    if not state.active_block or state.active_block.block_type != "thinking":
                        for event_str in state.start_new_block("thinking"):
                            yield event_str
                            # if sse_debugger:
                            #     sse_debugger.log_translated_sse(
                            #         response_id, "content_block_start", json.loads(event_str.split("\n")[1][6:])
                            #     )

                    state.active_block.update(delta.reasoning_content)
                    event_str = _format_sse(
                        ContentBlockDeltaEvent(
                            type="content_block_delta",
                            index=state.active_block.index,
                            delta=ThinkingDelta(type="thinking_delta", thinking=delta.reasoning_content),
                        )
                    )
                    yield event_str
                    # if sse_debugger:
                    #     sse_debugger.log_translated_sse(
                    #         response_id, "content_block_delta", json.loads(event_str.split("\n")[1][6:])
                    #     )

                # --- Handle Text Content ---
                if delta.content:
                    if not state.active_block or state.active_block.block_type != "text":
                        for event_str in state.start_new_block("text"):
                            yield event_str
                            # if sse_debugger:
                            #     sse_debugger.log_translated_sse(
                            #         response_id, "content_block_start", json.loads(event_str.split("\n")[1][6:])
                            #     )

                    state.active_block.update(delta.content)
                    event_str = _format_sse(
                        ContentBlockDeltaEvent(
                            type="content_block_delta",
                            index=state.active_block.index,
                            delta=TextDelta(type="text_delta", text=delta.content),
                        )
                    )
                    yield event_str
                    # if sse_debugger:
                    #     sse_debugger.log_translated_sse(
                    #         response_id, "content_block_delta", json.loads(event_str.split("\n")[1][6:])
                    #     )

                # --- Handle Tool Calls ---
                if delta.tool_calls:
                    for tc_chunk in delta.tool_calls:
                        openai_tool_index = tc_chunk.index

                        if not (
                            state.active_block
                            and state.active_block.block_type == "tool_use"
                            and state.active_block.openai_tool_index == openai_tool_index
                        ):
                            if tc_chunk.id and tc_chunk.function and tc_chunk.function.name:
                                tool_info = {
                                    "id": tc_chunk.id,
                                    "name": tc_chunk.function.name,
                                    "openai_tool_index": openai_tool_index,
                                }
                                state.tool_calls[openai_tool_index] = tool_info
                                for event_str in state.start_new_block("tool_use", tool_info=tool_info):
                                    yield event_str
                                    # if sse_debugger:
                                    #     sse_debugger.log_translated_sse(
                                    #         response_id,
                                    #         "content_block_start",
                                    #         json.loads(event_str.split("\n")[1][6:]),
                                    #     )
                            else:
                                logger.warning(
                                    f"Received arguments for non-active tool index {openai_tool_index}. Skipping."
                                )
                                continue

                        if tc_chunk.function and tc_chunk.function.arguments:
                            event_str = _format_sse(
                                ContentBlockDeltaEvent(
                                    type="content_block_delta",
                                    index=state.active_block.index,
                                    delta=InputJsonDelta(
                                        type="input_json_delta",
                                        partial_json=tc_chunk.function.arguments,
                                    ),
                                )
                            )
                            yield event_str
                            # if sse_debugger:
                            #     sse_debugger.log_translated_sse(
                            #         response_id, "content_block_delta", json.loads(event_str.split("\n")[1][6:])
                            #     )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Stream chunk parse error: {e}", extra={"chunk": data_str})

        # 3. Finalize stream with complete usage data
        for event_str in state.finalize(
            input_tokens=state.input_tokens or input_tokens,
            output_tokens=state.output_tokens,
            cache_creation_input_tokens=state.cache_creation_input_tokens,
            cache_read_input_tokens=state.cache_read_input_tokens,
        ):
            yield event_str
            # if sse_debugger:
            #     event_name = event_str.split("\n")[0].split(": ")[1]
            #     event_data = json.loads(event_str.split("\n")[1][6:])
            #     sse_debugger.log_translated_sse(response_id, event_name, event_data)

        logger.info("Streaming translation completed", extra={"response_id": response_id})

        # Final summary
        # if sse_debugger:
        #     sse_debugger.finish_batch(
        #         response_id,
        #         {
        #             "output_tokens": state.output_tokens,
        #             "input_tokens": state.input_tokens,
        #             "cache_read_input_tokens": state.cache_read_input_tokens,
        #             "finish_reason": state.finish_reason,
        #             "blocks_processed": state.next_block_index,
        #             "final_usage_handled": True,
        #         },
        #     )
    finally:
        tracer.stop_trace(t)
