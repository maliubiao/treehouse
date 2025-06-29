import hashlib
import os
import re
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
    ...         'path': '/path/to/file',
    ...         'src': 'original content',
    ...         'dst': 'new content'
    ...     }
    ... ]
    >>> engine.execute(instructions)
    """

    def execute(self, instructions):
        """
        执行替换指令集

        Args:
            instructions: 替换指令列表，每个指令为包含以下键的字典:
                - path: 文件绝对路径
                - src: 要替换的源字符串
                - dst: 替换后的目标字符串

        Raises:
            ValueError: 当出现以下情况时:
                - 源字符串在文件中不存在
                - 源字符串在文件中出现多次
                - 文件路径无效
        """
        validated = self._validate_instructions(instructions)

        for instr in validated:
            try:
                self._safe_replace(path=instr["path"], src=instr["src"], dst=instr["dst"])
            except Exception as e:
                raise RuntimeError(f"替换失败 @ {instr['path']}: {str(e)}") from e

    def _validate_instructions(self, instructions):
        """验证指令集有效性"""
        if not instructions:
            return []

        validated = []
        for i, instr in enumerate(instructions):
            if not self._is_valid_instruction(instr):
                raise ValueError(f"无效指令 @ 索引 {i}")

            # 检查文件是否存在
            path = Path(instr["path"])
            if not path.exists():
                raise FileNotFoundError(f"文件不存在: {path}")
            if not path.is_file():
                raise ValueError(f"路径不是文件: {path}")

            validated.append({"path": str(path.resolve()), "src": instr["src"], "dst": instr["dst"]})
        return validated

    @staticmethod
    def _is_valid_instruction(instr):
        """验证单个指令有效性"""
        required_keys = {"path", "src", "dst"}
        if not isinstance(instr, dict):
            return False
        if not required_keys.issubset(instr.keys()):
            return False
        if not instr["src"]:
            return False  # 源字符串不能为空
        return True

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
        new_content = original_content.replace(src, dst)

        # 创建备份
        backup_path = self._create_backup(path, original_content)

        try:
            # 写入新内容
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

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


class ReplaceInstructionParser:
    """
    替换指令解析器

    严格解析格式:
    [replace]: <文件路径>
    [start]
    <源字符串>
    [end]
    [start]
    <目标字符串>
    [end]
    """

    PATTERN = re.compile(r"\[replace\]:\s*(.+?)\n\[start\]\n(.*?)\n\[end\]\n\[start\]\n(.*?)\n\[end\]", re.DOTALL)

    @classmethod
    def parse(cls, content):
        """
        从文本内容解析替换指令

        Args:
            content: 包含替换指令的文本内容

        Returns:
            list: 解析后的指令字典列表
            [
                {
                    'path': '/absolute/path',
                    'src': 'original content',
                    'dst': 'new content'
                }
            ]

        Raises:
            ValueError: 当指令格式无效时
        """
        instructions = []
        matches = cls.PATTERN.findall(content)

        if not matches:
            return instructions

        for match in matches:
            if len(match) != 3:
                continue

            path = match[0].strip()
            src = match[1]
            dst = match[2]

            if not path:
                raise ValueError("无效路径")

            instructions.append({"path": path, "src": src, "dst": dst})

        return instructions


if __name__ == "__main__":
    import os
    import sys
    import tempfile

    print("=== ReplaceEngine 自测试开始 ===")

    # 测试1: 基本替换功能
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt") as tmp:
        test_path = tmp.name
        content = (
            "第一行内容\n"
            "第二行内容\n"
            "### 替换目标块 ###\n"
            "这是要被替换的独特内容块\n"
            "包含多行文本确保唯一性\n"
            "### 结束块 ###\n"
            "最后一行内容"
        )
        tmp.write(content)
        tmp.flush()

    print(f"测试1: 创建测试文件: {test_path}")
    src_block = "### 替换目标块 ###\n这是要被替换的独特内容块\n包含多行文本确保唯一性\n### 结束块 ###"
    dst_block = "### 已替换块 ###\n这是替换后的新内容块\n包含多行文本确保唯一性\n### 结束块 ###"

    instruction_str = f"""[replace]: {test_path}
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    print("解析替换指令...")
    instructions = ReplaceInstructionParser.parse(instruction_str)
    assert len(instructions) == 1, "指令解析失败"

    engine = ReplaceEngine()
    try:
        engine.execute(instructions)
        print("测试1: 替换执行成功")
    except Exception as e:
        print(f"测试1失败: {str(e)}")
        os.unlink(test_path)
        sys.exit(1)

    with open(test_path, "r") as f:
        new_content = f.read()

    if src_block in new_content:
        print("测试1错误: 原始内容未被替换")
        os.unlink(test_path)
        sys.exit(1)

    if dst_block not in new_content:
        print("测试1错误: 新内容未正确写入")
        os.unlink(test_path)
        sys.exit(1)

    print("测试1通过!")
    os.unlink(test_path)

    # 测试2: 源字符串多次出现
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt") as tmp:
        test_path = tmp.name
        content = "重复内容\n### 替换目标块 ###\n重复内容\n### 替换目标块 ###\n重复内容"
        tmp.write(content)
        tmp.flush()

    print(f"测试2: 创建测试文件: {test_path}")
    src_block = "### 替换目标块 ###"
    dst_block = "### 已替换块 ###"

    instruction_str = f"""[replace]: {test_path}
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    instructions = ReplaceInstructionParser.parse(instruction_str)
    engine = ReplaceEngine()
    try:
        engine.execute(instructions)
        print("测试2错误: 预期异常未抛出")
        os.unlink(test_path)
        sys.exit(1)
    except Exception as e:  # 捕获任何异常
        if "多个匹配项" in str(e):  # 检查错误信息
            print(f"测试2通过: 捕获到预期异常 - {str(e)}")
        else:
            print(f"测试2失败: 异常类型错误 - {str(e)}")
            os.unlink(test_path)
            sys.exit(1)
    finally:
        os.unlink(test_path)

    # 测试3: 源字符串不存在
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt") as tmp:
        test_path = tmp.name
        content = "没有目标内容"
        tmp.write(content)
        tmp.flush()

    print(f"测试3: 创建测试文件: {test_path}")
    src_block = "不存在的字符串"
    dst_block = "新内容"

    instruction_str = f"""[replace]: {test_path}
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    instructions = ReplaceInstructionParser.parse(instruction_str)
    engine = ReplaceEngine()
    try:
        engine.execute(instructions)
        print("测试3错误: 预期异常未抛出")
        os.unlink(test_path)
        sys.exit(1)
    except Exception as e:  # 捕获任何异常
        if "未找到匹配的源字符串" in str(e):  # 检查错误信息
            print(f"测试3通过: 捕获到预期异常 - {str(e)}")
        else:
            print(f"测试3失败: 异常类型错误 - {str(e)}")
            os.unlink(test_path)
            sys.exit(1)
    finally:
        os.unlink(test_path)

    # 测试4: 空字符串替换
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt") as tmp:
        test_path = tmp.name
        content = "原始内容"
        tmp.write(content)
        tmp.flush()

    print(f"测试4: 创建测试文件: {test_path}")
    src_block = "原始内容"
    dst_block = ""

    instruction_str = f"""[replace]: {test_path}
[start]
{src_block}
[end]
[start]
{dst_block}
[end]"""

    instructions = ReplaceInstructionParser.parse(instruction_str)
    engine = ReplaceEngine()
    try:
        engine.execute(instructions)
        print("测试4: 替换执行成功")
    except Exception as e:
        print(f"测试4失败: {str(e)}")
        os.unlink(test_path)
        sys.exit(1)

    with open(test_path, "r") as f:
        new_content = f.read()

    if new_content != "":
        print(f"测试4错误: 预期空文件, 实际内容: {new_content}")
        os.unlink(test_path)
        sys.exit(1)

    print("测试4通过!")
    os.unlink(test_path)

    print("=== 所有测试通过 ===")
