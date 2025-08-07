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
        date_dir = obsidian_root / f"{MOCK_TIME.tm_year}-{MOCK_TIME.tm_mon:02d}-{MOCK_TIME.tm_mday:02d}"
        note_file = date_dir / f"{MOCK_TIME.tm_hour:02d}-{MOCK_TIME.tm_min:02d}-{MOCK_TIME.tm_sec:02d}.md"
        index_file = obsidian_root / f"{MOCK_TIME.tm_year}-{MOCK_TIME.tm_mon:02d}-{MOCK_TIME.tm_mday:02d}-索引.md"
        return note_file, index_file

    def test_created_file_formatting(self) -> None:
        """Test formatting for [created file] instruction."""
        content = dedent("""\
            [created file]: /path/to/new/file.py
            [start]
            def main():
                print("Hello")
            [end]
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, index_file = self._get_expected_paths()

        self.assertTrue(note_file.exists())
        self.assertTrue(index_file.exists())

        expected_note_content = dedent("""\
            ### 回答

            ### ✨ Created File: `/path/to/new/file.py`

            ```python
            def main():
                print("Hello")
            ```
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

        expected_index_content = "- [[2023-10-26/12-30-05.md|12-30-05.md]]\n"
        self.assertEqual(index_file.read_text("utf-8"), expected_index_content)

    def test_overwrite_file_formatting(self) -> None:
        """Test formatting for [overwrite whole file] instruction."""
        content = dedent("""\
            [overwrite whole file]: /path/to/existing/file.js
            [start]
            console.log("overwritten");
            [end]
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答

            ### 🔄 Overwrote File: `/path/to/existing/file.js`

            ```js
            console.log("overwritten");
            ```
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

    def test_replace_formatting(self) -> None:
        """Test formatting for [replace] instruction."""
        content = dedent("""\
            [replace]: /path/to/replace.txt
            [start]
            old line
            [end]
            [start]
            new line
            [end]
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答

            ### 🔁 Replace in File: `/path/to/replace.txt`

            #### --- From

            ```diff

            - old line
            ```

            #### +++ To

            ```
            new line
            ```
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

    def test_think_block_formatting(self) -> None:
        """Test the formatting of <think> blocks."""
        content = dedent("""\
            <think>
            This is a thought.
            With multiple lines.
            </think>
            And some other text.
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答

            > ### 🤔 AI's Thought Process
            > This is a thought.
            > With multiple lines.

            And some other text.
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

    def test_git_commit_message_formatting(self) -> None:
        """Test formatting for [git commit message] instruction."""
        content = dedent("""\
            [git commit message]
            [start]
            feat: improve obsidian formatting
            - Add tests for new instruction types.
            [end]
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答

            ### 📝 Git Commit Message

            ```
            feat: improve obsidian formatting
            - Add tests for new instruction types.
            ```
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

    def test_nested_blocks_are_preserved(self) -> None:
        """Test that nested [start]/[end] tags are preserved inside a content block."""
        content = dedent("""\
            [created file]: /path/to/nested.txt
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

            ### ✨ Created File: `/path/to/nested.txt`

            ```
            outer code
            [start]
            inner content
            [end]
            more outer code
            ```
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

    def test_mixed_instructions(self) -> None:
        """Test a mix of instructions are handled correctly."""
        content = dedent("""\
            Here is the plan.
            <think>
            First, I will create a file.
            Then, I will replace content in another.
            </think>
            Okay, let's do it.
            [created file]: new.py
            [start]
            print("new")
            [end]
            Some explanatory text.
            [replace]: old.txt
            [start]
            old
            [end]
            [start]
            new
            [end]
            Final text.
        """)
        save_to_obsidian(self.temp_dir, content)
        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            Here is the plan.

            > ### 🤔 AI's Thought Process
            > First, I will create a file.
            > Then, I will replace content in another.

            Okay, let's do it.

            ### ✨ Created File: `new.py`

            ```python
            print("new")
            ```

            Some explanatory text.

            ### 🔁 Replace in File: `old.txt`

            #### --- From

            ```diff

            - old
            ```

            #### +++ To

            ```
            new
            ```

            Final text.
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

    def test_prompt_and_ask_param_usage(self) -> None:
        """Test the usage of 'prompt' and 'ask_param' arguments."""
        content = "Some content without instructions."
        prompt = "What is the meaning of life?"
        ask_param = "philosophy_question"

        save_to_obsidian(self.temp_dir, content, prompt=prompt, ask_param=ask_param)

        note_file, index_file = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            Some content without instructions.

            ### 问题

            ```
            What is the meaning of life?
            ```
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

        expected_index_content = "- [[2023-10-26/12-30-05.md|philosophy_question]]\n"
        self.assertEqual(index_file.read_text("utf-8"), expected_index_content)

    def test_plain_text(self) -> None:
        """Test behavior with content that has no instructions."""
        content = "Just simple text. No instructions here."
        save_to_obsidian(self.temp_dir, content)

        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            Just simple text. No instructions here.
            """).strip()
        self.assertTrue(note_file.exists())
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

    def test_unrecognized_instruction_is_plain_text(self) -> None:
        """Test that an instruction not in the recognized list is treated as plain text."""
        content = "Text with [start] but no end."
        save_to_obsidian(self.temp_dir, content)

        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答
            Text with [start] but no end.
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)

    def test_unclosed_block(self) -> None:
        """Test that an unclosed block is consumed to the end of the content."""
        content = "[created file]: /foo\n[start]\ncontent"
        save_to_obsidian(self.temp_dir, content)

        note_file, _ = self._get_expected_paths()

        expected_note_content = dedent("""\
            ### 回答

            ### ✨ Created File: `/foo`

            ```
            content
            ```
            """).strip()
        self.assertEqual(note_file.read_text("utf-8").strip(), expected_note_content)


if __name__ == "__main__":
    unittest.main()
