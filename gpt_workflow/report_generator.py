import datetime
from pathlib import Path


class ReportGenerator:
    """
    Generates and saves markdown reports for test fix attempts.
    """

    def __init__(self, reports_dir: str = "reports"):
        """
        Initializes the ReportGenerator.

        Args:
            reports_dir: The directory where reports will be saved.
        """
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(exist_ok=True)

    def _generate_filename(self, test_func_name: str) -> str:
        """
        Generates a unique, descriptive filename for the report.

        Args:
            test_func_name: The name of the test function being fixed.

        Returns:
            A string representing the filename.
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_func_name = "".join(c if c.isalnum() else "_" for c in test_func_name)
        return f"fix_report_{safe_func_name}_{timestamp}.md"

    def create_report(self, test_info: dict, analysis: str, prompt: str) -> Path:
        """
        Creates and saves a markdown report for a fix attempt.

        Args:
            test_info: A dictionary containing details about the failed test.
            analysis: The LLM-generated analysis of the issue.
            prompt: The full prompt sent to the LLM to generate the fix.

        Returns:
            The path to the generated report file.
        """
        filename = self._generate_filename(test_info.get("function", "unknown_test"))
        filepath = self.reports_dir / filename

        report_title = f"# 修复报告: {test_info.get('function', '未知测试')}"

        content = f"""{report_title}

## 问题摘要

- **测试函数**: `{test_info.get("function", "N/A")}`
- **文件**: `{test_info.get("file_path", "N/A")}:{test_info.get("line", "N/A")}`
- **问题类型**: `{test_info.get("issue_type", "N/A").upper()}`
- **错误信息**: `{test_info.get("error_message", "N/A")}`

---

## AI 专家分析

{analysis}

---

## 修复建议 (原始提示词)

以下是用于生成修复方案的完整提示词。

```prompt
{prompt}
```
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return filepath
