#!/usr/bin/env python3
"""
LLM 查询功能的 Web API 服务。

提供与命令行工具类似的功能，但通过HTTP接口暴露。
支持并发查询、SSE流式响应和动态补全。
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import uvicorn
from fastapi import Body, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import StreamingResponse

# --- 动态路径设置，确保能找到项目根目录下的模块 ---
current_dir = Path(__file__).parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))

# --- 从 llm_query.py 和 shell.py 复制并改造的代码 ---
import openai
from openai import AsyncOpenAI

from llm_query import GPTContextProcessor, get_conversation_file
from llm_query import ModelConfig as OriginalModelConfig
from llm_query import ModelSwitch as OriginalModelSwitch
from shell import handle_cmd_complete as original_handle_cmd_complete

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- 异步改造的核心部分 ---


async def async_query_gpt_api(
    api_key: str,
    messages: List[Dict[str, str]],  # 接收消息列表
    model: str,
    base_url: str,
    model_config: "ModelConfig",
    **kwargs,
) -> AsyncGenerator[Dict[str, str], None]:
    """
    异步、流式的OpenAI API查询生成器。

    Args:
        api_key (str): OpenAI API密钥
        messages (List[Dict[str, str]]): 对话历史消息列表
        model (str): 使用的模型名称
        base_url (str): API基础URL
        model_config (ModelConfig): 模型配置对象

    Yields:
        Dict[str, str]: 包含事件类型和数据的字典。
    """
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    extra_body = {}
    if model_config.is_thinking and model_config.thinking_budget > 0:
        extra_body = {
            "enable_thinking": True,
            "thinking_budget": model_config.thinking_budget,
        }

    create_params = {
        "model": model,
        "messages": messages,  # 直接使用传入的消息列表
        "stream": True,
        "temperature": model_config.temperature,
        "top_p": model_config.top_p,
    }
    if extra_body:
        create_params["extra_body"] = extra_body

    try:
        stream = await client.chat.completions.create(**create_params)
        async for chunk in stream:
            # 处理思考过程
            if hasattr(chunk.choices[0].delta, "reasoning_content") and chunk.choices[0].delta.reasoning_content:
                yield {"event": "thinking", "data": chunk.choices[0].delta.reasoning_content}

            # 处理主要内容
            if chunk.choices[0].delta.content:
                yield {"event": "content", "data": chunk.choices[0].delta.content}

        # 异步流结束后，发送结束信号
        yield {"event": "end", "data": "[DONE]"}

    except openai.APIError as e:
        error_message = f"OpenAI API Error: {e}"
        logger.error(error_message)
        yield {"event": "error", "data": error_message}
    except Exception as e:
        error_message = f"An unexpected error occurred: {e}"
        logger.error(error_message, exc_info=True)
        yield {"event": "error", "data": error_message}


class ModelConfig(OriginalModelConfig):
    pass


class ModelSwitch(OriginalModelSwitch):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.current_config:
            globals()["GLOBAL_MODEL_CONFIG"] = self.current_config

    def select(self, model_name: str) -> None:
        super().select(model_name)
        if self.current_config:
            globals()["GLOBAL_MODEL_CONFIG"] = self.current_config

    async def async_query(
        self, model_name: str, messages: List[Dict[str, str]], **kwargs
    ) -> AsyncGenerator[Dict[str, str], None]:
        if self.test_mode:
            yield {"event": "content", "data": "test_response"}
            return

        config = self._get_model_config(model_name)
        self.current_config = config

        async for chunk in async_query_gpt_api(
            base_url=config.base_url,
            api_key=config.key,
            messages=messages,
            model=config.model_name,
            model_config=config,
            **kwargs,
        ):
            yield chunk


def get_completion_suggestions(prefix: str) -> List[str]:
    import contextlib
    from io import StringIO

    output_catcher = StringIO()
    original_stdout = sys.stdout
    try:
        sys.stdout = output_catcher
        original_handle_cmd_complete(prefix)
        captured_output = output_catcher.getvalue()
    finally:
        sys.stdout = original_stdout

    if captured_output:
        return [line for line in captured_output.strip().split("\n") if line]
    return []


# --- FastAPI 应用定义 ---
model_switcher: Optional[ModelSwitch] = None
default_model: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model_switcher, default_model
    if "GPT_PATH" not in os.environ:
        logger.warning("GPT_PATH environment variable is not set. Using current directory as fallback.")
        os.environ["GPT_PATH"] = str(project_root)

    model_config_path = Path(os.environ["GPT_PATH"]) / "model.json"
    if not model_config_path.exists():
        logger.error(f"Model configuration file not found at {model_config_path}")
        model_switcher = ModelSwitch(test_mode=True)
    else:
        model_switcher = ModelSwitch()

    if default_model and model_switcher:
        try:
            model_switcher.select(default_model)
            logger.info(f"Default model set to: {default_model}")
        except ValueError as e:
            logger.error(f"Could not set default model '{default_model}': {e}")

    logger.info("Model switcher initialized successfully.")
    yield
    logger.info("Application shutdown complete.")


app = FastAPI(
    title="Terminal LLM API",
    description="A web API for interacting with Large Language Models, providing features similar to the terminal-llm tool.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: Optional[str] = None


@app.get("/models", summary="Get available models")
def get_models() -> Dict[str, List[str]]:
    if not model_switcher:
        return {"error": "Model switcher not initialized"}
    return {"models": model_switcher.models()}


@app.get("/complete", summary="Get command completions")
def get_completions(
    prefix: str = Query(..., description="The prefix to complete, e.g., '@file'"),
) -> Dict[str, List[str]]:
    suggestions = get_completion_suggestions(prefix)
    return {"completions": suggestions}


@app.post("/ask", summary="Ask a question to the LLM with streaming response")
async def ask_llm(request: AskRequest):
    """
    向LLM发送一个包含对话历史的请求，并以SSE事件流的形式接收响应。

    - **messages**: The entire conversation history, including the latest user message.
    - **model**: Optional. The specific model configuration to use from `model.json`.
    """
    if not model_switcher:

        async def error_stream():
            yield 'event: error\ndata: {"error": "Model switcher not initialized"}\n\n'

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    model = request.model
    if model:
        model_switcher.select(model)

    selected_model = model or model_switcher.models()[0]
    logger.info(f"Using model: {selected_model} for a conversation with {len(request.messages)} messages.")

    async def sse_generator():
        try:
            full_response_content = ""
            async for chunk in model_switcher.async_query(selected_model, request.messages):
                if chunk.get("event") == "error":
                    logger.error(f"Error from LLM stream: {chunk.get('data')}")
                json_data = json.dumps(chunk)
                yield f"{json_data}\n"
                await asyncio.sleep(0)
                if chunk.get("event") == "content":
                    full_response_content += chunk.get("data", "")
        except Exception as e:
            logger.error(f"Error during SSE generation: {e}", exc_info=True)
            error_payload = json.dumps({"event": "error", "data": str(e)})
            yield f"{error_payload}\n"

    return StreamingResponse(sse_generator(), media_type="application/x-ndjson")


def main():
    parser = argparse.ArgumentParser(description="Terminal LLM Web API Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server to.")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on.")
    parser.add_argument("--default-model", type=str, default=None, help="Default model to use for queries.")
    args = parser.parse_args()

    global default_model
    default_model = args.default_model

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
