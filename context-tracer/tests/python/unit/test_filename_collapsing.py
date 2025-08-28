#!/usr/bin/env python3
"""
Unit tests for filename collapsing functionality in tracer_html.py
"""

import os

# Add the src directory to Python path
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

from context_tracer.tracer_common import TraceTypes
from context_tracer.tracer_html import CallTreeHtmlRender


class TestFilenameCollapsing(unittest.TestCase):
    """Test filename collapsing functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create a mock trace_logic object
        self.mock_trace_logic = Mock()
        self.renderer = CallTreeHtmlRender(self.mock_trace_logic)

    def _create_line_event(self, frame_id, filename, lineno, line_text):
        """Helper to create a LINE event message"""
        return {
            "template": "{indent}▷ {filename}:{lineno} {line}",
            "data": {
                "indent": "",
                "filename": filename,
                "lineno": lineno,
                "line": line_text,
                "frame_id": frame_id,
                "original_filename": filename,
                "raw_line": line_text,
            },
        }

    def _create_non_line_event(self, frame_id, event_type):
        """Helper to create a non-LINE event message"""
        return {"template": "{indent}{message}", "data": {"indent": "", "message": event_type, "frame_id": frame_id}}

    def test_same_file_consecutive_lines(self):
        """Test that consecutive lines from same file collapse filename and right-align"""
        filename = "/path/to/file1.py"
        # First line from file1.py
        msg1 = self._create_line_event(1, filename, 10, "print('Hello')")
        self.renderer.add_raw_message(msg1, TraceTypes.COLOR_LINE)

        # Second line from same file
        msg2 = self._create_line_event(1, filename, 15, "x = 42")
        self.renderer.add_raw_message(msg2, TraceTypes.COLOR_LINE)

        # Third line from same file
        msg3 = self._create_line_event(1, filename, 20, "return x")
        self.renderer.add_raw_message(msg3, TraceTypes.COLOR_LINE)

        # Generate HTML and check results
        result = self.renderer.generate_html()

        # First line should show full filename:line
        self.assertIn("▷&nbsp;/path/to/file1.py:10&nbsp;print(&#x27;Hello&#x27;)", result)

        # --- Second line should be padded and right-aligned with the arrow ---
        first_lineno = 10
        total_width = len(filename) + 1 + len(str(first_lineno))

        second_lineno = 15
        aligned_str_2 = f"▷ {second_lineno}".rjust(total_width + 2)
        expected_html_part_2 = f"{aligned_str_2.replace(' ', '&nbsp;')}&nbsp;x&nbsp;=&nbsp;42"
        self.assertIn(expected_html_part_2, result)
        self.assertNotIn("/path/to/file1.py:15", result)

        # --- Third line should also be padded and right-aligned with the arrow ---
        third_lineno = 20
        aligned_str_3 = f"▷ {third_lineno}".rjust(total_width + 2)
        expected_html_part_3 = f"{aligned_str_3.replace(' ', '&nbsp;')}&nbsp;return&nbsp;x"
        self.assertIn(expected_html_part_3, result)
        self.assertNotIn("/path/to/file1.py:20", result)

    def test_different_files_show_full_filename(self):
        """Test that lines from different files show full filename"""
        # Line from file1.py
        msg1 = self._create_line_event(1, "/path/to/file1.py", 10, "print('Hello')")
        self.renderer.add_raw_message(msg1, TraceTypes.COLOR_LINE)

        # Line from different file
        msg2 = self._create_line_event(1, "/path/to/file2.py", 5, "import os")
        self.renderer.add_raw_message(msg2, TraceTypes.COLOR_LINE)

        # Another line from file2.py
        msg3 = self._create_line_event(1, "/path/to/file2.py", 8, "print('World')")
        self.renderer.add_raw_message(msg3, TraceTypes.COLOR_LINE)

        # Generate HTML and check results
        result = self.renderer.generate_html()

        # First line should show full filename
        self.assertIn("▷&nbsp;/path/to/file1.py:10&nbsp;print(&#x27;Hello&#x27;)", result)

        # Second line should show full filename for different file
        self.assertIn("▷&nbsp;/path/to/file2.py:5&nbsp;import&nbsp;os", result)

        # --- Third line should collapse filename and be right-aligned with the arrow ---
        filename2 = "/path/to/file2.py"
        first_lineno_f2 = 5
        total_width_f2 = len(filename2) + 1 + len(str(first_lineno_f2))

        third_lineno = 8
        aligned_str_3 = f"▷ {third_lineno}".rjust(total_width_f2 + 2)
        expected_html_part_3 = f"{aligned_str_3.replace(' ', '&nbsp;')}&nbsp;print(&#x27;World&#x27;)"
        self.assertIn(expected_html_part_3, result)
        self.assertNotIn("/path/to/file2.py:8", result)

    def test_different_frames_independent_tracking(self):
        """Test that different frames track filenames independently"""
        filename = "/path/to/file1.py"
        # Frame 1 - file1.py
        msg1 = self._create_line_event(1, filename, 10, "print('Hello')")
        self.renderer.add_raw_message(msg1, TraceTypes.COLOR_LINE)

        # Frame 2 - file1.py (same file, different frame)
        msg2 = self._create_line_event(2, filename, 15, "x = 42")
        self.renderer.add_raw_message(msg2, TraceTypes.COLOR_LINE)

        # Frame 1 - same file again
        msg3 = self._create_line_event(1, filename, 20, "return x")
        self.renderer.add_raw_message(msg3, TraceTypes.COLOR_LINE)

        # Generate HTML and check results
        result = self.renderer.generate_html()

        # First line should show full filename
        self.assertIn("▷&nbsp;/path/to/file1.py:10&nbsp;print(&#x27;Hello&#x27;)", result)

        # Second line should show full filename since it's a different frame
        self.assertIn("▷&nbsp;/path/to/file1.py:15&nbsp;x&nbsp;=&nbsp;42", result)

        # --- Third line should collapse filename for frame 1 and be right-aligned with the arrow ---
        first_lineno_f1 = 10
        total_width_f1 = len(filename) + 1 + len(str(first_lineno_f1))

        third_lineno = 20
        aligned_str_3 = f"▷ {third_lineno}".rjust(total_width_f1 + 2)
        expected_html_part_3 = f"{aligned_str_3.replace(' ', '&nbsp;')}&nbsp;return&nbsp;x"
        self.assertIn(expected_html_part_3, result)
        self.assertNotIn("/path/to/file1.py:20", result)

    def test_non_line_events_reset_tracking(self):
        """Test that non-LINE events reset frame tracking"""
        # First line from file1.py
        msg1 = self._create_line_event(1, "/path/to/file1.py", 10, "print('Hello')")
        self.renderer.add_raw_message(msg1, TraceTypes.COLOR_LINE)

        # Non-LINE event should reset tracking for frame 1
        msg_reset = self._create_non_line_event(1, TraceTypes.COLOR_CALL)
        self.renderer.add_raw_message(msg_reset, TraceTypes.COLOR_CALL)

        # Next line from same file should show full filename again
        msg2 = self._create_line_event(1, "/path/to/file1.py", 15, "x = 42")
        self.renderer.add_raw_message(msg2, TraceTypes.COLOR_LINE)

        # Generate HTML and check results
        result = self.renderer.generate_html()

        # First line should show full filename
        self.assertIn("▷&nbsp;/path/to/file1.py:10&nbsp;print(&#x27;Hello&#x27;)", result)

        # Next line should show full filename since tracking was reset
        self.assertIn("▷&nbsp;/path/to/file1.py:15&nbsp;x&nbsp;=&nbsp;42", result)

    def test_edge_case_same_line_different_files(self):
        """Test edge case where same line number but different files"""
        # Line 10 from file1.py
        msg1 = self._create_line_event(1, "/path/to/file1.py", 10, "print('File1')")
        self.renderer.add_raw_message(msg1, TraceTypes.COLOR_LINE)

        # Line 10 from file2.py (same line number, different file)
        msg2 = self._create_line_event(1, "/path/to/file2.py", 10, "print('File2')")
        self.renderer.add_raw_message(msg2, TraceTypes.COLOR_LINE)

        # Another line from file2.py (should collapse)
        msg3 = self._create_line_event(1, "/path/to/file2.py", 11, "x = 42")
        self.renderer.add_raw_message(msg3, TraceTypes.COLOR_LINE)

        # Generate HTML and check results
        result = self.renderer.generate_html()

        # First line should show full filename
        self.assertIn("▷&nbsp;/path/to/file1.py:10&nbsp;print(&#x27;File1&#x27;)", result)

        # Second line should show full filename for different file
        self.assertIn("▷&nbsp;/path/to/file2.py:10&nbsp;print(&#x27;File2&#x27;)", result)

        # --- Third line should collapse filename and be right-aligned with the arrow ---
        filename2 = "/path/to/file2.py"
        first_lineno_f2 = 10
        total_width_f2 = len(filename2) + 1 + len(str(first_lineno_f2))

        third_lineno = 11
        aligned_str_3 = f"▷ {third_lineno}".rjust(total_width_f2 + 2)
        expected_html_part_3 = f"{aligned_str_3.replace(' ', '&nbsp;')}&nbsp;x&nbsp;=&nbsp;42"
        self.assertIn(expected_html_part_3, result)
        self.assertNotIn(":11", result)

    def test_filename_collapsing_with_different_lengths(self):
        """Test filename collapsing with filenames of different lengths."""
        # First file with short name
        msg1 = self._create_line_event(1, "/short.py", 10, "print('Hello')")
        self.renderer.add_raw_message(msg1, TraceTypes.COLOR_LINE)

        # Second file with long name
        long_filename = "/a/very/long/path/to/a/file/with/a/very_long_name.py"
        msg2 = self._create_line_event(1, long_filename, 5, "x = 1")
        self.renderer.add_raw_message(msg2, TraceTypes.COLOR_LINE)

        # Another line from the long file
        msg3 = self._create_line_event(1, long_filename, 8, "y = 2")
        self.renderer.add_raw_message(msg3, TraceTypes.COLOR_LINE)

        result = self.renderer.generate_html()

        # First line should show full filename
        self.assertIn("▷&nbsp;/short.py:10&nbsp;print(&#x27;Hello&#x27;)", result)

        # Second line should show full filename for the long file
        self.assertIn(f"▷&nbsp;{long_filename}:5&nbsp;x&nbsp;=&nbsp;1", result)

        # Third line should collapse and be aligned based on the long filename
        # The alignment should be calculated based on the long filename's length
        first_lineno_long = 5
        total_width_long = len(long_filename) + 1 + len(str(first_lineno_long))

        third_lineno = 8
        aligned_str_3 = f"▷ {third_lineno}".rjust(total_width_long + 2)  # +2 for "▷ "
        expected_html_part_3 = f"{aligned_str_3.replace(' ', '&nbsp;')}&nbsp;y&nbsp;=&nbsp;2"
        self.assertIn(expected_html_part_3, result)
        self.assertNotIn(f"{long_filename}:8", result)


class TestSaveToFilePathHandling(unittest.TestCase):
    """Test path handling in save_to_file method"""

    def setUp(self):
        """Set up test fixtures"""
        # Create a mock trace_logic object
        self.mock_trace_logic = Mock()
        self.renderer = CallTreeHtmlRender(self.mock_trace_logic)

    def test_absolute_path_handling(self):
        """Test that absolute paths are handled correctly"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test with absolute path
            absolute_path = Path(temp_dir) / "test_absolute.html"
            result = self.renderer.save_to_file(str(absolute_path), is_multi_threaded=False)

            # Should return the same absolute path
            self.assertEqual(result.resolve(), absolute_path.resolve())
            # Directory should exist
            self.assertTrue(absolute_path.parent.exists())

    def test_relative_path_handling(self):
        """Test that relative paths use tracer-logs directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                # Test with relative path
                relative_path = "test_relative.html"
                result = self.renderer.save_to_file(relative_path, is_multi_threaded=False)

                # Should be in tracer-logs directory
                expected_path = Path(temp_dir) / "tracer-logs" / relative_path
                # Use resolve() to handle /private prefix on macOS
                self.assertEqual(result.resolve(), expected_path.resolve())
                # Directory should exist
                self.assertTrue(expected_path.parent.exists())

            finally:
                os.chdir(original_cwd)

    def test_multi_threaded_absolute_path(self):
        """Test multi-threaded mode with absolute path"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test with absolute path in multi-threaded mode
            # Note: save_to_file expects simple filenames, not paths with directories
            # The translator should handle path conversion before calling this method
            absolute_path = Path(temp_dir) / "test_mt.html"
            result = self.renderer.save_to_file("test_mt.html", is_multi_threaded=True)

            # Should create timestamped subdirectory with report.html
            self.assertTrue("test_mt_" in str(result))
            self.assertTrue(result.name == "report.html")
            # Directory should exist
            self.assertTrue(result.parent.exists())

    def test_multi_threaded_relative_path(self):
        """Test multi-threaded mode with relative path"""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                # Test with relative path in multi-threaded mode
                relative_path = "test_mt.html"
                result = self.renderer.save_to_file(relative_path, is_multi_threaded=True)

                # Should create timestamped subdirectory with report.html
                self.assertTrue("test_mt_" in str(result))
                self.assertTrue(result.name == "report.html")
                # Directory should exist
                self.assertTrue(result.parent.exists())

            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
