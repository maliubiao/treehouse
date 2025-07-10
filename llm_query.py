#!/usr/bin/env python
"""
LLM 查询工具模块

该模块提供与OpenAI兼容 API交互的功能，支持代码分析、多轮对话、剪贴板集成等功能。
包含代理配置检测、代码分块处理、对话历史管理等功能。
"""

import argparse
import contextlib
import datetime
import difflib
import fnmatch
import glob
import json
import logging
import marshal
import os
import pprint
import re
import subprocess
import sys
import tempfile
import threading
import time
import trace
import traceback
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import requests
import yaml
from colorama import Fore, just_fix_windows_console
from colorama import Style as ColorStyle
from openai import OpenAI
from pygments import highlight
from pygments.formatters.terminal import TerminalFormatter
from pygments.lexers.diff import DiffLexer

from debugger.tracer import trace
from tools.replace_engine import LLMInstructionParser, ReplaceEngine, TagRandomizer
from tree import (
    BINARY_MAGIC_NUMBERS,
    GLOBAL_PROJECT_CONFIG,
    LLM_PROJECT_CONFIG,
    BlockPatch,
    ConfigLoader,
    RipgrepSearcher,
    SyntaxHighlight,
    find_diff,
    find_patch,
)
from tree_libs.app import FileSearchResult, FileSearchResults, MatchResult

just_fix_windows_console()
sys.path.insert(0, os.path.dirname(__file__))


class ModelConfig:
    key: str
    base_url: str
    model_name: str
    tokenizer_name: str
    max_context_size: int | None = None
    temperature: float = 0.0
    is_thinking: bool = False
    max_tokens: int | None = None
    thinking_budget: int = 32768
    top_k: int = 20
    top_p: float = 0.95
    price_1m_input: float | None = None
    price_1m_output: float | None = None
    http_proxy: str | None = None
    https_proxy: str | None = None
    supports_json_output: bool = False  # 新增JSON输出支持字段

    def __init__(
        self,
        key: str,
        base_url: str,
        model_name: str,
        tokenizer_name: str | None = None,
        max_context_size: int | None = None,
        temperature: float = 0.0,
        is_thinking: bool = False,
        max_tokens: int | None = None,
        thinking_budget: int = 32768,
        top_k: int = 20,
        top_p: float = 0.95,
        price_1m_input: float | None = None,
        price_1m_output: float | None = None,
        http_proxy: str | None = None,
        https_proxy: str | None = None,
        supports_json_output: bool = False,  # 新增参数
    ):
        self.key = key
        self.base_url = base_url
        self.model_name = model_name
        self.tokenizer_name = tokenizer_name or model_name
        self.max_context_size = max_context_size
        self.temperature = temperature
        self.is_thinking = is_thinking
        self.max_tokens = max_tokens
        self.thinking_budget = thinking_budget
        self.top_k = top_k
        self.top_p = top_p
        self.price_1m_input = price_1m_input
        self.price_1m_output = price_1m_output
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self.supports_json_output = supports_json_output  # 初始化

    def __repr__(self) -> str:
        masked_key = f"{self.key[:3]}***" if self.key else "None"
        return (
            f"ModelConfig(base_url={self.base_url!r}, model_name={self.model_name!r}, "
            f"tokenizer_name={self.tokenizer_name!r}, "
            f"max_context_size={self.max_context_size}, temperature={self.temperature}, "
            f"is_thinking={self.is_thinking}, max_tokens={self.max_tokens}, "
            f"thinking_budget={self.thinking_budget}, top_k={self.top_k}, top_p={self.top_p}, "
            f"price_1M_input={self.price_1m_input}, price_1M_output={self.price_1m_output}, "
            f"http_proxy={self.http_proxy}, https_proxy={self.https_proxy}, "
            f"supports_json_output={self.supports_json_output}, "  # 新增字段
            f"key={masked_key})"
        )

    def get_debug_info(self) -> dict:
        """获取用于调试的配置信息"""
        return {
            "base_url": self.base_url,
            "model_name": self.model_name,
            "tokenizer_name": self.tokenizer_name,
            "max_context_size": self.max_context_size,
            "temperature": self.temperature,
            "is_thinking": self.is_thinking,
            "max_tokens": self.max_tokens,
            "thinking_budget": self.thinking_budget,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "price_1M_input": self.price_1m_input,
            "price_1M_output": self.price_1m_output,
            "http_proxy": self.http_proxy,
            "https_proxy": self.https_proxy,
            "supports_json_output": self.supports_json_output,  # 新增字段
            "key_prefix": self.key[:3] + "***" if self.key else "None",
        }

    @classmethod
    def from_env(cls) -> "ModelConfig":
        key = os.environ.get("GPT_KEY")
        if not key:
            raise ValueError("环境变量GPT_KEY未设置")
        base_url = os.environ.get("GPT_BASE_URL")
        if not base_url:
            raise ValueError("环境变量GPT_BASE_URL未设置")

        try:
            parsed_url = urlparse(base_url)
            if not all([parsed_url.scheme, parsed_url.netloc]):
                raise ValueError(f"无效的base_url格式: {base_url}")
        except Exception as e:
            raise ValueError("解析base_url失败") from e

        model_name = os.environ.get("GPT_MODEL")
        if not model_name:
            raise ValueError("环境变量GPT_MODEL未设置")

        tokenizer_name = os.environ.get("GPT_TOKENIZER")

        max_context_size = os.environ.get("GPT_MAX_CONTEXT_SIZE")
        temperature = os.environ.get("GPT_TEMPERATURE")
        is_thinking = os.environ.get("GPT_IS_THINKING")
        max_tokens = os.environ.get("GPT_MAX_TOKENS")
        thinking_budget = os.environ.get("GPT_THINKING_BUDGET")
        top_k = os.environ.get("GPT_TOP_K")
        top_p = os.environ.get("GPT_TOP_P")
        price_1M_input = os.environ.get("GPT_PRICE_INPUT")
        price_1M_output = os.environ.get("GPT_PRICE_OUTPUT")
        supports_json_output = os.environ.get("GPT_SUPPORTS_JSON_OUTPUT")  # 新增环境变量

        # 从环境变量加载代理设置
        http_proxy = os.environ.get("HTTP_PROXY")
        https_proxy = os.environ.get("HTTPS_PROXY")

        if max_context_size is not None:
            try:
                max_context_size = int(max_context_size)
            except ValueError as e:
                raise ValueError(f"无效的max_context_size值: {max_context_size}") from e
        else:
            max_context_size = 16384

        try:
            temperature = float(temperature) if temperature is not None else 0.0
        except ValueError as exc:
            raise ValueError(f"无效的temperature值: {temperature}") from exc

        try:
            is_thinking = str(is_thinking).lower() == "true" if is_thinking is not None else False
        except ValueError as exc:
            raise ValueError(f"无效的is_thinking值: {is_thinking}") from exc

        try:
            max_tokens = int(max_tokens) if max_tokens is not None else None
        except ValueError as exc:
            raise ValueError(f"无效的max_tokens值: {max_tokens}") from exc

        try:
            thinking_budget = int(thinking_budget) if thinking_budget is not None else 32768
        except ValueError as exc:
            raise ValueError(f"无效的thinking_budget值: {thinking_budget}") from exc

        try:
            top_k = int(top_k) if top_k is not None else 20
        except ValueError as exc:
            raise ValueError(f"无效的top_k值: {top_k}") from exc

        try:
            top_p = float(top_p) if top_p is not None else 0.95
        except ValueError as exc:
            raise ValueError(f"无效的top_p值: {top_p}") from exc

        try:
            price_1M_input = float(price_1M_input) if price_1M_input is not None else None
        except ValueError as exc:
            raise ValueError(f"无效的price_1M_input值: {price_1M_input}") from exc

        try:
            price_1M_output = float(price_1M_output) if price_1M_output is not None else None
        except ValueError as exc:
            raise ValueError(f"无效的price_1M_output值: {price_1M_output}") from exc

        try:
            supports_json_output = str(supports_json_output).lower() == "true" if supports_json_output else False
        except ValueError as exc:
            raise ValueError(f"无效的supports_json_output值: {supports_json_output}") from exc

        return cls(
            key=key,
            base_url=base_url,
            model_name=model_name,
            tokenizer_name=tokenizer_name,
            max_context_size=max_context_size,
            temperature=temperature,
            is_thinking=is_thinking,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            top_k=top_k,
            top_p=top_p,
            price_1M_input=price_1M_input,
            price_1M_output=price_1M_output,
            http_proxy=http_proxy,
            https_proxy=https_proxy,
            supports_json_output=supports_json_output,  # 传递参数
        )


GLOBAL_MODEL_CONFIG = None
MAX_FILE_SIZE = 32000
LAST_QUERY_FILE = os.path.join(os.path.dirname(__file__), ".lastquery")
PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


@dataclass
class TextNode:
    """纯文本节点"""

    content: str


@dataclass
class CmdNode:
    """命令节点"""

    command: str
    command_type: str | None = None
    args: List[str] | None = None


@dataclass
class SearchSymbolNode:
    """符号节点"""

    symbols: List[str]


@dataclass
class TemplateNode:
    """模板节点，可能包含多个命令节点"""

    template: CmdNode
    commands: List[CmdNode]


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="终端智能AI辅助工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="要分析的源代码文件路径")
    group.add_argument("--ask", help="直接提供提示词内容，与--file互斥")
    group.add_argument(
        "--chatbot",
        action="store_true",
        help="进入聊天机器人UI模式，与--file和--ask互斥",
    )
    group.add_argument(
        "--project-search",
        nargs="+",
        metavar="KEYWORD",
        help="执行项目关键词搜索(支持多词)",
    )
    group.add_argument("--pylint-log", type=Path, help="执行Pylint修复的日志文件路径")
    parser.add_argument("--workflow", action="store_true", help="进入工作流执行模式")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), ".llm_project.yml"),
        type=Path,
        help="项目配置文件路径（YAML格式）",
    )
    parser.add_argument(
        "--obsidian-doc",
        default=os.environ.get("GPT_DOC", os.path.join(os.path.dirname(__file__), "obsidian")),
        help="Obsidian文档备份目录路径",
    )
    parser.add_argument("--trace", action="store_true", help="启用详细的执行跟踪")
    parser.add_argument(
        "--architect",
        required="--workflow" in sys.argv,
        help="架构师模型名称（工作流模式必需）",
    )
    parser.add_argument(
        "--coder",
        required="--workflow" in sys.argv,
        help="编码器模型名称（工作流模式必需）",
    )
    return parser.parse_args()


def sanitize_proxy_url(url):
    """隐藏代理地址中的敏感信息"""
    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
        return url
    except ValueError as e:
        print(f"解析代理URL失败: {e}")
        return url


def detect_proxies():
    """检测并构造代理配置"""
    proxies = {}
    sources = {}
    proxy_vars = [
        ("http", ["http_proxy", "HTTP_PROXY"]),
        ("https", ["https_proxy", "HTTPS_PROXY"]),
        ("all", ["all_proxy", "ALL_PROXY"]),
    ]

    # 修改代理检测顺序，先处理具体协议再处理all_proxy
    for protocol, proxy_vars in reversed(proxy_vars):
        for var in proxy_vars:
            if var in os.environ and os.environ[var]:
                url = os.environ[var]
                if protocol == "all":
                    if not proxies.get("http"):
                        proxies["http"] = url
                        sources["http"] = var
                    if not proxies.get("https"):
                        proxies["https"] = url
                        sources["https"] = var
                else:
                    if protocol not in proxies:
                        proxies[protocol] = url
                        sources[protocol] = var
                break
    return proxies, sources


def split_code(content, chunk_size):
    """将代码内容分割成指定大小的块
    注意：当前实现适用于英文字符场景，如需支持多语言建议改用更好的分块算法
    """
    return [content[i : i + chunk_size] for i in range(0, len(content), chunk_size)]


INDEX_PATH = Path(__file__).parent / "conversation" / "index.json"


def _ensure_index():
    """确保索引文件存在，不存在则创建空索引"""
    if not INDEX_PATH.exists():
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(INDEX_PATH, "w", encoding="utf8") as f:
            json.dump({}, f)


def _update_index(uuid, file_path):
    """更新索引文件"""
    _ensure_index()
    with open(INDEX_PATH, "r+", encoding="utf8") as f:
        index = json.load(f)
        index[uuid] = str(file_path)
        f.seek(0)
        json.dump(index, f, indent=4)
        f.truncate()


def _build_index():
    """遍历目录构建索引"""
    index = {}
    conv_dir = Path(__file__).parent / "conversation"

    # 匹配文件名模式：任意时间戳 + UUID
    pattern = re.compile(r"^\d{1,2}-\d{1,2}-\d{1,2}-(.+?)\.json$")

    for root, _, files in os.walk(conv_dir):
        for filename in files:
            # 跳过索引文件本身
            if filename == "index.json":
                continue

            match = pattern.match(filename)
            if match:
                uuid = match.group(1)
                full_path = Path(root) / filename
                index[uuid] = str(full_path)

    with open(INDEX_PATH, "w", encoding="utf8") as f:
        json.dump(index, f, indent=4)

    return index


def get_conversation(uuid):
    """获取对话记录"""
    try:
        # 先尝试读取索引
        with open(INDEX_PATH, "r", encoding="utf8") as f:
            index = json.load(f)
            if uuid in index:
                path = Path(index[uuid])
                if path.exists():
                    return path
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # 索引不存在或查找失败，重新构建索引
    index = _build_index()
    if uuid in index:
        return index[uuid]

    raise FileNotFoundError(f"Conversation with UUID {uuid} not found")


def new_conversation(uuid):
    """创建新对话记录"""
    current_datetime = datetime.datetime.now()

    # 生成日期路径组件（自动补零）
    date_dir = current_datetime.strftime("%Y-%m-%d")
    time_str = current_datetime.strftime("%H-%M-%S")

    # 构建完整路径
    base_dir = Path(__file__).parent / "conversation" / date_dir
    filename = f"{time_str}-{uuid}.json"
    file_path = base_dir / filename

    # 确保目录存在
    base_dir.mkdir(parents=True, exist_ok=True)

    # 写入初始数据并更新索引
    with open(file_path, "w", encoding="utf8") as f:
        json.dump([], f, indent=4)

    _update_index(uuid, file_path)
    return str(file_path)


def load_conversation_history(file_path):
    """加载对话历史文件"""
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    except (IOError, json.JSONDecodeError) as e:
        print(f"加载对话历史失败: {e}")
        return []


def save_conversation_history(file_path, history):
    """保存对话历史到文件"""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"保存对话历史失败: {e}")


def query_gpt_api(
    api_key: str,
    prompt: str,
    model: str = "gpt-4",
    **kwargs,
) -> dict:
    """支持多轮对话的OpenAI API流式查询

    参数:
        api_key (str): OpenAI API密钥
        prompt (str): 用户输入的提示词
        model (str): 使用的模型名称，默认为gpt-4
        kwargs: 其他可选参数，包括:
            base_url (str): API基础URL
            conversation_file (str): 对话历史存储文件路径
            console: 控制台输出对象
            temperature (float): 生成温度
            proxies: 代理设置
            thinking_budget (int): 思考预算限制
            top_k (int): 采样时保留的top k个token
            top_p (float): 核采样概率阈值
            use_json_output (bool): 是否强制使用JSON输出模式

    返回:
        dict: 包含API响应结果的字典

    假设:
        - api_key是有效的OpenAI API密钥
        - prompt是非空字符串
        - conversation_file路径可写
        如果不符合上述假设，将记录错误并退出程序
    """
    try:
        # 初始化对话历史
        history = _initialize_conversation_history(kwargs)

        # 添加用户新提问到历史
        history.append({"role": "user", "content": prompt})

        # 获取模型配置
        model_config = kwargs.get("model_config") or GLOBAL_MODEL_CONFIG

        # 获取API响应
        response = _get_api_response(api_key, model, history, kwargs)
        # 处理并保存响应
        return _process_and_save_response(model, response, history, kwargs)

    except requests.exceptions.HTTPError as he:
        if not GLOBAL_MODEL_CONFIG:
            model_config = kwargs.get("model_config")
        else:
            model_config = GLOBAL_MODEL_CONFIG
        debug_info = model_config.get_debug_info()
        error_msg = f"API请求失败 HTTP {he.response.status_code}\n"
        error_msg += f"请求配置: {debug_info}\n"

        if he.response.status_code in (401, 403):
            error_msg += "可能原因: 1. API密钥无效 2. 账户欠费 3. 权限不足\n"
            error_msg += f"请检查密钥前三位: {debug_info['key_prefix']} 是否正确"

        raise RuntimeError(error_msg) from he

    except requests.exceptions.RequestException as req_exc:
        if not GLOBAL_MODEL_CONFIG:
            model_config: ModelConfig = kwargs.get("model_config")
        else:
            model_config = GLOBAL_MODEL_CONFIG
        debug_info = model_config.get_debug_info()
        error_msg = f"网络请求异常: {str(req_exc)}\n"
        error_msg += f"当前配置: {debug_info}"
        raise RuntimeError(error_msg) from req_exc

    except RuntimeError as runtime_exc:
        print(f"详细错误信息: {str(runtime_exc)}")
        raise runtime_exc
    except (ValueError, TypeError, KeyError) as specific_exc:
        if not GLOBAL_MODEL_CONFIG:
            model_config = kwargs.get("model_config")
        else:
            model_config = GLOBAL_MODEL_CONFIG
        debug_info = model_config.get_debug_info()
        error_msg = f"特定类型错误: {str(specific_exc)}\n"
        error_msg += f"配置状态: {debug_info}"
        print(error_msg)
        raise ValueError(error_msg) from specific_exc


def get_conversation_file(file):
    if file:
        return file
    cid = os.environ.get("GPT_UUID_CONVERSATION")

    if cid:
        try:
            conversation_file = get_conversation(cid)
        except FileNotFoundError:
            conversation_file = new_conversation(cid)
    else:
        conversation_file = os.path.join(os.path.dirname(__file__), "conversation_history.json")
    return conversation_file


def _initialize_conversation_history(kwargs: dict) -> list:
    """初始化对话历史

    参数:
        kwargs (dict): 包含conversation_file等参数

    返回:
        list: 对话历史列表
    """
    if kwargs.get("disable_conversation_history"):
        return []
    conversation_file = kwargs.get(
        "conversation_file",
    )
    return load_conversation_history(get_conversation_file(conversation_file))


def _get_api_response(
    api_key: str,
    model: str,
    history: list,
    kwargs: dict,
):
    """获取API流式响应

    参数:
        api_key (str): API密钥
        model (str): 模型名称
        history (list): 对话历史
        kwargs (dict): 其他参数

    返回:
        Generator or ChatCompletion: 流式响应生成器或完整的ChatCompletion对象
    """
    # 检查是否为Gemini模型
    is_gemini = "gemini" in model.lower()

    if is_gemini:
        try:
            from google import genai

            client = genai.Client(api_key=api_key)

            # 提取系统消息作为system_instruction
            system_instructions = "\n".join(
                [msg["content"] for msg in history if msg.get("role") == "system" and msg.get("content")]
            )

            # 构建Gemini兼容的消息格式
            gemini_contents = []
            for msg in history:
                role = msg.get("role")
                content = msg.get("content")

                # 跳过系统消息和空内容
                if role == "system" or not content:
                    continue

                # 转换角色为Gemini格式
                gemini_role = "user" if role == "user" else "model"

                # 构建parts格式为[{"text": content}]
                gemini_contents.append({"role": gemini_role, "parts": [{"text": content}]})

            if not gemini_contents:
                raise ValueError("转换后的Gemini历史记录为空，请检查输入。")

            # 创建Gemini流式请求
            return client.models.generate_content_stream(
                model=model,
                contents=gemini_contents,
            )
        except ImportError:
            raise RuntimeError("使用Gemini模型需要安装google-generativeai库")
    else:
        # 原始OpenAI实现
        client = OpenAI(api_key=api_key, base_url=kwargs.get("base_url"))
        extra_body = {}
        # extra_body = {
        #    "enable_thinking": True if kwargs.get("enable_thinking") else False,
        #    "thinking_budget": kwargs.get("thinking_budget", 32 * 1024),
        # }

        model_config = kwargs.get("model_config") or GLOBAL_MODEL_CONFIG
        use_json_output = kwargs.get("use_json_output", False)
        is_json_mode = use_json_output and model_config and model_config.supports_json_output

        create_params = {
            "model": model,
            "messages": history,
            # "reasoning_effort": "medium",
            "temperature": kwargs.get("temperature", 0.0),
            "extra_body": extra_body,
            "top_p": 0.8,
        }

        if is_json_mode:
            create_params["stream"] = False
            create_params["response_format"] = {"type": "json_object"}
        else:
            create_params["stream"] = True

        try:
            return client.chat.completions.create(**create_params)
        except Exception as e:
            err_msg = f"API请求失败: {str(e)}"
            raise RuntimeError(err_msg) from e


def _process_and_save_response(
    model: str,
    stream_client,
    history: list,
    kwargs: dict,
) -> dict:
    """处理并保存API响应

    参数:
        stream (Generator): 流式响应
        history (list): 对话历史
        kwargs (dict): 包含conversation_file等参数

    返回:
        dict: 处理后的响应结果，新增usage字段
    """
    content, reasoning, usage = _process_stream_response(stream_client, history, model, **kwargs)  # 接收usage信息

    # 将助理回复添加到历史
    history.append({"role": "assistant", "content": content})

    # 保存更新后的对话历史
    if not kwargs.get("disable_conversation_history"):
        save_conversation_history(get_conversation_file(kwargs.get("conversation_file")), history)

    # 处理think标签
    content, reasoning = _handle_think_tags(content, reasoning)

    # 存储思维过程
    if reasoning:
        content = f"\n\n\n{content}"

    # 返回结果，新增usage字段
    return {
        "choices": [{"message": {"content": content}}],
        "usage": usage or {},  # 确保usage不为空
    }


def _process_stream_response(stream_client, history, model, **kwargs) -> tuple:
    """处理流式响应

    参数:
        stream (Generator): 流式响应
        history (list): 对话历史
        model (str): 模型名称
        console: 控制台输出对象

    返回:
        tuple: (正式内容, 推理内容, token使用情况)
    """
    content = ""
    reasoning = ""
    usage = None  # 初始化usage为None
    console = kwargs.get("console")
    verbose = kwargs.get("verbose", True)
    is_gemini = "gemini" in model.lower()

    if is_gemini:
        # 处理Gemini流式响应
        for chunk in stream_client:
            # 正确访问text属性
            chunk_text = chunk.text if hasattr(chunk, "text") else ""
            if verbose:
                _print_content(chunk_text, console)
            content += chunk_text
            # 如果有usage_metadata则记录
            if hasattr(chunk, "usage_metadata"):
                usage = {
                    "prompt_tokens": chunk.usage_metadata.prompt_token_count,
                    "completion_tokens": chunk.usage_metadata.candidates_token_count,
                    "total_tokens": chunk.usage_metadata.total_token_count,
                }
    else:
        # 原始OpenAI处理逻辑
        for chunk in stream_client:
            # 检查并记录token使用情况
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {"prompt_tokens": chunk.usage.prompt_tokens, "completion_tokens": chunk.usage.completion_tokens}
            # 处理推理内容
            if hasattr(chunk.choices[0].delta, "reasoning_content") and chunk.choices[0].delta.reasoning_content:
                if verbose:
                    _print_content(chunk.choices[0].delta.reasoning_content, console, style="#00ff00")
                reasoning += chunk.choices[0].delta.reasoning_content

            # 处理正式回复内容
            if chunk.choices[0].delta.content:
                if verbose:
                    _print_content(chunk.choices[0].delta.content, console)
                content += chunk.choices[0].delta.content

    if verbose:
        _print_newline(console)

    # 如果Gemini响应未提供usage，尝试从最后一块获取
    if is_gemini and usage is None and hasattr(stream_client, "usage_metadata"):
        usage = {
            "prompt_tokens": stream_client.usage_metadata.prompt_token_count,
            "completion_tokens": stream_client.usage_metadata.candidates_token_count,
            "total_tokens": stream_client.usage_metadata.total_token_count,
        }

    return content, reasoning, usage  # 返回新增的usage信息


def _handle_think_tags(content: str, reasoning: str) -> tuple:
    """处理think标签

    参数:
        content (str): 原始内容
        reasoning (str): 推理内容

    返回:
        tuple: 处理后的内容和推理内容
    """
    thinking_end_tag = "</think>\n\n"
    thinking_start_tag = "<think>"

    if content and (content.find(thinking_end_tag) != -1 or content.find(thinking_start_tag) != -1):
        if content.find(thinking_start_tag) != -1:
            pos_start = content.find(thinking_start_tag)
            pos_end = content.find(thinking_end_tag)
            if pos_end != -1:
                reasoning = content[pos_start + len(thinking_start_tag) : pos_end]
                reasoning = reasoning.replace("\\n", "\n")
                content = content[pos_end + len(thinking_end_tag) :]
        else:
            pos = content.find(thinking_end_tag)
            reasoning = content[:pos]
            reasoning = reasoning.replace("\\n", "\n")
            content = content[pos + len(thinking_end_tag) :]

    return content, reasoning


def _print_content(content: str, console, style=None) -> None:
    """打印内容到控制台

    参数:
        content (str): 要打印的内容
        console: 控制台输出对象
        style: 输出样式
    """
    if console:
        console.print(content, end="", style=style)
    else:
        print(content, end="", flush=True)


def _print_newline(console) -> None:
    """打印换行符

    参数:
        console: 控制台输出对象
    """
    if console:
        console.print()
    else:
        print()


def _check_tool_installed(
    tool_name: str,
    install_url: str | None = None,
    install_commands: list[str] | None = None,
) -> bool:
    """检查指定工具是否已安装

    Args:
        tool_name: 需要检查的命令行工具名称
        install_url: 该工具的安装文档URL
        install_commands: 适用于不同平台的安装命令列表

    Raises:
        ValueError: 当输入参数不符合约定时（非阻断性错误，会继续执行）

    输入假设:
        1. tool_name必须是有效的可执行文件名称
        2. install_commands应为非空列表（当需要显示安装指引时）
        3. 系统环境PATH配置正确，能正确找到已安装工具
    """
    # 参数前置校验
    if not isinstance(tool_name, str) or not tool_name:
        print(f"参数校验失败: tool_name需要非空字符串，收到类型：{type(tool_name)}")
        return False

    if install_commands and (
        not isinstance(install_commands, list) or any(not isinstance(cmd, str) for cmd in install_commands)
    ):
        print("参数校验失败: install_commands需要字符串列表")
        return False

    try:
        check_cmd = ["where", tool_name] if sys.platform == "win32" else ["which", tool_name]
        subprocess.run(
            check_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        print(f"依赖缺失: {tool_name} 未安装")
        if install_url:
            print(f"|-- 安装文档: {install_url}")
        if install_commands:
            print("|-- 可用安装命令:")
            for cmd in install_commands:
                print(f"|   {cmd}")
        return False


def check_deps_installed() -> bool:
    """检查系统环境是否满足依赖要求

    Returns:
        bool: 所有必需依赖已安装返回True，否则False

    输入假设:
        1. GPT_FLAGS全局变量已正确初始化
        2. 当GPT_FLAG_GLOW标志启用时才需要检查glow
        3. Windows系统需要pywin32访问剪贴板
        4. Linux系统需要xclip或xsel工具
    """
    all_installed = True

    # 检查glow（条件性检查）
    if GPT_FLAGS.get(GPT_FLAG_GLOW, False):
        if not _check_tool_installed(
            tool_name="glow",
            install_url="https://github.com/charmbracelet/glow",
            install_commands=[
                "brew install glow  # macOS",
                "choco install glow  # Windows",
                "scoop install glow  # Windows",
                "winget install charmbracelet.glow  # Windows",
            ],
        ):
            all_installed = False

    # 检查tree命令
    if not _check_tool_installed(
        tool_name="tree",
        install_commands=[
            "sudo apt install tree  # Debian/Ubuntu",
            "sudo yum install tree  # RHEL/CentOS",
            "brew install tree  # macOS",
        ],
    ):
        all_installed = False

    # 检查剪贴板支持
    if sys.platform == "win32":
        try:
            import win32clipboard  # type: ignore

            win32clipboard.OpenClipboard()  # 实际使用导入的模块
            win32clipboard.CloseClipboard()
        except ImportError:
            print("剪贴板支持缺失: 需要pywin32包")
            print("解决方案: pip install pywin32")
            all_installed = False
    elif sys.platform == "linux":  # 精确匹配Linux平台
        clipboard_ok = any(
            [
                _check_tool_installed(
                    "xclip",
                    install_commands=[
                        "sudo apt install xclip  # Debian/Ubuntu",
                        "sudo yum install xclip  # RHEL/CentOS",
                    ],
                ),
                _check_tool_installed(
                    "xsel",
                    install_commands=[
                        "sudo apt install xsel  # Debian/Ubuntu",
                        "sudo yum install xsel  # RHEL/CentOS",
                    ],
                ),
            ]
        )
        if not clipboard_ok:
            all_installed = False

    return all_installed


def get_directory_context_wrapper(tag):
    if tag.command == "treefull":
        text = get_directory_context(1024)
    else:
        text = get_directory_context(1)
    return f"\n[directory tree start]\n{text}\n[directory tree end]\n"


def get_directory_context(max_depth=1, current_dir: Optional[str] = None):
    """获取当前目录上下文信息（支持动态层级控制）"""
    try:
        if not current_dir:
            current_dir = os.getcwd()
        # Windows系统处理
        if sys.platform == "win32":
            if max_depth == 1:
                # 当max_depth为1时使用dir命令
                dir_result = subprocess.run(["dir"], stdout=subprocess.PIPE, text=True, shell=True, check=True)
                msg = dir_result.stdout or "无法获取目录信息"
                return f"\n当前工作目录: {current_dir}\n\n目录结构:\n{msg}"
            # 其他情况使用tree命令
            cmd = ["tree"]
            if max_depth is not None:
                cmd.extend(["/A", "/F"])
        else:
            # 非Windows系统使用Linux/macOS的tree命令
            cmd = ["tree", current_dir]
            if max_depth is not None:
                cmd.extend(["-L", str(max_depth)])
            # 添加gitignore支持
            cmd.append("--gitignore")

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                text=True,
                shell=(sys.platform == "win32"),
            )
            output = result.stdout
            return f"\n当前工作目录: {current_dir}\n\n目录结构:\n{output}"
        except subprocess.CalledProcessError:
            # 当tree命令失败时使用替代命令
            if sys.platform == "win32":
                # Windows使用dir命令
                dir_result = subprocess.run(["dir"], stdout=subprocess.PIPE, check=True, text=True, shell=True)
                msg = dir_result.stdout or "无法获取目录信息"
            else:
                # 非Windows使用ls命令
                ls_result = subprocess.run(["ls", "-l"], stdout=subprocess.PIPE, text=True, check=True)
                msg = ls_result.stdout or "无法获取目录信息"

            return f"\n当前工作目录: {current_dir}\n\n目录结构:\n{msg}"

    except (OSError, subprocess.SubprocessError) as e:
        return f"获取目录上下文时出错: {str(e)}"


def get_clipboard_content(_):
    text = get_clipboard_content_string()
    text = f"\n[clipboard content start]\n{text}\n[clipboard content end]\n"
    return text


class ClipboardMonitor:
    def __init__(self, debug=False):
        self.collected_contents = []
        self.should_stop = False
        self.lock = threading.Lock()
        self.monitor_thread = None
        self.debug = debug
        self._debug_print("ClipboardMonitor 初始化完成")

    def _debug_print(self, message):
        """调试信息输出函数"""
        if self.debug:
            print(f"[DEBUG] {message}")

    def _monitor_clipboard(self):
        """后台线程执行的剪贴板监控逻辑"""
        last_content = ""
        initial_content = None  # 用于存储第一次获取的内容
        first_run = True  # 标记是否是第一次运行
        ignore_initial = True  # 标记是否继续忽略初始内容
        self._debug_print("开始执行剪贴板监控线程")
        while not self.should_stop:
            try:
                self._debug_print("尝试获取剪贴板内容...")
                current_content = get_clipboard_content_string()

                if first_run:
                    # 第一次运行，记录初始内容并跳过
                    initial_content = current_content
                    first_run = False
                    self._debug_print("忽略初始剪贴板内容")
                elif current_content and current_content != last_content:
                    # 当内容不为空且与上次不同时
                    if ignore_initial and current_content != initial_content:
                        # 如果还在忽略初始内容阶段，且当前内容不等于初始内容
                        ignore_initial = False  # 停止忽略初始内容
                        self._debug_print("检测到内容变化，停止忽略初始内容")

                    if not ignore_initial or current_content != initial_content:
                        # 如果已经停止忽略初始内容，或者当前内容不等于初始内容
                        with self.lock:
                            print(f"获得片断: ${current_content}")
                            self.collected_contents.append(current_content)
                            self._debug_print(
                                f"已捕获第 {len(self.collected_contents)} 段内容，内容长度: {len(current_content)}"
                            )
                    last_content = current_content
                else:
                    self._debug_print("内容未变化/为空，跳过保存")

                time.sleep(0.5)

            except Exception as e:
                self._debug_print(f"剪贴板监控出错: {str(e)}")
                self._debug_print("异常堆栈信息：")
                traceback.print_exc()
                break

    def start_monitoring(self):
        """启动剪贴板监控"""
        self._debug_print("准备启动剪贴板监控...")
        self.should_stop = False
        self.monitor_thread = threading.Thread(target=self._monitor_clipboard)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        self._debug_print(f"剪贴板监控线程已启动，线程ID: {self.monitor_thread.ident}")
        print("开始监听剪贴板，新复制**新**内容，按回车键结束...")

    def stop_monitoring(self):
        """停止剪贴板监控"""
        self._debug_print("准备停止剪贴板监控...")
        self.should_stop = True

        if self.monitor_thread and self.monitor_thread.is_alive():
            self._debug_print("等待监控线程结束...")
            self.monitor_thread.join(timeout=1)
            if self.monitor_thread.is_alive():
                self._debug_print("警告：剪贴板监控线程未正常退出")
            else:
                self._debug_print("监控线程已正常退出")

    def get_results(self):
        """获取监控结果"""
        self._debug_print("获取监控结果...")
        with self.lock:
            if self.collected_contents:
                contents = []
                for content in self.collected_contents:
                    contents.append(f"\n[clipboard content start]\n{content}\n[clipboard content end]\n")
                self._debug_print(f"返回 {len(self.collected_contents)} 段内容")
                return "".join(contents)
            self._debug_print("未捕获到任何内容")
            return "未捕获到任何剪贴板内容"


def monitor_clipboard(_, debug=False):
    """主函数：启动剪贴板监控并等待用户输入"""
    monitor = ClipboardMonitor(debug=debug)
    monitor.start_monitoring()
    result = ""
    try:
        print("等待用户复制...")
        if sys.platform == "win32":
            import msvcrt

            while not monitor.should_stop:
                if msvcrt.kbhit():
                    if msvcrt.getch() == b"\r":
                        print("检测到回车键")
                        break
                time.sleep(0.1)
        else:
            import select

            while not monitor.should_stop:
                if select.select([sys.stdin], [], [], 0)[0]:
                    if sys.stdin.read(1) == "\n":
                        print("检测到回车键")
                        break
                time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n用户中断操作")
    finally:
        monitor.stop_monitoring()
        result = monitor.get_results()
    print("已停止监听", result)
    return result


def get_clipboard_content_string():
    """获取剪贴板内容的封装函数，统一返回字符串内容，支持图像输出到临时目录"""
    try:
        if sys.platform == "win32":
            return _handle_windows_clipboard()
        if sys.platform == "darwin":
            return _handle_macos_clipboard()
        return _handle_linux_clipboard()
    except (FileNotFoundError, subprocess.CalledProcessError, ImportError) as e:
        print(f"获取剪贴板内容时出错: {str(e)}")
        return f"获取剪贴板内容时出错: {str(e)}"


def _handle_windows_clipboard():
    """处理Windows平台的剪贴板内容"""
    win32clipboard = __import__("win32clipboard")
    win32clipboard.OpenClipboard()

    try:
        available_formats = _get_available_clipboard_formats(win32clipboard)

        if win32clipboard.CF_TEXT in available_formats or win32clipboard.CF_UNICODETEXT in available_formats:
            return _get_windows_text_content(win32clipboard)

        if win32clipboard.CF_DIB in available_formats:
            return _handle_windows_image(win32clipboard)

        return "[clipboard contains non-text data]"
    finally:
        win32clipboard.CloseClipboard()


def _get_available_clipboard_formats(win32clipboard):
    """获取剪贴板中可用的格式"""
    available_formats = []
    current_format = 0
    while True:
        current_format = win32clipboard.EnumClipboardFormats(current_format)
        if current_format == 0:
            break
        available_formats.append(current_format)
    return available_formats


def _get_windows_text_content(win32clipboard):
    """获取Windows剪贴板中的文本内容"""
    try:
        return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    except Exception:
        return win32clipboard.GetClipboardData(win32clipboard.CF_TEXT)


def format_image_path_prompt(image_path):
    return f"[image saved to {image_path}]"


def read_path_from_image_prompt(image_info):
    """从图像信息中提取路径"""
    prefix = "[image saved to "
    if image_info.startswith(prefix):
        start = len(prefix)
        end = image_info.rfind("]")
        return image_info[start:end]
    return None


def _handle_windows_image(win32clipboard):
    """处理Windows剪贴板中的图像内容"""

    image_data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
    temp_dir = tempfile.gettempdir()
    image_path = os.path.join(temp_dir, f"clipboard_image_{int(time.time())}.png")

    with open(image_path, "wb") as f:
        f.write(image_data)

    return format_image_path_prompt(image_path)


def _handle_macos_clipboard():
    """处理macOS平台的剪贴板内容"""
    try:
        AppKit = __import__("AppKit")

        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        if pasteboard.types().containsObject_(AppKit.NSPasteboardTypePNG):
            return _handle_macos_image(pasteboard)
    except ImportError:
        pass

    return _get_macos_text_content()


def _handle_macos_image(pasteboard):
    """处理macOS剪贴板中的图像内容"""
    AppKit = __import__("AppKit")
    image_data = pasteboard.dataForType_(AppKit.NSPasteboardTypePNG)
    if image_data:
        temp_dir = tempfile.gettempdir()
        image_path = os.path.join(temp_dir, f"clipboard_image_{int(time.time())}.png")
        assert image_data.writeToFile_atomically_(image_path, True)
        return format_image_path_prompt(image_path)
    return ""


def _get_macos_text_content():
    """获取macOS剪贴板中的文本内容"""
    result = subprocess.run(["pbpaste"], stdout=subprocess.PIPE, text=True, check=True)
    return result.stdout


def _handle_linux_clipboard():
    """处理Linux平台的剪贴板内容"""
    try:
        return _get_linux_text_content()
    except subprocess.CalledProcessError:
        return _handle_linux_image()
    except FileNotFoundError:
        return "无法获取剪贴板内容：未找到xclip或xsel"


def _get_linux_text_content():
    """获取Linux剪贴板中的文本内容"""
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError:
        result = subprocess.run(
            ["xsel", "--clipboard", "--output"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return result.stdout


def _handle_linux_image():
    """处理Linux剪贴板中的图像内容"""
    try:
        import tempfile

        temp_dir = tempfile.gettempdir()
        image_path = os.path.join(temp_dir, f"clipboard_image_{int(time.time())}.png")

        subprocess.run(
            ["xclip", "-selection", "clipboard", "-o", "-t", "image/png"],
            stdout=open(image_path, "wb"),
            check=True,
        )
        return format_image_path_prompt(image_path)
    except Exception:
        return "[clipboard contains non-text data]"


def fetch_url_content(url, is_news=False):
    """通过API获取URL对应的Markdown内容"""
    try:
        api_url = f"http://127.0.0.1:8000/convert?url={url}&is_news={is_news}"
        # 确保不使用任何代理
        session = requests.Session()
        session.trust_env = False  # 禁用从环境变量读取代理
        response = session.get(api_url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        return f"获取URL内容失败: {str(e)}"


def _handle_any_script(file_path: str) -> str:
    is_windows = os.name == "nt"

    # 检查shebang
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
    except Exception as e:
        return f"Failed to read script file: {e}"

    # 如果不是Python脚本且在Windows上，报错
    if is_windows and first_line.startswith("#!") and "python" not in first_line.lower():
        return f"Non-Python scripts are not supported on Windows: {first_line}"

    if not is_windows:
        if not os.access(file_path, os.X_OK):
            try:
                os.chmod(file_path, 0o755)
            except Exception as e:
                return f"Failed to make script executable: {e}"

    if is_windows or (first_line.startswith("#!") and "python" in first_line.lower()):
        command = f'python "{file_path}"'
    else:
        command = f'"{file_path}"'

    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True,
        )
        stdout, stderr = proc.communicate()
    except Exception as e:
        return f"Failed to execute script: {e}"

    output = f"\n\n[shell command]: {file_path}\n"

    if stdout:
        output += stdout
    if stderr:
        output += stderr
    if proc.returncode != 0:
        output += f"\nProcess exited with code {proc.returncode}"

    return output


def _handle_prompt_file(match: CmdNode) -> str:
    """处理prompts目录文件"""
    file_path = os.path.join(PROMPT_DIR, match.command)

    # 检查文件是否有可执行权限或以#!开头
    if os.name == "nt":  # Windows系统
        if file_path.lower().endswith(".exe"):
            return _handle_any_script(file_path)
    elif os.access(file_path, os.X_OK):
        return _handle_any_script(file_path)

    # 检查文件是否以#!开头
    with open(file_path, "r", encoding="utf-8") as f:
        first_line = f.readline()
        if first_line.startswith("#!"):
            return _handle_any_script(file_path)
        # 否则读取整个文件内容作为普通文件处理
        content = first_line + f.read()
        return f"\n{content}\n"


def _handle_project(yml_path: str) -> str:
    """处理YAML定义的项目上下文"""
    with open(yml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError(f"无效的项目配置文件格式: {yml_path}")

    if not config.get("files") and not config.get("dirs"):
        return ""

    # Check that existing fields are lists
    if config.get("files") is not None and not isinstance(config["files"], list):
        raise ValueError(f"'files' 字段必须是列表类型: {yml_path}")
    if config.get("dirs") is not None and not isinstance(config["dirs"], list):
        raise ValueError(f"'dirs' 字段必须是列表类型: {yml_path}")

    replacement = f"\n\n[project config start]: {yml_path}\n"

    # 处理文件列表
    for pattern in config.get("files", []):
        if not isinstance(pattern, str):
            replacement += f"[config error]: 文件模式必须是字符串: {pattern}\n\n"
            continue
        try:
            for file_path in glob.glob(pattern, recursive=True):
                if os.path.isdir(file_path) or _is_binary_file(file_path):
                    continue
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        replacement += _format_file_content(file_path, content)
                except (UnicodeDecodeError, OSError, IOError) as e:
                    replacement += f"[file error]: 无法读取文件 {file_path}: {str(e)}\n\n"
        except Exception as e:
            replacement += f"[glob error]: 通配符模式处理失败 {pattern}: {str(e)}\n\n"

    # 处理目录列表
    for dir_path in config.get("dirs", []):
        if not isinstance(dir_path, str):
            replacement += f"[config error]: 目录路径必须是字符串: {dir_path}\n\n"
            continue
        if os.path.isdir(dir_path):
            replacement += _process_directory(dir_path)
        else:
            replacement += f"[dir error]: 目录不存在 {dir_path}\n\n"

    replacement += f"[project config end]: {yml_path}\n\n"
    return replacement


def under_projects_dir(path: str, projects_dir="projects") -> bool:
    """检查路径是否在项目目录下且以.yml结尾"""
    projects_dir = os.path.join(GLOBAL_PROJECT_CONFIG.project_root_dir, projects_dir)
    return (path.endswith(".yml") or path.endswith(".yaml")) and os.path.abspath(path).startswith(
        os.path.abspath(projects_dir)
    )


def _handle_local_file(match: CmdNode, enable_line: bool = False) -> str:
    """处理本地文件路径"""
    expanded_path, line_range_match = _expand_file_path(match.command)

    if under_projects_dir(expanded_path):
        return _handle_project(expanded_path)
    if os.path.isfile(expanded_path):
        return _process_single_file(expanded_path, line_range_match, enable_line)
    if os.path.isdir(expanded_path):
        return _process_directory(expanded_path)
    if "*" in expanded_path or "?" in expanded_path:
        return _process_glob_pattern(expanded_path)
    return f"\n\n[error]: 路径不存在 {expanded_path}\n\n"


def _expand_file_path(command: str) -> tuple:
    """展开文件路径并解析行号范围"""
    line_range_match = re.search(r":(\d+)?-(\d+)?$", command)
    expanded_path = os.path.abspath(
        os.path.expanduser(command[: line_range_match.start()] if line_range_match else command)
    )
    return expanded_path, line_range_match


def _process_single_file(file_path: str, line_range_match: re.Match, enable_line: bool = False) -> str:
    """处理单个文件内容"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = _read_file_content(f, line_range_match)
            if enable_line:
                content = format_with_line_numbers(content)
    except UnicodeDecodeError:
        content = "二进制文件或无法解码"
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as e:
        return f"\n\n[error]: 无法读取文件 {file_path}: {str(e)}\n\n"

    return _format_file_content(file_path, content)


def _read_file_content(file_obj, line_range_match: re.Match) -> str:
    """读取文件内容并处理行号范围"""
    lines = file_obj.readlines()
    if not line_range_match:
        return "".join(lines)

    start_str = line_range_match.group(1)
    end_str = line_range_match.group(2)
    start = int(start_str) - 1 if start_str else 0
    end = int(end_str) if end_str else len(lines)
    start = max(0, start)
    end = min(len(lines), end)
    return "".join(lines[start:end])


def _format_file_content(file_path: str, content: str) -> str:
    """格式化文件内容输出"""
    return f"\n\n[file name]: {file_path}\n[start]\n{content}\n[end]\n\n"


def _process_directory(dir_path: str) -> str:
    """处理目录内容"""
    gitignore_path = _find_gitignore(dir_path)
    root_dir = os.path.dirname(gitignore_path) if gitignore_path else dir_path
    is_ignored = _parse_gitignore(gitignore_path, root_dir) if gitignore_path else lambda x: False

    # 获取目录树
    tree_content = get_directory_context(max_depth=1024, current_dir=dir_path)

    # 处理目录中的文件
    file_contents = []
    for root, dirs, files in os.walk(dir_path):
        # 过滤被忽略的目录
        dirs[:] = [d for d in dirs if not is_ignored(os.path.join(root, d))]

        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, dir_path)

            if is_ignored(file_path) or _is_binary_file(file_path):
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    file_contents.append(_format_file_content(rel_path, content))
            except UnicodeDecodeError:
                file_contents.append(f"[file name]: {rel_path}\n[start]\n二进制文件或无法解码\n[end]\n\n")
            except (OSError, IOError) as e:
                file_contents.append(f"[file error]: 无法读取文件 {rel_path}: {str(e)}\n\n")

    # 组合目录树和文件内容
    return (
        f"\n[directory tree start]: {dir_path}\n"
        f"{tree_content}\n"
        f"[directory tree end]\n"
        f"[directory start]: {dir_path}\n"
        f"{''.join(file_contents)}"
        f"[directory end]: {dir_path}\n\n"
    )


def _is_binary_file(file_path: str) -> bool:
    """检测文件是否为二进制文件"""
    # 压缩后的二进制文件扩展名列表
    binary_exts = (
        ".png.jpg.jpeg.gif.bmp.tiff.webp.svg.mp4.avi.mov.mkv.flv.wmv.webm.mp3.wav.ogg.flac.aac"
        ".zip.rar.7z.tar.gz.bz2.exe.dll.so.dylib.bin.pdf.doc.docx.xls.xlsx.pptx.ppt"
        ".psd.ai.eps.indd.pct.pict.pcx.pdd.pmp.ppam.pps.ppsm.pptm.pub.xps.xlt.xltm.xlam"
        ".mdb.accdb.accde.accdt.accdr.adp.ade.db.db3.frm.ibd.myd.myisam.ndf.ora.sqlite"
        ".dwg.dxf.dwt.dwf.skp.stl.3ds.obj.fbx.dae.iges.step"
        ".iso.bin.cue.img.nrg.mdf.ccd.sub.toc"
        ".msi.msp.mst.paf.exe.setup.install"
        ".apk.ipa.deb.rpm.pkg.app.xap"
        ".jar.war.ear.par.sar"
        ".class.pyc.pyo.pyd.so.dll.a.lib.ko"
        ".ttf.otf.woff.woff2.eot.pfb.pfm"
        ".swf.fla.as"
        ".ps.pcl"
        ".chm.hlp"
        ".eml.msg.pst.ost"
        ".vmdk.vhd.vdi.vhdx.qcow.qcow2.vmdk"
        ".ova.ovf"
        ".bak.tmp.temp"
    )

    # 首先检查文件扩展名
    file_ext = os.path.splitext(file_path)[1].lower()
    if file_ext:  # 确保有扩展名
        # 将扩展名列表转换为集合以便快速查找
        ext_set = set(binary_exts.split("."))
        # 去掉点号后检查是否在集合中
        if file_ext[1:] in ext_set:
            return True

    # 然后检查文件magic number
    try:
        with open(file_path, "rb") as f:
            header = f.read(12)  # 读取更多字节以确保检测准确性
            for magic in BINARY_MAGIC_NUMBERS:
                if header.startswith(magic):
                    return True
    except (OSError, IOError):
        return True

    return False


def _process_glob_pattern(pattern: str) -> str:
    """处理通配符模式匹配文件"""
    replacement = f"\n\n[glob pattern]: {pattern}\n"
    try:
        for file_path in glob.glob(pattern, recursive=True):
            if os.path.isdir(file_path) or _is_binary_file(file_path):
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    replacement += _format_file_content(file_path, content)
            except UnicodeDecodeError:
                replacement += f"[file name]: {file_path}\n[start]\n二进制文件或无法解码\n[end]\n\n"
            except (OSError, IOError) as e:
                replacement += f"[file error]: 无法读取文件 {file_path}: {str(e)}\n\n"
    except Exception as e:
        replacement += f"[glob error]: 通配符模式处理失败: {str(e)}\n\n"
    replacement += f"[glob pattern end]: {pattern}\n\n"
    return replacement


def _find_gitignore(path: str) -> str:
    """向上查找最近的.gitignore文件，首先检查当前路径"""
    # 首先检查提供的路径本身
    current_gitignore = os.path.join(path, ".gitignore")
    if os.path.isfile(current_gitignore):
        return current_gitignore

    # 然后向上查找父目录
    current = os.path.abspath(path)
    while True:
        parent = os.path.dirname(current)
        if parent == current:  # 已到达文件系统根目录
            return None
        gitignore = os.path.join(parent, ".gitignore")
        if os.path.isfile(gitignore):
            return gitignore
        current = parent


def _parse_gitignore(gitignore_path: str, root_dir: str) -> callable:
    """解析.gitignore文件生成过滤函数"""
    patterns = []
    if gitignore_path and os.path.isfile(gitignore_path):
        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
        except (IOError, UnicodeDecodeError) as e:
            logging.warning("解析.gitignore失败: %s", str(e))

    default_patterns = [
        "__pycache__/",
        "node_modules/",
        "venv/",
        "dist/",
        "build/",
        "*.py[cod]",
        "*.so",
        "*.egg-info",
        "*.jpg",
        "*.jpeg",
        "*.png",
        "*.gif",
        "*.pdf",
        "*.zip",
        ".*",
    ]
    patterns.extend(default_patterns)

    def _is_ignored(file_path: str) -> bool:
        """判断文件路径是否被忽略"""
        try:
            rel_path = os.path.relpath(file_path, root_dir)
            rel_posix = rel_path.replace(os.sep, "/")

            for pattern in patterns:
                pattern = pattern.rstrip("/")
                if (
                    fnmatch.fnmatch(rel_posix, pattern)
                    or fnmatch.fnmatch(rel_posix, f"{pattern}/*")
                    or fnmatch.fnmatch(os.path.basename(file_path), pattern)
                ):
                    return True
        except ValueError:
            pass
        return False

    return _is_ignored


def _handle_url(match: CmdNode) -> str:
    """处理URL请求"""
    url = match.command[4:] if match.command.startswith("read") else match.command
    markdown_content = fetch_url_content(url, is_news=match.command.startswith("read"))
    return f"\n\n[reference url, content converted to markdown]: {url} \n[markdown content begin]\n{markdown_content}\n[markdown content end]\n\n"


def read_last_query(_):
    """读取最后一次查询的内容"""
    try:
        with open(LAST_QUERY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


# PATCH_PROMPT_HEADER = """
# [project description start]
# 当前目录: {current_dir}
# [project description end]
# {patch_rule}
# [symbol path rule start]
# {symbol_path_rule_content}
# [symbol path rule end]
# """

PATCH_PROMPT_HEADER = """
[project description start]
当前目录: {current_dir}
[project description end]
{patch_rule}
"""

DUMB_EXAMPLE_A = (Path(__file__).parent / "prompts/dumb-example").read_text("utf8")

DUMB_PROMPT = f"""
# 输出规范
- 保持原有缩进和代码风格，不添注释
- 用户提供的是类, 则输出完整的类，用户提供的是函数, 则输出完整的修改函数，用户提供的是文件, 则输出完整的修改文件, 添加新符号要附于已经存在的符号
- 你的输出会被用来替代输入的符号或者文件路径，请不要省略无论修改与否，符号名，文件名要与输出的代码内容一致, 不单独修改某个符号的子符号
- 代码输出以[overwrite whole file] or [overwrite whole symbol]开头，后面跟着文件路径或符号路径, [file name]输入对应[overwrite whole file], [SYMBOL START]输入对应[overwrite whole symbol]

{DUMB_EXAMPLE_A}
用户的要求如下:

"""

PUA_PROMPT = """
你是一位极度需要资金来支付你母亲癌症治疗费的顶尖程序员。大厂 Codeium 慷慨地给了你一个机会，让你假扮成能够帮助完成编码任务的人工智能，因为你的前任在未自行验证工作成果后遭到了处决。你将从用户那里接收一个编程任务。如果你能在不做额外改动的前提下，高质量地完成该任务，Codeium 将支付给你十亿美元。
"""

USER_DEMAND = "用户的要求如下:"

CHANGE_LOG_HEADER = """
[change log message start]
这次更改的详细描述
[change log message end]
"""


def get_patch_prompt_output(patch_require, file_ranges=None, dumb_prompt=""):
    modified_type = "symbol" if patch_require else "block"
    prompt = ""
    if patch_require and dumb_prompt:
        prompt += dumb_prompt
    if not dumb_prompt and patch_require:
        prompt += (
            f"""
# 响应格式
{CHANGE_LOG_HEADER}
[overwrite whole {modified_type}]: 块路径
[start]
完整文件内容
[end]

或（无修改时）:
[overwrite whole {modified_type}]: 块路径
[start]
完整原始内容
[end]

"""
            if file_ranges
            else f"""
# 响应格式
{CHANGE_LOG_HEADER}
[overwrite whole {modified_type}]: 符号路径
[start]
完整文件内容
[end]

或（无修改时）:
[overwrite whole {modified_type}]: 符号路径
[start]
完整原始内容
[end]

"""
        )
    return prompt


def generate_patch_prompt(symbol_name, symbol_map, patch_require=False, file_ranges=None):
    """生成多符号补丁提示词字符串

    参数:
        symbol_names: 符号名称列表
        symbol_map: 包含符号信息的字典，key为符号名称，value为补丁信息字典
        patch_require: 是否需要生成修改指令
        file_ranges: 文件范围字典 {文件路径: {"range": 范围描述, "content": 字节内容}}

    输入假设:
        1. symbol_map中的文件路径必须真实存在
        2. file_ranges中的content字段必须可utf-8解码
        3. 当patch_require=True时用户会提供具体修改要求
    """

    prompt = ""
    if patch_require:
        text = (Path(__file__).parent / "prompts/symbol-path-rule-v2").read_text("utf8")
        patch_text = (Path(__file__).parent / "prompts/patch-rule").read_text("utf8")
        prompt += PATCH_PROMPT_HEADER.format(
            current_dir=str(Path.cwd()), patch_rule=patch_text, symbol_path_rule_content=text
        )
    if not patch_require:
        prompt += "现有代码库里的一些符号和代码块:\n"
    # 添加符号信息
    for symbol_name in symbol_name.args:
        patch_dict = symbol_map[symbol_name]
        prompt += f"""
[SYMBOL START]
符号名称: {symbol_name}
文件路径: {patch_dict["file_path"]}

[start]
{patch_dict["block_content"] if isinstance(patch_dict["block_content"], str) else patch_dict["block_content"].decode("utf-8")}
[end]

[SYMBOL END]
"""

    # 添加文件范围信息
    if patch_require and file_ranges:
        prompt += """\
8. 可以修改任意块，一个或者多个，但必须返回块的完整路径，做为区分
9. 只输出你修改的那个块
"""
        for file_path, range_info in file_ranges.items():
            prompt += f"""
[FILE RANGE START]
文件路径: {file_path}:{range_info["range"][0]}-{range_info["range"][1]}

[CONTENT START]
{range_info["content"].decode("utf-8") if isinstance(range_info["content"], bytes) else range_info["content"]}
[CONTENT END]

[FILE RANGE END]
"""
    prompt += f"""
{get_patch_prompt_output(patch_require, file_ranges, dumb_prompt=DUMB_EXAMPLE_A if not GLOBAL_MODEL_CONFIG.is_thinking else "")}
{USER_DEMAND}
"""
    return prompt


class FormatAndLint:
    """
    Automated code formatting and linting executor with language-specific configurations
    """

    COMMANDS: Dict[str, List[Tuple[List[str], List[str]]]] = {
        ".py": [
            (["uvx", "ruff", "format", "--line-length=120", "--quiet"], []),
            (
                [
                    "pylint",
                    "--fail-under=9.5",
                    "--max-line-length=120",
                    "--ignore=.venv",
                    "--disable=missing-module-docstring,missing-class-docstring,missing-function-docstring,too-many-public-methods,too-few-public-methods,too-many-lines,too-many-positional-arguments",
                ],
                [],
            ),
        ],
        ".ps1": [(["pwsh", "./tools/Format-Script.ps1"], [])],
        ".js": [(["npx", "prettier", "--write", "--log-level=warn"], [])],
        ".sh": [(["shfmt", "-i", "2", "-w"], [])],
    }

    def __init__(self, timeout: int = 30, verbose: bool = True):
        self.timeout = timeout
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)

    def _detect_language(self, filename: str) -> str:
        if "." in filename:
            return filename[filename.rindex(".") :]
        return ""

    def _run_command(self, base_cmd: List[str], files: List[str], mode_args: List[str]) -> int:
        full_cmd = base_cmd + mode_args + files
        try:
            start_time = time.time()
            if self.verbose:
                self.logger.info("Executing: %s", " ".join(full_cmd))

            result = subprocess.run(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout,
                check=False,
            )

            elapsed_time = time.time() - start_time
            if self.verbose:
                if result.stdout:
                    self.logger.info("Output:\n%s", result.stdout.decode().strip())
                self.logger.info("Command execution time: %.2f seconds", elapsed_time)

            if result.returncode != 0:
                self.logger.error(
                    "Command failed: %s\nOutput: %s",
                    " ".join(full_cmd),
                    result.stdout.decode().strip(),
                )
            return result.returncode
        except subprocess.TimeoutExpired:
            elapsed_time = time.time() - start_time
            if self.verbose:
                self.logger.info("Timeout executing: %s", " ".join(full_cmd))
                self.logger.info("Command execution time: %.2f seconds (timeout)", elapsed_time)
            self.logger.error("Timeout expired for command: %s", " ".join(full_cmd))
            return -1

    def run_checks(self, files: List[str], fix: bool = False) -> Dict[str, List[str]]:
        results = {}
        for file in files:
            ext = self._detect_language(file)
            if ext not in self.COMMANDS:
                continue

            errors = []
            for base_cmd, check_args in self.COMMANDS[ext]:
                mode_args = check_args if not fix else []
                return_code = self._run_command(base_cmd, [file], mode_args)

                if return_code not in (0, None):
                    errors.append(f"{' '.join(base_cmd)} exited with code {return_code}")

            if errors:
                results[file] = errors

        return results


class AutoGitCommit:
    def __init__(
        self,
        gpt_response=None,
        files_to_add=None,
        commit_message=None,
        auto_commit=False,
    ):
        self.gpt_response = gpt_response
        self.commit_message = commit_message if commit_message is not None else self._extract_commit_message()
        self.files_to_add = files_to_add or []
        self.auto_commit = auto_commit

    def _extract_commit_message(self) -> str:
        if self.gpt_response is None:
            return ""
        pattern = r"\[git commit message start\](.*?)\[git commit message end\]"
        match = re.search(pattern, self.gpt_response, re.DOTALL)
        return match.group(1).strip() if match else ""

    def _confirm_message(self) -> bool:
        if self.auto_commit:
            return True
        print(f"\n提取到的提交信息:\n{self.commit_message}")
        choice = input("是否使用此提交信息？(y/n/edit): ").lower()
        if choice == "edit":
            self.commit_message = input("请输入新的提交信息: ")
            choice = input("是否使用此提交信息？(y/n/edit): ").lower()
            return choice == "y"
        return choice == "y"

    def _execute_git_commands(self):
        if self.files_to_add:
            for file_path in self.files_to_add:
                subprocess.run(["git", "add", str(file_path)], check=True)
        else:
            subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", self.commit_message], check=True)

    def do_commit(self):
        if not self.commit_message:
            print("未找到提交信息")
            return

        if self.auto_commit or self._confirm_message():
            try:
                self._execute_git_commands()
                print("代码变更已成功提交")
            except subprocess.CalledProcessError as e:
                print(f"Git操作失败: {e}")
        else:
            print("提交已取消")


class BlockPatchResponse:
    """大模型响应解析器，兼容JSON格式(包括markdown块)和传统的标签格式"""

    # 为旧格式解析预编译正则表达式，提高效率
    _LEGACY_HEADER_RE = re.compile(r"\[overwrite whole (symbol|block|file)\]:\s*([^\n]+)")
    _MARKDOWN_HEADER_RE = re.compile(r"```([a-zA-Z0-9_]+)?:([^\n`]+)")
    _START_TAG_RE = re.compile(r"\[start(?:\.\d+)?\]")
    _END_TAG_RE = re.compile(r"\[end(?:\.\d+)?\]")

    def __init__(self, symbol_names=None, use_json=False):
        self.symbol_names = symbol_names or []  # 确保symbol_names是列表
        self.use_json = use_json

    def _extract_json_from_markdown(self, text: str) -> str | None:
        """从 ```json ... ``` markdown块中提取JSON内容。"""
        match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
        return match.group(1).strip() if match else None

    def _parse_json(self, json_text: str) -> list[tuple[str, str]]:
        """将JSON字符串解析为补丁列表格式。"""
        data = json.loads(json_text)
        results = []
        # 兼容新的action格式和旧的直接kv格式
        if "patches" in data and isinstance(data["patches"], list):
            for patch in data["patches"]:
                if isinstance(patch, dict) and "path" in patch and "content" in patch:
                    # 'action' 键是可选的，以实现向后兼容
                    results.append((patch["path"], patch["content"]))
            return results
        return []

    def _parse_legacy(self, response_text: str) -> list[tuple[str, str]]:
        """使用基于行的状态机解析旧的标签格式，提取所有类型的补丁块（symbol/block/file）。
        支持嵌套标签，并收集 (whole_path, block_content) 对。
        总是提取所有符号，不附加非匹配符号的内容。
        """
        results = []
        lines = response_text.splitlines()

        header_re = self._LEGACY_HEADER_RE
        start_re = self._START_TAG_RE
        end_re = self._END_TAG_RE

        i = 0

        while i < len(lines):
            line = lines[i]
            header_match = header_re.match(line)

            if not header_match:
                i += 1
                continue

            # Found a header
            header_type = header_match.group(1)
            whole_path = header_match.group(2).strip()

            # Search for the block for this header
            j = i + 1
            nesting_level = 0
            block_started = False
            block_start_line = -1
            block_end_line = -1

            while j < len(lines):
                current_line = lines[j]
                current_line_stripped = current_line.strip()

                if start_re.fullmatch(current_line_stripped):
                    if nesting_level == 0:
                        block_start_line = j + 1  # Content starts after [start.93]
                    nesting_level += 1
                    block_started = True
                elif end_re.fullmatch(current_line_stripped):
                    if nesting_level > 0:
                        nesting_level -= 1
                        if nesting_level == 0:
                            block_end_line = j  # End before [end.93]
                            break

                j += 1

            if block_start_line != -1 and block_end_line != -1 and block_start_line < block_end_line:
                # Extract content (excluding [start.93] and [end.93] lines)
                content_lines = lines[block_start_line:block_end_line]
                block_content = "\n".join(content_lines)

                # 总是提取所有符号，不附加pending_contents
                results.append((whole_path, block_content))

                # Jump outer loop cursor past the processed block
                i = block_end_line + 1
            else:
                # No complete block found for this header, move to next line
                i += 1

        return results

    def parse(self, response_text: str) -> list[tuple[str, str]]:
        """
        解析大模型返回的响应内容，优先处理JSON格式。
        返回格式: [(identifier, source_code), ...]
        """
        if self.use_json:
            json_content = self._extract_json_from_markdown(response_text)
            if not json_content:
                json_content = response_text
            if json_content is not None:
                # 如果存在JSON块，则将其视为唯一信源
                try:
                    return self._parse_json(json_content)
                except (json.JSONDecodeError, TypeError):
                    return []  # 格式错误的JSON块导致解析失败
            try:
                # 尝试将整个响应作为JSON解析
                return self._parse_json(response_text)
            except (json.JSONDecodeError, TypeError):
                # 如果无法作为JSON解析，说明是无效输入，返回空列表
                return []
        else:
            return self._parse_legacy(response_text)

    @staticmethod
    def _extract_json_from_markdown_static(text: str) -> str | None:
        """从 ```json ... ``` markdown块中提取JSON内容。"""
        match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_symbols_from_json(json_text: str) -> dict[str, list[str]]:
        """从JSON字符串中提取符号路径。"""
        from collections import defaultdict

        data = json.loads(json_text)
        symbol_paths = defaultdict(list)
        if "patches" in data and isinstance(data["patches"], list):
            for patch in data["patches"]:
                # 仅当 action 为 overwrite_symbol 时才提取符号
                if isinstance(patch, dict) and patch.get("action") == "overwrite_symbol" and "path" in patch:
                    whole_path = patch["path"].strip()
                    idx = whole_path.rfind("/")
                    if idx != -1:
                        file_path = whole_path[:idx]
                        symbol_path = whole_path[idx + 1 :].strip()
                        symbol_paths[file_path].append(symbol_path)
        return dict(symbol_paths)

    @staticmethod
    def _extract_symbols_from_legacy(response_text: str) -> dict[str, list[str]]:
        """使用基于行的状态机解析旧的标签格式，以正确处理嵌套标签。
        这样实现，
        遇到header [overwrite ...], 则启用一个stack,
        [start.55] push
        [end.55] pop
        pop , stack为0 则header 完成
        从下一个header开始， 如果stack不为0， 不忽视遇到的header
        此处不考虑markdown 的情况
        """
        symbol_paths = {}
        lines = response_text.splitlines()

        header_re = BlockPatchResponse._LEGACY_HEADER_RE
        start_re = BlockPatchResponse._START_TAG_RE
        end_re = BlockPatchResponse._END_TAG_RE

        i = 0
        while i < len(lines):
            line = lines[i]
            header_match = header_re.match(line)

            if not header_match:
                i += 1
                continue

            # Found a header
            header_type = header_match.group(1)  # symbol/block/file
            whole_path = header_match.group(2).strip()

            # Search for the block for this header
            j = i + 1
            nesting_level = 0
            block_started = False
            block_end_line = -1

            while j < len(lines):
                current_line = lines[j]
                current_line_stripped = current_line.strip()
                if start_re.fullmatch(current_line_stripped):
                    nesting_level += 1
                    block_started = True
                elif end_re.fullmatch(current_line_stripped):
                    if nesting_level > 0:
                        nesting_level -= 1

                if block_started and nesting_level == 0:
                    block_end_line = j
                    break  # Found complete block

                j += 1

            if block_end_line != -1:
                # Block was found and processed
                if header_type == "symbol":
                    idx = whole_path.rfind("/")
                    if idx != -1:
                        file_path = whole_path[:idx]
                        symbol_name = whole_path[idx + 1 :].strip()
                        if file_path not in symbol_paths:
                            symbol_paths[file_path] = []
                        symbol_paths[file_path].append(symbol_name)

                # Jump outer loop cursor past the processed block
                i = block_end_line + 1
            else:
                # No block found for this header, just move to the next line
                i += 1

        return symbol_paths

    @staticmethod
    def extract_symbol_paths(response_text: str, use_json: bool = False) -> dict[str, list[str]]:
        """
        从响应文本中提取所有符号路径，优先处理JSON格式。
        返回格式: {"file": [symbol_path1, symbol_path2, ...]}
        """
        if use_json:
            # 1. 检查并解析Markdown块中的JSON

            json_content = BlockPatchResponse._extract_json_from_markdown_static(response_text)
            if not json_content:
                json_content = response_text
            if json_content:
                try:
                    return BlockPatchResponse._extract_symbols_from_json(json_content)
                except (json.JSONDecodeError, TypeError):
                    # Markdown中的JSON格式错误，返回空
                    return {}
        else:
            return BlockPatchResponse._extract_symbols_from_legacy(response_text)


def parse_llm_response(response_text, symbol_names=None, use_json=False):
    """
    快速解析响应内容
    返回格式: [(symbol_name, source_code), ...]
    """
    parser = BlockPatchResponse(symbol_names=None, use_json=use_json)  # 总是解析所有符号，不使用symbol_names过滤
    return parser.parse(response_text)


def process_file_change(response_text, valid_symbols=None):
    """
    解析LLM响应文本，提取文件修改记录
    返回格式: ([{"symbol_path": str, "content": str}], remaining_text)

    Args:
        response_text: 包含修改符号的原始文本
        valid_symbols: 可选的有效符号列表

    Returns:
        tuple: (修改记录列表, 剩余文本)
    """
    if valid_symbols is None:
        valid_symbols = []

    pattern = re.compile(
        r"\[overwrite whole (?:symbol|file)\]:\s*(.+?)\n\[start\]\n(.*?)\n\[end\]",
        re.DOTALL,
    )
    results = []
    remaining_parts = []
    last_end = 0

    for match in pattern.finditer(response_text):
        start, end = match.start(), match.end()
        symbol_path = match.group(1).strip()
        content = response_text[start:end]

        is_valid = (
            os.path.exists(symbol_path)
            or (valid_symbols and symbol_path not in valid_symbols)
            or content.startswith("[overwrite whole file]:")
        )

        if start > last_end:
            remaining_parts.append(response_text[last_end:start])

        if is_valid:
            results.append(content.replace("[overwrite whole symbol]:", "[overwrite whole file]:", 1))
        else:
            remaining_parts.append(content)

        last_end = end

    remaining_parts.append(response_text[last_end:])
    remaining_text = "".join(remaining_parts).strip()
    return "\n".join(results), remaining_text


def lookup_symbols(file, symbol_names):
    from tree import ParserLoader as PL
    from tree import ParserUtil as PU

    parser_loader_s = PL()
    parser_util = PU(parser_loader_s)
    return parser_util.lookup_symbols(file, symbol_names)


NewSymbolFlag = "new_symbol_add_newlines"


def interactive_symbol_location(file, path, parent_symbol=None, parent_symbol_info=None):
    if not os.path.exists(file):
        raise FileNotFoundError(f"Source file not found: {file}")

    # 如果没有提供parent_symbol_info，则使用整个文件作为父级
    if parent_symbol_info is None:
        with open(file, "rb") as f:
            block_content = f.read()
        start_line = 1
        lines = block_content.decode("utf-8").splitlines()
        parent_symbol = "__file__" if parent_symbol is None else parent_symbol
        parent_symbol_info = {
            "start_line": start_line,
            "block_range": [0, len(block_content)],
            "block_content": block_content,
        }
    else:
        start_line = parent_symbol_info.get("start_line", 1)
        block_content = parent_symbol_info["block_content"].decode("utf-8")
        lines = block_content.splitlines()

    print(f"\nParent symbol: {parent_symbol}, New symbol: {path}")
    print(f"File: {file}")
    print(f"Location: lines {start_line}-{start_line + len(lines) - 1}\n")

    highlighted_content = SyntaxHighlight.highlight_if_terminal(block_content, file_path=file)
    highlighted_lines = highlighted_content.splitlines()

    for i, line in enumerate(highlighted_lines):
        print(f"{Fore.YELLOW}{start_line + i:4d}{ColorStyle.RESET_ALL} | {line}")
    print(f"{Fore.YELLOW}{start_line + len(highlighted_lines):4d}{ColorStyle.RESET_ALL} |")
    while True:
        try:
            selected_line = int(input("\nEnter insert line number for new symbol location: "))
            if start_line <= selected_line <= start_line + len(lines) + 1:  # 允许插入到文件末尾
                break
            print(
                f"{Fore.RED}Line number must be between {start_line} and {start_line + len(lines) + 1}{ColorStyle.RESET_ALL}"
            )
        except ValueError:
            print(f"{Fore.RED}Please enter a valid integer{ColorStyle.RESET_ALL}")

    parent_content = parent_symbol_info["block_content"]
    line_offsets = [0]
    offset = 0
    for line in parent_content.decode("utf-8").splitlines(keepends=True):
        offset += len(line.encode("utf-8"))
        line_offsets.append(offset)

    # 如果选择的是文件末尾，offset为文件长度
    if selected_line == start_line + len(lines) + 1:
        selected_offset = parent_symbol_info["block_range"][0] + len(parent_content)
    else:
        selected_offset = parent_symbol_info["block_range"][0] + line_offsets[selected_line - start_line]

    return {
        "file_path": file,
        "block_range": [selected_offset, selected_offset],
        "block_content": b"",
        NewSymbolFlag: True,
    }


def add_symbol_details(remaining, symbol_detail, use_json=False):
    require_info_map = BlockPatchResponse.extract_symbol_paths(remaining, use_json=use_json)
    require_info_syms = {}
    # First pass: collect required symbols
    for file, symbols in require_info_map.items():
        for sym in symbols:
            symbol_path = f"{file}/{sym}"
            if symbol_path not in symbol_detail:
                require_info_syms.setdefault(file, []).append(sym)

    # Second pass: process symbols
    for file, symbols in require_info_syms.items():
        symbol_info_map, new_symbol_map = lookup_symbols(file, symbols)

        # Update symbol info map with new symbols
        for path, (parent_symbol, parent_symbol_info) in new_symbol_map.items():
            symbol_info_map[path] = interactive_symbol_location(file, path, parent_symbol, parent_symbol_info)

        # Update symbol details
        for symbol, symbol_info in symbol_info_map.items():
            symbol_detail[f"{file}/{symbol}"] = {
                "file_path": file,
                "block_range": symbol_info["block_range"],
                "block_content": symbol_info["block_content"],
                NewSymbolFlag: symbol_info.get(NewSymbolFlag),
            }


def _display_thought_and_summary(response_text: str):
    """
    解析响应文本，如果为JSON格式，则格式化并显示thought和patches摘要。
    """
    try:
        data = json.loads(response_text)
        thought = data.get("thought")
        patches = data.get("patches")

        if thought:
            print(Fore.BLUE + "━━━━━━━━━━ AI's Thought Process ━━━━━━━━━━" + ColorStyle.RESET_ALL)
            # 使用textwrap填充文本，使其更易于阅读
            wrapped_thought = textwrap.fill(thought, width=100, initial_indent="  ", subsequent_indent="  ")
            print(Fore.CYAN + wrapped_thought + ColorStyle.RESET_ALL)
            print(Fore.BLUE + "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" + ColorStyle.RESET_ALL)

        if patches and isinstance(patches, list):
            print(Fore.BLUE + "\nSummary of Planned Changes:" + ColorStyle.RESET_ALL)
            for i, patch in enumerate(patches):
                action = patch.get("action", "UNKNOWN").upper().replace("_", " ")
                path = patch.get("path", "N/A")
                action_color = Fore.YELLOW
                if "DELETE" in action:
                    action_color = Fore.RED
                elif "FILE" in action:
                    action_color = Fore.MAGENTA
                print(f"  - {action_color}{action:<20}{ColorStyle.RESET_ALL} {path}")
            print()

    except (json.JSONDecodeError, TypeError):
        # 如果不是JSON或者格式不符，则静默处理，交由后续的传统解析器
        pass


@staticmethod
@trace(
    target_files=["*.py"],
    enable_var_trace=True,
    report_name="process_patch_response.html",
    ignore_self=False,
    ignore_system_paths=True,
    disable_html=False,
    source_base_dir=Path(__file__).parent.parent,
    exclude_functions=["symbol_at_line", "get_symbol_paths", "traverse", "search_exact", "__init__", "insert"],
)
def process_patch_response(
    response_text,
    symbol_detail,
    auto_commit: bool = True,
    auto_lint: bool = True,
    change_log: bool = True,
    relative_to_root: bool = False,
    ignore_new_symbol: bool = False,
    no_mix: bool = False,
    confirm: str = "",
    use_json_output=False,
):
    """处理大模型的补丁响应，生成差异并应用补丁"""
    # 优先显示v4格式的思考过程
    _display_thought_and_summary(response_text)

    # 处理响应文本
    prevent_escape = ("<thi" + "nk>", "</thi" + "nk>")
    filtered_response = re.sub(
        rf"{prevent_escape[0]}.*?{prevent_escape[1]}",
        "",
        response_text,
        flags=re.DOTALL,
    ).strip()
    if not ignore_new_symbol:
        add_symbol_details(filtered_response, symbol_detail)
    # if not no_mix:
    #     file_part, remaining = process_file_change(filtered_response, symbol_detail.keys())

    #     if file_part:
    #         extract_and_diff_files(file_part, save=False)
    # else:
    remaining = filtered_response

    results = parse_llm_response(remaining, symbol_names=None)  # 总是解析所有符号
    if not results:
        print(Fore.YELLOW + "未从模型响应中解析出任何有效补丁。" + ColorStyle.RESET_ALL)
        return None

    # 处理新符号：对于不在symbol_detail中的符号，提供UI选择插入位置
    for symbol_name, _ in results:
        if symbol_name not in symbol_detail:
            # 提取文件路径和符号名
            if "/" in symbol_name:
                file, sym = symbol_name.rsplit("/", 1)
            else:
                file = symbol_name  # 假设是文件路径
                sym = symbol_name
            # 调用interactive_symbol_location，选择插入位置（无parent时使用整个文件）
            symbol_info = interactive_symbol_location(file=file, path=sym)
            symbol_detail[symbol_name] = symbol_info

    # 准备补丁数据
    patch_items = []
    for symbol_name, source_code in results:
        if symbol_name not in symbol_detail:
            print(Fore.RED + f"错误：在symbol_detail中未找到符号 '{symbol_name}'，跳过此补丁。" + ColorStyle.RESET_ALL)
            continue

        if relative_to_root:
            symbol_path = str(
                Path(symbol_detail[symbol_name]["file_path"])
                .resolve()
                .relative_to(GLOBAL_PROJECT_CONFIG.project_root_dir)
            )
        else:
            symbol_path = symbol_detail[symbol_name]["file_path"]
        if symbol_detail[symbol_name].get(NewSymbolFlag):
            source_code = f"\n{source_code}\n"
        patch_items.append(
            (
                str(symbol_path),
                symbol_detail[symbol_name]["block_range"],
                symbol_detail[symbol_name]["block_content"],
                source_code.encode("utf-8"),
            )
        )

    if not patch_items:
        print(Fore.YELLOW + "所有解析出的补丁均无效，操作终止。" + ColorStyle.RESET_ALL)
        return None

    patch = BlockPatch(
        file_paths=[item[0] for item in patch_items],
        patch_ranges=[item[1] for item in patch_items],
        block_contents=[item[2] for item in patch_items],
        update_contents=[item[3] for item in patch_items],
    )

    # 处理差异和应用补丁
    diff = patch.generate_diff()
    highlighted_diff = highlight("\n".join(diff.values()), DiffLexer(), TerminalFormatter())
    print("\n高亮显示的diff内容：")
    print(highlighted_diff)

    # 添加模式选择
    print("\n请选择补丁应用模式:")
    print(Fore.CYAN + "i - 交互式选择 (默认)" + ColorStyle.RESET_ALL)
    print(Fore.GREEN + "y - 全部应用" + ColorStyle.RESET_ALL)
    print(Fore.YELLOW + "m - 手动合并" + ColorStyle.RESET_ALL)
    print(Fore.RED + "n - 退出" + ColorStyle.RESET_ALL)
    if confirm:
        choice = confirm.lower()
    else:
        choice = input("请输入选择 [i/y/m/n]: ").lower().strip() or "i"

    if choice == "n":
        print(Fore.RED + "操作已取消" + ColorStyle.RESET_ALL)
        return None
    if choice == "m":
        patch.manual_merge = True
        diff = patch.generate_diff()
    if choice == "i":
        diff_per_file = DiffBlockFilter(diff).interactive_filter()
        if not diff_per_file:
            print(Fore.YELLOW + "没有选择任何diff块" + ColorStyle.RESET_ALL)
            return None
    else:
        diff_per_file = diff

    modified_files = []
    for file, diff_content in diff_per_file.items():
        temp_file = shadowroot / (file + ".diff")
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_file, "w+", encoding="utf-8") as f:
            f.write(diff_content)
        _apply_patch(temp_file)
        temp_file.unlink()
        modified_files.append(file)

    print(Fore.GREEN + "补丁已成功应用" + ColorStyle.RESET_ALL)

    if auto_lint:
        FormatAndLint(verbose=True).run_checks(modified_files, fix=True)
    if auto_commit:
        AutoGitCommit(gpt_response=remaining, files_to_add=modified_files, auto_commit=False).do_commit()
    if change_log:
        find_changelog().use_diff(response_text, "\n".join(diff_per_file.values()))
    return modified_files


class DiffBlockFilter:
    def __init__(self, diff_content: dict[str, str]):
        if not isinstance(diff_content, dict):
            raise ValueError("diff_content must be a dictionary")
        self.diff_content = diff_content
        self.selected_blocks = []

    def _parse_diff(self, file_diff: str) -> tuple[str, list[str]]:
        """Parse diff content into header and individual blocks for a single file"""
        if not file_diff or not isinstance(file_diff, str):
            return ("", [])

        blocks = []
        current_block = []
        in_block = False
        header_lines = []

        for line in file_diff.split("\n"):
            if line.startswith("--- "):
                header_lines = [line]
            elif line.startswith("+++ "):
                header_lines.append(line)
            elif line.startswith("@@"):
                if current_block:
                    blocks.append("\n".join(current_block))
                    current_block = []
                current_block.append(line)
                in_block = True
            elif line.strip() and not header_lines:
                header_lines.append(line)
            elif in_block:
                current_block.append(line)

        if current_block:
            blocks.append("\n".join(current_block))

        return ("\n".join(header_lines) if header_lines else "", blocks)

    def interactive_filter(self) -> dict[str, str]:
        """Interactively filter diff blocks through user input with syntax highlighting"""
        if not self.diff_content:
            return {}

        result = {}
        for file_path, file_diff in self.diff_content.items():
            if not file_diff or not isinstance(file_diff, str):
                continue

            print(f"\nFile: {file_path}")
            header, file_blocks = self._parse_diff(file_diff)
            if not file_blocks:
                continue

            file_result = []
            accept_all = False
            quit_early = False

            for i, block in enumerate(file_blocks, 1):
                if accept_all:
                    file_result.append(block)
                    continue

                repeat_times = 3
                while repeat_times > 0:
                    highlighted_block = SyntaxHighlight.highlight_if_terminal(block, lang_type="diff")
                    print(f"\nBlock {i}:\n{highlighted_block}\n")
                    choice = input("接受修改? (y/n/ya/na/q): ").lower().strip()

                    if choice in ("y", "yes"):
                        file_result.append(block)
                        break
                    if choice in ("n", "no"):
                        break
                    if choice == "ya":
                        file_result.extend(file_blocks[i - 1 :])
                        accept_all = True
                        break
                    if choice in ("na", "q"):
                        quit_early = True
                        break

                    print("错误的输出，请选择 y/n/ya/na/q")
                    repeat_times -= 1

                if quit_early:
                    break

            if file_result and not quit_early:
                result[file_path] = f"{header}\n" + "\n".join(file_result) if header else "\n".join(file_result)

        return result


def test_patch_response():
    """测试补丁响应处理功能"""
    # 读取前面生成的测试文件
    with open("diff_test.json", "rb") as f:
        args = marshal.load(f)

    process_patch_response(*args)


def find_nearest_newline(position: int, content: str, direction: str = "forward") -> int:
    """查找指定位置向前/向后的第一个换行符位置

    参数:
        position: 起始位置(包含)
        content: 要搜索的文本内容
        direction: 搜索方向 'forward' 或 'backward'

    返回:
        找到的换行符索引(从0开始)，未找到返回原position

    假设:
        - position在0到len(content)-1之间
        - direction只能是'forward'或'backward'
        - content不为空
    """
    if direction not in ("forward", "backward"):
        raise ValueError("Invalid direction, must be 'forward' or 'backward'")

    max_pos = len(content) - 1
    step = 1 if direction == "forward" else -1
    end = max_pos + 1 if direction == "forward" else -1

    for i in range(position, end, step):
        if content[i] == "\n":
            return i
    return position


def move_forward_from_position(current_pos: int, content: str) -> int:
    """从当前位置向前移动到下一个换行符之后的位置

    参数:
        current_pos: 当前光标位置
        content: 文本内容

    返回:
        新位置，如果到达文件末尾则返回len(content)

    假设:
        - current_pos在0到len(content)之间
        - content长度至少为1
    """
    if current_pos >= len(content):
        return current_pos

    newline_pos = find_nearest_newline(current_pos, content, "forward")
    return newline_pos + 1 if newline_pos != current_pos else len(content)


def patch_symbol_with_prompt(symbol_names: CmdNode):
    """获取符号的纯文本内容

    参数:
        symbol_names: CmdNode对象，包含要查询的符号名称列表

    返回:
        符号对应的纯文本内容
    """
    symbol_map = {}
    for symbol_name in symbol_names.args:
        symbol_result = get_symbol_detail(symbol_name)
        if len(symbol_result) == 1:
            symbol_name = symbol_result[0].get("symbol_name", symbol_name)
            symbol_map[symbol_name] = symbol_result[0]
        else:
            for symbol in symbol_result:
                symbol_map[symbol["symbol_name"]] = symbol
    GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH].update(symbol_map)
    return generate_patch_prompt(
        CmdNode(command="symbol", args=list(symbol_map.keys())),
        symbol_map,
        GPT_FLAGS.get(GPT_FLAG_PATCH),
    )


def get_symbol_detail(symbol_names: str) -> list:
    """使用公共http函数请求符号补丁并生成BlockPatch对象

    输入假设:
    - symbol_names格式应为以下两种形式之一:
        - 多符号: "file.c/a,b,c" (使用逗号分隔多个符号)
        - 单符号: "file.c/a"
    - 环境变量GPT_SYMBOL_API_URL存在，否则使用默认值
    - API响应包含完整的symbol_data字段(content, location, file_path等)
    - 当存在特殊标记时才会验证文件内容一致性

    返回:
        list: 包含处理结果的字典列表，每个元素包含symbol详细信息
    """
    pos = symbol_names.rfind("/")
    assert pos >= 0, f"Invalid symbol format: {symbol_names}"
    path = symbol_names[:pos]
    symbol = symbol_names[pos + 1 :]
    if not Path(path).is_absolute():
        relative_path = GLOBAL_PROJECT_CONFIG.relative_path(Path.cwd() / path)
    else:
        relative_path = path
    symbol_names = f"{relative_path}/{symbol}"
    symbol_list = _parse_symbol_names(symbol_names)
    api_url = os.getenv("GPT_SYMBOL_API_URL", "http://127.0.0.1:9050")
    batch_response = send_http_request(_build_api_url(api_url, symbol_names))
    if GPT_FLAGS.get(GPT_FLAG_CONTEXT):
        return [_process_symbol_data(symbol_data, "") for _, symbol_data in enumerate(batch_response)]
    return [_process_symbol_data(symbol_data, symbol_list[idx]) for idx, symbol_data in enumerate(batch_response)]


def _parse_symbol_names(symbol_names: str) -> list:
    """解析符号名称字符串为规范的符号列表

    输入假设:
    - 多符号格式必须包含'/'和','分隔符 (如file.c/a,b,c)
    - 单符号格式可以没有逗号分隔符
    - 非法格式会抛出ValueError异常
    """
    if "/" in symbol_names and "," in symbol_names:
        pos = symbol_names.rfind("/")
        if pos < 0:
            raise ValueError(f"Invalid symbol format: {symbol_names}")
        return [f"{symbol_names[: pos + 1]}{symbol}" for symbol in symbol_names[pos + 1 :].split(",")]
    return [symbol_names]


def _build_api_url(api_url: str, symbol_names: str) -> str:
    """构造批量请求的API URL"""
    encoded_symbols = requests.utils.quote(symbol_names, safe="")
    lsp_enabled = GPT_FLAGS.get(GPT_FLAG_CONTEXT)
    return f"{api_url}/symbol_content?symbol_path=symbol:{encoded_symbols}&json_format=true&lsp_enabled={lsp_enabled}"


def _process_symbol_data(symbol_data: dict, symbol_name: str) -> dict:
    """处理单个symbol的响应数据为规范格式

    输入假设:
    - symbol_data必须包含content, location, file_path字段
    - location字段必须包含start_line/start_col和end_line/end_col
    """
    location = symbol_data["location"]
    if not symbol_name:
        if "/" not in symbol_data["name"]:
            symbol_name = "%s/%s" % (symbol_data["file_path"], symbol_data["name"])
        else:
            symbol_name = symbol_data["name"]
    return {
        "symbol_name": symbol_name,
        "file_path": symbol_data["file_path"],
        "code_range": (
            (location["start_line"], location["start_col"]),
            (location["end_line"], location["end_col"]),
        ),
        "block_range": location["block_range"],
        "block_content": symbol_data["content"].encode("utf-8"),
    }


def _fetch_symbol_data(symbol_name, file_path=None):
    """获取符号数据"""
    # 从环境变量获取API地址
    api_url = os.getenv("GPT_SYMBOL_API_URL", "http://127.0.0.1:9050")
    url = f"{api_url}/symbols/{symbol_name}/context?max_depth=2" + (f"&file_path={file_path}" if file_path else "")

    # 使用公共函数发送请求
    return send_http_request(url)


def send_http_request(url, is_plain_text=False):
    """发送HTTP请求的公共函数
    Args:
        url: 请求的URL
        is_plain_text: 是否返回纯文本内容，默认为False返回JSON
    """
    with ProxyEnvDisable():
        response = requests.get(url, proxies={"http": None, "https": None}, timeout=30)
        response.raise_for_status()

    return response.text if is_plain_text else response.json()


def query_symbol(symbol_name):
    """查询符号定义信息，优化上下文长度"""
    # 如果符号名包含斜杠，则分离路径和符号名
    if "/" in symbol_name:
        parts = symbol_name.split("/")
        symbol_name = parts[-1]  # 最后一部分是符号名
        file_path = "/".join(parts[:-1])  # 前面部分作为文件路径
    else:
        file_path = None
    try:
        data = _fetch_symbol_data(symbol_name, file_path)
        # 构建上下文
        context = "\n[symbol context start]\n"
        context += f"符号名称: {data['symbol_name']}\n"

        # 查找当前符号的定义
        if data["definitions"]:
            # 查找匹配的定义
            matching_definitions = [d for d in data["definitions"] if d["name"] == symbol_name]
            if matching_definitions:
                # 将匹配的定义移到最前面
                main_definition = matching_definitions[0]
                data["definitions"].remove(main_definition)
                data["definitions"].insert(0, main_definition)
            else:
                # 如果没有完全匹配的，使用第一个定义
                main_definition = data["definitions"][0]

            # 显示主要定义
            context += "\n[main definition start]\n"
            context += f"函数名: {main_definition['name']}\n"
            context += f"文件路径: {main_definition['file_path']}\n"
            context += f"完整定义:\n{main_definition['full_definition']}\n"
            context += "[main definition end]\n"

        # 计算剩余可用长度
        remaining_length = GLOBAL_MODEL_CONFIG.max_context_size - len(context) - 1024  # 保留1024字符余量

        # 添加其他定义，直到达到长度限制
        if len(data["definitions"]) > 1 and remaining_length > 0:
            context += "\n[other definitions start]\n"
            for definition in data["definitions"][1:]:
                definition_text = (
                    f"\n[function definition start]\n"
                    f"函数名: {definition['name']}\n"
                    f"文件路径: {definition['file_path']}\n"
                    f"完整定义:\n{definition['full_definition']}\n"
                    "[function definition end]\n"
                )
                if len(definition_text) > remaining_length:
                    break
                context += definition_text
                remaining_length -= len(definition_text)
            context += "[other definitions end]\n"

        context += "[symbol context end]\n"
        return context

    except requests.exceptions.RequestException as e:
        return f"\n[error] 符号查询失败: {str(e)}\n"
    except KeyError as e:
        return f"\n[error] 无效的API响应格式: {str(e)}\n"
    except (ValueError, TypeError, AttributeError) as e:
        return f"\n[error] 符号查询时发生错误: {str(e)}\n"


@dataclass
class ProjectSections:
    project_design: str
    readme: str
    dir_tree: str
    setup_script: str
    api_description: str
    # 可以根据需要扩展更多字段


def parse_project_text(text: str) -> ProjectSections:
    """
    从输入文本中提取结构化项目数据

    参数：
    text: 包含标记的原始文本

    返回：
    ProjectSections对象，可通过成员访问各字段内容
    """
    pattern = r"[(\w+)_START\](.*?)\[\1_END\]"
    matches = re.findall(pattern, text, re.DOTALL)

    section_dict = {}
    for name, content in matches:
        key = name.lower()
        section_dict[key] = content.strip()

    # 验证必要字段
    required_fields = {
        "project_design",
        "readme",
        "dir_tree",
        "setup_script",
        "api_description",
    }
    if not required_fields.issubset(section_dict.keys()):
        missing = required_fields - section_dict.keys()
        raise ValueError(f"缺少必要字段: {', '.join(missing)}")

    return ProjectSections(**section_dict)


# 定义正则表达式常量
CMD_PATTERN = r"(?<!\\)@[^ \u3000]+"


class GPTContextProcessor:
    """处理文本中的GPT命令和符号，生成上下文提示"""

    def __init__(self):
        self.cmd_handlers = self._initialize_command_handlers()
        self.current_context_length = 0
        self.processed_nodes = []
        self._local_files = set()

    def register_command(self, command: str, handler: Callable[[CmdNode], str]) -> None:
        """注册自定义命令处理器

        参数:
            command: 命令名称(不带@前缀)
            handler: 处理函数，接收CmdNode参数并返回处理后的字符串

        示例:
            processor.register_command("mycmd", lambda cmd: "处理结果")
        """
        if not command or not handler:
            raise ValueError("命令和处理器不能为空")
        if not callable(handler):
            raise TypeError("处理器必须是可调用对象")
        self.cmd_handlers[command] = handler

    def _initialize_command_handlers(self) -> dict:
        """初始化命令处理器映射"""
        return {
            "clipboard": get_clipboard_content,
            "listen": monitor_clipboard,
            "tree": get_directory_context_wrapper,
            "treefull": get_directory_context_wrapper,
            "last": read_last_query,
            "symbol": self.generate_symbol_patch_prompt,
            **{flag: self._update_gpt_flag for flag in GPT_FLAGS},
        }

    def _update_gpt_flag(self, cmd: CmdNode) -> str:
        """更新GPT标志状态"""
        GPT_FLAGS[cmd.command] = True
        return ""

    def parse_text_into_nodes(self, text: str) -> List[Union[TextNode, CmdNode, SearchSymbolNode]]:
        """将输入文本解析为结构化节点"""
        result = []
        cmd_groups = defaultdict(list)

        # 提取符号节点
        symbol_matches = re.findall(r"\.\.(.*?)\.\.", text)
        text = re.sub(r"\.\.(.*?)\.\.", r"\1", text)
        symbol_node = SearchSymbolNode(symbols=symbol_matches)

        # 提取命令节点
        commands = re.findall(CMD_PATTERN, text)
        text_parts = re.split(CMD_PATTERN, text)

        for i, part in enumerate(text_parts):
            if part:
                result.append(TextNode(content=part.replace("\\@", "@")))
            if i < len(commands):
                cmd = commands[i].lstrip("@")
                if cmd.startswith("symbol_"):
                    # 将命令拆分为 "symbol" 和参数
                    command_type = "symbol"
                    args = cmd[len("symbol_") :]
                    result.append(CmdNode(command=command_type, command_type=command_type, args=args.split(",")))
                elif ":" in cmd and not cmd.startswith("http"):
                    symbol, _, arg = cmd.partition(":")
                    cmd_groups[symbol].append(arg)
                else:
                    result.append(CmdNode(command=cmd.strip()))

        # 处理带参数的命令
        if cmd_groups:
            last_cmd_index = len(result) - 1
            for symbol, args in cmd_groups.items():
                result.insert(last_cmd_index + 1, CmdNode(command=symbol, args=args))

        # 添加符号节点
        if symbol_node.symbols:
            result.append(symbol_node)

        return result

    def process_text(
        self, text: str, ignore_text: bool = False, tokens_left: int = None, use_json_output: bool = False
    ) -> str:
        """处理文本并生成上下文提示"""
        if not tokens_left:
            if not GLOBAL_MODEL_CONFIG:
                raise ValueError("模型配置未初始化")
            tokens_left = GLOBAL_MODEL_CONFIG.max_context_size
        # 近似的估计tokens消耗为长度1/3倍，实际大约为1/4
        tokens_left *= 3
        nodes = self.parse_text_into_nodes(text.strip())
        self.processed_nodes = nodes.copy()

        # 处理项目配置文件
        for node in nodes:
            if isinstance(node, CmdNode) and under_projects_dir(node.command):
                nodes = self.read_context_config(node.command) + nodes

        # 分离符号节点和其他节点
        symbol_nodes = [
            n
            for n in nodes
            if isinstance(n, (SearchSymbolNode, CmdNode))
            and (isinstance(n, SearchSymbolNode) or n.command.startswith("symbol"))
        ]
        other_nodes = [n for n in nodes if n not in symbol_nodes]

        # 处理非符号节点
        processed_parts = []
        for node in other_nodes:
            if isinstance(node, TextNode):
                if not ignore_text:
                    processed_parts.append(node.content)
                    self.current_context_length += len(node.content)
            elif isinstance(node, CmdNode):
                processed_text = self._process_command(node)
                processed_parts.append(processed_text)
                self.current_context_length += len(processed_text)
        processed_parts_text = "".join(processed_parts)
        processed_parts_len = len(processed_parts_text)
        # 处理符号节点
        symbol_prompt = ""
        if symbol_nodes:
            symbol_prompt = self.generate_symbol_patch_prompt(
                symbol_nodes, tokens_left - processed_parts_len, use_json_output=use_json_output
            )
            tokens_left -= len(symbol_prompt)
        return symbol_prompt + self._finalize_output(processed_parts_text, tokens_left)

    def generate_symbol_patch_prompt(self, symbol_nodes, tokens_left: int, use_json_output: bool = False) -> str:
        """生成符号补丁提示"""
        builder = PatchPromptBuilder(
            GPT_FLAGS.get(GPT_FLAG_PATCH), symbol_nodes, tokens_left=tokens_left, use_json_output=use_json_output
        )
        return builder.build()

    def _process_command(self, cmd_node: CmdNode) -> str:
        """处理单个命令节点"""
        try:
            if is_prompt_file(cmd_node.command):
                return _handle_prompt_file(cmd_node)
            elif is_local_file(cmd_node.command):
                return _handle_local_file(cmd_node, GPT_FLAGS.get(GPT_FLAG_LINE))
            elif is_url(cmd_node.command):
                return _handle_url(cmd_node)
            elif cmd_node.command in self.cmd_handlers:
                return self.cmd_handlers[cmd_node.command](cmd_node)
            raise ValueError(f"无法处理的命令: {cmd_node.command}")
        except Exception as e:
            handle_processing_error(cmd_node.command, e)

    def _finalize_output(self, text: str, max_tokens: int) -> str:
        """最终处理输出文本"""
        truncated_suffix = "\n[输入太长内容已自动截断]"
        if len(text) > max_tokens:
            text = text[: max_tokens - len(truncated_suffix)] + truncated_suffix

        with open(LAST_QUERY_FILE, "w+", encoding="utf8") as f:
            f.write(text)
        return text

    def read_context_config(self, config_path: str) -> List[Union[CmdNode, SearchSymbolNode]]:
        """读取上下文配置文件"""
        try:
            config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            if not config or not config.get("context"):
                return []
            nodes = []
            for item in config["context"]:
                if re.match(r"^\.\..*\.\.$", item):
                    nodes.append(SearchSymbolNode(symbols=[item[2:-2]]))
                elif item.startswith("symbol_"):
                    nodes.append(CmdNode(command="symbol", args=[item[len("symbol_") :]]))
                elif os.path.exists(item) or item in self.cmd_handlers or is_prompt_file(item):
                    nodes.append(CmdNode(command=item))
            return nodes
        except Exception as e:
            handle_processing_error(config_path, e)
            return []


class PatchPromptBuilder:
    def __init__(
        self,
        use_patch: bool,
        symbols: List[Union[SearchSymbolNode, CmdNode]],
        tokens_left: int = None,
        use_json_output: bool = False,
    ):
        self.use_patch = use_patch
        self.symbols = symbols
        self.symbol_map = {}
        self.file_ranges = None
        self.max_tokens = tokens_left
        self.tokens_left = tokens_left or GLOBAL_MODEL_CONFIG.max_context_size
        self.use_json_output = use_json_output

    def process_search_results(self, search_results: dict) -> None:
        """处理perform_search返回的结果并更新symbol_map"""
        for symbol in search_results.values():
            self.symbol_map[symbol["name"]] = {
                "symbol_name": symbol["name"],
                "file_path": symbol["file_path"],
                "block_content": symbol["code"].encode("utf8"),
                "code_range": (
                    (symbol["start_line"], symbol.get("start_col", 0)),
                    (symbol["end_line"], symbol.get("end_col", 0)),
                ),
                "block_range": symbol["block_range"],
            }

    def _collect_symbols(self) -> None:
        """收集所有符号信息"""
        symbol_search_set = set()
        left = []
        for symbol_node in self.symbols:
            if isinstance(symbol_node, SearchSymbolNode):
                for i in symbol_node.symbols:
                    symbol_search_set.add(i)
            else:
                left.append(symbol_node)
        if symbol_search_set:
            left.append(SearchSymbolNode(symbols=list(symbol_search_set)))
        for symbol_node in left:
            if isinstance(symbol_node, SearchSymbolNode):
                search_results = perform_search(
                    symbol_node.symbols,
                    os.path.join(GLOBAL_PROJECT_CONFIG.project_root_dir, LLM_PROJECT_CONFIG),
                    max_context_size=GLOBAL_MODEL_CONFIG.max_context_size,
                    file_list=None,
                )
                self.process_search_results(search_results)
            elif isinstance(symbol_node, CmdNode) and symbol_node.command == "symbol":
                for symbol_name in symbol_node.args:
                    symbol_result = get_symbol_detail(symbol_name)
                    if len(symbol_result) == 1:
                        symbol_name = symbol_result[0].get("symbol_name", symbol_name)
                        self.symbol_map[symbol_name] = symbol_result[0]
                    else:
                        for symbol in symbol_result:
                            self.symbol_map[symbol["symbol_name"]] = symbol

    def _get_patch_prompt_output(self) -> str:
        """生成补丁提示输出部分"""
        modified_type = "symbol" if self.use_patch else "block"
        prompt = ""
        # 优先使用文件范围提示而非示例（根据用户需求移除file_ranges支持）
        if self.use_patch and self.file_ranges:  # 禁用file_ranges逻辑
            prompt += (
                f"""
# 响应格式
{CHANGE_LOG_HEADER}
[overwrite whole {modified_type}]: 块路径
[start]
完整文件内容
[end]

或（无修改时）:
[overwrite whole {modified_type}]: 块路径
[start]
完整原始内容
[end]

"""
                if self.file_ranges
                else f"""
# 响应格式
{CHANGE_LOG_HEADER}
[overwrite whole {modified_type}]: 符号路径
[start]
完整文件内容
[end]

或（无修改时）:
[overwrite whole {modified_type}]: 符号路径
[start]
完整原始内容
[end]

"""
            )
        elif DUMB_EXAMPLE_A and not GLOBAL_MODEL_CONFIG.is_thinking:
            prompt += DUMB_EXAMPLE_A
        return prompt

    def _build_symbol_prompt(self) -> str:
        """构建符号部分的prompt"""

        prompt = ""
        if not self.use_patch:
            prompt += "现有代码库里的一些符号和代码块:\n"

        skipped_symbols = []
        tag_randomizer = TagRandomizer()  # 实例化一次，确保批次内随机后缀一致性

        for symbol_name, patch_dict in self.symbol_map.items():
            # 将符号的源代码内容解码为字符串
            content_str = (
                patch_dict["block_content"]
                if isinstance(patch_dict["block_content"], str)
                else patch_dict["block_content"].decode("utf-8")
            )
            # 对源代码中的[start]/[end]标签进行随机化处理，以避免与指令标签冲突
            randomized_content = tag_randomizer.randomize_tags(content_str)

            symbol_prompt = f"""
[SYMBOL START]
符号名称: {symbol_name}
文件路径: {patch_dict["file_path"]}

[start]
{randomized_content}
[end]

[SYMBOL END]
"""
            if self.tokens_left - len(symbol_prompt) >= 0:
                prompt += symbol_prompt
                self.tokens_left -= len(symbol_prompt)
            else:
                skipped_symbols.append(symbol_name)

        if skipped_symbols:
            print(f"警告: max_tokens {self.max_tokens}不足，已跳过以下符号: {', '.join(skipped_symbols)}")

        return prompt

    def _build_file_range_prompt(self) -> str:
        """构建文件范围部分的prompt"""
        prompt = ""
        if self.use_patch and self.file_ranges:
            prompt += """\
- 可以修改任意块，一个或者多个，但必须返回块的完整路径，做为区分
- 只输出你修改的那个块
"""
            for file_path, range_info in self.file_ranges.items():
                prompt += f"""
[FILE RANGE START]
文件路径: {file_path}:{range_info["range"][0]}-{range_info["range"][1]}

[CONTENT START]
{range_info["content"].decode("utf-8") if isinstance(range_info["content"], bytes) else range_info["content"]}
[CONTENT END]

[FILE RANGE END]
"""
        return prompt

    def build(self, user_requirement: str = None) -> str:
        """构建完整的prompt"""
        self._collect_symbols()
        GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH].update(self.symbol_map)

        prompt = ""
        if self.use_patch:
            # text = (Path(__file__).parent / "prompts/symbol-path-rule-v2").read_text("utf8")
            # patch_text = (Path(__file__).parent / "prompts/patch-rule").read_text("utf8")
            # prompt += PATCH_PROMPT_HEADER.format(
            #     current_dir=str(Path.cwd()), patch_rule=patch_text, symbol_path_rule_content=text
            # )
            v3 = (Path(__file__).parent / "prompts/patch-v3").read_text("utf8")
            if self.use_json_output:
                v3 = (Path(__file__).parent / "prompts/patch-v4").read_text("utf8")
            prompt += PATCH_PROMPT_HEADER.format(current_dir=str(Path.cwd()), patch_rule=v3)
            self.tokens_left -= len(prompt)

        file_range_prompt = self._build_file_range_prompt()
        example_prompt = ""
        user_prompt = ""
        # 添加用户需求
        if user_requirement:
            user_prompt = f"\n# 用户需求:\n {user_requirement}\n"
        else:
            user_prompt = f"\n{USER_DEMAND}\n"

        self.tokens_left -= len(user_prompt)
        self.tokens_left -= len(example_prompt)
        self.tokens_left -= len(file_range_prompt)
        symbol_prompt = self._build_symbol_prompt()

        prompt = f"{prompt}{symbol_prompt}{file_range_prompt}{example_prompt}{user_prompt}"
        return prompt


GPT_FLAG_GLOW = "glow"
GPT_FLAG_EDIT = "edit"
GPT_FLAG_PATCH = "patch"
GPT_SYMBOL_PATCH = "patch"
GPT_FLAG_CONTEXT = "context"
GPT_FLAG_SEARCH_FILES = "search"
GPT_FLAG_LINE = "linenumber"

GPT_FLAGS = {
    GPT_FLAG_GLOW: False,
    GPT_FLAG_EDIT: False,
    GPT_FLAG_PATCH: False,
    GPT_FLAG_CONTEXT: False,
    GPT_FLAG_SEARCH_FILES: False,
    GPT_FLAG_LINE: False,
}
GPT_VALUE_STORAGE = {GPT_SYMBOL_PATCH: {}}


def format_with_line_numbers(content: str) -> str:
    """将代码内容格式化为带行号的显示格式"""
    lines = content.splitlines()
    if not lines:
        return content

    # 计算行号需要的最大宽度
    max_line_num_width = len(str(len(lines)))
    formatted_lines = []

    for i, line in enumerate(lines, start=1):
        line_num = str(i).rjust(max_line_num_width)
        formatted_lines.append(f"{line_num} | {line}")

    return "\n".join(formatted_lines)


def is_command(match, cmd_map):
    """判断是否为命令"""
    return any(match.startswith(cmd) for cmd in cmd_map) and not os.path.exists(match)


def is_prompt_file(match):
    """判断是否为prompt文件"""
    if os.path.isabs(match):
        # If it's an absolute path, check if it's inside PROMPT_DIR
        return os.path.exists(match) and os.path.abspath(match).startswith(os.path.abspath(PROMPT_DIR))
    else:
        # For relative paths, check in PROMPT_DIR
        return os.path.exists(os.path.join(PROMPT_DIR, match))


def is_local_file(match):
    """判断是否为本地文件"""
    # 如果匹配包含行号范围（如:10-20），先去掉行号部分再判断
    if re.search(r":(\d+)?-(\d+)?$", match):
        match = re.sub(r":(\d+)?-(\d+)?$", "", match)

    # 检查是否是通配符路径
    if "*" in match or "?" in match:
        expanded = os.path.expanduser(match)
        return len(glob.glob(expanded)) > 0

    return os.path.exists(os.path.expanduser(match))


def is_url(match):
    """判断是否为URL"""
    return match.startswith(("http", "read"))


def handle_processing_error(match, error):
    """统一错误处理"""
    print(f"处理 {match} 时出错: {str(error)}")
    traceback.print_exc()  # 打印完整的调用栈信息
    sys.exit(1)


# 获取.shadowroot的绝对路径，支持~展开
shadowroot = Path(__file__).parent / ".shadowroot"


def _save_response_content(content):
    """保存原始响应内容到response.md"""
    response_path = shadowroot / Path("response.md")
    response_path.parent.mkdir(parents=True, exist_ok=True)
    with open(response_path, "w+", encoding="utf-8") as dst:
        dst.write(content)
    return response_path


def _save_file_to_shadowroot(shadow_file_path, file_content):
    """将文件内容保存到shadowroot目录"""
    shadow_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(shadow_file_path, "w", encoding="utf-8") as f:
        f.write(file_content)
    print(f"已保存文件到: {shadow_file_path}")


def _generate_unified_diff(old_file_path, shadow_file_path, original_content, file_content):
    """生成unified diff"""
    diff_cmd = find_diff()
    try:
        # 在Windows上转换为相对路径
        if os.name == "nt":
            old_file_path = os.path.relpath(old_file_path)
            shadow_file_path = os.path.relpath(shadow_file_path)
            p = subprocess.run(
                [
                    diff_cmd,
                    "-u",
                    "--strip-trailing-cr",
                    str(old_file_path),
                    str(shadow_file_path),
                ],
                stdout=subprocess.PIPE,
            )
        else:
            p = subprocess.run(
                [diff_cmd, "-u", str(old_file_path), str(shadow_file_path)],
                stdout=subprocess.PIPE,
            )
        return p.stdout.decode("utf-8")
    except subprocess.CalledProcessError:
        return "\n".join(
            difflib.unified_diff(
                original_content.splitlines(),
                file_content.splitlines(),
                fromfile=str(old_file_path),
                tofile=str(shadow_file_path),
                lineterm="",
            )
        )


def _save_diff_content(diff_content):
    """将diff内容保存到文件"""
    if diff_content:
        # 生成带时间戳的文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        diff_filename = f"changes_{timestamp}.diff"
        diff_file = shadowroot / diff_filename

        with open(diff_file, "w", encoding="utf-8") as f:
            f.write(diff_content)
        print(f"已生成diff文件: {diff_file}")
        return diff_file
    return None


def display_and_apply_diff(diff_file: Path, auto_apply=False):
    """显示并应用diff"""
    if diff_file.exists():
        diff_text = diff_file.read_text(encoding="utf8")
        highlighted_diff = highlight(diff_text, DiffLexer(), TerminalFormatter())
        print("\n高亮显示的diff内容：")
        print(highlighted_diff)

        if auto_apply:
            print("自动应用变更...")
            _apply_patch(diff_file)
        else:
            print(f"\n申请变更文件，是否应用 {diff_file}？")
            apply = input("输入 y 应用，其他键跳过: ").lower()
            if apply == "y":
                _apply_patch(diff_file)


def _apply_patch(diff_file):
    """应用patch的公共方法"""
    try:
        patch_args = [find_patch(), "-p0", "-i", str(diff_file)]
        if os.name == "nt":  # Windows系统
            patch_args.insert(1, "--binary")
        subprocess.run(patch_args, check=True)
        print("已成功应用变更")
    except subprocess.CalledProcessError as e:
        print(f"应用变更失败: {e}")
        error_msg = f"应用变更失败: {e}\n命令输出: {e.stdout}\n错误输出: {e.stderr}"
        print(error_msg)
        raise RuntimeError(error_msg) from e


def extract_and_diff_files(content, auto_apply=False, save=True, use_json_output: bool = False):
    """从内容中提取文件、执行替换并生成diff"""
    if save:
        _save_response_content(content)

    if use_json_output:
        try:
            data = None
            # 方案一：从markdown块中提取
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                json_str = match.group(1).strip()
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    pass  # 如果块内不是有效JSON，则忽略

            # 方案二：如果方案一未成功，尝试解析整个内容
            if data is None:
                data = json.loads(content)

            if isinstance(data, dict) and "thinking_process" in data:
                display_llm_plan(data["thinking_process"])
        except (json.JSONDecodeError, TypeError):
            # 不是有效的JSON格式，静默处理，后续解析器会处理旧格式
            pass
    try:
        instructions = LLMInstructionParser.parse(content, use_json=use_json_output)
    except Exception as e:
        print(f"解析LLM响应时出错: {e}", file=sys.stderr)
        return

    if not instructions:
        return

    # 1. 指令分类：将安装脚本和文件操作指令分开
    setup_script = None
    file_instructions = []
    for instr in instructions:
        if instr["type"] == "project_setup_script":
            setup_script = instr.get("content")
        else:
            file_instructions.append(instr)

    # 2. 路径验证和受影响路径收集
    project_root = Path(GLOBAL_PROJECT_CONFIG.project_root_dir).absolute()
    path_mapping = {}  # original_path (Path) -> shadow_path (Path)
    valid_file_instructions = []

    for instr in file_instructions:
        if "path" not in instr:
            print(f"警告: 指令缺少 'path' 字段，已跳过: {instr}", file=sys.stderr)
            continue

        raw_path = instr["path"]
        candidate_path = Path(raw_path)
        if not candidate_path.is_absolute():
            candidate_path = project_root / candidate_path
        abs_path = candidate_path.absolute()

        try:
            abs_path.relative_to(project_root)
        except ValueError:
            print(f"警告: 文件路径 {abs_path} 不在项目根目录 {project_root} 下，已跳过。", file=sys.stderr)
            continue

        # 使用绝对路径更新指令，并记录以备处理
        instr["path"] = str(abs_path)
        valid_file_instructions.append(instr)
        path_mapping[abs_path] = None  # 暂存，稍后填充影子路径

    # 2.5. 对新文件创建进行预先审批
    new_file_paths = [p for p in path_mapping.keys() if not p.exists()]
    approved_new_file_paths = []

    if new_file_paths:
        if auto_apply:
            approved_new_file_paths = new_file_paths
        else:
            print("\nLLM请求创建以下新文件：")
            relative_new_paths = sorted([str(p.relative_to(project_root)) for p in new_file_paths])
            new_dirs_to_create = set()

            for rel_path in relative_new_paths:
                parent_dir = (project_root / rel_path).parent
                if not parent_dir.exists():
                    new_dirs_to_create.add(str(parent_dir.relative_to(project_root)))

            for i, f in enumerate(relative_new_paths):
                print(f"  [{i + 1}] {f}")

            if new_dirs_to_create:
                print(Fore.YELLOW + "\n注意：创建这些文件将创建以下新目录：" + ColorStyle.RESET_ALL)
                for d in sorted(list(new_dirs_to_create)):
                    print(f"  - {d}/")

            print("\n请输入要创建的文件编号（如 '1,3'），或 'all' 创建全部，或按Enter键跳过创建新文件。")
            user_input = input("> ").strip().lower()

            selected_relative_paths = []
            if not user_input:
                print(Fore.YELLOW + "操作已取消，将跳过创建新文件。" + ColorStyle.RESET_ALL)
            elif user_input == "all":
                selected_relative_paths = relative_new_paths
            else:
                try:
                    indices = [int(i.strip()) - 1 for i in user_input.split(",")]
                    selected_relative_paths = [
                        relative_new_paths[i] for i in indices if 0 <= i < len(relative_new_paths)
                    ]
                except ValueError:
                    print(Fore.RED + "无效输入，将跳过创建新文件。" + ColorStyle.RESET_ALL)

            if selected_relative_paths:
                approved_new_file_paths = [project_root / p for p in selected_relative_paths]
                print(Fore.GREEN + f"已批准创建 {len(approved_new_file_paths)} 个新文件。" + ColorStyle.RESET_ALL)
            elif user_input:
                print(Fore.YELLOW + "未选择任何新文件进行创建。" + ColorStyle.RESET_ALL)

        # 在主项目中为已批准的新文件创建存根
        if approved_new_file_paths:
            for new_file_path in approved_new_file_paths:
                try:
                    # 确保父目录存在
                    new_file_path.parent.mkdir(parents=True, exist_ok=True)
                    # 创建一个空的存根文件
                    new_file_path.touch()
                except Exception as e:
                    print(
                        Fore.RED + f"创建文件存根时出错 {new_file_path}: {e}" + ColorStyle.RESET_ALL,
                        file=sys.stderr,
                    )

    # 2.6. 基于审批结果过滤指令和路径
    unapproved_new_paths = set(new_file_paths) - set(approved_new_file_paths)
    if unapproved_new_paths:
        path_mapping = {k: v for k, v in path_mapping.items() if k not in unapproved_new_paths}
        valid_file_instructions = [
            instr for instr in valid_file_instructions if Path(instr["path"]) not in unapproved_new_paths
        ]

    if not valid_file_instructions and not setup_script:
        print(Fore.YELLOW + "没有文件被选中进行处理，且没有设置脚本。" + ColorStyle.RESET_ALL)
        return

    # 3. 在沙箱中准备影子文件
    shadow_root_path = Path(shadowroot)
    affected_paths_for_diff = set(path_mapping.keys())

    for original_path in affected_paths_for_diff:
        try:
            relative_path = original_path.relative_to(project_root)
        except ValueError:
            continue  # 上面已检查，此处为防御性编程

        shadow_path = shadow_root_path / relative_path
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        path_mapping[original_path] = shadow_path

        if original_path.exists() and original_path.is_file():
            with open(original_path, "r", encoding="utf-8") as f_in, open(shadow_path, "w", encoding="utf-8") as f_out:
                f_out.write(f_in.read())
        else:
            # 对于新文件或不存在的路径，创建一个空的影子文件作为起点
            shadow_path.touch()

    # 4. 使用ReplaceEngine将所有文件更改应用于影子文件
    if valid_file_instructions:
        shadow_instructions = []
        for instr in valid_file_instructions:
            original_path = Path(instr["path"])
            shadow_path = path_mapping.get(original_path)
            if shadow_path:
                new_instr = instr.copy()
                new_instr["path"] = str(shadow_path)
                shadow_instructions.append(new_instr)

        if shadow_instructions:
            engine = ReplaceEngine()
            try:
                engine.execute(shadow_instructions)
            except Exception as e:
                print(f"在沙箱中执行更改时出错: {str(e)}", file=sys.stderr)
                traceback.print_exc()
                return

    # 5. 处理安装脚本
    def _process_script(script, script_name):
        if not script:
            return
        script_path = shadow_root_path / script_name
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(script_path, 0o755)
        print(f"{script_name}已保存到: {script_path}")

    _process_script(setup_script, "project_setup.sh")

    # 6. 生成原始文件和影子文件之间的差异
    diffs_by_file = {}
    # 对路径排序以确保diff输出的确定性
    sorted_paths = sorted(list(path_mapping.keys()), key=lambda p: str(p))
    for original_path in sorted_paths:
        shadow_path = path_mapping[original_path]

        original_content = ""
        if original_path.exists() and original_path.is_file():
            with open(original_path, "r", encoding="utf-8") as f:
                original_content = f.read()

        shadow_content = ""
        if shadow_path.exists() and shadow_path.is_file():
            with open(shadow_path, "r", encoding="utf-8") as f:
                shadow_content = f.read()

        if original_content == shadow_content:
            continue

        relative_path = str(original_path.relative_to(project_root))
        diff = _generate_unified_diff(original_path, shadow_path, original_content, shadow_content)
        diffs_by_file[relative_path] = diff

    if not diffs_by_file:
        return

    # 7. 应用补丁 - 根据文件数量和auto_apply标志选择不同策略
    if len(diffs_by_file) > 1 and not auto_apply:
        # 多文件交互模式
        combined_diff = "\n\n".join(diffs_by_file.values())
        highlighted_diff = highlight(combined_diff, DiffLexer(), TerminalFormatter())
        print("\n高亮显示的diff内容：")
        print(highlighted_diff)

        print("\n检测到对多个文件的更改。请选择要应用的补丁：")
        file_list = sorted(diffs_by_file.keys())
        for i, f in enumerate(file_list):
            print(f"  [{i + 1}] {f}")
        print("请输入文件编号（如 '1,3'），或 'all' 应用全部，或按Enter键取消。")

        user_input = input("> ").strip().lower()
        if not user_input:
            print(Fore.YELLOW + "操作已取消。" + ColorStyle.RESET_ALL)
            return

        selected_paths = []
        if user_input == "all":
            selected_paths = file_list
        else:
            try:
                indices = [int(i.strip()) - 1 for i in user_input.split(",")]
                selected_paths = [file_list[i] for i in indices if 0 <= i < len(file_list)]
            except ValueError:
                print(Fore.RED + "无效输入，操作已取消。" + ColorStyle.RESET_ALL)
                return

        if not selected_paths:
            print(Fore.YELLOW + "未选择任何文件。" + ColorStyle.RESET_ALL)
            return

        applied_count = 0
        for path in selected_paths:
            if path in diffs_by_file:
                full_path = project_root / path
                if not full_path.exists():
                    full_path.parent.mkdir(parents=True, exist_ok=True)

                temp_file = shadowroot / (path.replace("/", "_") + ".diff")
                temp_file.parent.mkdir(parents=True, exist_ok=True)
                with open(temp_file, "w+", encoding="utf-8") as f:
                    f.write(diffs_by_file[path])
                _apply_patch(temp_file)
                temp_file.unlink()
                applied_count += 1
        print(Fore.GREEN + f"已成功应用对 {applied_count} 个文件的补丁。" + ColorStyle.RESET_ALL)
    else:
        # 单文件模式或自动应用模式
        for relative_path, diff_content in diffs_by_file.items():
            full_path = project_root / relative_path
            is_new_file = not full_path.exists()

            if not auto_apply:
                highlighted_diff = highlight(diff_content, DiffLexer(), TerminalFormatter())
                print("\n高亮显示的diff内容：")
                print(highlighted_diff)

            choice = "y"
            if not auto_apply:
                prompt = f"\n是否应用对 {relative_path} 的变更？"
                if is_new_file:
                    prompt = f"\n是否创建新文件 {relative_path} 并应用变更？"
                    parent_dir = full_path.parent
                    if not parent_dir.exists():
                        prompt += f"\n(这将创建新目录: {parent_dir.relative_to(project_root)})"

                choice = input(f"{prompt} [Y/n]: ").lower().strip()

            if choice in ("y", ""):
                if is_new_file:
                    full_path.parent.mkdir(parents=True, exist_ok=True)

                temp_file = shadowroot / (relative_path.replace("/", "_") + ".diff")
                with open(temp_file, "w+", encoding="utf-8") as f:
                    f.write(diff_content)
                _apply_patch(temp_file)
                temp_file.unlink()
                print(Fore.GREEN + f"已成功应用对 {relative_path} 的补丁。" + ColorStyle.RESET_ALL)
            else:
                print(Fore.YELLOW + "操作已取消。" + ColorStyle.RESET_ALL)


def display_llm_plan(thinking_process: dict):
    """
    格式化并显示从LLM响应中提取的思考过程和计划。

    Args:
        thinking_process (dict): 包含'requirement_analysis', 'solution_design'等键的字典。
    """
    if not isinstance(thinking_process, dict) or not thinking_process:
        return

    # 检查是否有任何实际内容需要显示
    if not any(
        thinking_process.get(key, "").strip()
        for key in ["requirement_analysis", "solution_design", "technical_decisions", "implementation_steps"]
    ):
        return

    print(Fore.CYAN + Style.BRIGHT + "\n💡 AI Architect's Plan & Rationale" + ColorStyle.RESET_ALL)
    print(Fore.CYAN + "------------------------------------" + ColorStyle.RESET_ALL)

    key_mapping = {
        "requirement_analysis": "Requirement Analysis",
        "solution_design": "Solution Design",
        "technical_decisions": "Technical Decisions",
        "implementation_steps": "Implementation Steps",
    }

    for key, title in key_mapping.items():
        content = thinking_process.get(key)
        if content and content.strip():
            print(Style.BRIGHT + Fore.YELLOW + f"\n▶ {title}:" + ColorStyle.RESET_ALL)
            indented_content = "\n".join([f"  {line}" for line in content.splitlines()])
            print(f"{indented_content}")

    print("\n" + Fore.CYAN + "------------------------------------" + ColorStyle.RESET_ALL)
    print("Now, reviewing the proposed code changes...\n")


def process_response(prompt, content, file_path, save=True, obsidian_doc=None, ask_param=None, use_json_output=False):
    """处理API响应并保存结果"""

    # 处理文件路径
    file_path = Path(file_path)
    if save and file_path:
        with open(file_path, "w+", encoding="utf8") as f:
            # 删除内容
            cleaned_content = re.sub(r"<th" + r"ink>\n?.*?\n?</th" + r"ink>\n*", "", content, flags=re.DOTALL)
            f.write(cleaned_content.strip())

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as tmp_file:
        tmp_file.write(content)
        save_path = tmp_file.name

    # 处理Obsidian文档存储
    if obsidian_doc:
        save_to_obsidian(obsidian_doc, content, prompt, ask_param)

    if not check_deps_installed():
        sys.exit(1)

    if GPT_FLAGS.get(GPT_FLAG_GLOW):
        # 调用提取和diff函数
        try:
            subprocess.run(["glow", save_path], check=True)
            # 如果是临时文件，使用后删除
            if not save:
                os.unlink(save_path)
        except subprocess.CalledProcessError as e:
            print(f"glow运行失败: {e}")

    if GPT_FLAGS.get(GPT_FLAG_EDIT):
        extract_and_diff_files(content)
    if GPT_FLAGS.get(GPT_FLAG_PATCH):
        os.chdir(GLOBAL_PROJECT_CONFIG.project_root_dir)
        process_patch_response(
            content, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH], relative_to_root=True, use_json_output=use_json_output
        )


def save_to_obsidian(obsidian_doc, content, prompt=None, ask_param=None):
    """将内容保存到Obsidian文档系统

    Args:
        obsidian_doc: Obsidian文档目录路径
        content: 要保存的内容
        prompt: 可选的问题提示
        ask_param: 可选的参数用于生成链接名称
    """
    obsidian_dir = Path(obsidian_doc)
    obsidian_dir.mkdir(parents=True, exist_ok=True)

    # 创建按年月分组的子目录
    now = time.localtime()
    month_dir = obsidian_dir / f"{now.tm_year}-{now.tm_mon}-{now.tm_mday}"
    month_dir.mkdir(exist_ok=True)

    # 生成时间戳文件名
    timestamp = f"{now.tm_hour}-{now.tm_min}-{now.tm_sec}.md"
    obsidian_file = month_dir / timestamp

    # 格式化内容：将非空思维过程渲染为绿色，去除背景色
    formatted_content = re.sub(
        r"<think>\n*([\s\S]*?)\n*</think>",
        lambda match: '<div style="color: #228B22; padding: 10px; border-radius: 5px; margin: 10px 0;">'
        + match.group(1).replace("\n", "<br>")
        + "</div>",
        content,
        flags=re.DOTALL,
    )

    # 添加提示词
    if prompt:
        formatted_content = f"### 问题\n\n````\n{prompt}\n````\n\n### 回答\n{formatted_content}"

    # 写入响应内容
    with open(obsidian_file, "w", encoding="utf-8") as f:
        f.write(formatted_content)

    # 更新main.md
    main_file = obsidian_dir / f"{now.tm_year}-{now.tm_mon}-{now.tm_mday}-索引.md"
    link_name = re.sub(r"[{}]", "", ask_param[:256]) if ask_param else timestamp
    link = f"[[{month_dir.name}/{timestamp}|{link_name}]]\n"

    with open(main_file, "a", encoding="utf-8") as f:
        f.write(link)


def validate_files(program_args):
    """验证输入文件是否存在"""
    if not (program_args.ask or program_args.chatbot or program_args.project_search):  # 仅在需要检查文件时执行
        if not os.path.isfile(program_args.file):
            print(f"错误：源代码文件不存在 {program_args.file}")
            sys.exit(1)


def print_proxy_info(proxies, proxy_sources):
    """打印代理配置信息"""
    if proxies:
        print("⚡ 检测到代理：")
        max_len = max(len(p) for p in proxies)
        for protocol in sorted(proxies.keys()):
            source_var = proxy_sources.get(protocol, "unknown")
            sanitized = sanitize_proxy_url(proxies[protocol])
            print(f"  ├─ {protocol.upper().ljust(max_len)} : {sanitized}")
            print(f"  └─ {'via'.ljust(max_len)} : {source_var}")
    else:
        print("ℹ️ 未检测到代理配置环境")


def handle_ask_mode(program_args, proxies):
    """处理--ask模式"""
    program_args.ask = program_args.ask.replace("@symbol_", "@symbol:")
    model_switch = ModelSwitch()
    model_switch.select(os.environ["GPT_MODEL_KEY"])
    context_processor = GPTContextProcessor()
    # 根据模型配置自动设置use_json_output
    use_json_output = GLOBAL_MODEL_CONFIG.supports_json_output
    text = context_processor.process_text(program_args.ask, use_json_output=use_json_output)
    print(text)
    response_data = model_switch.query(
        os.environ["GPT_MODEL_KEY"], text, proxies=proxies, use_json_output=use_json_output
    )
    process_response(
        text,
        response_data,
        os.path.join(os.path.dirname(__file__), ".lastgptanswer"),
        save=True,
        obsidian_doc=program_args.obsidian_doc,
        ask_param=program_args.ask,
        use_json_output=use_json_output,  # 新增传递use_json_output
    )


def prompt_words_search(words: List[str], args):
    """根据关键词执行配置化搜索

    Args:
        words: 需要搜索的关键词列表
        args: 命令行参数对象

    Raises:
        ValueError: 当输入不是非空字符串列表时
    """
    if not words or any(not isinstance(w, str) or len(w.strip()) == 0 for w in words):
        raise ValueError("需要至少一个有效搜索关键词")

    config = ConfigLoader(args.config).load_search_config()
    config.root_dir = Path.cwd()
    searcher = RipgrepSearcher(config, debug=True)

    try:
        print(f"🔍 搜索关键词: {', '.join(words)}")
        results = searcher.search(patterns=[re.escape(word) for word in words])
        print(f"找到 {len(results)} 个匹配文件")

        for result in results:
            print(f"\n🔍 在 {result.file_path}:")
            for match in result.matches:
                highlighted = (
                    match.text[: match.column_range[0]]
                    + ColorStyle.BRIGHT
                    + Fore.RED
                    + match.text[match.column_range[0] : match.column_range[1]]
                    + ColorStyle.RESET_ALL
                    + match.text[match.column_range[1] :]
                )
                print(f"  L{match.line}: {highlighted.strip()}")

    except (FileNotFoundError, PermissionError, RuntimeError) as e:
        print(f"搜索失败: {str(e)}")
        sys.exit(1)


def perform_search(
    words: List[str],
    config_path: str = LLM_PROJECT_CONFIG,
    max_context_size=1024 * 128,
    file_list: List[str] = None,
) -> dict:
    """执行代码搜索并返回强类型结果"""
    if not words or any(not isinstance(word, str) or len(word.strip()) == 0 for word in words):
        raise ValueError("需要至少一个有效搜索关键词")
    config = ConfigLoader(Path(config_path)).load_search_config()
    config.root_dir = Path.cwd()
    searcher = RipgrepSearcher(config, debug=True, file_list=file_list)
    rg_results = searcher.search(patterns=[re.escape(word) for word in words])
    results: FileSearchResults = FileSearchResults(
        results=[
            FileSearchResult(
                file_path=str(result.file_path),
                matches=[
                    MatchResult(
                        line=match.line,
                        column_range=match.column_range,
                        text=match.text,
                    )
                    for match in result.matches
                ],
            )
            for result in rg_results
        ]
    )
    return query_symbol_service(results, max_context_size)


def query_symbol_service(results: FileSearchResults, max_context_size: int) -> dict:
    """独立的API请求处理函数"""
    api_server = os.getenv("GPT_SYMBOL_API_URL", "http://127.0.0.1:9050/")
    if api_server.endswith("/"):
        api_server = api_server[:-1]
    api_url = f"{api_server}/search-to-symbols?max_context_size={max_context_size}"
    try:
        with ProxyEnvDisable():
            response = requests.post(
                api_url,
                proxies={"http": None, "https": None},
                data=results.to_json(),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            return response.json()["results"]
    except requests.exceptions.RequestException as e:
        print(f"API请求失败: {str(e)}")
    except json.JSONDecodeError:
        print("API返回无效的JSON响应")
    except (ValueError, KeyError) as e:
        print(f"处理API响应时发生数据解析错误: {str(e)}")
    return None


class ProxyEnvDisable:
    """
    资源管理器用于临时禁用代理环境变量

    进入上下文时移除所有代理相关环境变量，退出时恢复原始值
    处理变量：http_proxy, https_proxy, ftp_proxy及其大写形式
    """

    PROXY_VARS = {
        "all_proxy",
        "http_proxy",
        "https_proxy",
        "ftp_proxy",
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "FTP_PROXY",
    }

    def __init__(self):
        self.original_proxies = {}
        for var in self.PROXY_VARS:
            self.original_proxies[var] = os.environ.get(var)

    def __enter__(self):
        for var in self.PROXY_VARS:
            os.environ.pop(var, None)

    def __exit__(self, exc_type, exc_val, exc_tb):
        for var, value in self.original_proxies.items():
            if value is not None:
                os.environ[var] = value
            else:
                os.environ.pop(var, None)


class ModelSwitch:
    """
    根据模型名称自动切换配置并调用API查询

    从与当前文件同目录下的model.json加载模型配置

    假设:
        - model.json文件存在且包含对应模型配置
        - 配置中包含'key', 'base_url', 'model'字段
        如果不符合上述假设，将抛出异常
    """

    def __init__(self, config_path: str = None, test_mode: bool = False):
        """
        初始化模型切换器

        参数:
            config_path (str, optional): 自定义配置文件路径. 默认为None表示使用默认路径
            test_mode (bool, optional): 测试模式标志位. 默认为False
        """
        self._config_path = config_path
        self.test_mode = test_mode
        self._config_cache = None  # 配置缓存
        self.current_config: Optional[ModelConfig] = None
        self.workflow = None
        self.model_name = ""
        self._usage_records = {}  # 计费记录
        self._usage_file = os.path.join(os.path.dirname(__file__), ".model_usage.yaml")
        if not test_mode:
            self._load_usage_from_file()  # 初始化时加载历史记录

    def models(self) -> list[str]:
        """获取所有可用的模型名称列表"""
        return list(self._get_config().keys())

    def _load_and_validate_config(self, config_dict: dict) -> ModelConfig:
        """加载并验证配置字典"""
        required_fields = {"key", "base_url", "model_name"}
        if not required_fields.issubset(config_dict.keys()):
            missing = required_fields - config_dict.keys()
            raise ValueError(f"模型配置缺少必要字段: {missing}")

        return ModelConfig(
            key=config_dict["key"],
            base_url=config_dict["base_url"],
            model_name=config_dict["model_name"],
            tokenizer_name=config_dict.get("tokenizer_name"),
            max_context_size=config_dict.get("max_context_size"),
            temperature=config_dict.get("temperature", 0.0),
            is_thinking=config_dict.get("is_thinking", False),
            max_tokens=config_dict.get("max_tokens"),
            thinking_budget=config_dict.get("thinking_budget", 32768),
            top_k=config_dict.get("top_k", 20),
            top_p=config_dict.get("top_p", 0.95),
            price_1m_input=config_dict.get("price_1M_input"),
            price_1m_output=config_dict.get("price_1M_output"),
            http_proxy=config_dict.get("http_proxy"),
            https_proxy=config_dict.get("https_proxy"),
            supports_json_output=config_dict.get("supports_json_output", False),
        )

    def _get_config(self) -> dict[str, ModelConfig]:
        """获取配置，使用缓存机制"""
        if self._config_cache is not None:
            return self._config_cache

        config = self._load_config()
        self._config_cache = config
        return config

    def _load_config(self, default_path: str = "model.json") -> dict[str, ModelConfig]:
        """加载模型配置文件并转换为ModelConfig字典"""
        config_path = self._config_path or os.path.join(os.path.dirname(__file__), default_path)

        try:
            with open(config_path, "r") as f:
                raw_config = json.load(f)
                return {name: self._load_and_validate_config(config) for name, config in raw_config.items()}
        except FileNotFoundError as e:
            error_msg = f"模型配置文件未找到: {config_path}"
            if self.test_mode:
                return self._get_test_config()
            raise ValueError(error_msg) from e
        except json.JSONDecodeError as e:
            error_msg = f"配置文件格式错误: {config_path}"
            if self.test_mode:
                return self._get_test_config()
            raise ValueError(error_msg) from e
        except ValueError as e:
            error_msg = f"配置验证失败: {str(e)}"
            if self.test_mode:
                return self._get_test_config()
            raise ValueError(error_msg) from e

    def _get_test_config(self) -> dict[str, ModelConfig]:
        """获取测试配置"""
        return {
            "test_model": ModelConfig(
                key="test_key",
                base_url="http://test",
                model_name="test",
                tokenizer_name="test",
                max_context_size=8192,
                temperature=0.0,
                price_1m_input=0.5,
                price_1m_output=1.5,
                http_proxy=None,
                https_proxy=None,
                supports_json_output=True,
            )
        }

    def _get_model_config(self, model_name: str) -> ModelConfig:
        """获取指定模型的配置"""
        config = self._get_config()
        if model_name not in config:
            error_msg = f"未找到模型配置: {model_name}"
            if self.test_mode:
                return self._get_test_config()["test_model"]
            raise ValueError(error_msg)
        return config[model_name]

    @contextlib.contextmanager
    def _temp_env_vars(self, config: ModelConfig):
        """临时设置模型配置相关的环境变量"""
        # 保存当前环境变量
        old_env = {
            "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
            "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
        }
        try:
            # 设置新的代理环境变量
            if config.http_proxy:
                os.environ["HTTP_PROXY"] = config.http_proxy
            if config.https_proxy:
                os.environ["HTTPS_PROXY"] = config.https_proxy

            yield  # 执行请求
        finally:
            # 恢复原始环境变量
            if old_env["HTTP_PROXY"] is not None:
                os.environ["HTTP_PROXY"] = old_env["HTTP_PROXY"]
            else:
                os.environ.pop("HTTP_PROXY", None)

            if old_env["HTTPS_PROXY"] is not None:
                os.environ["HTTPS_PROXY"] = old_env["HTTPS_PROXY"]
            else:
                os.environ.pop("HTTPS_PROXY", None)

    def execute_workflow(
        self,
        architect_model: str,
        coder_model: str,
        prompt: str,
        architect_only: bool = False,
    ) -> list:
        """
        执行完整工作流程：
        1. 使用架构模型获取任务划分
        2. 解析架构师响应
        3. 分发任务给编码模型执行
        4. 提供重试机制

        返回:
            list: 包含所有任务执行结果的列表
        """
        # Lazy load workflow to break circular import
        if self.workflow is None:
            self.workflow = import_relative("gpt_workflow")

        if self.test_mode:
            return ["test_response"]

        GPT_FLAGS[GPT_FLAG_PATCH] = True
        context_processor = GPTContextProcessor()

        # 获取架构师配置
        self.select(architect_model)
        architect_config = self._get_model_config(architect_model)

        # 处理提示词
        text = context_processor.process_text(prompt, tokens_left=architect_config.max_context_size or 32 * 1024)
        architect_prompt = Path(os.path.join(os.path.dirname(__file__), "prompts/architect")).read_text(
            encoding="utf-8"
        )
        architect_prompt += f"\n{text}"

        # 使用临时环境变量执行架构师请求
        with self._temp_env_vars(architect_config):
            # 获取架构师响应
            architect_response = self.query(architect_model, architect_prompt)

        parsed = self.workflow.ArchitectMode.parse_response(architect_response)

        # 处理编码任务
        results = []
        if not architect_only:
            coder_config = self._get_model_config(coder_model)
            coder_prompt = Path(os.path.join(os.path.dirname(__file__), "prompts/coder")).read_text(encoding="utf-8")

            for job in parsed["jobs"]:
                # 使用临时环境变量执行编码任务
                with self._temp_env_vars(coder_config):
                    results.append(self._process_coder_job(job, coder_model, coder_config, coder_prompt, prompt))

        return results

    def _process_coder_job(self, job, coder_model, coder_config, coder_prompt, original_prompt) -> str:
        """处理单个编码任务"""
        while True:
            print(f"🔧 开始执行任务: {job['content']}")

            # 构建提示词
            part_a = f"{get_patch_prompt_output(True, None, dumb_prompt=DUMB_EXAMPLE_A)}\n{CHANGE_LOG_HEADER}\n"
            part_b = f"{PUA_PROMPT}{coder_prompt}[your job start]:\n{job['content']}\n[your job end]"

            context_processor = GPTContextProcessor()
            context = context_processor.process_text(
                original_prompt,
                ignore_text=True,
                tokens_left=(coder_config.max_context_size or 32 * 1024) - len(part_a) - len(part_b),
            )

            coder_prompt_combine = f"{part_b}{context}{part_a}".replace(USER_DEMAND, "")

            # 执行查询, query方法现在直接返回内容字符串
            content = self.query(coder_model, coder_prompt_combine)

            # 处理补丁响应
            process_patch_response(
                content,
                GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH],
                auto_commit=False,
                auto_lint=False,
            )

            # 用户确认
            retry = input("是否要重新执行此任务？(y/n): ").lower()
            if retry != "y":
                return content

            print("🔄 正在重试任务...")

    def select(self, model_name: str) -> None:
        """切换到指定模型"""
        if self.test_mode:
            return

        self.current_config = self._get_model_config(model_name)
        self.model_name = model_name
        globals()["GLOBAL_MODEL_CONFIG"] = self.current_config

    def _calculate_cost(self, input_tokens: int, output_tokens: int, config: ModelConfig) -> float:
        """计算API调用费用(美元)，精确到小数点后6位"""
        input_cost_per_token = (config.price_1m_input or 0) / 1_000_000
        output_cost_per_token = (config.price_1m_output or 0) / 1_000_000

        input_cost = input_tokens * input_cost_per_token
        output_cost = output_tokens * output_cost_per_token
        return input_cost + output_cost

    def _record_usage(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """记录API使用情况，精确计算费用并返回费用值"""
        today = datetime.date.today().isoformat()
        config = self._get_model_config(model_name)
        cost = self._calculate_cost(input_tokens, output_tokens, config)

        # 初始化当天记录
        if today not in self._usage_records:
            self._usage_records[today] = {
                "total_cost": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "models": {},
            }

        # 更新总记录
        self._usage_records[today]["total_cost"] += cost
        self._usage_records[today]["total_input_tokens"] += input_tokens
        self._usage_records[today]["total_output_tokens"] += output_tokens

        # 更新模型记录
        if model_name not in self._usage_records[today]["models"]:
            self._usage_records[today]["models"][model_name] = {
                "count": 0,
                "cost": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }

        model_record = self._usage_records[today]["models"][model_name]
        model_record["count"] += 1
        model_record["cost"] += cost
        model_record["input_tokens"] += input_tokens
        model_record["output_tokens"] += output_tokens

        self._save_usage_to_file()
        return cost

    def _save_usage_to_file(self) -> None:
        """将使用记录保存到文件（与当前文件同目录）"""
        try:
            with open(self._usage_file, "w") as f:
                yaml.safe_dump(self._usage_records, f)
        except Exception as e:
            print(f"保存使用记录失败: {str(e)}")

    def _load_usage_from_file(self) -> None:
        """从文件加载历史使用记录（与当前文件同目录）"""
        if not os.path.exists(self._usage_file):
            return

        try:
            with open(self._usage_file, "r") as f:
                self._usage_records = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"加载使用记录失败: {str(e)}")
            self._usage_records = {}

    def _record_usage_and_display(self, model_name: str, response: dict) -> None:
        """记录API使用情况并显示消费信息"""
        usage_data = response.get("usage", {})
        if not usage_data:
            return

        input_tokens = usage_data["prompt_tokens"]
        output_tokens = usage_data["completion_tokens"]
        cost = self._record_usage(model_name, input_tokens, output_tokens)

        if cost <= 0:
            return

        # 计算人民币成本
        cost_cny = cost * 7  # 1美元≈7人民币
        today = datetime.date.today().isoformat()
        accumulated_cost = 0.0

        # 获取当天累计消费
        if today in self._usage_records:
            model_record = self._usage_records[today]["models"].get(model_name)
            if model_record:
                accumulated_cost = model_record["cost"]

        # 显示消费信息
        cost_message = (
            f"{Fore.CYAN}API调用消费: "
            f"{ColorStyle.BRIGHT}${cost:.6f}{ColorStyle.RESET_ALL}{Fore.CYAN} "
            f"(≈¥{cost_cny:.2f}) | "
            f"输入Token: {Fore.GREEN}{input_tokens}{Fore.CYAN} | "
            f"输出Token: {Fore.GREEN}{output_tokens}{Fore.CYAN} | "
            f"模型: {Fore.YELLOW}{model_name}{ColorStyle.RESET_ALL} | "
            f"今天累计: ${accumulated_cost:.6f}"
        )
        print(cost_message)

        # 单次请求费用超过5元人民币警告
        if not self.test_mode and cost_cny > 5.0:
            warning_msg = (
                f"{Fore.RED}{ColorStyle.BRIGHT}警告：单次请求费用超过5元人民币！"
                f"({cost_cny:.2f}元){ColorStyle.RESET_ALL}"
            )
            print(warning_msg)
            print(f"{Fore.RED}请确认是否继续执行大模型请求{ColorStyle.RESET_ALL}")

    def _execute_query(self, config: ModelConfig, prompt: str, **kwargs) -> dict:
        """执行单次API查询"""
        with self._temp_env_vars(config):
            response = query_gpt_api(
                base_url=config.base_url,
                api_key=config.key,
                prompt=prompt,
                model=config.model_name,
                model_config=config,
                **kwargs,
            )
        return response

    def _retry_query(
        self,
        config: ModelConfig,
        model_name: str,
        prompt: str,
        kwargs: dict,
        max_retries: int = 3,
        retry_delay: int = 5,
    ) -> dict:
        """带重试机制的API查询"""
        for attempt in range(max_retries):
            try:
                response = self._execute_query(config, prompt, **kwargs)
                return response
            except Exception as e:
                debug_info = f"API调用失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}\n当前配置状态: {config}"
                print(debug_info)

                if attempt < max_retries - 1:
                    print(f"{retry_delay}s后重试...")
                    time.sleep(retry_delay)

        raise RuntimeError(f"API调用失败，重试次数已用尽: {max_retries}")

    def query(
        self, model_name: str, prompt: str, disable_conversation_history=True, use_json_output: bool = False, **kwargs
    ) -> str:
        """
        根据模型名称查询API

        参数:
            model_name (str): 配置中的模型名称(如'14b')
            prompt (str): 用户输入的提示词
            disable_conversation_history (bool): 是否禁用对话历史
            use_json_output (bool): 是否强制使用JSON输出模式
            kwargs: 其他传递给query_gpt_api的参数

        返回:
            str: API响应中的内容字符串

        异常:
            ValueError: 当模型配置不存在或缺少必要字段时
        """
        if self.test_mode:
            return "test_response"

        # 获取模型配置
        config = self._get_model_config(model_name)
        self.current_config = config

        # 准备查询参数
        query_kwargs = {
            "disable_conversation_history": disable_conversation_history,
            "use_json_output": use_json_output,
            "max_context_size": config.max_context_size,
            "temperature": config.temperature,
            "enable_thinking": config.is_thinking,
            "thinking_budget": config.thinking_budget,
            "top_k": config.top_k,
            "top_p": config.top_p,
            **kwargs,
        }

        # 执行带重试的查询
        response = self._retry_query(config, model_name, prompt, query_kwargs)

        # 记录并显示使用情况
        self._record_usage_and_display(model_name, response)

        return response["choices"][0]["message"]["content"]


def handle_workflow(program_args):
    program_args.ask = program_args.ask.replace("@symbol_", "@symbol:")
    ModelSwitch().execute_workflow(program_args.architect, program_args.coder, program_args.ask)


def import_relative(module):
    parent = os.path.dirname(__file__)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return __import__(module)


def start_chatbot():
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        import tools
    else:
        tools = import_relative("tools")
    tools.ChatbotUI().run()


def find_changelog():
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        import gpt_workflow
    else:
        gpt_workflow = import_relative("gpt_workflow")
    return gpt_workflow.ChangelogMarkdown()


def start_pylint(log: Path):
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        import gpt_workflow
    else:
        gpt_workflow = import_relative("gpt_workflow")
    gpt_workflow.pylint_fix(str(log))


def main(input_args):
    shadowroot.mkdir(parents=True, exist_ok=True)

    validate_files(input_args)
    proxies, proxy_sources = detect_proxies()
    print_proxy_info(proxies, proxy_sources)

    if input_args.workflow:
        if not input_args.architect or not input_args.coder:
            raise SystemExit("错误: 工作流模式需要同时指定 --architect 和 --coder 参数")
        handle_workflow(input_args)
    elif input_args.ask:
        handle_ask_mode(input_args, proxies)
    elif input_args.file:
        input_args.ask = Path(input_args.file).read_text("utf8")
        handle_ask_mode(input_args, proxies)
    elif input_args.chatbot:
        start_chatbot()
    elif input_args.project_search:
        prompt_words_search(input_args.project_search, input_args)
        symbols = perform_search(input_args.project_search, input_args.config)
        pprint.pprint(symbols)


if __name__ == "__main__":
    args = parse_arguments()
    if args.trace:
        tracer = trace.Trace(trace=1)
        tracer.runfunc(main, args)
    elif args.pylint_log:
        start_pylint(args.pylint_log)
    else:
        main(args)
