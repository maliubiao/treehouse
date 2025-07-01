import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 将项目根目录添加到 sys.path，以便能够导入 tools 包中的模块
# 这种方式比相对导入更健壮，因为它不依赖于当前工作目录
# __file__ -> /Users/richard/code/terminal-llm/tests/test_replace_engine.py
# Path(__file__).parent -> /Users/richard/code/terminal-llm/tests
# Path(__file__).parent.parent -> /Users/richard/code/terminal-llm
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.replace_engine import LLMInstructionParser, ReplaceEngine


class TestReplaceEngineAndParser(unittest.TestCase):
    """
    为 ReplaceEngine 和 LLMInstructionParser 提供全面的单元测试。
    """

    def setUp(self):
        """
        在每个测试方法运行前执行。
        - 创建一个临时的测试目录。
        - 初始化 ReplaceEngine 实例。
        """
        # 使用 tempfile 模块创建安全的临时目录
        self.test_dir = Path(tempfile.mkdtemp(prefix="engine_tests_"))
        self.engine = ReplaceEngine()

    def tearDown(self):
        """
        在每个测试方法运行后执行。
        - 递归删除临时测试目录及其所有内容。
        """
        shutil.rmtree(self.test_dir)

    def _prepare_file(self, relative_path, content):
        """
        在测试目录中准备一个文件。
        - 支持创建子目录。
        """
        full_path = self.test_dir / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return str(full_path)

    def _read_file(self, relative_path):
        """读取测试目录中文件的内容。"""
        full_path = self.test_dir / relative_path
        if not full_path.exists():
            return None
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_create_new_file(self):
        """测试 'created_file' 指令，验证新文件是否正确创建。"""
        file_path = self.test_dir / "file1.txt"
        instructions_text = f"[created file]: {file_path}\n[start]\nHello, new world!\n[end]"

        instructions = LLMInstructionParser.parse(instructions_text)
        self.engine.execute(instructions)

        self.assertTrue(file_path.exists())
        self.assertEqual(self._read_file("file1.txt"), "Hello, new world!")

    def test_overwrite_whole_file(self):
        """测试 'overwrite_whole_file' 指令，验证文件内容是否被完全覆盖。"""
        file_path_str = self._prepare_file("file1.txt", "Old content.")
        instructions_text = f"[overwrite whole file]: {file_path_str}\n[start]\nNew content.\n[end]"

        instructions = LLMInstructionParser.parse(instructions_text)
        self.engine.execute(instructions)

        self.assertEqual(self._read_file("file1.txt"), "New content.")

    def test_basic_string_replacement(self):
        """测试 'replace' 指令，验证简单的字符串替换是否成功。"""
        file_path_str = self._prepare_file("file1.txt", "This is old content.")
        instructions_text = f"[replace]: {file_path_str}\n[start]\nold\n[end]\n[start]\nnew\n[end]"

        instructions = LLMInstructionParser.parse(instructions_text)
        self.engine.execute(instructions)

        self.assertEqual(self._read_file("file1.txt"), "This is new content.")

    def test_line_range_replacement(self):
        """测试 'replace_lines' 指令，验证指定行范围的替换。"""
        file_content = "Line 1\nLine 2\nLine 3\nLine 4\n"
        file_path_str = self._prepare_file("file1.txt", file_content)
        instructions_text = f"[replace]: {file_path_str}\n[lines]: 2-3\n[start]Line 2\nLine 3\n[end]\n[start]New Line 2\nNew Line 3\n[end]"

        instructions = LLMInstructionParser.parse(instructions_text)
        self.engine.execute(instructions)

        expected_content = "Line 1\nNew Line 2\nNew Line 3\n\nLine 4\n"
        self.assertEqual(self._read_file("file1.txt"), expected_content)

    def test_insert_content(self):
        """测试 'insert' 指令，验证内容是否在指定行号插入。"""
        file_path_str = self._prepare_file("file1.txt", "Line 1\nLine 2\n")
        instructions_text = f"[insert]: {file_path_str}\n[line]: 1\n[start]\nInserted Line\n[end]"

        instructions = LLMInstructionParser.parse(instructions_text)
        self.engine.execute(instructions)

        # 插入发生在第1行之后 (即索引为1的位置)
        expected_content = "Line 1\nInserted Line\n\nLine 2\n"
        self.assertEqual(self._read_file("file1.txt"), expected_content)

    def test_fail_on_multiple_matches_for_replace(self):
        """测试 'replace' 在找到多个匹配项时是否按预期失败。"""
        file_path_str = self._prepare_file("file1.txt", "fail fail")
        instructions_text = f"[replace]: {file_path_str}\n[start]\nfail\n[end]\n[start]\npass\n[end]"

        instructions = LLMInstructionParser.parse(instructions_text)
        with self.assertRaises(RuntimeError) as cm:
            self.engine.execute(instructions)

        self.assertIn("找到 2 个匹配项", str(cm.exception))

    def test_fail_on_source_mismatch_for_line_replace(self):
        """测试 'replace_lines' 在源内容不匹配时是否按预期失败。"""
        file_path_str = self._prepare_file("file1.txt", "Correct source\n")
        instructions_text = (
            f"[replace]: {file_path_str}\n[lines]: 1-1\n[start]\nWrong source\n[end]\n[start]\n...\n[end]"
        )

        instructions = LLMInstructionParser.parse(instructions_text)
        with self.assertRaises(RuntimeError) as cm:
            self.engine.execute(instructions)

        self.assertIn("源字符串与文件指定行范围的内容不匹配", str(cm.exception))

    def test_randomized_tag_restoration(self):
        """测试随机化标签 [start.XX] 是否能被正确还原为 [start]。"""
        file_path_str = self._prepare_file("file1.txt", "Initial")
        # 模拟LLM可能生成的、包含随机化标签的指令
        instructions_text = (
            f"[overwrite whole file]: {file_path_str}\n[start]\nThis has [start.12] and [end.99] tags.\n[end]"
        )

        instructions = LLMInstructionParser.parse(instructions_text)
        self.engine.execute(instructions)

        self.assertEqual(self._read_file("file1.txt"), "This has [start] and [end] tags.")

    def test_create_file_in_new_subdirectory(self):
        """测试 'created_file' 是否能自动创建尚不存在的父目录。"""
        file_path = self.test_dir / "new_dir" / "file.txt"
        instructions_text = f"[created file]: {file_path}\n[start]\nSubdir content\n[end]"

        instructions = LLMInstructionParser.parse(instructions_text)
        self.engine.execute(instructions)

        self.assertTrue(file_path.exists())
        self.assertEqual(self._read_file("new_dir/file.txt"), "Subdir content")

    def test_parser_with_all_instruction_types(self):
        """测试 LLMInstructionParser 是否能一次性解析所有类型的指令。"""
        text = """
[project setup script]
[start]
echo "setup"
[end]
[created file]: /tmp/a.txt
[start]
content_a
[end]
[overwrite whole file]: /tmp/b.txt
[start]
content_b
[end]
[replace]: /tmp/c.txt
[lines]: 5-10
[start]
src_c
[end]
[start]
dst_c
[end]
[insert]: /tmp/d.txt
[line]: 15
[start]
content_d
[end]
"""
        instructions = LLMInstructionParser.parse(text)
        self.assertEqual(len(instructions), 5)

        self.assertEqual(instructions[0]["type"], "project_setup_script")
        self.assertEqual(instructions[0]["content"], 'echo "setup"')

        self.assertEqual(instructions[1]["type"], "created_file")
        self.assertEqual(instructions[1]["path"], "/tmp/a.txt")
        self.assertEqual(instructions[1]["content"], "content_a")

        self.assertEqual(instructions[2]["type"], "overwrite_whole_file")
        self.assertEqual(instructions[2]["path"], "/tmp/b.txt")
        self.assertEqual(instructions[2]["content"], "content_b")

        self.assertEqual(instructions[3]["type"], "replace_lines")
        self.assertEqual(instructions[3]["path"], "/tmp/c.txt")
        self.assertEqual(instructions[3]["start_line"], 5)
        self.assertEqual(instructions[3]["end_line"], 10)
        self.assertEqual(instructions[3]["src"], "src_c")
        self.assertEqual(instructions[3]["dst"], "dst_c")

        self.assertEqual(instructions[4]["type"], "insert")
        self.assertEqual(instructions[4]["path"], "/tmp/d.txt")
        self.assertEqual(instructions[4]["line_num"], 15)
        self.assertEqual(instructions[4]["content"], "content_d")


if __name__ == "__main__":
    unittest.main(verbosity=2)
