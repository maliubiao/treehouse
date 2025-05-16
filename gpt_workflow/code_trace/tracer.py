import argparse
import json
import os
import subprocess
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from llm_query import BlockPatchResponse, ModelSwitch, process_patch_response
from tree import ParserLoader as PL
from tree import ParserUtil as PU


def build_response_template() -> str:
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


prompt_dir = Path(__file__).parent.parent.parent / "prompts"
base_prompt = (prompt_dir / "code-trace").read_text(encoding="utf-8") + "\n\n"
base_prompt += build_response_template()


class CodeTracer:
    """跟踪代码符号并进行批量处理的类，支持多线程处理"""

    def __init__(
        self, file_path: str, no_cache_prompt_file: List[str] = None, stop_event=None, skip_crc32: List[str] = None
    ):
        self.file_path = os.path.abspath(file_path)
        self.parser_loader = PL()
        self.parser_util = PU(self.parser_loader)
        self.results, self.code_map = self.parser_util.get_symbol_paths(self.file_path)
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
        self.batch_responses = []
        self.prompt = base_prompt + "\n\n"
        self.inspection_data = {"file_path": self.file_path, "symbol_batches": [], "prompts": [], "responses": []}
        self.global_transformations = {}  # 新增: 存储全局符号转换关系

    def _process_symbol(self, symbol_name: str, symbol: dict) -> str:
        if self.stop_event and self.stop_event.is_set():
            return ""
        if symbol["type"] not in ("function", "class", "namespace"):
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
        batch_symbols = [self._extract_symbol_name(snippet) for snippet in batch]

        batch_id = f"{self.file_path}_batch{len(self.inspection_data['symbol_batches']) + 1}"
        self.inspection_data["symbol_batches"].append(
            {
                "batch_id": batch_id,
                "symbols": batch_symbols,
                "symbol_snippets": batch,  # 保存原始符号片段
                "prompt_snippet": batch_prompt,
            }
        )

        print(f"Submitting batch symbols count: {len(batch)}")
        future = self.executor.submit(
            self.model_switch.query_for_text,
            model_name="hyperbolic-r1",
            prompt=batch_prompt,
            disable_conversation_history=True,
            verbose=False,
            no_cache_prompt_file=self.no_cache_prompt_file,
            skip_crc32=self.skip_crc32,
        )
        future.add_done_callback(lambda f: self._handle_response(f, batch_id))

    def _extract_symbol_name(self, snippet: str) -> str:
        lines = snippet.split("\n")
        for line in lines:
            if line.startswith("符号路径:"):
                return line.split("/")[-1].strip()
        return "unknown_symbol"

    def _handle_response(self, future, batch_id: str):
        try:
            if self.stop_event and self.stop_event.is_set():
                return
            response = future.result()
            with self.lock:
                self.responses.append(response)
                self.batch_responses.append(
                    {
                        "crc32": self.current_batch_crc,
                        "response": response,
                    }
                )
                self._record_response(batch_id, response)
            print("Successfully processed batch response")
        except Exception as e:
            print(f"Error processing batch: {str(e)}")

    def _record_response(self, batch_id: str, response: str):
        """记录响应数据，包括符号转换前后的代码对应关系"""

        # 解析响应中的符号转换结果
        parser = BlockPatchResponse()
        transformed_symbols = parser.parse(response)
        transformed_map = {symbol: code for symbol, code in transformed_symbols}

        # 更新batch信息
        for batch in self.inspection_data["symbol_batches"]:
            if batch["batch_id"] == batch_id:
                batch["response"] = response
                batch["symbol_transformations"] = []

                # 记录每个符号的转换关系
                for symbol_snippet in batch.get("symbol_snippets", []):
                    symbol_name = self._extract_symbol_name(symbol_snippet)
                    original_code = self.code_map.get(symbol_name, {}).get("code", "")
                    transformed_code = transformed_map.get(f"{self.file_path}/{symbol_name}", "")

                    if original_code or transformed_code:
                        # 更新全局转换关系
                        self.global_transformations[f"{self.file_path}/{symbol_name}"] = {
                            "file_path": self.file_path,
                            "symbol_name": symbol_name,
                            "original_code": original_code,
                            "transformed_code": transformed_code.strip("\n"),
                            "is_changed": transformed_code and transformed_code != original_code,
                        }

                        batch["symbol_transformations"].append(
                            {
                                "symbol": symbol_name,
                                "original_code": original_code,
                                "transformed_code": transformed_code.strip("\n"),
                            }
                        )
                break

        self.inspection_data["responses"].append(response)
        self._save_inspection_data()
        self._save_global_transformations()  # 新增: 保存全局转换关系

    def _save_inspection_data(self):
        """保存检查数据到文件，包括符号转换统计信息"""
        debug_dir = Path("trace_debug")
        debug_dir.mkdir(exist_ok=True)
        log_file = debug_dir / f"inspect_{Path(self.file_path).name}.json"

        # 添加转换统计信息
        total_symbols = 0
        transformed_symbols = 0
        for batch in self.inspection_data.get("symbol_batches", []):
            if "symbol_transformations" in batch:
                total_symbols += len(batch["symbol_transformations"])
                transformed_symbols += sum(
                    1
                    for t in batch["symbol_transformations"]
                    if t["transformed_code"] and t["transformed_code"] != t["original_code"]
                )

        self.inspection_data["transformation_stats"] = {
            "total_symbols": total_symbols,
            "transformed_symbols": transformed_symbols,
            "transformation_rate": transformed_symbols / total_symbols if total_symbols > 0 else 0,
        }

        try:
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(self.inspection_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving inspection data: {str(e)}")

    def _save_global_transformations(self):
        """保存全局符号转换关系到文件"""
        debug_dir = Path("trace_debug")
        debug_dir.mkdir(exist_ok=True)
        global_file = debug_dir / "global_transformations.json"

        try:
            with open(global_file, "w", encoding="utf-8") as f:
                json.dump(self.global_transformations, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving global transformations: {str(e)}")

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
                "\n".join(self.responses),
                self.symbol_detail_map,
                ignore_new_symbol=True,
                no_mix=True,
                confirm="y",
                change_log=False,
            )
            self._save_inspection_data()
            self._save_global_transformations()  # 确保最终保存
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

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict:
        """检查指定文件的跟踪调试信息"""
        debug_dir = Path("trace_debug")
        log_file = debug_dir / f"inspect_{Path(file_path).name}.json"
        if not log_file.exists():
            return {"error": f"No inspection data found for {file_path}"}

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"error": f"Failed to load inspection data: {str(e)}"}
