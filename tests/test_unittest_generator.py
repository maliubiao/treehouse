import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add project root to sys.path to allow importing project modules.
# This needs to be done before importing the module to be tested.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# The import target is still the same file, which now acts as a facade.
# This ensures backward compatibility of the test.
from gpt_workflow.unittester import UnitTestGenerator
from gpt_workflow.unittester.worker import _extract_code_from_response


class TestUnitTestGeneratorRefactored(unittest.TestCase):
    def setUp(self):
        """Set up a temporary directory and mock project structure."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Mock project structure
        self.mock_project_root = self.temp_path / "test_project"
        self.app_dir = self.mock_project_root / "my_app"
        self.tests_dir = self.mock_project_root / "generated_tests"
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.tests_dir.mkdir(exist_ok=True)

        # Mock source file
        self.source_file_path = self.app_dir / "main_logic.py"
        self.source_file_content = (
            "def helper_func(x):\n"
            "    return x * 2\n\n"
            "def func_to_test(a, b):\n"
            "    if a > 10:\n"
            "        raise ValueError('a cannot be > 10')\n"
            "    result = a + b\n"
            "    return helper_func(result)\n"
        )
        self.source_file_path.write_text(self.source_file_content)

        # Mock analysis report
        self.report_path = self.temp_path / "call_analysis_report.json"
        self.analysis_data = {
            str(self.source_file_path): {
                "func_to_test": [
                    {
                        "frame_id": 1,
                        "func_name": "func_to_test",
                        "original_filename": str(self.source_file_path),
                        "original_lineno": 5,
                        "args": {"a": 5, "b": 3},
                        "return_value": 16,
                        "exception": None,
                        "events": [{"type": "call", "data": {"func_name": "helper_func"}}],
                    },
                ]
            }
        }
        with open(self.report_path, "w") as f:
            json.dump(self.analysis_data, f)

        # Patch sys.exit to prevent tests from stopping
        self.sys_exit_patcher = patch("sys.exit")
        self.mock_sys_exit = self.sys_exit_patcher.start()

    def tearDown(self):
        """Clean up the temporary directory and stop patchers."""
        self.temp_dir.cleanup()
        self.sys_exit_patcher.stop()

    def _create_generator(self) -> UnitTestGenerator:
        """Create a generator instance with test configuration."""
        generator = UnitTestGenerator(report_path=str(self.report_path), test_mode=True)
        # Resolve the project root path to handle MacOS /private prefix
        generator.project_root = self.mock_project_root.resolve()
        return generator

    def test_extract_code_from_response(self):
        """Test the refactored code extraction utility."""
        python_code = "import unittest\nprint('hello')"
        response_new_format = f"Some text before\n[start]\n{python_code}\n[end]\nSome text after"
        response_markdown = f"```python\n{python_code}\n```"
        response_no_block = "Just some text."

        self.assertEqual(_extract_code_from_response(response_new_format), python_code)
        self.assertEqual(_extract_code_from_response(response_markdown), python_code)
        self.assertIsNone(_extract_code_from_response(response_no_block))

    @patch("gpt_workflow.unittester.generator.TracingModelSwitch.query")
    def test_generate_new_file_end_to_end(self, mock_query):
        """Test the full generation process for a new test file."""
        mock_query.side_effect = [
            # 1. Suggestion for file/class name
            '[start]{"file_name": "test_new_logic.py", "class_name": "TestNewLogic"}[end]',
            # 2. Generation for the single case (as a full file)
            """
            [start]
import unittest
from my_app.main_logic import func_to_test
class TestNewLogic(unittest.TestCase):
    def test_func_to_test_case_1(self):
        self.assertEqual(func_to_test(5, 3), 16)
if __name__ == '__main__':
    unittest.main()
            [end]
            """,
        ]

        generator = self._create_generator()
        self.assertTrue(generator.load_and_parse_report())

        success = generator.generate(
            target_funcs=["func_to_test"],
            output_dir=str(self.tests_dir),
            auto_confirm=True,
            use_symbol_service=False,
            num_workers=0,
        )

        self.assertTrue(success)
        self.assertEqual(mock_query.call_count, 2)
        output_file = self.tests_dir / "test_new_logic.py"
        self.assertTrue(output_file.exists())
        content = output_file.read_text()
        self.assertIn("class TestNewLogic(unittest.TestCase):", content)
        self.assertIn("test_func_to_test_case_1", content)


if __name__ == "__main__":
    unittest.main()
