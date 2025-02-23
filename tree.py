import asyncio
import importlib
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import requests
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
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

        # 定义查询语句（针对C语言）
        query_source = """
        [
            (declaration
                (storage_class_specifier) @storage_class
                type: _ @return_type
                declarator: (function_declarator
                    declarator: (identifier) @symbol_name
                    parameters: (parameter_list) @params
                )
            ) @func_decl
            (#eq? @storage_class "extern")
            
            (function_definition
                type: _ @return_type
                declarator: (function_declarator
                    declarator: (identifier) @symbol_name
                    parameters: (parameter_list) @params
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
            ) @call
            (#contains? @body @call)
        )
        """
        query = Query(lang, query_source)

        self._parsers[lang_name] = lang_parser
        self._queries[lang_name] = query
        return lang_parser, query


def parse_code_file(file_path, lang_parser):
    """解析代码文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()
    # with open("a.dot", "w+") as f:
    #     parser.print_dot_graphs(f)
    tree = lang_parser.parse(bytes(code, "utf-8"))
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


def init_symbol_database(db_path: str = "symbols.db"):
    """初始化符号数据库"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
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
            calls TEXT
        )
    """
    )
    conn.commit()
    return conn


def insert_symbol(conn, symbol_info: Dict):
    """插入符号信息到数据库"""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO symbols (name, file_path, type, signature, body, full_definition, calls)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            symbol_info["name"],
            symbol_info["file_path"],
            symbol_info["type"],
            symbol_info["signature"],
            symbol_info["body"],
            symbol_info["full_definition"],
            json.dumps(symbol_info.get("calls", [])),
        ),
    )
    conn.commit()


def search_symbols(conn, prefix: str, limit: int = 10) -> List[Dict]:
    """根据前缀搜索符号"""
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


def get_symbol_info(conn, symbol_name: str) -> Optional[SymbolInfo]:
    """获取符号的完整信息"""
    cursor = conn.cursor()
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
async def search_symbols_api(prefix: str, limit: int = 10):
    """符号搜索API
    Args:
        prefix: 搜索前缀，至少1个字符
        limit: 返回结果数量限制，默认10
    """
    conn = get_db_connection()
    if len(prefix) < 1:
        return {"error": "Prefix must be at least 1 character"}
    results = search_symbols(conn, prefix, limit)
    return {"results": results}


@app.get("/symbols/{symbol_name}")
async def get_symbol_info_api(symbol_name: str):
    """获取符号信息API"""
    conn = get_db_connection()
    symbol_info = get_symbol_info(conn, symbol_name)
    if symbol_info:
        return symbol_info
    return {"error": "Symbol not found"}


def test_fastapi_endpoints():
    """测试FastAPI提供的两个外部接口"""

    # 使用全局数据库连接
    test_conn = get_db_connection()

    # 准备测试数据
    test_symbols = [
        {
            "name": "test_function",
            "file_path": "/path/to/file",
            "type": "function",
            "signature": "def test_function()",
            "body": "pass",
            "full_definition": "def test_function(): pass",
            "calls": [],
        },
        {
            "name": "another_function",
            "file_path": "/another/path",
            "type": "function",
            "signature": "def another_function()",
            "body": "pass",
            "full_definition": "def another_function(): pass",
            "calls": [],
        },
        {
            "name": "test_variable",
            "file_path": "/path/to/file",
            "type": "variable",
            "signature": "test_variable = 1",
            "body": "",
            "full_definition": "test_variable = 1",
            "calls": [],
        },
    ]

    # 插入测试数据
    for symbol in test_symbols:
        insert_symbol(test_conn, symbol)

    # 设置请求超时时间
    timeout = (5, 5)  # 连接超时和读取超时均为5秒

    # 测试搜索接口
    # 情况1：正常搜索，有多个结果
    response = requests.get("http://localhost:8000/symbols/search?prefix=test&limit=10", timeout=timeout)
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 2  # 应该匹配到test_function和test_variable
    assert any(result["name"] == "test_function" for result in data["results"])
    assert any(result["name"] == "test_variable" for result in data["results"])

    # 情况2：搜索无结果
    response = requests.get("http://localhost:8000/symbols/search?prefix=nonexistent&limit=10", timeout=timeout)
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 0

    # 情况3：搜索限制结果数量
    response = requests.get("http://localhost:8000/symbols/search?prefix=test&limit=1", timeout=timeout)
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1

    # 测试获取符号信息接口
    # 情况1：正常获取符号信息
    response = requests.get("http://localhost:8000/symbols/test_function", timeout=timeout)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_function"
    assert data["type"] == "function"
    assert data["signature"] == "def test_function()"

    # 情况2：获取不存在的符号信息
    response = requests.get("http://localhost:8000/symbols/nonexistent", timeout=timeout)
    assert response.status_code == 200
    data = response.json()
    assert data == {"error": "Symbol not found"}

    # 清理测试数据
    test_conn.execute("DELETE FROM symbols")
    test_conn.commit()


def test_symbols_api():
    """测试符号相关API"""
    # 使用全局数据库连接
    test_conn = get_db_connection()

    # 准备测试数据
    test_symbol = {
        "name": "test_function",
        "file_path": "/path/to/file",
        "type": "function",
        "signature": "def test_function()",
        "body": "pass",
        "full_definition": "def test_function(): pass",
        "calls": [],
    }
    insert_symbol(test_conn, test_symbol)

    # 创建新的事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # 测试搜索接口
        # 正常情况
        response = loop.run_until_complete(search_symbols_api("test", 10))
        assert len(response["results"]) == 1
        assert response["results"][0]["name"] == "test_function"

        # 测试无结果情况
        response = loop.run_until_complete(search_symbols_api("nonexistent", 10))
        assert len(response["results"]) == 0

        # 测试获取符号信息接口
        # 正常情况
        response = loop.run_until_complete(get_symbol_info_api("test_function"))
        assert response.name == "test_function"
        assert response.type == "function"

        # 测试符号不存在情况
        response = loop.run_until_complete(get_symbol_info_api("nonexistent"))
        assert response == {"error": "Symbol not found"}

    finally:
        # 关闭事件循环
        loop.close()
        # 删除测试符号
        test_conn.execute("DELETE FROM symbols WHERE name = ?", ("test_function",))
        test_conn.commit()


def process_source_file(file_path: Path, project_dir: Path, conn: sqlite3.Connection):
    """处理单个源代码文件，提取符号并插入数据库"""
    # 解析代码文件并构建符号表
    parser, query = ParserLoader().get_parser(str(file_path))
    tree, code = parse_code_file(file_path, parser)
    matches = query.matches(tree.root_node)
    symbols = process_matches(matches, code)

    # 将符号信息插入数据库
    for file_path, symbol_dict in symbols.items():
        # 获取完整文件路径
        full_path = str(project_dir / file_path)

        # 准备批量插入数据
        insert_data = []
        for symbol_name, symbol_info in symbol_dict.items():
            insert_data.append(
                (
                    symbol_name,
                    full_path,
                    symbol_info["type"],
                    symbol_info["signature"],
                    symbol_info["body"],
                    symbol_info["full_definition"],
                    json.dumps(symbol_info["calls"]),
                )
            )

        # 批量插入数据库
        if insert_data:
            conn.executemany("INSERT OR REPLACE INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?)", insert_data)
            conn.commit()


def scan_project_files(project_path: str, conn: sqlite3.Connection, include_suffixes: List[str] = None):
    """扫描项目路径下的所有源代码文件并处理
    Args:
        project_path: 项目路径
        conn: 数据库连接
        include_suffixes: 要包含的文件后缀列表，如果为None则包含所有支持的后缀
    """
    project_dir = Path(project_path)
    # 如果没有指定包含的后缀，则使用所有支持的后缀
    suffixes = include_suffixes if include_suffixes else SUPPORTED_LANGUAGES.keys()

    for suffix in suffixes:
        # 确保后缀以点开头
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        for file_path in project_dir.rglob(f"*{suffix}"):
            process_source_file(file_path, project_dir, conn)


def main(host: str = "127.0.0.1", port: int = 8000, project_path: str = ".", include_suffixes: List[str] = None):
    """启动FastAPI服务并初始化符号表
    Args:
        host: 服务器地址
        port: 服务器端口
        project_path: 项目路径
        include_suffixes: 要包含的文件后缀列表
    """
    # 初始化数据库连接
    conn = init_symbol_database()

    try:
        # 扫描并处理项目文件
        scan_project_files(project_path, conn, include_suffixes)

        # 启动FastAPI服务
        uvicorn.run(app, host=host, port=port)
    finally:
        # 关闭数据库连接
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="代码分析工具")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="HTTP服务器绑定地址")
    parser.add_argument("--port", type=int, default=8000, help="HTTP服务器绑定端口")
    parser.add_argument("--project", type=str, default=".", help="项目根目录路径")
    parser.add_argument("--demo", action="store_true", help="运行演示模式")
    parser.add_argument("--include", type=str, nargs="+", help="要包含的文件后缀列表（可指定多个，如 .c .h）")

    args = parser.parse_args()

    if args.demo:
        demo_main()
        test_symbols_api()
        # test_fastapi_endpoints()
    else:
        main(host=args.host, port=args.port, project_path=args.project, include_suffixes=args.include)
