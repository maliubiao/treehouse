import os
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

# 假设 tests/ 和 tools/ 是项目根目录下的同级目录
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tools"))


# 导入新工具的核心逻辑函数
from tools.re_patch import run_re_patch


class TestRePatchTool(unittest.TestCase):
    def setUp(self):
        """为每个测试设置一个临时的项目环境"""
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmpdir.name)

        # `extract_and_diff_files` 需要一个 shadow 目录来操作
        self.shadow_dir = self.project_root / ".shadowroot"
        self.shadow_dir.mkdir()

        # `llm_query` 模块使用一个全局变量 `shadowroot`
        self.shadow_patch = patch("llm_query.shadowroot", self.shadow_dir)
        self.shadow_patch.start()

        # 保存原始工作目录，以便在测试后恢复
        self.original_cwd = os.getcwd()

        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(self.shadow_patch.stop)
        self.addCleanup(lambda: os.chdir(self.original_cwd))

    def test_re_patch_modify_and_create(self):
        """
        测试工具是否能正确修改现有文件并创建新文件（及其父目录）。
        """
        try:
            # 1. 准备初始状态
            existing_file = self.project_root / "existing1.txt"
            existing_file.write_text("original content", encoding="utf-8")

            new_file_path = self.project_root / "new_dir" / "new_file.txt"
            self.assertFalse(new_file_path.parent.exists())

            # 2. 准备包含指令的响应文本文件
            response_content = dedent("""
    这是一个LLM响应，用于测试。

    [overwrite whole file]: existing1.txt
    [start]
    modified content
    [end]

    [created file]: new_dir/new_file.txt
    [start]
    new file content
    [end]
    """)
            response_file = self.project_root / "response.txt"
            response_file.write_text(response_content, encoding="utf-8")

            # 3. 执行工具的核心逻辑
            # 使用 patch 抑制 stdout 输出，保持测试日志干净
            with patch("sys.stdout"):
                result = run_re_patch(response_file, self.project_root)

            # 4. 验证结果
            self.assertTrue(result, "工具应报告成功执行")

            # 验证文件是否被修改
            self.assertEqual(existing_file.read_text(encoding="utf-8"), "modified content")

            # 验证新目录和新文件是否被创建
            self.assertTrue(new_file_path.parent.is_dir())
            self.assertTrue(new_file_path.is_file())
            self.assertEqual(new_file_path.read_text(encoding="utf-8"), "new file content")
        finally:
            os.remove(str(existing_file))

    def test_re_patch_with_project_setup_script(self):
        """
        测试工具如何处理 [project setup script] 指令。
        """
        # 1. 准备包含设置脚本的响应文件
        response_content = """
[project setup script]
[start.57]
#!/bin/bash
echo "Setup script generated"
[end.57]
"""
        response_file = self.project_root / "response_with_script.txt"
        response_file.write_text(response_content, encoding="utf-8")

        # 2. 执行工具
        with patch("sys.stdout"):
            result = run_re_patch(response_file, self.project_root)

        # 3. 验证结果
        self.assertTrue(result)

        # 验证设置脚本是否已按预期保存到 shadow 目录中
        setup_script_path = self.shadow_dir / "project_setup.sh"
        self.assertTrue(setup_script_path.is_file())
        self.assertIn("Setup script generated", setup_script_path.read_text(encoding="utf-8"))
        # 验证脚本是否具有可执行权限
        self.assertTrue(os.access(setup_script_path, os.X_OK))

    def test_re_patch_non_existent_file(self):
        """
        测试当指定的响应文件不存在时工具的行为。
        """
        non_existent_file = self.project_root / "non_existent.txt"

        with patch("sys.stderr"):  # 抑制错误输出
            result = run_re_patch(non_existent_file, self.project_root)

        self.assertFalse(result, "工具应在文件不存在时报告失败")
