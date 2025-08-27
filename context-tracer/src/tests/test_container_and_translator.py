import argparse
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project's source directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
print(sys.path[0])

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tests"))
print(sys.path[0])

from context_tracer.container import (
    DataContainerReader,
    DataContainerWriter,
    EventType,
    FileManager,
    TraceEvent,
)
from context_tracer.tracer import TraceConfig
from context_tracer.translator import Translator
from context_tracer.translator import main as translator_main

from tests.test_py_tracer import BaseTracerTest

# Use a fixed key for reproducible tests
TEST_KEY = b"\xde\xad\xbe\xef" * 4  # 16 bytes
TEST_KEY_HEX = TEST_KEY.hex()


class TestFileManager(unittest.TestCase):
    """Unit tests for the FileManager class."""

    def setUp(self):
        self.fm = FileManager()

    def test_get_id_for_files_and_dynamic_code(self):
        # Test normal file path
        path1_id = self.fm.get_id("/app/main.py")
        self.assertEqual(path1_id, 0)
        self.assertEqual(self.fm.get_id("/app/main.py"), 0)  # Should be cached

        # Test another file path
        path2_id = self.fm.get_id("/app/utils.py")
        self.assertEqual(path2_id, 1)

        # Test dynamic code
        dynamic_code_1 = "print('hello')"
        dynamic_id_1 = self.fm.get_id("<string>", content=dynamic_code_1)
        self.assertEqual(dynamic_id_1, 2)
        self.assertEqual(self.fm._dynamic_code[dynamic_id_1], dynamic_code_1)

        # Test another dynamic code snippet
        dynamic_code_2 = "x = 1"
        dynamic_id_2 = self.fm.get_id("<exec>", content=dynamic_code_2)
        self.assertEqual(dynamic_id_2, 3)

    def test_get_path(self):
        id_main = self.fm.get_id("/app/main.py")
        id_string = self.fm.get_id("<string>", "...")
        self.assertEqual(self.fm.get_path(id_main), "/app/main.py")
        self.assertEqual(self.fm.get_path(id_string), "<string>")
        self.assertIsNone(self.fm.get_path(999))  # Non-existent ID

    def test_get_source_lines_dynamic(self):
        code = "line1\nline2"
        dynamic_id = self.fm.get_id("<dynamic>", content=code)
        self.assertEqual(self.fm.get_source_lines(dynamic_id), ["line1", "line2"])

    def test_get_source_lines_from_file(self):
        # This part requires a temporary file, so we'll do it in a test
        # that inherits from BaseTracerTest if needed, or mock it.
        # Here we'll just mock Path.read_text.
        file_id = self.fm.get_id("/fake/file.py")
        with patch("pathlib.Path.read_text", return_value="a = 1\nb = 2") as mock_read:
            lines = self.fm.get_source_lines(file_id)
            self.assertEqual(lines, ["a = 1", "b = 2"])
            mock_read.assert_called_once_with(encoding="utf-8")

    def test_serialization_deserialization(self):
        self.fm.get_id("/app/main.py")
        self.fm.get_id("<string>", "print(1)")
        serialized_data = self.fm.serialize()
        self.assertIsInstance(serialized_data, bytes)

        new_fm = FileManager.deserialize(serialized_data)
        self.assertEqual(new_fm._file_to_id, self.fm._file_to_id)
        self.assertEqual(new_fm._id_to_file, self.fm._id_to_file)
        self.assertEqual(new_fm._dynamic_code, self.fm._dynamic_code)
        self.assertEqual(new_fm._next_id, self.fm._next_id)


class TestDataContainer(BaseTracerTest):
    """Tests the write/read cycle of the DataContainer."""

    def test_write_read_cycle(self):
        """Test a full write and read cycle to ensure data integrity."""
        container_path = self.test_dir / "test_cycle.bin"
        fm = FileManager()
        writer = DataContainerWriter(container_path, TEST_KEY, fm)

        # Create some events using V3 list-based format
        events: list[TraceEvent] = [
            TraceEvent(
                event_type=EventType.CALL.value,
                timestamp=time.time(),
                thread_id=1,
                frame_id=101,
                file_id=fm.get_id("/app/main.py"),
                lineno=10,
                data=["main", "a=1"],  # [func_name, args_str]
            ),
            TraceEvent(
                event_type=EventType.LINE.value,
                timestamp=time.time() + 0.1,
                thread_id=1,
                frame_id=101,
                file_id=fm.get_id("/app/main.py"),
                lineno=11,
                data=["x = 1", "x = 1", [["x", "1"]]],  # [line_content, raw_line, tracked_vars_list]
            ),
            TraceEvent(
                event_type=EventType.RETURN.value,
                timestamp=time.time() + 0.2,
                thread_id=1,
                frame_id=101,
                file_id=fm.get_id("/app/main.py"),
                lineno=12,
                data=["main", "None", []],  # [func_name, return_value_str, tracked_vars_list]
            ),
        ]

        # Write events
        writer.open()
        for event in events:
            writer.add_event(event)
        writer.close()

        self.assertTrue(container_path.exists())

        # Read back and verify
        reader = DataContainerReader(container_path, TEST_KEY)
        reader.open()

        # Check file manager
        self.assertIsNotNone(reader.file_manager)
        self.assertEqual(reader.file_manager._file_to_id, fm._file_to_id)

        # Check events
        read_events = list(reader)
        self.assertEqual(len(read_events), len(events))
        for original, read in zip(events, read_events):
            self.assertEqual(original, read)
        reader.close()

    def test_read_with_wrong_key(self):
        """Test that reading with an incorrect key fails."""
        container_path = self.test_dir / "wrong_key.bin"
        fm = FileManager()
        writer = DataContainerWriter(container_path, TEST_KEY, fm)
        writer.open()
        writer.close()

        wrong_key = b"\x11" * 16
        reader = DataContainerReader(container_path, wrong_key)
        # Decryption of the header should fail
        with self.assertRaises(ValueError):
            reader.open()


class TestTranslator(BaseTracerTest):
    """Tests for the Translator tool."""

    def setUp(self):
        super().setUp()
        self.container_path = self.test_dir / "sample.bin"
        self.fm = FileManager()
        self.events: list[TraceEvent] = [
            TraceEvent(
                event_type=EventType.CALL.value,
                timestamp=time.time(),
                thread_id=1,
                frame_id=101,
                file_id=self.fm.get_id("/app/main.py"),
                lineno=10,
                data=["main", "a=1"],  # [func_name, args_str]
            ),
            TraceEvent(
                event_type=EventType.LINE.value,
                timestamp=time.time(),
                thread_id=1,
                frame_id=101,
                file_id=self.fm.get_id("/app/main.py"),
                lineno=11,
                data=["x = a", "x = a", [["x", "1"]]],  # [line_content, raw_line, tracked_vars_list]
            ),
            TraceEvent(
                event_type=EventType.RETURN.value,
                timestamp=time.time(),
                thread_id=1,
                frame_id=101,
                file_id=self.fm.get_id("/app/main.py"),
                lineno=12,
                data=["main", "None", []],  # [func_name, return_value_str, tracked_vars_list]
            ),
        ]

        # Create a dummy source file for the translator to read
        source_file = self.test_dir / "main.py"
        source_file.parent.mkdir(exist_ok=True)
        source_file.write_text("...\n" * 9 + "def main(a):\n  x=a\n  return None\n")
        self.fm.get_id(str(source_file.resolve()))  # Use resolved path in FM

        # Overwrite file_id in events to match the real file
        file_id = self.fm.get_id(str(source_file.resolve()))
        # Since NamedTuples are immutable, we need to create new events
        self.events = [
            TraceEvent(
                event_type=event.event_type,
                timestamp=event.timestamp,
                thread_id=event.thread_id,
                frame_id=event.frame_id,
                file_id=file_id,
                lineno=event.lineno,
                data=event.data,
            )
            for event in self.events
        ]

        # Write the container file
        writer = DataContainerWriter(self.container_path, TEST_KEY, self.fm)
        writer.open()
        for event in self.events:
            writer.add_event(event)
        writer.close()

    def test_translate_to_html(self):
        """Test translation from .bin to .html."""
        output_path = self.test_dir / "report.html"
        translator = Translator(self.container_path, TEST_KEY)
        translator.translate_to_html(output_path)

        self.assertTrue(output_path.exists())
        html_content = output_path.read_text("utf-8")

        # Check for key content
        self.assertIn("Trace Report for report.html", html_content)
        self.assertIn("main(a=1)", html_content)
        self.assertIn("→&nbsp;None", html_content)

        # Check that tracked variables are stored in JavaScript data
        self.assertIn('"x": "1"', html_content)  # From tracked_vars in JavaScript data
        self.assertIn("window.lineComment", html_content)

    def test_translate_to_text(self):
        """Test translation from .bin to .log."""
        output_path = self.test_dir / "trace.log"
        translator = Translator(self.container_path, TEST_KEY)
        translator.translate_to_text(output_path)

        self.assertTrue(output_path.exists())
        text_content = output_path.read_text("utf-8")

        # Check for key content
        self.assertIn("CALL -> main(a=1)", text_content)
        self.assertIn("LINE ->", text_content)
        self.assertIn("[vars: {'x': '1'}]", text_content)
        self.assertIn("RETURN <- main -> None", text_content)

    @patch("argparse._sys")
    def test_translator_cli(self, mock_sys):
        """Test the command-line interface of the translator."""
        output_path_html = self.test_dir / "cli_report.html"
        mock_sys.argv = [
            "translator.py",
            str(self.container_path),
            "--key",
            TEST_KEY_HEX,
            "--format",
            "html",
            "--output",
            str(output_path_html),
        ]

        translator_main()

        self.assertTrue(output_path_html.exists())
        self.assertIn("main(a=1)", output_path_html.read_text("utf-8"))

    @patch("argparse._sys")
    @patch("sys.exit")
    def test_translator_cli_invalid_key(self, mock_exit, mock_sys):
        """Test CLI with an invalid key."""
        mock_sys.argv = [
            "translator.py",
            str(self.container_path),
            "--key",
            "invalidhex",
        ]
        translator_main()
        mock_exit.assert_called_with(1)


if __name__ == "__main__":
    unittest.main()
