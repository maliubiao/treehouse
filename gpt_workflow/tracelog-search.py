import argparse
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

MAIN_PROMPT = """
你需要根据用户的需求，决定要执行什么命令处理日志，以获取需要的上下文，你可能需要执行多次命令逼近目标。
有一份很大的trace log, 包括程序每一行执行了什么东西， 你需要搜索这个tracelog, 获取上下文，满足用户的需求，
获取的上下文不能太大，以免超过你的上下文总长度。
每次返回一个的命令过来，请求用正则表达式搜索日志，然后这个命令的执行结果会在下一次反馈给你。
命令中可以使用rg, awk, sed, head tail, 但必须是one liner。
使用rg的时候要求它的输出带行号, sed -n '10,20p' filename 可以获取行号范围的文本, awk 'NR>=10 && NR<=20' filename 也可以。
用户可能会提供一个目录树，或者终端的程序输出信息，或者其它相关信息， 都可以做为搜索的依据，最主要的还是用户的需求描述。
通常来说需要把用户需求转成英文，因为源代码是英文写的，以确认合适的搜索条件。
要搜索的log名为{log_name}，
你上次搜索到什么东西，会作为附件给你，根据它，规划下一次搜索，逼近目标，
当需求已经满足，不再需要搜索内容你需要回复，`yes`，
关键字的范围显示控制在30行以上, 写的不够模糊的正则很难收获很好的结果，能搜索到信息总比啥也搜索不好。
禁止使用跨行正则, 禁用使用-A -B -n -e 之外的rg选项。
你必须在结论中([conclusion start])记录你在日志里搜索到重要信息，要不然下次就看不到它们了，以指导下一次如何搜索日志，
关于日志格式的重要信息，日志中涉及到的术语，文件名，函数名, 变量名, 典型的日志行样本, 至少记录20条这些内容，如果不是已经记录的话, 关
内容以中文回复。

输入解读:
[last command start]
command 
[last command end]

[last search result start]
command's search result
[last search result end]

输出规范:

你对问题的分析，决定搜索哪些词

[why search these words start] 
为什么要搜索这些词，让用户能理解你的目的
[why search these words end] 

[command start]
command to search
[command end]

[problem solved start]
如果不需要更多次搜索，设为yes,不然设为no
[problem solved end]

[conclusion start]
本轮的结论，你找到了什么，下一步做什么
[conclusion end]

"""

MINI_PROMPT = """
你需要通过多次执行命令行工具（rg/awk/sed/head/tail）搜索大型跟踪日志文件 `{log_name}`，逐步逼近用户需求目标。每次返回**单个单行命令**，当获取到足够上下文时回复`yes`。

**核心约束**
1. 输出限制：每次搜索结果控制在30-50行（避免上下文超长）
2. 命令规范：
   - 必须为单行命令（one liner）
   - 使用`rg`时必须包含`-n`显示行号（例：`rg -n 'pattern'`）
   - 允许范围提取（例：`sed -n '10,20p'` 或 `awk 'NR>=10&&NR<=20'`）
   - 禁用跨行正则和复杂选项（仅允许rg的`-A/-B/-e`）
3. 搜索策略：
   - 优先使用英文关键词（源代码为英文）
   - 正则表达式需适度模糊（避免过度精确导致零结果）
   - 基于上次结果迭代优化搜索
4. 结论要求：
   - **必须用中文记录**
   - 包含至少20条关键信息（术语/文件名/函数名/变量名）
   - 包含5个以上典型日志行样本
   - 记录日志格式特征（时间戳、消息结构等）

**输入数据**
[last command start]
[上次执行的命令]
[last command end]

[last search result start]
[上次命令的搜索结果]
[last search result end]

**输出规范**
1. 问题分析：解读用户需求与日志特征的关联性
2. 搜索词说明：解释关键词选择逻辑（中英对照）
3. 单行命令：可直接执行的搜索命令
4. 状态标记：是否需要继续搜索
5. 结论记录：
   - 累计发现的关键信息（≥20条）
   - 新发现的日志结构特征
   - 典型日志行样本（≥5个）
   - 明确的后续计划

**严格遵循的回复格式**
[问题分析]
当前搜索意图分析...

[why search these words start]
1. 选择关键词A的原因：... (Reason for choosing keyword A: ...)
2. 选择关键词B的原因：... (Reason for choosing keyword B: ...)
[why search these words end]

[command start]
[单行命令，如：rg -n 'error|fail' {log_name} | head -30]
[command end]

[problem solved start]
[yes/no]
[problem solved end]

[conclusion start]
## 关键信息记录（累计≥20条）
1. 日志结构：时间戳格式[HH:mm:ss.SSS]
2. 关键术语：
   - 函数名: `parse_request()`, `handle_timeout()`
   - 文件名: `network.c`, `utils.h`
   - 变量名: `retry_count`, `max_buffer`
   - 错误码: `ERR_TIMEOUT=0x5`, `ERR_MEMORY=0x7`
   - 模块名: `NETWORK`, `STORAGE`
3. 典型样本：
   [15:32:45.123] INFO: Loading module: NETWORK
   [15:33:01.456] ERROR: Invalid input at parse_request():102
   [15:33:05.789] DEBUG: Retry count: 3, max_buffer=4096
   [15:33:10.234] WARN: Memory threshold exceeded (75%)
   [15:33:15.678] TRACE: Entering handle_timeout()
## 后续计划
1. 搜索`NETWORK`模块的错误日志
2. 检查`handle_timeout()`相关调用链
[conclusion end]
"""

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
        prompt = f"# 用户需求\n{user_query}\n\n"  # 使用传入的user_query参数

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
            except (IOError, UnicodeDecodeError) as e:  # 更具体的异常捕获
                prompt += f"无法读取日志文件预览: {e}\n"

        if self.state.round > 0:
            prompt += "## 搜索历史\n"
            # History of all rounds except the last one
            for res in self.state.all_results[:-1]:
                prompt += f"### 第 {res.round} 轮\n"
                prompt += "[why search these words start]\n"
                prompt += f"{res.why_search}\n"
                prompt += "[why search these words end]\n\n"
                prompt += "[command start]\n"
                prompt += f"{res.command}\n"
                prompt += "[command end]\n\n"
                prompt += "[conclusion start]\n"
                prompt += f"{res.conclusion}\n"
                prompt += "[conclusion end]\n\n"

            # Last round details
            last_res = self.state.all_results[-1]
            prompt += f"## 上一轮（第 {last_res.round} 轮）的搜索与结果\n"
            prompt += "[why search these words start]\n"
            prompt += f"{last_res.why_search}\n"
            prompt += "[why search these words end]\n\n"
            prompt += "[last command start]\n"
            prompt += last_res.command + "\n"
            prompt += "[last command end]\n\n"
            prompt += "[last search result start]\n"
            result = last_res.result
            if len(result) > 65536:
                result = result[:32768] + "\n\n... [结果截断] ...\n\n" + result[-32768:]
            prompt += result + "\n"
            prompt += "[last search result end]\n\n"
            prompt += "[conclusion start]\n"
            prompt += f"{last_res.conclusion}\n"
            prompt += "[conclusion end]\n\n"
        prompt += GEMINI_PROMPT.format(log_name=str(self.log_path))
        return prompt

    def _parse_model_response(self, response: str) -> ModelResponse:
        """Parse the model's response to extract structured data."""

        def extract_block(tag: str, text: str) -> str:
            # 增强模式：兼容标签行前后的markdown标识符(**)和可选的###前缀
            pattern = re.compile(
                rf"(?:\*\*)?(?:###\s*)?\[{tag} start\](?:\*\*)?(.*?)(?:\*\*)?(?:###\s*)?\[{tag} end\](?:\*\*)?",
                re.DOTALL,
            )
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
            return ""

        why_search = extract_block("why search these words", response) or "No analysis provided"

        # 处理rg command：从代码块中提取实际命令
        command_block = extract_block("command", response)
        command = ""
        if command_block:
            # 尝试从代码块中提取命令（去除```bash等标记）
            code_match = re.search(r"```(?:bash)?\s*(.*?)\s*```", command_block, re.DOTALL)
            if code_match:
                command = code_match.group(1).strip()
            else:
                command = command_block.strip()

        solved_str = extract_block("problem solved", response).lower()
        solved = solved_str == "yes"
        conclusion = extract_block("conclusion", response) or "No conclusion provided for this round."

        return ModelResponse(why_search=why_search, command=command, solved=solved, conclusion=conclusion)

    def _is_command_allowed(self, command: str) -> bool:
        """
        Check if all parts of a piped command are in the whitelist.
        This version correctly handles pipes within quoted arguments.
        """
        try:
            tokens = shlex.split(command)
            current_segment_tokens = []

            for token in tokens:
                if token == "|":
                    if not current_segment_tokens:
                        # This means we have something like `| command` or `command || command`
                        return False

                    # Check the command in the completed segment
                    cmd_executable = current_segment_tokens[0]
                    if cmd_executable not in self.allowed_commands:
                        return False

                    # Reset for the next segment
                    current_segment_tokens = []
                else:
                    current_segment_tokens.append(token)

            # Check the last (or only) segment
            if not current_segment_tokens:
                # This could happen if the command ends with a pipe `command |`
                return False

            cmd_executable = current_segment_tokens[0]
            if cmd_executable not in self.allowed_commands:
                return False

            return True
        except ValueError:
            # shlex.split can fail on unclosed quotes (e.g., "rg 'hello")
            return False

    def _execute_shell_command(self, command: str) -> Tuple[bool, str, float]:
        """安全地执行单行shell命令并返回结果"""
        if not self._is_command_allowed(command):
            return False, f"错误: 命令 '{command}' 包含不允许的程序。只允许: {self.allowed_commands}", 0.0
        try:
            start_time = time.time()

            # 2. 创建并执行临时脚本以避免shell注入问题
            with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".sh") as tmp_script:
                tmp_script.write("#!/bin/bash\n")
                tmp_script.write("set -o pipefail\n")  # Important for getting error from any part of the pipe
                tmp_script.write(command)
                tmp_script_path = tmp_script.name

            os.chmod(tmp_script_path, 0o755)

            process = subprocess.run(
                ["bash", tmp_script_path], capture_output=True, text=True, check=False, cwd=self.log_path.parent
            )

            os.unlink(tmp_script_path)

            end_time = time.time()

            output = process.stdout.strip()

            if process.returncode != 0:
                if process.stderr:
                    if output:
                        output += "\n"
                    output += process.stderr.strip()

            if not output.strip():
                output = "未找到匹配结果"

            return True, output.strip(), end_time - start_time
        except FileNotFoundError:
            return False, "错误: 'bash' 命令未找到。请确保bash shell已安装并在您的 PATH 中。", 0.0
        except subprocess.SubprocessError as e:
            return False, f"子进程执行错误: {str(e)}", 0.0
        except OSError as e:
            return False, f"系统操作错误: {str(e)}", 0.0

    def _update_state(self, model_response: ModelResponse, command: str, result: str, duration: float):
        """更新搜索状态"""
        self.state.round += 1
        self.state.last_command = command
        self.state.last_result = result
        self.state.solved = model_response.solved
        self.state.all_results.append(
            SearchRoundResult(
                round=self.state.round,
                why_search=model_response.why_search,
                command=command,
                result=result,
                conclusion=model_response.conclusion,
                duration=duration,
            )
        )

    def _generate_summary_prompt(self, user_query: str, results: List[SearchRoundResult]) -> str:
        """为生成最终总结报告构建提示词"""
        history = f"**用户原始需求**: {user_query}\n\n"
        for result in results:
            history += f"### 第 {result.round} 轮\n"
            history += f"**搜索原因**: {result.why_search}\n"
            history += f"**执行的命令**: `{result.command}`\n"
            history += f"**结论**: {result.conclusion}\n"
            # 限制每轮结果的长度，避免prompt过长
            result_text = result.result
            if len(result_text) > 2000:
                result_text = result_text[:1000] + "\n...[结果截断]...\n" + result_text[-1000:]
            history += f"**搜索结果摘要**:\n```\n{result_text}\n```\n\n"

        return f"{SUMMARY_PROMPT}\n{history}"

    def summarize_results(self, user_query: str, results: List[SearchRoundResult]) -> str:
        """调用LLM生成最终的分析报告总结"""
        if not results:
            console.print("[bold yellow]没有搜索结果，无法生成总结报告。[/bold yellow]")
            return ""

        console.print("\n[bold blue]正在生成最终的分析报告总结...[/bold blue]")
        prompt = self._generate_summary_prompt(user_query, results)

        raw_summary_response = self.model_switch.query(self.model_name, prompt, stream=True)

        # Extract the actual summary from within the conclusion tags
        summary = self._parse_model_response(raw_summary_response).conclusion  # Re-using extract_block logic

        return summary

    def _handle_unparseable_response(self, response: str) -> Optional[Union[ModelResponse, str]]:
        """Handles cases where the model response is not as expected, interacts with the user."""
        console.print("\n[bold red]Model response could not be parsed.[/bold red]")
        console.print("[bold yellow]Original Response:[/bold yellow]")
        console.print(Markdown(f"```markdown\n{response}\n```"))

        action = console.input("Choose action: [m]anual command, [r]etry, [a]bort: ").lower().strip()

        if action == "m":
            command = console.input("Enter rg command: ").strip()
            if not command:
                console.print("[red]No command entered, aborting search.[/red]")
                return None
            return ModelResponse(
                why_search="User manual input", command=command, solved=False, conclusion="User provided manual command"
            )
        if action == "r":
            console.print("[yellow]Retrying...[/yellow]")
            return "retry"
        console.print("[red]Aborting search.[/red]")
        return None

    def _get_and_parse_model_response(self) -> Optional[Union[ModelResponse, str]]:
        """Queries the model, parses the response, and handles retries."""
        while True:
            prompt = self._build_prompt(self.state.user_query)
            print(prompt)
            response_text = self.model_switch.query(self.model_name, prompt, stream=True)
            try:
                model_response = self._parse_model_response(response_text)
                if model_response.command or model_response.solved:
                    return model_response
            except (ValueError, json.JSONDecodeError) as e:  # 更具体的异常类型
                print(f"Failed to parse model response: {e}")

            user_choice = self._handle_unparseable_response(response_text)
            if user_choice == "retry":
                continue
            return user_choice

    def _execute_and_update(self, model_response: ModelResponse) -> bool:
        """Executes the command, updates state, and prints info. Returns True to continue."""
        command = model_response.command
        console.print("\n[bold cyan]Model suggests executing:[/bold cyan]")
        console.print(f"[yellow]{command}[/yellow]")
        if not self.auto_confirm:
            confirm = console.input("Execute? ([y]/n/e)dit): ").lower().strip()

            if confirm == "n":
                console.print("[red]User cancelled execution. Aborting.[/red]")
                return False
            if confirm == "e":
                command = console.input("Enter new command: ").strip()

        if not command:
            console.print("[red]No command to execute. Aborting.[/red]")
            return False
        _, result, duration = self._execute_shell_command(command)

        self._update_state(model_response, command, result, duration)

        self._print_round_info(self.state.all_results[-1])
        return True

    def _print_round_info(self, round_result: SearchRoundResult):
        """Prints the information for a completed search round."""
        console.print("\n[bold cyan]Round {round} Search[/bold cyan]".format(round=round_result.round))
        console.print("[yellow]Reason:[/yellow] {why_search}".format(why_search=round_result.why_search))
        console.print("[yellow]Duration:[/yellow] {duration:.2f}s".format(duration=round_result.duration))
        console.print("[yellow]Command:[/yellow] {command}".format(command=round_result.command))
        console.print("[yellow]Result:[/yellow]")
        result_summary = round_result.result[:1000]
        if len(round_result.result) > 1000:
            result_summary += "\n..."
        console.print(Markdown(f"```\n{result_summary}\n```"))

    def search(self, user_query: str) -> List[SearchRoundResult]:
        """执行多轮搜索流程"""
        console.print(f"[bold green]Starting analysis for: {user_query}[/bold green]")

        # 检查rg命令是否存在
        if not self._check_rg_exists():
            console.print("[bold red]Error: 'rg' (ripgrep) not found. Please install and add to PATH.[/bold red]")
            return []

        self.state = SearchState(user_query=user_query)

        while self.state.round < self.max_rounds and not self.state.solved:
            model_response = self._get_and_parse_model_response()

            if model_response is None:
                break

            if isinstance(model_response, str) and model_response == "retry":
                continue

            if model_response.solved:
                console.print("[bold green]Model indicates problem is solved.[/bold green]")
                self.state.solved = True
                break

            if not self._execute_and_update(model_response):
                break

        return self.state.all_results

    def generate_report(
        self, results: List[SearchRoundResult], output_path: Optional[str] = None, summary: Optional[str] = None
    ) -> Path:
        """生成搜索报告"""
        if not output_path:
            output_dir = Path("doc") / "tracelog_search"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            output_path = output_dir / f"tracelog_search_{timestamp}.md"
        else:
            output_path = Path(output_path)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# Trace Log 搜索报告\n\n")
            f.write(f"**用户需求**: {self.state.user_query}\n\n")
            f.write(
                f"**解决状态**: {'已解决' if self.state.solved else f'未解决（达到最大轮次 {self.max_rounds}）'}\n\n"
            )

            if summary:
                f.write("## 最终分析总结\n\n")
                f.write(summary)
                f.write("\n\n---\n\n")

            for result in results:
                f.write("## 详细搜索过程\n\n")
                f.write(f"## 第 {result.round} 轮搜索\n\n")
                f.write(f"### 搜索原因\n{result.why_search}\n\n")
                f.write(f"### 执行命令\n```bash\n{result.command}\n```\n\n")
                f.write(f"### 耗时\n{result.duration:.2f} 秒\n\n")
                f.write(f"### 搜索结果\n```\n{result.result}\n```\n\n")

            f.write(f"---\n*生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n")

        return output_path

    def _check_rg_exists(self) -> bool:
        """检查rg命令是否存在"""
        try:
            subprocess.run(["rg", "--version"], capture_output=True, check=True)
            return True
        except FileNotFoundError:
            return False


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Trace Log搜索分析工具", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("query", nargs="+", help="搜索需求描述")
    parser.add_argument("-m", "--model", type=str, default="deepseek-r1", help="使用的LLM模型名称")
    parser.add_argument("-l", "--log-path", type=str, default="trace_report.log", help="trace log文件路径")
    parser.add_argument("-r", "--max-rounds", type=int, default=8, help="最大搜索轮次")
    parser.add_argument("-o", "--output", type=str, default=None, help="报告输出路径")
    parser.add_argument("--auto-confirm", action="store_true", help="自动确认并执行建议的命令。")
    return parser.parse_args()


def main():
    args = parse_arguments()
    user_query = " ".join(args.query)

    try:
        # 初始化搜索器
        searcher = TraceLogSearcher(
            model_name=args.model, log_path=args.log_path, max_rounds=args.max_rounds, auto_confirm=args.auto_confirm
        )

        # 执行搜索
        results = searcher.search(user_query)

        # 新增：生成总结报告
        summary = None
        if results:
            confirm_summary = console.input("\n是否需要LLM对整个过程进行总结并生成报告? ([y]/n): ").lower().strip()
            if confirm_summary != "n":
                summary = searcher.summarize_results(user_query, results)

        # 生成报告
        report_path = searcher.generate_report(results, args.output, summary)
        console.print(f"\n[bold green]搜索报告已保存至: {report_path}[/bold green]")

        # 显示最终状态
        if searcher.state and searcher.state.solved:
            console.print(Markdown("# ✅ 搜索完成: 问题已解决"))
            if results:
                console.print(Markdown(f"最终搜索结果:\n```\n{results[-1].result}\n```"))
        else:
            console.print(Markdown("# ⚠️ 搜索完成: 达到最大轮次但问题未完全解决"))
            console.print("建议尝试以下方法:")
            console.print("- 提供更多关于问题的细节")
            console.print("- 修改搜索关键词")
            console.print("- 增加搜索轮次 (使用 --max-rounds 参数)")

    except FileNotFoundError as e:
        console.print(f"[bold red]错误: {str(e)}[/bold red]")
    except Exception as e:
        console.print(f"[bold red]未处理的错误: {str(e)}[/bold red]")
        raise
    finally:
        # 确保程序正常退出，即使在异常情况下
        console.print("[bold blue]程序执行完毕。[/bold blue]")
        sys.exit(0)


if __name__ == "__main__":
    main()
