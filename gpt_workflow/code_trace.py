import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from llm_query import ModelSwitch, process_patch_response
from tree import ParserLoader as PL
from tree import ParserUtil as PU


class CodeTracer:
    """跟踪代码符号并进行批量处理的类，支持多线程处理"""

    def __init__(
        self, file_path: str, no_cache_prompt_file: List[str] = None, stop_event=None, skip_crc32: List[str] = None
    ):
        self.file_path = file_path
        self.parser_loader = PL()
        self.parser_util = PU(self.parser_loader)
        self.results, self.code_map = self.parser_util.get_symbol_paths(file_path)
        self.symbol_detail_map: Dict[str, dict] = {}
        self.responses: List[str] = []
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=32)
        self.ranges = []
        self.model_switch = ModelSwitch()
        self.no_cache_prompt_file = no_cache_prompt_file or []
        self.processed_symbols = []
        self.stop_event = stop_event
        self.skip_crc32 = set(skip_crc32 or [])
        self.symbol_crc_map: Dict[str, List[str]] = {}
        self.current_batch_crc = None

        prompt_dir = Path(__file__).parent.parent / "prompts"
        self.prompt = (prompt_dir / "code-trace").read_text(encoding="utf-8") + "\n\n"
        self.prompt += self._build_response_template()
        self.prompt += (prompt_dir / "dumb-example").read_text(encoding="utf-8") + "\n\n"

    def _build_response_template(self) -> str:
        header = "[modified whole {modified_type}]: 符号路径".format(modified_type="symbol")
        end_tag = "[" + "end]"
        return f"""
# 响应格式
{header}
[start]
完整原始内容
{end_tag}

或（无修改时）:
{header}
[start]
完整原始内容
{end_tag}
"""

    def _process_symbol(self, symbol_name: str, symbol: dict) -> str:
        if self.stop_event and self.stop_event.is_set():
            return ""
        if symbol["type"] not in ("function", "class", "namespace", "declaration"):
            print(f"Skipping non-target symbol: {symbol_name}({symbol['type']})")
            return ""
        if symbol_name.count(".") > 1:
            return ""
        self.symbol_detail_map[f"{self.file_path}/{symbol_name}"] = {
            "file_path": self.file_path,
            "block_range": symbol["block_range"],
            "block_content": symbol["code"].encode("utf-8") if isinstance(symbol["code"], str) else symbol["code"],
        }
        range = symbol["block_range"]
        start_pos, end_pos = range
        for prev_start, prev_end in self.ranges:
            if start_pos <= prev_end and end_pos >= prev_start:
                print(f"Skipping overlapping symbol: {symbol_name}")
                return ""
        self.ranges.append(symbol["block_range"])
        code_content = symbol["code"] if isinstance(symbol["code"], str) else symbol["code"].decode("utf-8")
        end_tag = "[" + "end]"
        return f"""
[SYMBOL START]
符号路径: {self.file_path}/{symbol_name}

[start]
{code_content}
{end_tag}

[SYMBOL END]
"""

    def _submit_batch(self, batch: List[str]):
        if self.stop_event and self.stop_event.is_set():
            return
        if not batch:
            return

        batch_prompt = self.prompt + "\n".join(batch)
        batch_crc = hex(zlib.crc32(batch_prompt.encode("utf-8")) & 0xFFFFFFFF)[2:].zfill(8)

        if batch_crc in self.skip_crc32:
            print(f"Skipping batch with CRC32: {batch_crc}")
            return

        self.current_batch_crc = batch_crc
        print(f"Submitting batch with CRC32: {batch_crc}, symbols count: {len(batch)}")

        future = self.executor.submit(
            self.model_switch.query_for_text,
            model_name="siliconflow-r1",
            prompt=batch_prompt,
            disable_conversation_history=True,
            verbose=True,
            no_cache_prompt_file=self.no_cache_prompt_file,
        )
        future.add_done_callback(self._handle_response)

    def _handle_response(self, future):
        try:
            if self.stop_event and self.stop_event.is_set():
                return
            response = future.result()
            with self.lock:
                self.responses.append(response)
            print("Successfully processed batch response")
        except Exception as e:
            print(f"Error processing batch: {str(e)}")

    def process(self):
        current_batch = []
        current_length = 0
        MAX_BATCH_LENGTH = 60000
        MAX_BATCH_SIZE = 4

        added = set()
        for symbol_name, symbol in self.code_map.items():
            if self.stop_event and self.stop_event.is_set():
                print("检测到停止事件，终止符号处理")
                break

            symbol_snippet = self._process_symbol(symbol_name, symbol)
            if not symbol_snippet:
                continue
            if "class" in symbol["code"] or "namespace" in symbol["code"]:
                print(f"Skipping symbol {symbol_name}({symbol['type']})")
                continue
            if symbol_name.count(".") > 0 and symbol_name[: symbol_name.rfind(".")] in added:
                print(f"Skipping symbol {symbol_name} due to parent symbol already added")
                continue
            print(f"Processing symbol: {symbol_name}({symbol['type']})")
            print("adding symbol:", symbol_name)
            added.add(symbol_name)
            snippet_length = len(symbol_snippet)
            if current_length + snippet_length > MAX_BATCH_LENGTH or len(current_batch) >= MAX_BATCH_SIZE:
                self._submit_batch(current_batch)
                current_batch = []
                current_length = 0

            current_batch.append(symbol_snippet)
            current_length += snippet_length
            self.processed_symbols.append(symbol_name)

        if not (self.stop_event and self.stop_event.is_set()):
            self._submit_batch(current_batch)

        self.executor.shutdown(wait=not (self.stop_event and self.stop_event.is_set()))

        if not (self.stop_event and self.stop_event.is_set()):
            process_patch_response(
                "\n".join(self.responses), self.symbol_detail_map, ignore_new_symbol=True, no_mix=True, confirm="y"
            )
            print("All symbols processed with multi-threading")
        else:
            print("处理已中止，跳过最终响应处理")

    @classmethod
    def lookup_prompt_cache(cls, search_string: str, delete_matched: bool = False) -> Tuple[List[Dict], str]:
        """在prompt缓存中搜索包含指定字符串的条目，返回结果和CRC32列表"""
        cache_dir = Path("prompt_cache")
        if not cache_dir.exists():
            return ([], "")

        results = []
        crc_list = []
        deleted_files = []

        for cache_file in cache_dir.glob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    prompt_content = data.get("prompt", "")
                    response_content = data.get("response_text", "")

                    if search_string in prompt_content or search_string in response_content:
                        crc_value = hex(data.get("crc32", "0"))[2:].zfill(8)
                        results.append(
                            {
                                "filename": cache_file.name,
                                "crc32": crc_value,
                                "timestamp": data.get("timestamp", ""),
                                "prompt_preview": prompt_content[:200] + "..."
                                if len(prompt_content) > 200
                                else prompt_content,
                                "response_preview": response_content[:200] + "..."
                                if len(response_content) > 200
                                else response_content,
                            }
                        )
                        crc_list.append(crc_value)

                        if delete_matched:
                            os.remove(cache_file)
                            deleted_files.append(cache_file.name)

            except Exception as e:
                print(f"Error reading cache file {cache_file}: {str(e)}")

        crc_str = ",".join(crc_list)
        if delete_matched and deleted_files:
            print(f"\nDeleted {len(deleted_files)} matched cache files: {', '.join(deleted_files)}")

        return (results, crc_str)


class TraceConfig:
    def __init__(self, config_file: str):
        self.config_file = config_file
        self.source_files: List[str] = []
        self.verify_cmd: str = ""
        self.progress_dir = Path("trace_progress")
        self.traced_files: Set[str] = set()
        self.failed_files: List[str] = []
        self.verify_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.skip_crc32: Set[str] = set()
        self.load_config()
        self.ensure_progress_dir()

    def load_config(self) -> None:
        try:
            with open(self.config_file, "r") as f:
                config = yaml.safe_load(f)
            source_patterns = config.get("source_files", [])
            for pattern in source_patterns:
                matched_files = glob.glob(pattern, recursive=True)
                self.source_files.extend(matched_files)
            self.verify_cmd = config.get("verify_cmd", "")
            progress_dir = config.get("progress_dir", "trace_progress")
            self.progress_dir = Path(progress_dir)
            self.skip_crc32 = set(config.get("skip_crc32", []))
        except Exception as e:
            print(f"Error loading config file: {str(e)}")
            raise

    def ensure_progress_dir(self) -> None:
        self.progress_dir.mkdir(exist_ok=True)

    def load_progress(self) -> None:
        self.traced_files = set()
        progress_file = self.progress_dir / "trace_progress.json"
        if progress_file.exists():
            try:
                with open(progress_file, "r") as f:
                    progress_data = json.load(f)
                self.traced_files = set(progress_data.get("traced_files", []))
                print(f"Loaded {len(self.traced_files)} traced files from progress")
            except Exception as e:
                print(f"Error loading progress file: {str(e)}")

    def save_progress(self) -> None:
        progress_file = self.progress_dir / "trace_progress.json"
        try:
            with open(progress_file, "w") as f:
                json.dump({"traced_files": list(self.traced_files)}, f, indent=2)
            print(f"Progress saved to {progress_file}")
        except Exception as e:
            print(f"Error saving progress file: {str(e)}")

    def save_failed_files(self) -> None:
        if not self.failed_files:
            return

        failed_file = self.progress_dir / "failed_files.json"
        try:
            with open(failed_file, "w") as f:
                json.dump({"failed_files": self.failed_files}, f, indent=2)
            print(f"Failed files saved to {failed_file}")
        except Exception as e:
            print(f"Error saving failed files: {str(e)}")

    def restore_file(self, file_path: str) -> None:
        try:
            subprocess.run(["git", "restore", file_path], check=True)
            print(f"Restored {file_path} using git restore")
        except subprocess.CalledProcessError as e:
            print(f"git restore failed: {str(e)}, trying git checkout")
            try:
                subprocess.run(["git", "checkout", "--", file_path], check=True)
                print(f"Checked out {file_path} to discard changes")
            except subprocess.CalledProcessError as e2:
                print(f"Failed to restore {file_path}: {str(e2)}")

    def save_failed_symbols(self, file_path: str, symbols: List[str], crc32_list: List[str]) -> None:
        if not symbols:
            return
        debug_dir = self.progress_dir / "debug"
        debug_dir.mkdir(exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_file = debug_dir / f"failed_symbols_{file_path.replace('/', '_')}_{timestamp}.json"
        try:
            with open(debug_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "file_path": file_path,
                        "failed_symbols": symbols,
                        "crc32_list": crc32_list,
                        "timestamp": timestamp,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            print(f"Saved failed symbols with CRC32 to {debug_file}")
        except Exception as e:
            print(f"Error saving failed symbols: {str(e)}")

    def mark_as_traced(self, file_path: str) -> None:
        self.traced_files.add(file_path)
        self.save_progress()

    def verify_trace(self) -> bool:
        if not self.verify_cmd:
            return True

        with self.verify_lock:
            try:
                print(f"Running verify command: {self.verify_cmd}")
                result = subprocess.run(self.verify_cmd, shell=True, check=False)
                return result.returncode == 0
            except Exception as e:
                print(f"Error running verify command: {str(e)}")
                return False

    def get_next_file(self, ignore_traced: bool = True) -> Optional[str]:
        if ignore_traced:
            for file in self.source_files:
                if file not in self.traced_files:
                    return file
            return None
        else:
            return self.source_files[0] if self.source_files else None

    def trace_single_file(self, file_path: str) -> Tuple[bool, Optional[str]]:
        if self.stop_event.is_set():
            return (False, file_path)

        print(f"Processing file: {file_path}")
        tracer = CodeTracer(file_path, stop_event=self.stop_event, skip_crc32=self.skip_crc32)
        tracer.process()
        processed_symbols = tracer.processed_symbols

        if not self.verify_trace():
            print(f"Verification failed after processing {file_path}")
            self.restore_file(file_path)
            crc_list = [tracer.current_batch_crc] if tracer.current_batch_crc else []
            self.save_failed_symbols(file_path, processed_symbols, crc_list)
            self.failed_files.append(file_path)
            self.stop_event.set()
            return (False, file_path)

        self.mark_as_traced(file_path)
        return (True, None)

    def trace_all_files(self, ignore_traced: bool = True, parallel: bool = True) -> Tuple[bool, Optional[str]]:
        self.load_progress()

        remaining_files = []
        for file in self.source_files:
            if not ignore_traced or file not in self.traced_files:
                if os.path.exists(file):
                    remaining_files.append(file)
                else:
                    print(f"File {file} does not exist, skipping")

        if not remaining_files:
            print("All files have been traced successfully or do not exist.")
            return (True, None)

        print(f"Found {len(remaining_files)} files to process")

        if not parallel:
            for file in remaining_files:
                if self.stop_event.is_set():
                    break
                success, failed_file = self.trace_single_file(file)
                if not success:
                    self.save_failed_files()
                    return (False, failed_file)
            self.save_failed_files()
            return (True, None)

        print(f"Processing {len(remaining_files)} files in parallel")
        with ThreadPoolExecutor(max_workers=32) as pool:
            futures = {pool.submit(self.trace_single_file, file): file for file in remaining_files}

            for future in as_completed(futures):
                success, failed_file = future.result()
                if not success:
                    self.stop_event.set()
                    for f in futures:
                        f.cancel()
                    self.save_failed_files()
                    return (False, failed_file)

        self.save_failed_files()
        return (True, None)


def main():
    parser = argparse.ArgumentParser(description="Trace code symbols and process them in batch")
    parser.add_argument("--file", "-f", dest="file_path", help="Path to the file to be analyzed")
    parser.add_argument("--config", "-c", dest="config_file", help="Path to the trace configuration file")
    parser.add_argument(
        "--no-cache", dest="no_cache_files", help="Comma-separated list of prompt files to not cache", default=""
    )
    parser.add_argument(
        "--ignore-traced", dest="ignore_traced", action="store_true", help="Ignore already traced files", default=True
    )
    parser.add_argument(
        "--parallel", dest="parallel", action="store_true", help="Process files in parallel", default=False
    )
    parser.add_argument(
        "--skip-crc32", dest="skip_crc32", help="Comma-separated list of CRC32 values to skip", default=""
    )
    parser.add_argument(
        "--lookup-string", dest="lookup_string", help="Search prompt cache for specific string and get CRC32 values"
    )
    parser.add_argument(
        "--delete-matched",
        dest="delete_matched",
        action="store_true",
        help="Delete matched cache files when using --lookup-string",
    )

    args = parser.parse_args()

    # Handle lookup string first
    if args.lookup_string:
        results, crc_str = CodeTracer.lookup_prompt_cache(args.lookup_string, args.delete_matched)
        if results:
            print("\nFound matching cache entries:")
            print(f"{'CRC32':<10} | {'Filename':<30} | {'Timestamp':<20}")
            print("-" * 70)
            for entry in results:
                print(f"{entry['crc32']:<10} | {entry['filename']:<30} | {entry['timestamp']:<20}")

            print(f"\nCRC32 list for skipping: {crc_str}")
            print("You can use with --skip-crc32 parameter like:")
            print(f"  --skip-crc32 {crc_str}")
        else:
            print(f"No cache entries found containing string: {args.lookup_string}")
        sys.exit(0)

    if args.config_file:
        config = TraceConfig(args.config_file)
        if args.skip_crc32:
            config.skip_crc32.update(args.skip_crc32.split(","))
        success, failed_file = config.trace_all_files(ignore_traced=args.ignore_traced, parallel=args.parallel)
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
