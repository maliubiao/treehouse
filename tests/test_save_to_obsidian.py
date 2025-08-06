import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from textwrap import dedent
from typing import Tuple
from unittest.mock import patch

# Add project root to sys.path to allow importing from the parent directory
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from llm_query import save_to_obsidian

# A mock for time.localtime() to ensure deterministic test results
# time.struct_time(tm_year=2023, tm_mon=10, tm_mday=26, tm_hour=12, tm_min=30, tm_sec=5, ...)
MOCK_TIME: time.struct_time = time.struct_time((2023, 10, 26, 12, 30, 5, 3, 299, 0))


class TestSaveToObsidian(unittest.TestCase):
    """Test suite for the save_to_obsidian function."""

    def setUp(self) -> None:
        """Set up a temporary directory and mock time for each test."""
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = self.temp_dir_obj.name
        self.mock_localtime = patch("time.localtime", return_value=MOCK_TIME)
        self.mock_localtime.start()

    def tearDown(self) -> None:
        """Clean up the temporary directory and stop mocks after each test."""
        self.temp_dir_obj.cleanup()
        self.mock_localtime.stop()

    def _get_expected_paths(self) -> Tuple[Path, Path]:
        """Get the expected paths for the note and index files based on mock time."""
        obsidian_root = Path(self.temp_dir)
        date_dir = obsidian_root / "2023-10-26"
        note_file = date_dir / "12-30-5.md"
        index_file = obsidian_root / "2023-10-26-索引.md"
        return note_file, index_file

    def test_basic_conversion_and_file_structure(self) -> None:
        """Test basic code block conversion and correct file/directory creation."""
        content = dedent("""\
            Some text before.
            [start]
            def hello():
                print("hello")
            [end]
            Some text after.
        """)
        save_to_obsidian(self.temp_dir, content)

        note_file, index_file = self._get_expected_paths()

        self.assertTrue(note_file.exists())
        self.assertTrue(index_file.exists())

        expected_note_content = dedent("""\
            ### 回答
            Some text before.
            ```
            def hello():
                print("hello")
            ```
            Some text after.
        """)
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content.strip())

        expected_index_content = "[[2023-10-26/12-30-5.md|12-30-5.md]]\n"
        self.assertEqual(index_file.read_text("utf-8"), expected_index_content)

    def test_multiple_code_blocks(self) -> None:
        """Test correct handling of multiple code blocks in order."""
        content = dedent("""\
            Block 1:
            [start]
            code 1
            [end]
            Block 2:
            [start]
            code 2
            [end]
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            Block 1:
            ```
            code 1
            ```
            Block 2:
            ```
            code 2
            ```
        """)
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content.strip())

    def test_nested_blocks_are_preserved(self) -> None:
        """Test that nested [start]/[end] tags are preserved as text content."""
        content = dedent("""\
            [start]
            outer code
            [start]
            inner content
            [end]
            more outer code
            [end]
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            ```
            outer code
            [start]
            inner content
            [end]
            more outer code
            ```
        """)
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content.strip())

    def test_think_block_formatting(self) -> None:
        """Test the HTML formatting of <think> blocks."""
        content = dedent("""\
            <think>
            This is a thought.
            With multiple lines.
            </think>
            And some code.
            [start]
            print("done")
            [end]
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            <div style="color: #228B22; padding: 10px; border-radius: 5px; margin: 10px 0;">This is a thought.<br>With multiple lines.</div>
            And some code.
            ```
            print("done")
            ```
        """)
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content.strip())

    def test_prompt_and_ask_param_usage(self) -> None:
        """Test the usage of 'prompt' and 'ask_param' arguments."""
        content = "Some content."
        prompt = "What is the meaning of life?"
        ask_param = "philosophy_question"

        save_to_obsidian(self.temp_dir, content, prompt=prompt, ask_param=ask_param)

        note_file, index_file = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            Some content.

            ### 问题

            ````
            What is the meaning of life?
            ````
        """)
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content.strip())

        expected_index_content = "[[2023-10-26/12-30-5.md|philosophy_question]]\n"
        self.assertEqual(index_file.read_text("utf-8"), expected_index_content)

    def test_no_code_blocks(self) -> None:
        """Test behavior with content that has no code blocks."""
        content = "Just simple text. No code blocks here."
        save_to_obsidian(self.temp_dir, content)

        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            Just simple text. No code blocks here.
        """)
        self.assertTrue(note_file.exists())
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content.strip())

    def test_unclosed_block(self) -> None:
        """Test that an unclosed block is treated as plain text."""
        content = "Text with [start] but no end."
        save_to_obsidian(self.temp_dir, content)

        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            Text with [start] but no end.
        """)
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content.strip())

    def test_empty_block(self) -> None:
        """Test that an empty block '[start][end]' is handled correctly."""
        content = dedent("""\
            An empty block:
            [start]
            [end]
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            An empty block:
            ```

            ```
        """)
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content.strip())


if __name__ == "__main__":
    unittest.main()
