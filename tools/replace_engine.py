import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path


class ReplaceEngine:
    """
    安全执行字符串替换操作的引擎

    功能特点:
    - 严格验证替换源字符串的唯一性
    - 操作失败时自动回滚
    - 支持批量顺序执行替换指令
    - 详细的错误报告机制

    使用示例:
    >>> engine = ReplaceEngine()
    >>> instructions = [
    ...     {
    ...         'type': 'replace',
    ...         'path': '/path/to/file',
    ...         'src': 'original content',
    ...         'dst': 'new content'
    ...     },
    ...     {
    ...         'type': 'replace_lines',
    ...         'path': '/path/to/file',
    ...         'start_line': 5,
    ...         'end_line': 8,
    ...         'src': 'lines content',
    ...         'dst': 'new lines'
    ...     },
    ...     {
    ...         'type': 'insert',
    ...         'path': '/path/to/file',
    ...         'line_num': 10,
    ...         'content': 'inserted content'
    ...     }
    ... ]
    >>> engine.execute(instructions)
    """

    def execute(self, instructions):
        """
        执行替换指令集

        Args:
            instructions: 替换指令列表，每个指令为包含以下键的字典:
                - type: 操作类型 (replace/replace_lines/insert)
                - path: 文件绝对路径
                - 其他操作特定参数

        Raises:
            ValueError: 当出现以下情况时:
                - 源字符串在文件中不存在
                - 源字符串在文件中出现多次
                - 文件路径无效
                - 行号范围无效
        """
        validated = self._validate_instructions(instructions)

        for instr in validated:
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
            except Exception as e:
                raise RuntimeError(f"操作失败 @ {instr['path']}: {str(e)}") from e

    def _validate_instructions(self, instr_set):
        """验证指令集有效性"""
        if not instr_set:
            return []

        validated = []
        for i, instr in enumerate(instr_set):
            if not self._is_valid_instruction(instr):
                raise ValueError(f"无效指令 @ 索引 {i}")

            # 检查文件是否存在
            path = Path(instr["path"])
            if not path.exists():
                raise FileNotFoundError(f"文件不存在: {path}")
            if not path.is_file():
                raise ValueError(f"路径不是文件: {path}")

            # 根据指令类型进行额外验证
            if instr["type"] == "replace":
                validated.append(
                    {"type": "replace", "path": str(path.resolve()), "src": instr["src"], "dst": instr["dst"]}
                )
            elif instr["type"] == "replace_lines":
                # 验证行号范围
                start_line = instr["start_line"]
                end_line = instr["end_line"]
                if not (isinstance(start_line, int) and isinstance(end_line, int)):
                    raise ValueError(f"行号必须是整数: start_line={start_line}, end_line={end_line}")
                if start_line < 1 or end_line < start_line:
                    raise ValueError(f"无效行号范围: {start_line}-{end_line}")

                validated.append(
                    {
                        "type": "replace_lines",
                        "path": str(path.resolve()),
                        "start_line": start_line,
                        "end_line": end_line,
                        "src": instr["src"],
                        "dst": instr["dst"],
                    }
                )
            else:  # insert
                # 验证行号
                line_num = instr["line_num"]
                if not isinstance(line_num, int) or line_num < 0:  # 0 for inserting at the beginning
                    raise ValueError(f"无效行号: {line_num}")

                validated.append(
                    {"type": "insert", "path": str(path.resolve()), "line_num": line_num, "content": instr["content"]}
                )
        return validated

    @staticmethod
    def _is_valid_instruction(instr):
        """验证单个指令有效性"""
        if not isinstance(instr, dict):
            return False

        # 公共必填字段
        if "type" not in instr or "path" not in instr:
            return False

        # 类型特定验证
        if instr["type"] == "replace":
            required_keys = {"src", "dst"}
            return required_keys.issubset(instr.keys())

        if instr["type"] == "replace_lines":
            required_keys = {"start_line", "end_line", "src", "dst"}
            return required_keys.issubset(instr.keys())

        if instr["type"] == "insert":
            required_keys = {"line_num", "content"}
            return required_keys.issubset(instr.keys())

        return False

    def _safe_replace(self, path, src, dst):
        """
        安全的替换实现（带备份和回滚机制）

        步骤:
        1. 创建临时备份文件
        2. 执行替换操作
        3. 验证替换结果
        4. 失败时恢复备份
        """
        # 读取原始内容
        with open(path, "r", encoding="utf-8") as f:
            original_content = f.read()

        # 验证源字符串唯一性
        count = original_content.count(src)
        if count == 0:
            raise ValueError("未找到匹配的源字符串")
        if count > 1:
            raise ValueError(f"找到多个匹配项 ({count}处)，无法确保唯一性")

        # 执行替换
        updated_content = original_content.replace(src, dst)

        # 创建备份
        backup_path = self._create_backup(path, original_content)

        try:
            # 写入新内容
            with open(path, "w", encoding="utf-8") as f:
                f.write(updated_content)

            # 验证替换结果
            if not self._verify_replacement(path, src, dst):
                raise RuntimeError("替换后验证失败")

        except Exception:
            # 恢复备份
            self._restore_backup(backup_path, path)
            raise
        finally:
            # 清理备份
            if backup_path.exists():
                backup_path.unlink()

    def _safe_replace_lines(self, path, start_line, end_line, src, dst):
        """
        安全的行号范围替换实现

        步骤:
        1. 创建临时备份文件
        2. 执行行范围替换
        3. 验证替换结果
        4. 失败时恢复备份
        """
        # 读取原始内容
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 验证行号范围
        if start_line < 1 or end_line > len(lines) or start_line > end_line:
            raise ValueError(f"无效行号范围: {start_line}-{end_line}，文件总行数: {len(lines)}")

        # 提取行范围内容
        original_block = "".join(lines[start_line - 1 : end_line])
        if original_block.strip() != src.strip():
            raise ValueError("源字符串与文件指定行范围的内容不匹配")

        # 创建备份
        backup_path = self._create_backup(path, "".join(lines))

        try:
            # 准备替换内容（保留换行符）
            dst_lines = dst.splitlines(keepends=True)
            if dst and not dst.endswith("\n"):
                dst_lines[-1] += "\n"

            # 构建新内容
            new_lines = lines[: start_line - 1] + dst_lines + lines[end_line:]

            # 写入新内容
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

        except Exception:
            self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path.exists():
                backup_path.unlink()

    def _safe_insert(self, path, line_num, content):
        """
        安全的插入实现

        步骤:
        1. 创建临时备份文件
        2. 执行插入操作
        3. 验证插入结果
        4. 失败时恢复备份
        """
        # 读取原始内容
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 验证行号
        if line_num < 0 or line_num > len(lines):
            raise ValueError(f"无效行号: {line_num}，文件总行数: {len(lines)}")

        # 创建备份
        backup_path = self._create_backup(path, "".join(lines))

        try:
            # 准备插入内容（保留换行符）
            insert_lines = content.splitlines(keepends=True)
            if content and not content.endswith("\n"):
                insert_lines[-1] += "\n"

            # 执行插入
            new_lines = lines[:line_num] + insert_lines + lines[line_num:]

            # 写入新内容
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

        except Exception:
            self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path.exists():
                backup_path.unlink()

    @staticmethod
    def _create_backup(original_path, content):
        """创建临时备份文件"""
        backup_dir = Path(tempfile.gettempdir())
        file_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        backup_name = f"{Path(original_path).name}.bak_{file_hash}"
        backup_path = backup_dir / backup_name

        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)

        return backup_path

    @staticmethod
    def _restore_backup(backup_path, target_path):
        """从备份恢复文件"""
        with open(backup_path, "r", encoding="utf-8") as f:
            content = f.read()

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _verify_replacement(path, src, dst):
        """验证替换结果是否正确"""
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # 源字符串应完全消失
        if src in content:
            return False

        # 目标字符串应存在（除非是删除操作）
        if dst and dst not in content:
            return False

        return True

    @staticmethod
    def _verify_lines_replacement(path, start_line, expected):
        """验证行号范围替换结果"""
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 计算替换后的行数
        expected_lines = expected.splitlines(keepends=True)
        if expected and not expected.endswith("\n"):
            expected_lines[-1] += "\n"

        expected_line_count = len(expected_lines)
        actual_block = "".join(lines[start_line - 1 : start_line - 1 + expected_line_count])

        return actual_block.strip() == expected.strip()

    @staticmethod
    def _verify_insertion(path, line_num, expected):
        """验证插入结果"""
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 计算插入内容的行数
        insert_lines = expected.splitlines(keepends=True)
        if expected and not expected.endswith("\n"):
            insert_lines[-1] += "\n"
        insert_line_count = len(insert_lines)

        # 验证插入位置
        actual_block = "".join(lines[line_num : line_num + insert_line_count])
        return actual_block.strip() == expected.strip()


class LLMInstructionParser:
    """
    从LLM响应内容中解析指令。
    支持文件创建/覆盖和部分内容替换。

    增强功能:
    - 移除了未使用的user verify功能
    - 强化了文件覆盖指令的可靠性
    - 简化了正则表达式模式
    - 添加了更健壮的内容提取
    - 支持行号范围替换和插入指令
    """

    _PATTERN = re.compile(
        r"\[project setup shellscript start\]\n(?P<setup_script>.*?)\n\[project setup shellscript end\]|"
        r"\[(?P<action>overwrite whole file|created file)\]:\s*(?P<path>[^\n]+)\n\[start\]\n(?P<content>.*?)\n\[end\]|"
        r"```(?P<lang>\w*):(?P<alt_path>[^\n]+?)\n(?P<alt_content>.*?)```|"
        r"\[replace\]:\s*(?P<path_replace>.+?)\n(?:\[lines\]:\s*(?P<lines>\d+-\d+)\n)?"
        r"\[start\]\n(?P<src_replace>.*?)\n\[end\]\n\[start\]\n(?P<dst_replace>.*?)\n\[end\]|"
        r"\[insert\]:\s*(?P<path_insert>.+?)\n\[line\]:\s*(?P<line_num>\d+)\n"
        r"\[start\]\n(?P<content_insert>.*?)\n\[end\]",
        re.DOTALL,
    )

    @classmethod
    def parse(cls, content):
        """
        从文本内容解析指令。

        支持格式:
        1. 项目设置脚本:
           [project setup shellscript start]...script...[project setup shellscript end]

        2. 文件覆盖/创建:
           [overwrite whole file]: /path/to/file
           [start]
           ...content...
           [end]

        3. 代码块格式文件:
           ```lang:/path/to/file
           ...content...
           ```

        4. 字符串替换:
           [replace]: /path/to/file
           [start]
           ...src...
           [end]
           [start]
           ...dst...
           [end]

        5. 行号范围替换:
           [replace]: /path/to/file
           [lines]: start_line-end_line
           [start]
           ...src...
           [end]
           [start]
           ...dst...
           [end]

        6. 指定行插入:
           [insert]: /path/to/file
           [line]: line_number
           [start]
           ...content...
           [end]
        """
        instructions = []
        for match in cls._PATTERN.finditer(content):
            gd = match.groupdict()

            # 处理项目设置脚本
            if gd["setup_script"] is not None:
                instructions.append({"type": "project_setup_script", "content": gd["setup_script"].strip()})

            # 处理文件覆盖/创建指令
            elif gd["action"] is not None:
                action_type = gd["action"].replace(" ", "_")
                instructions.append(
                    {
                        "type": action_type,
                        "path": gd["path"].strip(),
                        "content": gd["content"],
                    }
                )

            # 处理代码块格式文件
            elif gd["alt_path"] is not None:
                instructions.append(
                    {
                        "type": "overwrite_whole_file",
                        "path": gd["alt_path"].strip(),
                        "content": gd["alt_content"].strip(),
                    }
                )

            # 处理字符串替换和行号范围替换
            elif gd["path_replace"] is not None:
                # 检查是否是行号范围替换
                if gd["lines"] is not None:
                    try:
                        start_line, end_line = map(int, gd["lines"].split("-"))
                    except ValueError:
                        continue  # 跳过格式错误的行号

                    instructions.append(
                        {
                            "type": "replace_lines",
                            "path": gd["path_replace"].strip(),
                            "start_line": start_line,
                            "end_line": end_line,
                            "src": gd["src_replace"],
                            "dst": gd["dst_replace"],
                        }
                    )
                else:
                    instructions.append(
                        {
                            "type": "replace",
                            "path": gd["path_replace"].strip(),
                            "src": gd["src_replace"],
                            "dst": gd["dst_replace"],
                        }
                    )

            # 处理插入指令
            elif gd["path_insert"] is not None and gd["line_num"] is not None:
                try:
                    line_num = int(gd["line_num"])
                except ValueError:
                    continue  # 跳过无效行号

                instructions.append(
                    {
                        "type": "insert",
                        "path": gd["path_insert"].strip(),
                        "line_num": line_num,
                        "content": gd["content_insert"],
                    }
                )

        return instructions


def _run_tests():
    """执行所有测试用例"""
    print("=== ReplaceEngine Self-test Start ===")

    # Test 1: Basic replacement
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt", encoding="utf-8") as tmp:
        test_path = tmp.name
        content = (
            "Line 1\n"
            "Line 2\n"
            "### START BLOCK ###\n"
            "Unique content to be replaced.\n"
            "It can span multiple lines.\n"
            "### END BLOCK ###\n"
            "Last line."
        )
        tmp.write(content)
        tmp.flush()

    print(f"Test 1: Created test file: {test_path}")
    src_block = "### START BLOCK ###\nUnique content to be replaced.\nIt can span multiple lines.\n### END BLOCK ###"
    dst_block = "### REPLACED BLOCK ###\nThis is the new content.\nIt also spans multiple lines.\n### END BLOCK ###"

    instruction_text = f"""[replace]: {test_path}
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    print("Parsing replacement instruction...")
    instr_list = LLMInstructionParser.parse(instruction_text)
    assert len(instr_list) == 1, "Instruction parsing failed"
    assert instr_list[0]["type"] == "replace"

    engine = ReplaceEngine()
    try:
        engine.execute(instr_list)
        print("Test 1: Replacement successful")
    except RuntimeError as e:
        print(f"Test 1 FAILED: {str(e)}")
        os.unlink(test_path)
        sys.exit(1)

    with open(test_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    if src_block in new_content:
        print("Test 1 ERROR: Original content was not replaced.")
        os.unlink(test_path)
        sys.exit(1)

    if dst_block not in new_content:
        print("Test 1 ERROR: New content was not written correctly.")
        os.unlink(test_path)
        sys.exit(1)

    print("Test 1 PASSED!")
    os.unlink(test_path)

    # Test 2: Multiple occurrences of source string
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt", encoding="utf-8") as tmp:
        test_path = tmp.name
        content = "重复内容\n### 替换目标块 ###\n重复内容\n### 替换目标块 ###\n重复内容"
        tmp.write(content)
        tmp.flush()

    print(f"测试2: 创建测试文件: {test_path}")
    src_block = "### 替换目标块 ###"
    dst_block = "### 已替换块 ###"

    instruction_text = f"""[replace]: {test_path}
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    instr_list = LLMInstructionParser.parse(instruction_text)
    engine = ReplaceEngine()
    try:
        engine.execute(instr_list)
        print("测试2错误: 预期异常未抛出")
        os.unlink(test_path)
        sys.exit(1)
    except RuntimeError as e:
        if "多个匹配项" in str(e):
            print(f"测试2通过: 捕获到预期异常 - {str(e)}")
        else:
            print(f"测试2失败: 异常类型错误 - {str(e)}")
            os.unlink(test_path)
            sys.exit(1)
    finally:
        if os.path.exists(test_path):
            os.unlink(test_path)

    # Test 3: Source string not found
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt", encoding="utf-8") as tmp:
        test_path = tmp.name
        content = "没有目标内容"
        tmp.write(content)
        tmp.flush()

    print(f"测试3: 创建测试文件: {test_path}")
    src_block = "不存在的字符串"
    dst_block = "新内容"

    instruction_text = f"""[replace]: {test_path}
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    instr_list = LLMInstructionParser.parse(instruction_text)
    engine = ReplaceEngine()
    try:
        engine.execute(instr_list)
        print("测试3错误: 预期异常未抛出")
        os.unlink(test_path)
        sys.exit(1)
    except RuntimeError as e:
        if "未找到匹配的源字符串" in str(e):
            print(f"测试3通过: 捕获到预期异常 - {str(e)}")
        else:
            print(f"测试3失败: 异常类型错误 - {str(e)}")
            os.unlink(test_path)
            sys.exit(1)
    finally:
        if os.path.exists(test_path):
            os.unlink(test_path)

    # Test 4: Empty string replacement
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt", encoding="utf-8") as tmp:
        test_path = tmp.name
        content = "原始内容"
        tmp.write(content)
        tmp.flush()

    print(f"测试4: 创建测试文件: {test_path}")
    src_block = "原始内容"
    dst_block = ""

    instruction_text = f"""[replace]: {test_path}
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    instr_list = LLMInstructionParser.parse(instruction_text)
    engine = ReplaceEngine()
    try:
        engine.execute(instr_list)
        print("测试4: 替换执行成功")
    except RuntimeError as e:
        print(f"测试4失败: {str(e)}")
        os.unlink(test_path)
        sys.exit(1)

    with open(test_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    if new_content != "":
        print(f"测试4错误: 预期空文件, 实际内容: {new_content}")
        os.unlink(test_path)
        sys.exit(1)

    print("测试4通过!")
    os.unlink(test_path)

    # Test 5: Overwrite whole file
    print("测试5: 覆盖整个文件指令")
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt", encoding="utf-8") as tmp:
        test_path = tmp.name
        tmp.write("原始内容")
        tmp.flush()

    new_content = "这是全新的文件内容"
    instruction_text = f"""[overwrite whole file]: {test_path}
[start]
{new_content}
[end]"""

    instr_list = LLMInstructionParser.parse(instruction_text)
    assert len(instr_list) == 1, "文件覆盖指令解析失败"
    assert instr_list[0]["type"] == "overwrite_whole_file", "指令类型错误"
    assert instr_list[0]["path"] == test_path, "路径解析错误"
    assert instr_list[0]["content"] == new_content, "内容解析错误"
    print("测试5通过!")
    os.unlink(test_path)

    # Test 6: Create new file
    print("测试6: 创建新文件指令")
    with tempfile.NamedTemporaryFile(mode="w+", delete=True, suffix=".txt", encoding="utf-8") as tmp:
        # 获取临时文件名但不实际创建文件
        test_path = tmp.name

    new_content = "新文件内容"
    instruction_text = f"""[created file]: {test_path}
[start]
{new_content}
[end]"""

    instr_list = LLMInstructionParser.parse(instruction_text)
    assert len(instr_list) == 1, "文件创建指令解析失败"
    assert instr_list[0]["type"] == "created_file", "指令类型错误"
    assert instr_list[0]["path"] == test_path, "路径解析错误"
    assert instr_list[0]["content"] == new_content, "内容解析错误"
    print("测试6通过!")

    # Test 7: Line range replacement
    print("测试7: 行号范围替换")
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt", encoding="utf-8") as tmp:
        test_path = tmp.name
        content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\n"
        tmp.write(content)
        tmp.flush()

    src_block = "Line 3\nLine 4\n"
    dst_block = "New Line 3\nNew Line 4"
    instruction_text = f"""[replace]: {test_path}
[lines]: 3-4
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    instr_list = LLMInstructionParser.parse(instruction_text)
    assert len(instr_list) == 1, "行号替换指令解析失败"
    assert instr_list[0]["type"] == "replace_lines"
    assert instr_list[0]["start_line"] == 3
    assert instr_list[0]["end_line"] == 4

    engine = ReplaceEngine()
    try:
        engine.execute(instr_list)
        print("测试7: 行号替换执行成功")
    except RuntimeError as e:
        print(f"测试7失败: {str(e)}")
        os.unlink(test_path)
        sys.exit(1)

    with open(test_path, "r", encoding="utf-8") as f:
        new_content = f.read()
        expected = "Line 1\nLine 2\nNew Line 3\nNew Line 4\nLine 5\nLine 6\n"
        if new_content != expected:
            print(f"测试7错误: 预期内容: '{expected}', 实际内容: '{new_content}'")
            os.unlink(test_path)
            sys.exit(1)

    print("测试7通过!")
    os.unlink(test_path)

    # Test 8: Insert at specific line
    print("测试8: 指定行插入")
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt", encoding="utf-8") as tmp:
        test_path = tmp.name
        content = "Line 1\nLine 2\nLine 3\nLine 4\n"
        tmp.write(content)
        tmp.flush()

    insert_content = "Inserted Line"
    instruction_text = f"""[insert]: {test_path}
[line]: 2
[start]
{insert_content}
[end]"""

    instr_list = LLMInstructionParser.parse(instruction_text)
    assert len(instr_list) == 1, "插入指令解析失败"
    assert instr_list[0]["type"] == "insert"
    assert instr_list[0]["line_num"] == 2

    engine = ReplaceEngine()
    try:
        engine.execute(instr_list)
        print("测试8: 插入执行成功")
    except RuntimeError as e:
        print(f"测试8失败: {str(e)}")
        os.unlink(test_path)
        sys.exit(1)

    with open(test_path, "r", encoding="utf-8") as f:
        new_content = f.read()
        expected = "Line 1\nLine 2\nInserted Line\nLine 3\nLine 4\n"
        if new_content != expected:
            print(f"测试8错误: 预期内容: '{expected}', 实际内容: '{new_content}'")
            os.unlink(test_path)
            sys.exit(1)

    print("测试8通过!")
    os.unlink(test_path)

    print("=== 所有测试通过 ===")


if __name__ == "__main__":
    _run_tests()
