#!/usr/bin/env python3
"""
Trace Log Analyzer - 解析lldb trace日志并生成解释报告
"""

import argparse
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn

from llm_query import FileSearchResult, FileSearchResults, MatchResult, ModelSwitch, query_symbol_service

# 常量定义
MAX_TOKENS_PER_CHUNK = 120000  # 每个块的最大token数
DEFAULT_CONTEXT_LINES = 50  # 默认上下文行数
OUTPUT_DIR = Path("doc")  # 输出目录
BATCH_SIZE = 50
# 批量查询符号的批次大小


class TraceAnalyzer:
    def __init__(self, basedir: str, project_name: str, model_name: str, goals: str = "", max_workers: int = 4):
        self.basedir = Path(basedir).resolve() if basedir else Path.cwd()
        self.project_name = project_name
        self.model_name = model_name
        self.goals = goals
        self.max_workers = max_workers
        self.symbol_cache: Dict[Tuple[str, int], Optional[Dict]] = {}
        self.lock = threading.Lock()

        # 创建输出目录
        OUTPUT_DIR.mkdir(exist_ok=True)

    def _extract_symbol_locations(self, log_lines: List[str]) -> Set[Tuple[str, int]]:
        """
        从trace日志中提取符号位置信息并去重
        返回: 包含(file_path, line_num)元组的集合
        """
        pattern = r";\s*([^\s:]+(?::[^\s:]+)*):(\d+)\b"
        locations = set()

        for line in log_lines:
            match = re.search(pattern, line)
            if match:
                file_path, line_num = match.group(1), int(match.group(2))
                abs_path = self._resolve_path(file_path)
                locations.add((str(abs_path), line_num))

        return locations

    def _resolve_path(self, file_path: str) -> Path:
        """解析文件路径，处理相对路径和绝对路径"""
        path = Path(file_path)
        if not path.is_absolute():
            return self.basedir / path
        return path

    def _batch_fetch_symbols(self, locations: Set[Tuple[str, int]]) -> None:
        """批量获取符号代码并更新缓存"""
        # 过滤已缓存的符号
        uncached_locations = [loc for loc in locations if loc not in self.symbol_cache]
        if not uncached_locations:
            return

        # 准备批量查询
        file_results = {}
        for file_path, line_num in uncached_locations:
            if file_path not in file_results:
                file_results[file_path] = FileSearchResult(file_path=file_path, matches=[])
            file_results[file_path].matches.append(MatchResult(line=line_num, column_range=(0, 0), text=""))

        # 创建查询对象
        search_request = FileSearchResults(results=list(file_results.values()))

        # 查询符号服务
        try:
            with self.lock:
                search_results = query_symbol_service(search_request, max_context_size=1024 * 1024)
        except (ConnectionError, TimeoutError) as e:
            print(f"符号服务查询错误: {str(e)}")
            return

        # 处理查询结果 - 使用新的结果格式
        for symbol_data in search_results.values():
            file_path = symbol_data["file_path"]
            start_line = symbol_data["start_line"]
            end_line = symbol_data["end_line"]
            block_content = symbol_data["code"]

            # 缓存这个符号覆盖的所有行号
            for line_num in range(start_line, end_line + 1):
                cache_key = (file_path, line_num)
                if cache_key in uncached_locations:
                    self.symbol_cache[cache_key] = {
                        "file_path": file_path,
                        "symbol_name": symbol_data["name"],
                        "block_content": block_content,
                        "code_range": (
                            (start_line, symbol_data.get("start_col", 0)),
                            (end_line, symbol_data.get("end_col", 0)),
                        ),
                    }

        # 缓存未找到的符号
        for loc in uncached_locations:
            if loc not in self.symbol_cache:
                self.symbol_cache[loc] = None

    def _create_prompt(self, log_chunk: str, locations: Set[Tuple[str, int]]) -> str:
        """为日志块创建提示词"""
        base_prompt = [
            "## 任务说明",
            "你是一个高级软件分析专家，正在分析一段软件执行的trace日志。",
            "请完成以下任务：",
            "1. 分析trace日志块的完整执行过程,包括函数调用关系",
            "2. 解释每个关键步骤在做什么3. 生成mermaid流程图展示执行流程",
            "4. 所有分析使用中文",
            "5. 用通俗的的话解释其作用和目的",
            "",
            "## Trace日志块",
            "```",
            log_chunk,
            "```",
        ]

        # 添加用户额外目标
        if self.goals:
            base_prompt.extend(["", "## 额外分析目标", self.goals, ""])

        # 添加相关代码参考
        base_prompt.append("## 相关代码参考")
        added_symbols = set()

        for file_path, line_num in locations:
            symbol_data = self.symbol_cache.get((file_path, line_num))
            if not symbol_data:
                continue

            # 避免重复添加相同符号
            symbol_key = (file_path, symbol_data["symbol_name"])
            if symbol_key in added_symbols:
                continue
            added_symbols.add(symbol_key)

            base_prompt.append(f"### 文件: {file_path} - 符号: {symbol_data['symbol_name']}")
            base_prompt.append("```c++")
            base_prompt.append(symbol_data["block_content"])
            base_prompt.append("```")
            base_prompt.append("")

        base_prompt.append("## 你的分析（请严格按照以下格式输出）")
        base_prompt.append("1. **执行过程概述**: \n2. **关键步骤解释**: \n3. **mermaid流程图**: \n```mermaid")

        return "\n".join(base_prompt)

    def _process_chunk(self, chunk_idx: int, log_chunk: str) -> Tuple[Optional[str], Optional[str]]:
        """处理单个日志块并获取分析结果"""
        # 提取符号位置
        log_lines = log_chunk.splitlines()
        locations = self._extract_symbol_locations(log_lines)

        # 批量获取符号代码
        self._batch_fetch_symbols(locations)

        # 创建提示词
        prompt = self._create_prompt(log_chunk, locations)

        # 查询大模型
        try:
            response = ModelSwitch().query_for_text(model_name=self.model_name, prompt=prompt, stream=False)
            return prompt, response
        except (ConnectionError, TimeoutError) as e:
            print(f"处理块 {chunk_idx} 时出错: {str(e)}")
            return prompt, None

    def _save_result(self, chunk_idx: int, question: str, answer: str):
        """保存分析结果到markdown文件"""
        filename = OUTPUT_DIR / f"{self.project_name}_part_{chunk_idx}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {self.project_name} - Trace分析报告 (Part {chunk_idx})\n\n")
            f.write("## 模型分析结果\n")
            f.write(answer)
            f.write("\n\n## 原始问题\n```markdown\n")
            f.write(question)
            f.write("\n```\n")

    def _split_log(self, log_content: str) -> List[str]:
        """将日志分割成大小合适的块，确保在函数边界分割且每个块至少包含50行"""
        chunks = []
        current_chunk = []
        current_size = 0
        lines = log_content.splitlines()

        # 用于检测函数边界的正则表达式
        function_boundary = re.compile(r"^\s*(bl\s+|ret\b|->\s+ret\b)", re.IGNORECASE)

        # 最小行数要求
        min_lines = 300

        for line in lines:
            line_size = len(line) + 1  # 加上换行符

            # 检查是否达到函数边界
            is_boundary = function_boundary.search(line) is not None

            current_chunk.append(line)
            current_size += line_size

            # 只有当当前块足够大并且遇到函数边界时才分割
            if (current_size > MAX_TOKENS_PER_CHUNK or is_boundary) and len(current_chunk) >= min_lines:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0

        # 处理剩余行
        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    def analyze(self, trace_file: str):
        """主分析函数"""
        # 读取trace文件
        try:
            with open(trace_file, "r", encoding="utf-8", errors="replace") as f:
                log_content = f.read()
        except (FileNotFoundError, PermissionError) as e:
            print(f"无法读取trace文件: {str(e)}")
            return

        # 分割日志
        chunks = self._split_log(log_content)
        total_chunks = len(chunks)
        print(f"发现 {total_chunks} 个日志块，开始分析...")

        # 使用线程池并行处理
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}

            # 提交任务
            for idx, chunk in enumerate(chunks):
                future = executor.submit(self._process_chunk, idx, chunk)
                futures[future] = idx

            # 进度显示
            with Progress(
                TextColumn("[bold blue]{task.description}", justify="right"),
                BarColumn(bar_width=None),
                TaskProgressColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task(f"[cyan]分析{self.project_name}的trace日志...", total=total_chunks)

                # 处理结果
                for future in as_completed(futures):
                    idx = futures[future]
                    question, answer = future.result()

                    if answer:
                        # 保存结果
                        self._save_result(idx, question, answer)
                        progress.print(f"✅ 块 {idx} 分析完成")
                    else:
                        progress.print(f"❌ 块 {idx} 分析失败")

                    progress.update(task, advance=1)

        print(f"\n分析完成！结果保存在 {OUTPUT_DIR} 目录")


def main():
    parser = argparse.ArgumentParser(
        description="Trace日志分析工具 - 解析lldb trace日志并生成解释报告",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--trace_file", required=True, help="lldb trace日志文件路径")
    parser.add_argument("--project_name", required=True, help="项目名称（用于输出文件名）")
    parser.add_argument("--basedir", default="", help="源代码基础目录（用于解析相对路径）")
    parser.add_argument("--model", default="deepseek-r1", help="选择大模型（deepseek-r1, gpt-4, claude-3等）")
    parser.add_argument("--workers", type=int, default=4, help="并行工作线程数（设置为1禁用并行）")
    parser.add_argument("--goals", default="", help="额外分析目标（添加到prompt中，可以是文件路径或文本）")

    args = parser.parse_args()

    # 如果提供了目标文件，读取其内容
    goals_text = args.goals
    if args.goals and os.path.isfile(args.goals):
        try:
            with open(args.goals, "r", encoding="utf-8") as f:
                goals_text = f.read()
        except (IOError, OSError) as e:  # 更具体的异常类型
            print(f"警告：无法读取目标文件 '{args.goals}': {str(e)}")

    # 初始化模型并分析
    ModelSwitch().select(args.model)
    analyzer = TraceAnalyzer(
        basedir=args.basedir,
        project_name=args.project_name,
        model_name=args.model,
        goals=goals_text,
        max_workers=args.workers,
    )
    analyzer.analyze(args.trace_file)


if __name__ == "__main__":
    main()
