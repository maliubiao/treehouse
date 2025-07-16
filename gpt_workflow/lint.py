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

from llm_query import (
    GPT_FLAG_PATCH,
    GPT_FLAGS,
    GPT_SYMBOL_PATCH,
    GPT_VALUE_STORAGE,
    ModelSwitch,
    PatchPromptBuilder,
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

    def __init__(self, model_switch: Optional[ModelSwitch] = None) -> None:
        self.model_switch = model_switch or ModelSwitch()

    def fix_symbol(self, symbol: Dict, symbol_map: Dict) -> None:
        """使用PatchPromptBuilder生成并应用修复建议"""
        # 1. 从lint错误为AI准备用户需求
        group: list[LintResult] = symbol.get("own_errors", [])
        errors_desc = "\n".join(
            f"- (代码: {res.code}): {res.message}\n  在行: {res.original_line.strip()}" for res in group
        )

        user_requirement = (
            f"请根据以下pylint错误信息，修复符号 '{symbol['name']}'。\n\n"
            f"待修复的错误：\n"
            f"-------------------\n"
            f"{errors_desc}\n"
            f"-------------------\n\n"
            "修复要求：\n"
            f"1. 必须只修改目标符号 `{symbol['name']}` 的代码。\n"
            "2. 必须保持函数/方法的签名不变，以确保API兼容性。\n"
            "3. 修复代码以解决上述所有lint问题。\n"
        )

        # 2. 设置并使用PatchPromptBuilder
        GPT_FLAGS[GPT_FLAG_PATCH] = True
        max_tokens = (
            self.model_switch.current_config.max_context_size * 3 if self.model_switch.current_config else 8000 * 3
        )

        builder = PatchPromptBuilder(use_patch=True, symbols=[], tokens_left=max_tokens)
        builder.process_search_results(symbol_map)

        # 3. 构建提示并查询模型
        prompt = builder.build(user_requirement=user_requirement)
        print(prompt)  # 用于调试，可观察最终提示

        response = self.model_switch.query("coder", prompt, stream=True)

        # 4. 处理响应并应用补丁
        process_patch_response(
            response,
            GPT_VALUE_STORAGE[GPT_SYMBOL_PATCH],
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
        max_file_fix_iterations: int = 5,  # Add max iterations to prevent infinite loops
    ):
        self.log_path = Path(linter_log_path) if linter_log_path else None
        self.results: list[LintResult] = []
        self.file_groups: dict[str, list[LintResult]] = {}
        self.fixer = LintReportFix()
        self.auto_apply = auto_apply
        self.root_dir = root_dir if root_dir is not None else Path.cwd().resolve()
        self.git_hint = git_hint
        self.max_file_fix_iterations = max_file_fix_iterations

    def _get_pylint_args(self) -> List[str]:
        """获取pylint的配置参数"""
        args: List[str] = []
        pylintrc_path = self.root_dir / ".pylintrc"
        if pylintrc_path.exists():
            args.extend(["--rcfile", str(pylintrc_path)])
        return args

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

                pylint_args = self._get_pylint_args()
                pylint_files_relative = list(dict.fromkeys(files_result.stdout.splitlines())) if files_result else []
                if not pylint_files_relative:
                    log_content = ""
                else:
                    pylint_files_absolute = [str(self.root_dir / f) for f in pylint_files_relative]
                    result = subprocess.run(
                        ["pylint", *pylint_args, *pylint_files_absolute],
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

        elif self.log_path:
            if not self.log_path.is_file():
                raise FileNotFoundError(f"日志文件 '{self.log_path}' 不存在或不是文件")

            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    log_content = f.read()
                self.results = LintParser.parse(log_content)
                # Ensure all paths are absolute, resolving against root_dir
                for r in self.results:
                    if not Path(r.file_path).is_absolute():
                        r.file_path = str((self.root_dir / r.file_path).resolve())
            except OSError as e:
                raise RuntimeError(f"读取日志文件失败: {e}") from e

    def group_results_by_file(self) -> None:
        """按文件路径对结果进行分组"""
        self.file_groups = defaultdict(list)
        for res in self.results:
            self.file_groups[res.file_path].append(res)

    def _select_files_interactively(self) -> List[str]:
        """
        在'stage'模式下，以交互方式提示用户选择要修复的文件。

        显示带有pylint错误的文件列表，并要求用户做出选择。

        Returns:
            用户选择要修复的文件的路径列表。
        """
        if self.git_hint != "stage" or not self.file_groups:
            return list(self.file_groups.keys())

        print("\n--- Pylint Fixer: Interactive File Selection (Stage Mode) ---")
        print("The following staged files have linting errors:")

        indexed_files = list(self.file_groups.keys())

        for i, file_path in enumerate(indexed_files):
            errors = self.file_groups[file_path]
            error_count = len(errors)
            print(f"\n[{i + 1}] {file_path} ({error_count} {'error' if error_count == 1 else 'errors'})")
            for error in errors[:3]:
                print(f"  - L{error.line}: {error.code}: {error.message}")
            if error_count > 3:
                print(f"  - ... and {error_count - 3} more.")

        while True:
            prompt_message = "\nEnter the numbers of the files to fix (e.g., 1,3), 'all', or 'none': "
            choice = input(prompt_message).strip().lower()

            if not choice or choice == "none":
                print("No files selected. Exiting.")
                return []

            if choice == "all":
                print(f"All {len(indexed_files)} files selected for fixing.")
                return indexed_files

            try:
                selected_indices = [int(x.strip()) - 1 for x in choice.split(",")]

                if all(0 <= idx < len(indexed_files) for idx in selected_indices):
                    selected_files = [indexed_files[i] for i in selected_indices]
                    print("\nSelected files for fixing:")
                    for f in selected_files:
                        print(f" - {f}")
                    return selected_files
                else:
                    print(f"Error: Invalid number. Please enter numbers between 1 and {len(indexed_files)}.")
            except ValueError:
                print("Error: Invalid input. Please enter numbers, 'all', or 'none'.")

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
        except (RuntimeError, ValueError, IOError) as e:
            traceback.print_exc()
            print("无法自动修复当前错误组", str(e))
        except Exception:
            traceback.print_exc()
            print("发生未预期的错误")
            raise

    def _get_symbol_locations(self, file_path: str) -> list[tuple[int, int]]:
        """获取符号定位信息"""
        return [(line.line, line.column_range[0]) for line in self.file_groups[file_path]]

    def _associate_errors_with_symbols(
        self, file_path: str, parser_util: ParserUtil, code_map: Dict, locations: List[Tuple[int, int]]
    ) -> Dict[str, Dict]:
        """关联错误信息到符号"""
        symbol_map = parser_util.find_symbols_for_locations(code_map, locations, max_context_size=1024 * 1024)
        new_symbol_map: Dict[str, Dict] = {}
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

    def update_symbol_map(self, file_path: str) -> Tuple[ParserUtil, Dict]:
        """更新符号映射"""
        parser_loader = ParserLoader()
        parser_util = ParserUtil(parser_loader)
        _, code_map = parser_util.get_symbol_paths(file_path)
        return parser_util, code_map

    def _rerun_pylint_for_file(self, file_path: str) -> None:
        """针对单个文件重新运行pylint并更新结果"""
        try:
            pylint_args = self._get_pylint_args()
            result = subprocess.run(
                ["pylint", *pylint_args, file_path],
                capture_output=True,
                text=True,
                cwd=self.root_dir,
                check=False,
            )
            new_results = LintParser.parse(result.stdout)

            # 更新全局results：移除旧的，添加新的
            self.results = [r for r in self.results if r.file_path != file_path] + new_results

            # 更新file_groups
            if new_results:
                self.file_groups[file_path] = new_results
            elif file_path in self.file_groups:
                del self.file_groups[file_path]

        except Exception as e:
            print(f"重新运行pylint失败 for {file_path}: {str(e)}")
            raise

    def _process_symbols_for_file(self, file_path: str) -> None:
        """处理单个文件的所有符号，使用迭代修复循环"""
        iteration_count = 0
        while self.file_groups.get(file_path):
            iteration_count += 1
            print(f"\n--- Processing {file_path} (Iteration {iteration_count}/{self.max_file_fix_iterations}) ---")

            if iteration_count > self.max_file_fix_iterations:
                print(
                    f"警告: 已达到对文件 {file_path} 的最大修复尝试次数 ({self.max_file_fix_iterations})，跳过剩余错误。"
                )
                break

            parser_util, code_map = self.update_symbol_map(file_path)
            locations = self._get_symbol_locations(file_path)
            if not locations:
                # No lint errors found in this iteration for this file, break.
                # This should ideally be caught by `while self.file_groups.get(file_path)`
                # but adding for robustness.
                break

            symbol_map = self._associate_errors_with_symbols(file_path, parser_util, code_map, locations)

            # 获取有错误的symbols，按起始行排序（从上到下修复）
            symbols_with_errors = [s for s in symbol_map.values() if s.get("own_errors")]
            if not symbols_with_errors:
                # All errors seem to be resolved for this file based on current analysis.
                print(f"文件 {file_path} 在本轮未发现需要修复的符号级错误。")
                break

            # 处理第一个有错误的symbol
            symbol_to_fix = symbols_with_errors[0]
            print(f"尝试修复符号: {symbol_to_fix['name']}")
            self._process_symbol_group(symbol_to_fix, symbol_map)

            # 修复后重新运行pylint更新错误列表
            print(f"\n验证 {file_path} 的修复结果，重新运行pylint...")
            self._rerun_pylint_for_file(file_path)

        if not self.file_groups.get(file_path):
            print(f"\n文件 {file_path} 的所有Lint错误已解决。")
        else:
            print(f"\n文件 {file_path} 仍存在未解决的Lint错误，请手动检查。")
            current_errors = self.file_groups.get(file_path, [])
            for err in current_errors:
                print(f"  - L{err.line}: {err.code}: {err.message}")

    def execute(self) -> None:
        """执行完整的修复流程"""
        self.load_and_validate_log()
        if not self.results:
            print("未发现可修复的错误")
            return

        self.group_results_by_file()
        selected_files = self._select_files_interactively()

        if not selected_files:
            return

        ModelSwitch().select("coder")

        for file_path in selected_files:
            if file_path in self.file_groups:
                print(f"\n--- 开始处理文件: {file_path} ---")
                self._process_symbols_for_file(file_path)
            else:
                print(f"\n文件 {file_path} 在选中后没有发现Pylint错误，跳过处理。")

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
