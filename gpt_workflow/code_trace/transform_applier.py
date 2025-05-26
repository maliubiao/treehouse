import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from colorama import Fore, Style, init

from llm_query import process_patch_response
from tree import BlockPatch, ParserLoader, ParserUtil, SyntaxHighlight


class TransformApplier:
    """应用转换日志中的修改到源代码"""

    def __init__(self, skip_symbols: Optional[Set[str]] = None):
        self.skip_symbols = self._normalize_skip_symbols(skip_symbols or set())
        self.parser_loader = ParserLoader()
        self.parser_util = ParserUtil(self.parser_loader)
        init()  # Initialize colorama

    def _normalize_skip_symbols(self, skip_symbols: Set[str]) -> Set[str]:
        """标准化跳过符号的格式，确保与符号键格式一致"""
        normalized = set()
        for symbol in skip_symbols:
            if "/" in symbol:  # 已经是完整路径格式
                normalized.add(os.path.abspath(symbol))
            else:  # 只有符号名，转换为统一格式
                normalized.add(f"/{symbol}")
        return normalized

    def load_transformations(self, transform_file: Path) -> Dict:
        """从转换文件加载转换数据"""
        if not transform_file.exists():
            raise FileNotFoundError(f"Transform file not found: {transform_file}")

        try:
            with open(transform_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid transformation file format: {str(e)}") from e

    def _validate_transformation_data(self, transform_data: Dict, file_path: str) -> None:
        """验证转换数据的有效性"""
        if not isinstance(transform_data, dict):
            raise ValueError("Transformation data must be a dictionary")

        for key, data in transform_data.items():
            if not isinstance(data, dict):
                raise ValueError(f"Invalid transformation entry for {key}")

            required_fields = {
                "file_path": str,
                "symbol_name": str,
                "original_code": str,
                "transformed_code": str,
                "is_changed": bool,
            }

            for field, field_type in required_fields.items():
                if field not in data:
                    raise ValueError(f"Missing required field '{field}' in transformation for {key}")
                if not isinstance(data[field], field_type):
                    raise ValueError(f"Field '{field}' must be {field_type.__name__} in transformation for {key}")

    def _get_symbol_key(self, file_path: str, symbol_name: str) -> str:
        """生成统一的符号键，使用绝对路径"""
        abs_file_path = os.path.abspath(file_path)
        return f"{abs_file_path}/{symbol_name}"

    def _should_skip_symbol(self, symbol_key: str, symbol_name: str) -> bool:
        """检查是否应该跳过该符号"""
        # 检查完整路径格式
        if symbol_key in self.skip_symbols:
            print(f"{Fore.YELLOW}Skipping symbol (full path match): {symbol_key}{Style.RESET_ALL}")
            return True

        # 检查仅符号名格式
        if f"/{symbol_name}" in self.skip_symbols:
            print(f"{Fore.YELLOW}Skipping symbol (name only match): {symbol_name}{Style.RESET_ALL}")
            return True

        return False

    def apply_transformations(self, file_path: str, transform_file: Path) -> bool:
        """应用转换到指定文件"""
        try:
            transform_data = self.load_transformations(transform_file)
            if not transform_data:
                print(f"{Fore.YELLOW}No transformation data found in {transform_file}{Style.RESET_ALL}")
                return False

            self._validate_transformation_data(transform_data, file_path)

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
    def apply_from_default_transform_file(cls, file_path: str, skip_symbols: Optional[Set[str]] = None) -> bool:
        """从默认转换文件应用转换"""
        transform_file = cls.get_transform_file(file_path)
        if not transform_file.exists():
            print(f"{Fore.YELLOW}No transformation file found at {transform_file}{Style.RESET_ALL}")
            return False

        applier = cls(skip_symbols=skip_symbols)
        return applier.apply_transformations(file_path, transform_file)
