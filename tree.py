import argparse
import asyncio
import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

# Windows控制台颜色修复
from colorama import just_fix_windows_console
from pygments import formatters, highlight, lexers
from tree_sitter import Node, Parser

from lsp.client import GenericLSPClient
from tree_libs.ast import (
    SUPPORTED_LANGUAGES,
    ParserLoader,
    ParserUtil,
    SourceSkeleton,
)

just_fix_windows_console()

# 设置日志级别
logger = logging.getLogger(__name__)


LLM_PROJECT_CONFIG = ".llm_project.yml"


class ProjectConfig:
    """强类型的项目配置数据结构"""

    def __init__(
        self,
        project_root_dir: str,
        exclude: Dict[str, List[str]],
        include: Dict[str, List[str]],
        file_types: List[str],
        lsp: Optional[Dict[str, Any]] = None,
    ):
        self.project_root_dir = project_root_dir
        self.exclude = exclude
        self.include = include
        self.file_types = file_types
        self.lsp = lsp if lsp is not None else {}
        self._lsp_clients: Dict[str, Any] = {}
        self._lsp_lock = threading.Lock()
        self.symbol_service_url: Optional[str] = None
        self._config_file_path: Optional[Path] = None

    def relative_path(self, path: Union[Path, str]) -> str:
        """获取相对于项目根目录的路径"""
        try:
            return str(Path(path).relative_to(self.project_root_dir))
        except ValueError:
            return str(path)

    def relative_to_current_path(self, path: Union[Path, str]) -> str:
        path = Path(path)
        if path.is_absolute():
            try:
                return str(path.relative_to(Path.cwd()))
            except ValueError:
                return str(path)
        else:
            p = (Path.cwd() / path).resolve()
            return str(p.relative_to(Path.cwd()))

    def get_lsp_client(self, key: str) -> Optional[Any]:
        """获取缓存的LSP客户端"""
        with self._lsp_lock:
            return self._lsp_clients.get(key)

    def set_lsp_client(self, key: str, client: Any):
        """设置缓存的LSP客户端"""
        with self._lsp_lock:
            self._lsp_clients[key] = client

    def set_config_file_path(self, config_path: Path):
        """设置配置文件路径"""
        self._config_file_path = config_path

    def update_symbol_service_url(self, url: str):
        """更新符号服务URL并保存配置"""
        self.symbol_service_url = url
        self.save_config()

    def save_config(self):
        """将配置保存到文件"""
        if not self._config_file_path:
            return

        config_data = {
            "project_root_dir": str(self.project_root_dir),
            "exclude": self.exclude,
            "include": self.include,
            "file_types": self.file_types,
            "lsp": self.lsp,
            "symbol_service_url": self.symbol_service_url,
        }

        try:
            with open(self._config_file_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config_data, f, sort_keys=False)
        except IOError as e:
            logging.error(f"保存配置文件失败: {e}")


class ConfigLoader:
    """加载和管理LLM项目搜索配置"""

    def __init__(self, config_path: Path = Path(LLM_PROJECT_CONFIG)):
        self.config_path = Path(config_path)
        self._default_config = ProjectConfig(
            project_root_dir=str(Path.cwd()),
            lsp={"commands": {"py": "pylsp"}, "default": "py"},
            exclude={
                "dirs": [
                    ".git",
                    ".venv",
                    "node_modules",
                    "build",
                    "dist",
                    "__pycache__",
                ],
                "files": ["*.min.js", "*.bundle.css", "*.log", "*.tmp"],
            },
            include={"dirs": [], "files": ["*.py", "*.js", "*.md", "*.txt"]},
            file_types=[".py", "*.js", "*.md", "*.txt"],
        )

    def bubble_up_for_root_dir(self, path: Path) -> Path:
        """向上遍历目录，找到包含配置文件的根目录"""
        while path != path.parent:
            if (path / self.config_path).exists():
                return path / self.config_path
            path = path.parent
        return path / self.config_path

    def load_config(self) -> ProjectConfig:
        """加载并验证配置文件"""
        if not self.config_path.is_absolute():
            self.config_path = self.bubble_up_for_root_dir(Path.cwd() / self.config_path)
        if not self.config_path.exists():
            return self._default_config
        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            project_config = self._merge_configs(config)
            project_config.set_config_file_path(self.config_path)
            return project_config
        except (yaml.YAMLError, IOError) as e:
            print(f"❌ 配置文件加载失败: {str(e)}")
            return self._default_config

    def load_search_config(self, config: Optional[ProjectConfig] = None) -> "SearchConfig":
        """从已加载的配置创建SearchConfig"""
        config_to_use = config if config is not None else self.load_config()
        return self._create_search_config(config_to_use)

    def get_default_config(self) -> ProjectConfig:
        """获取默认配置"""
        return self._default_config

    def _merge_configs(self, user_config: dict) -> ProjectConfig:
        """合并用户配置和默认配置"""
        project_config = ProjectConfig(
            project_root_dir=Path(
                os.path.expanduser(user_config.get("project_root_dir", self._default_config.project_root_dir))
            ).resolve(),
            lsp=user_config.get("lsp", self._default_config.lsp),
            exclude={
                "dirs": user_config.get("exclude", {}).get("dirs", self._default_config.exclude["dirs"]),
                "files": user_config.get("exclude", {}).get("files", self._default_config.exclude["files"]),
            },
            include={
                "dirs": user_config.get("include", {}).get("dirs", self._default_config.include["dirs"]),
                "files": user_config.get("include", {}).get("files", self._default_config.include["files"]),
            },
            file_types=user_config.get("file_types", self._default_config.file_types),
        )
        project_config.symbol_service_url = user_config.get("symbol_service_url")
        return project_config

    def _create_search_config(self, config: ProjectConfig) -> "SearchConfig":
        """创建SearchConfig对象并进行验证"""
        return SearchConfig(
            root_dir=Path(config.project_root_dir).expanduser().resolve(),
            exclude_dirs=config.exclude["dirs"],
            exclude_files=config.exclude["files"],
            include_dirs=config.include["dirs"],
            include_files=config.include["files"],
            file_types=config.file_types,
        )


GLOBAL_PROJECT_CONFIG = ConfigLoader(LLM_PROJECT_CONFIG).load_config()


class TrieNode:
    """前缀树节点"""

    __slots__ = ["children", "is_end", "symbols"]

    def __init__(self):
        self.children: Dict[str, TrieNode] = {}  # 字符到子节点的映射
        self.is_end: bool = False  # 是否单词结尾
        self.symbols: List[Dict[str, Any]] = []  # 存储符号详细信息（支持同名不同定义的符号）


class SymbolTrie:
    def __init__(self, case_sensitive: bool = True):
        self.root = TrieNode()
        self.case_sensitive = case_sensitive
        self._size = 0  # 记录唯一符号数量

    def _normalize(self, word: str) -> str:
        """统一大小写处理"""
        return word if self.case_sensitive else word.lower()

    def insert(self, symbol_name: str, symbol_info: Dict[str, Any]):
        """插入符号到前缀树"""
        node = self.root
        word = self._normalize(symbol_name)

        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]

        # 直接替换符号信息
        node.symbols = [symbol_info]
        if not node.is_end:  # 新增唯一符号计数
            self._size += 1
        node.is_end = True

        # 为自动补全插入带文件名的符号，避免递归
        if not symbol_name.startswith("symbol:"):
            file_basename = extract_identifiable_path(symbol_info["file_path"])
            composite_key = f"symbol:{file_basename}/{word}"
            # 使用新的symbol_info副本，防止引用问题
            self.insert(composite_key, symbol_info)

    def search_exact(self, symbol_path: str) -> Optional[Dict[str, Any]]:
        """精确搜索符号路径

        参数：
            symbol_path: 要搜索的完整符号路径

        返回：
            匹配的符号信息，如果未找到则返回None
        """
        node = self.root
        path = self._normalize(symbol_path)

        # 遍历路径中的每个字符
        for char in path:
            if char not in node.children:
                return None
            node = node.children[char]

        # 如果找到完整匹配的节点，返回第一个符号信息
        if node.is_end and node.symbols:
            return node.symbols[0]
        return None

    def search_prefix(
        self, prefix: str, max_results: Optional[int] = None, use_bfs: bool = False
    ) -> List[Dict[str, Any]]:
        """前缀搜索

        参数：
            prefix: 要搜索的前缀字符串
            max_results: 最大返回结果数量，None表示不限制
            use_bfs: 是否使用广度优先搜索

        返回：
            匹配前缀的符号列表
        """
        node = self.root
        prefix = self._normalize(prefix)

        # 定位到前缀末尾节点
        for char in prefix:
            if char not in node.children:
                return []
            node = node.children[char]

        # 选择遍历算法
        results: List[Dict[str, Any]] = []
        if use_bfs:
            self._bfs_collect(node, prefix, results, max_results)
        else:
            self._dfs_collect(node, prefix, results, max_results)
        return results

    def _bfs_collect(self, node: TrieNode, current_prefix: str, results: list, max_results: Optional[int]):
        """广度优先收集符号"""

        queue: deque = deque([(node, current_prefix)])

        while queue:
            current_node, current_path = queue.popleft()

            if current_node.is_end:
                for symbol in current_node.symbols:
                    results.append({"name": current_path, "details": symbol})
                    if max_results is not None and len(results) >= max_results:
                        return

            for char in sorted(current_node.children.keys()):
                child = current_node.children[char]
                queue.append((child, current_path + char))

    def _dfs_collect(self, node: TrieNode, current_prefix: str, results: list, max_results: Optional[int]):
        """深度优先收集符号"""
        if max_results is not None and len(results) >= max_results:
            return

        if node.is_end:
            for symbol in node.symbols:
                results.append({"name": current_prefix, "details": symbol})
                if max_results is not None and len(results) >= max_results:
                    return

        for char, child in node.children.items():
            self._dfs_collect(child, current_prefix + char, results, max_results)

    def to_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        """将前缀树转换为包含所有符号的字典"""
        result: Dict[str, List[Dict[str, Any]]] = {}
        self._collect_all_symbols(self.root, "", result)
        return result

    def _collect_all_symbols(self, node: TrieNode, current_prefix: str, result: Dict):
        """递归收集所有符号"""
        if node.is_end:
            result[current_prefix] = list(node.symbols)

        for char, child in node.children.items():
            self._collect_all_symbols(child, current_prefix + char, result)

    @property
    def size(self) -> int:
        """返回唯一符号数量"""
        return self._size

    @classmethod
    def from_symbols(cls, symbols_dict: Dict, case_sensitive: bool = True) -> "SymbolTrie":
        """从现有符号字典构建前缀树"""
        trie = cls(case_sensitive)
        for symbol_name, entries in symbols_dict.items():
            for entry in entries:
                trie.insert(
                    symbol_name,
                    {
                        "file_path": entry[0],
                        "signature": entry[1],
                        "full_definition_hash": entry[2],
                    },
                )
        return trie


class Match:
    def __init__(self, line: int, column_range: tuple[int, int], text: str):
        self.line = line
        self.column_range = column_range
        self.text = text


class SearchResult:
    def __init__(self, file_path: Path, matches: List[Match], stats: Optional[Dict] = None):
        self.file_path = file_path
        self.matches = matches
        self.stats = stats or {}


class SearchConfig:
    __slots__ = [
        "root_dir",
        "exclude_dirs",
        "exclude_files",
        "include_dirs",
        "include_files",
        "file_types",
    ]

    def __init__(
        self,
        root_dir: Path,
        exclude_dirs: List[str],
        exclude_files: List[str],
        include_dirs: List[str],
        include_files: List[str],
        file_types: List[str],
    ):
        self.root_dir = root_dir
        self.exclude_dirs = exclude_dirs
        self.exclude_files = exclude_files
        self.include_dirs = include_dirs
        self.include_files = include_files
        self.file_types = file_types


class RipgrepSearcher:
    def __init__(self, config: SearchConfig, debug: bool = False, file_list: Optional[list[str]] = None):
        self.config = config
        self.debug = debug
        self.file_pattern = self._build_file_pattern()
        self.file_list = file_list

    def _build_file_pattern(self) -> str:
        """构建符合ripgrep要求的文件类型匹配模式"""
        extensions = [ext.lstrip("*.") for ext in self.config.file_types]
        return f"*.{{{','.join(extensions)}}}"

    def search(self, patterns: List[str], search_root: Optional[Path] = None) -> List[SearchResult]:
        """Execute ripgrep search with multiple patterns"""
        if not patterns:
            raise ValueError("At least one search pattern is required")
        actual_root = search_root or self.config.root_dir
        if not actual_root.exists():
            raise ValueError(f"Configured root directory does not exist: {actual_root}")

        cmd = self._build_command(patterns, actual_root)
        if self.debug:
            logger.debug("Executing command: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False)
        if self.debug:
            logger.debug(result.stdout)
        if result.returncode not in (0, 1):
            error_msg = f"rg command failed: {result.stderr}\nCommand: {' '.join(cmd)}"
            raise RuntimeError(error_msg)

        return self._parse_results(result.stdout)

    def _build_command(self, patterns: List[str], search_root: Path) -> List[str]:
        cmd = [
            "rg.exe" if os.name == "nt" else "rg",
            "--json",
            "--smart-case",
            "--trim",
            "--type-add",
            f"custom:{self.file_pattern}",
            "-t",
            "custom",
            "--no-ignore",
        ]
        for pattern in patterns:
            cmd.extend(["--regexp", pattern])

        if self.file_list:
            cmd.extend(["--follow", "--glob"] + self.file_list)
        else:
            for d in self.config.exclude_dirs:
                cmd.extend(["--glob", f"!{d.replace(os.sep, '/')}/**"])
            for f in self.config.exclude_files:
                cmd.extend(["--glob", f"!{f.replace(os.sep, '/')}"])
            for d in self.config.include_dirs:
                cmd.extend(["--glob", f"{d.replace(os.sep, '/')}/**"])
            cmd.append(str(search_root).replace(os.sep, "/"))
        return cmd

    def _parse_results(self, output: str) -> List[SearchResult]:
        results: Dict[Path, Dict[str, Any]] = defaultdict(lambda: {"matches": [], "stats": {}})
        for line in output.splitlines():
            try:
                data = json.loads(line)
                path_str = data.get("data", {}).get("path", {}).get("text")
                if not path_str:
                    continue
                path = Path(path_str)

                if data["type"] == "match":
                    line_num = data["data"]["line_number"]
                    text = data["data"]["lines"]["text"]
                    for submatch in data["data"]["submatches"]:
                        match = Match(line_num, (submatch["start"], submatch["end"]), text)
                        results[path]["matches"].append(match)
                elif data["type"] == "end":
                    results[path]["stats"] = data["data"].get("stats", {})
            except (KeyError, json.JSONDecodeError):
                continue
        return [SearchResult(path, entry["matches"], entry["stats"]) for path, entry in results.items()]


BINARY_MAGIC_NUMBERS = {
    b"\x89PNG",
    b"\xff\xd8",
    b"GIF",
    b"BM",
    b"%PDF",
    b"MZ",
    b"\x7fELF",
    b"PK",
    b"Rar!",
    b"\x1f\x8b",
    b"BZh",
    b"\xfd7zXZ",
    b"7z\xbc\xaf\x27\x1c",
    b"ITSF",
    b"\x49\x44\x33",
    b"\x00\x00\x01\xba",
    b"\x00\x00\x01\xb3",
    b"FLV",
    b"RIFF",
    b"OggS",
    b"fLaC",
    b"\x1a\x45\xdf\xa3",
    b"\x30\x26\xb2\x75\x8e\x66\xcf\x11",
    b"\x00\x01\x00\x00",
    b"OTTO",
    b"wOFF",
    b"ttcf",
    b"\xed\xab\xee\xdb",
    b"\x53\x51\x4c\x69\x74\x65\x20\x66",
    b"\x50\x4b\x03\x04",
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
}


def find_diff() -> str:
    git_path = shutil.which("git")
    if not git_path:
        return ""
    if git_path.lower().endswith("git.exe"):
        return str(Path(git_path).parent.parent / "usr" / "bin" / "diff.exe")
    return shutil.which("diff") or ""


def find_patch() -> str:
    git_path = shutil.which("git")
    if not git_path:
        return ""
    if git_path.lower().endswith("git.exe"):
        return str(Path(git_path).parent.parent / "usr" / "bin" / "patch.exe")
    return shutil.which("patch") or ""


class BlockPatch:
    def __init__(
        self,
        file_paths: list[str],
        patch_ranges: list[tuple],
        block_contents: list[bytes],
        update_contents: list[bytes],
        manual_merge: bool = False,
    ):
        if not (len(file_paths) == len(patch_ranges) == len(block_contents) == len(update_contents)):
            raise ValueError("All parameter lists must have the same length")
        self.manual_merge = manual_merge
        self.file_paths, self.patch_ranges, self.block_contents, self.update_contents = [], [], [], []
        for i, path in enumerate(file_paths):
            if block_contents[i] != update_contents[i]:
                self.file_paths.append(path)
                self.patch_ranges.append(patch_ranges[i])
                self.block_contents.append(block_contents[i])
                self.update_contents.append(update_contents[i])

        self.source_codes: Dict[str, bytes] = {}
        if not self.file_paths:
            return
        for path in set(self.file_paths):
            with open(path, "rb") as f:
                content = f.read()
                if self._is_binary_file(content):
                    raise ValueError(f"File {path} is binary, refusing to modify.")
                try:
                    content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(f"File {path} is not UTF-8 encoded, refusing to modify.") from exc
                self.source_codes[path] = content

    def _is_binary_file(self, content: bytes) -> bool:
        return any(content.startswith(magic) for magic in BINARY_MAGIC_NUMBERS)

    def _validate_ranges(self, original_code: bytes, ranges: list[tuple[int, int]]) -> None:
        checked_ranges: List[Tuple[int, int]] = []
        for current in ranges:
            for checked in checked_ranges:
                if not (current[1] <= checked[0] or checked[1] <= current[0]):
                    raise ValueError(f"Ranges overlap: {current} and {checked}")
            checked_ranges.append(current)

    def _build_modified_blocks(self, original_code: bytes, replacements: list) -> list[bytes]:
        for (start, end), old_content_bytes, _ in replacements:
            if start != end and original_code[start:end] != old_content_bytes:
                expected_bytes = original_code[start:end]

                print(f"ERROR: Content mismatch for range {start}:{end}.", file=sys.stderr)

                try:
                    # We assume unified_diff is imported at the file level as it's used in _process_single_file_diff
                    expected_str_lines = expected_bytes.decode("utf-8").splitlines(keepends=True)
                    actual_str_lines = old_content_bytes.decode("utf-8").splitlines(keepends=True)

                    diff = unified_diff(
                        expected_str_lines,
                        actual_str_lines,
                        fromfile="expected_in_file",
                        tofile="actual_from_model",
                    )
                    print("Showing diff on stderr:", file=sys.stderr)
                    sys.stderr.writelines(diff)
                    sys.stderr.flush()
                except (UnicodeDecodeError, NameError):
                    print("Cannot generate text diff. Showing raw bytes:", file=sys.stderr)
                    print(f"Expected: {expected_bytes!r}", file=sys.stderr)
                    print(f"Actual:   {old_content_bytes!r}", file=sys.stderr)

                raise ValueError(f"Content mismatch for range {start}:{end}")

        self._validate_ranges(original_code, [(s, e) for (s, e), _, _ in replacements])
        replacements.sort(key=lambda x: x[0][0])

        blocks: List[bytes] = []
        last_pos = 0
        for (start, end), _, new_content_bytes in replacements:
            if last_pos < start:
                blocks.append(original_code[last_pos:start])
            blocks.append(new_content_bytes)
            last_pos = end
        if last_pos < len(original_code):
            blocks.append(original_code[last_pos:])
        return blocks

    def _generate_system_diff(self, original_file: str, modified_file: str) -> Optional[str]:
        diff_tool = find_diff()
        if not diff_tool:
            return None
        try:
            cmd = [diff_tool, "-u", original_file, modified_file]
            if os.name == "nt":
                cmd = [
                    diff_tool,
                    "-u",
                    "--strip-trailing-cr",
                    os.path.relpath(original_file),
                    os.path.relpath(modified_file),
                ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, encoding="utf8")
            return result.stdout if result.returncode in (0, 1) else None
        except FileNotFoundError:
            return None

    def _launch_diff_tool(self, original_path: str, modified_path: str) -> None:
        if shutil.which("code"):
            tool_cmd = ["code", "-d", original_path, modified_path]
        elif shutil.which("vimdiff"):
            tool_cmd = ["vimdiff", original_path, modified_path]
        else:
            raise RuntimeError("No suitable diff tool found (VS Code or vim).")
        subprocess.run(tool_cmd, check=True)
        if "code" in tool_cmd[0]:
            input("Press Enter to continue after merging in VS Code...")

    def file_mtime(self, path: str) -> str:
        t = datetime.fromtimestamp(os.stat(path).st_mtime, timezone.utc)
        return t.astimezone().isoformat()

    def _process_single_file_diff(self, file_path: str, indices: list[int]) -> list[str]:
        original_code = self.source_codes[file_path]
        replacements = [((self.patch_ranges[i]), self.block_contents[i], self.update_contents[i]) for i in indices]
        modified_blocks = self._build_modified_blocks(original_code, replacements)
        modified_code_bytes = b"".join(modified_blocks)

        with (
            tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".original") as f_orig,
            tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".modified") as f_mod,
        ):
            f_orig.write(original_code)
            f_mod.write(modified_code_bytes)
            f_orig_path, f_mod_path = f_orig.name, f_mod.name

        if self.manual_merge:
            self._launch_diff_tool(f_orig_path, f_mod_path)
            with open(f_mod_path, "rb") as f:
                modified_code_bytes = f.read()
            for i in indices:
                self.update_contents[i] = modified_code_bytes

        system_diff = self._generate_system_diff(f_orig_path, f_mod_path)
        os.unlink(f_orig_path)
        os.unlink(f_mod_path)

        if system_diff:
            diff_lines = []
            for line in system_diff.splitlines(keepends=True):
                if line.startswith("--- ") or line.startswith("+++ "):
                    parts = line.split("\t", 1)
                    diff_lines.append(
                        f"{parts[0].split()[0]} {file_path}\t{parts[1]}"
                        if len(parts) > 1
                        else f"{parts[0].split()[0]} {file_path}\n"
                    )
                else:
                    diff_lines.append(line)
            return diff_lines
        else:
            logger.warning("System diff tool failed, falling back to difflib.")
            return list(
                unified_diff(
                    original_code.decode("utf8").splitlines(keepends=True),
                    modified_code_bytes.decode("utf8").splitlines(keepends=True),
                    fromfile=file_path,
                    tofile=file_path,
                )
            )

    def generate_diff(self) -> Dict[str, str]:
        if not self.file_paths:
            return {}
        file_groups = defaultdict(list)
        for i, path in enumerate(self.file_paths):
            file_groups[path].append(i)
        return {path: "".join(self._process_single_file_diff(path, indices)) for path, indices in file_groups.items()}

    def _process_single_file_patch(self, file_path: str, indices: list[int]) -> bytes:
        original_code = self.source_codes[file_path]
        replacements = [((self.patch_ranges[i]), self.block_contents[i], self.update_contents[i]) for i in indices]
        modified_blocks = self._build_modified_blocks(original_code, replacements)
        return b"".join(modified_blocks)

    def apply_patch(self) -> Dict[str, bytes]:
        if not self.file_paths:
            return {}
        patched_files = {}
        file_groups = defaultdict(list)
        for i, path in enumerate(self.file_paths):
            file_groups[path].append(i)
        for path, indices in file_groups.items():
            patched_files[path] = self._process_single_file_patch(path, indices)
        return patched_files


def split_source(source: str, start_row: int, start_col: int, end_row: int, end_col: int) -> tuple[str, str, str]:
    lines = source.splitlines(keepends=True)
    if not lines:
        return ("", "", "") if source == "" else (source, "", "")
    max_row = len(lines) - 1
    start_row, end_row = max(0, min(start_row, max_row)), max(0, min(end_row, max_row))

    def calc_pos(row: int, col: int) -> int:
        return sum(len(line) for line in lines[:row]) + max(0, min(col, len(lines[row])))

    start_pos, end_pos = calc_pos(start_row, start_col), calc_pos(end_row, end_col)
    if start_pos > end_pos:
        start_pos, end_pos = end_pos, start_pos
    return (source[:start_pos], source[start_pos:end_pos], source[end_pos:])


def get_node_segment(code: str, node: Node) -> tuple[str, str, str]:
    return split_source(code, node.start_point[0], node.start_point[1], node.end_point[0], node.end_point[1])


def safe_replace(code: str, new_code: str, start: tuple[int, int], end: tuple[int, int]) -> str:
    before, _, after = split_source(code, *start, *end)
    return before + new_code + after


def parse_code_file(file_path: Path, lang_parser: Parser) -> Node:
    with open(file_path, "rb") as f:
        code = f.read()
    tree = lang_parser.parse(code)
    return tree.root_node


def get_code_from_node(code: bytes, node: Node) -> bytes:
    return code[node.start_byte : node.end_byte]


def extract_identifiable_path(file_path: str) -> str:
    current_dir = str(GLOBAL_PROJECT_CONFIG.project_root_dir)
    abs_path = os.path.abspath(os.path.join(current_dir, file_path) if not os.path.isabs(file_path) else file_path)
    if abs_path.startswith(current_dir):
        return os.path.relpath(abs_path, current_dir).replace("\\", "/")
    return abs_path.replace("\\", "/")


def update_trie_if_needed(prefix: str, trie: SymbolTrie, file_parser_info_cache: Dict, just_path: bool = False) -> bool:
    if not prefix.startswith("symbol:"):
        return False
    path_part = prefix.removeprefix("symbol:")
    file_path = path_part[: path_part.rfind("/")] if "/" in path_part and not just_path else path_part
    ext = Path(file_path).suffix.lower()
    if ext not in SUPPORTED_LANGUAGES:
        return False

    try:
        current_mtime = os.path.getmtime(file_path)
    except FileNotFoundError:
        return False

    parser_instance, cached_mtime, _ = file_parser_info_cache.get(file_path, (None, 0, ""))
    if current_mtime > cached_mtime:
        logger.debug("File modified, re-parsing: %s", file_path)
        parser_loader = ParserLoader()
        parser_instance = ParserUtil(parser_loader)
        parser_instance.update_symbol_trie(file_path, trie)
        file_parser_info_cache[file_path] = (parser_instance, current_mtime, file_path)
        return True
    return False


def perform_trie_search(
    trie: SymbolTrie,
    prefix: str,
    max_results: int,
    file_parser_info_cache: Dict,
    file_path: Optional[str] = None,
    use_bfs: bool = False,
    search_exact: bool = False,
) -> list:
    if search_exact:
        result = trie.search_exact(prefix)
        return [result] if result else []

    results = trie.search_prefix(prefix, max_results=max_results, use_bfs=use_bfs)
    if not results and file_path:
        if update_trie_if_needed(f"symbol:{file_path}", trie, file_parser_info_cache, just_path=True):
            return trie.search_prefix(prefix, max_results=max_results, use_bfs=use_bfs)
    return results


def dynamic_import(module_name: str) -> Any:
    return importlib.import_module(module_name)


def main(
    host: str = "127.0.0.1",
    port: int = 8000,
    project_paths: Optional[List[str]] = None,
):
    # This function is now a simple launcher for the web service.
    # The actual app is created by the factory in tree_libs.app
    app_factory = dynamic_import("tree_libs.app")
    app = app_factory.create_app()

    # Initialization logic that might have been in `build_index` or `initialize_symbol_trie`
    # can now be performed here, populating the app's state.
    # For now, we start with an empty symbol trie.
    # To populate, you would run a separate indexing command.

    logger.info(f"Starting web service at http://{host}:{port}")
    uvicorn = dynamic_import("uvicorn")
    uvicorn.run(app, host=host, port=port)


def start_lsp_client_once(config: ProjectConfig, file_path: str) -> GenericLSPClient:
    try:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")
        logger.debug("Attempting to start LSP client for: %s", file_path)
        relative_path = config.relative_path(path)

        lsp_config = _determine_lsp_config(config, relative_path, path.suffix)
        cache_key = f"lsp:{lsp_config['lsp_key']}:{lsp_config['workspace_path']}"

        cached_client = config.get_lsp_client(cache_key)
        if cached_client:
            logger.debug("Using cached LSP client for: %s", cache_key)
            return cached_client

        client = _initialize_lsp_client(config, lsp_config["lsp_key"], lsp_config["workspace_path"])
        _start_lsp_thread(
            client,
            {
                "key": cache_key,
                "command": config.lsp.get("commands", {}).get(lsp_config["lsp_key"], lsp_config["lsp_key"]),
            },
        )

        config.set_lsp_client(cache_key, client)
        logger.debug("Cached new LSP client: %s", cache_key)
        client.initialized_event.wait(timeout=10)
        return client
    except Exception as e:
        logger.error("LSP client startup failed for %s: %s", file_path, e, exc_info=True)
        raise


def _determine_lsp_config(config: ProjectConfig, relative_path: str, suffix: str) -> dict:
    workspace_path = config.project_root_dir
    lsp_key = config.lsp.get("suffix", {}).get(suffix.lstrip("."))
    if not lsp_key and "subproject" in config.lsp:
        for subpath, cmd_key in config.lsp["subproject"].items():
            if relative_path.startswith(subpath):
                lsp_key = cmd_key
                workspace_path = str(Path(config.project_root_dir) / subpath)
                break
    if not lsp_key:
        lsp_key = config.lsp.get("default", "py")
    return {"lsp_key": lsp_key, "workspace_path": workspace_path}


def _initialize_lsp_client(config: ProjectConfig, lsp_key: str, workspace_path: str) -> GenericLSPClient:
    lsp_command = config.lsp.get("commands", {}).get(lsp_key)
    if not lsp_command:
        raise ValueError(f"LSP command not configured for key: {lsp_key}")
    logger.info("Initializing LSP client. Command: %s, Workspace: %s", lsp_command, workspace_path)
    return GenericLSPClient(lsp_command.split(), workspace_path)


def _start_lsp_thread(client: GenericLSPClient, client_info: dict):
    def run_event_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            logger.debug("Starting LSP client thread: %s", client_info["key"])
            client.start()
            loop.run_forever()
        except Exception as e:
            logger.error("LSP client event loop error: %s", e, exc_info=True)
        finally:
            logger.debug("Shutting down LSP client: %s", client_info["key"])
            if client.running:
                loop.run_until_complete(client.shutdown())
            loop.close()

    thread = threading.Thread(target=run_event_loop, daemon=True, name=f"LSP-{client_info['key']}")
    thread.start()


class SyntaxHighlight:
    def __init__(
        self, source_code: str, file_path: Optional[str] = None, lang_type: Optional[str] = None, theme: str = "default"
    ):
        self.source_code = source_code
        self.lexer = None
        self.theme = theme
        try:
            if lang_type:
                self.lexer = lexers.get_lexer_by_name(lang_type)
            elif file_path:
                self.lexer = lexers.get_lexer_for_filename(file_path)
        except Exception:
            self.lexer = lexers.get_lexer_by_name("text")
        if not self.lexer:
            raise ValueError("Could not determine language type.")

    def render(self) -> str:
        formatter = formatters.Terminal256Formatter(style=self.theme)
        return highlight(self.source_code, self.lexer, formatter)

    @staticmethod
    def highlight_if_terminal(
        source_code: str, file_path: Optional[str] = None, lang_type: Optional[str] = None, theme: str = "default"
    ) -> str:
        if sys.stdout.isatty():
            return SyntaxHighlight(source_code, file_path, lang_type, theme).render()
        return source_code


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    arg_parser = argparse.ArgumentParser(description="Code Analysis and Interaction Tool")
    arg_parser.add_argument("--host", type=str, default="127.0.0.1", help="HTTP server host")
    arg_parser.add_argument("--port", type=int, default=8000, help="HTTP server port")
    arg_parser.add_argument("--project", type=str, nargs="+", default=["."], help="Project root directories")
    arg_parser.add_argument("--debug-symbol-path", type=str, help="Print symbol paths for a given file")
    arg_parser.add_argument("--debug-skeleton", type=str, help="Generate and print a source code skeleton for a file")
    arg_parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set logging level",
    )
    arg_parser.add_argument("--lsp", type=str, help="启动LSP客户端，指定LSP服务器命令（如：pylsp）")
    arg_parser.add_argument("--debugger-port", type=int, default=9911, help="调试器服务端口")
    args = arg_parser.parse_args()
    logger.setLevel(args.log_level.upper())
    if args.lsp:
        start_lsp_client_once(GLOBAL_PROJECT_CONFIG, GLOBAL_PROJECT_CONFIG.project_root_dir)
    if args.debug_symbol_path:
        logger.info("Debug Mode: Printing symbol paths for %s", args.debug_symbol_path)
        parser_loader = ParserLoader()
        parser_util = ParserUtil(parser_loader)
        parser_util.print_symbol_paths(args.debug_symbol_path)
    elif args.debug_skeleton:
        logger.info("Debug Mode: Generating skeleton for %s", args.debug_skeleton)
        parser_loader = ParserLoader()
        skeleton = SourceSkeleton(parser_loader)
        framework = skeleton.generate_framework(args.debug_skeleton)
        print(SyntaxHighlight.highlight_if_terminal(framework, file_path=args.debug_skeleton))
    else:
        logger.info("Starting Code Analysis Service...")
        main(host=args.host, port=args.port, project_paths=args.project)
