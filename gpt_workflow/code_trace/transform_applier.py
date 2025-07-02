import fnmatch
import json
import os
from pathlib import Path
from typing import Dict, Optional, Set

from colorama import Fore, Style

from tree import BlockPatch, ParserLoader, ParserUtil, SyntaxHighlight


class TransformApplier:
    """应用转换日志中的修改到源代码"""

    def __init__(self, skip_symbols: Optional[Set[str]] = None, dry_run: bool = False):
        self.skip_symbols = self._normalize_skip_symbols(skip_symbols or set())
        self.dry_run = dry_run
        self.parser_loader = ParserLoader()
        self.parser_util = ParserUtil(self.parser_loader)

    def _normalize_skip_symbols(self, skip_symbols: Set[str]) -> Set[str]:
        """标准化跳过符号的格式，支持glob模式"""
        normalized = set()
        for symbol in skip_symbols:
            if "/" in symbol:  # 已经是完整路径格式
                normalized.add(os.path.abspath(symbol))
            else:  # 只有符号名，转换为统一格式
                normalized.add(f"*/{symbol}")  # 添加通配符以支持glob匹配
        return normalized

    def load_transformations(self, transform_file: Path) -> Dict:
        """从转换文件加载转换数据"""
        if not transform_file.exists():
            raise FileNotFoundError(f"Transform file not found: {transform_file}")

        try:
            with open(transform_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return self._validate_and_filter_transformations(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid transformation file format: {str(e)}") from e

    def _validate_and_filter_transformations(self, transform_data: Dict) -> Dict:
        """验证并过滤转换数据，确保格式正确"""
        valid_data = {}
        for symbol_key, data in transform_data.items():
            try:
                # 基本字段验证
                if not all(
                    k in data for k in ["file_path", "symbol_name", "original_code", "transformed_code", "is_changed"]
                ):
                    print(
                        f"{Fore.YELLOW}Skipping invalid transformation (missing fields): {symbol_key}{Style.RESET_ALL}"
                    )
                    continue

                # 类型验证
                if not isinstance(data["original_code"], str) or not isinstance(data["transformed_code"], str):
                    print(
                        f"{Fore.YELLOW}Skipping invalid transformation (invalid code type): {symbol_key}{Style.RESET_ALL}"
                    )
                    continue

                # 空字符串检查
                if not data["original_code"].strip():
                    print(
                        f"{Fore.YELLOW}Skipping transformation with empty original code: {symbol_key}{Style.RESET_ALL}"
                    )
                    continue

                # 布尔值验证
                is_changed = data["is_changed"]
                if isinstance(is_changed, str):
                    is_changed = is_changed.lower() == "true"
                elif not isinstance(is_changed, bool):
                    is_changed = False

                # 如果转换后代码为空，强制标记为未更改
                if not data["transformed_code"].strip():
                    is_changed = False

                valid_data[symbol_key] = {
                    "file_path": data["file_path"],
                    "symbol_name": data["symbol_name"],
                    "original_code": data["original_code"],
                    "transformed_code": data["transformed_code"],
                    "is_changed": is_changed,
                }

            except Exception as e:
                print(f"{Fore.YELLOW}Skipping invalid transformation ({str(e)}): {symbol_key}{Style.RESET_ALL}")
                continue

        return valid_data

    def _get_symbol_key(self, file_path: str, symbol_name: str) -> str:
        """生成统一的符号键，使用绝对路径"""
        abs_file_path = os.path.abspath(file_path)
        return f"{abs_file_path}/{symbol_name}"

    def _should_skip_symbol(self, symbol_key: str, symbol_name: str) -> bool:
        """检查是否应该跳过该符号，支持glob模式匹配"""
        for pattern in self.skip_symbols:
            if fnmatch.fnmatch(symbol_key, pattern):
                if self.dry_run:
                    print(
                        f"{Fore.YELLOW}[DRY-RUN] Would skip symbol (pattern match): {symbol_key} (pattern: {pattern}){Style.RESET_ALL}"
                    )
                else:
                    print(
                        f"{Fore.YELLOW}Skipping symbol (pattern match): {symbol_key} (pattern: {pattern}){Style.RESET_ALL}"
                    )
                return True
        return False

    def apply_transformations(self, file_path: str, transform_file: Path) -> bool:
        """应用转换到指定文件"""
        try:
            transform_data = self.load_transformations(transform_file)
            if not transform_data:
                print(f"{Fore.YELLOW}No valid transformation data found in {transform_file}{Style.RESET_ALL}")
                return False

            # 获取文件中的符号
            _, code_map = self.parser_util.get_symbol_paths(file_path)
            if not code_map:
                print(f"{Fore.YELLOW}No symbols found in {file_path}{Style.RESET_ALL}")
                return False

            # 准备补丁数据
            patch_items = []
            symbol_detail = {}
            applied_symbols = []
            skipped_symbols = []
            missing_symbols = []

            for symbol_name, symbol_info in code_map.items():
                symbol_key = self._get_symbol_key(file_path, symbol_name)

                if self._should_skip_symbol(symbol_key, symbol_name):
                    skipped_symbols.append(symbol_name)
                    continue

                if symbol_key not in transform_data:
                    missing_symbols.append(symbol_name)
                    continue

                transform = transform_data[symbol_key]
                if not transform["is_changed"]:
                    skipped_symbols.append(symbol_name)
                    continue

                # 确保转换后代码不为空
                if not transform["transformed_code"].strip():
                    print(f"{Fore.YELLOW}Skipping symbol with empty transformed code: {symbol_name}{Style.RESET_ALL}")
                    skipped_symbols.append(symbol_name)
                    continue

                symbol_detail[symbol_key] = {
                    "file_path": file_path,
                    "block_range": symbol_info["block_range"],
                    "block_content": symbol_info["code"].encode("utf-8")
                    if isinstance(symbol_info["code"], str)
                    else symbol_info["code"],
                }

                patch_items.append(
                    (
                        file_path,
                        symbol_info["block_range"],
                        symbol_info["code"].encode("utf-8")
                        if isinstance(symbol_info["code"], str)
                        else symbol_info["code"],
                        transform["transformed_code"].encode("utf-8"),
                    )
                )
                applied_symbols.append(symbol_name)

            # 打印转换统计信息
            print(f"\n{Fore.CYAN}=== Transformation Statistics ==={Style.RESET_ALL}")
            print(f"Total symbols in file: {len(code_map)}")
            print(f"Applied transformations: {Fore.GREEN}{len(applied_symbols)}{Style.RESET_ALL}")
            print(f"Skipped symbols (config): {Fore.YELLOW}{len(skipped_symbols)}{Style.RESET_ALL}")
            print(f"Missing transformations: {Fore.RED}{len(missing_symbols)}{Style.RESET_ALL}")

            if skipped_symbols:
                print(f"\n{Fore.YELLOW}Skipped symbols:{Style.RESET_ALL}")
                for sym in skipped_symbols:
                    print(f"  - {sym}")

            if self.dry_run:
                print(
                    f"\n{Fore.BLUE}DRY-RUN: Would apply transformations to {len(applied_symbols)} symbols:{Style.RESET_ALL}"
                )
                for sym in applied_symbols:
                    print(f"  - {sym}")
                return True

            if not patch_items:
                print(f"{Fore.YELLOW}No transformations to apply{Style.RESET_ALL}")
                return False

            print(f"\n{Fore.GREEN}Applying transformations to {len(applied_symbols)} symbols:{Style.RESET_ALL}")
            for sym in applied_symbols:
                print(f"  - {sym}")

            # 创建并应用补丁
            patch = BlockPatch(
                file_paths=[item[0] for item in patch_items],
                patch_ranges=[item[1] for item in patch_items],
                block_contents=[item[2] for item in patch_items],
                update_contents=[item[3] for item in patch_items],
            )

            # 生成差异并应用
            diff = patch.generate_diff()
            if not diff:
                print(f"{Fore.YELLOW}No differences found{Style.RESET_ALL}")
                return False
            print(SyntaxHighlight.highlight_if_terminal("\n".join(diff.values()), file_path=file_path))
            # 直接应用补丁
            patched_files = patch.apply_patch()
            if not patched_files:
                print(f"{Fore.RED}Failed to apply patch{Style.RESET_ALL}")
                return False
            for patched_file in patched_files:
                with open(patched_file, "wb") as f:
                    f.write(patched_files[patched_file])
            print(f"{Fore.GREEN}Successfully applied transformations to {file_path}{Style.RESET_ALL}")
            return True

        except Exception as e:
            print(f"{Fore.RED}Error applying transformations: {str(e)}{Style.RESET_ALL}")
            return False

    @classmethod
    def get_transform_file(cls, file_path: str) -> Path:
        """获取文件的默认转换文件路径"""
        file_name = Path(file_path).name
        return Path("trace_debug") / "file_transformations" / f"{file_name}_transformations.json"

    @classmethod
    def apply_from_default_transform_file(
        cls, file_path: str, skip_symbols: Optional[Set[str]] = None, dry_run: bool = False
    ) -> bool:
        """从默认转换文件应用转换"""
        transform_file = cls.get_transform_file(file_path)
        if not transform_file.exists():
            print(f"{Fore.YELLOW}No transformation file found at {transform_file}{Style.RESET_ALL}")
            return False

        applier = cls(skip_symbols=skip_symbols, dry_run=dry_run)
        return applier.apply_transformations(file_path, transform_file)
