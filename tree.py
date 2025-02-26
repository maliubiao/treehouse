import asyncio
import hashlib
import importlib
import json
import os
import re
import sqlite3
import subprocess
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Dict, List, Optional, Union

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi import Query as QueryArgs
from pydantic import BaseModel
from tqdm import tqdm  # 用于显示进度条
from tree_sitter import Language, Parser, Query

# 文件后缀到语言名称的映射
SUPPORTED_LANGUAGES = {
    ".c": "c",
    ".h": "c",
    ".py": "python",
    ".js": "javascript",
    ".java": "java",
    ".go": "go",
}

# 各语言的查询语句映射
LANGUAGE_QUERIES = {
    "c": """
    [
        (declaration
            (storage_class_specifier) @storage_class
            type: _ @return_type
            declarator: (function_declarator
                declarator: (identifier) @symbol_name
                parameters: (parameter_list) @params
            )
        ) @func_decl
        
        (function_definition
            type: _ @return_type
            declarator: (function_declarator
                declarator: (identifier) @symbol_name
                parameters: (parameter_list) @params
            )
            body: (compound_statement) @body
        )
        (function_definition
            type: _ @return_type
            declarator: (pointer_declarator
              declarator: (function_declarator
                  declarator: (identifier) @symbol_name
                  parameters: (parameter_list) @params
              )
            )
            body: (compound_statement) @body
        )  
        (preproc_def
            name: (identifier) @symbol_name
            value: (_) @macro_value
        )
    ]
    (
        (call_expression
            function: (identifier) @called_function
            (#not-match? @called_function "^(__builtin_|typeof$)")
        ) @call
    )
    """,
    "python": """
    [
        (function_definition
            (async) @async_keyword
            name: (identifier) @symbol_name
            parameters: (parameters) @params
            return_type: (_)? @return_type
            body: (block) @body
        )
        
        (class_definition
            name: (identifier) @symbol_name
            body: (block) @body
        )
    ]
    (
        (call
            function: (identifier) @called_function
        ) @call
        (#contains? @body @call)
    )
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

    def get_parser(self, file_path: str) -> tuple[Parser, Query]:
        """根据文件路径获取对应的解析器和查询对象"""
        suffix = Path(file_path).suffix.lower()
        lang_name = SUPPORTED_LANGUAGES.get(suffix)
        if not lang_name:
            raise ValueError(f"不支持的文件类型: {suffix}")

        if lang_name in self._parsers:
            return self._parsers[lang_name], self._queries[lang_name]

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
        return lang_parser, query


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
    return tree, code


def get_code_from_node(code, node):
    """根据Node对象提取代码片段"""
    return code[node.start_byte : node.end_byte]


def process_matches(matches, code):
    """处理查询匹配结果"""
    symbols = {}
    current_function = None
    symbol_name = None

    for match in matches:
        _, captures = match
        if not captures:
            continue
        # print({k: [n.text.decode("utf-8") for n in v] for k, v in captures.items()})

        if "symbol_name" in captures:
            symbol_node = captures["symbol_name"][0]
            symbol_name = code[symbol_node.start_byte : symbol_node.end_byte]

        if "storage_class" in captures and captures["storage_class"][0].text == b"extern":
            return_type = get_code_from_node(code, captures["return_type"][0])
            params = get_code_from_node(code, captures["params"][0])
            signature = f"extern {return_type} {symbol_name}{params};"
            symbols[symbol_name] = {
                "type": "external_function",
                "signature": signature,
                "body": None,
                "full_definition": signature,
                "calls": [],
            }
            continue

        if "return_type" in captures and "body" in captures:
            return_type_node = captures["return_type"][0]
            return_type = code[return_type_node.start_byte : return_type_node.end_byte]

            params_node = captures["params"][0]
            params = code[params_node.start_byte : params_node.end_byte]

            body_node = captures["body"][0]
            body = code[body_node.start_byte : body_node.end_byte]

            full_definition = f"{return_type} {symbol_name}{params} {body}"

            symbols[symbol_name] = {
                "type": "function",
                "signature": f"{return_type} {symbol_name}{params}",
                "body": body,
                "full_definition": full_definition,
                "calls": [],
            }
            current_function = symbol_name

        elif "macro_value" in captures:
            macro_node = captures["macro_value"][0]
            macro_value = code[macro_node.start_byte : macro_node.end_byte]
            symbols[symbol_name] = {"type": "macro", "value": macro_value}

        elif "called_function" in captures and current_function:
            called_node = captures["called_function"][0]
            called_func = code[called_node.start_byte : called_node.end_byte]
            if called_func not in symbols[current_function]["calls"]:
                symbols[current_function]["calls"].append(called_func)

    return symbols


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
    lang_parser, query = parser_loader.get_parser("test.c")

    # 解析代码文件
    tree, code = parse_code_file("test.c", lang_parser)

    # 执行查询并处理结果
    matches = query.matches(tree.root_node)
    symbols = process_matches(matches, code)

    # 生成并打印 JSON 输出
    output = generate_json_output(symbols)
    print(output)
    print(generate_mermaid_dependency_graph(symbols))
    # 打印 main 函数调用链
    print_main_call_chain(symbols)


app = FastAPI()

# 全局数据库连接
global_db_conn = None


def get_db_connection():
    """获取全局数据库连接"""
    global global_db_conn
    if global_db_conn is None:
        global_db_conn = init_symbol_database()
    return global_db_conn


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
        # 验证输入
        for field in ["name", "file_path", "type", "signature", "body", "full_definition"]:
            validate_input(str(symbol_info[field]))

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


def get_symbol_info(conn, symbol_name: str, file_path: Optional[str] = None) -> Optional[SymbolInfo]:
    """获取符号的完整信息"""
    validate_input(symbol_name)

    cursor = conn.cursor()
    if file_path:
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

    row = cursor.fetchone()
    if row:
        return SymbolInfo(
            name=row[0],
            file_path=row[1],
            type=row[2],
            signature=row[3],
            body=row[4],
            full_definition=row[5],
            calls=json.loads(row[6]) if row[6] else [],
        )
    return None


@app.get("/symbols/search")
async def search_symbols_api(prefix: str = QueryArgs(..., min_length=1), limit: int = QueryArgs(10, ge=1, le=100)):
    """符号搜索API"""
    try:
        validate_input(prefix)
        conn = get_db_connection()
        results = search_symbols(conn, prefix, limit)
        return {"results": results}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/symbols/{symbol_name}")
async def get_symbol_info_api(symbol_name: str, file_path: Optional[str] = QueryArgs(None)):
    """获取符号信息API"""
    try:
        validate_input(symbol_name)
        conn = get_db_connection()
        symbol_info = get_symbol_info(conn, symbol_name, file_path)
        if symbol_info:
            return symbol_info
        return {"error": "Symbol not found"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def get_symbol_context(conn, symbol_name: str, file_path: Optional[str] = None, max_depth: int = 3) -> dict:
    """获取符号的调用树上下文（带深度限制）"""
    validate_input(symbol_name)
    if max_depth < 0 or max_depth > 10:
        raise ValueError("深度值必须在0到10之间")

    cursor = conn.cursor()
    if file_path:
        cursor.execute(
            """
            WITH RECURSIVE call_tree(name, file_path, depth) AS (
                SELECT s.name, s.file_path, 0
                FROM symbols s
                WHERE s.name = ? AND s.file_path LIKE ?
                
                UNION ALL
                
                SELECT json_each.value, s.file_path, ct.depth + 1
                FROM call_tree ct
                JOIN symbols s ON ct.name = s.name AND ct.file_path = s.file_path
                JOIN json_each(s.calls)
                WHERE ct.depth < ?
            )
            SELECT DISTINCT name, file_path 
            FROM call_tree
            WHERE depth <= ?
            """,
            (symbol_name, f"%{file_path}%", max_depth - 1, max_depth),
        )
    else:
        cursor.execute(
            """
            WITH RECURSIVE call_tree(name, file_path, depth) AS (
                SELECT s.name, s.file_path, 0
                FROM symbols s
                WHERE s.name = ?
                
                UNION ALL
                
                SELECT json_each.value, s.file_path, ct.depth + 1
                FROM call_tree ct
                JOIN symbols s ON ct.name = s.name AND ct.file_path = s.file_path
                JOIN json_each(s.calls)
                WHERE ct.depth < ?
            )
            SELECT DISTINCT name, file_path 
            FROM call_tree
            WHERE depth <= ?
            """,
            (symbol_name, max_depth - 1, max_depth),
        )

    # 获取所有结果并处理重复符号
    rows = cursor.fetchall()
    if not rows:
        return {"error": f"未找到符号 {symbol_name} 的定义"}

    # 创建一个字典来存储符号及其文件路径
    symbol_dict = {}
    for name, path in rows:
        if name not in symbol_dict:
            symbol_dict[name] = path
        else:
            # 如果当前符号已经存在，且当前路径与目标文件更匹配，则更新
            if file_path and path.endswith(file_path):
                symbol_dict[name] = path

    # 确保目标符号在结果中
    if symbol_name not in symbol_dict:
        symbol_dict[symbol_name] = file_path if file_path else rows[0][1]

    # 按优先级排序：目标符号在前，其他符号按字母顺序
    sorted_symbols = sorted(symbol_dict.keys(), key=lambda x: (x != symbol_name, x))

    # 查询符号定义
    placeholders = ",".join(["?"] * len(sorted_symbols))
    cursor.execute(
        f"""
        SELECT name, file_path, full_definition 
        FROM symbols 
        WHERE name IN ({placeholders})
        """,
        sorted_symbols,
    )

    definitions = []
    for row in cursor.fetchall():
        definitions.append({"name": row[0], "file_path": row[1], "full_definition": row[2]})

    return {"symbol_name": symbol_name, "file_path": file_path, "max_depth": max_depth, "definitions": definitions}


@app.get("/symbols/{symbol_name}/context")
async def get_symbol_context_api(symbol_name: str, file_path: Optional[str] = QueryArgs(None), max_depth: int = 3):
    """获取符号上下文API"""
    try:
        validate_input(symbol_name)
        conn = get_db_connection()
        context = get_symbol_context(conn, symbol_name, file_path, max_depth)
        return context
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/symbols/complete")
async def symbol_completion(prefix: str = QueryArgs(..., min_length=1), max_results: int = 10):
    trie = app.state.symbol_trie
    # 确保max_results是整数类型
    max_results = int(max_results)
    # 限制结果范围在1到50之间
    max_results = max(1, min(50, max_results))
    results = trie.search_prefix(prefix)[:max_results]
    return {"completions": results}


def test_symbols_api():
    """测试符号相关API"""
    globals()["global_db_conn"] = sqlite3.connect(":memory:")
    # 初始化内存数据库
    test_conn = globals()["global_db_conn"]
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
            "calls": ["helper_function", "undefined_function"],  # 增加未定义的函数
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
    ]
    trie = SymbolTrie.from_symbols({})
    app.state.symbol_trie = trie
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
        response = loop.run_until_complete(get_symbol_info_api("main_function", "/path/to/file"))
        assert response.name == "main_function"

        # 测试获取符号上下文接口
        # 情况1：正常获取上下文
        response = loop.run_until_complete(get_symbol_context_api("main_function", "/path/to/file"))
        assert response["symbol_name"] == "main_function"
        assert len(response["definitions"]) == 2

        # 情况2：获取不存在的符号上下文
        response = loop.run_until_complete(get_symbol_context_api("nonexistent", "/path/to/file"))
        assert "error" in response

        # 测试前缀搜索接口
        # 情况1：正常前缀搜索
        response = loop.run_until_complete(symbol_completion("calc"))
        assert len(response["completions"]) == 1
        assert response["completions"][0]["name"] == "calculate_sum"

        # 情况2：无匹配结果的前缀搜索
        response = loop.run_until_complete(symbol_completion("xyz"))
        assert len(response["completions"]) == 0

    finally:
        # 关闭事件循环
        loop.close()
        # 删除测试符号
        test_conn.execute("DELETE FROM symbols WHERE file_path = ?", ("/path/to/file",))
        test_conn.commit()


def debug_process_source_file(file_path: Path, project_dir: Path):
    """调试版本的源代码处理函数，直接打印符号信息而不写入数据库"""
    try:
        # 解析代码文件并构建符号表
        parser, query = ParserLoader().get_parser(str(file_path))
        tree, code = parse_code_file(file_path, parser)
        matches = query.matches(tree.root_node)
        symbols = process_matches(matches, code)

        # 获取完整文件路径（规范化处理）
        full_path = str((project_dir / file_path).resolve().absolute())

        print(f"\n处理文件: {full_path}")
        print("=" * 50)

        for symbol_name, symbol_info in symbols.items():
            if not symbol_info.get("body"):
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


def parse_source_file(file_path: Path, parser, query):
    """解析源代码文件并返回符号表"""
    tree, code = parse_code_file(file_path, parser)
    matches = query.matches(tree.root_node)
    return process_matches(matches, code)


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
        if not symbol_info.get("body"):
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
                symbol_info["body"],
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


class TrieNode:
    """前缀树节点"""

    __slots__ = ["children", "is_end", "symbols"]

    def __init__(self):
        self.children = {}  # 字符到子节点的映射
        self.is_end = False  # 是否单词结尾
        self.symbols = []  # 存储符号详细信息（支持同名不同定义的符号）


class SymbolTrie:
    def __init__(self, case_sensitive=False):
        self.root = TrieNode()
        self.case_sensitive = case_sensitive
        self._size = 0  # 记录唯一符号数量

    def _normalize(self, word):
        """统一大小写处理"""
        return word if self.case_sensitive else word.lower()

    def insert(self, symbol_name, symbol_info):
        """插入符号到前缀树"""
        node = self.root
        word = self._normalize(symbol_name)

        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]

        # 避免重复添加相同定义的符号
        if not any(s["full_definition_hash"] == symbol_info["full_definition_hash"] for s in node.symbols):
            node.symbols.append(symbol_info)
            if not node.is_end:  # 新增唯一符号计数
                self._size += 1
            node.is_end = True

    def search_prefix(self, prefix):
        """前缀搜索"""
        node = self.root
        prefix = self._normalize(prefix)

        # 定位到前缀末尾节点
        for char in prefix:
            if char not in node.children:
                return []
            node = node.children[char]

        # 收集所有子节点符号
        results = []
        self._dfs_collect(node, prefix, results)
        return results

    def _dfs_collect(self, node, current_prefix, results):
        """深度优先收集符号"""
        if node.is_end:
            for symbol in node.symbols:
                results.append({"name": current_prefix, "details": symbol})

        for char, child in node.children.items():
            self._dfs_collect(child, current_prefix + char, results)

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
    def from_symbols(cls, symbols_dict, case_sensitive=False):
        """从现有符号字典构建前缀树"""
        trie = cls(case_sensitive)
        for symbol_name, entries in symbols_dict.items():
            for entry in entries:
                trie.insert(
                    symbol_name, {"file_path": entry[0], "signature": entry[1], "full_definition_hash": entry[2]}
                )
        return trie


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


def parse_worker_wrapper(file_path):
    """工作进程的包装函数"""
    try:
        start_time = time.time() * 1000
        parser1, query = ParserLoader().get_parser(str(file_path))
        symbols = parse_source_file(file_path, parser1, query)
        parse_time = time.time() * 1000 - start_time
        print(f"文件 {file_path} 解析完成，耗时 {parse_time:.2f} 毫秒")
        return (file_path, symbols)
    except Exception as e:
        print(f"解析失败 {file_path}: {str(e)}")
        return None, None


def check_file_needs_processing(conn: sqlite3.Connection, full_path: str) -> bool:
    """快速检查文件是否需要处理"""
    start_time = time.time() * 1000
    cursor = conn.cursor()
    cursor.execute("SELECT file_hash, last_modified FROM file_metadata WHERE file_path = ?", (full_path,))
    file_metadata = cursor.fetchone()

    if file_metadata:
        file_hash = calculate_file_hash(Path(full_path))
        last_modified = Path(full_path).stat().st_mtime
        if file_metadata[0] == file_hash and file_metadata[1] == last_modified:
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
    from difflib import unified_diff

    diff = unified_diff(t.splitlines(), t2.splitlines(), fromfile="数据库中的定义", tofile="内存中的定义", lineterm="")
    print("符号定义差异对比：")
    for line in diff:
        print(line)
    import pdb

    pdb.set_trace()


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
    project_paths: List[str], conn: sqlite3.Connection, include_suffixes: List[str] = None
):
    """优化后的项目文件扫描"""
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

    # 获取需要处理的文件列表
    tasks = []
    for project_path in project_paths:
        project_dir = Path(project_path)
        if not project_dir.exists():
            print(f"警告：项目路径 {project_path} 不存在，跳过处理")
            continue

        for file_path in project_dir.rglob("*"):
            if file_path.suffix.lower() not in suffixes:
                continue

            full_path = str((project_dir / file_path).resolve().absolute())
            need_process = check_file_needs_processing(conn, full_path)
            if need_process:
                tasks.append(file_path)

    # 使用多进程池处理解析任务
    with Pool(processes=os.cpu_count()) as pool:
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


def build_index(project_paths: List[str] = ["."], include_suffixes: List[str] = None, db_path: str = "symbols.db"):
    """构建符号索引"""
    # 初始化数据库连接
    conn = init_symbol_database(db_path)

    try:
        # 扫描并处理项目文件
        scan_project_files_optimized(project_paths, conn, include_suffixes)
        print("符号索引构建完成")
    finally:
        # 关闭数据库连接
        conn.close()


def main(
    host: str = "127.0.0.1",
    port: int = 8000,
    project_paths: List[str] = ["."],
    include_suffixes: List[str] = None,
    db_path: str = "symbols.db",
):
    """启动FastAPI服务
    Args:
        host: 服务器地址
        port: 服务器端口
        project_paths: 项目路径列表
        include_suffixes: 要包含的文件后缀列表
        db_path: 符号数据库文件路径，默认为当前目录下的symbols.db
    """
    # 初始化数据库连接
    build_index(project_paths, include_suffixes, db_path)
    # 启动FastAPI服务
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="代码分析工具")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="HTTP服务器绑定地址")
    parser.add_argument("--port", type=int, default=8000, help="HTTP服务器绑定端口")
    parser.add_argument("--project", type=str, nargs="+", default=["."], help="项目根目录路径（可指定多个）")
    parser.add_argument("--demo", action="store_true", help="运行演示模式")
    parser.add_argument("--include", type=str, nargs="+", help="要包含的文件后缀列表（可指定多个，如 .c .h）")
    parser.add_argument("--debug-file", type=str, help="单文件调试模式，指定要调试的文件路径")
    parser.add_argument("--format-dir", type=str, help="指定要格式化的目录路径")
    parser.add_argument("--build-index", action="store_true", help="构建符号索引")
    parser.add_argument("--db-path", type=str, default="symbols.db", help="符号数据库文件路径")

    args = parser.parse_args()

    if args.demo:
        demo_main()
        test_symbols_api()
    elif args.debug_file:
        debug_process_source_file(Path(args.debug_file), Path(args.project[0]))
    elif args.format_dir:
        format_c_code_in_directory(Path(args.format_dir))
    elif args.build_index:
        build_index(project_paths=args.project, include_suffixes=args.include, db_path=args.db_path)
    else:
        main(
            host=args.host,
            port=args.port,
            project_paths=args.project,
            include_suffixes=args.include,
            db_path=args.db_path,
        )
