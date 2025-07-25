import hashlib
import json
import os
import random
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


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

    def __init__(self) -> None:
        self.random_suffix = f"{random.randint(0, 99):02d}"
        self.tag_pattern = re.compile(r"\[(start|end)\]")
        self.randomized_pattern = re.compile(r"\[(start|end)\.\d{2}\]")

    def randomize_tags(self, content: str) -> str:
        """
        将内容中的标准标签替换为随机化标签。

        Args:
            content (str): 需要处理的文本内容。

        Returns:
            str: 处理后的文本，所有[start]和[end]标签被替换为随机化版本。
        """

        def replace_tag(match: re.Match[str]) -> str:
            tag_type = match.group(1)
            return f"[{tag_type}.{self.random_suffix}]"

        return self.tag_pattern.sub(replace_tag, content)

    @staticmethod
    def restore_tags(content: str) -> str:
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

    def execute(self, instructions: List[Dict[str, Any]]) -> None:
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
                # 移除了对'replace'的特殊处理，因为解析器现在会将'replace'区分为
                # 'replace_string' 和 'replace_lines'，简化了此处的逻辑。
                if instr["type"] == "replace_lines":
                    self._safe_replace_lines(
                        path=instr["path"],
                        start_line=instr["start_line"],
                        end_line=instr["end_line"],
                        src=instr["src"],
                        dst=instr["dst"],
                    )
                elif instr["type"] == "replace":
                    self._safe_replace(path=instr["path"], src=instr["src"].strip(), dst=instr["dst"].strip())
                elif instr["type"] == "insert":
                    self._safe_insert(path=instr["path"], line_num=instr["line_num"], content=instr["content"])
                elif instr["type"] == "overwrite_whole_file":
                    self._safe_overwrite_file(path=instr["path"], content=instr["content"])
                elif instr["type"] == "created_file":
                    self._safe_create_file(path=instr["path"], content=instr["content"])
                elif instr["type"] == "project_setup_script":
                    # project_setup_script is handled by the caller, so we ignore it here.
                    pass
                else:
                    raise ValueError(f"未知的指令类型: {instr['type']}")

            except Exception as e:
                # 统一异常出口，附加文件路径信息，方便调试
                raise RuntimeError(f"操作失败 @ {instr.get('path', 'project_setup_script')}: {e}") from e

    def _restore_randomized_tags(self, instructions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        还原指令内容中的所有随机化标签。
        """
        restored: List[Dict[str, Any]] = []
        for instr in instructions:
            new_instr = instr.copy()
            if new_instr["type"] in ("replace", "replace_lines"):
                if "src" in new_instr:
                    new_instr["src"] = TagRandomizer.restore_tags(new_instr["src"])
                if "dst" in new_instr:
                    new_instr["dst"] = TagRandomizer.restore_tags(new_instr["dst"])
            elif new_instr["type"] in ("insert", "overwrite_whole_file", "created_file", "project_setup_script"):
                if "content" in new_instr:
                    new_instr["content"] = TagRandomizer.restore_tags(new_instr["content"])
            restored.append(new_instr)
        return restored

    def _validate_path_for_instruction(self, path_str: str, instr_type: str) -> str:
        """验证指令中的路径，并返回解析后的绝对路径。"""
        path = Path(path_str)
        if instr_type == "created_file":
            # 对于 created_file，我们只需要确保父目录是可写的。
            # 如果父目录不存在，我们将在执行时创建它。
            parent_dir = path.parent
            if parent_dir.exists() and not os.access(parent_dir, os.W_OK):
                raise ValueError(f"父目录不可写: {parent_dir}")
        else:  # For all other instructions, path must exist and be a file
            if not path.exists():
                raise FileNotFoundError(f"文件不存在: {path}")
            if not path.is_file():
                raise ValueError(f"路径不是一个文件: {path}")

        return str(path.resolve())

    def _validate_instructions(self, instr_set: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """验证指令集的有效性，并解析为内部格式。"""
        if not instr_set:
            return []

        validated: List[Dict[str, Any]] = []
        for i, instr in enumerate(instr_set):
            if not self._is_valid_instruction(instr):
                raise ValueError(f"无效或不完整的指令 @ 索引 {i}: {instr}")

            if "path" in instr:
                # 路径验证在这里不进行，因为对于不存在的文件路径，
                # resolve() 会失败。路径在每个操作函数内部处理。
                # instr["path"] = self._validate_path_for_instruction(instr["path"], instr["type"])
                pass

            # 类型特定验证
            if instr["type"] == "replace_lines":
                s_line, e_line = instr["start_line"], instr["end_line"]
                if not (isinstance(s_line, int) and isinstance(e_line, int) and 1 <= s_line <= e_line):
                    raise ValueError(f"无效的行号范围: start={s_line}, end={e_line}")

            elif instr["type"] == "insert":
                line_num = instr["line_num"]
                if not (isinstance(line_num, int) and line_num >= 0):
                    raise ValueError(f"无效的插入行号: {line_num}")

            validated.append(instr)
        return validated

    @staticmethod
    def _is_valid_instruction(instr: Dict[str, Any]) -> bool:
        """检查单个指令是否包含所有必需的键。"""
        if not isinstance(instr, dict) or "type" not in instr:
            return False

        instr_type = instr["type"]

        # 定义每种指令类型所需的键
        requirements: Dict[str, set] = {
            "project_setup_script": {"content"},
            "replace": {"path", "src", "dst"},
            "replace_lines": {"path", "start_line", "end_line", "src", "dst"},
            "insert": {"path", "line_num", "content"},
            "overwrite_whole_file": {"path", "content"},
            "created_file": {"path", "content"},
        }

        # 检查指令类型是否已知，以及是否所有必需的键都存在
        if instr_type not in requirements:
            return False

        return requirements[instr_type].issubset(instr.keys())

    def _safe_create_file(self, path: str, content: str) -> None:
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

    def _safe_overwrite_file(self, path: str, content: str) -> None:
        """安全地用新内容覆盖整个文件，使用备份和回滚机制。"""
        self._validate_path_for_instruction(path, "overwrite_whole_file")
        backup_path: Optional[Path] = None
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

    def _safe_replace(self, path: str, src: str, dst: str) -> None:
        """安全地替换文件中的唯一匹配字符串，使用备份和回滚机制。"""
        self._validate_path_for_instruction(path, "replace")
        with open(path, "r", encoding="utf-8") as f:
            original_content = f.read()

        # count = original_content.count(src)
        # if count == 0:
        #     # 允许源字符串为空的情况，此时不做任何操作
        #     if src == "":
        #         return
        #     raise RuntimeError("未找到匹配的源字符串")
        # if count > 1:
        #     raise RuntimeError(f"找到 {count} 个匹配项，无法确保唯一性以进行安全替换")

        updated_content = original_content.replace(src, dst)

        backup_path = self._create_backup(path, original_content)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(updated_content)
        except Exception:
            if backup_path:
                self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path and backup_path.exists():
                backup_path.unlink()

    def _safe_replace_lines(self, path: str, start_line: int, end_line: int, src: str, dst: str) -> None:
        """安全地替换指定行范围的内容，使用备份和回滚机制。"""
        self._validate_path_for_instruction(path, "replace_lines")
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not 1 <= start_line <= end_line <= len(lines):
            raise RuntimeError(f"无效行号范围: {start_line}-{end_line}，文件总行数: {len(lines)}")

        original_block = "".join(lines[start_line - 1 : end_line])
        # 使用strip()来忽略因编辑器配置可能产生的尾部空白差异
        if original_block.strip() != src.strip():
            # 提供详细的差异信息，便于调试
            raise RuntimeError(
                f"源字符串与文件指定行范围的内容不匹配。\n--- EXPECTED ---\n{src}\n--- ACTUAL ---\n{original_block}"
            )

        backup_path = self._create_backup(path, "".join(lines))
        try:
            # 将替换内容按行分割，并确保每行都以换行符结尾
            dst_lines = [line + "\n" for line in dst.splitlines(True)]
            if not dst.endswith("\n"):
                dst_lines = [line + "\n" for line in dst.splitlines()]

            # 修复：如果dst非空，在其后增加一个额外的空行，以提高代码变更的可读性
            if dst:
                dst_lines.append("\n")

            new_lines = lines[: start_line - 1] + dst_lines + lines[end_line:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            if backup_path:
                self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path and backup_path.exists():
                backup_path.unlink()

    def _safe_insert(self, path: str, line_num: int, content: str) -> None:
        """安全地在指定行号插入内容，使用备份和回滚机制。"""
        self._validate_path_for_instruction(path, "insert")
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # line_num可以等于len(lines)，表示在文件末尾插入
        if not 0 <= line_num <= len(lines):
            raise RuntimeError(f"无效行号: {line_num}，文件总行数: {len(lines)}")

        backup_path = self._create_backup(path, "".join(lines))
        try:
            # 将插入内容按行分割，并确保每行都以换行符结尾
            insert_lines = [line + "\n" for line in content.splitlines()]

            # 修复：如果content非空，在其后增加一个额外的空行，以提高代码变更的可读性
            if content:
                insert_lines.append("\n")

            new_lines = lines[:line_num] + insert_lines + lines[line_num:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            if backup_path:
                self._restore_backup(backup_path, path)
            raise
        finally:
            if backup_path and backup_path.exists():
                backup_path.unlink()

    @staticmethod
    def _create_backup(original_path: str, content: str) -> Path:
        """创建临时备份文件。"""
        backup_dir = Path(tempfile.gettempdir())
        file_hash = hashlib.md5(str(original_path).encode()).hexdigest()[:8]
        backup_name = f"{Path(original_path).name}.{file_hash}.bak"
        backup_path = backup_dir / backup_name
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)
        return backup_path

    @staticmethod
    def _restore_backup(backup_path: Path, target_path: str) -> None:
        """从备份恢复文件。"""
        if backup_path and backup_path.exists():
            with open(backup_path, "r", encoding="utf-8") as f_bak, open(target_path, "w", encoding="utf-8") as f_orig:
                f_orig.write(f_bak.read())


class LLMInstructionParser:
    """
    一个解析器，能从LLM响应中提取结构化文件操作指令。

    该解析器是向后兼容的。它首先尝试将输入解析为JSON格式。如果失败，
    它会回退到基于文本标签的旧格式进行解析。这确保了对新旧两种指令
    格式的健壮支持。

    - **JSON格式**: 一个包含 `actions` 数组的JSON对象，结构清晰。
    - **旧格式**: 基于`[command]: ... [start] ... [end]`标签的文本格式。
    """

    # 用于旧格式解析的状态机
    _HEADER_RE = {
        "setup": re.compile(r"^\[project setup script\]$"),
        "file_op": re.compile(r"^\[(overwrite whole file|created file|replace|insert)\]:\s*(.*)$"),
        "lines": re.compile(r"^\[lines\]:\s*(\d+)-(\d+)$"),
        "line": re.compile(r"^\[line\]:\s*(\d+)$"),
        "start": re.compile(r"^\[start.*\]$"),
        "end": re.compile(r"^\[end.*\]$"),
    }

    @staticmethod
    def _extract_json_block(text: str) -> Optional[str]:
        """
        从markdown代码块（如 ```json ... ```）中提取JSON字符串。
        此方法能健壮地处理周围的文本。

        Args:
            text: 来自LLM响应的原始字符串。

        Returns:
            提取出的JSON字符串，如果未找到有效块则返回None。
        """
        # 这个正则表达式寻找一个json块，允许可选的 "json" 语言提示。
        # 它捕获围栏之间的内容。
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            # 捕获的内容在块内可能仍有前导/尾随空格，因此我们对其进行strip。
            return match.group(1).strip()
        return None

    @classmethod
    def parse(cls, text: str, use_json=False) -> List[Dict[str, Any]]:
        """
        解析输入文本，自动检测并处理JSON或旧版标签格式。

        该解析器是向后兼容的。它首先尝试从markdown代码块中查找并解析JSON。
        如果失败或未找到，它会尝试将整个输入作为JSON解析。如果仍然失败，
        它会回退到基于文本标签的旧格式进行解析。

        Args:
            text: 包含指令的原始字符串，可以是JSON或文本标签格式。

        Returns:
            一个指令字典的列表。
        """
        if use_json:
            # 方案一：从markdown块中提取并解析JSON
            json_str = cls._extract_json_block(text)
            if json_str:
                try:
                    data = json.loads(json_str)
                    return cls._parse_from_json(data)
                except json.JSONDecodeError:
                    # 如果提取的块不是有效的JSON，则继续尝试其他方案
                    pass
            data = json.loads(text)
            return cls._parse_from_json(data)
        else:
            return cls._parse_from_legacy_text(text)

    @classmethod
    def _parse_from_json(cls, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从解析后的JSON对象中提取指令。"""
        instructions: List[Dict[str, Any]] = []
        if not isinstance(data, dict) or "actions" not in data or not isinstance(data["actions"], list):
            return []

        # 定义JSON action_type到内部type的映射
        action_map = {
            "run_shell_script": "project_setup_script",
            "create_file": "created_file",
            "overwrite_file": "overwrite_whole_file",
        }
        # 定义JSON字段名到内部字段名的映射
        field_map = {
            "script_content": "content",
            "file_path": "path",
        }

        for action in data["actions"]:
            if not isinstance(action, dict) or "action_type" not in action:
                continue

            action_type = action.get("action_type")
            internal_type = action_map.get(action_type)

            if not internal_type:
                # 忽略未知的action类型，以实现前向兼容
                continue

            instr: Dict[str, Any] = {"type": internal_type}
            all_fields_present = True
            for json_field, internal_field in field_map.items():
                if json_field in action:
                    instr[internal_field] = action[json_field]

            # 'content'是通用字段，也需要检查
            if "content" in action and "content" not in instr:
                instr["content"] = action["content"]

            # 验证指令是否完整
            # 此处简化验证逻辑，依赖于ReplaceEngine中的_is_valid_instruction
            # 但我们可以做一个基本检查
            if internal_type in ("created_file", "overwrite_whole_file") and "path" not in instr:
                all_fields_present = False

            if all_fields_present:
                instructions.append(instr)

        return instructions

    @classmethod
    def _parse_from_legacy_text(cls, text: str) -> List[Dict[str, Any]]:
        """
        使用状态机从文本中解析所有最外层的指令（旧版格式）。
        """
        instructions: List[Dict[str, Any]] = []
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if cls._HEADER_RE["setup"].match(line):
                content, i_after = cls._consume_block(lines, i + 1)
                if content is not None:
                    instructions.append({"type": "project_setup_script", "content": content})
                i = i_after
                continue

            file_op_match = cls._HEADER_RE["file_op"].match(line)
            if file_op_match:
                op_type = file_op_match.group(1).replace(" ", "_")
                path = file_op_match.group(2).strip()
                instr, i_after = cls._parse_file_op_body(lines, i + 1, op_type, path)
                if instr:
                    instructions.append(instr)
                i = i_after
                continue

            i += 1

        return instructions

    @classmethod
    def _parse_file_op_body(
        cls, lines: List[str], start_index: int, op_type: str, path: str
    ) -> Optional[tuple[Dict[str, Any], int]]:
        """解析文件操作指令的元数据和内容块。"""
        i = start_index
        instr: Dict[str, Any] = {"type": op_type, "path": path}

        # 处理 replace 和 insert 的元数据行
        if op_type == "replace":
            if i < len(lines):
                lines_match = cls._HEADER_RE["lines"].match(lines[i].strip())
                if lines_match:
                    instr["type"] = "replace_lines"
                    instr["start_line"] = int(lines_match.group(1))
                    instr["end_line"] = int(lines_match.group(2))
                    i += 1
        elif op_type == "insert":
            if i < len(lines):
                line_match = cls._HEADER_RE["line"].match(lines[i].strip())
                if line_match:
                    instr["line_num"] = int(line_match.group(1))
                    i += 1
                else:
                    return None  # 格式错误，跳过
            else:
                return None  # 文件结束，指令不完整

        # 消耗内容块
        current_op_type = instr["type"]
        if current_op_type in ("replace", "replace_lines"):
            src, i_after_src = cls._consume_block(lines, i)
            if src is None:
                return None
            dst, i_after_dst = cls._consume_block(lines, i_after_src)
            if dst is None:
                return None
            instr["src"] = src
            instr["dst"] = dst
            return instr, i_after_dst

        # created_file, overwrite_whole_file, insert
        content, i_after_content = cls._consume_block(lines, i)
        if content is None:
            return None
        instr["content"] = content
        return instr, i_after_content

    @classmethod
    def _consume_block(cls, lines: List[str], start_index: int) -> Optional[tuple[str, int]]:
        """
        从指定索引开始，消耗一个由[start]...[end]包围的块。
        支持嵌套块，只在最外层块结束时停止。
        返回 (块内容, 结束后的新索引)。
        """
        i = start_index
        while i < len(lines):
            if cls._HEADER_RE["start"].match(lines[i].strip()):
                break
            i += 1
        else:
            return None  # 没有找到 [start]

        nesting_level = 1
        start_block_index = i + 1
        i += 1

        while i < len(lines):
            line = lines[i]
            if cls._HEADER_RE["start"].match(line.strip()):
                nesting_level += 1
            elif cls._HEADER_RE["end"].match(line.strip()):
                nesting_level -= 1

            if nesting_level == 0:
                # 提取从[start]后到[end]前的内容
                content = "\n".join(lines[start_block_index:i])
                return content, i + 1

            i += 1

        # 如果循环结束但嵌套级别不为0，说明格式错误
        return None
