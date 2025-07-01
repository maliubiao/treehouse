import hashlib
import os
import random
import re
import sys
import tempfile
from pathlib import Path


class TagRandomizer:
    """
    处理标签随机化和还原的工具类。

    LLM在生成包含[start]/[end]标签的代码时，可能会在指令部分也错误地使用
    这些标签。为了避免解析歧义，此工具类将指令内容中的标准标签随机化为
    [start.XX]/[end.XX]格式，在执行前再由ReplaceEngine还原。

    功能:
    - 将标准标签[start]/[end]随机化为[start.XX]/[end.XX]格式。
    - 将随机化标签还原为标准标签。

    使用示例:
    >>> randomizer = TagRandomizer()
    >>> source_code = "print('[start] a block [end]')"
    >>> randomized_content = randomizer.randomize_tags(source_code)
    >>> print(randomized_content)
    # print('[start.XX] a block [end.XX]')
    >>> restored_content = TagRandomizer.restore_tags(randomized_content)
    >>> print(restored_content)
    # print('[start] a block [end]')
    """

    def __init__(self):
        self.random_suffix = f"{random.randint(0, 99):02d}"
        self.tag_pattern = re.compile(r"\[(start|end)\]")
        self.randomized_pattern = re.compile(r"\[(start|end)\.\d{2}\]")

    def randomize_tags(self, content):
        """
        将内容中的标准标签替换为随机化标签。

        Args:
            content (str): 需要处理的文本内容。

        Returns:
            str: 处理后的文本，所有[start]和[end]标签被替换为随机化版本。
        """

        def replace_tag(match):
            tag_type = match.group(1)
            return f"[{tag_type}.{self.random_suffix}]"

        return self.tag_pattern.sub(replace_tag, content)

    @staticmethod
    def restore_tags(content):
        """
        将内容中的随机化标签还原为标准标签。

        此方法为静态方法，因为它不依赖于任何实例状态。

        Args:
            content (str): 需要处理的文本内容。

        Returns:
            str: 处理后的文本，所有[start.XX]和[end.XX]标签被还原为标准形式。
        """
        pattern = re.compile(r"\[(start|end)\.\d{2}\]")
        return pattern.sub(r"[\1]", content)


class ReplaceEngine:
    """
    一个安全的文件修改引擎，用于执行LLM生成的指令。

    功能特点:
    - 支持多种操作：文件创建、全量覆盖、内容替换、按行替换、内容插入。
    - 安全至上：所有文件写操作都通过备份-回滚机制保证原子性。
    - 严格验证：在执行操作前，对指令和文件状态进行严格校验。
    - 错误处理：提供清晰的错误信息。

    使用示例:
    >>> engine = ReplaceEngine()
    >>> instructions = [
    ...     {'type': 'created_file', 'path': '/tmp/new_file.txt', 'content': 'Hello World'},
    ...     {'type': 'overwrite_whole_file', 'path': '/tmp/new_file.txt', 'content': 'New Content'},
    ...     # ... 其他指令
    ... ]
    >>> engine.execute(instructions)
    """

    def execute(self, instructions):
        """
        按顺序执行一个指令集。

        Args:
            instructions (list[dict]): 从LLMInstructionParser解析出的指令列表。

        Raises:
            ValueError: 当指令验证失败时。
            RuntimeError: 当文件操作执行失败时。
            FileNotFoundError: 当指令中指定的文件不存在时（`created_file`除外）。
        """
        validated = self._validate_instructions(instructions)
        restored_instructions = self._restore_randomized_tags(validated)

        for instr in restored_instructions:
            try:
                if instr["type"] == "replace":
                    self._safe_replace(path=instr["path"], src=instr["src"], dst=instr["dst"])
                elif instr["type"] == "replace_lines":
                    self._safe_replace_lines(
                        path=instr["path"],
                        start_line=instr["start_line"],
                        end_line=instr["end_line"],
                        src=instr["src"],
                        dst=instr["dst"],
                    )
                elif instr["type"] == "insert":
                    self._safe_insert(path=instr["path"], line_num=instr["line_num"], content=instr["content"])
                elif instr["type"] == "overwrite_whole_file":
                    self._safe_overwrite_file(path=instr["path"], content=instr["content"])
                elif instr["type"] == "created_file":
                    self._safe_create_file(path=instr["path"], content=instr["content"])
                # project_setup_script is handled by the caller, so we ignore it here.

            except Exception as e:
                # 统一异常出口，附加文件路径信息，方便调试
                raise RuntimeError(f"操作失败 @ {instr.get('path', 'project_setup_script')}: {e}") from e

    def _restore_randomized_tags(self, instructions):
        """
        还原指令内容中的所有随机化标签。
        """
        restored = []
        for instr in instructions:
            new_instr = instr.copy()
            if new_instr["type"] in ("replace", "replace_lines"):
                new_instr["src"] = TagRandomizer.restore_tags(instr["src"])
                new_instr["dst"] = TagRandomizer.restore_tags(instr["dst"])
            elif new_instr["type"] in ("insert", "overwrite_whole_file", "created_file", "project_setup_script"):
                if "content" in new_instr:
                    new_instr["content"] = TagRandomizer.restore_tags(instr["content"])
            restored.append(new_instr)
        return restored

    def _validate_instructions(self, instr_set):
        """验证指令集的有效性，并解析为内部格式。"""
        if not instr_set:
            return []

        validated = []
        for i, instr in enumerate(instr_set):
            if not self._is_valid_instruction(instr):
                raise ValueError(f"无效或不完整的指令 @ 索引 {i}: {instr}")

            # 对需要路径的指令进行标准化和存在性检查
            if "path" in instr:
                path = Path(instr["path"])
                # created_file 指令允许文件不存在，但其父目录必须可写
                if instr["type"] == "created_file":
                    parent_dir = path.parent
                    if not parent_dir.exists():
                        # We will create it, just check if we can write there
                        try:
                            parent_dir.mkdir(parents=True, exist_ok=True)
                            if not any(parent_dir.iterdir()):
                                parent_dir.rmdir()  # Clean up test directory if we created it and it's empty
                        except OSError as e:
                            raise ValueError(f"无法创建父目录 for {path}: {e}")
                    elif not os.access(parent_dir, os.W_OK):
                        raise ValueError(f"父目录不可写: {parent_dir}")
                # 其他指令要求文件必须存在
                elif not path.exists():
                    raise FileNotFoundError(f"文件不存在: {path}")
                elif not path.is_file():
                    raise ValueError(f"路径不是一个文件: {path}")

                instr["path"] = str(path.resolve())

            # 类型特定验证
            if instr["type"] == "replace_lines":
                start_line, end_line = instr["start_line"], instr["end_line"]
                if not (isinstance(start_line, int) and isinstance(end_line, int) and 1 <= start_line <= end_line):
                    raise ValueError(f"无效的行号范围: start={start_line}, end={end_line}")

            elif instr["type"] == "insert":
                line_num = instr["line_num"]
                if not (isinstance(line_num, int) and line_num >= 0):  # 0 for insert at the beginning
                    raise ValueError(f"无效的插入行号: {line_num}")

            validated.append(instr)
        return validated

    @staticmethod
    def _is_valid_instruction(instr):
        """检查单个指令是否包含所有必需的键。"""
        if not isinstance(instr, dict) or "type" not in instr:
            return False

        instr_type = instr["type"]
        if instr_type == "project_setup_script":
            return "content" in instr

        # All other types require a path
        if "path" not in instr:
            return False

        if instr_type == "replace":
            return {"src", "dst"}.issubset(instr.keys())
        if instr_type == "replace_lines":
            return {"start_line", "end_line", "src", "dst"}.issubset(instr.keys())
        if instr_type == "insert":
            return {"line_num", "content"}.issubset(instr.keys())
        if instr_type in ("overwrite_whole_file", "created_file"):
            return "content" in instr

        return False

    def _safe_create_file(self, path, content):
        """
        安全地创建或覆盖一个文件。

        此行为对于在沙箱环境中或需要幂等文件操作的场景非常有用。
        如果文件不存在，它会连同其父目录一起被创建。
        此操作不执行备份，因为它被视为建立一个确定的状态，而非修改现有状态。
        """
        path_obj = Path(path)
        # 根据用户反馈，`created_file`指令现在可以覆盖现有文件，
        # 以支持沙箱环境中的文件状态重置。
        # 因此，移除了原有的FileExistsError检查。

        # 自动创建父目录，这比用户预期的更周到
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        # 'w'模式会截断并写入文件，如果文件存在则覆盖，不存在则创建。
        with open(path_obj, "w", encoding="utf-8") as f:
            f.write(content)

    def _safe_overwrite_file(self, path, content):
        """安全地用新内容覆盖整个文件，使用备份和回滚机制。"""
        backup_path = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                original_content = f.read()
            backup_path = self._create_backup(path, original_content)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            if backup_path:
                self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path and backup_path.exists():
                backup_path.unlink()

    def _safe_replace(self, path, src, dst):
        """安全地替换文件中的唯一匹配字符串，使用备份和回滚机制。"""
        with open(path, "r", encoding="utf-8") as f:
            original_content = f.read()

        count = original_content.count(src)
        if count == 0:
            raise ValueError("未找到匹配的源字符串")
        if count > 1:
            raise ValueError(f"找到 {count} 个匹配项，无法确保唯一性以进行安全替换")

        updated_content = original_content.replace(src, dst, 1)

        backup_path = self._create_backup(path, original_content)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(updated_content)
        except Exception:
            self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path and backup_path.exists():
                backup_path.unlink()

    def _safe_replace_lines(self, path, start_line, end_line, src, dst):
        """安全地替换指定行范围的内容，使用备份和回滚机制。"""
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not (1 <= start_line <= end_line <= len(lines)):
            raise ValueError(f"无效行号范围: {start_line}-{end_line}，文件总行数: {len(lines)}")

        original_block = "".join(lines[start_line - 1 : end_line])
        # 使用strip()来忽略因编辑器配置可能产生的尾部空白差异
        if original_block.strip() != src.strip():
            # 提供详细的差异信息，便于调试
            raise ValueError(
                f"源字符串与文件指定行范围的内容不匹配。\n--- EXPECTED ---\n{src}\n--- ACTUAL ---\n{original_block}"
            )

        backup_path = self._create_backup(path, "".join(lines))
        try:
            # 将替换内容按行分割，并确保每行都以换行符结尾
            dst_lines = [line + "\n" for line in dst.splitlines()]
            if dst:
                # 增加一个额外的空行，以提高代码变更的可读性
                dst_lines.append("\n")

            new_lines = lines[: start_line - 1] + dst_lines + lines[end_line:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path and backup_path.exists():
                backup_path.unlink()

    def _safe_insert(self, path, line_num, content):
        """安全地在指定行号插入内容，使用备份和回滚机制。"""
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # line_num可以等于len(lines)，表示在文件末尾插入
        if not (0 <= line_num <= len(lines)):
            raise ValueError(f"无效行号: {line_num}，文件总行数: {len(lines)}")

        backup_path = self._create_backup(path, "".join(lines))
        try:
            # 将插入内容按行分割，并确保每行都以换行符结尾
            insert_lines = [line + "\n" for line in content.splitlines()]
            if content:
                # 增加一个额外的空行，以提高代码变更的可读性
                insert_lines.append("\n")

            new_lines = lines[:line_num] + insert_lines + lines[line_num:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path and backup_path.exists():
                backup_path.unlink()

    @staticmethod
    def _create_backup(original_path, content):
        """创建临时备份文件。"""
        backup_dir = Path(tempfile.gettempdir())
        file_hash = hashlib.md5(str(original_path).encode()).hexdigest()[:8]
        backup_name = f"{Path(original_path).name}.{file_hash}.bak"
        backup_path = backup_dir / backup_name
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)
        return backup_path

    @staticmethod
    def _restore_backup(backup_path, target_path):
        """从备份恢复文件。"""
        if backup_path and backup_path.exists():
            with open(backup_path, "r", encoding="utf-8") as f_bak, open(target_path, "w", encoding="utf-8") as f_orig:
                f_orig.write(f_bak.read())


class LLMInstructionParser:
    """
    从LLM响应内容中解析出结构化的文件操作指令。

    该解析器设计得非常健壮，能识别多种常见的LLM输出格式，包括
    严格的指令格式和常见的Markdown代码块格式。
    """

    _PATTERN = re.compile(
        # 格式1: 项目设置脚本
        # [project setup script]
        # [start]
        # ... shell script ...
        # [end]
        r"\[project setup script\]\n\[start\]\n?(?P<setup_script>.*?)\n?\[end\]|"
        # 格式2: 文件创建/覆盖
        # [overwrite whole file|created file]: /path/to/file
        # [start]
        # ... content ...
        # [end]
        r"\[(?P<action>overwrite whole file|created file)\]:\s*(?P<path>[^\n]+?)\n\[start\]\n?(?P<content>.*?)\n?\[end\]|"
        # 格式3: 标准替换 (字符串或行范围)
        # [replace]: /path/to/file
        # [lines]: 5-10  (可选)
        # [start]
        # ... src content ...
        # [end]
        # [start]
        # ... dst content ...
        # [end]
        r"\[replace\]:\s*(?P<path_replace>[^\n]+?)\n(?:\[lines\]:\s*(?P<lines>\d+-\d+)\n)?\[start\]\n?(?P<src_replace>.*?)\n?\[end\]\n\[start\]\n?(?P<dst_replace>.*?)\n?\[end\]|"
        # 格式4: 插入
        # [insert]: /path/to/file
        # [line]: 15
        # [start]
        # ... content ...
        # [end]
        r"\[insert\]:\s*(?P<path_insert>[^\n]+?)\n\[line\]:\s*(?P<line_num>\d+)\n\[start\]\n?(?P<content_insert>.*?)\n?\[end\]|"
        # 格式5 (备用): Markdown代码块格式
        # ```python:/path/to/file
        # ... content ...
        # ```
        r"```(?P<lang>\w*):(?P<alt_path>[^\n]+?)\n(?P<alt_content>.*?)```",
        re.DOTALL | re.MULTILINE,
    )

    @classmethod
    def parse(cls, text):
        """
        从文本中解析所有匹配的指令。
        """
        instructions = []
        for match in cls._PATTERN.finditer(text):
            groups = match.groupdict()

            if groups["setup_script"] is not None:
                instructions.append({"type": "project_setup_script", "content": groups["setup_script"].strip()})

            elif groups["action"] is not None:
                instructions.append(
                    {
                        "type": groups["action"].replace(" ", "_"),
                        "path": groups["path"].strip(),
                        "content": groups["content"].strip(),
                    }
                )

            elif groups["path_replace"] is not None:
                path = groups["path_replace"].strip()
                if groups["lines"]:
                    start, end = map(int, groups["lines"].split("-"))
                    instructions.append(
                        {
                            "type": "replace_lines",
                            "path": path,
                            "start_line": start,
                            "end_line": end,
                            "src": groups["src_replace"].strip(),
                            "dst": groups["dst_replace"].strip(),
                        }
                    )
                else:
                    instructions.append(
                        {
                            "type": "replace",
                            "path": path,
                            "src": groups["src_replace"].strip(),
                            "dst": groups["dst_replace"].strip(),
                        }
                    )

            elif groups["path_insert"] is not None:
                instructions.append(
                    {
                        "type": "insert",
                        "path": groups["path_insert"].strip(),
                        "line_num": int(groups["line_num"]),
                        "content": groups["content_insert"].strip(),
                    }
                )

            elif groups["alt_path"] is not None:
                instructions.append(
                    {
                        "type": "overwrite_whole_file",
                        "path": groups["alt_path"].strip(),
                        "content": groups["alt_content"].strip(),
                    }
                )

        return instructions


def _run_tests():
    """为ReplaceEngine和LLMInstructionParser运行一个全面的自测试套件。"""
    import shutil
    import traceback

    print("=" * 20 + " Engine Self-test Start " + "=" * 20)
    engine = ReplaceEngine()
    test_dir = Path(tempfile.gettempdir()) / "engine_tests"
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)

    test_counter = 1

    def run_test(name, instructions_text, initial_content, expected_content_map, should_fail=False):
        nonlocal test_counter
        print(f"\n--- Test {test_counter}: {name} ---")

        # Create a map from placeholder name to full temporary path
        all_relative_paths = set(initial_content.keys()) | set(expected_content_map.keys())
        # For tests that are expected to fail, the placeholder might not be in the maps.
        # Find all placeholders in the instruction text to be robust.
        placeholders = re.findall(r"\{([^}]+)\}", instructions_text)
        all_relative_paths.update(placeholders)

        path_map = {rel_path: str(test_dir / rel_path) for rel_path in all_relative_paths}

        try:
            # 1. Setup initial files
            for rel_path, content in initial_content.items():
                full_path = Path(path_map[rel_path])
                full_path.parent.mkdir(parents=True, exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)

            # 2. Prepare instructions by replacing placeholders with full paths.
            final_instructions_text = instructions_text
            for rel_path, full_path in path_map.items():
                final_instructions_text = final_instructions_text.replace(f"{{{rel_path}}}", full_path)

            instructions = LLMInstructionParser.parse(final_instructions_text)

            # 3. Execute
            engine.execute(instructions)

            if should_fail:
                print(">>> FAILED: Expected an exception, but none was raised.")
                return

            # 4. Verify
            for rel_path, expected_content in expected_content_map.items():
                full_path = Path(path_map[rel_path])
                if not full_path.exists():
                    print(f">>> FAILED: Expected file '{rel_path}' not found.")
                    return
                with open(full_path, "r", encoding="utf-8") as f:
                    actual_content = f.read()
                if actual_content != expected_content:
                    print(f">>> FAILED: Content mismatch in '{rel_path}'.")
                    print(f"--- EXPECTED ---\n{expected_content}\n--- ACTUAL ---\n{actual_content}")
                    return
            print(">>> PASSED!")

        except Exception as e:
            if should_fail:
                print(f">>> PASSED: Caught expected exception: {type(e).__name__}: {e}")
            else:
                print(f">>> FAILED: Unexpected exception: {type(e).__name__}: {e}")
                traceback.print_exc()
        finally:
            test_counter += 1

    # --- Test Cases ---

    # Test 1: Create a new file
    run_test(
        "Create a new file",
        "[created file]: {file1.txt}\n[start]\nHello, new world!\n[end]",
        {},
        {"file1.txt": "Hello, new world!"},
    )

    # Test 2: Overwrite a whole file
    run_test(
        "Overwrite a whole file",
        "[overwrite whole file]: {file1.txt}\n[start]\nNew content.\n[end]",
        {"file1.txt": "Old content."},
        {"file1.txt": "New content."},
    )

    # Test 3: Basic string replacement
    run_test(
        "Basic string replacement",
        "[replace]: {file1.txt}\n[start]\nold\n[end]\n[start]\nnew\n[end]",
        {"file1.txt": "This is old content."},
        {"file1.txt": "This is new content."},
    )

    # Test 4: Line range replacement
    run_test(
        "Line range replacement",
        "[replace]: {file1.txt}\n[lines]: 2-3\n[start]Line 2\nLine 3\n[end]\n[start]New Line 2\nNew Line 3\n[end]",
        {"file1.txt": "Line 1\nLine 2\nLine 3\nLine 4\n"},
        {"file1.txt": "Line 1\nNew Line 2\nNew Line 3\n\nLine 4\n"},
    )

    # Test 5: Insert content at a specific line
    run_test(
        "Insert content at a specific line",
        "[insert]: {file1.txt}\n[line]: 1\n[start]\nInserted Line\n[end]",
        {"file1.txt": "Line 1\nLine 2\n"},
        {"file1.txt": "Line 1\nInserted Line\n\nLine 2\n"},
    )

    # Test 6: Fail on multiple matches for replace
    run_test(
        "Fail on multiple matches for replace",
        "[replace]: {file1.txt}\n[start]\nfail\n[end]\n[start]\npass\n[end]",
        {"file1.txt": "fail fail"},
        {},
        should_fail=True,
    )

    # Test 7: Fail on source mismatch for line replace
    run_test(
        "Fail on source mismatch for line replace",
        "[replace]: {file1.txt}\n[lines]: 1-1\n[start]\nWrong source\n[end]\n[start]\n...\n[end]",
        {"file1.txt": "Correct source\n"},
        {},
        should_fail=True,
    )

    # Test 8: Randomized tag restoration
    run_test(
        "Randomized tag restoration",
        "[overwrite whole file]: {file1.txt}\n[start]\nThis has [start" + ".12] and [end" + ".99] tags.\n[end]",
        {"file1.txt": "Initial"},
        {"file1.txt": "This has [start] and [end] tags."},
    )

    # Test 9: Create file in a new subdirectory
    run_test(
        "Create file in a new subdirectory",
        "[created file]: {new_dir/file.txt}\n[start]\nSubdir content\n[end]",
        {},
        {"new_dir/file.txt": "Subdir content"},
    )

    print("\n" + "=" * 21 + " Engine Self-test End " + "=" * 22)
    # Clean up test directory
    shutil.rmtree(test_dir)


if __name__ == "__main__":
    _run_tests()
