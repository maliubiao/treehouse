#!/usr/bin/env python
"""
Pylint错误自动修复工具

该模块提供解析Pylint输出、关联错误到代码符号、自动生成修复补丁的功能
包含结构化错误表示、智能分组、模型交互等功能
"""

import re
import subprocess
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

import llm_query
from llm_query import (
    CmdNode,
    ModelSwitch,
    generate_patch_prompt,
    process_patch_response,
)
from tree_libs.app import (
    FileSearchResult,
    FileSearchResults,
    MatchResult,
)
from tree_libs.ast import (
    ParserLoader,
    ParserUtil,
)


class LintResult(BaseModel):
    """Structured representation of pylint error"""

    file_path: str
    line: int
    column_range: tuple[int, int]
    code: str
    message: str
    original_line: str

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "LintResult":
        return cls.model_validate_json(json_str)

    @property
    def full_message(self) -> str:
        """Format message with code for display"""
        return f"{self.code}: {self.message}"


class LintParser:
    """
    Parse pylint output into structured LintResult objects
    Example input format: "tree.py:1870:0: C0325: Unnecessary parens after 'not' keyword"
    """

    _LINE_PATTERN = re.compile(
        r"^(?P<path>.+?):"  # File path
        r"(?P<line>\d+):"  # Line number
        r"(?P<column>\d+): "  # Column start
        r"(?P<code>\w+):\s*"  # Lint code with colon
        r"(?P<message>.+)$"  # Error message
    )

    @classmethod
    def parse(cls, raw_output: str) -> list[LintResult]:
        """Parse raw pylint output into structured results"""
        results = []
        for line in raw_output.splitlines():
            if not line.strip() or line.startswith("***"):
                continue

            if match := cls._LINE_PATTERN.match(line):
                result = cls._create_lint_result(match)
                if result:
                    results.append(result)
        return results

    @classmethod
    def _create_lint_result(cls, match: re.Match) -> LintResult | None:
        """Create LintResult from regex match object"""
        groups = match.groupdict()
        message = groups["message"].strip()
        column = int(groups["column"])

        start_col, end_col = cls._parse_column_range(message, column)
        file_path = groups["path"]
        line_num = int(groups["line"])
        original_line = cls._read_source_line(file_path, line_num)

        return LintResult(
            file_path=file_path,
            line=line_num,
            column_range=(start_col, end_col),
            code=groups["code"],
            message=message,
            original_line=original_line,
        )

    @classmethod
    def _parse_column_range(cls, message: str, default_col: int) -> tuple[int, int]:
        """Parse column range from message or use default column"""
        if column_range_match := re.search(r"column (\d+)-(\d+)", message):
            return (int(column_range_match.group(1)), int(column_range_match.group(2)))
        return (default_col, default_col)

    @classmethod
    def _read_source_line(cls, file_path: str, line_num: int) -> str:
        """Read original source line from file"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                file_lines = f.readlines()
                if 0 < line_num <= len(file_lines):
                    return file_lines[line_num - 1].rstrip("\n")
        except OSError as e:
            print(f"Error reading {file_path}:{line_num} - {str(e)}")
        return ""


class LintReportFix:
    """根据Lint检查结果自动生成修复补丁"""

    _MAX_CONTEXT_SPAN = 100  # 最大上下文跨度行数

    def __init__(self, model_switch: ModelSwitch = None):
        self.model_switch = model_switch or ModelSwitch()

    def _build_prompt(self, symbol: Dict, symbol_map: Dict) -> str:
        """构建合并后的提示词模板"""
        group: list[LintResult] = symbol.get("own_errors", [])
        errors_desc = "\n\n".join(
            f"错误代码: {res.code}\n描述: {res.message}\n原代码行: {res.original_line}" for res in group
        )
        base_prompt = generate_patch_prompt(
            CmdNode(command="symbol", args=[symbol["name"]]),
            symbol_map,
            patch_require=True,
        )

        return f"{base_prompt}\n{errors_desc}\n不破坏编程接口，避免无法通过测试\n"

    def fix_symbol(self, symbol: Dict, symbol_map: Dict) -> None:
        """生成批量修复建议"""
        prompt = self._build_prompt(symbol, symbol_map)
        print(prompt)
        response = self.model_switch.query("coder", prompt)
        process_patch_response(
            response,
            symbol_map,
            auto_commit=False,
            auto_lint=False,
        )


class PylintFixer:
    """自动化修复Pylint报告的主处理器"""

    def __init__(
        self,
        linter_log_path: str,
        auto_apply: bool = False,
        root_dir: Optional[Path] = None,
        git_hint: str = "",
    ):
        self.log_path = Path(linter_log_path)
        self.results: list[LintResult] = []
        self.file_groups: dict[str, list[LintResult]] = {}
        self.fixer = LintReportFix()
        self.auto_apply = auto_apply
        self.root_dir = root_dir if root_dir is not None else Path.cwd().resolve()
        self.git_hint = git_hint

    def load_and_validate_log(self) -> None:
        """加载并验证日志文件或从git命令获取日志"""
        files_result = None
        if not self.log_path and not self.git_hint:
            self.git_hint = "auto"

        if self.git_hint:
            try:
                if self.git_hint == "auto":
                    files_result = subprocess.run(
                        ["git", "ls-files", "*.py"],
                        capture_output=True,
                        text=True,
                        cwd=self.root_dir,
                        check=True,
                    )
                elif self.git_hint == "stage":
                    files_result = subprocess.run(
                        ["git", "diff", "--cached", "--name-only", "--", "*.py"],
                        capture_output=True,
                        text=True,
                        cwd=self.root_dir,
                        check=True,
                    )

                # 准备pylint参数
                pylint_args = []
                pylintrc_path = self.root_dir / ".pylintrc"
                if pylintrc_path.exists():
                    pylint_args.extend(["--rcfile", str(pylintrc_path)])

                # 一次性对所有文件执行pylint
                result = subprocess.run(
                    ["pylint", *pylint_args, *files_result.stdout.splitlines()],
                    capture_output=True,
                    text=True,
                    cwd=self.root_dir,
                    check=False,
                )
                log_content = result.stdout
                self.results = LintParser.parse(log_content)

            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Git命令执行失败: {e.stderr}") from e
            except Exception as e:
                raise RuntimeError(f"执行过程中出错: {str(e)}") from e

        else:
            if not self.log_path.is_file():
                raise FileNotFoundError(f"日志文件 '{self.log_path}' 不存在或不是文件")

            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    log_content = f.read()
                self.results = LintParser.parse(log_content)
            except OSError as e:
                raise RuntimeError(f"读取日志文件失败: {e}") from e

    def group_results_by_file(self) -> None:
        """按文件路径对结果进行分组"""
        self.file_groups = defaultdict(list)
        for res in self.results:
            self.file_groups[res.file_path].append(res)

    def _process_symbol_group(self, symbol: Dict, symbol_map: Dict) -> None:
        """处理单个符号的错误组"""
        group = symbol.get("own_errors", [])
        if not group:
            return

        print(f"\n当前错误组信息（共 {len(group)} 个错误）:")
        for idx, result in enumerate(group, 1):
            print(f"错误 {idx}: {result.file_path} 第 {result.line} 行 : {result.message}")

        if not self.auto_apply:
            response = input("是否修复这组错误？(y/n): ").strip().lower()
            if response != "y":
                print("跳过这组错误")
                return

        try:
            self.fixer.fix_symbol(symbol, symbol_map)
        except (RuntimeError, ValueError, IOError) as e:  # 更具体的异常类型
            traceback.print_exc()
            print("无法自动修复当前错误组", str(e))
        except Exception as e:  # 保留最外层Exception捕获但添加详细日志
            traceback.print_exc()
            print("发生未预期的错误:", str(e))
            raise  # 重新抛出以便上层处理

    def _get_symbol_locations(self, file_path: str) -> list[tuple[int, int]]:
        """获取符号定位信息"""
        return [(line.line, line.column_range[0]) for line in self.file_groups[file_path]]

    def _associate_errors_with_symbols(
        self, file_path: str, parser_util: ParserUtil, code_map: Dict, locations: List[Tuple[int, int]]
    ) -> Dict[str, Dict]:
        """关联错误信息到符号"""
        symbol_map = parser_util.find_symbols_for_locations(code_map, locations, max_context_size=1024 * 1024)
        new_symbol_map = {}
        for name, symbol in symbol_map.items():
            symbol["original_name"] = name
            symbol["name"] = f"{file_path}/{name}"
            new_symbol_map[symbol["name"]] = symbol
            symbol["block_content"] = symbol["code"].encode("utf8")
            symbol["file_path"] = file_path
            symbol["own_errors"] = [
                lint_error
                for lint_error in self.file_groups[file_path]
                if any(lint_error.line == line for line, _ in symbol["locations"])
            ]
        return new_symbol_map

    def _group_symbols_by_token_limit(self, symbol_map: Dict) -> list[list]:
        """按token限制分组符号"""
        groups = []
        current_group = []
        current_size = 0
        for symbol in symbol_map.values():
            symbol_size = len(symbol["code"])
            if current_size + symbol_size > llm_query.GLOBAL_MODEL_CONFIG.max_context_size:
                groups.append(current_group)
                current_group = [symbol]
                current_size = symbol_size
            else:
                current_group.append(symbol)
                current_size += symbol_size
        if current_group:
            groups.append(current_group)
        return groups

    def update_symbol_map(self, file_path: str) -> Tuple[ParserUtil, Dict]:
        """更新符号映射"""
        parser_loader = ParserLoader()
        parser_util = ParserUtil(parser_loader)
        _, code_map = parser_util.get_symbol_paths(file_path)
        return parser_util, code_map

    def _process_symbols_for_file(self, file_path: str) -> None:
        """处理单个文件的所有符号"""
        parser_util, code_map = self.update_symbol_map(file_path)
        locations = self._get_symbol_locations(file_path)
        symbol_map = self._associate_errors_with_symbols(file_path, parser_util, code_map, locations)
        symbol_groups = self._group_symbols_by_token_limit(symbol_map)
        for group in symbol_groups:
            for symbol in group:
                self._process_symbol_group(symbol, symbol_map)
                # 更新后重新获取符号映射
                parser_util, code_map = self.update_symbol_map(file_path)

    def execute(self) -> None:
        """执行完整的修复流程"""
        self.load_and_validate_log()
        if not self.results:
            print("未发现可修复的错误")
            return
        ModelSwitch().select("coder")
        self.group_results_by_file()

        for file_path in self.file_groups:
            self._process_symbols_for_file(file_path)

        print("\n修复流程完成")


def pylint_fix(pylint_log: str) -> None:
    """修复入口函数"""
    if pylint_log in ("auto", "stage"):
        fixer = PylintFixer("", auto_apply=True, git_hint=pylint_log)
    else:
        fixer = PylintFixer(str(pylint_log), auto_apply=True)
    fixer.execute()


def lint_to_search_protocol(lint_results: list[LintResult]) -> FileSearchResults:
    """Convert lint results to search protocol format retaining positional data"""
    file_groups: dict[str, list[MatchResult]] = defaultdict(list)
    for lint_res in lint_results:
        file_groups[lint_res.file_path].append(
            MatchResult(
                line=lint_res.line,
                column_range=lint_res.column_range,
                text="",  # Text field not used in positional search
            )
        )
    return FileSearchResults(
        results=[FileSearchResult(file_path=file_path, matches=matches) for file_path, matches in file_groups.items()]
    )
