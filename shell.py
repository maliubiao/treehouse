#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import urllib.parse
from pathlib import Path

import requests
from colorama import Fore, Style


def format_conversation_menu():
    title = sys.stdin.readline().strip()

    print(f"{title}：")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 4:
            continue

        idx, date_time, uuid, preview = parts[0], parts[1], parts[2], parts[3]
        preview = preview.replace("\n", " ").strip()[:32].rstrip() + "..." if len(preview) > 32 else preview

        print(
            f"{Fore.WHITE}{Style.BRIGHT}{idx:>2}){Style.RESET_ALL} "
            f"{Fore.YELLOW}{date_time:<19}{Style.RESET_ALL} "
            f"{Fore.CYAN}{uuid:<36}{Style.RESET_ALL} {preview}"
        )


def handle_complete(prefix: str):
    """处理符号补全请求..."""
    if not prefix.startswith("symbol_"):
        return

    gpt_api_server = os.getenv("GPT_SYMBOL_API_URL")
    if not gpt_api_server:
        logging.warning("GPT_SYMBOL_API_URL environment variable not set")
        return

    local_path = prefix[len("symbol_") :].replace("//", "/")
    path_obj = Path(local_path)

    if local_path.endswith("/"):
        _handle_directory_completion(local_path, gpt_api_server)
    else:
        _process_file_completion(path_obj, gpt_api_server, prefix)


def handle_cmd_complete(prefix: str):
    """
    传入以@号开头, [clipboard tree treefull read listen glow last edit patch context]
    这是特殊实例
    可补全GPT_PATH/prompts目录下的文件
    可任意子目录，子文件
    当以symbol_开头时，用handle_complete补全
    对补全的结果数组做排序
    """
    prefix = prefix.strip("@")
    special_commands = [
        "clipboard",
        "tree",
        "treefull",
        "read",
        "listen",
        "glow",
        "last",
        "edit",
        "patch",
        "context",
        "symbol_",
    ]

    completions = []
    prompts_dir = os.path.join(os.getenv("GPT_PATH", ""), "prompts")

    # 处理特殊命令补全
    completions.extend(cmd for cmd in special_commands if cmd.startswith(prefix))

    # 处理prompts目录补全
    if os.path.isdir(prompts_dir):
        try:
            items = os.listdir(prompts_dir)
            for item in items:
                full_path = item.replace(":", "_")
                if full_path.startswith(prefix):
                    if os.path.isdir(os.path.join(prompts_dir, item)):
                        completions.append(f"{full_path}/")
                    else:
                        completions.append(full_path)
        except OSError as e:
            logging.error("Failed to list prompts directory: %s", e)
    # 处理symbol_前缀补全
    if prefix.startswith("symbol_"):
        handle_complete(prefix)
        return
    # 去重排序并添加@前缀
    seen = set()
    for item in sorted(completions):
        if item not in seen:
            seen.add(item)
            print(f"{item}")


def _process_file_completion(path_obj: Path, api_server: str, prefix: str):
    """统一处理文件补全逻辑"""
    if path_obj.exists():
        if path_obj.is_dir():
            _complete_local_directory(str(path_obj))
        else:
            _request_api_completion(api_server, prefix)
    else:
        parent_dir = path_obj.parent
        if parent_dir.exists() and parent_dir.is_dir():
            _complete_partial_path(parent_dir, path_obj.name)
        else:
            _request_api_completion(api_server, prefix)


def _complete_partial_path(parent_dir: Path, base_name: str):
    """补全部分存在的路径"""
    try:
        for item in parent_dir.iterdir():
            if item.name.startswith(base_name):
                if parent_dir == Path("."):
                    print(f"symbol_{item.name}")
                else:
                    relative_path = parent_dir.joinpath(item.name).as_posix()
                    suffix = "/" if item.is_dir() else ""
                    print(f"symbol_{relative_path}{suffix}")
    except OSError as e:
        logging.error("Partial path completion failed: %s", str(e))


def _handle_directory_completion(local_path: str, api_server: str):
    """处理目录补全请求"""
    dir_path = local_path.rstrip("/")
    path_obj = Path(dir_path)

    if path_obj.exists():
        if path_obj.is_file():
            _request_api_completion(api_server, f"symbol_{dir_path}/")
        else:
            _complete_local_directory(local_path)
    else:
        logging.warning("Invalid directory path: %s", dir_path)


def _complete_local_directory(local_path: str):
    """执行本地目录补全"""
    try:
        clean_path = local_path.rstrip("/")
        dir_path = Path(clean_path)
        if not dir_path.is_dir():
            logging.warning("Directory path does not exist or is not a directory: %s", clean_path)
            return

        for item in dir_path.iterdir():
            suffix = "/" if item.is_dir() else ""
            if clean_path == ".":
                print(f"symbol_{item.name}{suffix}")
            else:
                print(f"symbol_{clean_path}/{item.name}{suffix}")
    except OSError as e:
        logging.error("Local completion failed: %s", str(e))


def split_symbol_and_path(prefix):
    if prefix.startswith("symbol_"):
        prefix = prefix[len("symbol_") :]

    last_slash = prefix.rfind("/")
    if last_slash == -1:
        return prefix, ""

    path = prefix[:last_slash]
    symbol = prefix[last_slash + 1 :]
    return path, symbol


def make_path_relative_to_root_dir(prefix):
    """将路径转换为相对于根目录的路径"""
    path, symbol = split_symbol_and_path(prefix)
    if path:
        path = relative_to_root_dir(path)
        return f"symbol_{path}/{symbol}"
    else:
        return prefix


def relative_to_root_dir(path):
    """返回相对于根目录的路径"""
    current = Path(path)
    if not current.is_absolute():
        current = Path.cwd() / path

    root_dir = find_root_dir()
    if root_dir and root_dir in current.parents:
        return current.relative_to(root_dir)
    return current


LLM_PROJECT_CONFIG = ".llm_project.yml"


def find_root_dir(root_dir_contains=LLM_PROJECT_CONFIG):
    current_path = Path.cwd()
    while current_path != current_path.parent:
        if (current_path / root_dir_contains).exists():
            return current_path
        current_path = current_path.parent
    return None


def _request_api_completion(api_server: str, prefix: str):
    """请求远程API补全"""
    original_env = {
        "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
        "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
        "ALL_PROXY": os.environ.get("ALL_PROXY"),
        "http_proxy": os.environ.get("http_proxy"),
        "https_proxy": os.environ.get("https_proxy"),
        "all_proxy": os.environ.get("all_proxy"),
    }
    try:
        # 彻底清除代理环境变量
        for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
            os.environ.pop(proxy_var, None)

        new_prefix = make_path_relative_to_root_dir(prefix)
        api_prefix = new_prefix.replace("symbol_", "symbol:", 1)  # 仅替换第一个symbol_
        encoded_prefix = urllib.parse.quote(api_prefix, safe="")  # 严格编码所有特殊字符
        resp = requests.get(
            f"{api_server}complete_realtime",
            params={"prefix": encoded_prefix},
            timeout=1,
            proxies={"http": None, "https": None},
        )
        if resp.ok:
            path, _ = split_symbol_and_path(prefix)
            for item in resp.text.splitlines():
                item = item.replace("symbol:", "symbol_")
                _, symbol = split_symbol_and_path(item)
                print(f"symbol_{path}/{symbol}")
    except requests.RequestException as e:
        logging.error("API request failed: %s", str(e))
    finally:
        # 恢复原始环境变量
        for var, value in original_env.items():
            if value is not None:
                os.environ[var] = value
            else:
                os.environ.pop(var, None)


def scan_conversation_files(conversation_dir: str, limit: int):
    files = []
    for root, _, filenames in os.walk(conversation_dir):
        for fname in filenames:
            if fname in ["index.json", ".DS_Store"] or not fname.endswith(".json"):
                continue

            path = os.path.join(root, fname)
            try:
                date_str = Path(root).name
                time_uuid = Path(fname).stem
                uuid = "-".join(time_uuid.split("-")[3:])
                time_str = ":".join(time_uuid.split("-")[:3])
                preview = get_preview(path)
                files.append((Path(path).stat().st_mtime, date_str + time_str, uuid, preview))
            except (OSError, json.JSONDecodeError):
                continue

    files.sort(reverse=True, key=lambda x: x[0])
    return files[:limit] if limit > 0 else files


def get_preview(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list) and data:
                return data[0].get("content", "")[:32].replace("\n", " ").strip()
    except (IOError, json.JSONDecodeError):
        pass
    return "N/A"


def list_models(config_file: str):
    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)
        for name, settings in config.items():
            if settings.get("key"):
                print(f"{name}: {settings['model_name']}")


def list_model_names(config_file: str):
    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)
        for name, settings in config.items():
            if settings.get("key"):
                print(name)


def read_model_config(model_name: str, config_file: str):
    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f).get(model_name, {})
        if not config.get("key"):
            print("")
            return

        output = []
        for k in (
            "key",
            "base_url",
            "model_name",
            "max_context_size",
            "max_tokens",
            "temperature",
            "is_thinking",
        ):
            if k in config:
                output.append(str(config[k]))
            else:
                default = (
                    64 * 1024
                    if k == "max_context_size"
                    else 8 * 1024 if k == "max_tokens" else 0.0 if k == "temperature" else ""
                )
                output.append(str(default))
        print(" ".join(output))


def main():
    parser = argparse.ArgumentParser(description="Terminal LLM helper script")
    subparsers = parser.add_subparsers(dest="command")

    commands = {
        "shell-complete": ("prefix",),
        "complete": ("prefix",),
        "conversations": ("--limit",),
        "list-models": ("config_file",),
        "list-model-names": ("config_file",),
        "read-model-config": ("model_name", "config_file"),
        "format-conversation-menu": (),
    }

    for cmd, args in commands.items():
        sp = subparsers.add_parser(cmd)
        for arg in args:
            if arg.startswith("--"):
                sp.add_argument(arg, type=int, default=0)
            else:
                sp.add_argument(arg)

    args = parser.parse_args()

    command_handlers = {
        "complete": lambda: handle_complete(args.prefix),
        "shell-complete": lambda: handle_cmd_complete(args.prefix),
        "conversations": lambda: _handle_conversations(args.limit),
        "list-models": lambda: list_models(args.config_file),
        "list-model-names": lambda: list_model_names(args.config_file),
        "read-model-config": lambda: read_model_config(args.model_name, args.config_file),
        "format-conversation-menu": format_conversation_menu,
    }

    if handler := command_handlers.get(args.command):
        handler()


def _handle_conversations(limit: int):
    base_dir = os.path.join(os.getenv("GPT_PATH"), "conversation")
    files = scan_conversation_files(base_dir, limit)
    for idx, (_, date_str, uuid, preview) in enumerate(files, 1):
        print("\t".join([str(idx), f"{date_str}", uuid, preview]))


if __name__ == "__main__":
    main()
