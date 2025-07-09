import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tree import SymbolTrie
from tree_libs.app import WebServiceState, create_app


class TestSymbolContentAPI(unittest.TestCase):
    """
    针对 /symbol_content API 端点的高强度测试套件。
    """

    client: TestClient
    project_root: Path
    app: Any


@classmethod
def setUpClass(cls) -> None:
    """在所有测试开始前，创建测试项目结构和文件。"""
    cls.project_root = Path(tempfile.mkdtemp(prefix="test_api_"))

    # 创建一个用于测试的干净的应用实例
    cls.app = create_app()
    cls.client = TestClient(cls.app)

    # 获取并配置应用状态
    state: WebServiceState = cls.app.state.web_service_state
    state.config.project_root_dir = str(cls.project_root)

    # 创建测试文件结构
    py_content = """def top_level_func():
    print("hello from top_level_func")

class MyClass:
    \"\"\"A simple test class.\"\"\"
    def my_method(self):
        return 1

def another_func():
    pass
"""
    cls.py_file_path = cls.project_root / "test_py.py"
    cls.py_file_path.write_text(py_content, encoding="utf-8")

    c_dir = cls.project_root / "sub"
    c_dir.mkdir()
    c_content = """
#include <stdio.h>

int calculate(int a, int b) {
    return a + b;
}
"""
    cls.c_file_path = c_dir / "test_c.c"
    cls.c_file_path.write_text(c_content, encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        """在所有测试结束后，清理临时目录。"""
        shutil.rmtree(cls.project_root)

    def setUp(self) -> None:
        """在每个测试之前，重置应用状态并设置工作目录。"""
        import os

        self.old_cwd = os.getcwd()
        os.chdir(self.project_root)

        state: WebServiceState = self.client.app.state.web_service_state
        state.file_symbol_trie = SymbolTrie(case_sensitive=True)
        state.file_parser_info_cache = {}
        state.symbol_cache = {}

        # 解析测试文件并插入符号
        self._parse_and_insert_symbols(state, self.py_file_path)
        self._parse_and_insert_symbols(state, self.c_file_path)

    def tearDown(self) -> None:
        """恢复原始工作目录。"""
        import os

        os.chdir(self.old_cwd)

    def _parse_and_insert_symbols(self, state: WebServiceState, file_path: Path):
        """解析文件并将符号插入前缀树"""
        from tree_libs.ast import parse_file

        rel_path = file_path.relative_to(self.project_root).as_posix()
        symbols, code_map = parse_file(str(file_path), self.project_root)
        for symbol in symbols:
            full_symbol_name = f"{rel_path}/{symbol['name']}"
            symbol_info = {
                "file_path": rel_path,
                "signature": symbol.get("signature", ""),
                "full_definition_hash": symbol.get("full_definition_hash", ""),
                "location": symbol.get("location", ((0, 0), (0, 0), (0, 0))),
            }
            state.file_symbol_trie.insert(full_symbol_name, symbol_info)
        state.file_parser_info_cache[rel_path] = code_map

    def test_get_python_function_plaintext(self) -> None:
        """测试：获取单个Python函数的纯文本内容。"""
        rel_path = self.py_file_path.relative_to(self.project_root).as_posix()
        response = self.client.get(f"/symbol_content?symbol_path={rel_path}/top_level_func")
        self.assertEqual(response.status_code, 200)
        self.assertIn('def top_level_func():\n    print("hello from top_level_func")', response.text)

    def test_get_python_class_method_json(self) -> None:
        """测试：以JSON格式获取Python类的方法。"""
        rel_path = self.py_file_path.relative_to(self.project_root).as_posix()
        response = self.client.get(f"/symbol_content?symbol_path={rel_path}/MyClass.my_method&json_format=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        symbol_info = data[0]
        self.assertEqual(symbol_info["name"], f"{rel_path}/MyClass.my_method")
        self.assertEqual(symbol_info["file_path"], str(rel_path))
        self.assertIn("def my_method(self):\n        return 1", symbol_info["content"])
        self.assertIn("location", symbol_info)
        self.assertIn("start_line", symbol_info["location"])

    def test_get_c_function_from_subdirectory(self) -> None:
        """测试：从子目录获取C语言函数。"""
        rel_path = self.c_file_path.relative_to(self.project_root).as_posix()
        response = self.client.get(f"/symbol_content?symbol_path={rel_path}/calculate")
        self.assertEqual(response.status_code, 200)
        self.assertIn("int calculate(int a, int b) {\n    return a + b;\n}", response.text)

    def test_get_multiple_symbols(self) -> None:
        """测试：一次性请求多个符号。"""
        rel_path = self.py_file_path.relative_to(self.project_root).as_posix()
        response = self.client.get(f"/symbol_content?symbol_path={rel_path}/MyClass,another_func")
        self.assertEqual(response.status_code, 200)
        content = response.text
        self.assertIn("class MyClass:", content)
        self.assertIn("def another_func():", content)
        self.assertIn("return 1\n\ndef another_func():\n    pass", content)

    def test_get_symbol_by_line_number(self) -> None:
        """测试：通过行号获取符号 (e.g., at_LINE)。"""
        rel_path = self.py_file_path.relative_to(self.project_root).as_posix()
        # 第4行是 MyClass 的定义
        response = self.client.get(f"/symbol_content?symbol_path={rel_path}/at_4")
        self.assertEqual(response.status_code, 200)
        self.assertIn("class MyClass:", response.text)

    def test_get_near_symbol_by_line_number(self) -> None:
        """测试：通过邻近行号获取符号 (e.g., near_LINE)。"""
        rel_path = self.py_file_path.relative_to(self.project_root).as_posix()
        # 第2行在 top_level_func 内部, near_2 应该找到整个函数
        response = self.client.get(f"/symbol_content?symbol_path={rel_path}/near_2")
        self.assertEqual(response.status_code, 200)
        self.assertIn("def top_level_func():", response.text)

    def test_symbol_not_found(self) -> None:
        """测试：请求一个不存在的符号应返回404。"""
        rel_path = self.py_file_path.relative_to(self.project_root).as_posix()
        response = self.client.get(f"/symbol_content?symbol_path={rel_path}/non_existent_func")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Symbol not found", response.text)

    def test_file_not_found(self) -> None:
        """测试：请求一个不存在的文件中的符号应返回404。"""
        response = self.client.get(f"/symbol_content?symbol_path=non_existent.py/some_func")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Symbol not found: some_func", response.text)

    def test_malformed_path_no_slash(self) -> None:
        """测试：格式错误的路径（没有斜杠）应返回400。"""
        response = self.client.get(f"/symbol_content?symbol_path=test_py.py")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Symbol path format is incorrect", response.text)

    def test_malformed_path_no_symbols(self) -> None:
        """测试：路径中没有提供符号应返回400。"""
        rel_path = self.py_file_path.relative_to(self.project_root).as_posix()
        response = self.client.get(f"/symbol_content?symbol_path={rel_path}/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("At least one symbol is required", response.text)

    def test_cache_invalidation_on_file_change(self) -> None:
        """测试：当源文件被修改时，缓存应失效并返回新内容。"""
        rel_path = self.py_file_path.relative_to(self.project_root).as_posix()

        response1 = self.client.get(f"/symbol_content?symbol_path={rel_path}/another_func")
        self.assertEqual(response1.status_code, 200)
        self.assertIn("def another_func():\n    pass", response1.text)

        time.sleep(1.1)

        new_content = self.py_file_path.read_text(encoding="utf-8").replace("pass", "print('updated')")
        self.py_file_path.write_text(new_content, encoding="utf-8")

        # 清除缓存确保重新解析
        state = self.client.app.state.web_service_state
        state.file_parser_info_cache.clear()
        state.symbol_cache.clear()
        self._parse_and_insert_symbols(state, self.py_file_path)

        response2 = self.client.get(f"/symbol_content?symbol_path={rel_path}/another_func")
        self.assertEqual(response2.status_code, 200)
        self.assertNotIn("pass", response2.text)
        self.assertIn("print('updated')", response2.text)
        self.assertNotEqual(response1.text, response2.text)


if __name__ == "__main__":
    unittest.main()
