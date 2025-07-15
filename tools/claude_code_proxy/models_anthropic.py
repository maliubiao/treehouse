from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

# --- Content Block Models ---


class AnthropicTextContent(BaseModel):
    """Model for a text content block in an Anthropic message."""

    type: Literal["text"]
    text: str


class AnthropicToolUseContent(BaseModel):
    """Model for a tool_use content block from an assistant."""

    type: Literal["tool_use"]
    id: str
    name: str
    input: Dict[str, Any]


class AnthropicToolResultContent(BaseModel):
    """Model for a tool_result content block from a user."""

    type: Literal["tool_result"]
    tool_use_id: str
    content: Union[str, List[AnthropicTextContent]]
    is_error: Optional[bool] = Field(default=None)


class AnthropicThinkingContent(BaseModel):
    """Model for a thinking content block from an assistant."""

    type: Literal["thinking"]
    thinking: str


# Union of all possible content block types for a message
AnthropicContent = Union[
    AnthropicTextContent,
    AnthropicToolUseContent,
    AnthropicToolResultContent,
    AnthropicThinkingContent,
]


# --- Request Models ---


class AnthropicMessage(BaseModel):
    """Model for a single message in an Anthropic API request."""

    role: Literal["user", "assistant"]
    content: Union[str, List[AnthropicContent]]


class AnthropicTool(BaseModel):
    """Model for a single tool definition in an Anthropic request."""

    name: str
    description: str
    input_schema: Dict[str, Any]


class AnthropicThinkingConfig(BaseModel):
    """Model for Anthropic's thinking configuration."""

    type: Literal["enabled", "disabled"] = "disabled"
    budget_tokens: Optional[int] = Field(default=None)


class AnthropicRequest(BaseModel):
    """Model for a request to the Anthropic Messages API."""

    model: str
    messages: List[AnthropicMessage]
    system: Optional[Union[str, List[AnthropicTextContent]]] = Field(default=None)
    max_tokens: int
    stream: Optional[bool] = Field(default=False)
    temperature: Optional[float] = Field(default=None)
    tools: Optional[List[AnthropicTool]] = Field(default=None)
    thinking: Optional[AnthropicThinkingConfig] = Field(default=None)


# --- Response Models ---


class Usage(BaseModel):
    """Model for API usage statistics."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None


class AnthropicMessageResponse(BaseModel):
    """Model for a complete, non-streaming response from the Messages API."""

    id: str
    type: Literal["message"]
    role: Literal["assistant"]
    model: str
    content: List[Union[AnthropicTextContent, AnthropicToolUseContent, AnthropicThinkingContent]]
    stop_reason: Optional[str] = Field(default=None)
    stop_sequence: Optional[str] = Field(default=None)
    usage: Usage


# --- Streaming Response Models ---


# Represents the data inside a content_block during streaming events
class ContentBlock(BaseModel):
    type: str
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    thinking: Optional[str] = None


# Streaming Event Deltas
class TextDelta(BaseModel):
    """A delta in a text content block."""

    type: Literal["text_delta"]
    text: str


class InputJsonDelta(BaseModel):
    """A delta in a tool_use content block's input JSON."""

    type: Literal["input_json_delta"]
    partial_json: str


class ThinkingDelta(BaseModel):
    """A delta in a thinking content block."""

    type: Literal["thinking_delta"]
    thinking: str


class SignatureDelta(BaseModel):
    """A signature for a thinking content block."""

    type: Literal["signature_delta"]
    signature: str


# Streaming Events
class MessageStartEvent(BaseModel):
    """Event sent when a message stream starts."""

    type: Literal["message_start"]
    message: AnthropicMessageResponse


class ContentBlockStartEvent(BaseModel):
    type: Literal["content_block_start"]
    index: int
    content_block: ContentBlock


class ContentBlockDeltaEvent(BaseModel):
    """Event for a delta in a content block."""

    type: Literal["content_block_delta"]
    index: int
    delta: Union[TextDelta, InputJsonDelta, ThinkingDelta, SignatureDelta]


class ContentBlockStopEvent(BaseModel):
    type: Literal["content_block_stop"]
    index: int


class MessageDelta(BaseModel):
    """A delta in the top-level message object."""

    stop_reason: Optional[str] = Field(default=None)
    stop_sequence: Optional[str] = Field(default=None)


class MessageDeltaUsage(BaseModel):
    """Usage stats included in a message_delta event."""

    output_tokens: int
    input_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None


class MessageDeltaEvent(BaseModel):
    """Event for a delta in the message, including usage."""

    type: Literal["message_delta"]
    delta: MessageDelta
    usage: MessageDeltaUsage


class MessageStopEvent(BaseModel):
    """Event sent when a message stream stops."""

    type: Literal["message_stop"]


# --- Batch Processing Models ---


class AnthropicBatchRequestItem(BaseModel):
    """Model for a single request in an Anthropic Message Batch."""

    custom_id: str
    params: AnthropicRequest


class AnthropicBatchRequest(BaseModel):
    """Model for creating an Anthropic Message Batch."""

    requests: List[AnthropicBatchRequestItem]


class AnthropicBatchResponse(BaseModel):
    """Model for an Anthropic Message Batch response."""

    id: str
    type: Literal["message_batch"]
    processing_status: Literal["in_progress", "ended", "canceled", "expired"]
    request_counts: Dict[str, int]
    ended_at: Optional[str] = None
    created_at: str
    expires_at: str
    cancel_initiated_at: Optional[str] = None
    results_url: Optional[str] = None


class AnthropicBatchResult(BaseModel):
    """Model for a single result in an Anthropic Message Batch."""

    custom_id: str
    result: Dict[str, Any]  # Can be succeeded, errored, canceled, or expired
