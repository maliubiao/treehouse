import datetime
import os
import re


class ChangelogMarkdown:
    """
    用一个.changelog.md 记录文件的内容
    每个change log有desc, 有代码的diff string, use ```quote
    add desc, diff
    recent -> latest 3 changes and git head, return message should wrapper in [change log start]...[change log end]
    load -> parse md file, read sections, map to change log entry
    autosave feature, save to a valid markdown format
    """

    def __init__(self, file_path=".changelog.md"):
        self.file_path = file_path
        self.entries = []
        self._load_existing()

    def add_entry(self, description, diff):
        """添加新的变更记录"""
        entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": description,
            "diff": diff,
        }
        self.entries.append(entry)
        self._save()

    def use_diff(self, text, diff):
        """
        从get_patch_prompt_output格式的文本中提取描述和差异

        参数:
            text: 包含[change log message start]...的文本
            diff: 差异内容
        """
        desc_match = re.search(r"\[change log message start\](.*?)\[change log message end\]", text, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else "No description provided"
        self.add_entry(description, diff)

    def get_recent(self, count=3):
        """获取最近的变更记录"""
        recent = self.entries[-count:] if len(self.entries) > count else self.entries.copy()
        return f"[change log start]\n{self._format_entries(recent)}\n[change log end]"

    def _load_existing(self):
        """加载现有的变更记录"""
        if os.path.exists(self.file_path):
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read()
                self._parse_markdown(content)

    def _parse_markdown(self, content):
        """解析markdown格式的变更记录"""
        pattern = r"## Date (.*?)\n### Description\n(.*?)\n\n### Diff\n```diff\n(.*?)\n```"
        matches = re.findall(pattern, content, re.DOTALL)
        for timestamp, desc, diff in matches:
            self.entries.append({"timestamp": timestamp, "description": desc.strip(), "diff": diff.strip()})

    def _save(self):
        """保存变更记录到文件"""
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(self._generate_markdown())

    def _generate_markdown(self):
        """生成markdown格式的内容"""
        output = []
        for entry in self.entries:
            output.append(f"## Date {entry['timestamp']}\n")
            output.append("### Description\n")
            output.append(f"{entry['description']}\n\n")
            output.append("### Diff\n```diff\n")
            output.append(f"{entry['diff']}\n")
            output.append("```\n\n")
        return "".join(output)

    def _format_entries(self, entries):
        """格式化条目用于输出"""
        return "\n".join(
            f"Timestamp: {e['timestamp']}\n" f"Description: {e['description']}\n" f"Diff:\n{e['diff']}\n"
            for e in entries
        )
