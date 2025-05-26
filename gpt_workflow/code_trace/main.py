import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml
from colorama import Fore, Style, init

from llm_query import ModelSwitch

from .config import TraceConfig
from .tracer import CodeTracer, base_prompt
from .transform_applier import TransformApplier


def parse_error_lines(output: str) -> List[str]:
    """Parse error lines from compiler output."""
    error_pattern = re.compile(r"([^ \n]+?):(\d+):\d+")
    error_lines = []
    for match in error_pattern.finditer(output):
        file_path = os.path.abspath(match.group(1))
        if os.path.exists(file_path):
            lineno = int(match.group(2))
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    if 0 < lineno <= len(lines):
                        error_line = lines[lineno - 1].strip()
                        if len(error_line) > 10 and not re.match(r"^[\W_]+$", error_line):
                            error_lines.append(error_line)
            except (IOError, UnicodeDecodeError) as e:
                print(f"Error reading file {file_path}: {str(e)}")
    return error_lines


def get_clipboard_content() -> str:
    """Get content from system clipboard."""
    try:
        if sys.platform == "darwin":
            return subprocess.check_output(["pbpaste"]).decode("utf-8")
        if sys.platform == "win32":
            try:
                import win32clipboard  # pylint: disable=import-outside-toplevel

                win32clipboard.OpenClipboard()
                data = win32clipboard.GetClipboardData()
                win32clipboard.CloseClipboard()
                return data
            except ImportError:
                return ""
        # Linux/other - try xclip or xsel
        try:
            return subprocess.check_output(["xclip", "-o"]).decode("utf-8")
        except (subprocess.CalledProcessError, FileNotFoundError):
            return subprocess.check_output(["xsel", "--clipboard", "--output"]).decode("utf-8")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error getting clipboard content: {str(e)}")
        return ""


def print_transformation_report(transform_data: Dict, file_filter: Optional[str] = None) -> None:
    """Pretty print transformation report."""
    init()  # Initialize colorama

    print(f"\n{Fore.YELLOW}=== Code Transformation Report ==={Style.RESET_ALL}")

    total_symbols = len(transform_data)
    changed_symbols = sum(1 for t in transform_data.values() if t["is_changed"])
    unchanged_symbols = total_symbols - changed_symbols

    print(f"{Fore.CYAN}Summary:{Style.RESET_ALL}")
    print(f"  Total symbols processed: {total_symbols}")
    print(f"  Changed symbols: {Fore.GREEN}{changed_symbols}{Style.RESET_ALL}")
    print(f"  Unchanged symbols: {unchanged_symbols}")
    print(f"  Transformation rate: {changed_symbols / total_symbols:.1%}\n")

    for symbol_path, data in transform_data.items():
        if file_filter and file_filter not in symbol_path:
            continue

        file_path = data["file_path"]
        is_changed = data["is_changed"]

        print(f"\n{Fore.YELLOW}Symbol: {symbol_path}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}File: {file_path}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Status: {'MODIFIED' if is_changed else 'UNCHANGED'}{Style.RESET_ALL}")

        print(f"\n{Fore.GREEN}Original Code:{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{data['original_code']}{Style.RESET_ALL}")

        if is_changed:
            print(f"\n{Fore.GREEN}Transformed Code:{Style.RESET_ALL}")
            print(f"{Fore.WHITE}{data['transformed_code']}{Style.RESET_ALL}")
        print("-" * 80)


def handle_prompt_debug(args: argparse.Namespace) -> None:
    """Handle prompt debug functionality."""
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
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error processing prompt debug file: {str(e)}")
        sys.exit(1)


def handle_inspect_transform(args: argparse.Namespace) -> None:
    """Handle transformation inspection."""
    if args.transform_file:
        transform_file = Path(args.transform_file)
    elif args.inspect_file:
        file_name = Path(args.inspect_file).name
        transform_file = Path("trace_debug") / "file_transformations" / f"{file_name}_transformations.json"
    else:
        print(f"{Fore.RED}Error: Either --inspect-file or --transform-file must be specified{Style.RESET_ALL}")
        sys.exit(1)

    if not transform_file.exists():
        print(f"{Fore.RED}Error: No transformation data found at {transform_file}{Style.RESET_ALL}")
        sys.exit(1)

    try:
        with open(transform_file, "r", encoding="utf-8") as f:
            transform_data = json.load(f)
            print_transformation_report(transform_data, args.inspect_file)
    except (IOError, json.JSONDecodeError) as e:
        print(f"{Fore.RED}Error loading transformation data: {str(e)}{Style.RESET_ALL}")
        sys.exit(1)
    sys.exit(0)


def handle_file_inspection(args: argparse.Namespace) -> None:
    """Handle file inspection functionality."""
    inspection_data = CodeTracer.inspect_file(args.inspect_file)
    if "error" in inspection_data:
        print(f"{Fore.RED}{inspection_data['error']}{Style.RESET_ALL}")
        sys.exit(1)

    print(f"\n{Fore.YELLOW}=== Inspection Report for {args.inspect_file} ==={Style.RESET_ALL}")
    print(f"{Fore.CYAN}Processed Symbols:{Style.RESET_ALL} {len(inspection_data.get('processed_symbols', []))}")

    print(f"\n{Fore.GREEN}Batch Processing Details:{Style.RESET_ALL}")
    for i, batch in enumerate(inspection_data.get("symbol_batches", []), 1):
        print(f"{Fore.YELLOW}Batch #{i} ({batch['batch_id']}):{Style.RESET_ALL}")
        print(f"  Symbols: {', '.join(batch['symbols'])}")
        print(f"  Prompt Preview:\n{Fore.WHITE}{batch['prompt_snippet']}{Style.RESET_ALL}")
        if "response" in batch:
            print(f"  Response Preview:\n{Fore.WHITE}{batch['response']}{Style.RESET_ALL}")
        print("-" * 80)

    print(f"\n{Fore.GREEN}Latest 3 Responses:{Style.RESET_ALL}")
    for resp in inspection_data.get("responses", [])[-3:]:
        print(f"{Fore.WHITE}{resp}{Style.RESET_ALL}\n{'-' * 40}")

    sys.exit(0)


def handle_lookup_operations(args: argparse.Namespace) -> None:
    """Handle lookup operations from command line arguments."""
    search_strings = []
    if args.lookup_strings:
        search_strings.extend([s for s in args.lookup_strings if len(s) > 10 and not re.match(r"^[\W_]+$", s)])
    if args.lookup_yaml:
        try:
            with open(args.lookup_yaml, "r", encoding="utf-8") as f:
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
        except (IOError, yaml.YAMLError) as e:
            print(f"Error loading lookup YAML file: {str(e)}")
            sys.exit(1)
    if args.pasteboard:
        clipboard_content = get_clipboard_content()
        if clipboard_content:
            error_lines = parse_error_lines(clipboard_content)
            search_strings.extend(error_lines)
            print(f"Found {len(error_lines)} error lines in clipboard content")

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


def handle_apply_transform(args: argparse.Namespace) -> None:
    """Handle applying transformations from transformation files."""
    skip_symbols = set(args.skip_symbols.split(",")) if args.skip_symbols else set()

    if args.transform_file:
        transform_file = Path(args.transform_file)
        if not transform_file.exists():
            print(f"{Fore.RED}Error: Transformation file not found at {transform_file}{Style.RESET_ALL}")
            sys.exit(1)

        applier = TransformApplier(skip_symbols=skip_symbols, dry_run=args.dry_run)
        success = applier.apply_transformations(args.file_path, transform_file)
        if not success:
            sys.exit(1)
    else:
        if not args.file_path:
            print(f"{Fore.RED}Error: --file must be specified when using default transformation file{Style.RESET_ALL}")
            sys.exit(1)

        success = TransformApplier.apply_from_default_transform_file(args.file_path, skip_symbols, dry_run=args.dry_run)
        if not success:
            sys.exit(1)

    sys.exit(0)


def main() -> None:
    """Main entry point for code tracing functionality."""
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
        help="Search prompt cache for specific string and get CRC32 values",
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
        help="Delete matched cache files when using lookup options",
    )
    parser.add_argument(
        "--prompt-debug",
        dest="prompt_debug",
        help="Path to prompt cache JSON file to resend for debugging",
    )
    parser.add_argument(
        "--inspect-file",
        dest="inspect_file",
        help="Path to source file to view processing details",
    )
    parser.add_argument(
        "--inspect-transform",
        dest="inspect_transform",
        action="store_true",
        help="Show detailed report of all code transformations",
    )
    parser.add_argument(
        "--transform-file",
        dest="transform_file",
        help="Path to specific transformation file to inspect",
    )
    parser.add_argument(
        "--apply-transform",
        dest="apply_transform",
        action="store_true",
        help="Apply transformations from transformation files",
    )
    parser.add_argument(
        "--skip-symbols",
        dest="skip_symbols",
        help="Comma-separated list of symbols to skip when applying transformations",
        default="",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview which symbols would be skipped without actually applying changes",
        default=False,
    )
    args = parser.parse_args()

    if args.inspect_transform:
        handle_inspect_transform(args)

    if args.prompt_debug:
        handle_prompt_debug(args)

    if args.inspect_file:
        handle_file_inspection(args)

    if args.lookup_strings or args.lookup_yaml or args.pasteboard:
        handle_lookup_operations(args)

    if args.apply_transform:
        handle_apply_transform(args)

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
