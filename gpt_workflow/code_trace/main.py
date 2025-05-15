import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
from colorama import Fore, Style, init

from llm_query import ModelSwitch

from .config import TraceConfig
from .tracer import CodeTracer, base_prompt


def parse_error_lines(output: str):
    """Parse error lines from compiler output"""
    error_pattern = re.compile(r"([^ \n]+?):(\d+):\d+")
    error_lines = []
    for match in error_pattern.finditer(output):
        file_path = os.path.abspath(match.group(1))
        if os.path.exists(file_path):
            lineno = int(match.group(2))
            try:
                with open(file_path, "r") as f:
                    lines = f.readlines()
                    if 0 < lineno <= len(lines):
                        error_line = lines[lineno - 1].strip()
                        # Skip lines that are too short or just punctuation
                        if len(error_line) > 10 and not re.match(r"^[\W_]+$", error_line):
                            error_lines.append(error_line)
            except Exception:
                continue
    return error_lines


def get_clipboard_content() -> str:
    """Get content from system clipboard"""
    try:
        if sys.platform == "darwin":
            return subprocess.check_output(["pbpaste"]).decode("utf-8")
        elif sys.platform == "win32":
            import win32clipboard

            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData()
            win32clipboard.CloseClipboard()
            return data
        else:
            # Linux/other - try xclip or xsel
            try:
                return subprocess.check_output(["xclip", "-o"]).decode("utf-8")
            except:
                return subprocess.check_output(["xsel", "--clipboard", "--output"]).decode("utf-8")
    except Exception as e:
        print(f"Error getting clipboard content: {str(e)}")
        return ""


def main():
    """
    改后遇到编译不过，把不过的那行，找出是哪个prompt生成, 并删除缓存, 获取到一串crc32
    python gpt_workflow/code_trace.py --lookup "thread_id_array.resize(num_threads);" --delete-matched
    #git restore 编译失败的文件,  重试，跳过crc32代表的那些符号， 不处理它们， 如果不跳过，前边删除了缓存，可以重试，不过还是有可能会失败
    python ~/code/terminal-llm/gpt_workflow/code_trace.py --file target/Process.cpp --skip-crc32 650fe38c,7d2f978c
    """
    init()  # Initialize colorama

    parser = argparse.ArgumentParser(description="Trace code symbols and process them in batch")
    parser.add_argument("--file", "-f", dest="file_path", help="Path to the file to be analyzed")
    parser.add_argument("--config", "-c", dest="config_file", help="Path to the trace configuration file")
    parser.add_argument(
        "--no-cache", dest="no_cache_files", help="Comma-separated list of prompt files to not cache", default=""
    )
    parser.add_argument(
        "--parallel", dest="parallel", action="store_true", help="Process files in parallel", default=False
    )
    parser.add_argument(
        "--skip-crc32", dest="skip_crc32", help="Comma-separated list of CRC32 values to skip", default=""
    )
    parser.add_argument(
        "--lookup-string",
        dest="lookup_strings",
        action="append",
        help="Search prompt cache for specific string and get CRC32 values (can be specified multiple times)",
    )
    parser.add_argument(
        "--lookup-yaml", dest="lookup_yaml", help="YAML file containing list of strings to lookup in prompt cache"
    )
    parser.add_argument(
        "--pasteboard",
        dest="pasteboard",
        action="store_true",
        help="Read error lines from clipboard and lookup in prompt cache",
    )
    parser.add_argument(
        "--delete-matched",
        dest="delete_matched",
        action="store_true",
        help="Delete matched cache files when using --lookup-string or --lookup-yaml",
    )
    parser.add_argument(
        "--prompt-debug",
        dest="prompt_debug",
        help="Path to prompt cache JSON file to resend for debugging",
    )

    args = parser.parse_args()

    # Handle prompt debug first
    if args.prompt_debug:
        try:
            with open(args.prompt_debug, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

                prompt = cache_data.get("prompt", "")
                if not prompt:
                    print("Error: No prompt found in the debug file")
                    sys.exit(1)

                model_switch = ModelSwitch()
                start_tag = "[SYMBOL START]"
                idx = prompt.find(start_tag)
                if idx == -1:
                    print(f"Error: No start tag '{start_tag}' found in the prompt")
                    sys.exit(1)

                prompt = base_prompt + start_tag + prompt[idx:]
                print("Debugging prompt:")
                print(prompt)
                response = model_switch.query_for_text(
                    model_name="deepseek-r1",
                    prompt=prompt,
                    disable_conversation_history=True,
                    verbose=True,
                    no_cache_prompt_file=[],
                    ignore_cache=True,
                )
                print("\nDebug Response:")
                print(response)
                sys.exit(0)
        except Exception as e:
            print(f"Error processing prompt debug file: {str(e)}")
            sys.exit(1)

    # Handle lookup operations first
    if args.lookup_strings or args.lookup_yaml or args.pasteboard:
        search_strings = []
        if args.lookup_strings:
            search_strings.extend([s for s in args.lookup_strings if len(s) > 10 and not re.match(r"^[\W_]+$", s)])
        if args.lookup_yaml:
            try:
                with open(args.lookup_yaml, "r") as f:
                    lookup_data = yaml.safe_load(f)
                    if isinstance(lookup_data, list):
                        search_strings.extend(
                            [s for s in lookup_data if isinstance(s, str) and not re.match(r"^[\W_]+$", s)]
                        )
                    elif isinstance(lookup_data, dict) and "search_strings" in lookup_data:
                        search_strings.extend(
                            [
                                s
                                for s in lookup_data["search_strings"]
                                if isinstance(s, str) and not re.match(r"^[\W_]+$", s)
                            ]
                        )
            except Exception as e:
                print(f"Error loading lookup YAML file: {str(e)}")
                sys.exit(1)
        if args.pasteboard:
            clipboard_content = get_clipboard_content()
            if clipboard_content:
                error_lines = parse_error_lines(clipboard_content)
                search_strings.extend(error_lines)
                print(f"Found {len(error_lines)} error lines in clipboard content")

        # Print search strings with color
        if search_strings:
            print(f"\n{Fore.YELLOW}Search strings:{Style.RESET_ALL}")
            for i, s in enumerate(search_strings, 1):
                print(f"  {Fore.CYAN}{i}.{Style.RESET_ALL} {s}")

        all_results = []
        all_crc = set()
        for search_str in search_strings:
            results, crc_str = CodeTracer.lookup_prompt_cache(search_str, args.delete_matched)
            if results:
                all_results.extend(results)
                all_crc.update(crc_str.split(",") if crc_str else [])

        if all_results:
            print(f"\n{Fore.GREEN}Found matching cache entries:{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}{'CRC32':<10} | {'Filename':<30} | {'Timestamp':<20}{Style.RESET_ALL}")
            print("-" * 70)
            for entry in all_results:
                print(
                    f"{Fore.CYAN}{entry['crc32']:<10}{Style.RESET_ALL} | {entry['filename']:<30} | {entry['timestamp']:<20}"
                )

            crc_list = ",".join(all_crc)
            print(
                f"\n{Fore.GREEN}Combined CRC32 list for skipping:{Style.RESET_ALL} {Fore.CYAN}{crc_list}{Style.RESET_ALL}"
            )
            print(f"{Fore.YELLOW}You can use with --skip-crc32 parameter like:{Style.RESET_ALL}")
            print(f"  {Fore.CYAN}--skip-crc32 {crc_list}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}No cache entries found containing the search strings{Style.RESET_ALL}")
        sys.exit(0)

    if args.config_file:
        config = TraceConfig(args.config_file)
        if args.skip_crc32:
            config.skip_crc32.update(args.skip_crc32.split(","))
        success, failed_file = config.trace_all_files(parallel=args.parallel)
        if success:
            print("All files processed successfully")
        else:
            print(f"Error processing files. Verification failed due to file: {failed_file}")
            if config.failed_files:
                print("Failed files list:", config.failed_files)
            sys.exit(1)
    elif args.file_path:
        skip_crc32 = args.skip_crc32.split(",") if args.skip_crc32 else []
        tracer = CodeTracer(args.file_path, skip_crc32=skip_crc32)
        if args.no_cache_files:
            tracer.no_cache_prompt_file = args.no_cache_files.split(",")
            print("No cache prompt files: ", tracer.no_cache_prompt_file)

        tracer.process()
    else:
        parser.error("Either --file or --config must be specified")


if __name__ == "__main__":
    main()
