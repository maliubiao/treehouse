#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
from pathlib import Path

import requests


def format_conversation_menu():
    title = sys.stdin.readline().strip()
    color_reset = "\033[0m"
    color_number = "\033[1m"
    color_date = "\033[33m"
    color_uuid = "\033[36m"

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
            f"{color_number}{idx:>2}){color_reset} "
            f"{color_date}{date_time:<19}{color_reset} "
            f"{color_uuid}{uuid:<36}{color_reset} {preview}"
        )


def handle_complete(prefix: str):
    """处理符号补全请求..."""
    if not prefix.startswith("symbol_"):
        return

    gpt_api_server = os.getenv("GPT_API_SERVER")
    if not gpt_api_server:
        logging.warning("GPT_API_SERVER environment variable not set")
        return

    local_path = prefix[len("symbol_") :].replace("//", "/")
    path_obj = Path(local_path)

    if local_path.endswith("/"):
        _handle_directory_completion(local_path, gpt_api_server)
    else:
        _process_file_completion(path_obj, gpt_api_server, prefix)


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
            _request_api_completion(api_server, f"symbol:{dir_path}/")
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
            print(f"symbol_{clean_path}/{item.name}{suffix}")
    except OSError as e:
        logging.error("Local completion failed: %s", str(e))


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

        api_prefix = prefix.replace("symbol_", "symbol:")
        resp = requests.get(
            f"{api_server}complete_realtime",
            params={"prefix": api_prefix},
            timeout=1,
            proxies={"http": None, "https": None},
        )
        if resp.ok:
            for item in resp.text.splitlines():
                print(item.replace("symbol:", "symbol_"))
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
        print(" ".join(str(config.get(k, "")) for k in ("key", "base_url", "model_name", "max_tokens", "temperature")))


def main():
    parser = argparse.ArgumentParser(description="Terminal LLM helper script")
    subparsers = parser.add_subparsers(dest="command")

    commands = {
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
