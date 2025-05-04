import argparse
import asyncio
import fnmatch
import hashlib
import importlib
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import typing
import zlib
from abc import ABC, abstractmethod
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import unified_diff
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import unquote, urlparse

from debugger.tracer import TraceConfig, start_trace
import yaml

# Windows控制台颜色修复
from colorama import just_fix_windows_console
from fastapi import Body, FastAPI, Form, HTTPException
from fastapi import Query as QueryArgs
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from pygments import formatters, highlight, lexers, styles
from tqdm import tqdm  # 用于显示进度条
from tree_sitter import Language, Node, Parser, Query

from lsp.client import GenericLSPClient, LSPFeatureError
from lsp.language_id import LanguageId

just_fix_windows_console()

# 设置日志级别
logger = logging.getLogger(__name__)

# 定义语言名称常量
C_LANG = "c"
PYTHON_LANG = "python"
JAVASCRIPT_LANG = "javascript"
TYPESCRIPT_LANG = "typescript"
TYPESCRIPT_TSX_LANG = "typescript_tsx"
JAVA_LANG = "java"
GO_LANG = "go"
SHELL_LANG = "bash"
CPP_LANG = "cpp"

# 文件后缀到语言名称的映射
SUPPORTED_LANGUAGES = {
    ".c": C_LANG,
    ".h": C_LANG,
    ".py": PYTHON_LANG,
    ".js": JAVASCRIPT_LANG,
    ".ts": TYPESCRIPT_LANG,
    ".tsx": TYPESCRIPT_TSX_LANG,
    ".java": JAVA_LANG,
    ".go": GO_LANG,
    ".sh": SHELL_LANG,
    ".cpp": CPP_LANG,
    ".cc": CPP_LANG,
}

# 各语言的查询语句映射
LANGUAGE_QUERIES = {
    "c": r"""
[
    (function_definition
        type: _ @function.return_type
        declarator: (function_declarator
            declarator: (identifier) @function.name
            parameters: (parameter_list) @function.params
        )
        body: (compound_statement) @function.body
    )
    (function_definition
        type: _ @function.return_type
        declarator: (pointer_declarator
            declarator: (function_declarator
                declarator: (identifier) @function.name
                parameters: (parameter_list) @function.params
            )
        )
        body: (compound_statement) @function.body
    )
]
(
    (call_expression
        function: (identifier) @called_function
        (#not-match? @called_function "^(__builtin_|typeof$)")
    ) @call
)
    """,
    "python": r"""
[
(module
  (expression_statement
  (assignment
    left: _ @left
    ) @assignment
  )
)

(class_definition
	name: (identifier) @class-name
    superclasses: (argument_list) ?
    body: (block
        [(decorated_definition
            _ * @method.decorator
            (function_definition
                "async"? @method.async
                "def" @method.def
                name: _ @method.name
                parameters: _ @method.params
                body: _ @method.body
            )
        )
        (function_definition
                "async"? @method.async
                "def" @method.def
                name: _ @method.name
                parameters: _ @method.params
                body: _ @method.body
            )
        ]*  @functions
    ) @class-body
) @class

(decorated_definition
    _ * @function-decorator
    (function_definition
        "async"? @function.async
        "def" @function.def
        name: _ @function.name
        parameters: (parameters
        ) @function.params
        body: (block) @function.body
        (#not-match? @function.params "\((self|cls).*\)")
    )
) @function-full

(module
(function_definition
    "async"? @function.async
    "def" @function.def
    name: _ @function.name
    parameters: (parameters
    ) @function.params
    body: (block) @function.body
    (#not-match? @function.params "\((self|cls).*\)")
) @function-full
)
]
(call
    function: [
        (identifier) @called_function
        (attribute attribute: (identifier) @called_function)
    ]
) @method.call
    """,
    "javascript": """
    [
        (function_declaration
            name: (identifier) @symbol_name
            parameters: (formal_parameters) @params
            body: (statement_block) @body
        )
        (method_definition
            name: (property_identifier) @symbol_name
            parameters: (formal_parameters) @params
            body: (statement_block) @body
        )
    ]
    (
        (call_expression
            function: (identifier) @called_function
        ) @call
        (#contains? @body @call)
    )
    """,
    "java": """
    [
        (method_declaration
            name: (identifier) @symbol_name
            parameters: (formal_parameters) @params
            body: (block) @body
        )
        (class_declaration
            name: (identifier) @symbol_name
            body: (class_body) @body
        )
    ]
    (
        (method_invocation
            name: (identifier) @called_function
        ) @call
        (#contains? @body @call)
    )
    """,
    "go": """
    [
        (function_declaration
            name: (identifier) @symbol_name
            parameters: (parameter_list) @params
            result: (_)? @return_type
            body: (block) @body
        )
        (method_declaration
            name: (field_identifier) @symbol_name
            parameters: (parameter_list) @params
            result: (_)? @return_type
            body: (block) @body
        )
    ]
    (
        (call_expression
            function: (identifier) @called_function
        ) @call
        (#contains? @body @call)
    )
    """,
    "bash": """
    """,
}


LLM_PROJECT_CONFIG = ".llm_project.yml"


class ProjectConfig:
    """强类型的项目配置数据结构"""

    def __init__(
        self,
        project_root_dir: str,
        exclude: Dict[str, List[str]],
        include: Dict[str, List[str]],
        file_types: List[str],
        lsp: Dict[str, Any] = {},
    ):
        self.project_root_dir = project_root_dir
        self.exclude = exclude
        self.include = include
        self.file_types = file_types
        self.lsp = lsp
        self._lsp_clients: Dict[str, Any] = {}
        self._lsp_lock = threading.Lock()
        self.symbol_service_url: Optional[str] = None
        self._config_file_path: Optional[Path] = None

    def relative_path(self, path: Path) -> str:
        """获取相对于项目根目录的路径"""
        try:
            return str(path.relative_to(self.project_root_dir))
        except ValueError:
            return str(path)

    def relative_to_current_path(self, path: Path) -> str:
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
                "dirs": list(
                    set(self._default_config.exclude["dirs"] + user_config.get("exclude", {}).get("dirs", []))
                ),
                "files": list(
                    set(self._default_config.exclude["files"] + user_config.get("exclude", {}).get("files", []))
                ),
            },
            include={
                "dirs": list(
                    set(self._default_config.include["dirs"] + user_config.get("include", {}).get("dirs", []))
                ),
                "files": list(
                    set(self._default_config.include["files"] + user_config.get("include", {}).get("files", []))
                ),
            },
            file_types=list(set(self._default_config.file_types + user_config.get("file_types", []))),
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
        self.children = {}  # 字符到子节点的映射
        self.is_end = False  # 是否单词结尾
        self.symbols = []  # 存储符号详细信息（支持同名不同定义的符号）


class SymbolTrie:
    def __init__(self, case_sensitive=True):
        self.root = TrieNode()
        self.case_sensitive = case_sensitive
        self._size = 0  # 记录唯一符号数量

    def _normalize(self, word):
        """统一大小写处理"""
        # return word
        return word if self.case_sensitive else word.lower()

    def insert(self, symbol_name, symbol_info):
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

    def search_exact(self, symbol_path):
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

    def search_prefix(self, prefix, max_results=None, use_bfs=False):
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
        results = []
        if use_bfs:
            self._bfs_collect(node, prefix, results, max_results)
        else:
            self._dfs_collect(node, prefix, results, max_results)
        return results

    def _bfs_collect(self, node, current_prefix, results, max_results):
        """广度优先收集符号

        参数：
            node: 起始节点
            current_prefix: 当前前缀
            results: 结果列表
            max_results: 最大结果数量限制
        """
        from collections import deque

        queue = deque([(node, current_prefix)])

        while queue:
            current_node, current_path = queue.popleft()

            if current_node.is_end:
                for symbol in current_node.symbols:
                    results.append({"name": current_path, "details": symbol})
                    if max_results is not None and len(results) >= max_results:
                        return

            # 按字母顺序入队保证确定性
            for char in sorted(current_node.children.keys()):
                child = current_node.children[char]
                queue.append((child, current_path + char))

    def _dfs_collect(self, node, current_prefix, results, max_results):
        """深度优先收集符号

        参数：
            node: 当前节点
            current_prefix: 当前前缀
            results: 结果列表
            max_results: 最大结果数量限制
        """
        # 如果达到最大结果数量，直接返回
        if max_results is not None and len(results) >= max_results:
            return

        if node.is_end:
            for symbol in node.symbols:
                results.append({"name": current_prefix, "details": symbol})
                # 检查是否达到最大结果数量
                if max_results is not None and len(results) >= max_results:
                    return

        for char, child in node.children.items():
            self._dfs_collect(child, current_prefix + char, results, max_results)

    def to_dict(self):
        """将前缀树转换为包含所有符号的字典"""
        result = {}
        self._collect_all_symbols(self.root, "", result)
        return result

    def _collect_all_symbols(self, node, current_prefix, result):
        """递归收集所有符号"""
        if node.is_end:
            result[current_prefix] = list(node.symbols)

        for char, child in node.children.items():
            self._collect_all_symbols(child, current_prefix + char, result)

    def __str__(self):
        """将前缀树转换为字符串表示，列出所有符号"""
        symbol_dict = self.to_dict()
        output = []
        for symbol_name, symbols in symbol_dict.items():
            for symbol in symbols:
                output.append(f"符号名称: {symbol_name}")
                output.append(f"文件路径: {symbol['file_path']}")
                output.append(f"签名: {symbol['signature']}")
                output.append(f"定义哈希: {symbol['full_definition_hash']}")
                output.append("-" * 40)
        return "\n".join(output)

    @property
    def size(self):
        """返回唯一符号数量"""
        return self._size

    @classmethod
    def from_symbols(cls, symbols_dict, case_sensitive=True):
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


class ParserLoader:
    def __init__(self):
        self._parsers = {}
        self._languages = {}
        self._queries = {}
        self.lang = None

    def _get_language(self, lang_name: str):
        """动态加载对应语言的 Tree-sitter 模块"""
        if lang_name in self._languages:
            return self._languages[lang_name]

        module_name = f"tree_sitter_{lang_name}"
        if lang_name == TYPESCRIPT_LANG:
            module = importlib.import_module("tree_sitter_typescript")
            return getattr(module, "language_typescript")
        elif lang_name == TYPESCRIPT_TSX_LANG:
            module = importlib.import_module("tree_sitter_typescript")
            return getattr(module, "language_tsx")
        else:
            try:
                lang_module = importlib.import_module(module_name)
            except ImportError as exc:
                raise ImportError(
                    f"Language parser for '{lang_name}' not installed. Try: pip install {module_name.replace('_', '-')}"
                ) from exc
            return lang_module.language

    def get_parser(self, file_path: str) -> tuple[Parser, Query, str]:
        """根据文件路径获取对应的解析器和查询对象"""
        suffix = Path(file_path).suffix.lower()
        lang_name = SUPPORTED_LANGUAGES.get(suffix)
        if not lang_name:
            raise ValueError(f"不支持的文件类型: {suffix}")

        if lang_name in self._parsers:
            return self._parsers[lang_name], self._queries[lang_name], lang_name
        self.lang = lang_name

        language = self._get_language(lang_name)
        lang = Language(language())
        lang_parser = Parser(lang)

        # 根据语言类型获取对应的查询语句
        query_source = LANGUAGE_QUERIES.get(lang_name)
        if query_source:
            query = Query(lang, query_source)
            self._queries[lang_name] = query
        else:
            query = None
        self._parsers[lang_name] = lang_parser
        return lang_parser, query, lang_name


class ParserUtil:
    def __init__(self, parser_loader: ParserLoader):
        """初始化解析器工具类"""
        self.parser_loader = parser_loader
        self.node_processor = NodeProcessor()
        self.code_map_builder = CodeMapBuilder(None, self.node_processor, lang=parser_loader.lang)
        self._source_code = None

    def prepare_root_node(self, file_path: str):
        """获取文件的根节点"""
        parser, _, lang_name = self.parser_loader.get_parser(file_path)
        self.node_processor.lang_spec = find_spec_for_lang(lang_name)
        with open(file_path, "rb") as f:
            source_code = f.read()
        self._source_code = source_code
        tree = parser.parse(source_code)
        root_node = tree.root_node
        self.code_map_builder.root_node = root_node
        return root_node

    def get_symbol_paths(self, file_path: str, debug: bool = False):
        """解析代码文件并返回所有符号路径及对应代码和位置信息"""
        root_node = self.prepare_root_node(file_path)
        results = []
        code_map = {}
        if is_node_module(root_node.type) and len(root_node.children) != 0:
            self.code_map_builder.process_import_block(root_node, code_map, self._source_code, results)
        self.code_map_builder.traverse(root_node, [], [], code_map, self._source_code, results)
        return results, code_map

    def update_symbol_trie(self, file_path: str, symbol_trie: SymbolTrie):
        """更新符号前缀树，将文件中的所有符号插入到前缀树中"""
        paths, code_map = self.get_symbol_paths(file_path)
        for path in paths:
            info = code_map[path]
            symbol_info = self.code_map_builder.build_symbol_info(info, file_path)
            symbol_trie.insert(path, symbol_info)

    def find_symbols_by_location(self, code_map: dict, line: int, column: int) -> list[dict]:
        """根据行列位置查找对应的符号信息列表，按嵌套层次排序（最内层在前）"""
        return self.code_map_builder.find_symbols_by_location(code_map, line, column)

    def find_symbols_for_locations(
        self,
        code_map: dict,
        locations: list[tuple[int, int]],
        max_context_size: int = 16 * 1024,
    ) -> dict[str, dict]:
        """批量处理位置并返回符号名到符号信息的映射"""
        return self.code_map_builder.find_symbols_for_locations(code_map, locations, max_context_size)

    def symbol_at_line(self, line: int) -> dict:
        return self.code_map_builder.build_symbol_info_at_line(line)

    def near_symbol_at_line(self, line: int) -> dict:
        return self.code_map_builder.build_near_symbol_info_at_line(line)

    def lookup_symbols(self, file_path: str, symbols: list[str]):
        """根据文件路径列表查找符号"""
        _, code_map = self.get_symbol_paths(file_path)
        m = {}
        n = {}
        for path in symbols:
            path_backup = path
            symbol_info = code_map.get(path, None)
            if symbol_info:
                m[path] = code_map[path]
                m[path]["block_content"] = m[path]["code"].encode("utf-8")
                continue
            for _ in range(path.count(".")):
                path = path[: path.rfind(".")]
                symbol_info = code_map.get(path, None)
                symbol_info["block_content"] = symbol_info["code"].encode("utf-8")
                if symbol_info:
                    n[path_backup] = (path, symbol_info)
                    break
            if not symbol_info:
                # 使用整个文件作为符号信息
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                file_size = len(file_bytes)
                symbol_info = {
                    "block_content": file_bytes,
                    "block_range": (0, file_size),
                    "start_line": 0,
                    "file_path": file_path,
                }
                n[path_backup] = ("module", symbol_info)
        return m, n

    def print_symbol_paths(self, file_path: str):
        """打印文件中的所有符号路径及对应代码和位置信息"""
        paths, code_map = self.get_symbol_paths(file_path)
        for path in paths:
            info = code_map[path]
            print(
                f"{path}:\n"
                f"代码位置: 第{info['start_line'] + 1}行{info['start_col'] + 1}列 "
                f"到 第{info['end_line'] + 1}行{info['end_col'] + 1}列\n"
                f"调用列表: {[call['name'] for call in info['calls']]}\n"
                f"代码内容:\n{info['code']}\n"
            )


class BaseNodeProcessor(ABC):
    """抽象基类，包含通用节点处理方法"""

    @staticmethod
    def find_child_by_type(node, target_type):
        """在节点子节点中查找指定类型的节点"""
        for child in node.children:
            if child.type == target_type:
                return child
        return None

    @staticmethod
    def find_child_by_field(node, field_name):
        """根据字段名查找子节点"""
        for child in node.children:
            if child.type == field_name:
                return child
        return None

    @staticmethod
    def find_identifier_in_node(node):
        """在节点中查找identifier节点"""
        for child in node.children:
            if child.type == NodeTypes.IDENTIFIER:
                return child.text.decode("utf8")
        return None

    @staticmethod
    def get_full_attribute_name(node):
        """递归获取属性调用的完整名称"""
        if node.type == NodeTypes.IDENTIFIER:
            return node.text.decode("utf8")
        if node.type == NodeTypes.ATTRIBUTE:
            obj_part = BaseNodeProcessor.get_full_attribute_name(node.child_by_field_name("object"))
            attr_part = node.child_by_field_name("attribute").text.decode("utf8")
            return f"{obj_part}.{attr_part}"
        return ""

    @staticmethod
    def get_function_name_from_call(function_node):
        """从函数调用节点中提取函数名"""
        if function_node.type == NodeTypes.IDENTIFIER:
            return function_node.text.decode("utf8")
        if function_node.type == NodeTypes.ATTRIBUTE:
            return BaseNodeProcessor.get_full_attribute_name(function_node)
        return None

    @staticmethod
    def is_standard_type(type_name: str) -> bool:
        """判断是否是标准库类型或基本类型"""
        basic_types = {
            "typing",
            "int",
            "str",
            "float",
            "bool",
            "list",
            "dict",
            "tuple",
            "set",
            "None",
            "Any",
            "Optional",
            "Union",
            "List",
            "Dict",
            "Tuple",
            "Set",
            "Type",
            "Callable",
            "Iterable",
            "Sequence",
            "Mapping",
            "TypeVar",
            "Generic",
            "Protocol",
            "runtime_checkable",
        }

        if "." in type_name:
            module_part, *rest = type_name.split(".", 1)
            if module_part == "typing":
                try:
                    return getattr(typing, rest[0].split(".", 1)[0]) is not None
                except AttributeError:
                    return False
            return module_part in {"typing", "collections", "abc"}
        return type_name in basic_types


def find_spec_for_lang(lang: str) -> "LangSpec":
    """根据语言名称查找对应的语言特定处理策略"""
    if lang == PYTHON_LANG:
        return PythonSpec()
    elif lang == JAVASCRIPT_LANG:
        return JavascriptSpec()
    elif lang == TYPESCRIPT_LANG or lang == TYPESCRIPT_TSX_LANG:
        return TypeScriptSpec()
    # elif lang == JAVASCRIPT_LANG:
    #     return JavaScriptSpec()
    # elif lang == JAVA_LANG:
    #     return JavaSpec()
    if lang == GO_LANG:
        return GoLangSpec()
    if lang in (CPP_LANG, C_LANG):
        return CPPSpec()
    return None


class LangSpec(ABC):
    """语言特定处理策略接口"""

    @abstractmethod
    def get_symbol_name(self, node: Node) -> str:
        """提取节点的符号名称"""
        raise NotImplementedError("Subclasses must implement get_symbol_name")

    @abstractmethod
    def get_function_name(self, node: Node) -> str:
        raise NotImplementedError("Subclasses must implement get_function_name")


class JavascriptSpec(LangSpec):
    """JavaScript语言特定处理策略"""

    def get_symbol_name(self, node: Node) -> str:
        if node.type == NodeTypes.JS_CLASS_DECLARATION:
            class_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            if not class_name:
                class_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return class_name.text.decode("utf8") if class_name else None

        if node.type == NodeTypes.JS_METHOD_DEFINITION:
            method_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_PROPERTY_IDENTIFIER)
            if method_name:
                return method_name.text.decode("utf8")
            return None

        if node.type == NodeTypes.JS_FUNCTION_DECLARATION:
            func_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            return func_name.text.decode("utf8") if func_name else None

        if node.type == NodeTypes.JS_ARROW_FUNCTION:
            parent = node.parent
            if parent and parent.type == NodeTypes.JS_VARIABLE_DECLARATION:
                return BaseNodeProcessor.find_identifier_in_node(parent)
            return None

        if node.type == NodeTypes.JS_GENERATOR_FUNCTION_DECLARATION:
            func_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            return func_name.text.decode("utf8") if func_name else None

        if node.type == NodeTypes.JS_METHOD_DEFINITION:
            class_node = node.parent
            if class_node and class_node.type == NodeTypes.JS_CLASS_DECLARATION:
                class_name = self.get_symbol_name(class_node)
                property_identifier = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_PROPERTY_IDENTIFIER)
                if property_identifier:
                    method_name = property_identifier.text.decode("utf8")
                    return f"{class_name}.{method_name}" if class_name and method_name else None

        if node.type == NodeTypes.JS_LEXICAL_DECLARATION:
            declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_VARIABLE_DECLARATOR)
            if declarator and BaseNodeProcessor.find_child_by_type(declarator, NodeTypes.JS_FUNCTION_EXPRESSION):
                return BaseNodeProcessor.find_identifier_in_node(declarator)
            if declarator and BaseNodeProcessor.find_child_by_type(declarator, NodeTypes.JS_ARROW_FUNCTION):
                return BaseNodeProcessor.find_identifier_in_node(declarator)
            if declarator and BaseNodeProcessor.find_child_by_type(declarator, NodeTypes.JS_OBJECT):
                return BaseNodeProcessor.find_identifier_in_node(declarator)

        if node.type == NodeTypes.JS_ARROW_FUNCTION:
            parent = node.parent
            if parent and parent.type == NodeTypes.JS_VARIABLE_DECLARATION:
                return BaseNodeProcessor.find_identifier_in_node(parent)

        if node.type == NodeTypes.JS_VARIABLE_DECLARATION:
            return BaseNodeProcessor.find_identifier_in_node(node)

        return None

    def get_function_name(self, node: Node) -> str:
        return self.get_symbol_name(node)


class TypeScriptSpec(JavascriptSpec):
    """TypeScript语言特定处理策略"""

    def get_symbol_name(self, node: Node) -> str:
        if node.type == NodeTypes.TS_NAMESPACE:
            namespace_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            return namespace_name.text.decode("utf8") if namespace_name else None

        if node.type == NodeTypes.TS_ABSTRACT_CLASS_DECLARATION:
            class_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return class_name.text.decode("utf8") if class_name else None

        if node.type == NodeTypes.TS_ABSTRACT_METHOD_SIGNATURE:
            method_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_PROPERTY_IDENTIFIER)
            if method_name:
                return f"{method_name.text.decode('utf8')}" if method_name else None
            return None

        if node.type == NodeTypes.TS_PUBLIC_FIELD_DEFINITION:
            field_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_PROPERTY_IDENTIFIER)
            if field_name:
                return field_name.text.decode("utf8") if field_name else None
            return None

        if node.type == NodeTypes.TS_TYPE_ALIAS_DECLARATION:
            type_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return type_name.text.decode("utf8") if type_name else None

        if node.type == NodeTypes.TS_INTERFACE_DECLARATION:
            interface_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return interface_name.text.decode("utf8") if interface_name else None

        if node.type == NodeTypes.TS_ENUM_DECLARATION:
            enum_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return enum_name.text.decode("utf8") if enum_name else None

        if node.type == NodeTypes.TS_MODULE_DECLARATION:
            module_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return module_name.text.decode("utf8") if module_name else None

        if node.type == NodeTypes.TS_DECLARE_FUNCTION:
            func_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            return func_name.text.decode("utf8") if func_name else None

        return super().get_symbol_name(node)

    def get_function_name(self, node: Node) -> str:
        return self.get_symbol_name(node)


class PythonSpec(LangSpec):
    def get_symbol_name(self, node):
        if node.type == NodeTypes.IF_STATEMENT and self.is_main_block(node):
            return "__main__"
        return None

    def get_function_name(self, node):
        return None

    @staticmethod
    def is_main_block(node):
        """判断是否是__main__块"""
        condition = BaseNodeProcessor.find_child_by_type(node, NodeTypes.COMPARISON_OPERATOR)
        if condition:
            left = BaseNodeProcessor.find_child_by_type(condition, NodeTypes.IDENTIFIER)
            right = BaseNodeProcessor.find_child_by_type(condition, NodeTypes.STRING)
            if left and left.text.decode("utf8") == "__name__" and right and "__main__" in right.text.decode("utf8"):
                return True
        return False


class CPPSpec(LangSpec):
    """C++语言特定处理策略"""

    def get_symbol_name(self, node: Node):
        if node.type in (NodeTypes.CPP_CLASS_SPECIFIER, NodeTypes.C_STRUCT_SPECFIER):
            return self.get_cpp_class_name(node)
        if node.type == NodeTypes.CPP_NAMESPACE_DEFINITION:
            return self.get_cpp_namespace_name(node)
        if node.type == NodeTypes.C_DECLARATION:
            return self.get_cpp_declaration_name(node)
        if node.type == NodeTypes.CPP_FRIEND_DECLARATION:
            return self.get_friend_function_name(node)
        return None

    def get_cpp_class_name(self, node: Node):
        """从C++类定义节点中提取类名"""
        class_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.C_TYPE_IDENTIFIER)
        if class_name:
            return class_name.text.decode("utf8")
        return None

    def get_cpp_namespace_name(self, node: Node):
        """从命名空间定义节点中提取命名空间名称"""
        namespace_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.CPP_NAMESPACE_IDENTIFIER)
        if namespace_name:
            return namespace_name.text.decode("utf8")
        return None

    def get_cpp_declaration_name(self, node: Node):
        """从声明节点中提取限定名称"""
        init_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.CPP_INIT_DECLARATOR)
        if not init_declarator:
            return None

        # 统一处理数组声明和普通声明
        declarator = (
            BaseNodeProcessor.find_child_by_type(init_declarator, NodeTypes.C_ARRAY_DECLARATOR) or init_declarator
        )

        # 尝试获取限定标识符
        qualified_id = BaseNodeProcessor.find_child_by_type(declarator, NodeTypes.CPP_QUALIFIED_IDENTIFIER)
        if qualified_id:
            namespace = BaseNodeProcessor.find_child_by_type(qualified_id, NodeTypes.CPP_NAMESPACE_IDENTIFIER)
            identifier = BaseNodeProcessor.find_child_by_type(qualified_id, NodeTypes.IDENTIFIER)
            if namespace and identifier:
                return f"{namespace.text.decode('utf8')}.{identifier.text.decode('utf8')}"

        return BaseNodeProcessor.find_identifier_in_node(declarator)

    def get_friend_function_name(self, node: Node):
        decl = BaseNodeProcessor.find_child_by_type(node, NodeTypes.C_DECLARATION)
        return self.get_function_name(decl) if decl else None

    def get_function_name(self, node: Node):
        result = None
        pointer_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.C_POINTER_DECLARATOR)
        if pointer_declarator:
            func_declarator = pointer_declarator.child_by_field_name("declarator")
            if func_declarator and func_declarator.type == NodeTypes.FUNCTION_DECLARATOR:
                result = BaseNodeProcessor.find_identifier_in_node(func_declarator)

        if not result:
            reference_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.CPP_REFERENCE_DECLARATOR)
            if reference_declarator:
                func_declarator = BaseNodeProcessor.find_child_by_type(
                    reference_declarator, NodeTypes.FUNCTION_DECLARATOR
                )
                if func_declarator:
                    result = BaseNodeProcessor.find_identifier_in_node(func_declarator)
                    if not result:
                        operator_name = BaseNodeProcessor.find_child_by_type(
                            func_declarator, NodeTypes.CPP_OPERATOR_NAME
                        )
                        if operator_name:
                            result = operator_name.text.decode("utf8")

        if not result:
            func_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.FUNCTION_DECLARATOR)
            if func_declarator:
                qualified_id = BaseNodeProcessor.find_child_by_type(func_declarator, NodeTypes.CPP_QUALIFIED_IDENTIFIER)
                if qualified_id:
                    namespace = BaseNodeProcessor.find_child_by_type(qualified_id, NodeTypes.CPP_NAMESPACE_IDENTIFIER)
                    identifier = BaseNodeProcessor.find_child_by_type(qualified_id, NodeTypes.IDENTIFIER)
                    if namespace and identifier:
                        result = f"{namespace.text.decode('utf8')}.{identifier.text.decode('utf8')}"
                if not result:
                    result = BaseNodeProcessor.find_identifier_in_node(func_declarator)
                if not result:
                    field = BaseNodeProcessor.find_child_by_type(func_declarator, NodeTypes.CPP_FIELD_IDENTIFIER)
                    if field:
                        result = field.text.decode("utf8")
                if not result:
                    operator_name = BaseNodeProcessor.find_child_by_type(func_declarator, NodeTypes.CPP_OPERATOR_NAME)
                    if operator_name:
                        result = operator_name.text.decode("utf8")

        return result


class GoLangSpec(LangSpec):
    """Go语言特定处理策略"""

    def get_symbol_name(self, node) -> str:
        if node.type == NodeTypes.GO_TYPE_DECLARATION:
            return self.get_go_type_name(node)
        if node.type == NodeTypes.GO_METHOD_DECLARATION:
            return self.get_go_method_name(node)
        if node.type == NodeTypes.GO_FUNC_DECLARATION:
            return self.get_go_function_name(node)
        if node.type == NodeTypes.GO_PACKAGE_CLAUSE:
            return self.get_go_package_name(node)
        return None

    def get_function_name(self, node):
        pass

    @staticmethod
    def get_go_method_name(node):
        """从Go方法声明节点中提取方法名，格式为(ReceiverType).MethodName"""
        find_child = BaseNodeProcessor.find_child_by_type
        parameter_list = find_child(node, NodeTypes.GO_PARAMETER_LIST)
        if not parameter_list:
            return None
        parameter_declaration = find_child(parameter_list, NodeTypes.GO_PARAMETER_DECLARATION)
        if not parameter_declaration:
            return None

        type_node = find_child(parameter_declaration, NodeTypes.GO_TYPE_IDENTIFIER)
        if not type_node:
            pointer_type = find_child(parameter_declaration, NodeTypes.GO_POINTER_TYPE)
            if pointer_type:
                type_node = find_child(pointer_type, NodeTypes.GO_TYPE_IDENTIFIER)
                if not type_node:
                    type_node = find_child(pointer_type, NodeTypes.GO_QUALIFIED_TYPE)
        method_name = None

        # 查找方法名
        func_identifier = find_child(node, NodeTypes.GO_FIELD_IDENTIFIER)
        if func_identifier:
            method_name = func_identifier.text.decode("utf8")

        if not method_name or not type_node:
            return None

        return f"{type_node.text.decode('utf8')}.{method_name}"

    @staticmethod
    def get_go_function_name(node):
        """从Go函数声明节点中提取函数名"""
        func_identifier = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
        if func_identifier:
            return func_identifier.text.decode("utf8")
        return None

    @staticmethod
    def get_go_package_name(node):
        """从Go包声明节点中提取包名"""
        package_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.GO_PACKAGE_IDENTIFIER)
        if package_name:
            return package_name.text.decode("utf8")
        return None

    @staticmethod
    def get_go_type_name(node):
        """从Go类型声明节点中提取类型名"""
        for child in node.children:
            if child.type == NodeTypes.GO_TYPE_SPEC:
                for sub_child in child.children:
                    if sub_child.type == NodeTypes.GO_TYPE_IDENTIFIER:
                        return sub_child.text.decode("utf8")
        return None


class NodeProcessor(BaseNodeProcessor):
    """节点处理器，使用语言特定策略处理节点"""

    def __init__(self, lang_spec: LangSpec = None):
        self.lang_spec = lang_spec

    def get_symbol_name(self, node):
        """提取节点的符号名称"""
        if not hasattr(node, "type"):
            return None
        if node.type == NodeTypes.CLASS_DEFINITION:
            return self.get_class_name(node)
        if node.type in NodeTypes.FUNCTION_DEFINITION:
            return self.get_function_name(node)
        if node.type == NodeTypes.ASSIGNMENT:
            return self.get_assignment_name(node)

        if self.lang_spec:
            return self.lang_spec.get_symbol_name(node)
        return None

    def get_class_name(self, node):
        """从类定义节点中提取类名"""
        for child in node.children:
            if child.type == NodeTypes.IDENTIFIER:
                return child.text.decode("utf8")
        return None

    def get_function_name(self, node):
        """从函数定义节点中提取函数名"""
        if node.type == NodeTypes.FUNCTION_DEFINITION:
            name_node = BaseNodeProcessor.find_child_by_field(node, NodeTypes.NAME)
            if name_node:
                return name_node.text.decode("utf8")
            word_node = BaseNodeProcessor.find_child_by_type(node, NodeTypes.WORD)
            if word_node:
                return word_node.text.decode("utf8")
            identifier_node = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            if identifier_node:
                return identifier_node.text.decode("utf8")
        if self.lang_spec:
            return self.lang_spec.get_function_name(node)
        return BaseNodeProcessor.find_identifier_in_node(node)

    @staticmethod
    def get_assignment_name(node):
        """从赋值节点中提取变量名"""
        identifier = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
        if identifier:
            return identifier.text.decode("utf8")

        left = node.child_by_field_name("left")
        if left and left.type == NodeTypes.IDENTIFIER:
            return left.text.decode("utf8")
        return None


class CodeMapBuilder:
    def __init__(
        self,
        root_node: Node | None,
        node_processor: NodeProcessor,
        lang: str = PYTHON_LANG,
    ):
        self.node_processor = node_processor
        self.lang = lang
        self.root_node = root_node

    def symbol_at_line(self, line: int) -> Node | None:
        """查找指定行开始的第一个语法树节点，使用层级遍历"""
        if not self.root_node:
            return None
        queue = [self.root_node]
        while queue:
            current_node = queue.pop(0)
            start_row, _ = current_node.start_point
            if start_row == line and current_node.parent:
                return current_node
            queue.extend(current_node.children)
        return None

    def build_symbol_info_at_line(self, line: int) -> dict | None:
        """构建指定行符号的完整信息"""
        node = self.symbol_at_line(line)
        if not node:
            return None
        return self.symbol_info_from_node(node)

    def build_near_symbol_info_at_line(self, line: int) -> dict | None:
        """构建指定行附近符号的完整信息"""
        node = self.symbol_at_line(line)
        if not node:
            return None
        while (
            node
            and node.parent
            and node.parent.type != self.root_node.type
            and not NodeTypes.is_structure_tree_node(node.type)
        ):
            node = node.parent
        if not node:
            return None
        return self.symbol_info_from_node(node)

    def symbol_info_from_node(self, node: Node) -> dict:
        """从节点中提取符号信息"""
        node_info = self.get_symbol_range_info(None, node)
        symbol_info = {
            "code": node.text.decode("utf8"),
            "calls": [],
            "signature": "",
            "full_definition_hash": "",
            "type": "block",
            "start_line": node_info["start_point"][0],
            "end_line": node_info["end_point"][0],
            "location": (
                (node_info["start_point"][0], node_info["start_point"][1]),
                (node_info["end_point"][0], node_info["end_point"][1]),
                (node_info["start_byte"], node_info["end_byte"]),
            ),
        }
        return symbol_info

    def _extract_import_block(self, node: Node):
        """提取文件开头的import块，包含注释、字符串字面量和导入语句"""
        import_block = []
        current_node = node
        while current_node and current_node.type in (
            NodeTypes.COMMENT,
            NodeTypes.IMPORT_STATEMENT,
            NodeTypes.IMPORT_FROM_STATEMENT,
            NodeTypes.EXPRESSION_STATEMENT,
            NodeTypes.GO_IMPORT_DECLARATION,
            NodeTypes.GO_PACKAGE_CLAUSE,
        ):
            if current_node.type == NodeTypes.EXPRESSION_STATEMENT:
                if current_node.children[0].type == NodeTypes.STRING:
                    import_block.append(current_node)
            else:
                import_block.append(current_node)
            current_node = current_node.next_sibling
        return import_block

    def _get_effective_node(self, node: Node):
        """获取有效的语法树节点（处理装饰器情况）"""
        if (
            node.type
            in (
                NodeTypes.FUNCTION_DEFINITION,
                NodeTypes.CPP_CLASS_SPECIFIER,
                NodeTypes.TS_INTERFACE_DECLARATION,
                NodeTypes.JS_CLASS_DECLARATION,
            )
            and node.parent
            and node.parent.type
            in (
                NodeTypes.DECORATED_DEFINITION,
                NodeTypes.CPP_TEMPLATE_DECLARATION,
                NodeTypes.TS_EXPORT_STATEMENT,
            )
        ):
            return node.parent
        return node

    def get_symbol_range_info(self, source_bytes: bytes, node: Node):
        """获取节点的代码和位置信息"""
        effective_node = self._get_effective_node(node)
        start_byte = effective_node.start_byte
        start_point = effective_node.start_point
        while node.prev_sibling and node.prev_sibling.type == NodeTypes.COMMENT:
            node = node.prev_sibling
            start_byte = node.start_byte
            start_point = node.start_point
        if source_bytes:
            # 找到行的起始位置
            line_start_byte = source_bytes.rfind(b"\n", 0, start_byte) + 1
            space_ = ord(b" ")
            tab_ = ord(b"\t")
            # 验证从行开始到当前位置都是空白字符
            if line_start_byte < start_byte:
                whitespace = source_bytes[line_start_byte:start_byte]
                if not all([c in (space_, tab_) for c in whitespace]):
                    line_start_byte = start_byte  # 如果不是纯空白，保持原位置
                else:
                    start_byte = line_start_byte
                    start_point = (start_point[0], 0)  # 列位置设为0
        return {
            "start_byte": start_byte,
            "end_byte": effective_node.end_byte,
            "start_point": start_point,
            "end_point": effective_node.end_point,
        }

    def _extract_code(self, source_bytes, start_byte, end_byte):
        """从源字节中提取代码"""
        # 找到行起始位置
        return source_bytes[start_byte:end_byte].decode("utf8")

    def _build_code_map_entry(self, path_key, code, node_info):
        """构建代码映射条目"""
        return {
            "code": code,
            "block_range": (node_info["start_byte"], node_info["end_byte"]),
            "start_line": node_info["start_point"][0],
            "start_col": node_info["start_point"][1],
            "end_line": node_info["end_point"][0],
            "end_col": node_info["end_point"][1],
            "calls": [],
            "type": "unknown",
        }

    def process_import_block(self, node, code_map, source_bytes, results):
        """处理import块"""
        import_block = self._extract_import_block(node.children[0])
        if import_block:
            first_node = import_block[0]
            last_node = import_block[-1]
            node_info = {
                "start_byte": first_node.start_byte,
                "end_byte": last_node.end_byte,
                "start_point": first_node.start_point,
                "end_point": last_node.end_point,
            }
            code = self._extract_code(source_bytes, node_info["start_byte"], node_info["end_byte"])
            code_map["__import__"] = self._build_code_map_entry("__import__", code, node_info)
            code_map["__import__"]["type"] = "import_block"
            results.append("__import__")

    def _process_symbol_node(self, node, current_symbols, current_nodes, code_map, source_bytes, results):
        """处理符号节点，返回处理后的有效节点或None"""
        symbol_name = self.node_processor.get_symbol_name(node)
        if symbol_name is None:
            return None

        type_mapping = {
            NodeTypes.CLASS_DEFINITION: "class",
            NodeTypes.GO_TYPE_DECLARATION: "type",
            NodeTypes.GO_METHOD_DECLARATION: "method",
            NodeTypes.CPP_NAMESPACE_DEFINITION: "namespace",
            NodeTypes.CPP_TEMPLATE_DECLARATION: "template",
            NodeTypes.IF_STATEMENT: "main_block" if PythonSpec.is_main_block(node) else None,
            NodeTypes.GO_IMPORT_DECLARATION: "import_declaration",
            NodeTypes.ASSIGNMENT: "module_variable" if not current_symbols else "variable",
            NodeTypes.GO_PACKAGE_CLAUSE: "package",
            NodeTypes.C_DECLARATION: "declaration",
        }

        symbol_type = type_mapping.get(node.type)
        if symbol_type is None and NodeTypes.is_structure_tree_node(node.type):
            symbol_type = "function"

        if symbol_type is None:
            symbol_type = node.type

        effective_node = self._get_effective_node(node)
        current_symbols.append(symbol_name)
        current_nodes.append(effective_node)

        path_key = ".".join(current_symbols)
        current_node = current_nodes[-1]

        node_info = self.get_symbol_range_info(source_bytes, current_node)
        code = self._extract_code(source_bytes, node_info["start_byte"], node_info["end_byte"])
        code_entry = self._build_code_map_entry(path_key, code, node_info)
        code_entry["type"] = symbol_type
        if path_key in code_map:
            start_line = code_entry["start_line"]
            path_key = f"{path_key}_{start_line}"
        code_map[path_key] = code_entry
        results.append(path_key)
        if node.type == NodeTypes.GO_PACKAGE_CLAUSE:
            return None
        return effective_node

    def _add_call_info(self, func_name, current_symbols, code_map, node):
        """通用方法：添加调用信息到code_map"""
        if func_name and current_symbols:
            current_path = ".".join(current_symbols)
            if current_path in code_map:
                start_line, start_col = node.start_point
                end_line, end_col = node.end_point
                call_info = {
                    "name": func_name,
                    "start_point": (start_line, start_col),
                    "end_point": (end_line, end_col),
                }
                code_map[current_path]["calls"].append(call_info)

    def _extract_function_calls(self, node: Node, current_symbols, code_map):
        """提取函数调用信息并添加到当前符号的calls集合"""
        if node.type == NodeTypes.CALL:
            function_node = node.child_by_field_name("function")
            if function_node:
                func_name = self.node_processor.get_function_name_from_call(function_node)
                self._add_call_info(func_name, current_symbols, code_map, function_node)
        elif node.type == NodeTypes.ATTRIBUTE:
            func_name = self.node_processor.get_full_attribute_name(node)
            self._add_call_info(func_name, current_symbols, code_map, node)
        elif node.type == NodeTypes.C_ATTRIBUTE_DECLARATION:
            return
        elif self.lang in (C_LANG, CPP_LANG) and node.type == NodeTypes.IDENTIFIER:
            self._add_call_info(node.text.decode("utf8"), current_symbols, code_map, node)
        for child in node.children:
            self._extract_function_calls(child, current_symbols, code_map)

    def _extract_parameter_type_calls(self, node, current_symbols, code_map):
        """提取参数的类型注释中的调用信息"""
        if NodeTypes.is_type(node.type):
            type_node = node.child_by_field_name("type")
            if not type_node:
                return
            identifiers = self._collect_type_identifiers(type_node)
            for identifier in identifiers:
                type_name = identifier.text.decode("utf8")
                if not self.node_processor.is_standard_type(type_name):
                    self._add_call_info(type_name, current_symbols, code_map, identifier)

    def _collect_type_identifiers(self, node):
        """递归收集类型节点中的所有标识符"""
        identifiers = []
        if NodeTypes.is_identifier(node.type):
            identifiers.append(node)
        for child in node.children:
            identifiers.extend(self._collect_type_identifiers(child))
        return identifiers

    def traverse(self, node, current_symbols, current_nodes, code_map, source_bytes, results):
        processed_node = self._process_symbol_node(
            node, current_symbols, current_nodes, code_map, source_bytes, results
        )
        if processed_node:
            self._extract_function_calls(processed_node, current_symbols, code_map)
        self._extract_parameter_type_calls(node, current_symbols, code_map)
        for child in node.children:
            self.traverse(child, current_symbols, current_nodes, code_map, source_bytes, results)
        if processed_node:
            current_symbols.pop()
            current_nodes.pop()

    def build_symbol_info(self, info, file_path):
        """构建符号信息字典"""
        full_definition_hash = calculate_crc32_hash(info["code"])
        location = (
            (info["start_line"], info["start_col"]),
            (info["end_line"], info["end_col"]),
            info["block_range"],
        )
        return {
            "file_path": file_path,
            "signature": "",
            "full_definition_hash": full_definition_hash,
            "location": location,
            "calls": info["calls"],
        }

    def find_symbols_by_location(self, code_map: dict, line: int, column: int) -> list[dict]:
        """根据行列位置查找对应的符号信息列表，按嵌套层次排序（最内层在前）"""
        matched_symbols = []

        # 先查找包含位置的符号
        for path, info in code_map.items():
            start_line = info["start_line"]
            start_col = info["start_col"]
            end_line = info["end_line"]
            end_col = info["end_col"]

            if (start_line < line or (start_line == line and start_col <= column)) and (
                line < end_line or (line == end_line and column <= end_col)
            ):
                if info.get("type") == "variable":
                    continue
                matched_symbols.append({"symbol": path, "info": info})

        # 按嵌套深度排序
        matched_symbols.sort(
            key=lambda x: (
                -x["symbol"].count("."),
                x["symbol"].split(".")[-1].startswith("__"),
                x["symbol"],
            )
        )
        return matched_symbols

    def find_symbols_for_locations(
        self,
        code_map: dict,
        locations: list[tuple[int, int]],
        max_context_size: int = 16 * 1024,
    ) -> dict[str, dict]:
        """批量处理位置并返回符号名到符号信息的映射"""
        sorted_symbols = sorted(
            code_map.items(),
            key=lambda item: (
                -item[1]["start_line"],
                -item[1]["start_col"],
                item[1]["end_line"],
                item[1]["end_col"],
            ),
        )
        sorted_locations = sorted(locations, key=lambda loc: (loc[0], loc[1]))

        processed_symbols = {}
        symbol_locations = {}
        total_code_size = 0

        locations = []
        for line, col in sorted_locations:
            current_symbol = None
            for symbol_path, symbol_info in sorted_symbols:
                if symbol_info["type"] == "variable":
                    continue
                s_line = symbol_info["start_line"]
                s_col = symbol_info["start_col"]
                e_line = symbol_info["end_line"]
                e_col = symbol_info["end_col"]

                if (
                    (s_line <= line <= e_line)
                    and (s_col <= col if line == s_line else True)
                    and (col <= e_col if line == e_line else True)
                ):
                    current_symbol = symbol_path
                    break
            if current_symbol:
                locations.append((line, col, current_symbol))
                symbol_info = code_map[current_symbol]
                if symbol_info.get("type") == "function":
                    parts = current_symbol.split(".")
                    if len(parts) > 1:
                        class_path = ".".join(parts[:-1])
                        if class_path in processed_symbols:
                            locations.append((line, col, class_path))
                            continue
                        if class_path in code_map:
                            class_info = code_map[class_path]
                            class_code_length = len(class_info.get("code", ""))
                            if (
                                class_path not in processed_symbols
                                and total_code_size + class_code_length <= max_context_size
                            ):
                                current_symbol = class_path
                                symbol_info = class_info
                                code_length = class_code_length
                                locations.append((line, col, current_symbol))
                if current_symbol not in processed_symbols:
                    code_length = len(symbol_info.get("code", ""))
                    if total_code_size + code_length > max_context_size:
                        logging.warning(f"Context size exceeded {max_context_size} bytes, stopping symbol collection")
                        break
                    processed_symbols[current_symbol] = symbol_info.copy()
                    total_code_size += code_length
            else:
                symbol_info = self.build_near_symbol_info_at_line(line)
                if not symbol_info:
                    continue
                code_length = len(symbol_info.get("code", ""))
                if total_code_size + code_length > max_context_size:
                    logging.warning(f"Context size exceeded {max_context_size} bytes, stopping symbol collection")
                    break
                locations.append((line, col, near_symbol_at_line(line)))
                processed_symbols[near_symbol_at_line(line)] = symbol_info
                total_code_size += code_length
            if total_code_size >= max_context_size:
                break
        for line, col, symbol in locations:
            if symbol not in symbol_locations:
                symbol_locations[symbol] = []
            symbol_locations[symbol].append((line, col))
        for symbol in processed_symbols:
            processed_symbols[symbol]["locations"] = symbol_locations[symbol]
        return processed_symbols


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
    def __init__(self, config: SearchConfig, debug: bool = False, file_list: list[str] = None):
        self.config = config
        self.debug = debug
        self.file_pattern = self._build_file_pattern()
        self.file_list = file_list

    def _build_file_pattern(self) -> str:
        """构建符合ripgrep要求的文件类型匹配模式"""
        predefined = []
        extensions = []
        for ext in self.config.file_types:
            clean_ext = ext.lstrip(".")
            if "/" in clean_ext:  # 处理预定义类型如 'python'
                predefined.append(clean_ext)
            else:
                extensions.append(clean_ext)

        patterns = predefined.copy()
        if extensions:
            patterns.append(f"*.{{{','.join(extensions)}}}")
        return ",".join(patterns)

    def search(self, patterns: List[str], search_root: Path = None) -> List[SearchResult]:
        """Execute ripgrep search with multiple patterns

        Args:
            patterns: List of regex patterns to search
            search_root: 已废弃，使用config中的root_dir

        Returns:
            List of structured search results

        Raises:
            ValueError: If invalid search root or empty patterns
            RuntimeError: If rg command execution fails
        """
        if not patterns:
            raise ValueError("At least one search pattern is required")
        if search_root:
            actual_root = search_root
        else:
            actual_root = self.config.root_dir
        if not actual_root.exists():
            raise ValueError(f"配置的根目录不存在: {actual_root}")

        cmd = self._build_command(patterns, actual_root)
        if self.debug:
            print("调试信息：执行命令:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if self.debug:
            print(result.stdout)
        if result.returncode not in (0, 1):  # trace [subprocess.run, result.returncode]
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
            "--no-ignore",  # 确保遵守我们自己的过滤规则
        ]
        # 添加搜索模式
        for pattern in patterns:
            cmd.extend(["--regexp", pattern])

        if self.file_list:
            cmd.extend(["--follow", "--glob"] + list(self.file_list))
        else:
            # 添加排除目录
            for d in self.config.exclude_dirs:
                cmd.extend(["--glob", f"!{d.replace(os.sep, '/')}/**"])

            # 添加排除文件
            for f in self.config.exclude_files:
                cmd.extend(["--glob", f"!{f.replace(os.sep, '/')}"])

            # 添加包含目录（通过glob实现）
            for d in self.config.include_dirs:
                cmd.extend(["--glob", f"{d.replace(os.sep, '/')}/**"])
            # 最终添加搜索根目录
            cmd.append(str(search_root).replace(os.sep, "/"))
        return cmd

    def _parse_results(self, output: str) -> List[SearchResult]:
        results: Dict[Path, Dict] = {}

        for line in output.splitlines():
            try:
                data = json.loads(line)
                if data["type"] == "begin":
                    path = Path(data["data"]["path"]["text"])
                    if path not in results:
                        results[path] = {"matches": [], "stats": {}}
                elif data["type"] == "match":
                    path = Path(data["data"]["path"]["text"])
                    line_num = data["data"]["line_number"]
                    text = data["data"]["lines"]["text"]
                    for submatch in data["data"]["submatches"]:
                        start = submatch["start"]
                        end = submatch["end"]
                        columns = (start, end)
                        match = Match(line_num, columns, text)
                        if path in results:
                            results[path]["matches"].append(match)
                elif data["type"] == "end":
                    path = Path(data["data"]["path"]["text"])
                    stats = data["data"].get("stats", {})
                    if path in results:
                        results[path]["stats"] = stats
            except (KeyError, json.JSONDecodeError):
                continue

        return [SearchResult(path, entry["matches"], entry["stats"]) for path, entry in results.items()]


def dump_tree(node, indent=0):
    prefix = "  " * indent
    node_text = node.text.decode("utf8") if node.text else ""
    # 或者根据 source_bytes 截取：node_text = source_bytes[node.start_byte:node.end_byte].decode('utf8')
    print(f"{prefix}{node.type} [start:{node.start_byte}, end:{node.end_byte}] '{node_text}'")
    for child in node.children:
        dump_tree(child, indent + 1)


# 定义Tree-sitter节点类型常量
class NodeTypes:
    MODULE = "module"
    TRANSLATION_UNIT = "translation_unit"
    COMPOUND_STATEMENT = "compound_statement"
    CLASS_DEFINITION = "class_definition"
    FUNCTION_DEFINITION = "function_definition"
    DECORATED_DEFINITION = "decorated_definition"
    EXPRESSION_STATEMENT = "expression_statement"
    IMPORT_STATEMENT = "import_statement"
    IMPORT_FROM_STATEMENT = "import_from_statement"
    C_DEFINE = "preproc_def"
    C_INCLUDE = "preproc_include"
    C_DECLARATION = "declaration"
    GO_SOURCE_FILE = "source_file"
    GO_IMPORT_DECLARATION = "import_declaration"
    GO_CONST_DECLARATION = "const_declaration"
    GO_VAR_DECLARATION = "var_declaration"
    GO_TYPE_DECLARATION = "type_declaration"
    GO_FUNC_DECLARATION = "function_declaration"
    GO_METHOD_DECLARATION = "method_declaration"
    GO_PACKAGE_CLAUSE = "package_clause"
    GO_FIELD_IDENTIFIER = "field_identifier"
    GO_PARAMETER_LIST = "parameter_list"
    GO_TYPE_IDENTIFIER = "type_identifier"
    GO_PARAMETER_DECLARATION = "parameter_declaration"
    COMMENT = "comment"
    BLOCK = "block"
    BODY = "body"
    STRING = "string"
    IDENTIFIER = "identifier"
    ASSIGNMENT = "assignment"
    IF_STATEMENT = "if_statement"
    CALL = "call"
    ATTRIBUTE = "attribute"
    NAME = "name"
    WORD = "word"
    C_POINTER_DECLARATOR = "pointer_declarator"
    FUNCTION_DECLARATOR = "function_declarator"
    COMPARISON_OPERATOR = "comparison_operator"
    TYPED_PARAMETER = "typed_parameter"
    TYPED_DEFAULT_PARAMETER = "typed_default_parameter"
    GENERIC_TYPE = "generic_type"
    UNION_TYPE = "union_type"
    GO_IMPORT_SPEC = "import_spec"
    GO_IMPORT_SPEC_LIST = "import_spec_list"
    GO_PACKAGE_IDENTIFIER = "package_identifier"
    GO_INTERPRETED_STRING_LITERAL = "interpreted_string_literal"
    GO_BLANK_IDENTIFIER = "blank_identifier"
    GO_TYPE_SPEC = "type_spec"
    GO_POINTER_TYPE = "pointer_type"
    GO_QUALIFIED_TYPE = "qualified_type"
    CPP_NAMESPACE = "namespace"
    CPP_NAMESPACE_IDENTIFIER = "namespace_identifier"
    CPP_NAMESPACE_DEFINITION = "namespace_definition"
    CPP_CLASS_SPECIFIER = "class_specifier"
    CPP_TEMPLATE_DECLARATION = "template_declaration"
    CPP_ACCESS_SPECIFIER = "access_specifier"
    CPP_FIELD_IDENTIFIER = "field_identifier"
    CPP_FIELD_DEFINITION = "field_definition"
    CPP_INIT_DECLARATOR = "init_declarator"
    CPP_QUALIFIED_IDENTIFIER = "qualified_identifier"
    CPP_REFERENCE_DECLARATOR = "reference_declarator"
    CPP_OPERATOR_NAME = "operator_name"
    C_STRUCT_SPECFIER = "struct_specifier"
    C_TYPE_IDENTIFIER = "type_identifier"
    CPP_FRIEND_DECLARATION = "friend_declaration"
    C_ATTRIBUTE_DECLARATION = "attribute_declaration"
    C_ARRAY_DECLARATOR = "array_declarator"
    JS_FUNCTION_DECLARATION = "function_declaration"
    JS_CLASS_DECLARATION = "class_declaration"
    JS_FUNCTION_EXPRESSION = "function_expression"
    JS_LEXICAL_DECLARATION = "lexical_declaration"
    JS_VARIABLE_DECLARATION = "variable_declaration"
    JS_VARIABLE_DECLARATOR = "variable_declarator"
    JS_ARROW_FUNCTION = "arrow_function"
    JS_GENERATOR_FUNCTION_DECLARATION = "generator_function_declaration"
    JS_METHOD_DEFINITION = "method_definition"
    JS_PROPERTY_IDENTIFIER = "property_identifier"
    JS_OBJECT = "object"
    JS_PROGRAM = "program"
    TS_TYPE_ALIAS_DECLARATION = "type_alias_declaration"
    TS_INTERFACE_DECLARATION = "interface_declaration"
    TS_ENUM_DECLARATION = "enum_declaration"
    TS_MODULE_DECLARATION = "module_declaration"
    TS_DECLARE_FUNCTION = "declare_function"
    TS_ABSTRACT_CLASS_DECLARATION = "abstract_class_declaration"
    TS_ABSTRACT_METHOD_SIGNATURE = "abstract_method_signature"
    TS_PUBLIC_FIELD_DEFINITION = "public_field_definition"
    TS_ACCESSIBILITY_MODIFIER = "accessibility_modifier"
    TS_TYPE_ANNOTATION = "type_annotation"
    TS_PREDEFINED_TYPE = "predefined_type"
    TS_UNION_TYPE = "union_type"
    TS_LITERAL_TYPE = "literal_type"
    TS_OPTIONAL_CHAIN = "optional_chain"
    TS_AS_EXPRESSION = "as_expression"
    TS_SATISFIES_EXPRESSION = "satisfies_expression"
    TS_TYPE_IDENTIFIER = "type_identifier"
    TS_NAMESPACE = "internal_module"
    TS_EXPORT_STATEMENT = "export_statement"

    @staticmethod
    def is_module(node_type):
        return node_type in (
            NodeTypes.MODULE,
            NodeTypes.TRANSLATION_UNIT,
            NodeTypes.GO_SOURCE_FILE,
            NodeTypes.JS_PROGRAM,
            NodeTypes.TS_MODULE_DECLARATION,
        )

    @staticmethod
    def is_import(node_type):
        return node_type in (
            NodeTypes.IMPORT_STATEMENT,
            NodeTypes.IMPORT_FROM_STATEMENT,
            NodeTypes.GO_IMPORT_DECLARATION,
        )

    @staticmethod
    def is_structure_tree_node(node_type):
        return node_type in (
            NodeTypes.C_STRUCT_SPECFIER,
            NodeTypes.CPP_CLASS_SPECIFIER,
            NodeTypes.CPP_TEMPLATE_DECLARATION,
            NodeTypes.CPP_NAMESPACE_DEFINITION,
            NodeTypes.CLASS_DEFINITION,
            NodeTypes.FUNCTION_DEFINITION,
            NodeTypes.DECORATED_DEFINITION,
            NodeTypes.GO_FUNC_DECLARATION,
            NodeTypes.GO_METHOD_DECLARATION,
            NodeTypes.GO_TYPE_DECLARATION,
            NodeTypes.TS_TYPE_ALIAS_DECLARATION,
            NodeTypes.TS_INTERFACE_DECLARATION,
            NodeTypes.TS_ENUM_DECLARATION,
            NodeTypes.TS_ABSTRACT_CLASS_DECLARATION,
        )

    @staticmethod
    def is_statement(node_type):
        return node_type in (
            NodeTypes.EXPRESSION_STATEMENT,
            NodeTypes.IF_STATEMENT,
            NodeTypes.CALL,
            NodeTypes.ASSIGNMENT,
            NodeTypes.TS_AS_EXPRESSION,
            NodeTypes.TS_SATISFIES_EXPRESSION,
        )

    @staticmethod
    def is_identifier(node_type):
        return node_type in (
            NodeTypes.IDENTIFIER,
            NodeTypes.NAME,
            NodeTypes.WORD,
            NodeTypes.GO_PACKAGE_IDENTIFIER,
            NodeTypes.GO_BLANK_IDENTIFIER,
            NodeTypes.GO_TYPE_IDENTIFIER,
            NodeTypes.TS_TYPE_ANNOTATION,
        )

    @staticmethod
    def is_type(node_type):
        return node_type in (
            NodeTypes.TYPED_PARAMETER,
            NodeTypes.TYPED_DEFAULT_PARAMETER,
            NodeTypes.GENERIC_TYPE,
            NodeTypes.UNION_TYPE,
            NodeTypes.TS_UNION_TYPE,
            NodeTypes.TS_LITERAL_TYPE,
            NodeTypes.TS_PREDEFINED_TYPE,
        )


INDENT_UNIT = "    "  # 定义缩进单位


def is_node_module(node_type):
    return NodeTypes.is_module(node_type)


class SourceSkeleton:
    def __init__(self, parser_loader: ParserLoader):
        self.parser_loader = parser_loader

    def _get_docstring(self, node, parent_type: str):
        """根据Tree-sitter节点类型提取文档字符串"""
        if parent_type == NodeTypes.DECORATED_DEFINITION:
            for child in node.children:
                if child.type == NodeTypes.FUNCTION_DEFINITION:
                    node = child
                    parent_type = NodeTypes.FUNCTION_DEFINITION
                    break
        # 模块文档字符串：第一个连续的字符串表达式
        if is_node_module(parent_type):
            if len(node.children) > 1 and node.children[0].type == NodeTypes.EXPRESSION_STATEMENT:
                return node.children[0].text.decode("utf8")

        # 类/函数文档字符串：body中的第一个字符串表达式
        if parent_type in (NodeTypes.CLASS_DEFINITION, NodeTypes.FUNCTION_DEFINITION):
            node = node.child_by_field_name(NodeTypes.BODY)
            if node:
                if (
                    len(node.children) > 1
                    and node.children[0].type == NodeTypes.EXPRESSION_STATEMENT
                    and node.children[0].children[0].type == NodeTypes.STRING
                ):
                    return node.children[0].text.decode("utf8")
        if parent_type in (
            NodeTypes.GO_FUNC_DECLARATION,
            NodeTypes.GO_METHOD_DECLARATION,
        ):
            prev = node.prev_sibling
            comment_all = []
            while prev and prev.type == NodeTypes.COMMENT:
                comment_all.append(prev.text.decode("utf8"))
                prev = prev.prev_sibling
            return "\n".join(reversed(comment_all))
        return None

    def _capture_signature(self, node, source_bytes: bytes) -> str:
        """精确捕获定义签名（基于Tree-sitter解析结构）"""
        start = node.start_byte
        end = 0

        if node.type == NodeTypes.DECORATED_DEFINITION:
            for v in node.children:
                if v.type in (
                    NodeTypes.FUNCTION_DEFINITION,
                    NodeTypes.CLASS_DEFINITION,
                ):
                    for j, v1 in enumerate(v.children):
                        if v1.type == NodeTypes.BLOCK:
                            end = v.children[j - 1].end_byte
                            break
            if end == 0:
                dump_tree(node, source_bytes)
                raise ValueError("unknown ast")
            return source_bytes[start:end].decode("utf8")

        if node.type in (
            NodeTypes.FUNCTION_DEFINITION,
            NodeTypes.CLASS_DEFINITION,
            NodeTypes.GO_FUNC_DECLARATION,
            NodeTypes.GO_METHOD_DECLARATION,
        ):
            for j, v1 in enumerate(node.children):
                if v1.type in (NodeTypes.BLOCK, NodeTypes.COMPOUND_STATEMENT):
                    end = node.children[j - 1].end_byte
                    break
            if end == 0:
                dump_tree(node, source_bytes)
                raise ValueError("unknown ast")
            return source_bytes[start:end].decode("utf8")

        dump_tree(node, source_bytes)
        raise ValueError("unknown ast")

    def _process_node(self, node, source_bytes: bytes, indent=0, lang_name="") -> List[str]:
        """基于Tree-sitter节点类型的处理逻辑"""
        output = []
        indent_str = INDENT_UNIT * indent

        def process_module_node():
            for child in node.children:
                if child.type in [
                    NodeTypes.CLASS_DEFINITION,
                    NodeTypes.FUNCTION_DEFINITION,
                    NodeTypes.IMPORT_FROM_STATEMENT,
                    NodeTypes.EXPRESSION_STATEMENT,
                    NodeTypes.IMPORT_STATEMENT,
                    NodeTypes.DECORATED_DEFINITION,
                    NodeTypes.C_DEFINE,
                    NodeTypes.C_INCLUDE,
                    NodeTypes.C_DECLARATION,
                    NodeTypes.GO_IMPORT_DECLARATION,
                    NodeTypes.GO_CONST_DECLARATION,
                    NodeTypes.GO_TYPE_DECLARATION,
                    NodeTypes.GO_FUNC_DECLARATION,
                    NodeTypes.GO_METHOD_DECLARATION,
                    NodeTypes.GO_PACKAGE_CLAUSE,
                ]:
                    output.extend(self._process_node(child, source_bytes, lang_name=lang_name))

        def process_class_node():
            class_sig = self._capture_signature(node, source_bytes)
            output.append(f"\n{class_sig}")

            docstring = self._get_docstring(node, NodeTypes.CLASS_DEFINITION)
            if docstring:
                output.append(f'{indent_str}{INDENT_UNIT}"""{docstring}"""')

            body = node.child_by_field_name(NodeTypes.BODY)
            if body:
                for member in body.children:
                    if member.type in [
                        NodeTypes.FUNCTION_DEFINITION,
                        NodeTypes.DECORATED_DEFINITION,
                        NodeTypes.GO_IMPORT_DECLARATION,
                        NodeTypes.GO_METHOD_DECLARATION,
                    ]:
                        output.extend(self._process_node(member, source_bytes, indent + 1, lang_name=lang_name))
                    elif member.type == NodeTypes.EXPRESSION_STATEMENT:
                        code = source_bytes[member.start_byte : member.end_byte].decode("utf8")
                        output.append(f"{indent_str}{INDENT_UNIT}{code}")

        def process_function_node():
            if self.is_lang_cstyle(lang_name):
                docstring = self._get_docstring(node, node.type)
                if docstring:
                    output.append(f"{indent_str}{docstring}")

            func_sig = self._capture_signature(node, source_bytes)
            output.append(f"{indent_str}{func_sig}")

            if not self.is_lang_cstyle(lang_name):
                docstring = self._get_docstring(node, node.type)
                if docstring:
                    output.append(f"{indent_str}{INDENT_UNIT}{docstring}")

            if self.is_lang_cstyle(lang_name):
                output.append("{\n    //Placeholder\n}")
            else:
                output.append(f"{indent_str}{INDENT_UNIT}pass  # Placeholder")

        def process_other_node():
            if is_node_module(node.parent.type):
                code = source_bytes[node.start_byte : node.end_byte].decode("utf8")
                output.append(f"{code}")

        # 处理模块级元素
        if is_node_module(node.type):
            process_module_node()
        # 处理类定义
        elif node.type == NodeTypes.CLASS_DEFINITION:
            process_class_node()
        # 处理函数/方法定义
        elif node.type in [
            NodeTypes.FUNCTION_DEFINITION,
            NodeTypes.DECORATED_DEFINITION,
            NodeTypes.GO_FUNC_DECLARATION,
            NodeTypes.GO_METHOD_DECLARATION,
        ]:
            process_function_node()
        # 处理模块级赋值
        elif node.type in (
            NodeTypes.C_DEFINE,
            NodeTypes.GO_IMPORT_DECLARATION,
            NodeTypes.C_INCLUDE,
            NodeTypes.C_DECLARATION,
            NodeTypes.IMPORT_STATEMENT,
            NodeTypes.IMPORT_FROM_STATEMENT,
            NodeTypes.GO_CONST_DECLARATION,
            NodeTypes.GO_TYPE_DECLARATION,
            NodeTypes.GO_PACKAGE_CLAUSE,
        ):
            process_other_node()

        return output

    def is_lang_cstyle(self, lang_name):
        return lang_name in ("c", "cpp", "go", "java")

    def generate_framework(self, file_path: str) -> str:
        """生成符合测试样例结构的框架代码"""
        parser, _, lang_name = self.parser_loader.get_parser(file_path)

        with open(file_path, "rb") as f:
            source_bytes = f.read()

        tree = parser.parse(source_bytes)
        root = tree.root_node
        framework_lines = (
            ["// Auto-generated code skeleton\n"]
            if self.is_lang_cstyle(lang_name)
            else ["# Auto-generated code skeleton\n"]
        )
        framework_content = self._process_node(root, source_bytes, lang_name=lang_name)

        # 合并结果并优化格式
        result = "\n".join(framework_lines + framework_content)
        return re.sub(r"\n{3,}", "\n\n", result).strip() + "\n"
        # 常见二进制文件的magic number


BINARY_MAGIC_NUMBERS = {
    b"\x89PNG",  # PNG
    b"\xff\xd8",  # JPEG
    b"GIF",  # GIF
    b"BM",  # BMP
    b"%PDF",  # PDF
    b"MZ",  # Windows PE executable
    b"\x7fELF",  # ELF executable
    b"PK",  # ZIP
    b"Rar!",  # RAR
    b"\x1f\x8b",  # GZIP
    b"BZh",  # BZIP2
    b"\xfd7zXZ",  # XZ
    b"7z\xbc\xaf\x27\x1c",  # 7-Zip
    b"ITSF",  # CHM
    b"\x49\x44\x33",  # MP3
    b"\x00\x00\x01\xba",  # MPEG
    b"\x00\x00\x01\xb3",  # MPEG video
    b"FLV",  # Flash video
    b"RIFF",  # WAV, AVI
    b"OggS",  # OGG
    b"fLaC",  # FLAC
    b"\x1a\x45\xdf\xa3",  # WebM
    b"\x30\x26\xb2\x75\x8e\x66\xcf\x11",  # WMV, ASF
    b"\x00\x01\x00\x00",  # TrueType font
    b"OTTO",  # OpenType font
    b"wOFF",  # WOFF font
    b"ttcf",  # TrueType collection
    b"\xed\xab\xee\xdb",  # RPM package
    b"\x53\x51\x4c\x69\x74\x65\x20\x66",  # SQLite
    b"\x4d\x5a",  # MS Office documents (DOCX, XLSX etc)
    b"\x50\x4b\x03\x04",  # ZIP-based formats (DOCX, XLSX etc)
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # MS Office legacy (DOC, XLS etc)
    b"\x09\x08\x10\x00\x00\x06\x05\x00",  # Excel
    b"\x09\x08\x10\x00\x00\x06\x05\x00",  # Excel
    b"\x50\x4b\x03\x04\x14\x00\x06\x00",  # OpenDocument
    b"\x25\x50\x44\x46\x2d\x31\x2e",  # PDF
    b"\x46\x4c\x56\x01",  # FLV
    b"\x4d\x54\x68\x64",  # MIDI
    b"\x52\x49\x46\x46",  # WAV, AVI
    b"\x23\x21\x41\x4d\x52",  # AMR
    b"\x23\x21\x53\x49\x4c\x4b",  # SILK
    b"\x4f\x67\x67\x53",  # OGG
    b"\x66\x4c\x61\x43",  # FLAC
    b"\x4d\x34\x41\x20",  # M4A
    b"\x00\x00\x00\x20\x66\x74\x79\x70",  # MP4
    b"\x00\x00\x00\x18\x66\x74\x79\x70",  # 3GP
    b"\x00\x00\x00\x14\x66\x74\x79\x70",  # MOV
    b"\x1a\x45\xdf\xa3",  # WebM
    b"\x30\x26\xb2\x75\x8e\x66\xcf\x11",  # WMV, ASF
    b"\x52\x61\x72\x21\x1a\x07\x00",  # RAR
    b"\x37\x7a\xbc\xaf\x27\x1c",  # 7z
    b"\x53\x5a\x44\x44\x88\xf0\x27\x33",  # SZDD
    b"\x75\x73\x74\x61\x72",  # TAR
    b"\x1f\x9d",  # Z
    b"\x1f\xa0",  # Z
    b"\x42\x5a\x68",  # BZ2
    b"\x50\x4b\x03\x04",  # ZIP
    b"\x50\x4b\x05\x06",  # ZIP (empty archive)
    b"\x50\x4b\x07\x08",  # ZIP (spanned archive)
    b"\x46\x4c\x56\x01",  # FLV
    b"\x4d\x54\x68\x64",  # MIDI
    b"\x52\x49\x46\x46",  # WAV, AVI
    b"\x23\x21\x41\x4d\x52",  # AMR
    b"\x23\x21\x53\x49\x4c\x4b",  # SILK
    b"\x4f\x67\x67\x53",  # OGG
    b"\x66\x4c\x61\x43",  # FLAC
    b"\x4d\x34\x41\x20",  # M4A
    b"\x00\x00\x00\x20\x66\x74\x79\x70",  # MP4
    b"\x00\x00\x00\x18\x66\x74\x79\x70",  # 3GP
    b"\x00\x00\x00\x14\x66\x74\x79\x70",  # MOV
    b"\x1a\x45\xdf\xa3",  # WebM
    b"\x30\x26\xb2\x75\x8e\x66\xcf\x11",  # WMV, ASF
    b"\x52\x61\x72\x21\x1a\x07\x00",  # RAR
    b"\x37\x7a\xbc\xaf\x27\x1c",  # 7z
    b"\x53\x5a\x44\x44\x88\xf0\x27\x33",  # SZDD
    b"\x75\x73\x74\x61\x72",  # TAR
    b"\x1f\x9d",  # Z
    b"\x1f\xa0",  # Z
    b"\x42\x5a\x68",  # BZ2
    b"\x50\x4b\x03\x04",  # ZIP
    b"\x50\x4b\x05\x06",  # ZIP (empty archive)
    b"\x50\x4b\x07\x08",  # ZIP (spanned archive)
}


def find_diff() -> str:
    """
    检查系统PATH中是否存在git工具，支持Windows/Linux/MacOS
    返回diff工具的完整路径
    """
    git_path = shutil.which("git")
    if not git_path:
        return ""

    if git_path.endswith("git.exe") or git_path.endswith("git.EXE"):  # Windows
        return str(Path(git_path).parent.parent / "usr" / "bin" / "diff.exe")
    elif shutil.which("diff"):  # Linux/MacOS
        return shutil.which("diff")
    return ""


def find_patch() -> str:
    """
    检查系统PATH中是否存在git工具，支持Windows/Linux/MacOS
    返回patch工具的完整路径
    """

    git_path = shutil.which("git")
    if not git_path:
        return ""

    if git_path.endswith("git.exe") or git_path.endswith("git.EXE"):  # Windows
        return str(Path(git_path).parent.parent / "usr" / "bin" / "patch.exe")
    elif shutil.which("patch"):  # Linux/MacOS
        return shutil.which("patch")
    return ""


class BlockPatch:
    """用于生成多文件代码块的差异补丁"""

    def __init__(
        self,
        file_paths: list[str],
        patch_ranges: list[tuple],
        block_contents: list[bytes],
        update_contents: list[bytes],
        manual_merge: bool = False,
    ):
        """
        初始化补丁对象（支持多文件）

        参数：
            file_paths: 源文件路径列表
            patch_ranges: 补丁范围列表，每个元素格式为(start_pos, end_pos)
            block_contents: 原始块内容列表(bytes)
            update_contents: 更新后的内容列表(bytes)
        """
        if (
            len(
                {
                    len(file_paths),
                    len(patch_ranges),
                    len(block_contents),
                    len(update_contents),
                }
            )
            != 1
        ):
            raise ValueError("所有参数列表的长度必须一致")
        self.manual_merge = manual_merge
        # 过滤掉没有实际更新的块
        self.file_paths = []
        self.patch_ranges = []
        self.block_contents = []
        self.update_contents = []
        for i, file_path in enumerate(file_paths):
            if block_contents[i] != update_contents[i]:
                self.file_paths.append(file_path)
                self.patch_ranges.append(patch_ranges[i])
                self.block_contents.append(block_contents[i])
                self.update_contents.append(update_contents[i])

        # 如果没有需要更新的块，直接返回
        if not self.file_paths:
            return
        # 按文件路径分组存储源代码
        self.source_codes = {}
        for path in set(self.file_paths):
            with open(path, "rb") as f:
                content = f.read()
                if self._is_binary_file(content):
                    raise ValueError(f"文件 {path} 是二进制文件，拒绝修改以避免不可预测的结果")
                try:
                    # 检测是否为UTF-8编码
                    content.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(f"文件 {path} 不是UTF-8编码，拒绝修改以避免不可预测的结果") from exc
                self.source_codes[path] = content

    def _is_binary_file(self, content: bytes) -> bool:
        """判断文件是否为二进制文件"""
        # 检查文件头是否匹配已知的二进制文件类型
        for magic in BINARY_MAGIC_NUMBERS:
            if content.startswith(magic):
                return True
        return False

    def _validate_ranges(self, ranges: list[tuple[int, int]]) -> None:
        """验证范围列表是否有重叠"""
        # 使用新列表存储已通过检测的range
        checked_ranges = []
        for current_range in ranges:
            # 针对已通过检测的range做暴力检查
            for checked_range in checked_ranges:
                # 检查两个范围是否重叠
                if not (current_range[1] <= checked_range[0] or checked_range[1] <= current_range[0]):
                    raise ValueError(f"替换区间存在重叠：{current_range} 和 {checked_range}")
            # 将当前range加入已通过检测的列表
            checked_ranges.append(current_range)

    def _build_modified_blocks(self, original_code: str, replacements: list) -> list[str]:
        """构建修改后的代码块数组"""
        # 验证所有块内容
        for (start_pos, end_pos), old_content, _ in replacements:
            if start_pos != end_pos:  # 仅对非插入操作进行验证
                selected = original_code[start_pos:end_pos]
                if selected.decode("utf8").strip() != old_content.strip():
                    raise ValueError(f"内容不匹配\n选中内容：{selected}\n传入内容：{old_content}")

        # 检查替换区间是否有重叠
        self._validate_ranges([(start_pos, end_pos) for (start_pos, end_pos), _, _ in replacements])

        # 按起始位置排序替换区间
        replacements.sort(key=lambda x: x[0][0])

        # 初始化变量
        blocks = []
        last_pos = 0

        # 遍历替换区间，拆分原始代码
        for (start_pos, end_pos), old_content, new_content in replacements:
            # 添加替换区间前的代码块
            if last_pos < start_pos:
                blocks.append(original_code[last_pos:start_pos].decode("utf8"))

            # 添加替换区间代码块
            blocks.append(new_content)  # 直接使用新内容，已经是utf8字符串

            # 更新最后位置
            last_pos = end_pos

        # 添加最后一段代码
        if last_pos < len(original_code):
            blocks.append(original_code[last_pos:].decode("utf8"))

        return blocks

    def _generate_system_diff(self, original_file: str, modified_file: str) -> str:
        """使用系统diff工具生成差异"""
        diff_tool = find_diff()
        try:
            # 在Windows上转换为相对路径并处理换行符
            if os.name == "nt":
                original_file = os.path.relpath(original_file)
                modified_file = os.path.relpath(modified_file)
                result = subprocess.run(
                    [
                        diff_tool,
                        "-u",
                        "--strip-trailing-cr",
                        original_file,
                        modified_file,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    encoding="utf8",
                )
            else:
                result = subprocess.run(
                    [diff_tool, "-u", original_file, modified_file],
                    capture_output=True,
                    encoding="utf8",
                    text=True,
                    check=False,
                )
            # 对于diff工具，返回0表示文件相同，返回1表示文件有差异，这都是正常情况
            if result.returncode in (0, 1):
                return result.stdout
            return None
        except FileNotFoundError:
            return None

    def _launch_diff_tool(self, original_path: str, modified_path: str) -> None:
        """启动可视化diff工具进行手动合并"""
        # 优先尝试VS Code，其次vimdiff
        if platform.system() == "Darwin":
            vscode_paths = [
                "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
                "/Applications/VSCode.app/Contents/Resources/app/bin/code",
            ]
            for code_path in vscode_paths:
                if os.path.exists(code_path):
                    subprocess.run([code_path, "-d", original_path, modified_path], check=True)
                    print("请在VS Code中完成合并，完成后请按回车继续...")
                    input()
                    return
        elif platform.system() == "Windows":
            code_exe = shutil.which("code.exe")
            if code_exe:
                subprocess.run([code_exe, "-d", original_path, modified_path], check=True)
                print("请在VS Code中完成合并，完成后请按回车继续...")
                input()
                return
        else:  # Linux
            if shutil.which("code"):
                subprocess.run(["code", "-d", original_path, modified_path], check=True)
                print("请在VS Code中完成合并，完成后请按回车继续...")
                input()
                return

        # 回退到vimdiff
        if shutil.which("vimdiff"):
            subprocess.run(["vimdiff", original_path, modified_path], check=True)
        else:
            raise RuntimeError("未找到可用的diff工具，请安装VS Code或vim")

    def file_mtime(self, path):
        t = datetime.fromtimestamp(os.stat(path).st_mtime, timezone.utc)
        return t.astimezone().isoformat()

    def _process_single_file_diff(self, file_path: str, indices: list[int]) -> list[str]:
        """处理单个文件的差异生成"""
        original_code = self.source_codes[file_path]

        # 收集所有需要替换的块
        replacements = []
        for idx in indices:
            start_pos, end_pos = self.patch_ranges[idx]
            replacements.append(
                (
                    (start_pos, end_pos),
                    self.block_contents[idx].decode("utf8"),
                    self.update_contents[idx].decode("utf8"),
                )
            )

        # 构建修改后的代码块
        modified_blocks = self._build_modified_blocks(original_code, replacements)
        modified_code = "".join(modified_blocks)

        with (
            tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".original", encoding="utf8") as f_orig,
            tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".modified", encoding="utf8") as f_mod,
        ):
            f_orig.write(original_code.decode("utf8"))
            f_orig_path = f_orig.name
            f_mod.write(modified_code)
            f_mod_path = f_mod.name

        if self.manual_merge:
            self._launch_diff_tool(f_orig_path, f_mod_path)
            # 重新读取用户修改后的内容
            with open(f_mod_path, "rb") as f:
                modified_code = f.read()
            # 更新替换内容
            for idx in indices:
                self.update_contents[idx] = modified_code

        system_diff = self._generate_system_diff(f_orig_path, f_mod_path)

        os.unlink(f_orig_path)
        os.unlink(f_mod_path)

        # 回退到Python实现
        if not system_diff:
            print("系统diff工具不存在，使用python difflib实现")
            diff_lines = list(
                unified_diff(
                    original_code.decode("utf8").splitlines(keepends=True),
                    modified_code.splitlines(keepends=True),
                    fromfile=file_path,
                    tofile=file_path,
                    fromfiledate=self.file_mtime(f_orig_path),
                    tofiledate=self.file_mtime(f_mod_path),
                )
            )
            # Add newline character to lines starting with --- or +++
            for i, line in enumerate(diff_lines):
                if line.startswith("---") or line.startswith("+++"):
                    diff_lines[i] = line + "\n"
            return diff_lines

        # 调整系统diff输出中的文件路径
        diff_lines = []
        for line in system_diff.splitlines(keepends=True):
            if line.startswith("--- ") or line.startswith("+++ "):
                if "\t" in line:
                    first, timestamp = line.split("\t")
                    diff_lines.append(f"{first.split()[0]} {file_path}\t{timestamp}")
                else:
                    diff_lines.append(f"{line.split()[0]} {file_path}")
            else:
                diff_lines.append(line)

        return diff_lines

    def generate_diff(self) -> str:
        """生成多文件差异补丁"""
        if not self.file_paths:
            return {}

        # 按文件分组处理
        file_groups = defaultdict(list)
        for idx, path in enumerate(self.file_paths):
            file_groups[path].append(idx)
        m = {}
        for file_path, indices in file_groups.items():
            m[file_path] = "".join(self._process_single_file_diff(file_path, indices))
        return m

    def _process_single_file_patch(self, file_path: str, indices: list[int]) -> bytes:
        """处理单个文件的补丁应用"""
        original_code = self.source_codes[file_path]

        # 收集所有需要替换的块
        replacements = []
        for idx in indices:
            start_pos, end_pos = self.patch_ranges[idx]
            replacements.append(
                (
                    (start_pos, end_pos),
                    self.block_contents[idx].decode("utf8"),
                    self.update_contents[idx].decode("utf8"),
                )
            )

        # 构建修改后的代码块
        modified_blocks = self._build_modified_blocks(original_code, replacements)
        return "".join(modified_blocks).encode("utf8")

    def apply_patch(self) -> dict[str, bytes]:
        """应用多文件补丁，返回修改后的代码字典"""
        if not self.file_paths:
            return {}

        patched_files = {}
        # 按文件分组处理
        file_groups = defaultdict(list)
        for idx, path in enumerate(self.file_paths):
            file_groups[path].append(idx)

        for file_path, indices in file_groups.items():
            patched_files[file_path] = self._process_single_file_patch(file_path, indices)

        return patched_files


def split_source(source: str, start_row: int, start_col: int, end_row: int, end_col: int) -> tuple[str, str, str]:
    """
    根据行列位置将源代码分割为三段

    参数：
        source: 原始源代码字符串
        start_row: 起始行号(0-based)
        start_col: 起始列号(0-based)
        end_row: 结束行号(0-based)
        end_col: 结束列号(0-based)

    返回：
        tuple: (前段内容, 选中内容, 后段内容)
    """
    lines = source.splitlines(keepends=True)
    if not lines:
        return ("", "", "") if source == "" else (source, "", "")

    # 处理越界行号
    max_row = len(lines) - 1
    start_row = max(0, min(start_row, max_row))
    end_row = max(0, min(end_row, max_row))

    # 计算行列位置对应的绝对字节偏移
    def calc_pos(row: int, col: int) -> int:
        line = lines[row]
        # 列号限制在[0, 当前行长度]范围内
        clamped_col = max(0, min(col, len(line)))
        # 计算该行之前的累计长度
        prev_lines_len = sum(len(line) for line in lines[:row])
        return prev_lines_len + clamped_col

    # 获取实际偏移位置
    start_pos = calc_pos(start_row, start_col)
    end_pos = calc_pos(end_row, end_col)

    # 确保顺序正确
    if start_pos > end_pos:
        start_pos, end_pos = end_pos, start_pos

    return (source[:start_pos], source[start_pos:end_pos], source[end_pos:])


def get_node_segment(code: str, node) -> tuple[str, str, str]:
    """根据AST节点获取代码分段"""
    start_row = node.start_point[0]
    start_col = node.start_point[1]
    end_row = node.end_point[0]
    end_col = node.end_point[1]
    return split_source(code, start_row, start_col, end_row, end_col)


def safe_replace(code: str, new_code: str, start: tuple[int, int], end: tuple[int, int]) -> str:
    """安全替换代码段"""
    before, _, after = split_source(code, *start, *end)
    return before + new_code + after


def test_split_source_and_patch():
    """使用tree-sitter验证代码提取功能"""
    pass


def parse_code_file(file_path, lang_parser):
    """解析代码文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()
    tree = lang_parser.parse(bytes(code, "utf-8"))
    # 打印调试信息
    # print("解析树结构：")
    # print(tree.root_node)
    # print("\n代码内容：")
    # print(code)
    return tree


def get_code_from_node(code, node):
    """根据Node对象提取代码片段"""
    return code[node.start_byte : node.end_byte]


# import pprint


def captures_dump(captures):
    # 结构化输出captures字典内容，用于调试
    print("===========\nCaptures 字典内容：")
    for key, nodes in captures.items():
        print(f"Key: {key}")
        for i, node in enumerate(nodes):
            # 输出节点文本内容及其位置范围
            print(f"  Node {i}: {node.text.decode('utf-8')} (位置: {node.start_point} -> {node.end_point})")


def process_matches(matches: List[Tuple[Any, Dict]], lang_name: str) -> Dict:
    """处理查询匹配结果，支持多语言符号提取"""
    symbols: Dict = {}
    block_array: List[Tuple] = []
    function_calls: List = []

    for match in matches:
        _, captures = match
        if not captures:
            continue

        if "class-name" in captures:
            process_class_definition(captures, symbols, block_array)
        elif "function.name" in captures:
            process_function_definition(captures, lang_name, symbols, block_array)
        elif "called_function" in captures:
            function_calls.append(captures)

    process_function_calls(function_calls, block_array, symbols)
    return symbols


def process_class_definition(captures: Dict, symbols: Dict, block_array: List) -> None:
    """处理类定义及其方法"""
    class_node = captures["class-name"][0]
    class_name = class_node.text.decode("utf-8")
    class_def_node = captures["class"][0]

    symbols[class_name] = {
        "type": "class",
        "signature": f"class {class_name}",
        "calls": [],
        "methods": [],
        "full_definition": class_def_node.text.decode("utf8"),
    }

    async_lines = [x.start_point[0] for x in captures.get("method.async", [])]

    for i, _ in enumerate(captures.get("method.name", [])):
        process_class_method(captures, i, async_lines, class_name, symbols, block_array)


def process_class_method(
    captures: Dict,
    index: int,
    async_lines: List[int],
    class_name: str,
    symbols: Dict,
    block_array: List,
) -> None:
    """处理类方法"""
    method_node = captures["method.name"][index]
    method_name = method_node.text.decode("utf-8")
    symbol_name = f"{class_name}.{method_name}"

    decorators = extract_decorators(captures.get("method.decorator", []))
    is_async = check_async_status(captures["method.def"][index], async_lines)

    params_node = captures["method.params"][index]
    body_node = captures["method.body"][index]

    async_prefix = "async " if is_async else ""
    signature = f"{async_prefix}def {symbol_name}{params_node.text.decode('utf-8')}:"

    symbols[class_name]["methods"].append(signature)
    symbols[symbol_name] = {
        "type": "method",
        "signature": signature,
        "body": body_node.text.decode("utf-8"),
        "full_definition": captures["functions"][index].text.decode("utf8"),
        "calls": [],
        "decorators": decorators,
    }
    block_array.append((symbol_name, body_node.start_point, body_node.end_point))


def process_function_definition(captures: Dict, lang_name: str, symbols: Dict, block_array: List) -> None:
    """分发函数处理逻辑"""
    if lang_name == C_LANG:
        process_c_function(captures, symbols, block_array)
    elif lang_name == PYTHON_LANG:
        process_python_function(captures, symbols, block_array)


def process_c_function(captures: Dict, symbols: Dict, block_array: List) -> None:
    """处理C语言函数"""
    function_node = captures["function.name"][0]
    return_type_node = captures["function.return_type"][0]
    params_node = captures["function.params"][0]
    body_node = captures["function.body"][0]

    function_name = function_node.text.decode("utf-8")
    signature = f"{return_type_node.text.decode('utf-8')} {function_name}{params_node.text.decode('utf-8')}"

    symbols[function_name] = {
        "type": "function",
        "signature": signature,
        "body": body_node.text.decode("utf-8"),
        "full_definition": f"{signature} {{\n{body_node.text.decode('utf-8')}\n}}",
        "calls": [],
    }
    block_array.append((function_name, body_node.start_point, body_node.end_point))


def process_python_function(captures: Dict, symbols: Dict, block_array: List) -> None:
    """处理Python函数"""
    function_node = captures["function.name"][0]
    function_name = function_node.text.decode("utf-8")

    decorators = extract_decorators(captures.get("function.decorator", []))
    is_async = "function.async" in captures
    params_node = captures["function.params"][0]
    body_node = captures["function.body"][0]

    async_prefix = "async " if is_async else ""
    signature = f"{async_prefix}def {function_name}{params_node.text.decode('utf-8')}:"

    symbols[function_name] = {
        "type": "function",
        "signature": signature,
        "body": body_node.text.decode("utf-8"),
        "full_definition": captures["function-full"][0].text.decode("utf8"),
        "calls": [],
        "async": is_async,
        "decorators": decorators,
    }
    block_array.append((function_name, body_node.start_point, body_node.end_point))


def process_function_calls(function_calls: List, block_array: List, symbols: Dict) -> None:
    """处理函数调用关系"""
    block_array.sort(key=lambda x: x[1][0])

    for call in function_calls:
        called_node = call["called_function"][0]
        called_func = called_node.text.decode("utf-8")
        called_line = called_node.start_point[0]

        containing_blocks = find_containing_blocks(called_line, block_array)

        for symbol_name, start, end in containing_blocks:
            if is_within_block(called_node, start, end):
                update_symbol_calls(symbol_name, called_func, symbols)


def find_containing_blocks(line: int, blocks: List) -> List:
    """使用二分查找定位包含指定行的代码块"""
    left, right = 0, len(blocks) - 1
    found = []

    while left <= right:
        mid = (left + right) // 2
        block_start = blocks[mid][1][0]
        block_end = blocks[mid][2][0]

        if block_start <= line <= block_end:
            found.extend(collect_adjacent_blocks(mid, line, blocks))
            break
        if line < block_start:
            right = mid - 1
        else:
            left = mid + 1
    return found


def collect_adjacent_blocks(mid: int, line: int, blocks: List) -> List:
    """收集相邻的可能包含指定行的代码块"""
    collected = [blocks[mid]]

    # 向左收集
    i = mid - 1
    while i >= 0 and blocks[i][1][0] <= line <= blocks[i][2][0]:
        collected.append(blocks[i])
        i -= 1

    # 向右收集
    i = mid + 1
    while i < len(blocks) and blocks[i][1][0] <= line <= blocks[i][2][0]:
        collected.append(blocks[i])
        i += 1

    return collected


def is_within_block(node: Any, start: Tuple[int, int], end: Tuple[int, int]) -> bool:
    """检查节点是否完全包含在代码块范围内"""
    node_start = node.start_point
    node_end = node.end_point

    # 检查行号范围
    if not start[0] <= node_start[0] <= end[0]:
        return False

    # 检查起始行首列
    if node_start[0] == start[0] and node_start[1] < start[1]:
        return False

    # 检查结束行尾列
    if node_end[0] == end[0] and node_end[1] > end[1]:
        return False

    return True


def update_symbol_calls(symbol_name: str, called_func: str, symbols: Dict) -> None:
    """更新符号的调用关系"""
    if symbol_name in symbols and called_func not in symbols[symbol_name]["calls"]:
        symbols[symbol_name]["calls"].append(called_func)


def extract_decorators(decorator_nodes: List) -> List[str]:
    """提取装饰器列表"""
    return [node.text.decode("utf-8") for node in decorator_nodes]


def check_async_status(def_node: Any, async_lines: List[int]) -> bool:
    """检查是否为异步函数"""
    return def_node.start_point[0] in async_lines


def generate_mermaid_dependency_graph(symbols):
    """生成 Mermaid 格式的依赖关系图"""
    mermaid_graph = "graph TD\n"

    for name, details in symbols.items():
        if details["type"] == "function":
            mermaid_graph += f"    {name}[{name}]\n"
            for called_func in details["calls"]:
                if called_func in symbols:
                    mermaid_graph += f"    {name} --> {called_func}\n"
                else:
                    mermaid_graph += f"    {name} --> {called_func}[未定义函数]\n"

    return mermaid_graph


def print_mermaid_dependency_graph(symbols):
    """打印 Mermaid 格式的依赖关系图"""
    print("\nMermaid 依赖关系图：")
    print(generate_mermaid_dependency_graph(symbols))
    print("\n提示：可以将上述输出复制到支持 Mermaid 的 Markdown 编辑器中查看图形化结果")


def generate_json_output(symbols):
    """生成 JSON 格式的输出"""
    output = {"symbols": [{"name": name, **details} for name, details in symbols.items()]}
    return json.dumps(output, indent=2)


def find_symbol_call_chain(symbols, start_symbol):
    """查找并打印指定符号的调用链"""
    if start_symbol in symbols and symbols[start_symbol]["type"] == "function":
        print(f"\n{start_symbol} 函数调用链：")
        for called_func in symbols[start_symbol]["calls"]:
            if called_func in symbols:
                print(f"\n{called_func} 函数的完整定义：")
                print(symbols[called_func]["full_definition"])
            else:
                print(f"\n警告：函数 {called_func} 未找到定义")


def print_main_call_chain(symbols):
    """打印 main 函数调用链"""
    find_symbol_call_chain(symbols, "main")


def demo_main():
    """主函数，用于演示功能"""
    # 初始化解析器加载器
    parser_loader = ParserLoader()

    # 获取解析器和查询对象
    lang_parser, query, lang_name = parser_loader.get_parser("test.c")

    # 解析代码文件
    tree = parse_code_file("test-code-files/test.c", lang_parser)

    # 执行查询并处理结果
    matches = query.matches(tree.root_node)
    symbols = process_matches(matches, lang_name)

    # 生成并打印 JSON 输出
    output = generate_json_output(symbols)
    print(output)
    print(generate_mermaid_dependency_graph(symbols))
    # 打印 main 函数调用链
    print_main_call_chain(symbols)


app = FastAPI()

# 全局数据库连接
GLOBAL_DB_CONN = None
DEFAULT_DB = "symbols.db"


def get_db_connection():
    """获取全局数据库连接"""
    global GLOBAL_DB_CONN
    if GLOBAL_DB_CONN is None:
        GLOBAL_DB_CONN = init_symbol_database(DEFAULT_DB)
    return GLOBAL_DB_CONN


class SymbolInfo(BaseModel):
    """符号信息模型"""

    name: str
    file_path: str
    type: str
    signature: str
    body: str
    full_definition: str
    calls: List[str]


def init_symbol_database(db_path: Union[str, sqlite3.Connection] = "symbols.db"):
    """初始化符号数据库
    支持传入数据库路径或已存在的数据库连接对象
    """
    if isinstance(db_path, sqlite3.Connection):
        conn = db_path
    else:
        conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 创建符号表
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            type TEXT NOT NULL,
            signature TEXT NOT NULL,
            body TEXT NOT NULL,
            full_definition TEXT NOT NULL,
            full_definition_hash INTEGER NOT NULL,
            calls TEXT,
            UNIQUE(name, file_path)
        )
    """
    )

    # 创建文件元数据表
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS file_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL UNIQUE,
            last_modified REAL NOT NULL,
            file_hash TEXT NOT NULL,
            total_symbols INTEGER DEFAULT 0
        )
    """
    )

    # 创建索引以优化查询性能
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_symbols_name
        ON symbols(name)
    """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_symbols_file
        ON symbols(file_path)
    """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_file_metadata_path
        ON file_metadata(file_path)
    """
    )

    conn.commit()
    return conn


def calculate_crc32_hash(text: str) -> int:
    """计算字符串的CRC32哈希值"""
    return zlib.crc32(text.encode("utf-8"))


def validate_input(value: str, max_length: int = 255) -> str:
    """验证输入参数，防止SQL注入"""
    if not value or len(value) > max_length:
        raise ValueError(f"输入值长度必须在1到{max_length}之间")
    if re.search(r"[;'\"]", value):
        raise ValueError("输入包含非法字符")
    return value.strip()


def insert_symbol(conn, symbol_info: Dict):
    """插入符号信息到数据库，处理唯一性冲突，并更新前缀搜索树"""
    cursor = conn.cursor()
    try:
        # 验证calls字段
        calls = symbol_info.get("calls", [])
        if not isinstance(calls, list):
            raise ValueError("calls字段必须是列表")
        for call in calls:
            validate_input(str(call))

        # 计算完整定义的哈希值
        full_definition_hash = calculate_crc32_hash(symbol_info["full_definition"])

        # 插入符号数据
        cursor.execute(
            """
            INSERT INTO symbols (name, file_path, type, signature, body, full_definition, full_definition_hash, calls)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                symbol_info["name"],
                symbol_info["file_path"],
                symbol_info["type"],
                symbol_info["signature"],
                symbol_info["body"],
                symbol_info["full_definition"],
                full_definition_hash,
                json.dumps(calls),
            ),
        )

        # 将符号插入到前缀树中
        symbol_name = symbol_info["name"]
        trie_info = {
            "name": symbol_name,
            "file_path": symbol_info["file_path"],
            "signature": symbol_info["signature"],
            "full_definition_hash": full_definition_hash,
        }
        app.state.symbol_trie.insert(symbol_name, trie_info)

        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
    except ValueError as e:
        conn.rollback()
        raise ValueError(f"输入数据验证失败: {str(e)}")


def search_symbols(conn, prefix: str, limit: int = 10) -> List[Dict]:
    """根据前缀搜索符号"""
    validate_input(prefix)
    if not 1 <= limit <= 100:
        raise ValueError("limit参数必须在1到100之间")

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT name, file_path FROM symbols
        WHERE name LIKE ? || '%'
        LIMIT ?
    """,
        (prefix, limit),
    )
    return [{"name": row[0], "file_path": row[1]} for row in cursor.fetchall()]


def get_symbol_info_simple(conn, symbol_name: str, file_path: Optional[str] = None) -> List[Dict]:
    """获取符号的简化信息，只返回符号名、文件路径和签名"""
    cursor = conn.cursor()
    if file_path:
        if not symbol_name:
            cursor.execute(
                """
                SELECT name, file_path, signature FROM symbols
                WHERE file_path LIKE ?
                """,
                (f"%{file_path}%",),
            )
        else:
            cursor.execute(
                """
                SELECT name, file_path, signature FROM symbols
                WHERE name = ? AND file_path LIKE ?
                """,
                (symbol_name, f"%{file_path}%"),
            )
    else:
        cursor.execute(
            """
            SELECT name, file_path, signature FROM symbols
            WHERE name = ?
            """,
            (symbol_name,),
        )

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "name": row[0],
                "file_path": row[1],
                "signature": row[2],
            }
        )
    return results


def get_symbol_info(conn, symbol_name: str, file_path: Optional[str] = None) -> List[SymbolInfo]:
    """获取符号的完整信息，返回一个列表"""

    cursor = conn.cursor()
    if file_path:
        if not symbol_name:
            cursor.execute(
                """
                SELECT name, file_path, type, signature, body, full_definition, calls FROM symbols
                WHERE file_path LIKE ?
                """,
                (f"%{file_path}%",),
            )
        else:
            cursor.execute(
                """
                SELECT name, file_path, type, signature, body, full_definition, calls FROM symbols
                WHERE name = ? AND file_path LIKE ?
                """,
                (symbol_name, f"%{file_path}%"),
            )
    else:
        cursor.execute(
            """
            SELECT name, file_path, type, signature, body, full_definition, calls FROM symbols
            WHERE name = ?
            """,
            (symbol_name,),
        )

    results = []
    for row in cursor.fetchall():
        results.append(
            SymbolInfo(
                name=row[0],
                file_path=row[1],
                type=row[2],
                signature=row[3],
                body=row[4],
                full_definition=row[5],
                calls=json.loads(row[6]) if row[6] else [],
            )
        )
    return results


def list_all_files(conn) -> List[str]:
    """获取数据库中所有文件的路径"""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT file_path FROM symbols
        """
    )
    return [row[0] for row in cursor.fetchall()]


@app.get("/symbols/search")
async def search_symbols_api(prefix: str = QueryArgs(..., min_length=1), limit: int = QueryArgs(10, ge=1, le=100)):
    """符号搜索API"""
    try:
        validate_input(prefix)
        conn = get_db_connection()
        results = search_symbols(conn, prefix, limit)
        return {"results": results}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/symbols/{symbol_name}")
async def get_symbol_info_api(symbol_name: str, file_path: Optional[str] = QueryArgs(None)):
    """获取符号信息API"""
    try:
        validate_input(symbol_name)
        conn = get_db_connection()
        symbol_infos = get_symbol_info(conn, symbol_name, file_path)
        if symbol_infos:
            return {"results": symbol_infos}
        return {"error": "Symbol not found"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/symbols/path/{path}")
async def get_symbols_by_path_api(path: str):
    """根据路径获取符号信息API"""
    try:
        conn = get_db_connection()
        symbols = get_symbol_info_simple(conn, "", file_path=path)
        return {"results": symbols}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/files")
async def list_files_api():
    """获取所有文件路径API"""
    try:
        conn = get_db_connection()
        files = list_all_files(conn)
        return {"results": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def get_symbol_context(conn, symbol_name: str, file_path: Optional[str] = None, max_depth: int = 2) -> dict:
    """获取符号的调用树上下文（带深度限制）"""
    validate_input(symbol_name)
    if max_depth < 0 or max_depth > 10:
        raise ValueError("深度值必须在0到10之间")

    cursor = conn.cursor()
    symbol_dict = {}
    current_symbols = [(symbol_name, file_path)]

    def process_symbol(symbol, path):
        if path:
            query = "SELECT name, file_path, calls FROM symbols WHERE name = ? AND file_path LIKE ?"
            params = (symbol, f"%{path}%")
        else:
            query = "SELECT name, file_path, calls FROM symbols WHERE name = ?"
            params = (symbol,)
        cursor.execute(query, params)
        return cursor.fetchall()

    def collect_symbols(rows):
        next_symbols = []
        for name, path, calls in rows:
            if name not in symbol_dict or path == file_path:
                symbol_dict[name] = path
            try:
                called_symbols = json.loads(calls)
                next_symbols.extend([(s, path) for s in called_symbols])
            except json.JSONDecodeError:
                continue
        return next_symbols

    for _ in range(max_depth + 1):
        next_symbols = []
        for symbol, path in current_symbols:
            rows = process_symbol(symbol, path)
            if rows:
                next_symbols.extend(collect_symbols(rows))
        current_symbols = list(set(next_symbols))
        if not current_symbols:
            break

    if symbol_name not in symbol_dict:
        return {"error": f"未找到符号 {symbol_name} 的定义"}

    sorted_symbols = sorted(
        symbol_dict.keys(),
        key=lambda x: (
            file_path and symbol_dict[x] != file_path,
            x != symbol_name,
            x,
        ),
    )

    placeholders = ",".join(["?"] * len(sorted_symbols))
    cursor.execute(
        f"""
        SELECT name, file_path, full_definition
        FROM symbols
        WHERE name IN ({placeholders})
        ORDER BY CASE
            WHEN file_path = ? THEN 0
            ELSE 1
        END, name
        """,
        sorted_symbols + [file_path] if file_path else sorted_symbols,
    )

    definitions = [{"name": row[0], "file_path": row[1], "full_definition": row[2]} for row in cursor.fetchall()]
    return {
        "symbol_name": symbol_name,
        "file_path": file_path,
        "max_depth": max_depth,
        "definitions": definitions,
    }


@app.get("/symbols/{symbol_name}/context")
async def get_symbol_context_api(symbol_name: str, file_path: Optional[str] = QueryArgs(None), max_depth: int = 1):
    """获取符号上下文API"""
    try:
        validate_input(symbol_name)
        conn = get_db_connection()
        context = get_symbol_context(conn, symbol_name, file_path, max_depth)
        return context
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def get_symbols_from_db(prefix: str, max_results: int, file_path: Optional[str] = None) -> list:
    """从数据库获取符号信息
    支持根据前缀和文件路径进行模糊匹配查询
    当同时提供前缀和路径时，使用两者进行查询
    当只提供其中一个时，仅使用提供的条件进行查询
    """

    conn = get_db_connection()
    cursor = conn.cursor()

    # 构建查询条件和参数
    conditions = []
    params = []

    if prefix:
        conditions.append("name LIKE ?")
        params.append(f"%{prefix}%")

    if file_path:
        conditions.append("file_path LIKE ?")
        params.append(f"%{file_path}%")

    # 如果没有提供任何条件，返回空列表
    if not conditions:
        return []

    # 构建完整的SQL查询
    where_clause = " AND ".join(conditions)
    query = f"SELECT name, file_path FROM symbols WHERE {where_clause} LIMIT ?"
    params.append(max_results)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    return [{"name": row[0], "details": {"file_path": row[1]}} for row in rows]


@app.get("/complete")
async def symbol_completion(prefix: str = QueryArgs(..., min_length=1), max_results: int = 10):
    """处理符号自动补全请求，支持前缀树和数据库两种搜索方式

    Args:
        prefix: 用户输入的搜索前缀，最小长度为1
        max_results: 最大返回结果数量，自动限制在1-50之间
    """
    # 如果前缀为空，直接返回空结果
    if not prefix:
        return {"completions": []}

    trie = app.state.symbol_trie
    # 确保max_results是整数类型（处理可能的字符串输入）
    max_results = int(max_results)
    # 限制结果范围在1到50之间，避免过大或非法的请求
    max_results = max(1, min(50, max_results))

    # 首先尝试使用前缀树搜索（高效的前缀匹配算法）
    results = trie.search_prefix(prefix)[:max_results]

    # 如果前缀树搜索结果为空，则使用数据库模糊搜索（回退机制保证覆盖率）
    if not results:
        # 使用数据库的LIKE查询进行模糊匹配
        results = get_symbols_from_db(prefix, max_results)

    # 返回标准化格式的补全结果列表
    return {"completions": results}


def extract_identifiable_path(file_path: str) -> str:
    """提取路径中易于识别的部分
    检测输入路径是否相对于当前文件的目录，如果不是则返回绝对路径

    Args:
        file_path: 文件路径（相对或绝对路径）

    Returns:
        相对路径（如果在当前文件目录下）或绝对路径（统一使用Linux路径分隔符）
    """
    current_dir = str(GLOBAL_PROJECT_CONFIG.project_root_dir)

    # 转换为绝对路径
    if os.path.isabs(file_path):
        abs_path = file_path
    else:
        # 将相对路径视为相对于当前文件目录解析
        abs_path = os.path.abspath(os.path.join(current_dir, file_path))

    # 检查是否在当前文件目录下
    if abs_path.startswith(current_dir):
        # 返回相对于当前目录的路径
        rel_path = os.path.relpath(abs_path, current_dir)
        return rel_path.replace("\\", "/")

    # 返回绝对路径（当路径不在当前目录下时）
    return abs_path.replace("\\", "/")


async def location_to_symbol(
    symbol: Dict,
    trie: SymbolTrie,
    lsp_client: GenericLSPClient,
    lookup_cache: Dict | None = None,
) -> List[Dict]:
    """通过LSP获取定义位置并更新符号前缀树

    Args:
        symbol: 包含调用信息的符号字典
        trie: 符号前缀树
        lsp_client: LSP客户端实例
        lookup_cache: 符号查找缓存，避免重复查找相同位置的符号

    Returns:
        收集到的符号定义信息列表
    """
    collected_symbols = []
    file_content_cache = {}
    file_lines_cache = {}
    if not lookup_cache:
        lookup_cache = {}

    # 初始化LSP服务器
    await _initialize_lsp_server(symbol, lsp_client)
    symbol_file_path = symbol["file_path"]
    # 处理每个调用
    calls = [(1, symbol) for symbol in symbol.get("calls", [])]
    symbols_filter = set()
    for level, call in calls:
        if level > 3:
            break
        try:
            symbols = await _process_call(
                call,
                symbol["file_path"],
                trie,
                lsp_client,
                file_content_cache,
                file_lines_cache,
                lookup_cache,
            )
            for sym in symbols:
                if sym["file_path"] == symbol_file_path:
                    if sym["name"] in symbols_filter:
                        continue
                    symbols_filter.add(sym["name"])
                    logger.info("检查同文件符号%s.%s的调用", sym["file_path"], sym["name"])
                    calls.extend([(level + 1, call) for call in sym["calls"]])
            collected_symbols.extend(symbols)
        except (ConnectionError, TimeoutError, RuntimeError) as e:
            print(f"处理调用 {call['name']} 时发生错误: {str(e)}")

    return collected_symbols


async def _initialize_lsp_server(symbol: Dict, lsp_client: GenericLSPClient) -> None:
    """初始化LSP服务器，发送文件打开通知"""
    file_path = symbol["file_path"]
    with open(file_path, "r", encoding="utf-8") as f:
        file_content = f.read()

    language_id = LanguageId.get_language_id(file_path)
    abs_file_path = os.path.abspath(file_path)
    lsp_client.send_notification(
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": f"file://{abs_file_path}",
                "languageId": language_id,
                "version": 1,
                "text": file_content,
            }
        },
    )


async def _process_call(
    call: Dict,
    file_path: str,
    trie: SymbolTrie,
    lsp_client: GenericLSPClient,
    file_content_cache: Dict,
    file_lines_cache: Dict,
    lookup_cache: Dict | None = None,
) -> List[Dict]:
    """处理单个调用，返回收集到的符号信息"""
    call_name = call["name"]
    line = call["start_point"][0] + 1
    char = call["start_point"][1] + 1

    # 获取定义信息
    definition = await lsp_client.get_definition(os.path.abspath(file_path), line, char)
    if not definition:
        return []

    definitions = definition if isinstance(definition, list) else [definition]

    collected_symbols = []
    for def_item in definitions:
        # 生成缓存key
        uri = def_item.get("uri", "")
        def_path = unquote(urlparse(uri).path) if uri.startswith("file://") else ""
        if not def_path:
            continue

        cache_key = f"{def_path}:{def_item.get('range', {}).get('start', {}).get('line', 0)}"
        if lookup_cache and cache_key in lookup_cache:
            continue
        symbols = await _process_definition(def_item, trie, call_name, file_content_cache, file_lines_cache)
        if lookup_cache:
            lookup_cache[cache_key] = symbols
        collected_symbols.extend(symbols)

    return collected_symbols


async def _process_definition(
    def_item: Dict,
    trie: SymbolTrie,
    call_name: str,
    file_content_cache: Dict,
    file_lines_cache: Dict,
) -> List[Dict]:
    """处理单个定义项，返回收集到的符号信息"""
    # 解析定义位置
    uri = def_item.get("uri", "")
    def_path = unquote(urlparse(uri).path) if uri.startswith("file://") else ""
    if not def_path or not os.path.exists(def_path):
        return []

    # 更新前缀树
    current_dir = os.path.dirname(os.path.abspath(__file__))
    rel_def_path = os.path.relpath(def_path, current_dir)
    update_trie_if_needed(f"symbol:{rel_def_path}", trie, app.state.file_parser_info_cache, just_path=True)

    # 获取文件内容
    lines = _get_file_content(def_path, file_content_cache, file_lines_cache)

    # 提取符号信息
    symbol_name = _extract_symbol_name(def_item, lines)
    if not symbol_name:
        return []

    # 搜索并收集符号
    return _collect_symbols(rel_def_path, symbol_name, call_name, trie, file_content_cache)


def _get_file_content(file_path: str, file_content_cache: Dict, file_lines_cache: Dict) -> List[str]:
    """获取文件内容，使用缓存优化性能"""
    if file_path not in file_content_cache:
        with open(file_path, "rb") as f:
            file_content_cache[file_path] = f.read()
            file_lines_cache[file_path] = file_content_cache[file_path].decode("utf8").splitlines()
    return file_lines_cache[file_path]


def _extract_symbol_name(def_item: Dict, lines: List[str]) -> str:
    """从定义项中提取符号名称"""
    range_info = def_item.get("range", {})
    start = range_info.get("start", {})
    end = range_info.get("end", {})

    # 处理行号
    start_line = start.get("line", 0)
    if start_line >= len(lines):
        return ""
    target_line = lines[start_line]

    # 处理字符位置
    start_char = start.get("character", 0)
    end_char = end.get("character", start_char + 1)

    # 提取符号名称
    symbol_name = target_line[start_char:end_char].strip()
    if not symbol_name:
        symbol_name = _expand_symbol_from_line(target_line, start_char, end_char)
    return symbol_name


def _collect_symbols(
    rel_def_path: str,
    symbol_name: str,
    call_name: str,
    trie: SymbolTrie,
    file_content_cache: Dict,
) -> List[Dict]:
    """收集符号信息"""
    symbols = perform_trie_search(
        trie=trie,
        prefix=f"symbol:{rel_def_path}/{symbol_name}",
        max_results=5,
        file_path=rel_def_path,
        updated=True,
        search_exact=True,
    )

    collected_symbols = []
    for s in symbols:
        if not s:
            continue
        # 获取符号的完整位置信息
        start_point, end_point, block_range = s["location"]
        # 提取符号对应的源代码内容
        content = file_content_cache[os.path.abspath(rel_def_path)][block_range[0] : block_range[1]].decode("utf8")
        # 构造完整的符号信息
        symbol_info = {
            "name": symbol_name,
            "file_path": rel_def_path,
            "location": {
                "start_line": start_point[0],
                "start_col": start_point[1],
                "end_line": end_point[0],
                "end_col": end_point[1],
                "block_range": block_range,
            },
            "content": content,
            "jump_from": call_name,
            "calls": s.get("calls", []),
        }
        collected_symbols.append(symbol_info)

    return collected_symbols


def _expand_symbol_from_line(line: str, start: int, end: int) -> str:
    """从行内容扩展符号边界"""
    # 向左扩展边界
    while start > 0 and (line[start - 1].isidentifier() or line[start - 1] == "_"):
        start -= 1

    # 向右扩展边界
    while end < len(line) and (line[end].isidentifier() or line[end] == "_"):
        end += 1

    return line[start:end].strip() or "<无名符号>"


@app.get("/symbol_content")
async def get_symbol_content(
    symbol_path: str = QueryArgs(..., min_length=1),
    json_format: bool = False,
    lsp_enabled: bool = False,
):
    """根据符号路径获取符号对应的源代码内容

    Args:
        symbol_path: 符号路径，格式为file_path/symbol1,symbol2,... 例如 "main.c/a,b,c"
        json_format: 是否返回JSON格式，包含每个符号的行号信息
        lsp_enabled: 是否启用LSP增强功能

    Returns:
        纯文本格式的源代码内容（多个符号内容用空行分隔），或包含每个符号信息的JSON数组
    """
    trie: SymbolTrie = app.state.file_symbol_trie
    file_parser_info_cache = app.state.file_parser_info_cache
    # 参数解析
    parsed = parse_symbol_path(symbol_path)
    if isinstance(parsed, PlainTextResponse):
        return parsed
    file_path_part, symbols = parsed

    # 符号查找
    symbol_results = validate_and_lookup_symbols(file_path_part, symbols, trie, file_parser_info_cache)
    if isinstance(symbol_results, PlainTextResponse):
        return symbol_results

    # 读取源代码
    source_code = read_source_code(symbol_results[0]["file_path"])
    if isinstance(source_code, PlainTextResponse):
        return source_code

    # 内容提取
    contents = extract_contents(source_code, symbol_results)
    collected_symbols = []
    lookup_cache = {}
    if lsp_enabled:
        for symbol in symbol_results:
            collected_symbols.extend(
                await location_to_symbol(
                    symbol,
                    trie,
                    start_lsp_client_once(GLOBAL_PROJECT_CONFIG, symbol_results[0]["file_path"]),
                    lookup_cache,
                )
            )
    # 构建响应
    return (
        collected_symbols + build_json_response(symbol_results, contents)
        if json_format
        else build_plaintext_response(contents)
    )


def parse_symbol_path(symbol_path: str) -> tuple[str, list] | PlainTextResponse:
    """解析符号路径参数"""
    if "/" not in symbol_path:
        return PlainTextResponse("符号路径格式错误，应为文件路径/符号1,符号2,...", status_code=400)

    last_slash_index = symbol_path.rfind("/", 1)
    file_path_part = symbol_path[:last_slash_index]
    symbols_part = symbol_path[last_slash_index + 1 :]
    symbols = [s.strip() for s in symbols_part.split(",") if s.strip()]

    if not symbols:
        return PlainTextResponse("至少需要一个符号", status_code=400)

    return (file_path_part, symbols)


def unnamed_symbol_at_line(line_number: int) -> str:
    """生成无名符号的名称"""
    return f"at_{line_number}"


def near_symbol_at_line(line_number: int) -> str:
    """生成无名符号的名称"""
    return f"near_{line_number}"


def line_number_from_unnamed_symbol(symbol: str) -> int:
    """从无名符号名称中提取行号"""
    matcher = re.match(r"(?:near|at)_(\d+)", symbol)
    if matcher:
        return int(matcher.group(1))
    return -1


def validate_and_lookup_symbols(
    file_path_part: str, symbols: list[str], trie: SymbolTrie, file_parser_info_cache
) -> list | PlainTextResponse:
    """验证并查找符号"""
    update_trie_if_needed(file_path_part, trie, file_parser_info_cache, just_path=True)

    symbol_results = []
    for symbol in symbols:
        full_symbol_path = f"{file_path_part}/{symbol}"
        line_number = line_number_from_unnamed_symbol(symbol)
        if line_number != -1:
            # 如果符号是无名符号，使用行号生成符号名称
            parser_instance: ParserUtil = file_parser_info_cache[file_path_part][0]
            fromatted_path = file_parser_info_cache[file_path_part][2]
            if symbol.startswith("near_"):
                result = parser_instance.near_symbol_at_line(line_number - 1)
            else:
                result = parser_instance.symbol_at_line(line_number - 1)
            if not result:
                return PlainTextResponse(f"未找到符号: {symbol}", status_code=404)
            result["file_path"] = fromatted_path
        else:
            result = trie.search_exact(full_symbol_path)
            if not result:
                return PlainTextResponse(f"未找到符号: {symbol}", status_code=404)
        if full_symbol_path.startswith("symbol:"):
            result["name"] = full_symbol_path[len("symbol:") :]
        else:
            result["name"] = full_symbol_path
        symbol_results.append(result)
    return symbol_results


def read_source_code(file_path: str) -> bytes | PlainTextResponse:
    """读取源代码文件"""
    try:
        with open(file_path, "rb") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
        return PlainTextResponse(f"无法读取文件: {str(e)}", status_code=500)


def extract_contents(source_code: bytes, symbol_results: list) -> list[str]:
    """提取符号内容"""
    return [
        source_code[result["location"][2][0] : result["location"][2][1]].decode("utf8") for result in symbol_results
    ]


def build_json_response(symbol_results: list, contents: list) -> list:
    """构建JSON响应"""
    return [
        {
            "name": result["name"],
            "file_path": result["file_path"],
            "content": content,
            "location": {
                "start_line": result["location"][0][0],
                "start_col": result["location"][0][1],
                "end_line": result["location"][1][0],
                "end_col": result["location"][1][1],
                "block_range": result["location"][2],
            },
            "calls": result.get("calls", []),
        }
        for result, content in zip(symbol_results, contents)
    ]


def build_plaintext_response(contents: list) -> PlainTextResponse:
    """构建纯文本响应"""
    return PlainTextResponse("\n\n".join(contents))


def update_trie_if_needed(prefix: str, trie, file_parser_info_cache, just_path=False) -> bool:
    """根据前缀更新前缀树，如果需要的话

    Args:
        prefix: 要检查的前缀
        trie: 前缀树对象
        file_parser_info_cache: 文件修改时间缓存

    Returns:
        bool: 是否执行了更新操作
    """
    if not prefix.startswith("symbol:"):
        return False
    if not just_path:
        # 使用rfind找到最后一个/的位置
        last_slash_idx = prefix.rfind("/")
        if last_slash_idx == -1:
            # 没有斜杠时，直接去掉'symbol:'前缀
            file_path = prefix[len("symbol:") :]
        else:
            # 提取从'symbol:'到最后一个/之间的部分作为文件路径
            file_path = prefix[len("symbol:") : last_slash_idx]
    else:
        file_path = prefix[len("symbol:") :] if prefix.startswith("symbol:") else prefix
    # 检查文件扩展名是否在支持的语言中
    pos = file_path.rfind(".")
    if pos < 0:
        return False
    ext = file_path[pos:].lower()
    if ext not in SUPPORTED_LANGUAGES:
        return False

    current_mtime = os.path.getmtime(file_path)
    parser_instance, cached_mtime, _ = file_parser_info_cache.get(file_path, (None, 0, ""))

    if current_mtime > cached_mtime:
        print(f"[DEBUG] 检测到文件修改: {file_path} (旧时间:{cached_mtime} 新时间:{current_mtime})")
        parser_loader = ParserLoader()
        parser_instance = ParserUtil(parser_loader)
        parser_instance.update_symbol_trie(file_path, trie)
        file_parser_info_cache[file_path] = (parser_instance, current_mtime, file_path)
        file_parser_info_cache[prefix] = (parser_instance, current_mtime, file_path)
        return True

    return False


@app.post("/lsp/didChange")
async def lsp_file_didChange(file_path: str = Form(...), content: str = Form(...)):
    """
    处理LSP文档变更通知的接口

    参数要求:
    - file_path: 文件路径参数，必须非空
    - content: 文件最新内容

    流程说明:
    1. 检查全局LSP_CLIENT是否可用，不可用时返回501错误
    2. 验证客户端是否支持文档同步功能
    3. 调用客户端的did_change方法发送变更通知
    4. 记录操作日志并返回成功响应

    异常处理:
    - 客户端未初始化返回HTTP 501
    - 功能不支持返回HTTP 400
    - 其他错误返回HTTP 500
    """
    client = getattr(app.state, "LSP_CLIENT", None)
    if not client or not client.running:
        return JSONResponse(status_code=501, content={"message": "LSP client not initialized"})

    try:
        client.did_change(file_path, content)
        print("Processed didChange notification for %s", file_path)
        return {"status": "success"}

    except LSPFeatureError as e:
        print("Feature not supported: %s", str(e))
        return JSONResponse(status_code=400, content={"message": f"Feature not supported: {e.feature}"})
    except Exception as e:
        traceback.print_exc()
        print("Failed to process didChange: %s", str(e))
        return JSONResponse(status_code=500, content={"message": "Internal server error"})


@app.get("/extract_identifier")
async def extract_identifier(text: str = QueryArgs(...)):
    """
    对输入文本进行分词，提取符合编程语言标识符规则的词语

    Args:
        text: 需要分词的原始文本，长度建议不超过1000字符
        有效输入示例: "ParserUtil Python TestCase"

    Returns:
        list[str]: 符合标识符规则的词语列表
    """
    if not text.strip():
        return []

    words = list(dynamic_import("jieba").cut(text, cut_all=False))
    identifier_pattern = re.compile(r"^[a-zA-Z_]\w*$")
    return [word for word in words if identifier_pattern.fullmatch(word)]


class MatchResult(BaseModel):
    line: int
    column_range: tuple[int, int]
    text: str


MatchResults = list[MatchResult]


class FileSearchResult(BaseModel):
    file_path: str
    matches: list[MatchResult]


class FileSearchResults(BaseModel):
    results: list[FileSearchResult]

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "FileSearchResults":
        return cls.model_validate_json(json_str)


@app.post("/search-to-symbols")
async def search_to_symbols(
    max_context_size: int = QueryArgs(default=16384),
    results: FileSearchResults = Body(...),
):
    """根据文件搜索结果解析符号路径"""

    # t = start_trace(config=TraceConfig(target_files=["*.py"], enable_var_trace=True, report_name="search.html"))
    parser_loader_s = ParserLoader()
    parser_util = ParserUtil(parser_loader_s)
    symbol_results = {}
    symbol_cache = app.state.symbol_cache
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for file_result in results.results:
        file_path_str = file_result.file_path
        file_path = Path(file_path_str)
        try:
            current_mtime = file_path.stat().st_mtime
        except FileNotFoundError:
            continue
        try:
            if file_path_str in symbol_cache:
                cached_mtime, code_map = symbol_cache[file_path_str]
                if cached_mtime != current_mtime:
                    _, code_map = parser_util.get_symbol_paths(file_path_str)
                    symbol_cache[file_path_str] = (current_mtime, code_map)
            else:
                _, code_map = parser_util.get_symbol_paths(file_path_str)
                symbol_cache[file_path_str] = (current_mtime, code_map)
        except ValueError as e:
            print("解析出错", file_path_str, e)
            continue
        locations = [(match.line - 1, match.column_range[0] - 1) for match in file_result.matches]
        symbols = parser_util.find_symbols_for_locations(code_map, locations, max_context_size=max_context_size)

        file_abs = os.path.abspath(file_path_str)
        if os.path.commonpath([file_abs, script_dir]) == script_dir:
            rel_path = os.path.relpath(file_abs, script_dir)
        else:
            rel_path = file_abs

        for key, value in symbols.items():
            value["name"] = f"{rel_path}/{key}"
            value["file_path"] = rel_path
        symbol_results.update(symbols)
    # t.stop()
    return JSONResponse(content={"results": symbol_results, "count": len(symbol_results)})


@app.get("/complete_realtime")
async def symbol_completion_realtime(prefix: str = QueryArgs(..., min_length=1), max_results: int = 10):
    """实时符号补全，直接解析指定文件并返回符号列表

    Args:
        prefix: 补全前缀，格式为symbol:文件路径/符号1,符号2,...
        max_results: 最大返回结果数量，默认为10，范围1-50

    Returns:
        纯文本格式的补全列表，每行一个补全结果
    """
    prefix = unquote(prefix)
    print(f"[INFO] 处理实时补全请求: {prefix[:50]}...")
    trie = app.state.file_symbol_trie
    max_results = clamp(max_results, 1, 50)
    file_path, symbols = parse_symbol_prefix(prefix)
    print("debug", file_path, symbols)
    current_prefix = determine_current_prefix(file_path, symbols)
    print("prefix", current_prefix)
    updated = update_trie_for_completion(file_path, trie, app.state.file_parser_info_cache)

    results = perform_trie_search(trie, current_prefix, max_results, file_path, updated)
    completions = build_completion_results(file_path, symbols, results)

    print(f"[INFO] 返回 {len(completions)} 个补全结果")
    return PlainTextResponse("\n".join(completions))


def parse_symbol_prefix(prefix: str) -> tuple[str | None, list[str]]:
    """解析符号前缀为文件路径和符号层级"""
    if not prefix.startswith("symbol:"):
        return None, []

    remaining = prefix[len("symbol:") :]
    slash_idx = remaining.rfind("/")

    if slash_idx == -1:
        return remaining, []

    file_path = remaining[:slash_idx]
    symbols = list(remaining[slash_idx + 1 :].split(","))
    return file_path, symbols


def determine_current_prefix(file_path: str | None, symbols: list[str]) -> str:
    """确定当前搜索前缀"""
    if symbols and any(symbols):
        return f"symbol:{file_path}/{symbols[-1]}"
    if file_path:
        return f"symbol:{file_path}"
    return ""


def update_trie_for_completion(file_path: str | None, trie: Any, mtime_cache: Any) -> bool:
    """更新前缀树数据"""
    if not file_path:
        return False
    return update_trie_if_needed(f"symbol:{file_path}", trie, mtime_cache, just_path=True)


def perform_trie_search(
    trie: SymbolTrie,
    prefix: str,
    max_results: int,
    file_path: str | None = None,
    updated: bool = False,
    search_exact: bool = False,
) -> list:
    """执行前缀树搜索"""
    if search_exact:
        results = [trie.search_exact(prefix)]
    else:
        results = trie.search_prefix(prefix, max_results=max_results, use_bfs=True) if file_path else []
    if not results and file_path and not updated:
        if update_trie_if_needed(f"symbol:{file_path}", trie, app.state.file_parser_info_cache):
            return trie.search_prefix(prefix, max_results)

    return results


def build_completion_results(file_path: str | None, symbols: list[str], results: list) -> list[str]:
    """构建补全结果列表"""

    base_str = f"symbol:{file_path}/"
    symbol_prefix = ",".join(symbols[:-1]) + "," if len(symbols) > 1 else ""

    completions = []
    for result in results:
        symbol_name = result["name"][result["name"].rfind("/") + 1 :]
        full_path = f"{base_str}{symbol_prefix}{symbol_name}"
        completions.append(full_path.replace("//", "/"))

    return completions


def clamp(value: int, min_val: int, max_val: int) -> int:
    """限制数值范围"""
    return max(min_val, min(max_val, value))


@app.get("/complete_simple")
async def symbol_completion_simple(prefix: str = QueryArgs(..., min_length=1), max_results: int = 10):
    """简化版符号补全，返回纯文本格式：symbol:filebase/symbol"""
    # 如果前缀为空，直接返回空响应
    if not prefix:
        return PlainTextResponse("")

    trie = app.state.symbol_trie
    max_results = max(1, min(50, int(max_results)))

    # 无论是否包含路径，都先尝试前缀树搜索
    results = trie.search_prefix(prefix)[:max_results]

    # 如果前缀树搜索结果为空，则根据情况从数据库搜索
    if not results:
        # 处理以symbol:开头的情况
        if prefix.startswith("symbol:"):
            # 去掉symbol:前缀
            clean_prefix = prefix[len("symbol:") :]
            # 判断是否包含路径分隔符
            if "/" in clean_prefix:
                # 如果包含路径，则拆分路径和符号名
                parts = clean_prefix.rsplit("/", 1)
                path_prefix = parts[0] if len(parts) > 1 else ""
                symbol_prefix = parts[-1]
                # 将路径和符号名分别传入
                results = get_symbols_from_db(symbol_prefix, max_results, path_prefix)
            else:
                # 如果不包含路径，则只传入符号名，路径为空
                results = get_symbols_from_db(clean_prefix, max_results, "")
        else:
            # 如果不以symbol:开头，则直接进行模糊搜索，路径为空
            results = get_symbols_from_db(prefix, max_results, "")

    # 处理每个结果，提取文件名和符号名
    output = []
    for item in results:
        file_path = item["details"]["file_path"]
        file_base = extract_identifiable_path(file_path)
        symbol_name = item["name"]
        if symbol_name.startswith("symbol:"):
            output.append(symbol_name)
        else:
            output.append(f"symbol:{file_base}/{symbol_name}")

    return PlainTextResponse("\n".join(output))


def debug_tree_source_file(file_path: Path):
    """调试函数：解析指定文件并打印整个语法树结构

    Args:
        file_path: 要调试的源代码文件路径
    """
    try:
        # 获取解析器和查询对象
        parser, _, _ = ParserLoader().get_parser(str(file_path))
        print("[DEBUG] 开始解析文件: {file_path}")

        # 解析文件并获取语法树
        tree = parse_code_file(file_path, parser)
        print("[DEBUG] 文件解析完成，开始打印语法树")

        # 递归打印语法树结构
        def print_tree(node, indent=0):
            # 获取节点文本内容
            node_text = node.text.decode("utf-8") if node.text else ""
            # 打印节点类型、位置和内容
            print(" " * indent + f"{node.type} ({node.start_point} -> {node.end_point}): {node_text}")
            for child in node.children:
                print_tree(child, indent + 2)

        # 从根节点开始打印
        print_tree(tree.root_node)
        print("[DEBUG] 语法树打印完成")

    except Exception as e:
        print(f"[ERROR] 调试语法树时发生错误: {str(e)}")
        raise


def debug_process_source_file(file_path: Path, project_dir: Path):
    """调试版本的源代码处理函数，直接打印符号信息而不写入数据库"""
    try:
        # 解析代码文件并构建符号表
        parser, query, lang_name = ParserLoader().get_parser(str(file_path))
        print(f"[DEBUG] 即将开始解析文件: {file_path}")
        tree = parse_code_file(file_path, parser)
        print("[DEBUG] 文件解析完成，开始匹配查询")
        matches = query.matches(tree.root_node)
        print(f"[DEBUG] 查询匹配完成，共找到 {len(matches)} 个匹配项，开始处理符号")
        symbols = process_matches(matches, lang_name)
        print(f"[DEBUG] 符号处理完成，共提取 {len(symbols)} 个符号")

        # 获取完整文件路径（规范化处理）
        full_path = str((project_dir / file_path).resolve().absolute())

        print(f"\n处理文件: {full_path}")
        print("=" * 50)

        for symbol_name, symbol_info in symbols.items():
            if not symbol_info.get("full_definition"):
                continue

            print(f"\n符号名称: {symbol_name}")
            print(f"类型: {symbol_info['type']}")
            print(f"签名: {symbol_info['signature']}")
            print(f"完整定义:\n{symbol_info['full_definition']}")
            print(f"调用关系: {symbol_info['calls']}")
            print("-" * 50)

        print(f"\n处理完成，共找到 {len(symbols)} 个符号")

    except Exception as e:
        print(f"处理文件时发生错误: {str(e)}")
        raise


def format_c_code_in_directory(directory: Path):
    """使用 clang-format 对指定目录下的所有 C 语言代码进行原位格式化，并利用多线程并行处理

    Args:
        directory: 要格式化的目录路径
    """

    # 支持的 C 语言文件扩展名
    c_extensions = [".c", ".h"]

    # 获取系统CPU核心数
    cpu_count = os.cpu_count() or 1

    # 记录已格式化文件的点号文件路径
    formatted_file_path = directory / ".formatted_files"

    # 读取已格式化的文件列表
    formatted_files = set()
    if formatted_file_path.exists():
        with open(formatted_file_path, "r", encoding="utf-8") as f:
            formatted_files = set(f.read().splitlines())

    # 收集所有需要格式化的文件路径
    files_to_format = [
        str(file_path)
        for file_path in directory.rglob("*")
        if file_path.suffix.lower() in c_extensions and str(file_path) not in formatted_files
    ]

    def format_file(file_path):
        """格式化单个文件的内部函数"""
        start_time = time.time()
        try:
            subprocess.run(["clang-format", "-i", file_path], check=True)
            formatted_files.add(file_path)
            return file_path, True, time.time() - start_time, None
        except subprocess.CalledProcessError as e:
            return file_path, False, time.time() - start_time, str(e)

    def process_future(future, pbar):
        """处理单个future结果的内部函数"""
        file_path, success, duration, error = future.result()
        pbar.set_postfix_str(f"正在处理: {os.path.basename(file_path)}")
        if success:
            pbar.write(f"✓ 成功格式化: {file_path} (耗时: {duration:.2f}s)")
        else:
            pbar.write(f"✗ 格式化失败: {file_path} (错误: {error})")
        pbar.update(1)

    # 创建线程池
    with ThreadPoolExecutor(max_workers=cpu_count) as executor:
        try:
            # 使用 tqdm 显示进度条
            with tqdm(total=len(files_to_format), desc="格式化进度", unit="文件") as pbar:
                futures = {executor.submit(format_file, file_path): file_path for file_path in files_to_format}

                for future in as_completed(futures):
                    process_future(future, pbar)

            # 将已格式化的文件列表写入点号文件
            with open(formatted_file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(formatted_files))

            # 打印已跳过格式化的文件
            skipped_files = [
                str(file_path)
                for file_path in directory.rglob("*")
                if file_path.suffix.lower() in c_extensions and str(file_path) in formatted_files
            ]
            if skipped_files:
                print("\n以下文件已经格式化过，本次跳过：")
                for file in skipped_files:
                    print(f"  {file}")

        except FileNotFoundError:
            print("未找到 clang-format 命令，请确保已安装 clang-format")


def parse_source_file(file_path: Path, parser, query, lang_name):
    """解析源代码文件并返回符号表"""
    tree = parse_code_file(file_path, parser)
    matches = query.matches(tree.root_node)
    return process_matches(matches, lang_name)


def check_symbol_duplicate(symbol_name: str, symbol_info: dict, all_existing_symbols: dict) -> bool:
    """检查符号是否已经存在"""
    if symbol_name not in all_existing_symbols:
        return False
    for existing_symbol in all_existing_symbols[symbol_name]:
        # and existing_symbol[2] == calculate_crc32_hash(symbol_info["full_definition"])
        if existing_symbol[1] == symbol_info["signature"]:
            return True
    return False


def prepare_insert_data(symbols: dict, all_existing_symbols: dict, full_path: str) -> tuple:
    """准备要插入数据库的数据"""
    insert_data = []
    duplicate_count = 0
    existing_symbol_names = set()

    for symbol_name, symbol_info in symbols.items():
        if not symbol_info.get("full_definition"):
            continue

        if check_symbol_duplicate(symbol_name, symbol_info, all_existing_symbols):
            duplicate_count += 1
            continue

        existing_symbol_names.add(symbol_name)
        insert_data.append(
            (
                None,  # id 由数据库自动生成
                symbol_name,
                full_path,
                symbol_info["type"],
                symbol_info["signature"],
                symbol_info.get("body", ""),
                symbol_info["full_definition"],
                calculate_crc32_hash(symbol_info["full_definition"]),
                json.dumps(symbol_info["calls"]),
            )
        )

    return insert_data, duplicate_count


def calculate_file_hash(file_path: Path) -> str:
    """计算文件的 MD5 哈希值
    Args:
        file_path: 文件路径
    Returns:
        文件的 MD5 哈希字符串
    """
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def get_database_stats(conn: sqlite3.Connection) -> tuple:
    """获取数据库统计信息"""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM symbols")
    total_symbols = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT file_path) FROM symbols")
    total_files = cursor.fetchone()[0]

    cursor.execute("PRAGMA index_list('symbols')")
    indexes = cursor.fetchall()

    return total_symbols, total_files, indexes


def get_existing_symbols(conn: sqlite3.Connection) -> dict:
    """获取所有已存在的符号"""
    cursor = conn.cursor()
    cursor.execute("SELECT name, file_path, signature, full_definition_hash FROM symbols")
    all_existing_symbols = {}
    total_rows = cursor.rowcount
    processed = 0
    spinner = ["-", "\\", "|", "/"]
    idx = 0

    for row in cursor.fetchall():
        if row[0] not in all_existing_symbols:
            all_existing_symbols[row[0]] = []
        all_existing_symbols[row[0]].append((row[1], row[2], row[3]))  # 存储哈希值而不是完整定义
        # 更新进度显示
        processed += 1
        idx = (idx + 1) % len(spinner)
        print(
            f"\r加载符号中... {spinner[idx]} 已处理 {processed}/{total_rows}",
            end="",
            flush=True,
        )

    # 清除进度显示行
    print("\r" + " " * 50 + "\r", end="", flush=True)
    print("符号缓存加载完成")
    return all_existing_symbols


def parse_worker_wrapper(file_path: Path) -> tuple[Path | None, dict | None]:
    """工作进程的包装函数，增加超时监控"""
    # 用于存储解析结果
    result = None
    # 创建线程锁
    result_lock = threading.Lock()

    def parse_task():
        nonlocal result
        try:
            start_time = time.time() * 1000
            parser1, query, lang_name = ParserLoader().get_parser(str(file_path))
            symbols = parse_source_file(file_path, parser1, query, lang_name)
            parse_time = time.time() * 1000 - start_time
            print(f"文件 {file_path} 解析完成，耗时 {parse_time:.2f} 毫秒")
            # 加锁更新结果
            with result_lock:
                result = (file_path, symbols)
        except Exception as e:
            print(f"解析失败 {file_path}: {str(e)}")
            # 加锁更新结果
            with result_lock:
                result = (None, None)

    # 创建并启动解析线程
    parse_thread = threading.Thread(target=parse_task)
    parse_thread.start()

    # 设置超时时间为5秒
    timeout = 5
    parse_thread.join(timeout)

    if parse_thread.is_alive():
        # 如果线程仍在运行，说明超时
        print(f"警告：文件 {file_path} 解析超时（超过{timeout}秒），正在等待完成...")
        # 继续等待线程完成
        parse_thread.join()

    # 加锁获取结果
    with result_lock:
        return result


def check_file_needs_processing(conn: sqlite3.Connection, full_path: str) -> bool:
    """快速检查文件是否需要处理，仅通过最后修改时间判断"""
    start_time = time.time() * 1000
    cursor = conn.cursor()
    cursor.execute("SELECT last_modified FROM file_metadata WHERE file_path = ?", (full_path,))
    file_metadata = cursor.fetchone()

    if file_metadata:
        last_modified = Path(full_path).stat().st_mtime
        if file_metadata[0] == last_modified:
            check_time = time.time() * 1000 - start_time
            print(f"文件 {full_path} 未修改，跳过处理，检查耗时 {check_time:.2f} 毫秒")
            return False
    check_time = time.time() * 1000 - start_time
    print(f"文件 {full_path} 需要处理，检查耗时 {check_time:.2f} 毫秒")
    return True


def debug_duplicate_symbol(symbol_name, all_existing_symbols, conn, data):
    """调试重复符号的辅助函数"""
    print(f"发现重复符号 {symbol_name}，详细信息如下：")
    # 打印内存中的符号信息
    for idx, existing in enumerate(all_existing_symbols[symbol_name]):
        print(f"  内存中第 {idx + 1} 个实例：")
        print(f"    文件路径: {existing[0]}")
        print(f"    签名: {existing[1]}")
        print(f"    完整定义哈希: {existing[2]}")

    # 从数据库查询该符号的所有记录
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM symbols WHERE name = ?", (symbol_name,))
    db_records = cursor.fetchall()
    t = None
    # 打印数据库中的符号信息并进行内容对比
    for idx, record in enumerate(db_records):
        print(f"  数据库中第 {idx + 1} 个实例：")
        print(f"    文件路径: {record[2]}")
        print(f"    签名: {record[4]}")
        print(f"    完整定义哈希: {record[7]}")
        t = record[6]
        print(f"    完整定义内容: {record[6]}")
    t2 = data[6]
    # 使用difflib生成unified diff格式的差异对比

    diff = unified_diff(
        t.splitlines(),
        t2.splitlines(),
        fromfile="数据库中的定义",
        tofile="内存中的定义",
        lineterm="",
    )
    print("符号定义差异对比：")
    for line in diff:
        print(line)
    # import pdb

    # pdb.set_trace()


def process_symbols_to_db(conn: sqlite3.Connection, file_path: Path, symbols: dict, all_existing_symbols: dict):
    """单线程数据库写入"""
    try:
        timing = {"start": time.time() * 1000, "prepare": 0, "insert": 0, "meta": 0}

        full_path = str(file_path.resolve().absolute())
        file_hash = calculate_file_hash(file_path)
        last_modified = file_path.stat().st_mtime

        # 开始事务
        conn.execute("BEGIN TRANSACTION")

        # 准备数据
        timing["prepare"] = time.time() * 1000
        insert_data, duplicate_count = prepare_insert_data(symbols, all_existing_symbols, full_path)
        timing["prepare"] = time.time() * 1000 - timing["prepare"]

        # 插入或更新符号数据
        timing["insert"] = time.time() * 1000
        if insert_data:
            filtered_data = []
            for data in insert_data:
                symbol_name = data[1]
                if symbol_name not in all_existing_symbols:
                    all_existing_symbols[symbol_name] = []

                if not any(existing[2] == data[7] for existing in all_existing_symbols[symbol_name]):
                    filtered_data.append(data)
                    all_existing_symbols[symbol_name].append((full_path, data[4], data[7]))

                    symbol_info = {
                        "name": data[1],
                        "file_path": data[2],
                        "signature": data[4],
                        "full_definition_hash": data[7],
                    }
                    app.state.symbol_trie.insert(symbol_name, symbol_info)

            if filtered_data:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO symbols
                    (id, name, file_path, type, signature, body, full_definition, full_definition_hash, calls)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            data[0],
                            data[1],
                            data[2],
                            data[3],
                            data[4],
                            data[5],
                            data[6],
                            data[7],
                            data[8],
                        )
                        for data in filtered_data
                    ],
                )
        timing["insert"] = time.time() * 1000 - timing["insert"]

        # 更新文件元数据
        timing["meta"] = time.time() * 1000
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO file_metadata
            (file_path, last_modified, file_hash, total_symbols)
            VALUES (?, ?, ?, ?)
            """,
            (full_path, last_modified, file_hash, len(symbols)),
        )
        timing["meta"] = time.time() * 1000 - timing["meta"]

        conn.commit()

        # 输出统计信息
        total_time = time.time() * 1000 - timing["start"]
        print(f"\n文件 {file_path} 处理完成：")
        print(f"  总符号数: {len(symbols)}")
        print(f"  重复符号数: {duplicate_count}")
        print(f"  新增符号数: {len(insert_data)}")
        print(f"  过滤符号数: {duplicate_count + (len(symbols) - len(insert_data))}")
        print("  性能数据（单位：毫秒）：")
        print(f"    数据准备: {timing['prepare']:.2f}")
        print(f"    数据插入: {timing['insert']:.2f}")
        print(f"    元数据更新: {timing['meta']:.2f}")
        print(f"    总耗时: {total_time:.2f}")

    except Exception:
        conn.rollback()
        raise


def scan_project_files_optimized(
    project_paths: List[str],
    conn: sqlite3.Connection,
    excludes: List[str] = None,
    include_suffixes: List[str] = None,
    parallel: int = -1,
):
    """优化后的项目文件扫描
    Args:
        project_paths: 项目路径列表
        conn: 数据库连接
        excludes: 要排除的文件模式列表
        include_suffixes: 要包含的文件后缀列表
        parallel: 并行度，-1表示使用CPU核心数，0或1表示单进程
    """
    validate_project_paths(project_paths)
    suffixes = include_suffixes if include_suffixes else SUPPORTED_LANGUAGES.keys()
    log_database_stats(conn)
    all_existing_symbols = get_existing_symbols(conn)
    # initialize_symbol_trie(all_existing_symbols)
    tasks = collect_processing_tasks(project_paths, conn, excludes, suffixes)
    process_files(conn, tasks, all_existing_symbols, parallel)


def validate_project_paths(project_paths: List[str]):
    non_existent_paths = [path for path in project_paths if not Path(path).exists()]
    if non_existent_paths:
        raise ValueError(f"以下路径不存在: {', '.join(non_existent_paths)}")


def log_database_stats(conn: sqlite3.Connection):
    total_symbols, total_files, indexes = get_database_stats(conn)
    print("\n数据库当前状态：")
    print(f"  总符号数: {total_symbols}")
    print(f"  总文件数: {total_files}")
    print(f"  索引数量: {len(indexes)}")
    for idx in indexes:
        print(f"    索引名: {idx[1]}, 唯一性: {'是' if idx[2] else '否'}")


def initialize_symbol_trie(all_existing_symbols: dict):
    trie = SymbolTrie.from_symbols(all_existing_symbols)
    app.state.symbol_trie = trie
    app.state.file_symbol_trie = SymbolTrie.from_symbols({})
    app.state.file_parser_info_cache = {}
    app.state.symbol_cache = {}


def collect_processing_tasks(
    project_paths: List[str],
    conn: sqlite3.Connection,
    excludes: List[str],
    suffixes: List[str],
) -> list:
    tasks = []
    for project_path in project_paths:
        project_dir = Path(project_path)
        if not project_dir.exists():
            print(f"警告：项目路径 {project_path} 不存在，跳过处理")
            continue

        for file_path in project_dir.rglob("*"):
            if not should_process_file(file_path, suffixes, excludes, project_dir):
                continue

            full_path = str((project_dir / file_path).resolve().absolute())
            if check_file_needs_processing(conn, full_path):
                tasks.append(file_path)
    return tasks


def should_process_file(file_path: Path, suffixes: List[str], excludes: List[str], project_dir: Path) -> bool:
    if file_path.suffix.lower() not in suffixes:
        return False

    full_path = str((project_dir / file_path).resolve().absolute())
    if excludes and any(fnmatch.fnmatch(full_path, pattern) for pattern in excludes):
        return False

    return True


def process_files(conn: sqlite3.Connection, tasks: list, all_existing_symbols: dict, parallel: int):
    if parallel in (0, 1):
        process_files_single(conn, tasks, all_existing_symbols)
    else:
        process_files_multiprocess(conn, tasks, all_existing_symbols, parallel)


def process_files_single(conn: sqlite3.Connection, tasks: list, all_existing_symbols: dict):
    print("\n使用单进程模式处理文件...")
    for file_path in tasks:
        print(f"[INFO] 开始处理文件: {file_path}")
        result = parse_worker_wrapper(file_path)
        if isinstance(result, tuple) and len(result) == 2:
            file_path, symbols = result
            print(f"[INFO] 文件 {file_path} 解析完成，开始插入数据库...")
            process_symbols_to_db(
                conn=conn,
                file_path=file_path,
                symbols=symbols,
                all_existing_symbols=all_existing_symbols,
            )
            print(f"[INFO] 文件 {file_path} 数据库插入完成")
        else:
            print(f"[WARNING] 文件 {file_path} 解析返回无效结果: {result}")


def process_files_multiprocess(conn: sqlite3.Connection, tasks: list, all_existing_symbols: dict, parallel: int):
    processes = os.cpu_count() if parallel == -1 else parallel
    print(f"\n使用多进程模式处理文件，进程数：{processes}...")
    with Pool(processes=processes) as pool:
        batch_size = 32
        for i in range(0, len(tasks), batch_size):
            results = []
            batch = tasks[i : i + batch_size]
            for result in pool.imap_unordered(partial(parse_worker_wrapper), batch):
                if result:
                    results.append(result)
            print(f"已完成批次 {i // batch_size + 1}/{(len(tasks) // batch_size) + 1}")
            process_batch_results(conn, results, all_existing_symbols)


def process_batch_results(conn: sqlite3.Connection, results: list, all_existing_symbols: dict):
    for file_path, symbols in results:
        if not file_path:
            continue
        process_symbols_to_db(
            conn=conn,
            file_path=file_path,
            symbols=symbols,
            all_existing_symbols=all_existing_symbols,
        )


def build_index(
    project_paths: List[str] = None,
    excludes: List[str] = None,
    include_suffixes: List[str] = None,
    db_path: str = "symbols.db",
    parallel: int = -1,
):
    """构建符号索引
    Args:
        parallel: 并行度，-1表示使用CPU核心数，0或1表示单进程
    """
    # 初始化数据库连接
    conn = init_symbol_database(db_path)
    try:
        # 扫描并处理项目文件
        scan_project_files_optimized(
            project_paths,
            conn,
            excludes=excludes,
            include_suffixes=include_suffixes,
            parallel=parallel,
        )
        print("符号索引构建完成")
    finally:
        # 关闭数据库连接
        conn.close()


def dynamic_import(module_name: str):
    """动态导入模块"""
    return importlib.import_module(module_name)


def main(
    host: str = "127.0.0.1",
    port: int = 8000,
    project_paths: List[str] = None,
    excludes: List[str] = None,
    include_suffixes: List[str] = None,
    db_path: str = "symbols.db",
    parallel: int = -1,
):
    """启动FastAPI服务
    Args:
        host: 服务器地址
        port: 服务器端口
        project_paths: 项目路径列表
        include_suffixes: 要包含的文件后缀列表
        db_path: 符号数据库文件路径，默认为当前目录下的symbols.db
        parallel: 并行度，-1表示使用CPU核心数，0或1表示单进程
    """
    # 初始化数据库连接
    # build_index(project_paths, excludes, include_suffixes, db_path, parallel)
    # 启动FastAPI服务
    initialize_symbol_trie({})
    dynamic_import("uvicorn").run(app, host=host, port=port)


def start_lsp_client_once(config: ProjectConfig, file_path: str):
    """启动LSP客户端线程

    参数:
        config: 项目配置对象
        file_path: 要分析的文件路径

    返回:
        已启动的LSP客户端对象
    """
    try:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        logger.debug("启动LSP客户端，文件: %s", file_path)
        suffix = path.suffix
        relative_path = config.relative_path(path)

        # 确定LSP配置
        lsp_config = _determine_lsp_config(config, relative_path, suffix)
        lsp_key = lsp_config["lsp_key"]
        workspace_path = lsp_config["workspace_path"]
        cache_key = f"lsp:{lsp_key}:{workspace_path}"

        # 检查缓存
        cached_client = config.get_lsp_client(cache_key)
        if cached_client:
            logger.debug("使用缓存的LSP客户端: %s", cache_key)
            return cached_client

        # 初始化客户端
        client = _initialize_lsp_client(config, lsp_key, workspace_path)

        # 启动客户端线程
        _start_lsp_thread(
            client,
            {
                "key": cache_key,
                "command": config.lsp.get("commands", {}).get(lsp_key, lsp_key),
                "workspace": workspace_path,
                "file": file_path,
                "suffix": suffix,
                "lsp_key": lsp_key,
            },
        )

        # 缓存客户端
        config.set_lsp_client(cache_key, client)
        logger.debug("已缓存LSP客户端: %s", cache_key)
        client.initialized_event.wait(timeout=5)
        return client
    except Exception as e:
        logger.error("LSP客户端启动失败: %s，文件: %s", str(e), file_path)
        raise


def _determine_lsp_config(config: ProjectConfig, relative_path: str, suffix: str) -> dict:
    """确定LSP配置

    返回包含以下键的字典:
    - lsp_key: LSP命令键
    - workspace_path: 工作区路径
    """
    workspace_path = config.project_root_dir
    lsp_key = None
    # 2. 如果没有后缀匹配，尝试根据子项目路径匹配
    if not lsp_key and "subproject" in config.lsp:
        for subpath, cmd_key in config.lsp["subproject"].items():
            if relative_path.startswith(subpath):
                lsp_key = cmd_key
                workspace_path = str(Path(config.project_root_dir) / subpath)
                break
    if not lsp_key:
        # 1. 首先尝试根据文件后缀匹配LSP
        lsp_key = config.lsp.get("suffix", {}).get(suffix.lstrip("."))
    # 3. 最后使用默认LSP
    if not lsp_key:
        lsp_key = config.lsp.get("default", "py")

    return {
        "lsp_key": lsp_key,
        "workspace_path": workspace_path,
    }


def _initialize_lsp_client(config: ProjectConfig, lsp_key: str, workspace_path: str) -> GenericLSPClient:
    """初始化LSP客户端"""
    lsp_command = config.lsp.get("commands", {}).get(lsp_key, "")
    assert lsp_command, f"LSP命令未配置: {lsp_key}"
    logger.info(
        "正在初始化LSP客户端，服务器命令：%s，工作区路径：%s",
        lsp_command,
        workspace_path,
    )
    return GenericLSPClient(lsp_command.split(), workspace_path)


def _start_lsp_thread(client: GenericLSPClient, client_info: dict):
    """启动LSP客户端线程"""

    def run_event_loop(client_info: dict):
        """运行LSP客户端事件循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            logger.debug(
                "启动LSP客户端线程: %s，命令: %s",
                client_info["key"],
                client_info["command"],
            )
            client.start()
            loop.run_forever()
        except (ConnectionError, RuntimeError) as e:
            traceback.print_exc()
            logger.error("LSP客户端运行异常: %s，客户端信息: %s", str(e), client_info)
        finally:
            logger.debug("关闭LSP客户端: %s", client_info["key"])
            loop.run_until_complete(client.shutdown())
            loop.close()
            logger.info("LSP客户端已关闭: %s", client_info["key"])

    thread = threading.Thread(
        target=run_event_loop,
        daemon=True,
        kwargs={"client_info": client_info},
        name=f"LSP-{client_info['lsp_key']}-{threading.get_ident()}",
    )
    thread.start()


class SyntaxHighlight:
    """
    自动语法高亮处理器
    输入假设:
    - 必须提供file_path或lang_type至少一个
    - 源代码需为字符串格式
    - 主题需存在于pygments.styles内置主题中
    """

    def __init__(self, source_code=None, file_path=None, lang_type=None, theme="default"):
        self.source_code = source_code
        self.lexer = None
        self.theme = theme
        self.available_themes = list(styles.get_all_styles())

        if lang_type:
            self.lexer = lexers.get_lexer_by_name(lang_type)
        elif file_path:
            self.lexer = lexers.get_lexer_for_filename(file_path)

        if not self.lexer:
            raise ValueError("无法确定语言类型，请指定lang_type或file_path")

    def render(self):
        formatter = formatters.Terminal256Formatter(style=self.theme)
        return highlight(self.source_code, self.lexer, formatter)

    def output(self):
        highlighted = self.render()
        print(highlighted)

    @staticmethod
    def highlight_if_terminal(source_code, file_path=None, lang_type=None, theme="default"):
        """根据终端是否支持颜色输出，决定是否进行语法高亮"""
        if sys.stdout.isatty():
            highlighter = SyntaxHighlight(source_code, file_path, lang_type, theme)
            return highlighter.render()
        return source_code


if __name__ == "__main__":
    # 配置日志格式
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    arg_parser = argparse.ArgumentParser(description="代码分析工具")
    arg_parser.add_argument("--host", type=str, default="127.0.0.1", help="HTTP服务器绑定地址")
    arg_parser.add_argument("--port", type=int, default=8000, help="HTTP服务器绑定端口")
    arg_parser.add_argument(
        "--project",
        type=str,
        nargs="+",
        default=["."],
        help="项目根目录路径（可指定多个）",
    )
    arg_parser.add_argument("--demo", action="store_true", help="运行演示模式")
    arg_parser.add_argument(
        "--include",
        type=str,
        nargs="+",
        help="要包含的文件后缀列表（可指定多个，如 .c .h）",
    )
    arg_parser.add_argument("--debug-file", type=str, help="单文件调试模式，指定要调试的文件路径")
    arg_parser.add_argument("--debug-tree", type=str, help="树结构调试模式，指定要调试的文件路径")
    arg_parser.add_argument("--format-dir", type=str, help="指定要格式化的目录路径")
    arg_parser.add_argument("--build-index", action="store_true", help="构建符号索引")
    arg_parser.add_argument("--db-path", type=str, default="symbols.db", help="符号数据库文件路径")
    arg_parser.add_argument(
        "--excludes",
        type=str,
        nargs="+",
        help="要排除的文件或目录路径列表（可指定多个）",
    )
    arg_parser.add_argument(
        "--parallel",
        type=int,
        default=-1,
        help="并行度，-1表示使用CPU核心数，0或1表示单进程",
    )
    arg_parser.add_argument("--debug-symbol-path", type=str, help="输出指定文件的符号路径")
    arg_parser.add_argument("--debug-skeleton", type=str, help="调试源代码框架，指定要调试的文件路径")
    arg_parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="设置日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )
    arg_parser.add_argument("--lsp", type=str, help="启动LSP客户端，指定LSP服务器命令（如：pylsp）")
    arg_parser.add_argument("--debugger-port", type=int, default=9911, help="调试器服务端口")

    args = arg_parser.parse_args()

    logger.info("启动代码分析工具: 日志输出: %s", args.log_level)
    logger.setLevel(args.log_level)

    DEFAULT_DB = args.db_path

    # 根据命令行参数启动对应功能
    if args.lsp:
        start_lsp_client_once(GLOBAL_PROJECT_CONFIG, GLOBAL_PROJECT_CONFIG.project_root_dir)

    if args.demo:
        logger.debug("进入演示模式")
        test_split_source_and_patch()
        demo_main()
    elif args.debug_file:
        logger.debug("单文件调试模式，文件路径：%s", args.debug_file)
        debug_process_source_file(Path(args.debug_file), Path(args.project[0]))
    elif args.debug_tree:
        debug_tree_source_file(Path(args.debug_tree))
    elif args.format_dir:
        logger.debug("格式化目录：%s", args.format_dir)
        format_c_code_in_directory(Path(args.format_dir))
    elif args.build_index:
        logger.info("开始构建符号索引")
        build_index(
            project_paths=args.project,
            excludes=args.excludes,
            include_suffixes=args.include,
            db_path=args.db_path,
            parallel=args.parallel,
        )
    elif args.debug_symbol_path:
        logger.debug("输出符号路径：%s", args.debug_symbol_path)
        parser_loader_s = ParserLoader()
        parser_util = ParserUtil(parser_loader_s)
        parser_util.print_symbol_paths(args.debug_symbol_path)
    elif args.debug_skeleton:
        parser_loader_s = ParserLoader()
        skeleton = SourceSkeleton(parser_loader_s)
        framework = skeleton.generate_framework(args.debug_skeleton)
        print("源代码框架信息：")
        print(SyntaxHighlight.highlight_if_terminal(framework, file_path=args.debug_skeleton))
    else:
        logger.info("启动FastAPI服务")
        # from debugger.web import service

        # service.start_debugger(args.debugger_port)
        main(
            host=args.host,
            port=args.port,
            project_paths=args.project,
            excludes=args.excludes,
            include_suffixes=args.include,
            db_path=args.db_path,
            parallel=args.parallel,
        )
