#!/usr/bin/env python
import os
import sys
import json
import time
import subprocess
import argparse
from urllib.parse import urlparse
from pathlib import Path
import tempfile
import re
import platform
import difflib
import datetime
import requests
from openai import OpenAI
from pygments import highlight
from pygments.lexers import DiffLexer
from pygments.formatters import TerminalFormatter

MAX_FILE_SIZE = 32000
MAX_PROMPT_SIZE = 163839


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="使用Groq API分析源代码",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="要分析的源代码文件路径")
    group.add_argument("--ask", help="直接提供提示词内容，与--file互斥")
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
        default=os.environ.get(
            "GPT_DOC", os.path.join(os.path.dirname(__file__), "obsidian")
        ),
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
    except Exception:
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
    for protocol, vars in reversed(proxy_vars):
        for var in vars:
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
        with open(INDEX_PATH, "w") as f:
            json.dump({}, f)


def _update_index(uuid, file_path):
    """更新索引文件"""
    _ensure_index()
    with open(INDEX_PATH, "r+") as f:
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

    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=4)

    return index


def get_conversation(uuid):
    """获取对话记录"""
    try:
        # 先尝试读取索引
        with open(INDEX_PATH, "r") as f:
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
    with open(file_path, "w") as f:
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
    except Exception as e:
        print(f"加载对话历史失败: {e}")
        return []


def save_conversation_history(file_path, history):
    """保存对话历史到文件"""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存对话历史失败: {e}")


def query_gpt_api(
    api_key,
    prompt,
    model="gpt-4",
    proxies=None,
    base_url=None,
    conversation_file="conversation_history.json",
):
    """支持多轮对话的OpenAI API流式查询

    参数:
        conversation_file (str): 对话历史存储文件路径
        其他参数同上
    """
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
            temperature=0.6,
            max_tokens=8192,
            top_p=0.8,
            stream=True,
        )

        content = ""
        reasoning = ""
        # 处理流式响应
        for chunk in stream:
            # 处理推理内容（仅打印不保存）
            if (
                hasattr(chunk.choices[0].delta, "reasoning_content")
                and chunk.choices[0].delta.reasoning_content
            ):
                print(chunk.choices[0].delta.reasoning_content, end="", flush=True)
                reasoning += chunk.choices[0].delta.reasoning_content
            # 处理正式回复内容
            if chunk.choices[0].delta.content:
                print(chunk.choices[0].delta.content, end="", flush=True)
                content += chunk.choices[0].delta.content
        print()  # 换行

        # 将助理回复添加到历史（仅保存正式内容）
        history.append({"role": "assistant", "content": content})

        # 保存更新后的对话历史
        save_conversation_history(conversation_file, history)

        # 存储思维过程
        if reasoning:
            content = reasoning + "\n" + content

        return {"choices": [{"message": {"content": content}}]}

    except Exception as e:
        print(f"OpenAI API请求失败: {e}")
        sys.exit(1)

def _check_tool_installed(tool_name, install_url=None, install_commands=None):
    """检查指定工具是否已安装"""
    result = subprocess.run(
        ["which", tool_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode != 0:
        print(f"错误：{tool_name} 未安装")
        if install_url:
            print(f"请访问 {install_url} 安装{tool_name}")
        if install_commands:
            print("请使用以下命令安装：")
            for cmd in install_commands:
                print(f"  {cmd}")
        return False
    return True


def check_deps_installed():
    """检查glow、tree和剪贴板工具是否已安装"""
    all_installed = True

    # 检查glow
    if not _check_tool_installed(
        "glow",
        install_url="https://github.com/charmbracelet/glow",
        install_commands=["brew install glow"],
    ):
        all_installed = False

    # 检查tree
    if not _check_tool_installed(
        "tree",
        install_commands=[
            "macOS: brew install tree",
            "Ubuntu/Debian: sudo apt install tree",
            "CentOS/Fedora: sudo yum install tree",
        ],
    ):
        all_installed = False

    # 检查剪贴板工具
    if sys.platform == "win32":
        try:
            import win32clipboard
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


def get_directory_context(max_depth=1):
    """获取当前目录上下文信息（支持动态层级控制）"""
    try:
        current_dir = os.getcwd()
        cmd = ["tree", '-I ".*"']
        if max_depth is not None:
            cmd.extend(["-L", str(max_depth)])

        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        if result.returncode == 0:
            output = result.stdout
            # 仅在无层级限制时检查输出长度
            if max_depth is None and len(output.encode()) > 2048:
                return get_directory_context(max_depth=1)  # 递归调用回退到一层
            return f"\n当前工作目录: {current_dir}\n\n目录结构:\n{output}"

        # 当tree命令失败时使用ls
        ls_result = subprocess.run(["ls", "-l"], stdout=subprocess.PIPE, text=True)
        msg = ls_result.stdout or "无法获取目录信息"
        return f"\n当前工作目录: {current_dir}\n\n目录结构:\n{msg}"

    except Exception as e:
        return f"获取目录上下文时出错: {str(e)}"


def process_text_with_tree(text):
    """处理包含@tree的文本，获取目录上下文并附加"""
    if "@tree" in text:
        # 移除@tree标记
        text = text.replace("@tree", "")
        # 获取目录上下文
        dir_context = get_directory_context()
        # 将目录上下文附加到文本后
        text = f"{text}\n{dir_context}"
    return text


def get_clipboard_content():
    """获取系统剪贴板内容，支持Linux、Mac、Windows"""
    try:
        # 判断操作系统
        if sys.platform == "win32":
            # Windows系统
            import win32clipboard

            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData()
            win32clipboard.CloseClipboard()
            return data
        elif sys.platform == "darwin":
            # Mac系统
            process = subprocess.Popen(["pbpaste"], stdout=subprocess.PIPE)
            stdout, _ = process.communicate()
            return stdout.decode("utf-8")
        else:
            # Linux系统
            # 尝试xclip
            try:
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard", "-o"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                stdout, _ = process.communicate()
                if process.returncode == 0:
                    return stdout.decode("utf-8")
            except FileNotFoundError:
                pass

            # 尝试xsel
            try:
                process = subprocess.Popen(
                    ["xsel", "--clipboard", "--output"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                stdout, _ = process.communicate()
                if process.returncode == 0:
                    return stdout.decode("utf-8")
            except FileNotFoundError:
                pass

            return "无法获取剪贴板内容：未找到xclip或xsel"
    except Exception as e:
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


USER_PROMPT_CONTEXT = {
    "edit": False,
    "read": False,
}


def process_text_with_file_path(text):
    """处理包含@...的文本，支持@cmd命令、@path文件路径、@http网址和prompts目录下的模板文件"""
    current_length = len(text)  # 初始化当前文本长度

    # 定义命令映射表
    cmd_map = {
        "clipboard": get_clipboard_content,
        "tree": get_directory_context,
        "treefull": lambda: get_directory_context(max_depth=None),
    }

    # 定义环境变量
    env_vars = {
        "os": sys.platform,
        "os_version": platform.version(),
        "current_path": os.getcwd(),
    }

    # 使用正则表达式查找所有@开头的命令或路径
    matches = re.findall(r"@([^\s]+)", text)

    truncated_suffix = "\n[输入太长内容已自动截断]"
    for match in matches:
        # 检查是否已超过最大限制
        if current_length >= MAX_PROMPT_SIZE:
            break  # 提前终止处理流程

        # 构造匹配键（带@符号）
        if text.endswith(match):
            match_key = f"@{match}"
        else:
            match_key = f"@{match} "

        # 计算匹配键的长度用于后续替换
        match_key_length = len(match_key)

        try:
            replacement = ""
            # 处理命令类型匹配
            if match in cmd_map:
                replacement = cmd_map[match]()

            # 处理prompts目录文件
            elif os.path.exists(os.path.join("prompts", match)):
                with open(os.path.join("prompts", match), "r", encoding="utf-8") as f:
                    content = f.read()
                    replacement = f"\n{content.format(**env_vars)}\n"

            # 处理本地文件路径
            elif os.path.exists(os.path.expanduser(match)):
                expanded_path = os.path.abspath(os.path.expanduser(match))
                with open(expanded_path, "r", encoding="utf-8") as f:
                    # 计算可读取的最大长度
                    content = f.read()
                    replacement = f"\n\n[file name]: {expanded_path}\n[file content begin]\n{content}"
                    replacement += "\n[file content end]\n\n"

            # 处理URL请求
            elif match.startswith(("http", "read")):
                url = match[4:] if match.startswith("read") else match
                markdown_content = fetch_url_content(url, is_news=match.startswith("read"))
                replacement = f"\n\n[reference url, content converted to markdown]: {url} \n[markdown content begin]\n{markdown_content}\n[markdown content end]\n\n"

            # 计算替换后的长度变化
            new_segment_length = len(replacement)
            old_segment_length = match_key_length

            # 预检查长度是否超限
            if current_length - old_segment_length + new_segment_length > MAX_PROMPT_SIZE:
                allowable_length = MAX_PROMPT_SIZE - (current_length - old_segment_length)
                replacement = replacement[:allowable_length-len(truncated_suffix)] + truncated_suffix

            # 执行替换并更新当前长度
            text = text.replace(match_key, replacement, 1)  # 只替换第一个匹配项
            current_length = current_length - old_segment_length + len(replacement)

            # 最终长度检查
            if current_length > MAX_PROMPT_SIZE:
                text = text[:MAX_PROMPT_SIZE]
                break

        except Exception as e:
            print(f"处理 {match} 时出错: {str(e)}")
            sys.exit(1)

    # 最终长度校验（防止累积误差）
    if len(text) > MAX_PROMPT_SIZE:
        suffix_len = len(truncated_suffix)
        text = text[:MAX_PROMPT_SIZE-suffix_len] + truncated_suffix

    return text


# 获取.shadowroot的绝对路径，支持~展开
shadowroot = Path(os.path.expanduser("~/.shadowroot"))


def extract_and_diff_files(content):
    """从内容中提取文件并生成diff"""
    # 提取文件内容并保存
    # 创建shadowroot目录
    # 备份response.md内容

    response_path = shadowroot / Path("response.md")
    with open(response_path, "w+", encoding="utf-8") as dst:
        dst.write(content)
    matches = re.findall(r"@([^\n]+)\n(.*)?\n@\1", content, re.S)
    if not matches:
        return

    # print(f"已备份response.md到: {response_path}")
    # 用于存储diff内容
    diff_content = ""

    for filename, file_content in matches:
        # 处理文件路径
        file_path = Path(filename)
        old_file_path = file_path
        # 如果是绝对路径，转换为相对路径
        if file_path.is_absolute():
            parts = file_path.parts[1:]
            file_path = Path(*parts)
        # 组合到shadowroot目录
        shadow_file_path = shadowroot / file_path
        # 创建父目录
        shadow_file_path.parent.mkdir(parents=True, exist_ok=True)
        # 写入文件内容
        with open(shadow_file_path, "w", encoding="utf-8") as f:
            f.write(file_content)
        print(f"已保存文件到: {shadow_file_path}")

        # 生成unified diff
        if old_file_path.exists():
            with open(old_file_path, "r", encoding="utf-8") as orig_file:
                original_content = orig_file.read()
                diff = difflib.unified_diff(
                    original_content.splitlines(),
                    file_content.splitlines(),
                    fromfile=str(old_file_path),
                    tofile=str(shadow_file_path),
                    lineterm="",
                )
                diff_content += "\n".join(diff) + "\n\n"

    # 将diff写入文件
    if diff_content:
        diff_file = shadowroot / "changes.diff"
        with open(diff_file, "w", encoding="utf-8") as f:
            f.write(diff_content)
        print(f"已生成diff文件: {diff_file}")
    # 检查是否存在diff文件
    diff_file = shadowroot / "changes.diff"
    if diff_file.exists():
        # 使用pygments高亮显示diff内容
        with open(diff_file, "r", encoding="utf-8") as f:
            diff_text = f.read()
            highlighted_diff = highlight(diff_text, DiffLexer(), TerminalFormatter())
            print("\n高亮显示的diff内容：")
            print(highlighted_diff)
        # 询问用户是否应用diff
        print(f"\n申请变更文件，是否应用 {diff_file}？")
        apply = input("输入 y 应用，其他键跳过: ").lower()
        if apply == "y":
            # 应用diff
            try:
                subprocess.run(["patch", "-p0", "-i", str(diff_file)], check=True)
                print("已成功应用变更")
            except subprocess.CalledProcessError as e:
                print(f"应用变更失败: {e}")


def process_response(
    response_data, file_path, save=True, obsidian_doc=None, ask_param=None
):
    """处理API响应并保存结果"""
    if not response_data["choices"]:
        raise ValueError("API返回空响应")

    content = response_data["choices"][0]["message"]["content"]

    # 获取文件扩展名
    ext = Path(file_path).suffix[1:] if Path(file_path).suffix else "txt"

    # 处理文件路径
    file_path = Path(file_path)
    if file_path.is_absolute():
        parts = file_path.parts[1:]
        relative_path = Path(*parts)
    else:
        relative_path = file_path

    if save:
        # 创建保存目录
        base_dir = Path(os.getenv("GROQ_DOC", os.getcwd()))
        save_dir = base_dir / "groq_responses" / relative_path.parent
        os.makedirs(save_dir, exist_ok=True)

        base_name = os.path.basename(file_path).split(".")[0]
        save_path = save_dir / f"response-{base_name}-{ext}.md"

        with open(save_path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        # 使用临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False
        ) as tmp_file:
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

        # 写入响应内容
        with open(obsidian_file, "w", encoding="utf-8") as f:
            f.write(content)

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
        sys.exit(1)

    extract_and_diff_files(content)


def main():
    args = parse_arguments()

    # 如果目录不存在则创建
    shadowroot.mkdir(parents=True, exist_ok=True)
    # 集中检查环境变量

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

    if not args.ask:  # 仅在未使用--ask参数时检查文件
        if not os.path.isfile(args.file):
            print(f"错误：源代码文件不存在 {args.file}")
            sys.exit(1)

        if not os.path.isfile(args.prompt_file):
            print(f"错误：提示词文件不存在 {args.prompt_file}")
            sys.exit(1)

    proxies, proxy_sources = detect_proxies()
    if proxies:
        print("⚡ 检测到代理配置：")
        max_len = max(len(p) for p in proxies.keys())
        for protocol in sorted(proxies.keys()):
            source_var = proxy_sources.get(protocol, "unknown")
            sanitized = sanitize_proxy_url(proxies[protocol])
            print(f"  ├─ {protocol.upper().ljust(max_len)} : {sanitized}")
            print(f"  └─ {'via'.ljust(max_len)} : {source_var}")
    else:
        print("ℹ️ 未检测到代理配置")

    if args.ask:
        ask_param = args.ask
    else:
        ask_param = args.file
    if args.ask:
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
            response_data,
            "",
            save=False,
            obsidian_doc=args.obsidian_doc,
            ask_param=ask_param,
        )
        return

    try:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt_template = f.read().strip()
        with open(args.file, "r", encoding="utf-8") as f:
            code_content = f.read()

        # 如果代码超过分块大小，则分割处理
        if len(code_content) > args.chunk_size:
            code_chunks = split_code(code_content, args.chunk_size)
            responses = []
            total_chunks = len(code_chunks)
            for i, chunk in enumerate(code_chunks, 1):
                # 在提示词中添加当前分块信息
                pager = f"这是代码的第 {i}/{total_chunks} 部分：\n\n"
                print(pager)
                chunk_prompt = prompt_template.format(
                    path=args.file, pager=pager, code=chunk
                )
                response_data = query_gpt_api(
                    api_key,
                    chunk_prompt,
                    proxies=proxies,
                    model=os.environ["GPT_MODEL"],
                    base_url=base_url,
                )
                response_pager = f"\n这是回答的第 {i}/{total_chunks} 部分：\n\n"
                responses.append(
                    response_pager + response_data["choices"][0]["message"]["content"]
                )
            final_content = "\n\n".join(responses)
            response_data = {"choices": [{"message": {"content": final_content}}]}
        else:
            full_prompt = prompt_template.format(
                path=args.file, pager="", code=code_content
            )
            response_data = query_gpt_api(
                api_key,
                full_prompt,
                proxies=proxies,
                model=os.environ["GPT_MODEL"],
                base_url=base_url,
            )
        process_response(
            response_data,
            args.file,
            obsidian_doc=args.obsidian_doc,
            ask_param=ask_param,
        )

    except Exception as e:
        print(f"运行时错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
