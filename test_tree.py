import os
import tempfile
import unittest
from textwrap import dedent

from fastapi.testclient import TestClient

# Import the implemented classes
from tree import BlockPatch, ParserLoader, ParserUtil, SourceSkeleton, SymbolTrie, app


class TestSourceFrameworkParser(unittest.TestCase):
    def setUp(self):
        self.parser_loader = ParserLoader()
        self.parser = SourceSkeleton(self.parser_loader)

    def create_temp_file(self, code: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write(code)
            return f.name

    def test_class_with_decorated_method(self):
        code = dedent(
            """
        class MyClass:
            @decorator1
            @decorator2
            def my_method(self):
                \"\"\"Method docstring\"\"\"
                a = 1
                b = 2
                return a + b
        """
        )
        expected = dedent(
            """
        # Auto-generated code skeleton

        class MyClass:
            @decorator1
            @decorator2
            def my_method(self):
                \"\"\"Method docstring\"\"\"
                pass  # Placeholder
        """
        ).strip()

        path = self.create_temp_file(code)
        result = self.parser.generate_framework(path).strip()
        os.unlink(path)

        self.assertEqual(result, expected)

    def test_module_level_elements(self):
        code = dedent(
            """
        \"\"\"Module docstring\"\"\"

        import os
        from sys import path

        VALUE = 100

        @class_decorator
        class MyClass:
            pass
        """
        )
        expected = dedent(
            """
        # Auto-generated code skeleton

        \"\"\"Module docstring\"\"\"
        import os
        from sys import path
        VALUE = 100
        @class_decorator
        class MyClass:
            pass  # Placeholder
        """
        ).strip()

        path = self.create_temp_file(code)
        result = self.parser.generate_framework(path).strip()
        os.unlink(path)

        self.assertEqual(result, expected)


class TestBlockPatch(unittest.TestCase):
    def setUp(self):
        self.temp_files = []

    def tearDown(self):
        for file in self.temp_files:
            if os.path.exists(file):
                os.unlink(file)

    def create_temp_file(self, code: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write(code)
            self.temp_files.append(f.name)
            return f.name

    def _find_byte_range(self, content: bytes, target: bytes) -> tuple[int, int]:
        """通过字符串查找确定字节范围"""
        start = content.find(target)
        if start == -1:
            raise ValueError(f"未找到目标字符串: {target}")
        return (start, start + len(target))

    def test_basic_patch(self):
        code = dedent(
            """
            def foo():
                return 1

            def bar():
                return 2
            """
        )
        file_path = self.create_temp_file(code)

        # 通过字符串查找确定字节范围
        with open(file_path, "rb") as f:
            content = f.read()
            patch_range = self._find_byte_range(content, b"return 1")

        # 测试基本补丁功能
        patch = BlockPatch(
            file_paths=[file_path],
            patch_ranges=[patch_range],  # return 1
            block_contents=[b"return 1"],
            update_contents=[b"return 10"],
        )

        # 验证差异生成
        diff = patch.generate_diff()
        self.assertIn("-    return 1", diff)
        self.assertIn("+    return 10", diff)

        # 验证补丁应用
        patched_files = patch.apply_patch()
        self.assertIn(file_path, patched_files)
        self.assertIn(b"return 10", patched_files[file_path])

    def test_multiple_patches(self):
        code = dedent(
            """
            def foo():
                return 1

            def bar():
                return 2
            """
        )
        file_path = self.create_temp_file(code)

        # 通过字符串查找确定字节范围
        with open(file_path, "rb") as f:
            content = f.read()
            patch_range1 = self._find_byte_range(content, b"return 1")
            patch_range2 = self._find_byte_range(content, b"return 2")

        # 测试多个补丁
        patch = BlockPatch(
            file_paths=[file_path, file_path],
            patch_ranges=[patch_range1, patch_range2],  # return 1, return 2
            block_contents=[b"return 1", b"return 2"],
            update_contents=[b"return 10", b"return 20"],
        )

        # 验证差异生成
        diff = patch.generate_diff()
        self.assertIn("-    return 1", diff)
        self.assertIn("+    return 10", diff)
        self.assertIn("-    return 2", diff)
        self.assertIn("+    return 20", diff)

        # 验证补丁应用
        patched_files = patch.apply_patch()
        self.assertIn(file_path, patched_files)
        self.assertIn(b"return 10", patched_files[file_path])
        self.assertIn(b"return 20", patched_files[file_path])

    def test_invalid_patch(self):
        code = dedent(
            """
            def foo():
                return 1
            """
        )
        file_path = self.create_temp_file(code)

        # 通过字符串查找确定字节范围
        with open(file_path, "rb") as f:
            content = f.read()
            patch_range = self._find_byte_range(content, b"return 1")

        # 测试无效补丁（内容不匹配）
        patch = BlockPatch(
            file_paths=[file_path],
            patch_ranges=[patch_range],  # return 1
            block_contents=[b"return 2"],  # 错误的内容
            update_contents=[b"return 10"],
        )
        with self.assertRaises(ValueError):
            patch.generate_diff()

        # 测试无效补丁（范围重叠）
        patch = BlockPatch(
            file_paths=[file_path, file_path],
            patch_ranges=[(patch_range[0], patch_range[1] - 2), (patch_range[0] + 2, patch_range[1])],  # 重叠范围
            block_contents=[b"return 1", b"return 1"],
            update_contents=[b"return 10", b"return 10"],
        )
        with self.assertRaises(ValueError):
            patch.generate_diff()

    def test_no_changes(self):
        code = dedent(
            """
            def foo():
                return 1
            """
        )
        file_path = self.create_temp_file(code)

        # 通过字符串查找确定字节范围
        with open(file_path, "rb") as f:
            content = f.read()
            patch_range = self._find_byte_range(content, b"return 1")

        # 测试没有实际变化的补丁
        patch = BlockPatch(
            file_paths=[file_path],
            patch_ranges=[patch_range],  # return 1
            block_contents=[b"return 1"],
            update_contents=[b"return 1"],  # 内容相同
        )

        # 验证差异为空
        self.assertEqual(patch.generate_diff(), "")

        # 验证补丁应用结果为空
        self.assertEqual(patch.apply_patch(), {})

    def test_multiple_files(self):
        code1 = dedent(
            """
            def foo():
                return 1
            """
        )
        code2 = dedent(
            """
            def bar():
                return 2
            """
        )
        file1 = self.create_temp_file(code1)
        file2 = self.create_temp_file(code2)

        # 通过字符串查找确定字节范围
        with open(file1, "rb") as f:
            content = f.read()
            patch_range1 = self._find_byte_range(content, b"return 1")

        with open(file2, "rb") as f:
            content = f.read()
            patch_range2 = self._find_byte_range(content, b"return 2")

        # 测试多文件补丁
        patch = BlockPatch(
            file_paths=[file1, file2],
            patch_ranges=[patch_range1, patch_range2],  # return 1, return 2
            block_contents=[b"return 1", b"return 2"],
            update_contents=[b"return 10", b"return 20"],
        )

        # 验证差异生成
        diff = patch.generate_diff()
        self.assertIn("-    return 1", diff)
        self.assertIn("+    return 10", diff)
        self.assertIn("-    return 2", diff)
        self.assertIn("+    return 20", diff)

        # 验证补丁应用
        patched_files = patch.apply_patch()
        self.assertIn(file1, patched_files)
        self.assertIn(file2, patched_files)
        self.assertIn(b"return 10", patched_files[file1])
        self.assertIn(b"return 20", patched_files[file2])

    def test_insert_patch(self):
        code = dedent(
            """
            def foo():
                return 1
            """
        )
        file_path = self.create_temp_file(code)

        # 通过字符串查找确定插入位置
        with open(file_path, "rb") as f:
            content = f.read()
            insert_pos = content.find(b"return 1")

        # 测试插入补丁
        patch = BlockPatch(
            file_paths=[file_path],
            patch_ranges=[(insert_pos, insert_pos)],  # 插入位置
            block_contents=[b""],  # 空内容
            update_contents=[b"print('inserted')\n    "],  # 插入内容
        )

        # 验证差异生成
        diff = patch.generate_diff()
        self.assertIn("+    print('inserted')", diff)

        # 验证补丁应用
        patched_files = patch.apply_patch()
        self.assertIn(file_path, patched_files)
        self.assertIn(b"print('inserted')", patched_files[file_path])
        self.assertIn(b"return 1", patched_files[file_path])  # 原有内容保持不变


class TestParserUtil(unittest.TestCase):
    def setUp(self):
        self.parser_loader = ParserLoader()
        self.parser_util = ParserUtil(self.parser_loader)

    def create_temp_file(self, code: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
            f.write(code)
            return f.name

    def test_get_symbol_paths(self):
        code = dedent(
            """
            class MyClass:
                def my_method(self):
                    pass
            """
        )
        path = self.create_temp_file(code)
        paths, code_map = self.parser_util.get_symbol_paths(path)
        os.unlink(path)

        expected_paths = ["MyClass", "MyClass.my_method"]
        self.assertEqual(sorted(paths), sorted(expected_paths))

        for path_key in expected_paths:
            self.assertIn(path_key, code_map)
            self.assertIn("code", code_map[path_key])
            self.assertIn("block_range", code_map[path_key])
            self.assertIn("start_line", code_map[path_key])
            self.assertIn("end_line", code_map[path_key])

    def test_main_block_detection(self):
        code = dedent(
            """
            if __name__ == "__main__":
                print("Hello World")
            """
        )
        path = self.create_temp_file(code)
        paths, code_map = self.parser_util.get_symbol_paths(path)
        os.unlink(path)

        self.assertIn("__main__", paths)
        self.assertIn("__main__", code_map)
        self.assertIn("code", code_map["__main__"])
        self.assertEqual(code_map["__main__"]["code"].strip(), 'if __name__ == "__main__":\n    print("Hello World")')

    def test_import_block_detection(self):
        code = dedent(
            """
            # This is a comment
            import os
            import sys
            """
        )
        path = self.create_temp_file(code)
        paths, code_map = self.parser_util.get_symbol_paths(path)
        os.unlink(path)

        self.assertIn("__import__", paths)
        self.assertIn("__import__", code_map)
        self.assertIn("code", code_map["__import__"])
        self.assertEqual(code_map["__import__"]["code"].strip(), "# This is a comment\nimport os\nimport sys")

    def test_import_block_with_strings_and_from_import(self):
        """测试包含字符串字面量、注释和多种导入语句的头部块"""
        code = dedent(
            """
            # 模块注释
            "文档字符串"
            """
            """\n            aaa\n            bbb\n            """
            """
            import os
            from sys import version
            import sys as sys1
        """
        )
        path = self.create_temp_file(code)
        paths, code_map = self.parser_util.get_symbol_paths(path)
        os.unlink(path)

        self.assertIn("__import__", paths)
        import_entry = code_map["__import__"]
        self.assertIn("# 模块注释", import_entry["code"])
        self.assertIn('"文档字符串"', import_entry["code"])
        self.assertIn("aaa\nbbb", import_entry["code"])
        self.assertIn("import os", import_entry["code"])
        self.assertIn("from sys import version", import_entry["code"])
        self.assertIn("import sys as sys1", import_entry["code"])


class TestSymbolsComplete(unittest.TestCase):
    """
    symbol:a.c/main,d 可补全symbol:a.c/main,debug
    symbol:a.c/m 可补全symbol:a.c/main
    symbol:a.c/main,debug,pr 可补全symbol:a.c/main,debug,print
    symbol:a.c/symbol_a,symbol_ 可补全symbol:a.c/symbol_a,symbol_b
    symbol:multi/level,path,test_ 可补全symbol:multi/level,path,test_case
    """

    def setUp(self):
        """初始化测试环境"""
        # 初始化测试数据
        symbols_dict = {
            "symbol:a.c/debug": [("/a.c", "debug()", "debug_hash")],
            "symbol:a.c/main": [("/a.c", "main()", "main_hash")],
            "symbol:a.c/print": [("/a.c", "print()", "print_hash")],
            "symbol:a.c/symbol_a": [("/a.c", "symbol_a", "symbol_b_hash")],
            "symbol:a.c/symbol_b": [("/a.c", "symbol_b", "symbol_b_hash")],
        }
        app.state.file_symbol_trie = SymbolTrie.from_symbols(symbols_dict)
        app.state.symbol_trie = SymbolTrie.from_symbols({})
        app.state.file_mtime_cache = {}

    def test_complete_debug_from_main_d(self):
        prefix = "symbol:a.c/main,d"
        expected = "symbol:a.c/main,debug"
        results = self._get_completions(prefix)
        self.assertIn(expected, results)

    def test_complete_main_from_m(self):
        prefix = "symbol:a.c/m"
        expected = "symbol:a.c/main"
        results = self._get_completions(prefix)
        self.assertIn(expected, results)

    def test_complete_print_in_multi_symbol_context(self):
        prefix = "symbol:a.c/main,debug,pr"
        expected = "symbol:a.c/main,debug,print"
        results = self._get_completions(prefix)
        self.assertIn(expected, results)

    def test_complete_symbol_b_after_symbol_a(self):
        prefix = "symbol:a.c/symbol_a,symbol_"
        expected = "symbol:a.c/symbol_a,symbol_b"
        results = self._get_completions(prefix)
        self.assertIn(expected, results)

    # 新增get_symbol_content测试用例
    def test_get_valid_symbol_content(self):
        """测试正常获取符号内容"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".c", delete=False) as tmp:
            tmp.write("void main() {\n  // main function\n}\n")
            tmp.flush()
            tmp.seek(0)

            # 更新符号位置信息
            app.state.file_symbol_trie.insert(
                "symbol:a.c/main",
                {
                    "file_path": tmp.name,
                    "location": ((1, 0), (3, 1), (0, len(tmp.read()))),
                },
            )

            test_client = TestClient(app)
            response = test_client.get(f"/symbol_content?symbol_path=symbol:a.c/main")
            self.assertEqual(response.status_code, 200)
            self.assertIn("void main()", response.text)

    def test_get_multiple_symbols_content(self):
        """测试获取多个符号内容"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".c", delete=False) as tmp:
            tmp.write("void main() {}\nvoid debug() {}\n")
            tmp.flush()

            # 插入两个符号的位置信息
            app.state.file_symbol_trie.insert(
                "symbol:a.c/main",
                {
                    "file_path": tmp.name,
                    "location": ((1, 0), (1, 13), (0, 13)),
                },
            )
            app.state.file_symbol_trie.insert(
                "symbol:a.c/debug",
                {
                    "file_path": tmp.name,
                    "location": ((2, 0), (2, 14), (14, 28)),
                },
            )

            test_client = TestClient(app)
            response = test_client.get("/symbol_content?symbol_path=symbol:a.c/main,debug")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text.count("\n\n"), 1)
            self.assertIn("void main()", response.text)
            self.assertIn("void debug()", response.text)

    def test_json_response_format(self):
        """测试JSON响应格式"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".c", delete=False) as tmp:
            tmp.write("void main() {\n  // test json\n}\n")
            tmp.flush()
            tmp.seek(0)
            # 设置精确的代码块范围
            full_content = tmp.read()
            start = 0
            end = len(full_content)
            app.state.file_symbol_trie.insert(
                "symbol:a.c/main",
                {
                    "file_path": tmp.name,
                    "location": ((1, 0), (3, 1), (start, end)),
                },
            )

            test_client = TestClient(app)
            response = test_client.get("/symbol_content?symbol_path=symbol:a.c/main&json=true")
            self.assertEqual(response.status_code, 200)
            json_data = response.json()
            self.assertEqual(json_data[0]["location"]["start_line"], 1)
            self.assertEqual(json_data[0]["location"]["end_line"], 3)
            self.assertIn("void main()", json_data[0]["content"])

    def test_invalid_symbol_path_format(self):
        """测试无效符号路径格式"""
        test_client = TestClient(app)
        response = test_client.get("/symbol_content?symbol_path=invalidpath")
        self.assertEqual(response.status_code, 400)
        self.assertIn("格式错误", response.text)

    def test_nonexistent_symbol(self):
        """测试不存在的符号"""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".c", delete=False) as tmp:
            tmp.write("void existing_func() {}\n")
            tmp.flush()

            # 确保Trie中没有该符号
            test_client = TestClient(app)
            response = test_client.get("/symbol_content?symbol_path=a.c/nonexist")
            self.assertEqual(response.status_code, 404)
            self.assertIn("未找到符号", response.text)

    def _get_completions(self, prefix: str) -> list:
        # 模拟请求上下文并调用补全接口
        test_client = TestClient(app)
        response = test_client.get(f"/complete_realtime?prefix={prefix}")
        return response.text.splitlines()


if __name__ == "__main__":
    unittest.main()
