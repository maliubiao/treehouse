#!/usr/bin/env python
"""
LLM 查询工具模块

该模块提供与OpenAI兼容 API交互的功能，支持代码分析、多轮对话、剪贴板集成等功能。
包含代理配置检测、代码分块处理、对话历史管理等功能。
"""

import argparse
import datetime
import difflib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

import requests
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import Style
from pygments import highlight
from pygments.formatters.terminal import TerminalFormatter
from pygments.lexers.diff import DiffLexer
from pygments.lexers.markup import MarkdownLexer
from pygments.style import Style as PygmentsStyle
from pygments.token import Token

# 初始化Markdown渲染器
from rich.console import Console
from rich.table import Table
from rich.text import Text

MAX_FILE_SIZE = 32000
MAX_PROMPT_SIZE = int(os.environ.get("GPT_MAX_TOKEN", 16384))
LAST_QUERY_FILE = os.path.join(os.path.dirname(__file__), ".lastquery")
PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


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
    api_key,
    prompt,
    model="gpt-4",
    **kwargs,
):
    """支持多轮对话的OpenAI API流式查询

    参数:
        conversation_file (str): 对话历史存储文件路径
        其他参数同上
    """
    # proxies = kwargs.get('proxies')
    base_url = kwargs.get("base_url")
    conversation_file = kwargs.get("conversation_file", "conversation_history.json")
    console = kwargs.get("console")

    cid = os.environ.get("GPT_UUID_CONVERSATION")
    if cid:
        try:
            conversation_file = get_conversation(cid)
            # print("旧对话: %s\n" % conversation_file)
        except FileNotFoundError:
            conversation_file = new_conversation(cid)
            # print("开新对话: %s\n" % conversation_file)

    # 加载历史对话
    history = load_conversation_history(conversation_file)

    # 添加用户新提问到历史
    history.append({"role": "user", "content": prompt})

    # 初始化OpenAI客户端
    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        # 创建流式响应（使用完整对话历史）
        stream = client.chat.completions.create(
            model=model,
            messages=history,
            temperature=kwargs.get("temperature", 0.0),
            max_tokens=MAX_PROMPT_SIZE,
            top_p=0.8,
            stream=True,
        )

        content = ""
        reasoning = ""
        # 处理流式响应
        for chunk in stream:
            # 处理推理内容（仅打印不保存）
            if hasattr(chunk.choices[0].delta, "reasoning_content") and chunk.choices[0].delta.reasoning_content:
                if console:
                    console.print(chunk.choices[0].delta.reasoning_content, end="", style="#00ff00")
                else:
                    print(chunk.choices[0].delta.reasoning_content, end="", flush=True)
                reasoning += chunk.choices[0].delta.reasoning_content

            # 处理正式回复内容
            if chunk.choices[0].delta.content:
                if console:
                    console.print(chunk.choices[0].delta.content, end="")
                else:
                    print(chunk.choices[0].delta.content, end="", flush=True)
                content += chunk.choices[0].delta.content

        if console:
            console.print()  # 换行
        else:
            print()  # 换行

        # 将助理回复添加到历史（仅保存正式内容）
        history.append({"role": "assistant", "content": content})

        # 保存更新后的对话历史
        save_conversation_history(conversation_file, history)

        thinking_end_tag = "</think>\n\n"
        if content and content.find(thinking_end_tag) != -1 and not content.strip().startswith("<think>"):
            pos = content.find(thinking_end_tag)
            reasoning = content[:pos]
            content = content[pos + len(thinking_end_tag) :]

        # 存储思维过程
        if reasoning:
            content = f"<think>\n{reasoning}\n</think>\n\n\n{content}"

        return {"choices": [{"message": {"content": content}}]}

    except Exception as e:
        print(f"OpenAI API请求失败: {e}")
        sys.exit(1)


def _check_tool_installed(tool_name, install_url=None, install_commands=None):
    """检查指定工具是否已安装"""
    try:
        if sys.platform == "win32":
            # Windows系统使用where命令
            subprocess.run(["where", tool_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        else:
            # 非Windows系统使用which命令
            subprocess.run(["which", tool_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except subprocess.CalledProcessError:
        print(f"错误：{tool_name} 未安装")
        if install_url:
            print(f"请访问 {install_url} 安装{tool_name}")
        if install_commands:
            print("请使用以下命令安装：")
            for cmd in install_commands:
                print(f"  {cmd}")
        return False


def check_deps_installed():
    """检查glow、tree和剪贴板工具是否已安装"""
    all_installed = True

    # 检查glow
    if not _check_tool_installed(
        "glow",
        install_url="https://github.com/charmbracelet/glow",
        install_commands=[
            "brew install glow  # macOS",
            "choco install glow  # Windows Chocolatey",
            "scoop install glow  # Windows Scoop",
            "winget install charmbracelet.glow  # Windows Winget",
        ],
    ):
        all_installed = False

    # 检查剪贴板工具
    if sys.platform == "win32":
        try:
            import win32clipboard as _
        except ImportError:
            print("错误：需要安装pywin32来访问Windows剪贴板")
            print("请执行：pip install pywin32")
            all_installed = False
    elif sys.platform != "darwin":  # Linux系统
        clipboard_installed = _check_tool_installed(
            "xclip",
            install_commands=[
                "Ubuntu/Debian: sudo apt install xclip",
                "CentOS/Fedora: sudo yum install xclip",
            ],
        ) or _check_tool_installed(
            "xsel",
            install_commands=[
                "Ubuntu/Debian: sudo apt install xsel",
                "CentOS/Fedora: sudo yum install xsel",
            ],
        )
        if not clipboard_installed:
            all_installed = False

    return all_installed


def get_directory_context_wrapper(tag):
    if tag == "treefull":
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

    except Exception as e:
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
                result = ""
                for content in self.collected_contents:
                    result += f"\n[clipboard content start]\n{content}\n[clipboard content end]\n"
                self._debug_print(f"返回 {len(self.collected_contents)} 段内容")
                return result
            else:
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
        else:
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
    except Exception as e:
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
    except Exception as e:
        return f"获取URL内容失败: {str(e)}"


def _handle_command(match, cmd_map):
    """处理命令类型匹配"""
    # 查找第一个冒号的位置
    colon_index = match.find(":")
    if colon_index != -1:
        # 如果找到冒号，将字符串分成两部分
        key = match[:colon_index]
        value = match[colon_index + 1 :]
        return cmd_map[key](value)
    else:
        # 如果没有冒号，直接处理整个字符串
        return cmd_map[match](match)


def _handle_shell_command(match):
    """处理shell命令"""
    with open(os.path.join("prompts", match), "r", encoding="utf-8") as f:
        content = f.read()
    try:
        process = subprocess.Popen(content, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        output = f"\n\n[shell command]: {content}\n"
        # if stdout:
        output += f"[stdout begin]\n{stdout}\n[stdout end]\n"
        if stderr:
            output += f"[stderr begin]\n{stderr}\n[stderr end]\n"
        return output
    except Exception as e:
        return f"\n\n[shell command error]: {str(e)}\n"


def _handle_prompt_file(match, env_vars):
    """处理prompts目录文件"""
    with open(os.path.join(PROMPT_DIR, match), "r", encoding="utf-8") as f:
        content = f.read()
        return f"\n{content}\n"


def _handle_local_file(match):
    """处理本地文件路径"""
    expanded_path = os.path.abspath(os.path.expanduser(match))
    with open(expanded_path, "r", encoding="utf-8") as f:
        content = f.read()
        replacement = f"\n\n[file name]: {expanded_path}\n[file content begin]\n{content}"
        replacement += "\n[file content end]\n\n"
        return replacement


def _handle_url(match):
    """处理URL请求"""
    url = match[4:] if match.startswith("read") else match
    markdown_content = fetch_url_content(url, is_news=match.startswith("read"))
    return f"\n\n[reference url, content converted to markdown]: {url} \n[markdown content begin]\n{markdown_content}\n[markdown content end]\n\n"


def read_last_query(_):
    """读取最后一次查询的内容"""
    try:
        with open(LAST_QUERY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def query_symbol(symbol_name):
    """查询符号定义信息，优化上下文长度"""
    # 如果符号名包含斜杠，则分离路径和符号名
    print(symbol_name)
    if "/" in symbol_name:
        parts = symbol_name.split("/")
        symbol_name = parts[-1]  # 最后一部分是符号名
        file_path = "/".join(parts[:-1])  # 前面部分作为文件路径
    else:
        file_path = None
    try:
        # 从环境变量获取API地址
        api_url = os.getenv("GPT_SYMBOL_API_URL", "http://127.0.0.1:9050/symbols")
        url = f"{api_url}/{symbol_name}/context?max_depth=2" + (f"&file_path={file_path}" if file_path else "")

        # 发送HTTP请求，禁用所有代理
        proxies = {"http": None, "https": None, "http_proxy": None, "https_proxy": None, "all_proxy": None}
        # 同时清除环境变量中的代理设置
        os.environ.pop("http_proxy", None)
        os.environ.pop("https_proxy", None)
        os.environ.pop("all_proxy", None)

        response = requests.get(url, proxies=proxies, timeout=5)
        response.raise_for_status()
        data = response.json()
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
        remaining_length = MAX_PROMPT_SIZE - len(context) - 1024  # 保留1024字符余量

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
    except Exception as e:
        return f"\n[error] 符号查询时发生错误: {str(e)}\n"


def preprocess_text(text):
    """预处理文本，将文本按{}分段，并提取@命令"""
    # 使用正则表达式按{}分段
    segments = re.split(r"(\{.*?\})", text)
    # 初始化结果列表
    result = []

    for segment in segments:
        if segment.startswith("{") and segment.endswith("}"):
            # 处理模板命令段
            # 提取所有@命令，保留@符号
            matches = re.findall(r"(\\?@[^\s]+)", segment.strip("{}"))
            if matches:
                # 第一个是模板，后面的都是参数
                template = matches[0].lstrip("\\")  # 只去掉转义符，保留@
                params = [match.lstrip("\\") for match in matches[1:]]  # 保留@
                # template的实现 "{} {}".format(*params)
            result.append(("template_cmd", template, *params))
        else:
            # 处理普通文本段，保留@符号和文本的混合
            # 按@符号分割文本，同时保留@符号
            parts = re.split(r"(\\?@[^\s]+)", segment)
            for part in parts:
                if not part:
                    continue
                if re.match(r"\\?@[^\s]+", part):
                    # 处理@命令，保留@符号
                    cmd = part.lstrip("\\")
                    result.append(("cmd", cmd))
                else:
                    # 处理普通文本
                    result.append(("text", part))

    return result


def process_text_with_file_path(text):
    """处理包含@...的文本，支持@cmd命令、@path文件路径、@http网址和prompts目录下的模板文件"""
    parts = preprocess_text(text)
    current_length = 0
    cmd_map = initialize_cmd_map()
    env_vars = initialize_env_vars()
    final_text = ""
    for part in parts:
        if part[0] == "text":
            final_text += part[1]
        elif part[0] == "cmd":
            cmd = part[1]
            text, current_length = process_match(cmd, text, current_length, cmd_map, env_vars)
            final_text += text
        elif part[0] == "template_cmd":
            template_replacement = get_replacement(part[1].strip("@"), cmd_map, env_vars)
            args = []
            for template_part in part[2:]:
                arg_templatement = get_replacement(template_part.strip("@"), cmd_map, env_vars)
                if arg_templatement:
                    args.append(arg_templatement)
            replacement = template_replacement.format(*args)
            final_text += replacement
            current_length += len(replacement)
        else:
            raise ValueError("bad part: %s" % part)
        if current_length >= MAX_PROMPT_SIZE:
            break
    return finalize_text(final_text)


def initialize_cmd_map():
    """初始化命令映射表"""
    return {
        "clipboard": get_clipboard_content,
        "listen": monitor_clipboard,
        "tree": get_directory_context_wrapper,
        "treefull": get_directory_context_wrapper,
        "last": read_last_query,
        "symbol": query_symbol,
    }


def initialize_env_vars():
    """初始化环境变量"""
    return {
        "os": sys.platform,
        "os_version": platform.version(),
        "current_path": os.getcwd(),
    }


def process_match(match, text, current_length, cmd_map, env_vars):
    """处理单个匹配项"""
    match_key = f"{match}" if text.endswith(match) else f"{match} "
    stripped_match = match.strip("@")

    try:
        replacement = get_replacement(stripped_match, cmd_map, env_vars)
        if not replacement:
            return text, current_length

        replacement = adjust_replacement_length(replacement, len(match_key), current_length)
        new_text = text.replace(match_key, replacement, 1)
        new_length = current_length - len(match_key) + len(replacement)

        return (new_text[:MAX_PROMPT_SIZE], MAX_PROMPT_SIZE) if new_length > MAX_PROMPT_SIZE else (new_text, new_length)

    except Exception as e:
        handle_processing_error(stripped_match, e)


def get_replacement(match, cmd_map, env_vars):
    """根据匹配类型获取替换内容"""
    if is_command(match, cmd_map):
        return _handle_command(match, cmd_map)
    elif match.endswith("="):
        return _handle_shell_command(match[:-1])
    elif is_prompt_file(match):
        return _handle_prompt_file(match, env_vars)
    elif is_local_file(match):
        return _handle_local_file(match)
    elif is_url(match):
        return _handle_url(match)
    return None


def adjust_replacement_length(replacement, match_length, current_length):
    """调整替换内容长度"""
    truncated_suffix = "\n[输入太长内容已自动截断]"
    max_allowed = MAX_PROMPT_SIZE - (current_length - match_length)
    if len(replacement) > max_allowed:
        return replacement[: max_allowed - len(truncated_suffix)] + truncated_suffix
    return replacement


def finalize_text(text):
    """最终处理文本"""
    truncated_suffix = "\n[输入太长内容已自动截断]"
    if len(text) > MAX_PROMPT_SIZE:
        text = text[: MAX_PROMPT_SIZE - len(truncated_suffix)] + truncated_suffix

    with open(LAST_QUERY_FILE, "w+", encoding="utf8") as f:
        f.write(text)
    return text


def is_command(match, cmd_map):
    """判断是否为命令"""
    return any(match.startswith(cmd) for cmd in cmd_map) and not os.path.exists(match)


def is_prompt_file(match):
    """判断是否为prompt文件"""
    return os.path.exists(os.path.join(PROMPT_DIR, match))


def is_local_file(match):
    """判断是否为本地文件"""
    return os.path.exists(os.path.expanduser(match))


def is_url(match):
    """判断是否为URL"""
    return match.startswith(("http", "read"))


def handle_processing_error(match, error):
    """统一错误处理"""
    print(f"处理 {match} 时出错: {str(error)}")
    sys.exit(1)


# 获取.shadowroot的绝对路径，支持~展开
shadowroot = Path(os.path.expanduser("~/.shadowroot"))


def _save_response_content(content):
    """保存原始响应内容到response.md"""
    response_path = shadowroot / Path("response.md")
    with open(response_path, "w+", encoding="utf-8") as dst:
        dst.write(content)
    return response_path


def _extract_file_matches(content):
    """从内容中提取文件匹配项"""
    return re.findall(r"\[modified file\]: (.*?)\n\[source code start\] *?\n(.*?)\n\[source code end\]", content, re.S)


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
    return difflib.unified_diff(
        original_content.splitlines(),
        file_content.splitlines(),
        fromfile=str(old_file_path),
        tofile=str(shadow_file_path),
        lineterm="",
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


def _display_and_apply_diff(diff_file):
    """显示并应用diff"""
    if diff_file.exists():
        with open(diff_file, "r", encoding="utf-8") as f:
            diff_text = f.read()
            highlighted_diff = highlight(diff_text, DiffLexer(), TerminalFormatter())
            print("\n高亮显示的diff内容：")
            print(highlighted_diff)

        print(f"\n申请变更文件，是否应用 {diff_file}？")
        apply = input("输入 y 应用，其他键跳过: ").lower()
        if apply == "y":
            try:
                subprocess.run(["patch", "-p0", "-i", str(diff_file)], check=True)
                print("已成功应用变更")
            except subprocess.CalledProcessError as e:
                print(f"应用变更失败: {e}")


def extract_and_diff_files(content):
    """从内容中提取文件并生成diff"""
    _save_response_content(content)
    matches = _extract_file_matches(content)
    if not matches:
        return

    diff_content = ""
    for filename, file_content in matches:
        file_path = Path(filename)
        old_file_path = file_path
        file_path = _process_file_path(file_path)
        shadow_file_path = shadowroot / file_path

        _save_file_to_shadowroot(shadow_file_path, file_content)
        original_content = ""
        if old_file_path.exists():
            with open(old_file_path, "r", encoding="utf8") as f:
                original_content = f.read()
        diff = _generate_unified_diff(old_file_path, shadow_file_path, original_content, file_content)
        diff_content += "\n".join(diff) + "\n\n"

    diff_file = _save_diff_content(diff_content)
    if diff_file:
        _display_and_apply_diff(diff_file)


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
            cleaned_content = re.sub(r"<think>\n?.*?\n?</think>\n\n\n?", "", content, flags=re.DOTALL)
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

    # 调用提取和diff函数
    try:
        subprocess.run(["glow", save_path], check=True)
        # 如果是临时文件，使用后删除
        if not save:
            os.unlink(save_path)
    except subprocess.CalledProcessError as e:
        print(f"glow运行失败: {e}")

    extract_and_diff_files(content)


def validate_environment():
    """验证必要的环境变量"""
    api_key = os.getenv("GPT_KEY")
    if not api_key:
        print("错误：未设置GPT_KEY环境变量")
        sys.exit(1)

    base_url = os.getenv("GPT_BASE_URL")
    if not base_url:
        print("错误：未设置GPT_BASE_URL环境变量")
        sys.exit(1)

    try:
        parsed_url = urlparse(base_url)
        if not all([parsed_url.scheme, parsed_url.netloc]):
            print(f"错误：GPT_BASE_URL不是有效的URL: {base_url}")
            sys.exit(1)
    except Exception as e:
        print(f"错误：解析GPT_BASE_URL失败: {e}")
        sys.exit(1)


def validate_files(args):
    """验证输入文件是否存在"""
    if not args.ask and not args.chatbot:  # 仅在未使用--ask参数时检查文件
        if not os.path.isfile(args.file):
            print(f"错误：源代码文件不存在 {args.file}")
            sys.exit(1)

        if not os.path.isfile(args.prompt_file):
            print(f"错误：提示词文件不存在 {args.prompt_file}")
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


def handle_ask_mode(args, api_key, proxies):
    """处理--ask模式"""
    base_url = os.getenv("GPT_BASE_URL")
    text = process_text_with_file_path(args.ask)
    print(text)
    response_data = query_gpt_api(
        api_key,
        text,
        proxies=proxies,
        model=os.environ["GPT_MODEL"],
        base_url=base_url,
    )
    process_response(
        text,
        response_data,
        os.path.join(os.path.dirname(__file__), ".lastgptanswer"),
        save=True,
        obsidian_doc=args.obsidian_doc,
        ask_param=args.ask,
    )


# 定义UI样式
class HackerStyle(PygmentsStyle):
    styles = {
        Token.Menu.Completions.Completion.Current: "bg:#00ff00 #000000",
        Token.Menu.Completions.Completion: "bg:#008800 #ffffff",
        Token.Scrollbar.Button: "bg:#003300",
        Token.Scrollbar: "bg:#00ff00",
        Token.Markdown.Heading: "#00ff00 bold",
        Token.Markdown.Code: "#00ff00",
        Token.Markdown.List: "#00ff00",
    }


class ChatbotUI:
    """终端聊天机器人UI类，支持流式响应、Markdown渲染和自动补全"""

    def __init__(self):
        """初始化UI组件和配置"""
        self.style = Style.from_dict(
            {
                "prompt": "#00ff00",
                "input": "#00ff00 bold",
                "output": "#00ff00",
                "status": "#00ff00 reverse",
                "markdown.heading": "#00ff00 bold",
                "markdown.code": "#00ff00",
                "markdown.list": "#00ff00",
                "gpt.response": "#00ff88",
                "gpt.prefix": "#00ff00 bold",
            }
        )
        self.session = PromptSession(style=self.style)
        self.bindings = self._setup_keybindings()
        self.console = Console()
        self.temperature = 0.6  # 默认温度值

    def _setup_keybindings(self):
        """设置快捷键绑定"""
        bindings = KeyBindings()

        @bindings.add("escape")
        @bindings.add("c-c")
        def _(event):
            event.app.exit()

        @bindings.add("c-l")
        def _(event):
            event.app.renderer.clear()

        return bindings

    def handle_command(self, cmd):
        """处理斜杠命令"""
        commands = {
            "clear": lambda: os.system("clear"),
            "help": self._display_help,
            "exit": lambda: sys.exit(0),
            "temperature": self._handle_temperature_command,
        }
        if cmd.startswith("temperature"):
            commands["temperature"](cmd)
        elif cmd in commands:
            commands[cmd]()
        else:
            print(f"未知命令: {cmd}")

    def _display_help(self):
        """显示详细的帮助信息"""

        # 创建帮助表格
        table = Table(show_header=True, header_style="bold magenta", box=None)
        table.add_column("命令", width=15)
        table.add_column("描述")
        table.add_column("示例", style="dim")

        # 添加命令信息
        commands = [
            ("/clear", "清空屏幕内容", "/clear"),
            ("/help", "显示本帮助信息", "/help"),
            ("/exit", "退出程序", "/exit"),
            ("/temperature", "设置生成温度(0-1)", "/temperature 0.8"),
        ]

        for cmd, desc, example in commands:
            table.add_row(Text(cmd, style="cyan"), desc, Text(example, style="green"))

        # 添加特殊符号说明
        self.console.print("\n[bold]常用特殊符号:[/]")
        symbol_table = Table(show_header=False, box=None, padding=(0, 1, 0, 0))
        symbol_table.add_column("符号", style="cyan", width=12)
        symbol_table.add_column("描述", style="white")

        symbols = [
            ("@clipboard", "插入剪贴板内容"),
            ("@tree", "显示当前目录结构"),
            ("@treefull", "显示完整目录结构"),
            ("@read", "读取文件内容"),
            ("@listen", "语音输入"),
            ("@symbol:", "插入特殊符号(如@symbol:check)"),
        ]

        for symbol, desc in symbols:
            symbol_table.add_row(symbol, desc)

        # 组合输出内容
        self.console.print("\n[bold]可用命令列表:[/]")
        self.console.print(table)
        self.console.print("\n[bold]符号功能说明:[/]")
        self.console.print(symbol_table)
        self.console.print("\n[dim]提示: 输入时使用Tab键触发自动补全，" "按Ctrl+L清屏，Esc键退出程序[/]")

    def _handle_temperature_command(self, cmd):
        """处理温度设置命令"""
        try:
            parts = cmd.split()
            if len(parts) == 1:
                print(f"当前temperature: {self.temperature}")
                return
            temp = float(parts[1])
            if 0 <= temp <= 1:
                self.temperature = temp
                print(f"temperature已设置为: {self.temperature}")
            else:
                print("temperature必须在0到1之间")
        except ValueError:
            print("temperature必须是一个数字")

    def get_completer(self):
        """获取自动补全器，支持@和/两种补全模式"""
        special_items = ["@clipboard", "@tree", "@treefull", "@read", "@listen", "@symbol:"]
        prompt_files = []
        if os.path.exists(os.path.join(os.getenv("GPT_PATH"), "prompts")):
            prompt_files = ["@" + f for f in os.listdir(os.path.join(os.getenv("GPT_PATH"), "prompts"))]

        commands = ["/clear", "/help", "/exit", "/temperature"]
        all_items = special_items + prompt_files + commands

        pattern = re.compile(r"(@|\/)\w*")
        meta_dict = {
            "@clipboard": "从剪贴板读取内容",
            "@tree": "显示目录树",
            "@treefull": "显示完整目录树",
            "@read": "读取文件内容",
            "@listen": "语音输入",
            "@symbol:": "插入特殊符号",
            "/clear": "清空屏幕",
            "/help": "显示详细帮助信息",
            "/exit": "退出程序",
            "/temperature": "设置生成温度参数 (0-1)",
        }

        return WordCompleter(
            words=all_items,
            pattern=pattern,
            meta_dict=meta_dict,
            ignore_case=True,
        )

    def stream_response(self, prompt):
        """流式获取GPT响应并实时渲染Markdown"""
        text = process_text_with_file_path(prompt)
        return query_gpt_api(
            api_key=os.getenv("GPT_KEY"),
            prompt=text,
            model=os.environ["GPT_MODEL"],
            base_url=os.getenv("GPT_BASE_URL"),
            stream=True,
            console=self.console,
            temperature=self.temperature,
        )

    def run(self):
        """启动聊天机器人主循环"""
        print("欢迎使用终端聊天机器人！输入您的问题，按回车发送。按ESC退出")

        while True:
            try:
                text = self.session.prompt(
                    "> ",
                    key_bindings=self.bindings,
                    completer=self.get_completer(),
                    complete_while_typing=True,
                    bottom_toolbar=lambda: f"状态: 就绪 [Ctrl+L 清屏] [@ 触发补全] [/ 触发命令] | temperature: {self.temperature}",
                    lexer=PygmentsLexer(MarkdownLexer),
                )

                if text and text.lower() == "q":
                    print("已退出聊天。")
                    break

                if text and not text.strip():
                    continue

                if not text:
                    break

                if text.startswith("/"):
                    self.handle_command(text[1:])
                    continue

                self.console.print("BOT:")
                self.stream_response(text)
            except KeyboardInterrupt:
                print("\n已退出聊天。")
                break
            except Exception as e:
                print(f"\n发生错误: {str(e)}\n")


def handle_code_analysis(args, api_key, proxies):
    """处理代码分析模式"""
    try:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt_template = f.read().strip()
        with open(args.file, "r", encoding="utf-8") as f:
            code_content = f.read()

        if len(code_content) > args.chunk_size:
            response_data = handle_large_code(args, code_content, prompt_template, api_key, proxies)
        else:
            response_data = handle_small_code(args, code_content, prompt_template, api_key, proxies)

        process_response(
            "",
            response_data,
            "",
            save=False,
            obsidian_doc=args.obsidian_doc,
            ask_param=args.file,
        )

    except Exception as e:
        print(f"运行时错误: {e}")
        sys.exit(1)


def handle_large_code(args, code_content, prompt_template, api_key, proxies):
    """处理大文件分块分析"""
    code_chunks = split_code(code_content, args.chunk_size)
    responses = []
    total_chunks = len(code_chunks)
    base_url = os.getenv("GPT_BASE_URL")
    for i, chunk in enumerate(code_chunks, 1):
        pager = f"这是代码的第 {i}/{total_chunks} 部分：\n\n"
        print(pager)
        chunk_prompt = prompt_template.format(path=args.file, pager=pager, code=chunk)
        response_data = query_gpt_api(
            api_key,
            chunk_prompt,
            proxies=proxies,
            model=os.environ["GPT_MODEL"],
            base_url=base_url,
        )
        response_pager = f"\n这是回答的第 {i}/{total_chunks} 部分：\n\n"
        responses.append(response_pager + response_data["choices"][0]["message"]["content"])
    return {"choices": [{"message": {"content": "\n\n".join(responses)}}]}


def handle_small_code(args, code_content, prompt_template, api_key, proxies):
    """处理小文件分析"""
    full_prompt = prompt_template.format(path=args.file, pager="", code=code_content)
    base_url = os.getenv("GPT_BASE_URL")
    return query_gpt_api(
        api_key,
        full_prompt,
        proxies=proxies,
        model=os.environ["GPT_MODEL"],
        base_url=base_url,
    )


def main():
    args = parse_arguments()
    shadowroot.mkdir(parents=True, exist_ok=True)

    validate_environment()
    validate_files(args)
    proxies, proxy_sources = detect_proxies()
    print_proxy_info(proxies, proxy_sources)

    if args.ask:
        handle_ask_mode(args, os.getenv("GPT_KEY"), proxies)
    elif args.chatbot:
        ChatbotUI().run()
    else:
        handle_code_analysis(args, os.getenv("GPT_KEY"), proxies)


if __name__ == "__main__":
    main()
