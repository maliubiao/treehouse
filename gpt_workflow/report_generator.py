import os
from datetime import datetime
from pathlib import Path
from typing import Dict


class ReportGenerator:
    """
    Generates and saves test failure analysis reports in Markdown format.
    """

    def __init__(self, report_dir: str):
        """
        Initializes the ReportGenerator.

        Args:
            report_dir: The base directory where reports will be saved.
        """
        self.base_dir = Path(report_dir)
        # Ensure the base directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_report(self, test_info: Dict, analysis: str, prompt: str) -> Path:
        """
        Creates a detailed Markdown report for a failed test case and saves it.

        The report is saved in a date-stamped subdirectory of the base_dir.

        Args:
            test_info: A dictionary containing details about the failed test.
            analysis: The AI-generated analysis of the failure.
            prompt: The full prompt used to generate the fix.

        Returns:
            The Path object of the generated report file.
        """
        # 1. Determine directory and filename
        today_str = datetime.now().strftime("%Y-%m-%d")
        report_subdir = self.base_dir / today_str
        report_subdir.mkdir(exist_ok=True)

        test_function = test_info.get("function", "unknown_function").replace(".", "_")
        timestamp_str = datetime.now().strftime("%H%M%S")
        filename = f"{test_function}_{timestamp_str}.md"
        report_path = report_subdir / filename

        # 2. Format the content into Markdown
        markdown_content = self._format_markdown(test_info, analysis, prompt)

        # 3. Write to file
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return report_path

    @staticmethod
    def _format_markdown(test_info: Dict, analysis: str, prompt: str) -> str:
        """
        Formats the collected data into a structured Markdown string.
        """
        traceback = test_info.get("traceback", "No traceback available.")
        # Ensure traceback is formatted as a code block
        if "```" not in traceback:
            traceback = f"```python\n{traceback}\n```"

        content = f"""
# Test Failure Analysis Report

- **Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- **Test Case:** `{test_info.get("function", "N/A")}`
- **File:** `{test_info.get("file_path", "N/A")}:{test_info.get("line", "N/A")}`
- **Issue Type:** {test_info.get("issue_type", "N/A").capitalize()}
- **Error Type:** `{test_info.get("error_type", "N/A")}`

---

## Error Message

> {test_info.get("error_message", "No message available.")}

## Traceback

{traceback}

---

## AI-Generated Analysis

{analysis}

---

## AI Fix Generation Prompt

<details>
<summary>Click to expand the full prompt used for generating the fix</summary>

```
{prompt}
```

</details>
"""
        return content.strip()
