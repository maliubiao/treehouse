from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import asyncstdlib
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from . import response_translator_v2 as response_translator

# from .batch_translator import (
#     # translate_anthropic_batch_to_openai, # W0611: Unused import
#     # translate_openai_batch_to_anthropic, # W0611: Unused import
# )
from .config_manager import ProviderConfig, config_manager
from .logger import RequestLogger, SSEDebugLogger, get_logger, setup_logging
from .models_anthropic import (
    AnthropicBatchRequest,
    AnthropicBatchResponse,
    AnthropicRequest,
)
from .models_openai import OpenAIChatCompletion, OpenAIChatCompletionChunk
from .provider_router import provider_router
from .request_translator import get_openai_request_with_reasoning

# Global setup - defer SSE debugger initialization to after config load
setup_logging()
logger = get_logger("server")
request_logger = RequestLogger(logger)

# In-memory storage for batch jobs (in production, use Redis or a database)
batch_jobs: Dict[str, AnthropicBatchResponse] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the lifespan of resources, like HTTP clients."""
    logger.info("Anthropic to OpenAI Proxy Server is starting up.")

    # Initialize the provider router, which loads config and creates clients.
    await provider_router.initialize()
    logger.info("Provider router initialized.")

    # Load full config and initialize SSE debugger
    config = config_manager.load_config()
    effective_log_level = config.logging.level.upper()
    logging.getLogger("anthropic_proxy").setLevel(effective_log_level)
    logger.info(f"Log level set to {effective_log_level}.")

    yield

    # Cleanup resources on shutdown
    await provider_router.cleanup()
    logger.info("Provider router cleaned up.")
    logger.info("Server is shutting down.")


app = FastAPI(
    title="Anthropic to OpenAI Proxy",
    description="A proxy server to translate Anthropic API requests and responses "
    "to and from OpenAI format, including multi-provider routing and batch processing.",
    lifespan=lifespan,
)


def _create_error_response(
    message: str, error_type: str = "invalid_request_error", status_code: int = 400
) -> JSONResponse:
    """Creates a standardized Anthropic-like error JSON response."""
    return JSONResponse(
        status_code=status_code,
        content={"type": "error", "error": {"type": error_type, "message": message}},
    )


def _handle_downstream_error(e: httpx.HTTPStatusError, request_id: str, provider_name: str) -> JSONResponse:
    """Creates a standardized error from a downstream HTTP error."""
    try:
        error_details = e.response.json()
        error_message = error_details.get("error", {}).get("message", e.response.text)
    except json.JSONDecodeError:
        error_details = {"raw_text": e.response.text}
        error_message = e.response.text

    request_logger.log_error(
        request_id,
        e,
        {
            "context": "downstream_api_error",
            "provider": provider_name,
            "downstream_status": e.response.status_code,
            "downstream_response": error_details,
        },
    )
    return _create_error_response(
        f"Error from provider '{provider_name}': {error_message}",
        error_type="api_error",
        status_code=e.response.status_code,
    )


async def _stream_and_translate_response(
    openai_stream_response: httpx.Response,
    anthropic_request: AnthropicRequest,
    request_id: str,
) -> AsyncGenerator[str, None]:
    """Handles the full lifecycle of streaming and translating a response."""
    openai_stream_generator = openai_stream_response.aiter_bytes()
    response_id = f"msg_{uuid.uuid4().hex}"  # Default, may be overwritten by first chunk

    try:
        # We need the first chunk to determine the response ID for Anthropic's format.
        first_chunk_bytes = await asyncstdlib.anext(openai_stream_generator, None)
        if first_chunk_bytes is None:
            logger.warning(f"Request {request_id}: Downstream stream was empty.")
            return

        chunk_str = first_chunk_bytes.decode("utf-8")
        for line in chunk_str.splitlines():
            if line.startswith("data: "):
                data_str = line.partition("data: ")[2].strip()
                if data_str != "[DONE]":
                    try:
                        chunk_model = OpenAIChatCompletionChunk.model_validate_json(data_str)
                        response_id = chunk_model.id
                        break
                    except (json.JSONDecodeError, ValueError):
                        continue

        # Create a new generator that puts the first chunk back.
        async def full_stream() -> AsyncGenerator[bytes, None]:
            yield first_chunk_bytes
            async for chunk in openai_stream_generator:
                yield chunk

        # Translate the complete stream.
        async for translated_chunk in response_translator.translate_openai_to_anthropic_stream(
            full_stream(),
            anthropic_request,
            response_id,
        ):
            yield translated_chunk

    except Exception as e:
        logger.error(f"Streaming translation error: {e}", extra={"request_id": request_id})
        yield f"data: {json.dumps({'type': 'error', 'error': {'type': 'server_error', 'message': str(e)}})}\n\n"
        return

    finally:
        await openai_stream_response.aclose()
        logger.info(f"Stream closed for request {request_id}")


from context_tracer.tracer import TraceConfig, TraceContext


@app.post("/v1/messages")
async def messages_proxy(request: Request) -> Response:
    request_id = str(uuid.uuid4())
    with TraceContext(
        TraceConfig(enable_var_trace=True, target_files=["*.py"], report_name=f"messages-{request_id}.html")
    ):
        try:
            body = await request.json()
            request_logger.log_request_received(request_id, request, body)
            anthropic_request = AnthropicRequest.model_validate(body)

            # # Debug dump
            # dump_dir = "logs/requests"
            # os.makedirs(dump_dir, exist_ok=True)
            # dump_path = os.path.join(dump_dir, f"{request_id}.json")
            # with open(dump_path, "w", encoding="utf-8") as f:
            #     json.dump(body, f, indent=2, ensure_ascii=False)

        except (json.JSONDecodeError, ValidationError) as e:
            request_logger.log_error(request_id, e, {"context": "request_validation"})
            return _create_error_response(f"Invalid request body: {e}")

        # --- Routing Logic ---
        provider_key = provider_router.route_request(anthropic_request)
        if not provider_key:
            msg = f"No provider could be determined for model '{anthropic_request.model}' based on routing rules."
            request_logger.log_error(request_id, ValueError(msg), {"context": "provider_selection"})
            return _create_error_response(msg, status_code=404)

        provider = provider_router.get_provider_by_key(provider_key)
        if not provider:
            msg = f"Provider key '{provider_key}' not found in configuration."
            request_logger.log_error(request_id, ValueError(msg), {"context": "provider_lookup"})
            return _create_error_response(msg, status_code=500)

        # --- Model Mapping and Logging ---
        target_model = provider_router.get_target_model(anthropic_request.model, provider_key)
        if "INVALID_" in target_model:  # Covers both mapping and config errors
            return _create_error_response(
                f"Invalid model mapping for '{anthropic_request.model}' on provider '{provider.name}'. Check logs for details.",
                status_code=400,
            )

        logger.info(
            f"Request {request_id} routed.",
            extra={
                "request_id": request_id,
                "anthropic_model": anthropic_request.model,
                "provider_key": provider_key,
                "provider_name": provider.name,
                "target_model": target_model,
                "is_stream": anthropic_request.stream,
                "is_thinking": anthropic_request.thinking and anthropic_request.thinking.type == "enabled",
            },
        )

        http_client = provider_router.get_client(provider_key)
        if not http_client:
            msg = f"Internal Server Error: HTTP client for provider key '{provider_key}' not found."
            request_logger.log_error(request_id, RuntimeError(msg), {"context": "client_initialization"})
            return _create_error_response(msg, error_type="api_error", status_code=500)

        # --- Request Translation ---
        try:
            openai_request, extra_body = get_openai_request_with_reasoning(
                anthropic_request, target_model, provider.model_dump()
            )
            request_payload = openai_request.model_dump(exclude_none=True)
            request_payload.update(extra_body)

            request_logger.log_request_translated(
                request_id,
                f"'{anthropic_request.model}' -> '{target_model}' via provider '{provider.name}'",
                request_payload,
            )
        except ValidationError as e:
            request_logger.log_error(request_id, e, {"context": "request_validation"})
            return _create_error_response(f"Invalid request: {e}", "invalid_request_error", 400)
        except Exception as e:
            request_logger.log_error(request_id, e, {"context": "request_translation"})
            return _create_error_response(f"Error during request translation: {e}", "api_error", 500)

        # --- Execution ---
        try:
            if anthropic_request.stream:
                stream_request = http_client.build_request(
                    "POST", "/chat/completions", json=request_payload, timeout=provider.timeout
                )
                openai_stream_response = await http_client.send(stream_request, stream=True)
                openai_stream_response.raise_for_status()

                logger.info(f"Initiated stream with provider '{provider.name}'", extra={"request_id": request_id})
                return StreamingResponse(
                    _stream_and_translate_response(openai_stream_response, anthropic_request, request_id),
                    media_type="text/event-stream",
                )
            else:
                response = await http_client.post("/chat/completions", json=request_payload, timeout=provider.timeout)
                response.raise_for_status()
                response_data = response.json()
                openai_response = OpenAIChatCompletion.model_validate(response_data)
                request_logger.log_response_received(request_id, provider.name, openai_response.model_dump())

                anthropic_response = response_translator.translate_openai_to_anthropic_non_stream(openai_response)
                request_logger.log_response_translated(request_id, anthropic_response.model_dump())

                return JSONResponse(content=json.loads(anthropic_response.model_dump_json(exclude_none=True)))
        except httpx.HTTPStatusError as e:
            return _handle_downstream_error(e, request_id, provider.name)
        except Exception as e:
            request_logger.log_error(request_id, e, {"context": "downstream_request"})
            return _create_error_response(f"An unexpected error occurred: {e}", "api_error", 500)


@app.post("/v1/messages/batches")
async def create_batch(request: Request) -> Response:
    request_id = str(uuid.uuid4())
    try:
        body = await request.json()
        anthropic_batch_request = AnthropicBatchRequest.model_validate(body)
    except (json.JSONDecodeError, ValidationError) as e:
        return _create_error_response(f"Invalid batch request: {e}")

    if not anthropic_batch_request.requests:
        return _create_error_response("Batch request cannot be empty.")

    # Determine the set of required providers
    providers_needed: Dict[str, ProviderConfig] = {}
    for item in anthropic_batch_request.requests:
        if item.params.stream:
            return _create_error_response("Streaming is not supported in batch requests")

        provider_key = provider_router.route_request(item.params)
        if not provider_key:
            return _create_error_response(f"No provider found for model: {item.params.model} based on routing rules")

        provider = provider_router.get_provider_by_key(provider_key)
        if provider:
            providers_needed[provider_key] = provider

    if len(providers_needed) > 1:
        provider_keys = ", ".join(providers_needed.keys())
        msg = f"Batch requests spanning multiple providers ({provider_keys}) are not supported in this version."
        logger.warning(msg, extra={"request_id": request_id})
        return _create_error_response(msg, status_code=422)  # Unprocessable Entity

    if not providers_needed:
        return _create_error_response("No valid provider could be determined for the batch request.", status_code=400)

    # All requests go to the same provider
    provider_key = list(providers_needed.keys())[0]
    provider = providers_needed[provider_key]
    http_client = provider_router.get_client(provider_key)
    if not http_client:
        return _create_error_response(f"Client for provider key {provider_key} not found", "api_error", 500)

    # Translate the entire batch
    openai_batch_requests = []
    for item in anthropic_batch_request.requests:
        target_model = provider_router.get_target_model(item.params.model, provider_key)
        if "INVALID_" in target_model:
            return _create_error_response(f"Invalid model mapping for '{item.params.model}' in batch.", status_code=400)

        openai_req, extra_body = get_openai_request_with_reasoning(item.params, target_model, provider.model_dump())
        body = openai_req.model_dump(exclude_none=True)
        body.update(extra_body)
        openai_batch_requests.append(
            {"custom_id": item.custom_id, "method": "POST", "url": "/v1/chat/completions", "body": body}
        )

    try:
        response = await http_client.post(
            "/v1/chat/completions/batches", json={"requests": openai_batch_requests}, timeout=provider.timeout
        )
        response.raise_for_status()

        # Process the response to check for partial failures
        batch_response = await response.json()
        responses = batch_response.get("responses", [])

        # Check if we have any failures
        has_failures = any(resp.get("status") == "error" for resp in responses)
        has_successes = any(resp.get("status") == "success" for resp in responses)

        if has_failures and has_successes:
            # Partial success - return 207
            return JSONResponse(
                {"status": "partial_failure", "provider": provider_key, "results": responses}, status_code=207
            )
        elif has_failures and not has_successes:
            # All failures - return error
            return JSONResponse({"status": "error", "provider": provider_key, "results": responses}, status_code=400)
        else:
            # All successes - return 200
            return JSONResponse(
                {
                    "status": "Batch request sent successfully to provider",
                    "provider": provider_key,
                    "results": responses,
                }
            )

    except httpx.HTTPStatusError as e:
        return _handle_downstream_error(e, request_id, provider_key)
    except Exception as e:
        request_logger.log_error(request_id, e, {"context": "batch_creation"})
        return _create_error_response(f"Error creating batch: {e}", "api_error", 500)
