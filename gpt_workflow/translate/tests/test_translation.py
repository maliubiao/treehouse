#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ..translation import get_translation_prompt, is_empty_content, translate_parallel


class TestTranslationFunctions(unittest.TestCase):
    @patch("gpt_workflow.translate.translation.ModelSwitch")
    def test_translate_parallel(self, mock_model):
        mock_model.query.return_value = {"choices": [{"message": {"content": "translated"}}]}
        paragraphs = [{"line_range": "1-2"}]
        source_lines = ["line1", "line2"]
        logger = MagicMock()

        cache, log = translate_parallel(paragraphs, source_lines, "zh-en", 2, logger, mock_model)
        self.assertEqual(cache[(1, 2)], "translated")

    def test_is_empty_content(self):
        self.assertTrue(is_empty_content("   \n\t"))
        self.assertTrue(is_empty_content("..."))
        self.assertFalse(is_empty_content("text"))

    def test_get_translation_prompt(self):
        # Create a temporary prompt file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as tmp_file:
            tmp_file.write("Translate this text")
            tmp_path = Path(tmp_file.name)

        try:
            # Test with mock path
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.open", unittest.mock.mock_open(read_data="Test prompt")):
                    prompt = get_translation_prompt("test text", "zh-en")
                    self.assertIn("Test prompt", prompt)
                    self.assertIn("test text", prompt)

            # Test unsupported direction
            with self.assertRaises(ValueError):
                get_translation_prompt("text", "invalid-direction")

        finally:
            if tmp_path.exists():
                tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
