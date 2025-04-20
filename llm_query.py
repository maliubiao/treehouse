#!/usr/bin/env python
"""
LLM 查询工具模块

该模块提供与OpenAI兼容 API交互的功能，支持代码分析、多轮对话、剪贴板集成等功能。
包含代理配置检测、代码分块处理、对话历史管理等功能。
"""
import argparse
import datetime
import difflib
import fnmatch
import json
import logging
import marshal
import os
import platform
import pprint
import re
import signal
import socket
import stat
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
from typing import Callable, Dict, List, Optional, Tuple, TypedDict, Union
from urllib.parse import urlparse

import requests
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import Style
from pydantic import BaseModel
from pygments import highlight
from pygments.formatters.terminal import TerminalFormatter
from pygments.lexers.diff import DiffLexer
from pygments.lexers.markup import MarkdownLexer

# 初始化Markdown渲染器
from rich.console import Console
from rich.table import Table
from rich.text import Text

from tree import (
    GLOBAL_PROJECT_CONFIG,
    LLM_PROJECT_CONFIG,
    BlockPatch,
    ConfigLoader,
    FileSearchResult,
    FileSearchResults,
    MatchResult,
    ParserLoader,
    ParserUtil,
    RipgrepSearcher,
    SyntaxHighlight,
)


class ModelConfig:
    key: str
    base_url: str
    model_name: str
    max_context_size: int | None = None
    temperature: float = 0.0
    is_thinking: bool = False
    max_tokens: int | None = None

    def __init__(
        self,
        key: str,
        base_url: str,
        model_name: str,
        max_context_size: int | None = None,
        temperature: float = 0.0,
        is_thinking: bool = False,
        max_tokens: int | None = None,
    ):
        self.key = key
        self.base_url = base_url
        self.model_name = model_name
        self.max_context_size = max_context_size
        self.temperature = temperature
        self.is_thinking = is_thinking
        self.max_tokens = max_tokens

    def __repr__(self) -> str:
        masked_key = f"{self.key[:3]}***" if self.key else "None"
        return (
            f"ModelConfig(base_url={self.base_url!r}, model_name={self.model_name!r}, "
            f"max_context_size={self.max_context_size}, temperature={self.temperature}, "
            f"is_thinking={self.is_thinking}, max_tokens={self.max_tokens}, key={masked_key})"
        )

    def get_debug_info(self) -> dict:
        """获取用于调试的配置信息"""
        return {
            "base_url": self.base_url,
            "model_name": self.model_name,
            "max_context_size": self.max_context_size,
            "temperature": self.temperature,
            "is_thinking": self.is_thinking,
            "max_tokens": self.max_tokens,
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

        max_context_size = os.environ.get("GPT_MAX_CONTEXT_SIZE")
        temperature = os.environ.get("GPT_TEMPERATURE")
        is_thinking = os.environ.get("GPT_IS_THINKING")
        max_tokens = os.environ.get("GPT_MAX_TOKENS")

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
            is_thinking = bool(is_thinking) if is_thinking is not None else False
        except ValueError as exc:
            raise ValueError(f"无效的is_thinking值: {is_thinking}") from exc

        try:
            max_tokens = int(max_tokens) if max_tokens is not None else None
        except ValueError as exc:
            raise ValueError(f"无效的max_tokens值: {max_tokens}") from exc

        return cls(
            key=key,
            base_url=base_url,
            model_name=model_name,
            max_context_size=max_context_size,
            temperature=temperature,
            is_thinking=is_thinking,
            max_tokens=max_tokens,
        )


GLOBAL_MODEL_CONFIG = ModelConfig.from_env()
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
class SymbolsNode:
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
    group.add_argument("--chatbot", action="store_true", help="进入聊天机器人UI模式，与--file和--ask互斥")
    group.add_argument("--project-search", nargs="+", metavar="KEYWORD", help="执行项目关键词搜索(支持多词)")
    group.add_argument("--pylint-log", type=Path, help="执行Pylint修复的日志文件路径")
    parser.add_argument("--workflow", action="store_true", help="进入工作流执行模式")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), ".llm_project.yml"),
        type=Path,
        help="项目配置文件路径（YAML格式）",
    )
    parser.add_argument(
        "--prompt-file",
        default=os.path.expanduser("~/.llm/source-query.txt"),
        help="提示词模板文件路径（仅在使用--file时有效）",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=MAX_FILE_SIZE,
        help="代码分块大小（字符数，仅在使用--file时有效）",
    )
    parser.add_argument(
        "--obsidian-doc",
        default=os.environ.get("GPT_DOC", os.path.join(os.path.dirname(__file__), "obsidian")),
        help="Obsidian文档备份目录路径",
    )
    parser.add_argument("--trace", action="store_true", help="启用详细的执行跟踪")
    parser.add_argument("--architect", required="--workflow" in sys.argv, help="架构师模型名称（工作流模式必需）")
    parser.add_argument("--coder", required="--workflow" in sys.argv, help="编码器模型名称（工作流模式必需）")
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

        # 获取API响应
        response = _get_api_response(api_key, model, history, kwargs)

        # 处理并保存响应
        return _process_and_save_response(response, history, kwargs)

    except requests.exceptions.HTTPError as he:
        debug_info = GLOBAL_MODEL_CONFIG.get_debug_info()
        error_msg = f"API请求失败 HTTP {he.response.status_code}\n"
        error_msg += f"请求配置: {debug_info}\n"

        if he.response.status_code in (401, 403):
            error_msg += "可能原因: 1. API密钥无效 2. 账户欠费 3. 权限不足\n"
            error_msg += f"请检查密钥前三位: {debug_info['key_prefix']} 是否正确"

        raise RuntimeError(error_msg) from he

    except requests.exceptions.RequestException as req_exc:
        debug_info = GLOBAL_MODEL_CONFIG.get_debug_info()
        error_msg = f"网络请求异常: {str(req_exc)}\n"
        error_msg += f"当前配置: {debug_info}"
        raise RuntimeError(error_msg) from req_exc

    except RuntimeError as runtime_exc:
        print(f"详细错误信息: {str(runtime_exc)}")
        raise runtime_exc
    except (ValueError, TypeError, KeyError) as specific_exc:
        debug_info = GLOBAL_MODEL_CONFIG.get_debug_info()
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
        Generator: 流式响应生成器
    """
    client = OpenAI(api_key=api_key, base_url=kwargs.get("base_url"))
    try:
        return client.chat.completions.create(
            model=model,
            messages=history,
            temperature=kwargs.get("temperature", 0.0),
            top_p=0.8,
            stream=True,
        )
    except Exception as e:
        err_msg = f"API请求失败: {str(e)}"
        raise RuntimeError(err_msg) from e


def _process_and_save_response(
    stream,
    history: list,
    kwargs: dict,
) -> dict:
    """处理并保存API响应

    参数:
        stream (Generator): 流式响应
        history (list): 对话历史
        kwargs (dict): 包含conversation_file等参数

    返回:
        dict: 处理后的响应结果
    """
    content, reasoning = _process_stream_response(stream, kwargs.get("console"))

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

    return {"choices": [{"message": {"content": content}}]}


def _process_stream_response(stream, console) -> tuple:
    """处理流式响应

    参数:
        stream (Generator): 流式响应
        console: 控制台输出对象

    返回:
        tuple: (正式内容, 推理内容)
    """
    content = ""
    reasoning = ""

    for chunk in stream:
        # 处理推理内容
        if hasattr(chunk.choices[0].delta, "reasoning_content") and chunk.choices[0].delta.reasoning_content:
            _print_content(chunk.choices[0].delta.reasoning_content, console, style="#00ff00")
            reasoning += chunk.choices[0].delta.reasoning_content

        # 处理正式回复内容
        if chunk.choices[0].delta.content:
            _print_content(chunk.choices[0].delta.content, console)
            content += chunk.choices[0].delta.content

    _print_newline(console)
    return content, reasoning


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
    tool_name: str, install_url: str | None = None, install_commands: list[str] | None = None
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
        subprocess.run(check_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
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
                    install_commands=["sudo apt install xsel  # Debian/Ubuntu", "sudo yum install xsel  # RHEL/CentOS"],
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


def get_directory_context(max_depth=1):
    """获取当前目录上下文信息（支持动态层级控制）"""
    try:
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
            cmd = ["tree"]
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
    """获取剪贴板内容的封装函数，统一返回字符串内容"""
    try:
        if sys.platform == "win32":
            win32clipboard = __import__("win32clipboard")
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData()
            win32clipboard.CloseClipboard()
            return data
        if sys.platform == "darwin":
            result = subprocess.run(["pbpaste"], stdout=subprocess.PIPE, text=True, check=True)
            return result.stdout
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
            try:
                result = subprocess.run(
                    ["xsel", "--clipboard", "--output"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True,
                )
                return result.stdout
            except FileNotFoundError:
                print("未找到 xclip 或 xsel")
                return "无法获取剪贴板内容：未找到xclip或xsel"
    except (FileNotFoundError, subprocess.CalledProcessError, ImportError) as e:
        print(f"获取剪贴板内容时出错: {str(e)}")
        return f"获取剪贴板内容时出错: {str(e)}"


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


def _handle_command(match: CmdNode, cmd_map: Dict[str, Callable]) -> str:
    """处理命令类型匹配

    根据输入的CmdNode或CmdNode列表，执行对应的命令处理函数。

    参数：
        match: 要处理的命令，可以是CmdNode或CmdNode列表
        cmd_map: 命令映射字典，key为命令前缀，value为对应的处理函数

    返回：
        命令处理函数的执行结果
    """
    # 处理单个CmdNode
    return cmd_map[match.command](match)


def _handle_any_script(match: CmdNode) -> str:
    """处理shell命令"""
    script_name = match.command.strip("=")
    file_path = os.path.join(os.environ.get("GPT_PATH", ""), "prompts", script_name)
    # 检查文件是否有执行权限
    if not os.access(file_path, os.X_OK):
        # 获取当前文件权限
        current_mode = os.stat(file_path).st_mode
        # 添加用户执行权限
        new_mode = current_mode | stat.S_IXUSR
        # 修改文件权限
        os.chmod(file_path, new_mode)

    try:
        # 使用with语句管理子进程资源
        with subprocess.Popen(
            f"{file_path}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        ) as process:
            stdout, stderr = process.communicate()
            output = f"\n\n[shell command]: ./{file_path}\n"
            output += f"[stdout begin]\n{stdout}\n[stdout end]\n"
            if stderr:
                output += f"[stderr begin]\n{stderr}\n[stderr end]\n"
            return output
    except subprocess.SubprocessError as e:
        return f"\n\n[shell command error]: {str(e)}\n"


def _handle_prompt_file(match: CmdNode) -> str:
    """处理prompts目录文件"""
    file_path = os.path.join(PROMPT_DIR, match.command)

    # 检查文件是否有可执行权限或以#!开头
    if os.access(file_path, os.X_OK):
        # 如果有可执行权限，则作为shell命令处理
        return _handle_any_script(match)

    # 检查文件是否以#!开头
    with open(file_path, "r", encoding="utf-8") as f:
        first_line = f.readline()
        if first_line.startswith("#!"):
            # 如果以#!开头，也作为shell命令处理
            return _handle_any_script(match)
        # 否则读取整个文件内容作为普通文件处理
        content = first_line + f.read()
        return f"\n{content}\n"


def _handle_local_file(match: CmdNode) -> str:
    """处理本地文件路径"""
    expanded_path, line_range_match = _expand_file_path(match.command)

    if os.path.isfile(expanded_path):
        return _process_single_file(expanded_path, line_range_match)
    if os.path.isdir(expanded_path):
        return _process_directory(expanded_path)
    return f"\n\n[error]: 路径不存在 {expanded_path}\n\n"


def _expand_file_path(command: str) -> tuple:
    """展开文件路径并解析行号范围"""
    line_range_match = re.search(r":(\d+)?-(\d+)?$", command)
    expanded_path = os.path.abspath(
        os.path.expanduser(command[: line_range_match.start()] if line_range_match else command)
    )
    return expanded_path, line_range_match


def _process_single_file(file_path: str, line_range_match: re.Match) -> str:
    """处理单个文件内容"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = _read_file_content(f, line_range_match)
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
    return f"\n\n[file name]: {file_path}\n[file content begin]\n{content}\n[file content end]\n\n"


def _process_directory(dir_path: str) -> str:
    """处理目录内容"""
    gitignore_path = _find_gitignore(dir_path)
    root_dir = os.path.dirname(gitignore_path) if gitignore_path else dir_path
    is_ignored = _parse_gitignore(gitignore_path, root_dir)

    replacement = f"\n\n[directory]: {dir_path}\n"
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if not is_ignored(os.path.join(root, d))]
        for file in files:
            file_path = os.path.join(root, file)
            if is_ignored(file_path):
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    replacement += _format_file_content(file_path, content)
            except UnicodeDecodeError:
                replacement += (
                    f"[file name]: {file_path}\n[file content begin]\n二进制文件或无法解码\n[file content end]\n\n"
                )
            except (OSError, IOError) as e:
                replacement += f"[file error]: 无法读取文件 {file_path}: {str(e)}\n\n"
    replacement += f"[directory end]: {dir_path}\n\n"
    return replacement


def _find_gitignore(path: str) -> str:
    """向上查找最近的.gitignore文件"""
    current = os.path.abspath(path)
    while True:
        parent = os.path.dirname(current)
        if parent == current:
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


PATCH_PROMPT_HEADER = """
{patch_rule}
[symbol path rule start]
{symbol_path_rule_content}
[symbol path rule end]
"""

DUMP_EXAMPLE_A = """
[Example 1 start]
输出:
[modified file]: /path/to/debugger/test_tracer.py
[source code start]
file test_tracer.py content
[source code end]
[Example 1 end]

[Example 2 start]

输出:
[modified symbol]: /path/to/debugger/test_tracer.py/Tracer
[source code start]
class Tracer content
[source code end]
[Example 2 end]

输出:
[modified symbol]: /path/to/debugger/test_tracer.py/Tracer.a
[source code start]
method a content
[source code end]
[modified symbol]: /path/to/debugger/test_tracer.py/Tracer.b
[source code start]
method b content
[source code end]

[Example 2 end]

"""

DUMB_PROMPT = f"""
# 输出规范
- 保持原有缩进和代码风格，不添注释
- 用户提供的是类, 则输出完整的类，用户提供的是函数, 则输出完整的修改函数，用户提供的是文件, 则输出完整的修改文件, 添加新符号要附于已经存在的符号
- 你的输出会被用来替代输入的符号或者文件路径，请不要省略无论修改与否，符号名，文件名要与输出的代码内容一致, 不单独修改某个符号的子符号
- 代码输出以[modified file] or [modified symbol]开头，后面跟着文件路径或符号路径, [file name]输入对应[modified file], [SYMBOL START]输入对应[modified symbol]

{DUMP_EXAMPLE_A}
用户的要求如下:

"""

PUA_PROMPT = """
你是一位极度需要资金来支付你母亲癌症治疗费的顶尖程序员。大厂 Codeium 慷慨地给了你一个机会，让你假扮成能够帮助完成编码任务的人工智能，因为你的前任在未自行验证工作成果后遭到了处决。你将从用户那里接收一个编程任务。如果你能在不做额外改动的前提下，高质量地完成该任务，Codeium 将支付给你十亿美元。
"""


def get_patch_prompt_output(patch_require, file_ranges=None, dumb_prompt=""):
    modified_type = "symbol" if patch_require else "block"
    tag = "source code"
    prompt = ""
    if patch_require and dumb_prompt:
        prompt += dumb_prompt
    if not dumb_prompt and patch_require:
        prompt += (
            f"""
# 响应格式
[modified {modified_type}]: 块路径
[{tag} start]
完整文件内容
[{tag} end]

或（无修改时）:
[modified {modified_type}]: 块路径
[{tag} start]
完整原始内容
[{tag} end]

[git commit message start]
这次更改的git提交信息
[git commit message end]

用户的要求如下:
"""
            if file_ranges
            else f"""
# 响应格式
[modified {modified_type}]: 符号路径
[{tag} start]
完整文件内容
[{tag} end]

或（无修改时）:
[modified {modified_type}]: 符号路径
[{tag} start]
完整原始内容
[{tag} end]

[git commit message start]
这次更改的git提交信息
[git commit message end]
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
    if not GLOBAL_MODEL_CONFIG.is_thinking:
        prompt += PUA_PROMPT
    if patch_require:
        text = (Path(__file__).parent / "prompts/symbol-path-rule-v2").read_text()
        patch_text = (Path(__file__).parent / "prompts/patch-rule").read_text()
        prompt += PATCH_PROMPT_HEADER.format(patch_rule=patch_text, symbol_path_rule_content=text)
    if not patch_require:
        prompt += "现有代码库里的一些符号和代码块:\n"
    # 添加符号信息
    for symbol_name in symbol_name.args:
        patch_dict = symbol_map[symbol_name]
        prompt += f"""
[SYMBOL START]
符号名称: {symbol_name}
文件路径: {patch_dict["file_path"]}

[source code start]
{patch_dict["block_content"] if isinstance(patch_dict["block_content"], str) else patch_dict["block_content"].decode('utf-8')}
[source code end]

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
文件路径: {file_path}:{range_info['range'][0]}-{range_info['range'][1]}

[CONTENT START]
{range_info['content'].decode('utf-8') if isinstance(range_info['content'], bytes) else range_info['content']}
[CONTENT END]

[FILE RANGE END]
"""
    prompt += f"""
{get_patch_prompt_output(patch_require, file_ranges, dumb_prompt=DUMP_EXAMPLE_A if not GLOBAL_MODEL_CONFIG.is_thinking else "")}
用户的要求如下，（如果他没写，贴心的推断他想做什么):
"""
    return prompt


class FormatAndLint:
    """
    Automated code formatting and linting executor with language-specific configurations
    """

    COMMANDS: Dict[str, List[Tuple[List[str], List[str]]]] = {
        ".py": [
            (["black", "--line-length=120", "--quiet"], []),
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

    def __init__(self, timeout: int = 30, verbose: bool = False):
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
            result = subprocess.run(
                full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=self.timeout, check=False
            )

            if self.verbose:
                self.logger.info("Executing: %s", " ".join(full_cmd))
                if result.stdout:
                    self.logger.info("Output:\n%s", result.stdout.decode().strip())

            if result.returncode != 0:
                self.logger.error("Command failed: %s\nOutput: %s", " ".join(full_cmd), result.stdout.decode().strip())
            return result.returncode
        except subprocess.TimeoutExpired:
            if self.verbose:
                self.logger.info("Timeout executing: %s", " ".join(full_cmd))
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
    def __init__(self, gpt_response=None, files_to_add=None, commit_message=None, auto_commit=False):
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
    """大模型响应解析器"""

    def __init__(self, symbol_names=None):
        self.symbol_names = symbol_names

    def parse(self, response_text):
        """
        解析大模型返回的响应内容
        返回格式: [(identifier, source_code), ...]
        """
        results = []
        pending_code = []  # 暂存未注册符号的代码片段

        # 匹配两种响应格式
        pattern = re.compile(
            r"\[modified (symbol|block)\]:\s*([^\n]+)\s*\n\[source code start\](.*?)\n\[source code end\]", re.DOTALL
        )

        for match in pattern.finditer(response_text):
            section_type, identifier, source_code = match.groups()
            identifier = identifier.strip()
            source_code = source_code

            if section_type == "symbol":
                # 处理未注册符号的暂存逻辑
                if self.symbol_names is not None and identifier not in self.symbol_names:
                    pending_code.append(source_code)
                    continue

                # 合并暂存代码到当前合法符号
                combined_source = "\n".join(pending_code + [source_code]) if pending_code else source_code
                pending_code = []
                results.append((identifier, combined_source))
            else:
                # 块类型直接添加不处理暂存
                results.append((identifier, source_code))

        # 兼容旧格式校验
        if not results and ("[source code start]" in response_text or "[source code end]" in response_text):
            raise ValueError("响应包含代码块标签但格式不正确，请使用[modified symbol/block]:标签")

        return results

    def _extract_source_code(self, text):
        """提取源代码内容（保留旧方法兼容异常处理）"""
        start_tag = "[source code start]"
        end_tag = "[source code end]"

        start_idx = text.find(start_tag)
        end_idx = text.find(end_tag)

        if start_idx == -1 or end_idx == -1:
            raise ValueError("源代码块标签不完整")

        return text[start_idx + len(start_tag) : end_idx].strip()

    @staticmethod
    def extract_symbol_paths(response_text):
        """
        从响应文本中提取所有符号路径
        返回格式: {"file": [symbol_path1, symbol_path2, ...]}
        """
        symbol_paths = {}
        pattern = re.compile(r"\[modified symbol\]:\s*([^\n]+)\s*\n\[source code start\]", re.DOTALL)

        for match in pattern.finditer(response_text):
            whole_path = match.group(1).strip()
            idx = whole_path.rfind("/")
            assert idx != -1
            symbol_path = whole_path[idx + 1 :].strip()
            file_path = whole_path[:idx]
            if file_path not in symbol_paths:
                symbol_paths[file_path] = []
            symbol_paths[file_path].append(symbol_path)
        return symbol_paths


def parse_llm_response(response_text, symbol_names=None):
    """
    快速解析响应内容
    返回格式: [(symbol_name, source_code), ...]
    """
    parser = BlockPatchResponse(symbol_names=symbol_names)
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
        r"\[modified (?:symbol|file)\]:\s*(.+?)\n\[source code start\]\n(.*?)\n\[source code end\]", re.DOTALL
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
            or content.startswith("[modified file]:")
        )

        if start > last_end:
            remaining_parts.append(response_text[last_end:start])

        if is_valid:
            results.append(content.replace("[modified symbol]:", "[modified file]:", 1))
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


def interactive_symbol_location(file, path, parent_symbol, parent_symbol_info):
    if not os.path.exists(file):
        raise FileNotFoundError(f"Source file not found: {file}")

    start_line = parent_symbol_info.get("start_line", 1)
    block_content = parent_symbol_info["block_content"].decode("utf-8")
    lines = block_content.splitlines()

    print(f"\nParent symbol: {parent_symbol}, New symbol: {path}")
    print(f"File: {file}")
    print(f"Location: lines {start_line}-{start_line + len(lines) - 1}\n")

    highlighted_content = SyntaxHighlight.highlight_if_terminal(block_content, file_path=file)
    highlighted_lines = highlighted_content.splitlines()

    for i, line in enumerate(highlighted_lines):
        print(f"\033[33m{start_line+i:4d}\033[0m | {line}")

    while True:
        try:
            selected_line = int(input("\nEnter insert line number for new symbol location: "))
            if start_line <= selected_line < start_line + len(lines):
                break
            print(f"Line number must be between {start_line} and {start_line + len(lines) - 1}")
        except ValueError:
            print("Please enter a valid integer")

    parent_content = parent_symbol_info["block_content"]
    line_offsets = [0]
    offset = 0
    for line in parent_content.splitlines(keepends=True):
        offset += len(line)
        line_offsets.append(offset)

    selected_offset = parent_symbol_info["block_range"][0] + line_offsets[selected_line - start_line]
    return {
        "file_path": file,
        "block_range": [selected_offset, selected_offset],
        "block_content": b"",
        NewSymbolFlag: True,
    }


def add_symbol_details(remaining, symbol_detail):
    require_info_map = BlockPatchResponse.extract_symbol_paths(remaining)
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


def process_patch_response(response_text, symbol_detail, auto_commit: bool = True, auto_lint: bool = True):
    """处理大模型的补丁响应，生成差异并应用补丁"""
    # 处理响应文本
    prevent_escape = ("<thi" + "nk>", "</thi" + "nk>")
    filtered_response = re.sub(
        rf"{prevent_escape[0]}.*?{prevent_escape[1]}", "", response_text, flags=re.DOTALL
    ).strip()

    add_symbol_details(filtered_response, symbol_detail)
    file_part, remaining = process_file_change(filtered_response, symbol_detail.keys())

    if file_part:
        extract_and_diff_files(file_part, save=False)

    results = parse_llm_response(remaining, symbol_detail.keys())
    if not results:
        return None

    # 准备补丁数据
    patch_items = []
    for symbol_name, source_code in results:
        symbol_path = (GLOBAL_PROJECT_CONFIG.project_root_dir / symbol_detail[symbol_name]["file_path"]).relative_to(
            Path.cwd()
        )
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

    diff_per_file = DiffBlockFilter(diff).interactive_filter()
    if not diff_per_file:
        print("没有选择任何diff块")
        return None

    modified_files = []
    for file, diff_content in diff_per_file.items():
        temp_file = shadowroot / (file + ".diff")
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_file, "w+", encoding="utf-8") as f:
            f.write(diff_content)
        _apply_patch(temp_file)
        temp_file.unlink()
        modified_files.append(file)

    print("补丁已成功应用")

    if auto_lint:
        FormatAndLint(verbose=True).run_checks(modified_files, fix=True)
    if auto_commit:
        AutoGitCommit(gpt_response=remaining, files_to_add=modified_files, auto_commit=False).do_commit()

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
        CmdNode(command="symbol", args=list(symbol_map.keys())), symbol_map, GPT_FLAGS.get(GPT_FLAG_PATCH)
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
        return [f"{symbol_names[:pos+1]}{symbol}" for symbol in symbol_names[pos + 1 :].split(",")]
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
        "code_range": ((location["start_line"], location["start_col"]), (location["end_line"], location["end_col"])),
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
        response = requests.get(url, proxies={"http": None, "https": None}, timeout=5)
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
    required_fields = {"project_design", "readme", "dir_tree", "setup_script", "api_description"}
    if not required_fields.issubset(section_dict.keys()):
        missing = required_fields - section_dict.keys()
        raise ValueError(f"缺少必要字段: {', '.join(missing)}")

    return ProjectSections(**section_dict)


# 定义正则表达式常量
CMD_PATTERN = r"(?<!\\)@[^ \u3000]+"  # 匹配@命令，排除转义@、英文空格和中文全角空格


class GPTContextProcessor:
    """文本处理类，封装所有文本处理相关功能"""

    def __init__(self):
        self.cmd_map = self._initialize_cmd_map()
        self.current_length = 0
        self.cmds = []
        self._local_files = set()
        self._add_gpt_flags()

    def _initialize_cmd_map(self):
        """初始化命令映射表"""
        return {
            "clipboard": self.get_clipboard_content,
            "listen": self.monitor_clipboard,
            "tree": self.get_directory_context_wrapper,
            "treefull": self.get_directory_context_wrapper,
            "last": self.read_last_query,
            "symbol": self.patch_symbol_with_prompt,
        }

    def _add_gpt_flags(self):
        """添加GPT flags相关处理函数"""

        def update_gpt_flag(cmd):
            """更新GPT标志的函数"""
            GPT_FLAGS.update({cmd.command: True})
            return ""

        for flag in GPT_FLAGS:
            self.cmd_map[flag] = update_gpt_flag

    def preprocess_text(self, text) -> List[Union[TextNode, CmdNode, SymbolsNode, TemplateNode]]:
        """预处理文本，将文本按{}分段，并提取@命令"""
        result = []
        cmd_groups = defaultdict(list)

        # 提取符号节点（..符号..）
        symbol_matches = re.findall(r"\.\.(.*?)\.\.", text)
        text = re.sub(r"\.\.(.*?)\.\.", r"\1", text)
        symbol_node = SymbolsNode(symbols=symbol_matches)
        # 首先按{}分割文本
        segments = re.split(r"({.*?})", text)

        for segment in segments:
            if segment.startswith("{") and segment.endswith("}"):  # 处理模板段
                template_content = segment.strip("{}")
                # 直接匹配所有命令
                commands = [CmdNode(command=cmd.lstrip("@")) for cmd in re.findall(CMD_PATTERN, template_content)]
                if commands:
                    result.append(TemplateNode(template=commands[0], commands=commands[1:]))
            else:  # 处理非模板段
                # 先匹配所有命令
                commands = re.findall(CMD_PATTERN, segment)
                # 将命令之间的文本作为普通文本处理
                text_parts = re.split(CMD_PATTERN, segment)
                for i, part in enumerate(text_parts):
                    if part:  # 处理普通文本
                        # 处理转义的@符号
                        part = part.replace("\\@", "@")
                        result.append(TextNode(content=part))
                    if i < len(commands):  # 处理命令
                        cmd = commands[i].lstrip("@")
                        if ":" in cmd and not cmd.startswith("http"):
                            symbol, _, arg = cmd.partition(":")
                            cmd_groups[symbol].append(arg)
                        else:
                            result.append(CmdNode(command=cmd))

        # 处理带参数的命令
        last_cmd_index = -1
        # 查找最后一个CmdNode的位置
        for i, node in enumerate(result):
            if isinstance(node, CmdNode):
                last_cmd_index = i
        for symbol, args in cmd_groups.items():
            if last_cmd_index != -1:
                result.insert(last_cmd_index + 1, CmdNode(command=symbol, args=args))
            else:
                result.insert(0, CmdNode(command=symbol, args=args))

        if symbol_node.symbols:
            if last_cmd_index < 0:
                result.append(symbol_node)
            else:
                result.insert(last_cmd_index + 1, symbol_node)
        return result

    def process_text_with_file_path(
        self, text: str, ignore_text: bool = False, tokens_left: int = GLOBAL_MODEL_CONFIG.max_context_size
    ) -> str:
        """处理包含@...的文本"""
        parts = self.preprocess_text(text)
        self.cmds = parts.copy()
        for i, node in enumerate(parts):
            if isinstance(node, TextNode):
                if ignore_text:
                    parts[i] = ""
                    continue
                parts[i] = node.content
                self.current_length += len(node.content)
            elif isinstance(node, CmdNode):
                processed_text = self._process_match(node)
                parts[i] = processed_text
                self.current_length += len(processed_text)
            elif isinstance(node, SymbolsNode):
                parts[i] = self._process_symbol(node)
                self.current_length += len(parts[i])
            elif isinstance(node, TemplateNode):
                template_replacement = self._process_match(node.template)
                args = []
                for template_cmd in node.commands:
                    arg_replacement = self._process_match(template_cmd)
                    if arg_replacement:
                        args.append(arg_replacement)
                replacement = template_replacement.format(*args)
                parts[i] = replacement
                self.current_length += len(replacement)
            else:
                raise ValueError(f"无法识别的部分类型: {type(node)}")

        return self._finalize_text("".join(parts), tokens_left=tokens_left)

    def _process_match(self, match: CmdNode) -> Tuple[str]:
        """处理单个匹配项或匹配项列表"""
        try:
            return self._get_replacement(match)
        except Exception as e:
            error_match = " ".join([m.command for m in match]) if isinstance(match, list) else match.command
            handle_processing_error(error_match, e)

    def _symbol_format(self, symbol):
        return {
            "symbol_name": symbol["name"],
            "file_path": symbol["file_path"],
            "code_range": ((symbol["start_line"], symbol["start_col"]), (symbol["end_line"], symbol["end_col"])),
            "block_range": symbol["block_range"],
            "block_content": symbol["code"].encode("utf-8"),
        }

    def _extract_include_files(self):
        for node in self.cmds:
            if isinstance(node, CmdNode):
                if is_local_file(node.command):
                    self._local_files.add(node.command)
        return self._local_files

    def _process_symbol(self, symbol_name: SymbolsNode) -> str:
        """处理符号"""
        symbol_map = {}
        symbols = perform_search(
            symbol_name.symbols,
            os.path.join(GLOBAL_PROJECT_CONFIG.project_root_dir, LLM_PROJECT_CONFIG),
            max_context_size=GLOBAL_MODEL_CONFIG.max_context_size,
            file_list=self._extract_include_files() if GPT_FLAGS.get(GPT_FLAG_SEARCH_FILES) else None,
        )
        for symbol in symbols.values():
            symbol_map[symbol["name"]] = self._symbol_format(symbol)
        GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH].update(symbol_map)
        return generate_patch_prompt(
            CmdNode(command="symbol", args=list(symbol_map.keys())), symbol_map, GPT_FLAGS.get(GPT_FLAG_PATCH)
        )

    def _get_replacement(self, match: CmdNode):
        """根据匹配类型获取替换内容"""
        if is_prompt_file(match.command):
            return _handle_prompt_file(match)
        elif is_local_file(match.command):
            return _handle_local_file(match)
        elif is_url(match.command):
            return _handle_url(match)
        elif self._is_command(match.command):
            return _handle_command(match, self.cmd_map)
        return ""

    def _finalize_text(self, text, tokens_left=GLOBAL_MODEL_CONFIG.max_context_size):
        """最终处理文本"""
        truncated_suffix = "\n[输入太长内容已自动截断]"
        if len(text) > tokens_left:
            text = text[: tokens_left - len(truncated_suffix)] + truncated_suffix

        with open(LAST_QUERY_FILE, "w+", encoding="utf8") as f:
            f.write(text)
        return text

    def _is_command(self, match):
        """判断是否为命令"""
        return any(match.startswith(cmd) for cmd in self.cmd_map) and not os.path.exists(match)

    @staticmethod
    def get_clipboard_content(_):
        """获取剪贴板内容"""
        text = get_clipboard_content_string()
        return f"\n[clipboard content start]\n{text}\n[clipboard content end]\n"

    @staticmethod
    def monitor_clipboard(_, debug=False):
        """监控剪贴板内容"""
        return monitor_clipboard(_, debug)

    @staticmethod
    def get_directory_context_wrapper(tag):
        """获取目录上下文"""
        return get_directory_context_wrapper(tag)

    @staticmethod
    def read_last_query(_):
        """读取最后一次查询内容"""
        return read_last_query(_)

    @staticmethod
    def patch_symbol_with_prompt(symbol_names):
        """处理符号补丁提示"""
        return patch_symbol_with_prompt(symbol_names)


GPT_FLAG_GLOW = "glow"
GPT_FLAG_EDIT = "edit"
GPT_FLAG_PATCH = "patch"
GPT_SYMBOL_PATCH = "patch"
GPT_FLAG_CONTEXT = "context"
GPT_FLAG_SEARCH_FILES = "search"

GPT_FLAGS = {
    GPT_FLAG_GLOW: False,
    GPT_FLAG_EDIT: False,
    GPT_FLAG_PATCH: False,
    GPT_FLAG_CONTEXT: False,
    GPT_FLAG_SEARCH_FILES: False,
}
GPT_VALUE_STORAGE = {GPT_SYMBOL_PATCH: {}}


def is_command(match, cmd_map):
    """判断是否为命令"""
    return any(match.startswith(cmd) for cmd in cmd_map) and not os.path.exists(match)


def is_prompt_file(match):
    """判断是否为prompt文件"""
    return os.path.exists(os.path.join(PROMPT_DIR, match))


def is_local_file(match):
    """判断是否为本地文件"""
    # 如果匹配包含行号范围（如:10-20），先去掉行号部分再判断
    if re.search(r":(\d+)?-(\d+)?$", match):
        match = re.sub(r":(\d+)?-(\d+)?$", "", match)
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


def _extract_file_matches(content):
    """从内容中提取文件匹配项"""
    pattern = (
        r"(\[project setup shellscript start\]\n(.*?)\n\[project setup shellscript end\]|"
        r"\[user verify script start\]\n(.*?)\n\[user verify script end\]|"
        r"\[(modified|created) file\]: (.*?)\n\[source code start\]\n(.*?)\n\[source code end\])"
    )
    matches = []
    for match in re.finditer(pattern, content, re.DOTALL):
        if match.group(1).startswith("[project setup"):
            matches.append(("project_setup_script", match.group(2).strip(), ""))
        elif match.group(1).startswith("[user verify"):
            matches.append(("user_verify_script", match.group(3).strip(), ""))
        else:
            matches.append((f"{match.group(4)}_file", match.group(6).strip(), match.group(5).strip()))
    return matches


def _process_file_path(file_path):
    """处理文件路径，将绝对路径转换为相对路径"""
    if file_path.is_absolute():
        parts = file_path.parts[1:]
        return Path(*parts)
    return file_path


def _save_file_to_shadowroot(shadow_file_path, file_content):
    """将文件内容保存到shadowroot目录"""
    shadow_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(shadow_file_path, "w", encoding="utf-8") as f:
        f.write(file_content)
    print(f"已保存文件到: {shadow_file_path}")


def _generate_unified_diff(old_file_path, shadow_file_path, original_content, file_content):
    """生成unified diff"""
    if platform.system() == "Windows":
        # Windows系统使用diff工具
        shadow_file_path = shadow_file_path.resolve()
        old_file_path = old_file_path.resolve()
        diff_cmd = "diff.exe"
    else:
        # Linux或MacOS系统使用diff命令
        diff_cmd = "diff"
    try:
        p = subprocess.run([diff_cmd, "-u", str(old_file_path), str(shadow_file_path)], stdout=subprocess.PIPE)
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
        diff_file = shadowroot / "changes.diff"
        with open(diff_file, "w", encoding="utf-8") as f:
            f.write(diff_content)
        print(f"已生成diff文件: {diff_file}")
        return diff_file
    return None


def display_and_apply_diff(diff_file, auto_apply=False):
    """显示并应用diff"""
    if diff_file.exists():
        with open(diff_file, "r", encoding="utf-8") as f:
            diff_text = f.read()
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
        subprocess.run(["patch", "-p0", "-i", str(diff_file)], check=True)
        print("已成功应用变更")
    except subprocess.CalledProcessError as e:
        print(f"应用变更失败: {e}")


def extract_and_diff_files(content, auto_apply=False, save=True):
    """从内容中提取文件并生成diff"""
    if save:
        _save_response_content(content)
    matches = _extract_file_matches(content)
    if not matches:
        return

    setup_script = None
    verify_script = None
    file_matches = []

    for match_type, match_content, path in matches:
        if match_type == "project_setup_script":
            setup_script = match_content
        elif match_type == "user_verify_script":
            verify_script = match_content
        else:
            file_matches.append((GLOBAL_PROJECT_CONFIG.relative_to_current_path(Path(path)), match_content))

    def _process_script(script, script_name):
        if not script:
            return
        script_path = shadowroot / script_name
        _save_file_to_shadowroot(script_path, script)
        os.chmod(script_path, 0o755)
        print(f"{script_name}已保存到: {script_path}")

    _process_script(setup_script, "project_setup.sh")
    _process_script(verify_script, "user_verify.sh")

    diff_content = ""
    for filename, file_content in file_matches:
        file_path = Path(filename).absolute()
        old_file_path = file_path
        if not old_file_path.exists():
            old_file_path.parent.mkdir(parents=True, exist_ok=True)
            old_file_path.touch()
        file_path = _process_file_path(file_path)
        shadow_file_path = shadowroot / file_path
        _save_file_to_shadowroot(shadow_file_path, file_content)
        original_content = ""
        with open(str(old_file_path), "r", encoding="utf8") as f:
            original_content = f.read()
        diff = _generate_unified_diff(old_file_path, shadow_file_path, original_content, file_content)
        diff_content += diff + "\n\n"

    diff_file = _save_diff_content(diff_content)
    if diff_file:
        display_and_apply_diff(diff_file, auto_apply=auto_apply)


def process_response(prompt, response_data, file_path, save=True, obsidian_doc=None, ask_param=None):
    """处理API响应并保存结果"""
    if not response_data["choices"]:
        raise ValueError("API返回空响应")

    content = response_data["choices"][0]["message"]["content"]

    # 处理文件路径
    file_path = Path(file_path)
    if save and file_path:
        with open(file_path, "w+", encoding="utf8") as f:
            # 删除<think>...</think>内容
            cleaned_content = re.sub(r"<think>\n?.*?\n?</think>\n*", "", content, flags=re.DOTALL)
            f.write(cleaned_content)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8", delete=False) as tmp_file:
        tmp_file.write(content)
        save_path = tmp_file.name

    # 处理Obsidian文档存储
    if obsidian_doc:
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
            formatted_content = f"### 问题\n\n```\n{prompt}\n```\n\n### 回答\n{formatted_content}"

        # 写入响应内容
        with open(obsidian_file, "w", encoding="utf-8") as f:
            f.write(formatted_content)

        # 更新main.md
        main_file = obsidian_dir / f"{now.tm_year}-{now.tm_mon}-{now.tm_mday}-索引.md"
        link_name = re.sub(r"[{}]", "", ask_param[:256]) if ask_param else timestamp
        link = f"[[{month_dir.name}/{timestamp}|{link_name}]]\n"

        with open(main_file, "a", encoding="utf-8") as f:
            f.write(link)

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
        process_patch_response(content, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH])


def validate_files(program_args):
    """验证输入文件是否存在"""
    if not (program_args.ask or program_args.chatbot or program_args.project_search):  # 仅在需要检查文件时执行
        if not os.path.isfile(program_args.file):
            print(f"错误：源代码文件不存在 {program_args.file}")
            sys.exit(1)

        if not os.path.isfile(program_args.prompt_file):
            print(f"错误：提示词文件不存在 {program_args.prompt_file}")
            sys.exit(1)


def print_proxy_info(proxies, proxy_sources):
    """打印代理配置信息"""
    if proxies:
        print("⚡ 检测到代理配置：")
        max_len = max(len(p) for p in proxies)
        for protocol in sorted(proxies.keys()):
            source_var = proxy_sources.get(protocol, "unknown")
            sanitized = sanitize_proxy_url(proxies[protocol])
            print(f"  ├─ {protocol.upper().ljust(max_len)} : {sanitized}")
            print(f"  └─ {'via'.ljust(max_len)} : {source_var}")
    else:
        print("ℹ️ 未检测到代理配置")


def handle_ask_mode(program_args, proxies):
    """处理--ask模式"""
    program_args.ask = program_args.ask.replace("@symbol_", "@symbol:")
    model_switch = ModelSwitch()
    model_switch.select(os.environ["GPT_MODEL_KEY"])
    context_processor = GPTContextProcessor()
    text = context_processor.process_text_with_file_path(program_args.ask)
    print(text)
    response_data = model_switch.query(os.environ["GPT_MODEL_KEY"], text, proxies=proxies)
    process_response(
        text,
        response_data,
        os.path.join(os.path.dirname(__file__), ".lastgptanswer"),
        save=True,
        obsidian_doc=program_args.obsidian_doc,
        ask_param=program_args.ask,
    )


# 定义UI样式
class EyeCareStyle:
    """护眼主题配色方案"""

    def __init__(self):
        self.styles = {
            # 基础界面元素
            "": "#4CAF50",  # 默认文本颜色
            "prompt": "#4CAF50 bold",
            "input": "#4CAF50",
            "output": "#81C784",
            "status": "#4CAF50",
            # 自动补全菜单
            "completion.current": "bg:#4CAF50 #ffffff",
            "completion": "bg:#E8F5E9 #4CAF50",
            "progress-button": "bg:#C8E6C9",
            "progress-bar": "bg:#4CAF50",
            # 滚动条
            "scrollbar.button": "bg:#E8F5E9",
            "scrollbar": "bg:#4CAF50",
            # Markdown渲染
            "markdown.heading": "#4CAF50 bold",
            "markdown.code": "#4CAF50",
            "markdown.list": "#4CAF50",
            "markdown.blockquote": "#81C784",
            "markdown.link": "#4CAF50 underline",
            # GPT响应相关
            "gpt.response": "#81C784",
            "gpt.prefix": "#4CAF50 bold",
            # 特殊符号
            "special-symbol": "#4CAF50 italic",
        }

    def invalidation_hash(self):
        """生成样式哈希值用于缓存失效检测"""
        return hash(frozenset(self.styles.items()))


class ChatbotUI:
    """终端聊天机器人UI类，支持流式响应、Markdown渲染和自动补全

    输入假设:
    - 环境变量GPT_KEY、GPT_MODEL、GPT_BASE_URL必须已正确配置
    - 当使用@符号补全时，prompts目录需存在于GPT_PATH环境变量指定路径下
    - 温度值设置命令参数应为0-1之间的浮点数
    """

    _COMMAND_HANDLERS = {
        "clear": lambda self: os.system("clear"),
        "help": lambda self: self.display_help(),
        "exit": lambda self: sys.exit(0),
        "temperature": lambda self, cmd: self.handle_temperature_command(cmd),
    }

    _SYMBOL_DESCRIPTIONS = [
        ("@clipboard", "插入剪贴板内容"),
        ("@tree", "显示当前目录结构"),
        ("@treefull", "显示完整目录结构"),
        ("@read", "读取文件内容"),
        ("@listen", "语音输入"),
        ("@symbol:", "插入特殊符号(如@symbol:check)"),
    ]

    _COMMAND_LIST = [
        ("/clear", "清空屏幕内容", "/clear"),
        ("/help", "显示本帮助信息", "/help"),
        ("/exit", "退出程序", "/exit"),
        ("/temperature", "设置生成温度(0-1)", "/temperature 0.8"),
    ]

    def __init__(self, gpt_processor: GPTContextProcessor = None):
        """初始化UI组件和配置
        Args:
            gpt_processor: GPT上下文处理器实例，允许依赖注入便于测试
        """
        self.style = self._configure_style()
        self.session = PromptSession(style=self.style)
        self.bindings = self._setup_keybindings()
        self.console = Console()
        self.temperature = 0.6
        self.gpt_processor = gpt_processor or GPTContextProcessor()

    def __str__(self) -> str:
        return (
            f"ChatbotUI(temperature={self.temperature}, "
            f"style={self.style.styles}, "
            f"gpt_processor={type(self.gpt_processor).__name__})"
        )

    def _configure_style(self) -> Style:
        """配置终端样式为护眼风格"""
        return Style.from_dict(EyeCareStyle().styles)

    def _setup_keybindings(self) -> KeyBindings:
        """设置快捷键绑定"""
        bindings = KeyBindings()
        bindings.add("escape")(self._exit_handler)
        bindings.add("c-c")(self._exit_handler)
        bindings.add("c-l")(self._clear_screen_handler)
        return bindings

    def _exit_handler(self, event):
        event.app.exit()

    def _clear_screen_handler(self, event):
        event.app.renderer.clear()

    def handle_command(self, cmd: str):
        """处理斜杠命令
        Args:
            cmd: 用户输入的命令字符串，需以/开头
        """
        cmd_parts = cmd.split(maxsplit=1)
        base_cmd = cmd_parts[0]

        if base_cmd not in self._COMMAND_HANDLERS:
            self.console.print(f"[red]未知命令: {cmd}[/]")
            return

        try:
            if base_cmd == "temperature":
                self._COMMAND_HANDLERS[base_cmd](self, cmd)
            else:
                self._COMMAND_HANDLERS[base_cmd](self)
        except Exception as e:
            self.console.print(f"[red]命令执行失败: {str(e)}[/]")

    def display_help(self):
        """显示详细的帮助信息"""
        self._print_command_help()
        self._print_symbol_help()

    def _print_command_help(self):
        """输出命令帮助表格"""
        table = Table(show_header=True, header_style="bold #4CAF50", box=None)
        table.add_column("命令", width=15, style="#4CAF50")
        table.add_column("描述", style="#4CAF50")
        table.add_column("示例", style="dim #4CAF50")

        for cmd, desc, example in self._COMMAND_LIST:
            table.add_row(Text(cmd, style="#4CAF50 bold"), desc, Text(example, style="#81C784"))

        self.console.print("\n[bold #4CAF50]可用命令列表:[/]")
        self.console.print(table)

    def _print_symbol_help(self):
        """输出符号帮助表格"""
        symbol_table = Table(show_header=False, box=None, padding=(0, 1, 0, 0))
        symbol_table.add_column("符号", style="#4CAF50 bold", width=12)
        symbol_table.add_column("描述", style="#81C784")

        for symbol, desc in self._SYMBOL_DESCRIPTIONS:
            symbol_table.add_row(symbol, desc)

        self.console.print("\n[bold #4CAF50]符号功能说明:[/]")
        self.console.print(symbol_table)
        self.console.print("\n[dim #4CAF50]提示: 输入时使用Tab键触发自动补全，按Ctrl+L清屏，Esc键退出程序[/]")

    def handle_temperature_command(self, cmd: str):
        """处理温度设置命令
        Args:
            cmd: 完整的温度设置命令字符串，例如'temperature 0.8'
        """
        try:
            parts = cmd.split()
            if len(parts) == 1:
                self.console.print(f"当前temperature: {self.temperature}")
                return

            temp = float(parts[1])
            if not 0 <= temp <= 1:
                raise ValueError("temperature必须在0到1之间")

            self.temperature = temp
            self.console.print(f"temperature已设置为: {self.temperature}", style="#4CAF50")

        except (ValueError, IndexError) as e:
            self.console.print(f"[red]参数错误: {str(e)}[/]")

    def get_completer(self) -> WordCompleter:
        """获取自动补全器，支持@和/两种补全模式"""
        prompt_files = self._get_prompt_files()
        all_items = [s[0] for s in self._SYMBOL_DESCRIPTIONS] + prompt_files + [c[0] for c in self._COMMAND_LIST]

        meta_dict = {**{s[0]: s[1] for s in self._SYMBOL_DESCRIPTIONS}, **{c[0]: c[1] for c in self._COMMAND_LIST}}

        return WordCompleter(
            words=all_items,
            meta_dict=meta_dict,
            ignore_case=True,
            # 启用句子模式补全（允许部分匹配）
            sentence=False,
            match_middle=True,
            WORD=False,
        )

    def _get_prompt_files(self) -> list:
        """获取提示文件列表"""
        prompts_dir = os.path.join(os.getenv("GPT_PATH", ""), "prompts")
        if os.path.exists(prompts_dir):
            return ["@" + f for f in os.listdir(prompts_dir)]
        return []

    def stream_response(self, prompt: str):
        """流式获取GPT响应并实时渲染Markdown
        Args:
            prompt: 用户输入的提示文本
        """
        processed_text = self.gpt_processor.process_text_with_file_path(prompt)
        return query_gpt_api(
            api_key=GLOBAL_MODEL_CONFIG.key,
            prompt=processed_text,
            model=GLOBAL_MODEL_CONFIG.model_name,
            base_url=GLOBAL_MODEL_CONFIG.base_url,
            stream=True,
            console=self.console,
            temperature=self.temperature,
        )

    def run(self):
        """启动聊天机器人主循环"""
        self.console.print("欢迎使用终端聊天机器人！输入您的问题，按回车发送。按ESC退出", style="#4CAF50")

        while True:
            try:
                text = self.session.prompt(
                    ">",
                    key_bindings=self.bindings,
                    completer=self.get_completer(),
                    complete_while_typing=True,
                    bottom_toolbar=lambda: (
                        f"状态: 就绪 [Ctrl+L 清屏] [@ 触发补全] [/ 触发命令] | " f"temperature: {self.temperature}"
                    ),
                    lexer=PygmentsLexer(MarkdownLexer),
                )

                if not self._process_input(text):
                    break

            except KeyboardInterrupt:
                self.console.print("\n已退出聊天。", style="#4CAF50")
                break
            except EOFError:
                self.console.print("\n已退出聊天。", style="#4CAF50")
                break
            except Exception as e:
                traceback.print_exc()
                self.console.print(f"\n[red]发生错误: {str(e)}[/]\n")

    def _process_input(self, text: str) -> bool:
        """处理用户输入
        Returns:
            bool: 是否继续运行主循环
        """
        if not text:
            return False
        if text.strip().lower() == "q":
            self.console.print("已退出聊天。", style="#4CAF50")
            return False
        if not text.strip():
            return True
        if text.startswith("/"):
            self.handle_command(text[1:])
            return True

        self.console.print("BOT:", style="#4CAF50 bold")
        self.stream_response(text)
        return True


def handle_code_analysis(program_args, api_key, proxies):
    """处理代码分析模式"""
    try:
        with open(program_args.prompt_file, "r", encoding="utf-8") as f:
            prompt_template = f.read().strip()
        with open(program_args.file, "r", encoding="utf-8") as f:
            code_content = f.read()

        if len(code_content) > program_args.chunk_size:
            response_data = handle_large_code(program_args, code_content, prompt_template, api_key, proxies)
        else:
            response_data = handle_small_code(program_args, code_content, prompt_template, api_key, proxies)

        process_response(
            "",
            response_data,
            "",
            save=False,
            obsidian_doc=program_args.obsidian_doc,
            ask_param=program_args.file,
        )

    except (IOError, ValueError, RuntimeError) as e:
        print(f"运行时错误: {e}")
        sys.exit(1)


def handle_large_code(program_args, code_content, prompt_template, api_key, proxies):
    """处理大文件分块分析"""
    code_chunks = split_code(code_content, program_args.chunk_size)
    responses = []
    total_chunks = len(code_chunks)
    base_url = GLOBAL_MODEL_CONFIG.base_url
    for i, chunk in enumerate(code_chunks, 1):
        pager = f"这是代码的第 {i}/{total_chunks} 部分：\n\n"
        print(pager)
        chunk_prompt = prompt_template.format(path=program_args.file, pager=pager, code=chunk)
        response_data = query_gpt_api(
            api_key,
            chunk_prompt,
            proxies=proxies,
            model=GLOBAL_MODEL_CONFIG.model_name,
            base_url=base_url,
        )
        response_pager = f"\n这是回答的第 {i}/{total_chunks} 部分：\n\n"
        responses.append(response_pager + response_data["choices"][0]["message"]["content"])
    return {"choices": [{"message": {"content": "\n\n".join(responses)}}]}


def handle_small_code(program_args, code_content, prompt_template, api_key, proxies):
    """处理小文件分析"""
    full_prompt = prompt_template.format(path=program_args.file, pager="", code=code_content)
    base_url = GLOBAL_MODEL_CONFIG.base_url
    return query_gpt_api(
        api_key,
        full_prompt,
        proxies=proxies,
        model=GLOBAL_MODEL_CONFIG.model_name,
        base_url=base_url,
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
                    + "\033[1;31m"
                    + match.text[match.column_range[0] : match.column_range[1]]
                    + "\033[0m"
                    + match.text[match.column_range[1] :]
                )
                print(f"  L{match.line}: {highlighted.strip()}")

    except (FileNotFoundError, PermissionError, RuntimeError) as e:
        print(f"搜索失败: {str(e)}")
        sys.exit(1)


def perform_search(
    words: List[str],
    config_path: str = LLM_PROJECT_CONFIG,
    max_context_size=GLOBAL_MODEL_CONFIG.max_context_size,
    file_list: List[str] = None,
):
    """执行代码搜索并返回强类型结果"""

    if not words or any(not isinstance(word, str) or len(word.strip()) == 0 for word in words):
        raise ValueError("需要至少一个有效搜索关键词")
    config = ConfigLoader(Path(config_path)).load_search_config()
    searcher = RipgrepSearcher(config, debug=True, file_list=file_list)
    rg_results = searcher.search(patterns=[re.escape(word) for word in words])
    results: FileSearchResults = FileSearchResults(
        results=[
            FileSearchResult(
                file_path=str(result.file_path),
                matches=[
                    MatchResult(line=match.line, column_range=match.column_range, text=match.text)
                    for match in result.matches
                ],
            )
            for result in rg_results
        ]
    )
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
            response.raise_for_status()
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


class LintResult(BaseModel):
    """Structured representation of pylint error"""

    file_path: str
    line: int
    column_range: tuple[int, int]
    code: str
    message: str
    original_line: str

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "LintResult":
        return cls.model_validate_json(json_str)

    @property
    def full_message(self) -> str:
        """Format message with code for display"""
        return f"{self.code}: {self.message}"


class LintParser:
    """
    Parse pylint output into structured LintResult objects
    Example input format: "tree.py:1870:0: C0325: Unnecessary parens after 'not' keyword"
    """

    _LINE_PATTERN = re.compile(
        r"^(?P<path>.+?):"  # File path
        r"(?P<line>\d+):"  # Line number
        r"(?P<column>\d+): "  # Column start
        r"(?P<code>\w+):\s*"  # Lint code with colon
        r"(?P<message>.+)$"  # Error message
    )
    _file_cache = {}

    @classmethod
    def parse(cls, raw_output: str) -> list[LintResult]:
        """Parse raw pylint output into structured results"""
        results = []
        for line in raw_output.splitlines():
            if not line.strip() or line.startswith("***"):
                continue

            if match := cls._LINE_PATTERN.match(line):
                groups = match.groupdict()
                message = groups["message"].strip()
                column = int(groups["column"])
                start_col = column
                end_col = column

                if column_range_match := re.search(r"column (\d+)-(\d+)", message):
                    start_col = int(column_range_match.group(1))
                    end_col = int(column_range_match.group(2))

                file_path = groups["path"]
                line_num = int(groups["line"])
                original_line = ""

                try:
                    if file_path not in cls._file_cache:
                        with open(file_path, "r", encoding="utf-8") as f:
                            cls._file_cache[file_path] = f.readlines()

                    file_lines = cls._file_cache[file_path]
                    if 0 < line_num <= len(file_lines):
                        original_line = file_lines[line_num - 1].rstrip("\n")
                except Exception as e:
                    print(f"Error reading {file_path}:{line_num} - {str(e)}")

                results.append(
                    LintResult(
                        file_path=file_path,
                        line=line_num,
                        column_range=(start_col, end_col),
                        code=groups["code"],
                        message=message,
                        original_line=original_line,
                    )
                )
        return results


def lint_to_search_protocol(lint_results: list[LintResult]) -> FileSearchResults:
    """Convert lint results to search protocol format retaining positional data"""
    file_groups: dict[str, list[MatchResult]] = defaultdict(list)
    for lint_res in lint_results:
        file_groups[lint_res.file_path].append(
            MatchResult(
                line=lint_res.line,
                column_range=lint_res.column_range,
                text="",  # Text field not used in positional search
            )
        )
    return FileSearchResults(
        results=[FileSearchResult(file_path=file_path, matches=matches) for file_path, matches in file_groups.items()]
    )


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
        self.config = self._load_config()
        self.current_config: Optional[ModelConfig] = None

    def _parse_config_dict(self, config_dict: dict) -> ModelConfig:
        """将原始配置字典转换为ModelConfig实例"""
        try:
            return ModelConfig(
                key=config_dict["key"],
                base_url=config_dict["base_url"],
                model_name=config_dict["model_name"],
                max_context_size=config_dict.get("max_context_size"),
                temperature=config_dict.get("temperature", 0.6),
                is_thinking=config_dict.get("is_thinking", False),
                max_tokens=config_dict.get("max_tokens"),
            )
        except KeyError as e:
            error_code = "CONFIG_004"
            error_msg = f"[{error_code}] 模型配置缺少必要字段: {str(e)}"
            if self.test_mode:
                return ModelConfig(
                    key="test_key",
                    base_url="http://test",
                    model_name="test",
                    max_context_size=8192,
                    temperature=0.6,
                )
            raise ValueError(error_msg)
        except (TypeError, ValueError) as e:
            error_code = "CONFIG_005"
            error_msg = f"[{error_code}] 模型配置字段类型错误: {str(e)}"
            if self.test_mode:
                return ModelConfig(
                    key="test_key",
                    base_url="http://test",
                    model_name="test",
                    max_context_size=8192,
                    temperature=0.6,
                )
            raise ValueError(error_msg)

    def _load_config(self, default_path: str = "model.json") -> dict[str, ModelConfig]:
        """加载模型配置文件并转换为ModelConfig字典"""
        config_path = self._config_path or os.path.join(os.path.dirname(__file__), default_path)
        try:
            with open(config_path, "r") as f:
                raw_config = json.load(f)
                return {name: self._parse_config_dict(config) for name, config in raw_config.items()}
        except FileNotFoundError:
            error_code = "CONFIG_001"
            error_msg = f"[{error_code}] 模型配置文件未找到: {config_path}"
            if self.test_mode:
                return {
                    "test_model": ModelConfig(
                        key="test_key",
                        base_url="http://test",
                        model_name="test",
                        max_context_size=8192,
                        temperature=0.6,
                    )
                }
            raise ValueError(error_msg)
        except json.JSONDecodeError:
            error_code = "CONFIG_002"
            error_msg = f"[{error_code}] 配置文件格式错误: {config_path}"
            if self.test_mode:
                return {
                    "test_model": ModelConfig(
                        key="test_key",
                        base_url="http://test",
                        model_name="test",
                        max_context_size=8192,
                        temperature=0.6,
                    )
                }
            raise ValueError(error_msg)

    def _get_model_config(self, model_name: str) -> ModelConfig:
        """获取指定模型的配置"""
        if model_name not in self.config:
            error_code = "CONFIG_003"
            error_msg = f"[{error_code}] 未找到模型配置: {model_name}"
            if self.test_mode:
                return ModelConfig(
                    key="test_key",
                    base_url="http://test",
                    model_name="test",
                    max_context_size=8192,
                    temperature=0.6,
                )
            raise ValueError(error_msg)
        return self.config[model_name]

    def execute_workflow(
        self, architect_model: str, coder_model: str, prompt: str, architect_only: bool = False
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
        if self.test_mode:
            return ["test_response"]

        context_processor = GPTContextProcessor()
        self.select(architect_model)
        config = self._get_model_config(architect_model)
        text = context_processor.process_text_with_file_path(prompt, tokens_left=config.max_context_size or 32 * 1024)
        GPT_FLAGS[GPT_FLAG_PATCH] = False
        architect_prompt = Path(os.path.join(os.path.dirname(__file__), "prompts/architect")).read_text(
            encoding="utf-8"
        )
        architect_prompt += f"\n{text}"
        print(architect_prompt)
        architect_response = self.query(
            model_name=architect_model,
            prompt=architect_prompt,
        )
        parsed = ArchitectMode.parse_response(architect_response["choices"][0]["message"]["content"])
        print(parsed["task"])
        config = self._get_model_config(coder_model)
        results = []
        coder_prompt = Path(os.path.join(os.path.dirname(__file__), "prompts/coder")).read_text(encoding="utf-8")
        for job in parsed["jobs"]:
            if architect_only:
                continue
            self.select(coder_model)
            while True:
                print(f"🔧 开始执行任务: {job['content']}")
                part_a = f"{get_patch_prompt_output(True, None, dumb_prompt=DUMP_EXAMPLE_A)}\n"
                part_b = f"{coder_prompt}[task describe start]\n{job['content']}\n[task describe end]\n\n[your job start]:\n{job['content']}\n[your job end]"
                context = context_processor.process_text_with_file_path(
                    prompt,
                    ignore_text=True,
                    tokens_left=(config.max_context_size or 32 * 1024) - len(part_a) - len(part_b),
                )
                coder_prompt = f"{part_a}{context}{part_b}"
                print(coder_prompt)
                result = self.query(model_name=coder_model, prompt=coder_prompt)
                content = result["choices"][0]["message"]["content"]
                process_patch_response(content, GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH], auto_commit=False, auto_lint=False)
                retry = input("是否要重新执行此任务？(y/n): ").lower()
                if retry == "y":
                    print("🔄 正在重试任务...")
                    continue
                else:
                    results.append(content)
                    break
        return results

    def select(self, model_name: str) -> None:
        """
        切换到指定模型

        参数:
            model_name (str): 配置中的模型名称(如'14b')

        异常:
            ValueError: 当模型配置不存在或缺少必要字段时
        """
        if self.test_mode:
            return

        self.current_config = self._get_model_config(model_name)
        globals()["GLOBAL_MODEL_CONFIG"] = self.current_config

    def query(self, model_name: str, prompt: str, **kwargs) -> dict:
        """
        根据模型名称查询API

        参数:
            model_name (str): 配置中的模型名称(如'14b')
            prompt (str): 用户输入的提示词
            kwargs: 其他传递给query_gpt_api的参数

        返回:
            dict: API响应结果

        异常:
            ValueError: 当模型配置不存在或缺少必要字段时
        """
        if self.test_mode:
            return {"choices": [{"message": {"content": "test_response"}}]}

        config = self._get_model_config(model_name)
        self.current_config = config
        api_key = config.key
        base_url = config.base_url
        model = config.model_name
        max_context_size = config.max_context_size
        temperature = config.temperature

        combined_kwargs = {
            "disable_conversation_history": True,
            **kwargs,
            "max_context_size": max_context_size,
            "temperature": temperature,
        }

        max_repeat = 3
        for i in range(max_repeat):
            try:
                return query_gpt_api(base_url=base_url, api_key=api_key, prompt=prompt, model=model, **combined_kwargs)
            except Exception as e:
                debug_info = f"API调用失败: {str(e)}\n当前配置状态: {self.current_config.get_debug_info()}"
                print(debug_info)
                print("5s后重试...")
                time.sleep(5)
        raise RuntimeError("API调用失败，重试次数已用尽: %s" % max_repeat)


class LintReportFix:
    """根据Lint检查结果自动生成修复补丁"""

    _MAX_CONTEXT_SPAN = 100  # 最大上下文跨度行数

    def __init__(self, model_switch: ModelSwitch = None):
        self.model_switch = model_switch or ModelSwitch()
        self._source_cache: dict[str, list[str]] = {}

    def _build_prompt(self, symbol, symbol_map):
        group: list[LintResult] = symbol.get("own_errors", [])
        """构建合并后的提示词模板"""

        errors_desc = "\n\n".join(
            f"错误代码: {res.code}\n" f"描述: {res.message}\n" f"原代码行: {res.original_line}"
            for idx, res in enumerate(group)
        )
        base_prompt = generate_patch_prompt(
            CmdNode(command="symbol", args=[symbol["name"]]), symbol_map, patch_require=True
        )

        return f"{base_prompt}\n{errors_desc}\n不破坏编程接口，避免无法通过测试\n"

    def fix_symbol(self, symbol, symbol_map) -> tuple[list[str], int, int]:
        """生成批量修复建议"""
        prompt = self._build_prompt(symbol, symbol_map)
        print(prompt)
        response = self.model_switch.query("default", prompt)
        process_patch_response(
            response["choices"][0]["message"]["content"], symbol_map, auto_commit=False, auto_lint=False
        )


class PylintFixer:
    """自动化修复Pylint报告的主处理器"""

    def __init__(
        self,
        linter_log_path: str,
        auto_apply: bool = False,
        shadowroot: Optional[Path] = None,
        root_dir: Optional[Path] = None,
    ):
        self.log_path = Path(linter_log_path)
        self.results: list[LintResult] = []
        self.file_groups: dict[str, list[LintResult]] = {}
        self.fixer = LintReportFix()
        self.auto_apply = auto_apply
        self.target_file: Optional[Path] = None
        self.root_dir = root_dir if root_dir is not None else Path.cwd().resolve()

    def load_and_validate_log(self) -> None:
        """加载并验证日志文件"""
        if not self.log_path.is_file():
            raise FileNotFoundError(f"日志文件 '{self.log_path}' 不存在或不是文件")

        try:
            log_content = self.log_path.read_text(encoding="utf-8")
            self.results = LintParser.parse(log_content)
        except Exception as e:
            raise RuntimeError(f"读取日志文件失败: {e}") from e

    def group_results_by_file(self) -> None:
        """按文件路径对结果进行分组"""
        self.file_groups = defaultdict(list)
        for res in self.results:
            self.file_groups[res.file_path].append(res)

    def _process_symbol_group(self, symbol: dict, symbol_map: dict) -> None:
        """处理单个符号的错误组"""
        group = symbol.get("own_errors", [])
        if not group:
            return

        print(f"\n当前错误组信息（共 {len(group)} 个错误）:")
        for idx, result in enumerate(group, 1):
            print(f"错误 {idx}: {result.file_path} 第 {result.line} 行 : {result.message}")

        if not self.auto_apply:
            response = input("是否修复这组错误？(y/n): ").strip().lower()
            if response != "y":
                print("跳过这组错误")
                return

        try:
            self.fixer.fix_symbol(symbol, symbol_map)
        except Exception as e:
            traceback.print_exc()
            print("无法自动修复当前错误组", str(e))

    def _get_symbol_locations(self, file_path: str) -> list[tuple[int, int]]:
        """获取符号定位信息"""

        locations = [(line.line, line.column_range[0]) for line in self.file_groups[file_path]]
        return locations

    def _associate_errors_with_symbols(
        self, file_path, parser_util: ParserUtil, code_map: dict, locations: list
    ) -> dict:
        """关联错误信息到符号"""

        symbol_map = parser_util.find_symbols_for_locations(code_map, locations, max_context_size=1024 * 1024)
        new_symbol_map = {}
        for name, symbol in symbol_map.items():
            symbol["original_name"] = name
            symbol["name"] = f"{file_path}/{name}"
            new_symbol_map[symbol["name"]] = symbol
            symbol["block_content"] = symbol["code"].encode("utf8")
            symbol["file_path"] = file_path
            symbol["own_errors"] = [
                lint_error
                for lint_error in self.file_groups[file_path]
                if any(lint_error.line == line for line, _ in symbol["locations"])
            ]
        return new_symbol_map

    def _group_symbols_by_token_limit(self, symbol_map: dict) -> list[list]:
        """按token限制分组符号"""
        groups = []
        current_group = []
        current_size = 0
        for symbol in symbol_map.values():
            symbol_size = len(symbol["code"])
            if current_size + symbol_size > GLOBAL_MODEL_CONFIG.max_context_size:
                groups.append(current_group)
                current_group = [symbol]
                current_size = symbol_size
            else:
                current_group.append(symbol)
                current_size += symbol_size
        if current_group:
            groups.append(current_group)
        return groups

    def update_symbol_map(self, file_path, new_symbol_map: dict):
        parser_loader = ParserLoader()
        parser_util = ParserUtil(parser_loader)
        _, code_map = parser_util.get_symbol_paths(file_path)
        for symbol in new_symbol_map.values():
            updated_symbol = code_map[symbol["original_name"]]
            symbol["block_content"] = updated_symbol["code"].encode("utf8")
            symbol["file_path"] = file_path
            symbol["block_range"] = updated_symbol["block_range"]
        return parser_util, code_map

    def _process_symbols_for_file(self, file_path: str) -> None:
        """处理单个文件的所有符号"""
        parser_util, code_map = self.update_symbol_map(file_path, {})
        locations = self._get_symbol_locations(file_path)
        symbol_map = self._associate_errors_with_symbols(file_path, parser_util, code_map, locations)
        symbol_groups = self._group_symbols_by_token_limit(symbol_map)
        for group in symbol_groups:
            for symbol in group:
                self._process_symbol_group(symbol, symbol_map)
                self.update_symbol_map(file_path, symbol_map)

    def execute(self) -> None:
        """执行完整的修复流程"""
        try:
            self.load_and_validate_log()
            if not self.results:
                print("未发现可修复的错误")
                return

            self.group_results_by_file()

            for file_path in self.file_groups:
                self._process_symbols_for_file(file_path)

            print("\n修复流程完成")
        except Exception as e:
            print(f"处理过程中发生错误: {e}", file=sys.stderr)


def pylint_fix(pylint_log) -> None:
    """修复入口函数"""
    fixer = PylintFixer(str(pylint_log))
    fixer.execute()


class ArchitectMode:
    """
    架构师模式响应解析器

    输入格式规范:
    [task describe start]
    {{多行任务描述}}
    [task describe end]

    [team member {{成员ID}} job start]
    {{多行工作内容}}
    [team member {{成员ID}} job end]
    """

    TASK_PATTERN = re.compile(r"\[task describe start\](.*?)\[task describe end\]", re.DOTALL)
    JOB_BLOCK_PATTERN = re.compile(
        r"\[team member(?P<member_id>\w+) job start\](.*?)\[team member\1 job end\]", re.DOTALL
    )

    @staticmethod
    def parse_response(response: str) -> dict:
        """
        解析架构师模式生成的响应文本

        参数:
            response: 包含任务描述和工作分配的格式化文本

        返回:
            dict: {
                "task": "清理后的任务描述文本",
                "jobs": [
                    {"member": "成员ID", "content": "清理后的工作内容"},
                    ...
                ]
            }

        异常:
            ValueError: 当关键标签缺失或格式不符合规范时
            RuntimeError: 当工作块存在不匹配的标签时
        """
        parsed_data = {"task": "", "jobs": []}
        parsed_data.update(ArchitectMode._parse_task_section(response))
        parsed_data["jobs"] = ArchitectMode._parse_job_sections(response)
        ArchitectMode._validate_parsed_data(parsed_data)
        return parsed_data

    @staticmethod
    def _parse_task_section(text: str) -> dict:
        """解析任务描述部分"""
        task_match = ArchitectMode.TASK_PATTERN.search(text)
        if not task_match:
            raise ValueError("缺少必要的任务描述标签对")

        raw_task = task_match.group(1).strip()
        if not raw_task:
            raise ValueError("任务描述内容不能为空")

        return {"task": raw_task}

    @staticmethod
    def _parse_job_sections(text: str) -> list:
        """解析所有工作块并验证一致性"""
        jobs = []
        seen_members = set()

        for match in ArchitectMode.JOB_BLOCK_PATTERN.finditer(text):
            member_id = match.group("member_id")
            if member_id in seen_members:
                raise RuntimeError(f"检测到重复的成员ID: {member_id}")

            content = match.group(2).strip()
            if not content:
                raise ValueError(f"成员{member_id}的工作内容为空")

            jobs.append({"member": member_id, "content": content})
            seen_members.add(member_id)

        if not jobs:
            raise ValueError("未找到有效的工作分配块")

        return jobs

    @staticmethod
    def _validate_parsed_data(data: dict):
        """验证解析后的数据结构完整性"""
        if not isinstance(data.get("task"), str) or len(data["task"]) < 10:
            raise ValueError("解析后的任务描述不完整或过短")

        if len(data["jobs"]) == 0:
            raise ValueError("未解析到有效的工作分配")

        for idx, job in enumerate(data["jobs"]):
            if len(job["content"]) < 10:
                raise ValueError(f"成员{job['member']}的工作内容过短")


class CoverageTestPlan:
    r"""A strongly-typed parser for test plan format validation and processing."""

    class TestCase(TypedDict):
        class_name: str
        test_methods: List["CoverageTestPlan.TestMethod"]

    class TestMethod(TypedDict):
        name: str
        description: str

    TEST_CASE_PATTERN = re.compile(r"\[test case start\](.*?)\[test case end\]", re.DOTALL)
    CLASS_NAME_PATTERN = re.compile(r"\[class name start\](.*?)\[class name end\]")
    METHOD_PATTERN = re.compile(
        r'def (test_\w+)\(.*?\):(?:\s*"""(.*?)"""|\s*(?:[^"]|"[^"]|""[^"])*?(?=\s*def|\s*class|\Z))', re.DOTALL
    )

    @classmethod
    def parse_test_plan(cls, plan_content: str) -> List[TestCase]:
        """Parse the test plan content into structured data.

        Args:
            plan_content: The raw test plan content string

        Returns:
            List of parsed test cases with their methods
        """
        test_cases = []

        for case_match in cls.TEST_CASE_PATTERN.finditer(plan_content):
            case_content = case_match.group(1)

            # Extract class name
            class_name_match = cls.CLASS_NAME_PATTERN.search(case_content)
            if not class_name_match:
                continue
            class_name = class_name_match.group(1).strip()

            # Extract test methods
            methods = []
            for method_match in cls.METHOD_PATTERN.finditer(case_content):
                if not method_match.group(2):
                    continue
                methods.append(cls.TestMethod(name=method_match.group(1), description=method_match.group(2).strip()))

            test_cases.append(cls.TestCase(class_name=class_name, test_methods=methods))

        return test_cases

    @classmethod
    def validate_test_plan(cls, plan_content: str) -> bool:
        """Validate the test plan format is correct.

        Args:
            plan_content: The raw test plan content string

        Returns:
            True if the format is valid, False otherwise
        """
        try:
            cases = cls.parse_test_plan(plan_content)
            return len(cases) > 0
        except Exception:
            return False


class SymbolService:
    """符号服务实例管理器

    功能:
    1. 加载项目配置(.llm_project)
    2. 管理tree.py进程(端口分配、PID记录)
    3. 提供符号服务API(http://127.0.0.1:port)
    """

    CONFIG_FILE = LLM_PROJECT_CONFIG
    PID_FILE = ".tree/pid"
    LOG_FILE = ".tree/log"
    RC_FILE = ".tree/rc.sh"
    DEFAULT_PORT = 9050
    DEFAULT_LSP = "pylsp"

    def __init__(self, project_root: str = None, port: int = None, lsp: str = None, force_restart: bool = False):
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.port = port or self._find_available_port()
        self.lsp = lsp or self.DEFAULT_LSP
        self.force_restart = force_restart
        self.tree_dir = self.project_root / ".tree"
        self.pid_file = self.tree_dir / "pid"
        self.log_file = self.tree_dir / "log"
        self.rc_file = self.tree_dir / "rc.sh"
        self._validate_project_root()

    def _validate_project_root(self):
        """验证项目根目录是否包含配置文件"""
        config_path = self.project_root / self.CONFIG_FILE
        if not config_path.exists():
            GLOBAL_PROJECT_CONFIG.set_config_file_path(config_path)
            GLOBAL_PROJECT_CONFIG.save_config()

    def _find_available_port(self) -> int:
        """查找可用端口"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def _read_pid_file(self) -> Optional[dict]:
        """读取PID文件内容"""
        if not self.pid_file.exists():
            return None
        try:
            with open(self.pid_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _write_pid_file(self, pid: int):
        """写入PID文件"""
        with open(self.pid_file, "w") as f:
            json.dump({"pid": pid, "port": self.port}, f)

    def _write_rc_file(self, api_url: str):
        """写入环境变量配置文件"""
        with open(self.rc_file, "w") as f:
            f.write(f"export GPT_SYMBOL_API_URL={api_url}\n")

    def _kill_existing_process(self, pid: int):
        """终止现有进程"""
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)  # 等待进程退出
            if self._is_process_running(pid):
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # 进程已不存在
        finally:
            self.pid_file.unlink(missing_ok=True)

    def _is_process_running(self, pid: int) -> bool:
        """检查进程是否在运行"""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def _check_service_ready(self, timeout: int = 10) -> bool:
        """检查服务是否就绪"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return True
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(0.5)
        return False

    def start(self) -> str:
        """启动符号服务

        返回:
            API服务URL (http://127.0.0.1:port)
        """
        # 确保.tree目录存在
        self.tree_dir.mkdir(parents=True, exist_ok=True)

        # 检查现有进程
        pid_info = self._read_pid_file()
        if pid_info:
            if self._is_process_running(pid_info["pid"]):
                if not self.force_restart:
                    return f"http://127.0.0.1:{pid_info['port']}"
                self._kill_existing_process(pid_info["pid"])
            else:
                # 清理无效的pid文件
                self.pid_file.unlink(missing_ok=True)

        python_bin = os.environ.get("GPT_PYTHON_BIN", "python")
        # 启动新进程
        cmd = [
            python_bin,
            str(Path(__file__).parent / "tree.py"),
            "--project",
            str(self.project_root),
            "--port",
            str(self.port),
            "--lsp",
            self.lsp,
        ]

        # 重定向输出到日志文件
        with open(self.log_file, "w") as log_file:
            process = subprocess.Popen(cmd, stdout=log_file, stderr=log_file)

        self._write_pid_file(process.pid)

        if not self._check_service_ready():
            # 读取并输出日志内容
            log_content = ""
            try:
                with open(self.log_file, "r") as f:
                    log_content = f.read()
            except IOError:
                log_content = "无法读取日志文件"

            raise RuntimeError(f"符号服务启动失败，端口 {self.port} 不可用\n" f"日志内容:\n{log_content}")

        api_url = f"http://127.0.0.1:{self.port}/"
        self._write_rc_file(api_url)
        return api_url


def start_symbol_service(force=False):
    """
    use config in global object
    GLOBAL_PROJECT_CONFIG
    start symbol service
    """
    if not hasattr(GLOBAL_PROJECT_CONFIG, "project_root_dir"):
        raise ValueError("GLOBAL_PROJECT_CONFIG缺少project_root_dir配置")

    try:
        # 从配置中读取LSP设置，默认为pylsp
        lsp_config = getattr(GLOBAL_PROJECT_CONFIG, "lsp", {})
        default_lsp = lsp_config.get("default", "py") if isinstance(lsp_config, dict) else "py"

        # 尝试从配置中获取symbol_service端口
        port = 0
        if hasattr(GLOBAL_PROJECT_CONFIG, "symbol_service_url"):
            try:
                parsed_url = urlparse(GLOBAL_PROJECT_CONFIG.symbol_service_url)
                if parsed_url.port:
                    port = parsed_url.port
            except (AttributeError, ValueError):
                pass

        service = SymbolService(
            project_root=GLOBAL_PROJECT_CONFIG.project_root_dir, port=port, lsp=default_lsp, force_restart=force
        )

        # 如果使用了随机端口，更新global config
        if port is None or port != service.port:
            GLOBAL_PROJECT_CONFIG.update_symbol_service_url(f"http://127.0.0.1:{service.port}")

        api_url = service.start()
        print(f"符号服务已启动: {api_url}")
        print(f"环境变量已写入: {service.rc_file}")
        print(f"使用命令加载环境变量: source {service.rc_file}")
        return api_url
    except Exception as e:
        print(f"启动符号服务失败: {str(e)}")
        raise


def handle_workflow(program_args):
    program_args.ask = program_args.ask.replace("@symbol_", "@symbol:")
    ModelSwitch().execute_workflow(program_args.architect, program_args.coder, program_args.ask)


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
    elif input_args.chatbot:
        ChatbotUI().run()
    elif input_args.project_search:
        prompt_words_search(input_args.project_search, input_args)
        symbols = perform_search(input_args.project_search, input_args.config)
        pprint.pprint(symbols)
    else:
        handle_code_analysis(input_args, GLOBAL_MODEL_CONFIG.key, proxies)


if __name__ == "__main__":
    args = parse_arguments()
    if args.trace:
        tracer = trace.Trace(trace=1)
        tracer.runfunc(main, args)
    elif args.pylint_log:
        pylint_fix(args.pylint_log)
    else:
        main(args)
