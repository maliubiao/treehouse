from __future__ import annotations

import json
from typing import Any, Dict, List

from .models_anthropic import (
    AnthropicBatchRequest,
    AnthropicBatchRequestItem,
    AnthropicMessageResponse,
)
from .models_openai import OpenAIChatCompletion
from .request_translator import translate_anthropic_to_openai


def translate_anthropic_batch_to_openai(
    anthropic_batch: AnthropicBatchRequest,
) -> List[Dict[str, Any]]:
    """
    Translates an Anthropic Message Batch request to OpenAI batch format.

    Args:
        anthropic_batch: The Anthropic batch request to translate.

    Returns:
        List of OpenAI-compatible batch requests.
    """
    openai_batch_requests = []

    for item in anthropic_batch.requests:
        openai_request = translate_anthropic_to_openai(item.params)
        openai_batch_requests.append(
            {
                "custom_id": item.custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": openai_request.model_dump(exclude_none=True),
            }
        )

    return openai_batch_requests


def translate_openai_batch_to_anthropic(openai_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Translates OpenAI batch results back to Anthropic format.

    Args:
        openai_results: List of OpenAI batch results.

    Returns:
        List of Anthropic-compatible batch results.
    """
    anthropic_results = []

    for result in openai_results:
        custom_id = result.get("custom_id")
        response = result.get("response", {})

        if response.get("status_code") == 200:
            # Successful response
            openai_completion = OpenAIChatCompletion.model_validate(response.get("body", {}))

            # Convert to Anthropic format
            anthropic_response = AnthropicMessageResponse(
                id=openai_completion.id,
                type="message",
                role="assistant",
                model=openai_completion.model,
                content=[{"type": "text", "text": openai_completion.choices[0].message.content or ""}]
                if openai_completion.choices[0].message.content
                else [],
                stop_reason=openai_completion.choices[0].finish_reason,
                usage={
                    "input_tokens": openai_completion.usage.prompt_tokens,
                    "output_tokens": openai_completion.usage.completion_tokens,
                },
            )

            anthropic_results.append(
                {
                    "custom_id": custom_id,
                    "result": {"type": "succeeded", "message": anthropic_response.model_dump(exclude_none=True)},
                }
            )
        else:
            # Error response
            anthropic_results.append(
                {
                    "custom_id": custom_id,
                    "result": {
                        "type": "errored",
                        "error": {
                            "type": "api_error",
                            "message": response.get("body", {}).get("error", {}).get("message", "Unknown error"),
                        },
                    },
                }
            )

    return anthropic_results
