import argparse
import glob
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

from llm_query import ModelSwitch, process_patch_response
from tree import ParserLoader as PL
from tree import ParserUtil as PU


class CodeTracer:
    """跟踪代码符号并进行批量处理的核心类"""

    def __init__(self, file_path: str, no_cache_prompt_file: List[str] = None):
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

        # 初始化提示模板
        prompt_dir = Path(__file__).parent.parent / "prompts"
        self.prompt = (prompt_dir / "code-trace").read_text(encoding="utf-8") + "\n\n"
        self.prompt += self._build_response_template()
        self.prompt += (prompt_dir / "dumb-example").read_text(encoding="utf-8") + "\n\n"

    def _build_response_template(self) -> str:
        """构建响应格式模板"""
        return """
# 响应格式
[modified whole {modified_type}]: 符号路径
[{tag} start]
完整文件内容
[{tag} end]

或（无修改时）:
[modified whole {modified_type}]: 符号路径
[{tag} start]
完整原始内容
[{tag} end]
""".format(modified_type="symbol", tag="symbol")

    def _process_symbol(self, symbol_name: str, symbol: dict) -> str:
        """处理单个符号并生成prompt片段"""
        if symbol["type"] not in ("function", "class", "namespace", "declaration"):
            print(f"Skipping non-target symbol: {symbol_name}({symbol['type']})")
            return ""
        if symbol_name.count(".") > 1:
            return ""
        self.symbol_detail_map[f"{self.file_path}/{symbol_name}"] = {
            "file_path": self.file_path,
            "block_range": symbol["block_range"],
            "block_content": symbol["code"].encode("utf-8"),
        }
        range = symbol["block_range"]
        start_pos, end_pos = range
        # Check for overlap with previously processed ranges
        for prev_start, prev_end in self.ranges:
            # Detect if there's any overlap
            if start_pos <= prev_end and end_pos >= prev_start:
                print(f"Skipping overlapping symbol: {symbol_name}")
                return ""
        # Add the current range to our list of processed ranges
        self.ranges.append(symbol["block_range"])
        code_content = symbol["code"] if isinstance(symbol["code"], str) else symbol["code"].decode("utf-8")
        return f"""
[SYMBOL START]
符号路径: {self.file_path}/{symbol_name}

[source code start]
{code_content}
[source code end]

[SYMBOL END]
"""

    def _submit_batch(self, batch: List[str]):
        """提交批处理任务到线程池"""
        if not batch:
            return

        batch_prompt = self.prompt + "\n".join(batch)
        print(f"Submitting batch with {len(batch)} symbols, length: {len(batch_prompt)}")

        future = self.executor.submit(
            self.model_switch.query_for_text,
            model_name="coder",
            prompt=batch_prompt,
            disable_conversation_history=True,
            verbose=False,
            no_cache_prompt_file=self.no_cache_prompt_file,
        )
        future.add_done_callback(self._handle_response)

    def _handle_response(self, future):
        """处理异步响应结果"""
        try:
            response = future.result()
            with self.lock:
                self.responses.append(response)
            print("Successfully processed batch response")
        except Exception as e:
            print(f"Error processing batch: {str(e)}")

    def process(self):
        """主处理流程"""
        current_batch = []
        current_length = 0
        MAX_BATCH_LENGTH = 60000  # 预留部分长度给prompt前缀
        MAX_BATCH_SIZE = 4

        added = set()
        for symbol_name, symbol in self.code_map.items():
            symbol_snippet = self._process_symbol(symbol_name, symbol)
            if not symbol_snippet:
                continue
            if "class" in symbol["code"] or "namespace" in symbol["code"]:
                print(f"Skipping symbol {symbol_name}({symbol['type']})")
                continue
            if symbol_name.count(".") > 0 and symbol_name[: symbol_name.rfind(".")] in added:
                print(f"Skipping symbol {symbol_name} due to parent symbol already added")
                continue
            # if "PrivateResume" not in symbol_name: continue
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

        # 提交最后一批
        self._submit_batch(current_batch)

        # 等待所有任务完成
        self.executor.shutdown(wait=True)

        with open("responses.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(self.responses))
        # 统一处理响应
        process_patch_response("\n".join(self.responses), self.symbol_detail_map, ignore_new_symbol=True, no_mix=True)
        print("All symbols processed with multi-threading")


class TraceConfig:
    """配置加载器，用于加载和处理跟踪配置"""

    def __init__(self, config_file: str):
        """初始化配置加载器

        Args:
            config_file: YAML配置文件路径
        """
        self.config_file = config_file
        self.source_files: List[str] = []
        self.verify_cmd: str = ""
        self.progress_dir = Path("trace_progress")
        self.traced_files: Set[str] = set()
        self.load_config()
        self.ensure_progress_dir()

    def load_config(self) -> None:
        """加载YAML配置文件"""
        try:
            with open(self.config_file, "r") as f:
                config = yaml.safe_load(f)

            # 处理源文件路径（支持glob模式）
            source_patterns = config.get("source_files", [])
            for pattern in source_patterns:
                matched_files = glob.glob(pattern, recursive=True)
                self.source_files.extend(matched_files)

            self.verify_cmd = config.get("verify_cmd", "")
            progress_dir = config.get("progress_dir", "trace_progress")
            self.progress_dir = Path(progress_dir)
        except Exception as e:
            print(f"Error loading config file: {str(e)}")
            raise

    def ensure_progress_dir(self) -> None:
        """确保进度目录存在"""
        self.progress_dir.mkdir(exist_ok=True)

    def load_progress(self) -> None:
        """加载之前的处理进度"""
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
        """保存处理进度"""
        progress_file = self.progress_dir / "trace_progress.json"
        try:
            with open(progress_file, "w") as f:
                json.dump({"traced_files": list(self.traced_files)}, f, indent=2)
            print(f"Progress saved to {progress_file}")
        except Exception as e:
            print(f"Error saving progress file: {str(e)}")

    def mark_as_traced(self, file_path: str) -> None:
        """将文件标记为已跟踪

        Args:
            file_path: 已处理的文件路径
        """
        self.traced_files.add(file_path)
        self.save_progress()

    def verify_trace(self) -> bool:
        """运行验证命令

        Returns:
            bool: True表示验证通过，False表示验证失败
        """
        if not self.verify_cmd:
            return True

        try:
            print(f"Running verify command: {self.verify_cmd}")
            result = subprocess.run(self.verify_cmd, shell=True, check=False)
            return result.returncode == 0
        except Exception as e:
            print(f"Error running verify command: {str(e)}")
            return False

    def get_next_file(self, ignore_traced: bool = True) -> Optional[str]:
        """获取下一个要处理的文件

        Args:
            ignore_traced: 是否忽略已经处理过的文件

        Returns:
            Optional[str]: 下一个要处理的文件路径，如果没有则返回None
        """
        if ignore_traced:
            for file in self.source_files:
                if file not in self.traced_files:
                    return file
            return None
        else:
            return self.source_files[0] if self.source_files else None

    def trace_all_files(self, ignore_traced: bool = True) -> bool:
        """处理所有配置的文件

        Args:
            ignore_traced: 是否忽略已经处理过的文件

        Returns:
            bool: 全部处理成功返回True，中途失败返回False
        """
        self.load_progress()

        while True:
            next_file = self.get_next_file(ignore_traced)
            if not next_file:
                print("All files have been traced successfully.")
                return True

            print(f"Processing file: {next_file}")
            tracer = CodeTracer(next_file)
            tracer.process()

            # 打印每个tracer的prompt缓存信息
            print("Prompt cache info for file:", next_file)
            print("Following prompts are cached:")
            for prompt in tracer.model_switch.get_prompt_cache_info():
                print("filename: ", prompt["filename"])
            print("-" * 40)

            if not self.verify_trace():
                print(f"Verification failed after processing {next_file}")
                return False

            self.mark_as_traced(next_file)


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

    args = parser.parse_args()

    if args.config_file:
        config = TraceConfig(args.config_file)
        config.trace_all_files(ignore_traced=args.ignore_traced)
        print("All files processed according to configuration")
    elif args.file_path:
        tracer = CodeTracer(args.file_path)
        if args.no_cache_files:
            tracer.no_cache_prompt_file = args.no_cache_files.split(",")
            print("No cache prompt files: ", tracer.no_cache_prompt_file)

        tracer.process()
        print("following prompts are cached, pass json name with --no-cache to use cache response for others")
        for prompt in tracer.model_switch.get_prompt_cache_info():
            print("filename: ", prompt["filename"])
    else:
        parser.error("Either --file or --config must be specified")


if __name__ == "__main__":
    main()
