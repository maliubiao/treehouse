from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .logger import get_logger
from .models_anthropic import (
    AnthropicMessage,
    AnthropicRequest,
    AnthropicTextContent,
    AnthropicToolResultContent,
    AnthropicToolUseContent,
)
from .models_openai import (
    OpenAIChatMessage,
    OpenAIFunction,
    OpenAIFunctionCall,
    OpenAIRequest,
    OpenAITool,
    OpenAIToolCall,
)

logger = get_logger("request_translator")


def translate_anthropic_to_openai(anthropic_request: AnthropicRequest, target_model: str) -> OpenAIRequest:
    """
    Translates an Anthropic Messages API request to an OpenAI Chat Completions API request.

    This function meticulously handles the structural differences between the two APIs,
    including system prompts, message roles, and tool usage.

    Args:
        anthropic_request: A Pydantic object representing the validated Anthropic request.
        target_model: The target OpenAI-compatible model name determined by the router.

    Returns:
        A Pydantic object representing the equivalent, validated OpenAI request.
    """
    logger.debug(
        "Starting request translation",
        extra={
            "anthropic_model": anthropic_request.model,
            "target_model": target_model,
            "message_count": len(anthropic_request.messages),
            "stream": anthropic_request.stream,
        },
    )

    # 1. Translate Tool Definitions
    openai_tools: Optional[List[OpenAITool]] = None
    if anthropic_request.tools:
        openai_tools = [
            OpenAITool(
                function=OpenAIFunction(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.input_schema,
                )
            )
            for tool in anthropic_request.tools
        ]
        logger.debug(f"Translated {len(openai_tools)} tools.")

    # 2. Translate Messages
    openai_messages: List[OpenAIChatMessage] = []

    # Translate System Prompt
    if anthropic_request.system:
        system_content = (
            anthropic_request.system
            if isinstance(anthropic_request.system, str)
            else "\n".join([c.text for c in anthropic_request.system])
        )
        if system_content.strip():
            openai_messages.append(OpenAIChatMessage(role="system", content=system_content))

    # Translate Message History
    for msg in anthropic_request.messages:
        openai_messages.extend(_translate_message_content(msg))

    # 3. Construct the final OpenAI request object
    openai_request = OpenAIRequest(
        model=target_model,
        messages=openai_messages,
        stream=anthropic_request.stream,
        temperature=anthropic_request.temperature,
        max_tokens=anthropic_request.max_tokens,
        tools=openai_tools,
    )

    return openai_request


def _translate_message_content(msg: AnthropicMessage) -> List[OpenAIChatMessage]:
    """Helper to translate a single Anthropic message to one or more OpenAI messages."""
    if isinstance(msg.content, str):
        return [OpenAIChatMessage(role=msg.role, content=msg.content)]

    messages: List[OpenAIChatMessage] = []
    if msg.role == "user":
        text_parts: List[str] = []
        for content_block in msg.content:
            if isinstance(content_block, AnthropicTextContent):
                text_parts.append(content_block.text)
            elif isinstance(content_block, AnthropicToolResultContent):
                tool_content = (
                    content_block.content
                    if isinstance(content_block.content, str)
                    else "\n".join([c.text for c in content_block.content])
                )
                messages.append(
                    OpenAIChatMessage(
                        role="tool",
                        tool_call_id=content_block.tool_use_id,
                        content=tool_content,
                    )
                )
        if text_parts:
            messages.append(OpenAIChatMessage(role="user", content="\n".join(text_parts)))

    elif msg.role == "assistant":
        text_parts = []
        tool_calls = []
        for content_block in msg.content:
            if isinstance(content_block, AnthropicTextContent):
                text_parts.append(content_block.text)
            elif isinstance(content_block, AnthropicToolUseContent):
                tool_calls.append(
                    OpenAIToolCall(
                        id=content_block.id,
                        function=OpenAIFunctionCall(
                            name=content_block.name,
                            arguments=json.dumps(content_block.input),
                        ),
                    )
                )
        text_content = "\n".join(text_parts) if text_parts else None
        if text_content or tool_calls:
            messages.append(
                OpenAIChatMessage(
                    role="assistant",
                    content=text_content,
                    tool_calls=tool_calls if tool_calls else None,
                )
            )
    return messages


def get_openai_request_with_reasoning(
    anthropic_request: AnthropicRequest,
    target_model: str,
    provider_config: Dict[str, Any],
) -> Tuple[OpenAIRequest, Dict[str, Any]]:
    """
    Generates an OpenAI request and a dictionary of extra parameters for the
    request body, specifically handling reasoning/thinking and other provider-
    specific settings.

    Args:
        anthropic_request: The original Anthropic request.
        target_model: The target model name for the OpenAI-compatible API.
        provider_config: The configuration dictionary for the selected provider.

    Returns:
        A tuple containing:
        - The translated OpenAIRequest object.
        - A dictionary of extra body parameters to be added to the request.
    """
    openai_request = translate_anthropic_to_openai(anthropic_request, target_model)
    extra_body: Dict[str, Any] = {}

    # Handle Reasoning/Thinking Parameters
    thinking_requested = anthropic_request.thinking and anthropic_request.thinking.type == "enabled"
    provider_supports_reasoning = provider_config.get("supports_reasoning", False)

    logger.debug(
        "Processing reasoning parameters",
        extra={
            "model": target_model,
            "provider": provider_config.get("name"),
            "thinking_requested": thinking_requested,
            "provider_supports_reasoning": provider_supports_reasoning,
        },
    )

    if thinking_requested:
        if provider_supports_reasoning:
            reasoning_config = provider_config.get("reasoning_config", {})

            if reasoning_config.get("include_reasoning"):
                extra_body["include_reasoning"] = True

            if anthropic_request.thinking.budget_tokens:
                budget_param = reasoning_config.get("thinking_budget_param")
                if budget_param:
                    extra_body[budget_param] = anthropic_request.thinking.budget_tokens
                    logger.debug(f"Added reasoning budget: {budget_param}={anthropic_request.thinking.budget_tokens}")
        else:
            logger.warning(
                "Anthropic 'thinking' was requested, but the selected provider does not support reasoning. Proceeding without it.",
                extra={
                    "model": target_model,
                    "provider": provider_config.get("name"),
                },
            )

    # Handle Max Tokens Override
    max_tokens_override = provider_config.get("max_tokens_override")
    if max_tokens_override is not None:
        original_max_tokens = openai_request.max_tokens
        if original_max_tokens is None or original_max_tokens > max_tokens_override:
            logger.info(
                f"Overriding max_tokens for provider '{provider_config.get('name')}': {original_max_tokens} -> {max_tokens_override}",
                extra={
                    "provider": provider_config.get("name"),
                    "original_max_tokens": original_max_tokens,
                    "max_tokens_override": max_tokens_override,
                },
            )
            openai_request.max_tokens = max_tokens_override

    return openai_request, extra_body
