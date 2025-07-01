import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path to allow importing project modules
# This needs to be done before importing the module to be tested.
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from gpt_workflow.unittest_generator import UnitTestGenerator


class TestUnitTestGenerator(unittest.TestCase):
    def setUp(self):
        """Set up a temporary directory and mock project structure."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Mock project structure
        self.project_root = self.temp_path / "test_project"
        self.app_dir = self.project_root / "my_app"
        self.tests_dir = self.project_root / "generated_tests"
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
                        "start_time": 0,
                        "end_time": 1,
                        "events": [
                            {"type": "line", "data": {"line_no": 8, "content": "result = a + b"}},
                            {
                                "type": "call",
                                "data": {
                                    "func_name": "helper_func",
                                    "original_filename": str(self.source_file_path),
                                    "original_lineno": 1,
                                    "args": {"x": 8},
                                    "return_value": 16,
                                    "exception": None,
                                    "caller_lineno": 9,
                                },
                            },
                        ],
                    },
                ]
            }
        }
        with open(self.report_path, "w") as f:
            json.dump(self.analysis_data, f)

        # Patch global `project_root` used in the module
        self.project_root_patcher = patch("gpt_workflow.unittest_generator.project_root", self.project_root)
        self.mock_project_root = self.project_root_patcher.start()

        # Patch `sys.exit` to prevent tests from stopping
        self.sys_exit_patcher = patch("sys.exit")
        self.mock_sys_exit = self.sys_exit_patcher.start()

    def tearDown(self):
        """Clean up the temporary directory and stop patchers."""
        self.temp_dir.cleanup()
        self.project_root_patcher.stop()
        self.sys_exit_patcher.stop()

    def test_init_and_load_report_success(self):
        """Test successful initialization and loading of a valid report."""
        generator = UnitTestGenerator(report_path=str(self.report_path))
        self.assertTrue(generator.load_and_parse_report())
        self.assertEqual(generator.analysis_data, self.analysis_data)

    def test_extract_code_from_response(self):
        """Test extraction of content from [start]/[end] blocks."""
        generator = UnitTestGenerator()
        python_code = "import unittest\nprint('hello')"
        response_new_format = f"Some text before\n[start]\n{python_code}\n[end]\nSome text after"
        response_markdown = f"```python\n{python_code}\n```"
        response_no_block = "Just some text."

        self.assertEqual(generator._extract_code_from_response(response_new_format), python_code)
        # Test fallback to markdown
        self.assertEqual(generator._extract_code_from_response(response_markdown), python_code)
        self.assertIsNone(generator._extract_code_from_response(response_no_block))

    def test_generate_relative_sys_path_snippet(self):
        """Test the generation of the sys.path setup snippet."""
        generator = UnitTestGenerator()
        test_file_path = self.tests_dir / "test_main_logic.py"
        # From generated_tests/, we need to go up one level to reach project_root
        # Path(__file__).parent is generated_tests, .parent is test_project (root)
        snippet = generator._generate_relative_sys_path_snippet(test_file_path, self.project_root)

        self.assertIn("import sys", snippet)
        self.assertIn("from pathlib import Path", snippet)
        # The new robust logic should result in `parent.parent` for this specific test case structure
        self.assertIn("project_root = Path(__file__).resolve().parent.parent", snippet)
        self.assertIn("sys.path.insert(0, str(project_root))", snippet)

    @patch("gpt_workflow.unittest_generator.TracingModelSwitch.query")
    def test_generate_end_to_end_single_case(self, mock_query):
        """Test the full generation process for a single test case, using the new engine."""
        # --- Mocks Setup ---
        # Mock 1: LLM suggestion for file/class name (JSON in [start]/[end])
        # Mock 2: LLM generation for the test case (Python code in [start]/[end])
        mock_query.side_effect = [
            # 1. Suggestion query
            """
            [start]
            {
                "file_name": "test_main_logic.py",
                "class_name": "TestMainLogic"
            }
            [end]
            """,
            # 2. Generation for the single case
            """
            [start]
import unittest
from unittest.mock import patch
import sys
from pathlib import Path

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
from my_app.main_logic import func_to_test, helper_func

class TestMainLogic(unittest.TestCase):
    @patch('my_app.main_logic.helper_func', return_value=16)
    def test_func_to_test_normal_return(self, mock_helper):
        self.assertEqual(func_to_test(5, 3), 16)
        mock_helper.assert_called_once_with(8)

if __name__ == '__main__':
    unittest.main()
            [end]
            """,
        ]

        generator = UnitTestGenerator(
            report_path=str(self.report_path),
            model_name="test_model",
            checker_model_name="test_checker",
            test_mode=True,  # Ensure mocks are used
        )
        self.assertTrue(generator.load_and_parse_report())

        # --- Execution ---
        success = generator.generate(
            target_funcs=["func_to_test"],
            output_dir=str(self.tests_dir),
            auto_confirm=True,
            use_symbol_service=False,  # Test file-based context
            num_workers=0,  # Serial execution
        )

        # --- Assertions ---
        self.assertTrue(success)
        self.assertEqual(mock_query.call_count, 2)

        # Check prompts
        name_prompt = mock_query.call_args_list[0].args[1]
        self.assertIn("enclosed in `[start]` and `[end]` tags", name_prompt)

        gen_prompt = mock_query.call_args_list[1].args[1]
        self.assertIn("enclosed within a single\n            `[start]` and `[end]` block", gen_prompt)
        self.assertIn("[FINAL] RETURNS: 16", gen_prompt)

        # Check final file content by reading it back
        output_file = self.tests_dir / "test_main_logic.py"
        self.assertTrue(output_file.exists())
        content = output_file.read_text()
        self.assertIn("class TestMainLogic(unittest.TestCase):", content)
        self.assertIn("test_func_to_test_normal_return", content)
        self.assertIn("if __name__ == '__main__':", content)
        # Check that ruff formatting did not over-indent the main block
        self.assertNotIn("    if __name__ == '__main__':", content)

    @patch("gpt_workflow.unittest_generator.query_symbol_service")
    @patch("gpt_workflow.unittest_generator.TracingModelSwitch.query")
    def test_generate_with_symbol_service(self, mock_query, mock_symbol_service):
        """Test that the symbol service path is correctly triggered and uses the new format."""
        # --- Mocks Setup ---
        mock_query.side_effect = [
            # 1. Suggestion
            '[start]\n{"file_name": "test_symbol.py", "class_name": "TestSymbol"}\n[end]',
            # 2. Generation
            """
            [start]
import unittest
class TestSymbol(unittest.TestCase):
    def test_symbol_based(self):
        self.assertTrue(True)
[end]
            """,
        ]
        mock_symbol_service.return_value = {
            "func_to_test": {"code": "def func_to_test(...)", "file_path": str(self.source_file_path)},
            "helper_func": {"code": "def helper_func(...)", "file_path": str(self.source_file_path)},
        }

        generator = UnitTestGenerator(report_path=str(self.report_path), test_mode=True)
        self.assertTrue(generator.load_and_parse_report())

        # --- Execution ---
        generator.generate(
            target_funcs=["func_to_test"],
            output_dir=str(self.tests_dir),
            auto_confirm=True,
            use_symbol_service=True,
            num_workers=0,
        )

        # --- Assertions ---
        mock_symbol_service.assert_called_once()
        # [BUG FIX] Assert that 'model_switch' is NOT passed to the service call
        self.assertNotIn("model_switch", mock_symbol_service.call_args.kwargs)

        self.assertEqual(mock_query.call_count, 2)

        gen_prompt = mock_query.call_args_list[1].args[1]
        self.assertIn("CONTEXT: RELEVANT SOURCE CODE (PRECISION MODE)", gen_prompt)
        self.assertIn("[Relevant Code Snippets]\n", gen_prompt)
        self.assertNotIn("CONTEXT: SOURCE CODE (FOR REFERENCE ONLY)", gen_prompt)
        self.assertIn("# Symbol: func_to_test", gen_prompt)


if __name__ == "__main__":
    unittest.main()
