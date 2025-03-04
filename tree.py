import asyncio
import fnmatch
import hashlib
import importlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import unified_diff
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi import Query as QueryArgs
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from tqdm import tqdm  # 用于显示进度条
from tree_sitter import Language, Parser, Query

# 定义语言名称常量
C_LANG = "c"
PYTHON_LANG = "python"
JAVASCRIPT_LANG = "javascript"
JAVA_LANG = "java"
GO_LANG = "go"

# 文件后缀到语言名称的映射
SUPPORTED_LANGUAGES = {
    ".c": C_LANG,
    ".h": C_LANG,
    ".py": PYTHON_LANG,
    ".js": JAVASCRIPT_LANG,
    ".java": JAVA_LANG,
    ".go": GO_LANG,
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
}


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

    def search_prefix(self, prefix, max_results=None):
        """前缀搜索

        参数：
            prefix: 要搜索的前缀字符串
            max_results: 最大返回结果数量，None表示不限制

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

        # 收集所有子节点符号
        results = []
        self._dfs_collect(node, prefix, results, max_results)
        return results

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
            result[current_prefix] = [symbol for symbol in node.symbols]

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
                    symbol_name, {"file_path": entry[0], "signature": entry[1], "full_definition_hash": entry[2]}
                )
        return trie


class ParserLoader:
    def __init__(self):
        self._parsers = {}
        self._languages = {}
        self._queries = {}

    def _get_language(self, lang_name: str):
        """动态加载对应语言的 Tree-sitter 模块"""
        if lang_name in self._languages:
            return self._languages[lang_name]

        module_name = f"tree_sitter_{lang_name}"

        try:
            lang_module = importlib.import_module(module_name)
        except ImportError as exc:
            raise ImportError(
                f"Language parser for '{lang_name}' not installed. Try: pip install {module_name.replace('_', '-')}"
            ) from exc

        if not hasattr(lang_module, "language"):
            raise AttributeError(f"Module {module_name} does not have 'language' attribute.")

        self._languages[lang_name] = lang_module.language
        return lang_module.language

    def get_parser(self, file_path: str) -> tuple[Parser, Query, str]:
        """根据文件路径获取对应的解析器和查询对象"""
        suffix = Path(file_path).suffix.lower()
        lang_name = SUPPORTED_LANGUAGES.get(suffix)
        if not lang_name:
            raise ValueError(f"不支持的文件类型: {suffix}")

        if lang_name in self._parsers:
            return self._parsers[lang_name], self._queries[lang_name], lang_name

        language = self._get_language(lang_name)
        lang = Language(language())
        lang_parser = Parser(lang)

        # 根据语言类型获取对应的查询语句
        query_source = LANGUAGE_QUERIES.get(lang_name)
        if not query_source:
            raise ValueError(f"不支持的语言类型: {lang_name}")

        query = Query(lang, query_source)

        self._parsers[lang_name] = lang_parser
        self._queries[lang_name] = query
        return lang_parser, query, lang_name


class ParserUtil:
    def __init__(self, parser_loader: ParserLoader):
        """初始化解析器工具类"""
        self.parser_loader = parser_loader

    @staticmethod
    def get_symbol_name(node):
        """提取节点的符号名称
        可能的输入假设: node必须是一个有效的语法树节点，且包含type字段
        如果不符合假设，将返回None
        """
        if not hasattr(node, "type"):
            return None

        if node.type == "class_definition":
            return ParserUtil._get_class_name(node)
        elif node.type == "function_definition":
            return ParserUtil._get_function_name(node)
        elif node.type == "assignment":
            return ParserUtil._get_assignment_name(node)
        return None

    @staticmethod
    def _get_class_name(node):
        """从类定义节点中提取类名"""
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf8")
        return None

    @staticmethod
    def _get_function_name(node):
        """从函数定义节点中提取函数名"""
        # 首先查找pointer_declarator节点
        pointer_declarator = ParserUtil._find_child_by_type(node, "pointer_declarator")

        # 如果有pointer_declarator，则在其内部查找function_declarator
        if pointer_declarator:
            func_declarator = pointer_declarator.child_by_field_name("declarator")
            if func_declarator and func_declarator.type == "function_declarator":
                return ParserUtil._find_identifier_in_node(func_declarator)

        # 如果没有pointer_declarator，直接查找function_declarator
        func_declarator = ParserUtil._find_child_by_type(node, "function_declarator")
        if func_declarator:
            return ParserUtil._find_identifier_in_node(func_declarator)

        # 如果都没有，直接查找identifier
        return ParserUtil._find_identifier_in_node(node)

    @staticmethod
    def _get_assignment_name(node):
        """从赋值节点中提取变量名"""
        identifier = ParserUtil._find_child_by_type(node, "identifier")
        if identifier:
            return identifier.text.decode("utf8")

        left = node.child_by_field_name("left")
        if left and left.type == "identifier":
            return left.text.decode("utf8")
        return None

    @staticmethod
    def _find_child_by_type(node, target_type):
        """在节点子节点中查找指定类型的节点"""
        for child in node.children:
            if child.type == target_type:
                return child
        return None

    @staticmethod
    def _find_identifier_in_node(node):
        """在节点中查找identifier节点"""
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf8")
        return None

    def _get_node_info(self, node):
        """获取节点的代码和位置信息"""
        # 处理装饰器情况：如果当前节点是function_definition且父节点是decorated_definition，则使用父节点范围
        effective_node = node
        if (
            effective_node.type == "function_definition"
            and effective_node.parent
            and effective_node.parent.type == "decorated_definition"
        ):
            effective_node = effective_node.parent

        # 获取字节位置
        start_byte = effective_node.start_byte
        end_byte = effective_node.end_byte

        # 获取行号和列号（从0开始）
        start_point = effective_node.start_point
        end_point = effective_node.end_point

        return {"start_byte": start_byte, "end_byte": end_byte, "start_point": start_point, "end_point": end_point}

    def _extract_code(self, source_bytes, start_byte, end_byte):
        """从源字节中提取代码"""
        return source_bytes[start_byte:end_byte].decode("utf8")

    def _build_code_map_entry(self, path_key, code, node_info):
        """构建代码映射条目"""
        return {
            "code": code,
            "block_range": (node_info["start_byte"], node_info["end_byte"]),
            "start_line": node_info["start_point"][0],  # 起始行号（从0开始）
            "start_col": node_info["start_point"][1],  # 起始列号（从0开始）
            "end_line": node_info["end_point"][0],  # 结束行号（从0开始）
            "end_col": node_info["end_point"][1],  # 结束列号（从0开始）
        }

    def traverse(self, node, current_symbols, current_nodes, code_map, source_bytes, results):
        """递归遍历语法树，记录符号节点的路径、代码和位置信息"""
        symbol_name = self.get_symbol_name(node)
        added = False
        if symbol_name is not None:
            current_symbols.append(symbol_name)
            current_nodes.append(node)
            added = True

            # 获取当前节点的路径、代码和位置信息
            path_key = ".".join(current_symbols)
            current_node = current_nodes[-1]  # 当前新增的节点

            # 获取节点信息
            node_info = self._get_node_info(current_node)
            # 提取代码内容
            code = self._extract_code(source_bytes, node_info["start_byte"], node_info["end_byte"])
            # 构建代码映射条目
            code_map[path_key] = self._build_code_map_entry(path_key, code, node_info)

            results.append(path_key)  # 添加完整路径到结果

        # 遍历子节点
        for child in node.children:
            self.traverse(child, current_symbols, current_nodes, code_map, source_bytes, results)

        # 回溯
        if added:
            current_symbols.pop()
            current_nodes.pop()

    def get_symbol_paths(self, file_path: str):
        """解析代码文件并返回所有符号路径及对应代码和位置信息"""
        # 获取对应语言的解析器
        parser, _, _ = self.parser_loader.get_parser(file_path)

        # 读取源代码文件
        with open(file_path, "rb") as f:
            source_code = f.read()
        # 解析代码
        tree = parser.parse(source_code)
        root_node = tree.root_node

        # 收集符号路径和代码
        results = []
        code_map = {}
        self.traverse(root_node, [], [], code_map, source_code, results)
        return results, code_map

    def update_symbol_trie(self, file_path: str, symbol_trie: SymbolTrie):
        """
        更新符号前缀树，将文件中的所有符号插入到前缀树中

        参数：
            file_path: 文件路径
            symbol_trie: 要更新的符号前缀树
        """
        paths, code_map = self.get_symbol_paths(file_path)
        for path in paths:
            info = code_map[path]
            # 计算代码的CRC32哈希值
            full_definition_hash = calculate_crc32_hash(info["code"])
            # 构建位置信息
            location = (
                (info["start_line"], info["start_col"]),
                (info["end_line"], info["end_col"]),
                info["block_range"],
            )
            # 构建符号信息字典
            symbol_info = {
                "file_path": file_path,
                "signature": "",  # 可以根据需要添加签名信息
                "full_definition_hash": full_definition_hash,
                "location": location,
            }
            # 将符号插入前缀树
            symbol_trie.insert(path, symbol_info)

    def print_symbol_paths(self, file_path: str):
        """打印文件中的所有符号路径及对应代码和位置信息"""
        paths, code_map = self.get_symbol_paths(file_path)
        for path in paths:
            info = code_map[path]
            print(
                f"{path}:\n"
                f"代码位置: 第{info['start_line']+1}行{info['start_col']+1}列 "
                f"到 第{info['end_line']+1}行{info['end_col']+1}列\n"
                f"代码内容:\n{info['code']}\n"
            )


def dump_tree(node, source_bytes, indent=0):
    prefix = "  " * indent
    node_text = node.text.decode("utf8") if node.text else ""
    # 或者根据 source_bytes 截取：node_text = source_bytes[node.start_byte:node.end_byte].decode('utf8')
    print(f"{prefix}{node.type} [start:{node.start_byte}, end:{node.end_byte}] '{node_text}'")
    for child in node.children:
        dump_tree(child, source_bytes, indent + 1)


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
    C_DEFINE = "preproc_include"
    C_DECLARATION = "declaration"
    GO_SOURCE_FILE = "source_file"
    GO_DECLARATION = "import_declaration"
    GO_CONST_DECLARTION = "const_declaration"
    GO_DECLARATION = "var_declaration"
    GO_TYPE_DECLARATION = "type_declaration"
    GO_FUNC_DECLARTION = "function_declaration"
    GO_METHOD_DECLARTION = "method_declaration"
    GO_CONST_DECLARATION = "const_declaration"
    GO_PACKAGE_CLAUSE = "package_clause"
    GO_COMMENT = "comment"
    BLOCK = "block"
    BODY = "body"
    STRING = "string"


INDENT_UNIT = "    "  # 定义缩进单位


class SourceSkeleton:
    def __init__(self, parser_loader: ParserLoader):
        self.parser_loader = parser_loader

    def _get_docstring(self, node, parent_type: str):
        """根据Tree-sitter节点类型提取文档字符串"""
        if parent_type == NodeTypes.DECORATED_DEFINITION:
            for i in node.children:
                if i.type == NodeTypes.FUNCTION_DEFINITION:
                    node = i
                    parent_type = NodeTypes.FUNCTION_DEFINITION
                    break
        # 模块文档字符串：第一个连续的字符串表达式
        if parent_type == NodeTypes.MODULE:
            if len(node.children) > 1 and node.children[0].type == NodeTypes.EXPRESSION_STATEMENT:
                return node.children[0].text.decode("utf8")

        # 类/函数文档字符串：body中的第一个字符串表达式
        elif parent_type in (NodeTypes.CLASS_DEFINITION, NodeTypes.FUNCTION_DEFINITION):
            node = node.child_by_field_name(NodeTypes.BODY)
            if node:
                if (
                    len(node.children) > 1
                    and node.children[0].type == NodeTypes.EXPRESSION_STATEMENT
                    and node.children[0].children[0].type == NodeTypes.STRING
                ):
                    return node.children[0].text.decode("utf8")
        elif parent_type in (NodeTypes.GO_FUNC_DECLARTION, NodeTypes.GO_METHOD_DECLARTION):
            prev = node.prev_sibling
            comment_all = []
            while prev.type == NodeTypes.GO_COMMENT:
                comment_all.append(prev.text.decode("utf8"))
                prev = prev.prev_sibling
            return "\n".join(comment_all)
        return None

    def _capture_signature(self, node, source_bytes: bytes) -> str:
        """精确捕获定义签名（基于Tree-sitter解析结构）"""

        start = node.start_byte
        end = 0
        if node.type == NodeTypes.DECORATED_DEFINITION:
            for i, v in enumerate(node.children):
                if v.type in (NodeTypes.FUNCTION_DEFINITION, NodeTypes.CLASS_DEFINITION):
                    for j, v1 in enumerate(v.children):
                        if v1.type == NodeTypes.BLOCK:
                            end = v.children[j - 1].end_byte
                            break
            if end == 0:
                dump_tree(node, source_bytes)
                raise ValueError("unknown ast")

            return source_bytes[start:end].decode("utf8")
        # 捕获定义主体
        elif node.type in (
            NodeTypes.FUNCTION_DEFINITION,
            NodeTypes.CLASS_DEFINITION,
            NodeTypes.GO_FUNC_DECLARTION,
            NodeTypes.GO_METHOD_DECLARTION,
        ):
            end = 0
            for j, v1 in enumerate(node.children):
                if v1.type in (NodeTypes.BLOCK, NodeTypes.COMPOUND_STATEMENT):
                    end = node.children[j - 1].end_byte
                    break
            if end == 0:
                dump_tree(node, source_bytes)
                raise ValueError("unknown ast")
            return source_bytes[start:end].decode("utf8")
        else:
            dump_tree(node, source_bytes)
            raise ValueError("unknown ast")

    def _process_node(self, node, source_bytes: bytes, indent=0, lang_name="") -> List[str]:
        """基于Tree-sitter节点类型的处理逻辑"""
        output = []
        indent_str = INDENT_UNIT * indent
        # 处理模块级元素
        if node.type in (NodeTypes.MODULE, NodeTypes.TRANSLATION_UNIT, NodeTypes.GO_SOURCE_FILE):
            # 处理模块子节点
            for child in node.children:
                if child.type in [
                    NodeTypes.CLASS_DEFINITION,
                    NodeTypes.FUNCTION_DEFINITION,
                    NodeTypes.IMPORT_FROM_STATEMENT,
                    NodeTypes.EXPRESSION_STATEMENT,
                    NodeTypes.IMPORT_STATEMENT,
                    NodeTypes.DECORATED_DEFINITION,
                    NodeTypes.C_DEFINE,
                    NodeTypes.C_DEFINE,
                    NodeTypes.C_DECLARATION,
                    NodeTypes.GO_DECLARATION,
                    NodeTypes.GO_CONST_DECLARTION,
                    NodeTypes.GO_TYPE_DECLARATION,
                    NodeTypes.GO_FUNC_DECLARTION,
                    NodeTypes.GO_METHOD_DECLARTION,
                    NodeTypes.GO_CONST_DECLARATION,
                    NodeTypes.GO_PACKAGE_CLAUSE,
                ]:
                    output.extend(self._process_node(child, source_bytes, lang_name=lang_name))

        # 处理类定义
        elif node.type == NodeTypes.CLASS_DEFINITION:
            # 捕获类签名
            class_sig = self._capture_signature(node, source_bytes)
            output.append(f"\n{class_sig}")

            # 提取类文档字符串
            docstring = self._get_docstring(node, NodeTypes.CLASS_DEFINITION)
            if docstring:
                output.append(f'{indent_str}{INDENT_UNIT}"""{docstring}"""')

            # 处理类成员
            body = node.child_by_field_name(NodeTypes.BODY)
            if body:
                for member in body.children:
                    if member.type in [
                        NodeTypes.FUNCTION_DEFINITION,
                        NodeTypes.DECORATED_DEFINITION,
                        NodeTypes.GO_DECLARATION,
                        NodeTypes.GO_METHOD_DECLARTION,
                    ]:
                        output.extend(self._process_node(member, source_bytes, indent + 1, lang_name=lang_name))
                    elif member.type == NodeTypes.EXPRESSION_STATEMENT:
                        code = source_bytes[member.start_byte : member.end_byte].decode("utf8")
                        output.append(f"{indent_str}{INDENT_UNIT}{code}")

        # 处理函数/方法定义
        elif node.type in [
            NodeTypes.FUNCTION_DEFINITION,
            NodeTypes.DECORATED_DEFINITION,
            NodeTypes.GO_FUNC_DECLARTION,
            NodeTypes.GO_METHOD_DECLARTION,
        ]:
            if self.is_lang_cstyle(lang_name):
                docstring = self._get_docstring(node, node.type)
                if docstring:
                    output.append(f"{indent_str}{docstring}")
            # 捕获函数签名
            func_sig = self._capture_signature(node, source_bytes)
            output.append(f"{indent_str}{func_sig}")
            if not self.is_lang_cstyle(lang_name):
                # 提取函数文档字符串
                docstring = self._get_docstring(node, node.type)
                if docstring:
                    output.append(f"{indent_str}{INDENT_UNIT}{docstring}")
            # 添加占位符
            if self.is_lang_cstyle(lang_name):
                output.append("{\n    //Placeholder\n}")
            else:
                output.append(f"{indent_str}{INDENT_UNIT}pass  # Placeholder")

        # 处理模块级赋值
        elif node.type in (
            NodeTypes.EXPRESSION_STATEMENT,
            NodeTypes.C_DEFINE,
            NodeTypes.GO_DECLARATION,
            NodeTypes.C_DEFINE,
            NodeTypes.C_DECLARATION,
            NodeTypes.IMPORT_STATEMENT,
            NodeTypes.IMPORT_FROM_STATEMENT,
            NodeTypes.GO_CONST_DECLARATION,
            NodeTypes.GO_TYPE_DECLARATION,
            NodeTypes.GO_PACKAGE_CLAUSE,
        ) and node.parent.type in (NodeTypes.MODULE, NodeTypes.GO_SOURCE_FILE, NodeTypes.TRANSLATION_UNIT):
            code = source_bytes[node.start_byte : node.end_byte].decode("utf8")
            output.append(f"{code}")

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
        if self.is_lang_cstyle(lang_name):
            framework = ["// Auto-generated code skeleton\n"]
        else:
            framework = ["# Auto-generated code skeleton\n"]
        framework_content = self._process_node(root, source_bytes, lang_name=lang_name)

        # 合并结果并优化格式
        result = "\n".join(framework + framework_content)
        return re.sub(r"\n{3,}", "\n\n", result).strip() + "\n"


class BlockPatch:
    """用于生成多文件代码块的差异补丁"""

    def __init__(
        self,
        file_paths: list[str],
        patch_ranges: list[tuple],
        block_contents: list[bytes],
        update_contents: list[bytes],
    ):
        """
        初始化补丁对象（支持多文件）

        参数：
            file_paths: 源文件路径列表
            patch_ranges: 补丁范围列表，每个元素格式为(start_pos, end_pos)
            block_contents: 原始块内容列表(bytes)
            update_contents: 更新后的内容列表(bytes)
        """
        if len({len(file_paths), len(patch_ranges), len(block_contents), len(update_contents)}) != 1:
            raise ValueError("所有参数列表的长度必须一致")

        # 过滤掉没有实际更新的块
        self.file_paths = []
        self.patch_ranges = []
        self.block_contents = []
        self.update_contents = []
        for i in range(len(file_paths)):
            if block_contents[i] != update_contents[i]:
                self.file_paths.append(file_paths[i])
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
                except UnicodeDecodeError:
                    raise ValueError(f"文件 {path} 不是UTF-8编码，拒绝修改以避免不可预测的结果")
                self.source_codes[path] = content

    def _is_binary_file(self, content: bytes) -> bool:
        """判断文件是否为二进制文件"""
        # 常见二进制文件的magic number
        binary_magic_numbers = {
            b"\x89PNG",  # PNG
            b"\xff\xd8",  # JPEG
            b"GIF",  # GIF
            b"BM",  # BMP
            b"%PDF",  # PDF
            b"MZ",  # Windows PE executable
            b"\x7fELF",  # ELF executable
            b"PK",  # ZIP
            b"Rar!",  # RAR
        }

        # 检查文件头是否匹配已知的二进制文件类型
        for magic in binary_magic_numbers:
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

        # 生成完整文件差异
        return list(
            unified_diff(
                original_code.decode("utf8").splitlines(keepends=True),
                modified_code.splitlines(keepends=True),
                fromfile=file_path,
                tofile=file_path,
                lineterm="",
                n=3,
            )
        )

    def generate_diff(self) -> str:
        """生成多文件差异补丁"""
        if not self.file_paths:
            return ""

        diff_output = []
        # 按文件分组处理
        file_groups = defaultdict(list)
        for idx, path in enumerate(self.file_paths):
            file_groups[path].append(idx)

        for file_path, indices in file_groups.items():
            diff_output.extend(self._process_single_file_diff(file_path, indices))

        return "".join(diff_output)

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
        prev_lines_len = sum(len(l) for l in lines[:row])
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
    # 创建临时文件并写入测试代码
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".c", delete=False) as tmp_file:
        code = """// Sample code
#include <stdio.h>

int main() {
    printf("Hello\\n");
    return 0;
}"""
        tmp_file.write(code)
        tmp_file_path = tmp_file.name

    try:
        # 获取解析器和查询对象
        parser_loader = ParserLoader()
        query_str = """
        (return_statement) @return
        """
        LANGUAGE_QUERIES["c"] = query_str
        lang_parser, query, _ = parser_loader.get_parser("test.c")

        # 解析代码文件
        tree = parse_code_file(tmp_file_path, lang_parser)
        captures = query.matches(tree.root_node)

        # 验证是否找到return语句
        assert len(captures) > 0, "未找到return语句"

        # 获取第一个return语句的节点
        _, capture = captures[0]
        return_node = capture["return"][0]
        # 使用split_source提取代码
        start_row, start_col = return_node.start_point
        end_row, end_col = return_node.end_point
        before, selected, after = split_source(code, start_row, start_col, end_row, end_col)

        # 验证提取结果
        assert selected == "return 0;", "提取的return语句不匹配"
        assert (
            before
            == """// Sample code
#include <stdio.h>

int main() {
    printf("Hello\\n");
    """
        ), "前段内容不匹配"
        assert after == "\n}", "后段内容不匹配"

        # 测试BlockPatch功能
        patch = BlockPatch(
            file_paths=[tmp_file_path],
            patch_ranges=[(return_node.start_byte, return_node.end_byte)],
            block_contents=[selected.encode("utf-8")],
            update_contents=[b"return 1;"],
        )

        # 生成差异
        diff = patch.generate_diff()
        assert "-    return 0;" in diff, "差异中缺少删除行"
        assert "+    return 1;" in diff, "差异中缺少添加行"

        # 应用补丁
        file_map = patch.apply_patch()
        assert b"return 1;" in list(file_map.values())[0], "修改后的代码中缺少更新内容"

        # 测试符号解析功能
        parser_util = ParserUtil(parser_loader)
        symbol_trie = SymbolTrie()

        # 解析测试文件并更新符号前缀树
        parser_util.update_symbol_trie(tmp_file_path, symbol_trie)

        # 测试精确搜索
        main_symbol = symbol_trie.search_exact("main")
        assert main_symbol is not None, "未找到main函数符号"
        assert main_symbol["file_path"] == tmp_file_path, "文件路径不匹配"

        # 测试前缀搜索
        prefix_results = symbol_trie.search_prefix("main")
        assert len(prefix_results) > 0, "前缀搜索未找到结果"
        assert any(result["name"] == "main" for result in prefix_results), "未找到main函数符号"

        # 打印符号路径
        print("\n测试文件中的符号路径：")
        parser_util.print_symbol_paths(tmp_file_path)

    finally:
        # 删除临时文件
        os.unlink(tmp_file_path)


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

    for i, method_node in enumerate(captures.get("method.name", [])):
        process_class_method(captures, i, async_lines, class_name, symbols, block_array)


def process_class_method(
    captures: Dict, index: int, async_lines: List[int], class_name: str, symbols: Dict, block_array: List
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
        elif line < block_start:
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
    if not (start[0] <= node_start[0] <= end[0]):
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

    # 分层查询调用关系
    for depth in range(max_depth + 1):
        next_symbols = []

        for symbol, path in current_symbols:
            # 查询当前符号的定义
            if path:
                query = "SELECT name, file_path, calls FROM symbols WHERE name = ? AND file_path LIKE ?"
                params = (symbol, f"%{path}%")
            else:
                query = "SELECT name, file_path, calls FROM symbols WHERE name = ?"
                params = (symbol,)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            if not rows:
                continue

            # 记录符号信息（优先保留当前文件中的定义）
            for name, path, calls in rows:
                if name not in symbol_dict or path == file_path:
                    symbol_dict[name] = path

            # 收集下一层要查询的符号
            for name, path, calls in rows:
                try:
                    called_symbols = json.loads(calls)
                    next_symbols.extend([(s, path) for s in called_symbols])
                except json.JSONDecodeError:
                    continue

        current_symbols = list(set(next_symbols))  # 去重

        if not current_symbols:
            break

    # 确保目标符号在结果中
    if symbol_name not in symbol_dict:
        return {"error": f"未找到符号 {symbol_name} 的定义"}

    # 按优先级排序：当前文件中的符号优先，目标符号优先，其他符号按字母顺序
    sorted_symbols = sorted(
        symbol_dict.keys(),
        key=lambda x: (
            file_path and symbol_dict[x] != file_path,  # 当前文件中的符号排在最前
            x != symbol_name,  # 目标符号其次
            x,  # 其他符号按字母顺序
        ),
    )

    # 查询符号定义
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

    definitions = []
    for row in cursor.fetchall():
        definitions.append({"name": row[0], "file_path": row[1], "full_definition": row[2]})

    return {"symbol_name": symbol_name, "file_path": file_path, "max_depth": max_depth, "definitions": definitions}


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
    如果是__init__.py文件，尝试提取上一级目录名
    否则直接返回文件名

    Args:
        file_path: 文件路径

    Returns:
        易于识别的路径部分
    """
    # 使用os.path处理路径，确保跨平台兼容性
    base_name = os.path.basename(file_path)
    if base_name == "__init__.py":
        # 获取上一级目录名
        dir_name = os.path.basename(os.path.dirname(file_path))
        if dir_name:
            # 使用os.path.join确保路径分隔符正确
            return os.path.join(dir_name, base_name)
    return base_name


import pdb


@app.get("/symbol_content")
async def get_symbol_content(symbol_path: str = QueryArgs(..., min_length=1), json: bool = False):
    """根据符号路径获取符号对应的源代码内容

    Args:
        symbol_path: 符号路径，格式为file_path>a>b>c
        json: 是否返回JSON格式，包含行号信息

    Returns:
        纯文本格式的源代码内容，或包含行号信息的JSON
    """
    trie = app.state.file_symbol_trie
    file_mtime_cache = app.state.file_mtime_cache
    # 检查并更新前缀树
    update_trie_if_needed(symbol_path, trie, file_mtime_cache)
    # 在前缀树中搜索符号路径
    result = trie.search_exact(symbol_path)

    if not result:
        return PlainTextResponse("未找到符号内容", status_code=404)

    # 获取符号的位置信息
    location = result["location"]
    file_path = result["file_path"]

    # 读取源代码文件
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception as e:
        return PlainTextResponse(f"无法读取文件: {str(e)}", status_code=500)

    # 提取符号对应的代码内容
    start_line, start_col = location[0]
    end_line, end_col = location[1]
    block_range = location[2]
    # 将源代码按行分割
    lines = source_code.splitlines()

    # 如果符号跨多行
    if start_line == end_line:
        # 单行情况
        line = lines[start_line]
        content = line[start_col:end_col]
    else:
        # 多行情况
        content_lines = []
        # 第一行
        first_line = lines[start_line]
        content_lines.append(first_line[start_col:])
        # 中间行
        for i in range(start_line + 1, end_line):
            content_lines.append(lines[i])
        # 最后一行
        last_line = lines[end_line]
        content_lines.append(last_line[:end_col])
        content = "\n".join(content_lines)

    if json:
        # 返回JSON格式，包含行号信息
        return {
            "file_path": file_path,
            "content": content,
            "location": {
                "start_line": start_line,
                "start_col": start_col,
                "end_line": end_line,
                "end_col": end_col,
                "block_range": block_range,
            },
        }
    return PlainTextResponse(content)


def update_trie_if_needed(prefix: str, trie, file_mtime_cache) -> bool:
    """根据前缀更新前缀树，如果需要的话

    Args:
        prefix: 要检查的前缀
        trie: 前缀树对象
        file_mtime_cache: 文件修改时间缓存

    Returns:
        bool: 是否执行了更新操作
    """
    if not prefix.startswith("symbol:"):
        return False

    pattern = r"symbol:([^/]+.*?(?:" + "|".join(re.escape(ext) for ext in SUPPORTED_LANGUAGES.keys()) + r"))/?"
    match = re.search(pattern, prefix)
    if not match:
        return False

    file_path = match.group(1)
    if not os.path.exists(file_path):
        return False

    current_mtime = os.path.getmtime(file_path)
    cached_mtime = file_mtime_cache.get(file_path, 0)

    if current_mtime > cached_mtime:
        print(f"[DEBUG] 检测到文件修改: {file_path} (旧时间:{cached_mtime} 新时间:{current_mtime})")
        parser_loader = ParserLoader()
        parser_util = ParserUtil(parser_loader)
        parser_util.update_symbol_trie(file_path, trie)
        file_mtime_cache[file_path] = current_mtime
        return True

    return False


@app.get("/complete_realtime")
async def symbol_completion_realtime(prefix: str = QueryArgs(..., min_length=1), max_results: int = 10):
    """实时符号补全，直接解析指定文件并返回符号列表

    Args:
        file_path: 要解析的文件路径
        max_results: 最大返回结果数量，默认为10，范围1-50

    Returns:
        纯文本格式的符号列表，每行一个符号
    """
    trie = app.state.file_symbol_trie
    max_results = max(1, min(50, int(max_results)))
    file_mtime_cache = app.state.file_mtime_cache

    # 检查并更新前缀树
    updated = update_trie_if_needed(prefix, trie, file_mtime_cache)

    # 搜索前缀
    results = trie.search_prefix(prefix, max_results=max_results)

    # 如果没有找到结果，尝试强制更新并重新搜索
    if not results and not updated:
        if update_trie_if_needed(prefix, trie, file_mtime_cache):
            results = trie.search_prefix(prefix, max_results)

    return PlainTextResponse("\n".join(result["name"] for result in results))


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


def test_symbols_api():
    """测试符号相关API"""
    globals()["GLOBAL_DB_CONN"] = sqlite3.connect(":memory:")
    # 初始化内存数据库
    test_conn = globals()["GLOBAL_DB_CONN"]
    init_symbol_database(test_conn)

    # 准备测试数据
    test_symbols = [
        {
            "name": "main_function",
            "file_path": "/path/to/file",
            "type": "function",
            "signature": "def main_function()",
            "body": "pass",
            "full_definition": "def main_function(): pass",
            "calls": ["helper_function", "undefined_function"],
        },
        {
            "name": "helper_function",
            "file_path": "/path/to/file",
            "type": "function",
            "signature": "def helper_function()",
            "body": "pass",
            "full_definition": "def helper_function(): pass",
            "calls": [],
        },
        {
            "name": "calculate_sum",
            "file_path": "/path/to/file",
            "type": "function",
            "signature": "def calculate_sum(a, b)",
            "body": "return a + b",
            "full_definition": "def calculate_sum(a, b): return a + b",
            "calls": [],
        },
        {
            "name": "compute_average",
            "file_path": "/path/to/file",
            "type": "function",
            "signature": "def compute_average(values)",
            "body": "return sum(values) / len(values)",
            "full_definition": "def compute_average(values): return sum(values) / len(values)",
            "calls": [],
        },
        {
            "name": "init_module",
            "file_path": "/path/to/__init__.py",
            "type": "module",
            "signature": "",
            "body": "",
            "full_definition": "",
            "calls": [],
        },
        {
            "name": "symbol:test/symbol",
            "file_path": "/path/to/symbol.py",
            "type": "symbol",
            "signature": "",
            "body": "",
            "full_definition": "",
            "calls": [],
        },
    ]
    trie = SymbolTrie.from_symbols({})
    app.state.symbol_trie = trie
    app.state.file_symbol_trie = SymbolTrie.from_symbols({})
    app.state.file_mtime_cache = {}
    # 插入测试数据
    for symbol in test_symbols:
        insert_symbol(test_conn, symbol)

    # 创建新的事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # 测试搜索接口
        response = loop.run_until_complete(search_symbols_api("main", 10))
        assert len(response["results"]) == 1

        # 测试获取符号信息接口
        response = loop.run_until_complete(search_symbols_api("main_function", 10))
        assert len(response["results"]) == 1
        assert response["results"][0]["name"] == "main_function"

        # 测试获取符号上下文接口
        response = loop.run_until_complete(get_symbol_context_api("main_function", "/path/to/file"))
        assert response["symbol_name"] == "main_function"
        assert len(response["definitions"]) == 2

        response = loop.run_until_complete(get_symbol_context_api("nonexistent", "/path/to/file"))
        assert "error" in response

        # 测试前缀搜索接口
        response = loop.run_until_complete(symbol_completion("calc"))
        assert len(response["completions"]) == 1
        assert response["completions"][0]["name"] == "calculate_sum"

        response = loop.run_until_complete(symbol_completion("xyz"))
        assert len(response["completions"]) == 0

        # 测试简化版符号补全接口
        # 情况1：正常符号补全
        response = loop.run_until_complete(symbol_completion_simple("calc"))
        assert b"symbol:file/calculate_sum" in response.body

        # 情况2：包含路径的符号补全
        response = loop.run_until_complete(symbol_completion_simple("symbol:test/"))
        assert b"symbol:test/symbol" in response.body

        # 新增测试实时符号补全接口
        # 情况1：测试存在的文件路径
        response = loop.run_until_complete(symbol_completion_realtime("symbol:file", 10))
        assert b"main_function" in response.body
        assert b"helper_function" in response.body

        # 情况2：测试不存在的文件路径
        response = loop.run_until_complete(symbol_completion_realtime("symbol:nonexistent", 10))
        assert response.body == b""

    finally:
        # 关闭事件循环
        loop.close()
        # 删除测试符号
        test_conn.execute("DELETE FROM symbols WHERE file_path = ?", ("/path/to/file",))
        test_conn.commit()


def debug_tree_source_file(file_path: Path):
    """调试函数：解析指定文件并打印整个语法树结构

    Args:
        file_path: 要调试的源代码文件路径
    """
    try:
        # 获取解析器和查询对象
        parser, _, _ = ParserLoader().get_parser(str(file_path))
        print(f"[DEBUG] 开始解析文件: {file_path}")

        # 解析文件并获取语法树
        tree = parse_code_file(file_path, parser)
        print(f"[DEBUG] 文件解析完成，开始打印语法树")

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
        print(f"[DEBUG] 语法树打印完成")

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
        print(f"[DEBUG] 文件解析完成，开始匹配查询")
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

        print("\n处理完成，共找到 {} 个符号".format(len(symbols)))

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
        with open(formatted_file_path, "r") as f:
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

    # 创建线程池
    with ThreadPoolExecutor(max_workers=cpu_count) as executor:
        try:
            # 使用 tqdm 显示进度条
            with tqdm(total=len(files_to_format), desc="格式化进度", unit="文件") as pbar:
                futures = {executor.submit(format_file, file_path): file_path for file_path in files_to_format}

                for future in as_completed(futures):
                    file_path, success, duration, error = future.result()
                    pbar.set_postfix_str(f"正在处理: {os.path.basename(file_path)}")
                    if success:
                        pbar.write(f"✓ 成功格式化: {file_path} (耗时: {duration:.2f}s)")
                    else:
                        pbar.write(f"✗ 格式化失败: {file_path} (错误: {error})")
                    pbar.update(1)

            # 将已格式化的文件列表写入点号文件
            with open(formatted_file_path, "w") as f:
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
        print(f"\r加载符号中... {spinner[idx]} 已处理 {processed}/{total_rows}", end="", flush=True)

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
        print(f"  内存中第 {idx+1} 个实例：")
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
        print(f"  数据库中第 {idx+1} 个实例：")
        print(f"    文件路径: {record[2]}")
        print(f"    签名: {record[4]}")
        print(f"    完整定义哈希: {record[7]}")
        t = record[6]
        print(f"    完整定义内容: {record[6]}")
    t2 = data[6]
    # 使用difflib生成unified diff格式的差异对比

    diff = unified_diff(t.splitlines(), t2.splitlines(), fromfile="数据库中的定义", tofile="内存中的定义", lineterm="")
    print("符号定义差异对比：")
    for line in diff:
        print(line)
    # import pdb

    # pdb.set_trace()


def process_symbols_to_db(conn: sqlite3.Connection, file_path: Path, symbols: dict, all_existing_symbols: dict):
    """单线程数据库写入"""
    try:
        start_time = time.time() * 1000
        full_path = str(file_path.resolve().absolute())
        file_hash = calculate_file_hash(file_path)
        last_modified = file_path.stat().st_mtime

        # 开始事务
        conn.execute("BEGIN TRANSACTION")

        # 准备数据
        prepare_start = time.time() * 1000
        insert_data, duplicate_count = prepare_insert_data(symbols, all_existing_symbols, full_path)
        prepare_time = time.time() * 1000 - prepare_start

        # 插入或更新符号数据
        insert_start = time.time() * 1000
        if insert_data:
            # 先进行过滤
            filtered_data = []
            for data in insert_data:
                symbol_name = data[1]
                if symbol_name not in all_existing_symbols:
                    all_existing_symbols[symbol_name] = []
                # 检查哈希值是否已经存在，避免重复添加
                if not any(existing[2] == data[7] for existing in all_existing_symbols[symbol_name]):
                    filtered_data.append(data)
                    all_existing_symbols[symbol_name].append((full_path, data[4], data[7]))
                    # 调试重复符号（需要时取消注释）
                    # if "get_proc_task" in symbol_name and len(all_existing_symbols[symbol_name]) > 1:
                    #     debug_duplicate_symbol(symbol_name, all_existing_symbols, conn, data)

                    # 更新前缀树
                    symbol_info = {
                        "name": data[1],
                        "file_path": data[2],
                        "signature": data[4],
                        "full_definition_hash": data[7],
                    }
                    app.state.symbol_trie.insert(symbol_name, symbol_info)

            # 插入过滤后的数据
            if filtered_data:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO symbols
                    (id, name, file_path, type, signature, body, full_definition, full_definition_hash, calls)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8])
                        for data in filtered_data
                    ],
                )
        insert_time = time.time() * 1000 - insert_start

        # 更新文件元数据
        meta_start = time.time() * 1000
        total_symbols = len(symbols)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO file_metadata
            (file_path, last_modified, file_hash, total_symbols)
            VALUES (?, ?, ?, ?)
            """,
            (full_path, last_modified, file_hash, total_symbols),
        )
        meta_time = time.time() * 1000 - meta_start

        conn.commit()

        # 输出统计信息
        total_time = time.time() * 1000 - start_time
        print(f"\n文件 {file_path} 处理完成：")
        print(f"  总符号数: {total_symbols}")
        print(f"  重复符号数: {duplicate_count}")
        print(f"  新增符号数: {len(insert_data)}")
        print(f"  过滤符号数: {duplicate_count + (total_symbols - len(symbols))}")
        print(f"  性能数据（单位：毫秒）：")
        print(f"    数据准备: {prepare_time:.2f}")
        print(f"    数据插入: {insert_time:.2f}")
        print(f"    元数据更新: {meta_time:.2f}")
        print(f"    总耗时: {total_time:.2f}")

    except Exception as e:
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
    # 检查路径是否存在
    non_existent_paths = [path for path in project_paths if not Path(path).exists()]
    if non_existent_paths:
        raise ValueError(f"以下路径不存在: {', '.join(non_existent_paths)}")

    suffixes = include_suffixes if include_suffixes else SUPPORTED_LANGUAGES.keys()

    # 获取数据库统计信息
    total_symbols, total_files, indexes = get_database_stats(conn)
    print("\n数据库当前状态：")
    print(f"  总符号数: {total_symbols}")
    print(f"  总文件数: {total_files}")
    print(f"  索引数量: {len(indexes)}")
    for idx in indexes:
        print(f"    索引名: {idx[1]}, 唯一性: {'是' if idx[2] else '否'}")

    # 获取已存在符号
    all_existing_symbols = get_existing_symbols(conn)
    trie = SymbolTrie.from_symbols(all_existing_symbols)
    app.state.symbol_trie = trie
    app.state.file_symbol_trie = SymbolTrie.from_symbols({})
    app.state.file_mtime_cache = {}
    # 获取需要处理的文件列表
    tasks = []
    for project_path in project_paths:
        project_dir = Path(project_path)
        if not project_dir.exists():
            print(f"警告：项目路径 {project_path} 不存在，跳过处理")
            continue

        for file_path in project_dir.rglob("*"):
            # 检查文件后缀是否在支持列表中
            if file_path.suffix.lower() not in suffixes:
                continue

            # 检查文件路径是否在排除列表中
            full_path = str((project_dir / file_path).resolve().absolute())
            if excludes:
                excluded = False
                for pattern in excludes:
                    if fnmatch.fnmatch(full_path, pattern):
                        excluded = True
                        break
                if excluded:
                    continue

            need_process = check_file_needs_processing(conn, full_path)
            if need_process:
                tasks.append(file_path)

    # 根据并行度选择处理方式
    if parallel in (0, 1):
        # 单进程处理
        print("\n使用单进程模式处理文件...")
        for file_path in tasks:
            print(f"[INFO] 开始处理文件: {file_path}")
            file_path, symbols = parse_worker_wrapper(file_path)
            if file_path:
                print(f"[INFO] 文件 {file_path} 解析完成，开始插入数据库...")
                process_symbols_to_db(
                    conn=conn, file_path=file_path, symbols=symbols, all_existing_symbols=all_existing_symbols
                )
                print(f"[INFO] 文件 {file_path} 数据库插入完成")
    else:
        # 多进程处理
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
                print(f"已完成批次 {i//batch_size + 1}/{(len(tasks)//batch_size)+1}")
                # 单线程处理数据库写入
                for file_path, symbols in results:
                    if not file_path:
                        continue
                    process_symbols_to_db(
                        conn=conn, file_path=file_path, symbols=symbols, all_existing_symbols=all_existing_symbols
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
            project_paths, conn, excludes=excludes, include_suffixes=include_suffixes, parallel=parallel
        )
        print("符号索引构建完成")
    finally:
        # 关闭数据库连接
        conn.close()


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
    build_index(project_paths, excludes, include_suffixes, db_path, parallel)
    # 启动FastAPI服务
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse
    import logging

    # 配置日志格式
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    arg_parser = argparse.ArgumentParser(description="代码分析工具")
    arg_parser.add_argument("--host", type=str, default="127.0.0.1", help="HTTP服务器绑定地址")
    arg_parser.add_argument("--port", type=int, default=8000, help="HTTP服务器绑定端口")
    arg_parser.add_argument("--project", type=str, nargs="+", default=["."], help="项目根目录路径（可指定多个）")
    arg_parser.add_argument("--demo", action="store_true", help="运行演示模式")
    arg_parser.add_argument("--include", type=str, nargs="+", help="要包含的文件后缀列表（可指定多个，如 .c .h）")
    arg_parser.add_argument("--debug-file", type=str, help="单文件调试模式，指定要调试的文件路径")
    arg_parser.add_argument("--debug-tree", type=str, help="树结构调试模式，指定要调试的文件路径")
    arg_parser.add_argument("--format-dir", type=str, help="指定要格式化的目录路径")
    arg_parser.add_argument("--build-index", action="store_true", help="构建符号索引")
    arg_parser.add_argument("--db-path", type=str, default="symbols.db", help="符号数据库文件路径")
    arg_parser.add_argument("--excludes", type=str, nargs="+", help="要排除的文件或目录路径列表（可指定多个）")
    arg_parser.add_argument("--parallel", type=int, default=-1, help="并行度，-1表示使用CPU核心数，0或1表示单进程")
    arg_parser.add_argument("--debug-symbol-path", type=str, help="输出指定文件的符号路径")
    arg_parser.add_argument("--debug-skeleton", type=str, help="调试源代码框架，指定要调试的文件路径")
    arg_parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="设置日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )

    args = arg_parser.parse_args()

    # 设置日志级别
    logging.getLogger().setLevel(args.log_level)
    logger = logging.getLogger(__name__)
    logger.info("启动代码分析工具，日志级别设置为：%s", args.log_level)

    DEFAULT_DB = args.db_path
    if args.demo:
        logger.debug("进入演示模式")
        test_split_source_and_patch()
        demo_main()
        test_symbols_api()
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
        print(framework)
    else:
        logger.info("启动FastAPI服务")
        main(
            host=args.host,
            port=args.port,
            project_paths=args.project,
            excludes=args.excludes,
            include_suffixes=args.include,
            db_path=args.db_path,
            parallel=args.parallel,
        )
