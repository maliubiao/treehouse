#!/usr/bin/env python3
import os
import tempfile
import unittest

from tools.paragraph_extractor import ParagraphExtractor


class TestParagraphExtractor(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

        # Create test source file
        self.source_file = os.path.join(self.test_dir, "test.py")
        with open(self.source_file, "w") as f:
            f.write("""# Sample file
def func1():
    pass

def func2():
    pass
""")

        # Create test YAML file
        self.yaml_file = os.path.join(self.test_dir, "test.yaml")
        with open(self.yaml_file, "w") as f:
            f.write("""format_version: 1.4
file_path: "test.py"
content_summary: "Sample test file"
paragraphs:
  - type: section
    line_range: 1-3
    line_count: 3
    description: "Function 1 section"
    content_attributes: [code, technical]
    
  - type: section
    line_range: 4-6
    line_count: 3
    description: "Function 2 section"
    content_attributes: [code, technical]
""")

    def test_file_loading(self):
        extractor = ParagraphExtractor(self.source_file, self.yaml_file)
        extractor.load_files()
        self.assertEqual(len(extractor.source_lines), 6)
        self.assertEqual(len(extractor.paragraphs), 2)

    def test_paragraph_extraction(self):
        extractor = ParagraphExtractor(self.source_file, self.yaml_file)
        extractor.load_files()

        # Capture print output
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            extractor.extract_paragraphs()

        output = f.getvalue()
        self.assertIn("Function 1 section", output)
        self.assertIn("1 | # Sample file", output)
        self.assertIn("Function 2 section", output)
        self.assertIn("5 | def func2():", output)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.test_dir)


if __name__ == "__main__":
    unittest.main()
