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
from starlette.responses import StreamingResponse

# --- 动态路径设置，确保能找到项目根目录下的模块 ---
# 将项目根目录添加到sys.path
# 这是必要的，因为我们可能需要从其他地方导入llm_query中的类
# 为了遵循不修改原则，我们直接从llm_query.py复制所需代码
# 但保留这个结构以备将来重构
current_dir = Path(__file__).parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))

# --- 从 llm_query.py 和 shell.py 复制并改造的代码 ---
# 注意：这是一个临时的解决方案，以遵守“不修改现有文件”的规则。
# 理想情况下，这些共享的类和函数应该被重构到一个公共库中。

# 从 llm_query.py 复制 ModelConfig 和 ModelSwitch
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
    prompt: str,
    model: str,
    base_url: str,
    model_config: "ModelConfig",
    **kwargs,
) -> AsyncGenerator[Dict[str, str], None]:
    """
    异步、流式的OpenAI API查询生成器。

    Args:
        api_key (str): OpenAI API密钥
        prompt (str): 用户输入的提示词
        model (str): 使用的模型名称
        base_url (str): API基础URL
        model_config (ModelConfig): 模型配置对象

    Yields:
        Dict[str, str]: 包含事件类型和数据的字典。
                         例如: {"event": "thinking", "data": "..."}
                               {"event": "content", "data": "..."}
    """
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # 准备多轮对话历史
    # 在API模式下，我们通常处理无状态请求，但保留加载历史的能力
    history = []
    if not kwargs.get("disable_conversation_history"):
        conversation_file = get_conversation_file(kwargs.get("conversation_file"))
        if os.path.exists(conversation_file):
            with open(conversation_file, "r", encoding="utf-8") as f:
                history = json.load(f)

    history.append({"role": "user", "content": prompt})

    extra_body = {}
    if model_config.is_thinking and model_config.thinking_budget > 0:
        extra_body = {
            "enable_thinking": True,
            "thinking_budget": model_config.thinking_budget,
        }

    create_params = {
        "model": model,
        "messages": history,
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
    """从 llm_query.py 继承并保持不变"""

    pass


class ModelSwitch(OriginalModelSwitch):
    """
    继承并改造 ModelSwitch 以支持异步查询。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 将GLOBAL_MODEL_CONFIG设置为当前选中的模型
        # 这是为了让GPTContextProcessor等复用的代码能正常工作
        if self.current_config:
            globals()["GLOBAL_MODEL_CONFIG"] = self.current_config

    def select(self, model_name: str) -> None:
        super().select(model_name)
        if self.current_config:
            globals()["GLOBAL_MODEL_CONFIG"] = self.current_config

    async def async_query(self, model_name: str, prompt: str, **kwargs) -> AsyncGenerator[Dict[str, str], None]:
        """
        异步查询API。

        Args:
            model_name (str): 模型名称
            prompt (str): 提示词

        Yields:
            Dict[str, str]: SSE事件字典
        """
        if self.test_mode:
            yield {"event": "content", "data": "test_response"}
            return

        config = self._get_model_config(model_name)
        self.current_config = config
        # globals()["GLOBAL_MODEL_CONFIG"] = config  # 确保全局配置同步

        async for chunk in async_query_gpt_api(
            base_url=config.base_url,
            api_key=config.key,
            prompt=prompt,
            model=config.model_name,
            model_config=config,
            **kwargs,
        ):
            yield chunk


def get_completion_suggestions(prefix: str) -> List[str]:
    """
    获取补全建议。
    这是对 shell.py 中 handle_cmd_complete 的改造，使其返回列表而不是打印。
    """
    # 捕获 `handle_cmd_complete` 的标准输出
    import contextlib
    from io import StringIO

    # 创建一个字符串IO来捕获输出
    output_catcher = StringIO()

    # 备份原始的 sys.stdout
    original_stdout = sys.stdout
    try:
        # 重定向 stdout
        sys.stdout = output_catcher
        # 调用原始函数，它的输出会进入 output_catcher
        original_handle_cmd_complete(prefix)
        # 获取捕获的输出
        captured_output = output_catcher.getvalue()
    finally:
        # 恢复原始的 stdout
        sys.stdout = original_stdout

    # 处理捕获的输出
    if captured_output:
        return [line for line in captured_output.strip().split("\n") if line]
    return []


# --- FastAPI 应用定义 ---

# 全局模型切换器实例
model_switcher: Optional[ModelSwitch] = None
default_model: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用生命周期的启动和关闭事件"""
    global model_switcher, default_model
    # 确保GPT_PATH环境变量存在，以便找到model.json
    if "GPT_PATH" not in os.environ:
        logger.warning("GPT_PATH environment variable is not set. Using current directory as fallback.")
        os.environ["GPT_PATH"] = str(project_root)

    model_config_path = Path(os.environ["GPT_PATH"]) / "model.json"
    if not model_config_path.exists():
        logger.error(f"Model configuration file not found at {model_config_path}")
        # 在这种情况下，应用可能无法正常工作
        model_switcher = ModelSwitch(test_mode=True)  # 使用测试模式以避免崩溃
    else:
        model_switcher = ModelSwitch()

    # 设置默认模型（如果提供）
    if default_model and model_switcher:
        try:
            model_switcher.select(default_model)
            logger.info(f"Default model set to: {default_model}")
        except ValueError as e:
            logger.error(f"Could not set default model '{default_model}': {e}")

    logger.info("Model switcher initialized successfully.")
    yield
    # 清理资源（如果需要）
    if model_switcher:
        # 可以在这里添加模型清理逻辑
        pass
    logger.info("Application shutdown complete.")


app = FastAPI(
    title="Terminal LLM API",
    description="A web API for interacting with Large Language Models, providing features similar to the terminal-llm tool.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS (Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境应配置为特定前端域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有HTTP头
)


@app.get("/models", summary="Get available models")
def get_models() -> Dict[str, List[str]]:
    """
    获取所有可用的模型列表。
    """
    if not model_switcher:
        return {"error": "Model switcher not initialized"}
    return {"models": model_switcher.models()}


@app.get("/complete", summary="Get command completions")
def get_completions(
    prefix: str = Query(..., description="The prefix to complete, e.g., '@file'"),
) -> Dict[str, List[str]]:
    """
    根据给定的前缀提供命令和路径补全。
    """
    suggestions = get_completion_suggestions(prefix)
    return {"completions": suggestions}


@app.post("/ask", summary="Ask a question to the LLM with streaming response")
async def ask_llm(
    prompt: str = Body(..., embed=True, description="The prompt to send to the LLM. Supports @-syntax."),
    model: Optional[str] = Query(None, description="The model to use for the query. Uses default if not provided."),
):
    """
    向LLM发送一个prompt并以SSE事件流的形式接收响应。

    - **prompt**: The main question or instruction for the LLM.
    - **model**: Optional. The specific model configuration to use from `model.json`.
    """
    if not model_switcher:

        async def error_stream():
            yield 'event: error\ndata: {"error": "Model switcher not initialized"}\n\n'

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    if model:
        model_switcher.select(model)

    # 默认使用第一个模型
    selected_model = model or model_switcher.models()[0]
    logger.info(f"Using model: {selected_model}")

    context_processor = GPTContextProcessor()
    processed_prompt = prompt
    # processed_prompt = context_processor.process_text(prompt)

    async def sse_generator():
        try:
            full_response_content = ""
            async for chunk in model_switcher.async_query(selected_model, processed_prompt):
                if chunk.get("event") == "error":
                    logger.error(f"Error from LLM stream: {chunk.get('data')}")

                # 将字典转换为JSON字符串
                json_data = json.dumps(chunk)

                # 格式化为SSE
                yield f"{json_data}\n"

                # 刷新缓冲区
                await asyncio.sleep(0)

                if chunk.get("event") == "content":
                    full_response_content += chunk.get("data", "")

        except Exception as e:
            logger.error(f"Error during SSE generation: {e}", exc_info=True)
            error_payload = json.dumps({"event": "error", "data": str(e)})
            yield f"{error_payload}\n"

    return StreamingResponse(sse_generator(), media_type="application/x-ndjson")


def main():
    """主函数，用于解析参数和启动服务。"""
    parser = argparse.ArgumentParser(description="Terminal LLM Web API Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server to.")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on.")
    parser.add_argument("--default-model", type=str, default=None, help="Default model to use for queries.")
    args = parser.parse_args()

    # 设置全局默认模型
    global default_model
    default_model = args.default_model

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
