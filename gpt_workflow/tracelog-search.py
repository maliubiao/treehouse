import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

from rich.console import Console
from rich.markdown import Markdown

from llm_query import ModelSwitch

console = Console()

# The mini prompt was removed as it was less structured.

GEMINI_PROMPT = """
# 角色与目标
你是一位资深的日志分析专家。你的目标是通过执行一系列命令行搜索，帮助用户在庞大的跟踪日志文件 (`{log_name}`) 中找到所需信息。

# 核心任务
- 理解用户需求。
- 通过迭代式搜索，在日志文件 (`{log_name}`) 中定位相关上下文。
- 日志文件非常大，你必须只获取小而相关的上下文片段，以防超出上下文窗口限制。
- 当你找到足够的信息满足用户需求时，终止流程。

# 工作流程（迭代过程）
1. 你会收到用户的请求，以及在后续的交互中，你上一条命令的执行结果。
2. 分析所有可用信息。
3. 构建一条用于搜索的单行命令。
4. 提供你的命令和执行该命令的理由。
5. 系统将执行你的命令，并在下一轮交互中返回其输出。
6. 重复此过程，每一轮都优化你的搜索，直到满足用户需求。

# 工具箱与限制
- **可用命令**: 你只能使用 `rg`, `awk`, `sed`, `head`, `tail`。
- **单行命令**: 所有命令都必须是单行命令（one-liner）。
- **`rg` (ripgrep) 使用规则**:
    - **强制**: 必须使用 `-n` 选项，让输出包含行号。
    - **可用选项**: 你只能使用 `-A` (后文), `-B` (前文), `-n` (行号), 和 `-e` (模式)。禁止使用其他任何选项。
    - **正则表达式**: 禁止使用跨行正则表达式。
- **`sed` / `awk` 提取行号范围**: 你可以使用 `sed -n '起始行,结束行p' {log_name}` 或 `awk 'NR>=起始行 && NR<=结束行' {log_name}` 这样的命令，来提取通过 `rg` 输出发现的特定行号范围。

# 搜索策略
- **翻译为英文**: 日志内容主要是英文。将用户的中文需求转换成英文关键词，可以更有效地搜索。
- **先宽后窄**: 使用一个稍微宽泛或“模糊”的正则表达式，通常比一个过于精确而搜不到任何结果的表达式要好。
- **上下文是关键**: 当找到匹配项时，尝试获取其周围约30行的上下文（例如，使用 `rg -A 15 -B 15`）。这有助于全面理解情况。

# 状态管理 (在 `[conclusion start]` 部分)
这部分是你的记忆。为了指导后续搜索，你**必须**在此总结你的发现。
- **目标**: 记录关键信息，为日志文件建立一个“地图”。
- **核对清单**: 在每一轮中，尝试将新的发现添加到这个清单中。目标是在整个会话中累积至少20个重要条目。
    - 日志中的重要术语或概念。
    - 相关的文件名、函数名、类名或变量名。
    - 典型的日志行格式或结构。
    - 关键的时间戳或序列号。
    - 基于已有发现，对问题成因的假设。

# 输入格式
[last command start]
(你上一轮提供的命令)
[last command end]

[last search result start]
(你上一条命令的输出结果)
[last search result end]

# 输出规范 (你必须严格遵循此结构，并以中文回复)

你对问题的分析，以及下一步的搜索计划。

[why search these words start]
解释你选择这些搜索词的理由，以便用户能理解你的计划。
[why search these words end]

[command start]
要执行的单行命令。
[command end]

[problem solved start]
如果用户需求已完全满足，无需更多搜索，则填 `yes`。否则，填 `no`。
[problem solved end]

[conclusion start]
根据“状态管理”指南，总结你本轮的发现。这是你进入下一轮的记忆。
[conclusion end]
"""

SUMMARY_PROMPT = """
# 任务：日志分析总结报告

你是一位顶级的软件工程师和日志分析专家。请根据以下多轮搜索的完整历史记录，为用户生成一份详细的分析报告。

## 报告要求：
1.  **问题概述**: 清晰地总结用户的原始需求。
2.  **最终结论**: 根据搜索结果，明确回答用户的问题或给出最终的分析结论。如果问题未完全解决，请说明当前进展和下一步建议。
3.  **分析过程**: 详细描述你是如何通过多轮搜索逐步定位问题的。解释每一轮搜索的逻辑、为什么选择特定的关键词，以及如何根据上一轮的结果调整下一步的搜索策略。
4.  **关键日志**: 引用最重要的几条日志片段，并解释它们与问题核心的关联。
5.  **报告格式**: 使用Markdown格式，结构清晰，语言专业且易于理解。

## 搜索历史记录：
"""


@dataclass
class SearchRoundResult:
    """Represents the result of a single search round."""

    round: int
    why_search: str
    command: str
    result: str
    duration: float
    conclusion: str


@dataclass
class SearchState:
    """Holds the entire state of the search process."""

    user_query: str
    round: int = 0
    last_command: str = ""
    last_result: str = ""
    solved: bool = False
    all_results: List[SearchRoundResult] = field(default_factory=list)


@dataclass
class ModelResponse:
    """Represents the parsed response from the language model."""

    why_search: str
    command: str
    solved: bool
    conclusion: str


class TraceLogSearcher:
    def __init__(
        self,
        model_name: str = "tracelog",
        log_path: str = "trace_report.log",
        max_rounds: int = 8,
        auto_confirm: bool = False,
    ):
        self.model_name = model_name
        self.model_switch = ModelSwitch()
        self.log_path = Path(log_path)
        self.max_rounds = max_rounds
        self.state: Optional[SearchState] = None
        self.model_switch.select(model_name)
        self.auto_confirm = auto_confirm
        self.allowed_commands = ["rg", "awk", "sed", "head", "tail"]
        if not self.log_path.exists():
            raise FileNotFoundError(f"Trace log not found: {self.log_path}")

    def _build_prompt(self, user_query: str) -> str:
        """构建包含历史信息的完整提示词"""
        prompt = f"# 用户需求\n{user_query}\n\n"

        if self.state.round == 0:
            try:
                with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    if len(lines) > 200:
                        head = "".join(lines[:100])
                        tail = "".join(lines[-100:])
                        preview_title = f"## 日志文件预览 ({self.log_path.name})"
                        file_start = f"\n\n### 文件开头\n```\n{head}\n```"
                        file_end = f"\n\n### 文件结尾\n```\n{tail}\n```\n"
                        initial_context = preview_title + file_start + file_end
                        prompt += initial_context
                    else:
                        prompt += f"## 日志文件 ({self.log_path.name})\n```\n{''.join(lines)}\n```\n"
            except (IOError, UnicodeDecodeError) as e:
                prompt += f"无法读取日志文件预览: {e}\n"

        if self.state.round > 0:
            # For past rounds, show a summary to save space
            if len(self.state.all_results) > 1:
                prompt += "## 历史搜索摘要\n"
                for res in self.state.all_results[:-1]:
                    prompt += f"### 第 {res.round} 轮\n"
                    prompt += f"**分析**: {res.why_search}\n"
                    prompt += f"**命令**: `{res.command}`\n"
                    prompt += f"**结论**: {res.conclusion}\n\n"

            # For the most recent round, show full details
            last_res = self.state.all_results[-1]
            prompt += f"## 上一轮（第 {last_res.round} 轮）的详细信息\n"
            prompt += "[last command start]\n"
            prompt += last_res.command + "\n"
            prompt += "[last command end]\n\n"

            prompt += "[last search result start]\n"
            result = last_res.result
            # Truncate long results to avoid excessive prompt length
            if len(result) > 8000:
                result = result[:4000] + "\n\n... [结果过长，已截断] ...\n\n" + result[-4000:]
            prompt += result + "\n"
            prompt += "[last search result end]\n\n"

            prompt += "[conclusion start]\n"
            prompt += f"{last_res.conclusion}\n"
            prompt += "[conclusion end]\n\n"

        # Append the main instruction prompt
        main_instructions = GEMINI_PROMPT.format(log_name=shlex.quote(str(self.log_path)))
        prompt += f"\n---\n{main_instructions}"

        return prompt

    def _parse_model_response(self, response: str) -> Optional[ModelResponse]:
        """Parse the model's response to extract structured data."""

        def extract_block(tag: str, text: str) -> str:
            pattern = re.compile(rf"\[{tag} start\](.*?)\[{tag} end\]", re.DOTALL)
            match = pattern.search(text)
            return match.group(1).strip() if match else ""

        try:
            why_search = extract_block("why search these words", response)
            command_str = extract_block("command", response)
            # Clean up potential markdown code blocks
            command = re.sub(r"^\s*```(?:\w+)?\n|```\s*$", "", command_str, flags=re.MULTILINE).strip()

            solved_str = extract_block("problem solved", response).lower().strip()
            solved = solved_str == "yes"
            conclusion = extract_block("conclusion", response)

            # A valid response must have a command or be solved.
            if command or solved:
                return ModelResponse(
                    why_search=why_search or "无分析",
                    command=command,
                    solved=solved,
                    conclusion=conclusion or "无结论",
                )
            return None
        except Exception:
            return None

    def _is_command_allowed(self, command: str) -> bool:
        """Check if all parts of a piped command are in the whitelist."""
        if not command.strip():
            return False
        try:
            # Split the command by pipes
            segments = command.split("|")
            for segment in segments:
                if not segment.strip():
                    return False  # Empty segment like `cmd || cmd`
                # Use shlex to correctly handle quotes
                tokens = shlex.split(segment)
                if not tokens:
                    return False  # Segment with only whitespace
                cmd_executable = tokens[0]
                if cmd_executable not in self.allowed_commands:
                    console.print(
                        f"[bold red]错误: 命令 '{cmd_executable}' 不在允许的列表中: {self.allowed_commands}[/bold red]"
                    )
                    return False
            return True
        except ValueError as e:
            # shlex.split can fail on unclosed quotes
            console.print(f"[bold red]命令语法错误: {e}[/bold red]")
            return False

    def _execute_shell_command(self, command: str) -> Tuple[bool, str, float]:
        """Safely execute a one-liner shell command and return the result."""
        if not self._is_command_allowed(command):
            return False, f"命令 '{command}' 包含不允许的程序。", 0.0

        start_time = time.time()
        try:
            # Use a temporary script to handle pipes and ensure safety
            with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".sh", encoding="utf-8") as tmp_script:
                tmp_script.write("#!/bin/bash\n")
                tmp_script.write("set -o pipefail\n")
                tmp_script.write(command)
                script_path = tmp_script.name

            os.chmod(script_path, 0o755)

            process = subprocess.run(
                ["/bin/bash", script_path],
                capture_output=True,
                text=True,
                check=False,  # We check returncode manually
                cwd=self.log_path.parent,
                encoding="utf-8",
                errors="ignore",
            )

            os.unlink(script_path)
            end_time = time.time()
            duration = end_time - start_time

            if process.returncode != 0:
                # Combine stdout and stderr for better error context
                error_message = f"命令执行失败，返回码: {process.returncode}\n"
                if process.stdout:
                    error_message += f"--- STDOUT ---\n{process.stdout.strip()}\n"
                if process.stderr:
                    error_message += f"--- STDERR ---\n{process.stderr.strip()}\n"
                return True, error_message.strip(), duration

            output = process.stdout.strip()
            if not output:
                output = "未找到匹配结果。"

            return True, output, duration

        except Exception as e:
            end_time = time.time()
            return False, f"执行命令时发生意外错误: {str(e)}", end_time - start_time

    def _update_state(self, model_response: ModelResponse, result: str, duration: float):
        """Updates the search state."""
        self.state.round += 1
        self.state.last_command = model_response.command
        self.state.last_result = result
        self.state.solved = model_response.solved
        self.state.all_results.append(
            SearchRoundResult(
                round=self.state.round,
                why_search=model_response.why_search,
                command=model_response.command,
                result=result,
                conclusion=model_response.conclusion,
                duration=duration,
            )
        )

    def _generate_summary_prompt(self, user_query: str, results: List[SearchRoundResult]) -> str:
        """Builds the prompt for generating the final summary report."""
        history = f"**用户原始需求**: {user_query}\n\n"
        for result in results:
            history += f"### 第 {result.round} 轮\n"
            history += f"**搜索原因**: {result.why_search}\n"
            history += f"**执行的命令**: `{result.command}`\n"
            history += f"**结论**: {result.conclusion}\n"
            # Limit the length of each round's result to avoid an overly long prompt
            result_text = result.result
            if len(result_text) > 2000:
                result_text = result_text[:1000] + "\n...[结果截断]...\n" + result_text[-1000:]
            history += f"**搜索结果摘要**:\n```\n{result_text}\n```\n\n"

        return f"{SUMMARY_PROMPT}\n{history}"

    def summarize_results(self, user_query: str, results: List[SearchRoundResult]) -> str:
        """Calls the LLM to generate a final analysis report summary."""
        if not results:
            return "没有搜索记录，无法生成总结。"

        console.print("\n[bold blue]正在生成最终的分析报告总结...[/bold blue]")
        prompt = self._generate_summary_prompt(user_query, results)

        # Use a different model or settings for summarization if needed
        summary_response = self.model_switch.query(self.model_name, prompt, stream=True)
        return summary_response

    def _get_and_parse_model_response(self) -> Optional[ModelResponse]:
        """Queries the model, parses the response, and handles retries."""
        prompt = self._build_prompt(self.state.user_query)
        response_text = self.model_switch.query(self.model_name, prompt, stream=True)
        model_response = self._parse_model_response(response_text)

        if model_response:
            return model_response

        # Handle unparseable response
        console.print("\n[bold red]模型未能生成有效的、可解析的响应。[/bold red]")
        console.print("[bold yellow]原始响应:[/bold yellow]")
        console.print(Markdown(f"```markdown\n{response_text}\n```"))
        # In a real scenario, you might add retry logic here. For now, we abort.
        return None

    def search(self, user_query: str) -> List[SearchRoundResult]:
        """Executes the multi-round search process."""
        console.print(f"[bold green]开始分析: {user_query}[/bold green]")

        if not self._check_rg_exists():
            console.print(
                "[bold red]错误: 'rg' (ripgrep) 命令未找到。请先安装 ripgrep 并确保它在您的 PATH 中。[/bold red]"
            )
            return []

        self.state = SearchState(user_query=user_query)

        while self.state.round < self.max_rounds and not self.state.solved:
            console.print(f"\n[bold magenta]--- 第 {self.state.round + 1}/{self.max_rounds} 轮 ---[/bold magenta]")

            model_response = self._get_and_parse_model_response()

            if not model_response:
                console.print("[bold red]无法从模型获取有效指令，搜索中止。[/bold red]")
                break

            if model_response.solved:
                console.print("[bold green]模型判断问题已解决。[/bold green]")
                self.state.solved = True
                # Even if solved, we should record the final conclusion
                self._update_state(model_response, "问题已解决，无执行结果。", 0.0)
                break

            command = model_response.command
            console.print("\n[bold blue]模型建议的分析步骤:[/bold blue]")
            console.print(f"  [cyan]分析:[/cyan] {model_response.why_search}")
            console.print(f"  [cyan]命令:[/cyan] [yellow]{command}[/yellow]")

            if not self.auto_confirm:
                action = console.input("请确认操作: ([y]es/n/e)dit/a)bort: ").lower().strip()
                if action in ("n", "a", "abort"):
                    console.print("[red]用户取消，搜索中止。[/red]")
                    break
                elif action in ("e", "edit"):
                    command = console.input(f"  [cyan]编辑命令:[/cyan] ").strip()
                    if not command:
                        console.print("[red]无有效命令，搜索中止。[/red]")
                        break
                    model_response.command = command  # Update the command to be executed

            success, result, duration = self._execute_shell_command(command)

            console.print(f"\n[bold blue]命令执行结果 ({duration:.2f}s):[/bold blue]")
            result_summary = result
            if len(result_summary) > 1000:
                result_summary = result_summary[:500] + "\n...\n" + result_summary[-500:]
            console.print(Markdown(f"```\n{result_summary}\n```"))

            self._update_state(model_response, result, duration)

        return self.state.all_results

    def generate_report(
        self,
        user_query: str,
        results: List[SearchRoundResult],
        output_path: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Path:
        """Generates a search report."""
        if not output_path:
            output_dir = Path("doc") / "tracelog_search"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            safe_query = re.sub(r"[\W_]+", "_", user_query.strip())[:50]
            output_path = output_dir / f"report_{timestamp}_{safe_query}.md"
        else:
            output_path = Path(output_path)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# Trace Log 分析报告\n\n")
            f.write(f"**查询**: `{user_query}`\n\n")
            status = "已解决" if self.state.solved else f"未解决 (已达最大轮次 {self.max_rounds})"
            f.write(f"**最终状态**: {status}\n\n")

            if summary:
                f.write("## 智能总结\n\n")
                f.write(summary)
                f.write("\n\n---\n\n")

            f.write("## 详细搜索过程\n\n")
            for result in results:
                f.write(f"### 第 {result.round} 轮\n\n")
                f.write(f"**分析与理由**:\n\n> {result.why_search}\n\n")
                f.write(f"**执行命令**:\n```bash\n{result.command}\n```\n\n")
                f.write(f"**执行耗时**: {result.duration:.2f} 秒\n\n")
                f.write(f"**本轮结论 (模型记忆)**:\n\n> {result.conclusion}\n\n")
                f.write(f"**搜索结果**:\n```log\n{result.result}\n```\n\n")
                f.write("---\n\n")

            f.write(f"*报告生成于: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n")

        return output_path

    def _check_rg_exists(self) -> bool:
        """Checks if the 'rg' command exists."""
        try:
            subprocess.run(["rg", "--version"], capture_output=True, check=True, text=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False


def parse_arguments():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="使用LLM进行智能Trace Log分析的工具", formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("query", nargs="+", help="您的分析需求，例如: '找出导致请求超时的原因'")
    parser.add_argument("-m", "--model", type=str, default="deepseek-r1", help="指定使用的LLM模型")
    parser.add_argument("-l", "--log-path", type=str, default="trace_report.log", help="要分析的trace log文件路径")
    parser.add_argument("-r", "--max-rounds", type=int, default=8, help="最大搜索轮次")
    parser.add_argument("-o", "--output", type=str, default=None, help="指定报告输出路径 (可选)")
    parser.add_argument("-y", "--auto-confirm", action="store_true", help="自动确认并执行模型建议的命令，无须手动确认")
    return parser.parse_args()


def main():
    args = parse_arguments()
    user_query = " ".join(args.query)

    try:
        searcher = TraceLogSearcher(
            model_name=args.model,
            log_path=args.log_path,
            max_rounds=args.max_rounds,
            auto_confirm=args.auto_confirm,
        )

        results = searcher.search(user_query)
        summary = None
        if results:
            if not args.auto_confirm:
                confirm = console.input("\n是否需要LLM对整个过程进行总结? ([y]/n): ").lower().strip()
                if confirm != "n":
                    summary = searcher.summarize_results(user_query, results)
            else:
                summary = searcher.summarize_results(user_query, results)

        if searcher.state:
            report_path = searcher.generate_report(user_query, results, args.output, summary)
            console.print(f"\n[bold green]分析报告已保存至: {report_path.resolve()}[/bold green]")
        else:
            console.print("\n[bold yellow]未进行任何搜索，不生成报告。[/bold yellow]")

        if searcher.state and searcher.state.solved:
            console.print(Markdown("# ✅ 分析完成: 问题已解决"))
        else:
            console.print(Markdown("# ⚠️ 分析结束: 可能未完全解决"))
            console.print("建议: 增加搜索轮次 (--max-rounds), 或提供更具体的初始问题。")

    except FileNotFoundError as e:
        console.print(f"[bold red]文件错误: {e}[/bold red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]发生未知错误: {e}[/bold red]")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    console.print("[bold blue]程序执行完毕。[/bold blue]")


if __name__ == "__main__":
    main()
