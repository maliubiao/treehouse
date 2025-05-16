#!/usr/bin/env python3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ..workflow import TranslationWorkflow


class TestTranslationWorkflow(unittest.TestCase):
    def setUp(self):
        self.test_file = Path("test.txt")
        with open(self.test_file, "w") as f:
            f.write("Test content")

    def tearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()

    @patch("gpt_workflow.translate.workflow.ModelSwitch")
    def test_init(self, mock_model):
        workflow = TranslationWorkflow("test.txt")
        self.assertEqual(workflow.source_file.name, "test.txt")
        self.assertIsNone(workflow.yaml_file)
        self.assertEqual(workflow.output_file.name, "test.translated")

    @patch("gpt_workflow.translate.workflow.load_config")
    def test_load_files(self, mock_load):
        mock_load.return_value = (["line1", "line2"], [])
        workflow = TranslationWorkflow("test.txt")
        workflow.load_files()
        self.assertEqual(workflow.source_lines, ["line1", "line2"])

    # Additional test cases would be added here...


if __name__ == "__main__":
    unittest.main()
