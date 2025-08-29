import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import TextIO

# Add the src directory to the path to allow direct import of the script.
# This is a common pattern for running tests locally without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_tracer.text_to_llm_context import process_log_file


class TestTextToLLMContext(unittest.TestCase):
    """Unit tests for the text_to_llm_context log compression script."""

    original_stdout: TextIO
    captured_output: io.StringIO

    def setUp(self) -> None:
        """Redirect stdout to an in-memory buffer to capture the output."""
        self.original_stdout = sys.stdout
        self.captured_output = io.StringIO()
        sys.stdout = self.captured_output

    def tearDown(self) -> None:
        """Restore the original stdout."""
        sys.stdout = self.original_stdout

    def _run_test_case(self, input_log: str, expected_output: str) -> None:
        """
        Helper method to run a test case with a given input and expected output.

        It writes the input log to a temporary file, processes it using the target
        function, and compares the captured stdout with the expected output.
        """
        # For malformed indentation tests, don't dedent the input to preserve spacing
        if "malformed" in input_log or "odd indentation" in input_log:
            dedented_input = input_log.strip()
        else:
            # Dedent the input to make test cases more readable in the source code.
            dedented_input = textwrap.dedent(input_log).strip()

        # For expected output, dedent it to match the actual output format
        # The actual output uses tabs, so we need to convert spaces to tabs in expected output
        dedented_expected = textwrap.dedent(expected_output).strip()

        with tempfile.NamedTemporaryFile(mode="w+", delete=True, encoding="utf-8", suffix=".log") as tmp_file:
            tmp_file.write(dedented_input)
            tmp_file.flush()

            process_log_file(Path(tmp_file.name))

        actual_output = self.captured_output.getvalue().strip()
        self.assertEqual(actual_output, dedented_expected)

    def test_simple_call_and_lines(self) -> None:
        """Tests basic compression: a single CALL followed by LINE events."""
        input_log = """
        ↘ CALL path/to/file.py:10 my_func() [frame:1][thread:1]
          ▷ path/to/file.py:11 line_content_1 # Debug: var=1
          ▷ path/to/file.py:12 line_content_2
        ↗ RETURN path/to/file.py my_func() → None [frame:1]
        """

        path_padding = " " * len("path/to/file.py")
        expected_output = f"""
        ↘ CALL path/to/file.py:10 my_func() [frame:1][thread:1]
        \t▷ {path_padding}:11 line_content_1 # Debug: var=1
        \t▷ {path_padding}:12 line_content_2
        ↗ RETURN path/to/file.py my_func() → None [frame:1]
        """
        self._run_test_case(input_log, expected_output)

    def test_nested_calls(self) -> None:
        """Tests compression with nested function calls and changing contexts."""
        input_log = """
        ↘ CALL path/to/file.py:20 outer_func() [frame:1][thread:1]
          ▷ path/to/file.py:21 calling_inner()
          ↘ CALL other/path/another.py:5 inner_func() [frame:2][thread:1]
            ▷ other/path/another.py:6 inside_inner()
          ↗ RETURN other/path/another.py inner_func() → True [frame:2]
          ▷ path/to/file.py:22 back_in_outer()
        """

        path1_padding = " " * len("path/to/file.py")
        path2_padding = " " * len("other/path/another.py")
        expected_output = f"""
        ↘ CALL path/to/file.py:20 outer_func() [frame:1][thread:1]
        \t▷ {path1_padding}:21 calling_inner()
        \t↘ CALL other/path/another.py:5 inner_func() [frame:2][thread:1]
        \t\t▷ {path2_padding}:6 inside_inner()
        \t↗ RETURN other/path/another.py inner_func() → True [frame:2]
        \t▷ {path1_padding}:22 back_in_outer()
        """
        self._run_test_case(input_log, expected_output)

    def test_context_switch_with_return(self) -> None:
        """Tests that a new CALL after a RETURN correctly shows the path again."""
        input_log = """
        ↘ CALL path/to/file.py:10 func_one() [frame:1][thread:1]
          ▷ path/to/file.py:11 do_something()
        ↗ RETURN path/to/file.py func_one() → None [frame:1]
        ↘ CALL path/to/file.py:15 func_two() [frame:2][thread:1]
          ▷ path/to/file.py:16 do_another_thing()
        """

        path_padding = " " * len("path/to/file.py")
        expected_output = f"""
        ↘ CALL path/to/file.py:10 func_one() [frame:1][thread:1]
        \t▷ {path_padding}:11 do_something()
        ↗ RETURN path/to/file.py func_one() → None [frame:1]
        ↘ CALL path/to/file.py:15 func_two() [frame:2][thread:1]
        \t▷ {path_padding}:16 do_another_thing()
        """
        self._run_test_case(input_log, expected_output)

    def test_exception_triggers_context(self) -> None:
        """Tests that an EXCEPTION event is treated as a context-defining event."""
        input_log = """
        ↘ CALL main.py:5 risky_func() [frame:1][thread:1]
          ▷ main.py:6 might_fail()
          ⚠ EXCEPTION IN risky_func AT main.py:7 ValueError: bad value [frame:1]
        """

        path_padding = " " * len("main.py")
        expected_output = f"""
        ↘ CALL main.py:5 risky_func() [frame:1][thread:1]
        \t▷ {path_padding}:6 might_fail()
        \t⚠ EXCEPTION IN risky_func AT main.py:7 ValueError: bad value [frame:1]
        """
        self._run_test_case(input_log, expected_output)

    def test_different_paths_in_same_scope(self) -> None:
        """
        Tests an edge case where a line event has a different path than its parent.
        The full path should be printed to avoid confusion.
        """
        input_log = """
        ↘ CALL path/to/file.py:10 my_func() [frame:1][thread:1]
          ▷ path/to/file.py:11 line_1
          ▷ different/file.py:99 line_2_from_other_file
          ▷ path/to/file.py:12 line_3
        """

        path_padding = " " * len("path/to/file.py")
        expected_output = f"""
        ↘ CALL path/to/file.py:10 my_func() [frame:1][thread:1]
        \t▷ {path_padding}:11 line_1
        \t▷ different/file.py:99 line_2_from_other_file
        \t▷ {path_padding}:12 line_3
        """
        self._run_test_case(input_log, expected_output)

    def test_empty_and_malformed_lines(self) -> None:
        """Tests that empty lines and lines with odd indentation are preserved."""
        input_log = """
        ↘ CALL path/to/file.py:10 my_func() [frame:1][thread:1]
          ▷ path/to/file.py:11 line_1

   This is a malformed line with 3 spaces
          ▷ path/to/file.py:12 line_2
        """

        expected_output = "↘ CALL path/to/file.py:10 my_func() [frame:1][thread:1]\n\t\t\t\t\t▷ path/to/file.py:11 line_1\n\n   This is a malformed line with 3 spaces\n\t\t\t\t\t▷ path/to/file.py:12 line_2"
        self._run_test_case(input_log, expected_output)

    def test_no_parent_context(self) -> None:
        """
        Tests a trace starting mid-execution (with a LINE event).
        It should be printed as-is since there's no parent context to compress.
        """
        input_log = """
          ▷ path/to/file.py:11 line_1
          ▷ path/to/file.py:12 line_2
        """

        expected_output = """
        \t▷ path/to/file.py:11 line_1
        \t▷ path/to/file.py:12 line_2
        """
        self._run_test_case(input_log, expected_output)

    def test_module_events(self) -> None:
        """Tests compression with MODULE events that establish context."""
        input_log = """
        ↘ MODULE my_module.py:0 <module>() [frame:1][thread:123]
          ▷ my_module.py:1 import os
          ▷ my_module.py:2 import sys
          ↘ CALL another/path.py:10 some_func() [frame:2][thread:123]
            ▷ another/path.py:11 do_work()
          ↗ RETURN another/path.py some_func() → None [frame:2]
          ▷ my_module.py:3 print("done")
        """

        module_padding = " " * len("my_module.py")
        another_padding = " " * len("another/path.py")
        expected_output = f"""
        ↘ MODULE my_module.py:0 <module>() [frame:1][thread:123]
        \t▷ {module_padding}:1 import os
        \t▷ {module_padding}:2 import sys
        \t↘ CALL another/path.py:10 some_func() [frame:2][thread:123]
        \t\t▷ {another_padding}:11 do_work()
        \t↗ RETURN another/path.py some_func() → None [frame:2]
        \t▷ {module_padding}:3 print("done")
        """
        self._run_test_case(input_log, expected_output)

    def test_return_statements(self) -> None:
        """Tests that RETURN statements don't establish context but preserve indentation."""
        input_log = """
        ↘ CALL path/to/file.py:10 func_one() [frame:1][thread:1]
          ▷ path/to/file.py:11 x = 1
        ↗ RETURN path/to/file.py func_one() → 42 [frame:1]
        ↘ CALL path/to/file.py:15 func_two() [frame:2][thread:1]
          ▷ path/to/file.py:16 y = 2
        ↗ RETURN path/to/file.py func_two() → None [frame:2]
        """

        path_padding = " " * len("path/to/file.py")
        expected_output = f"""
        ↘ CALL path/to/file.py:10 func_one() [frame:1][thread:1]
        \t▷ {path_padding}:11 x = 1
        ↗ RETURN path/to/file.py func_one() → 42 [frame:1]
        ↘ CALL path/to/file.py:15 func_two() [frame:2][thread:1]
        \t▷ {path_padding}:16 y = 2
        ↗ RETURN path/to/file.py func_two() → None [frame:2]
        """
        self._run_test_case(input_log, expected_output)

    def test_frozen_calls(self) -> None:
        """Tests calls to frozen modules like <frozen runpy>."""
        input_log = """
        ↘ CALL main.py:5 run_script() [frame:1][thread:1]
          ▷ main.py:6 runpy.run_path("script.py")
          ↘ CALL <frozen runpy>:262 run_path() [frame:2][thread:1]
            ▷ <frozen runpy>:263 _run_module_as_main()
          ↗ RETURN <frozen runpy> run_path() → None [frame:2]
          ▷ main.py:7 print("finished")
        """

        main_padding = " " * len("main.py")
        frozen_padding = " " * len("<frozen runpy>")
        expected_output = f"""
        ↘ CALL main.py:5 run_script() [frame:1][thread:1]
        \t▷ {main_padding}:6 runpy.run_path("script.py")
        \t↘ CALL <frozen runpy>:262 run_path() [frame:2][thread:1]
        \t\t▷ {frozen_padding}:263 _run_module_as_main()
        \t↗ RETURN <frozen runpy> run_path() → None [frame:2]
        \t▷ {main_padding}:7 print("finished")
        """
        self._run_test_case(input_log, expected_output)

    def test_deep_nesting_with_context_switches(self) -> None:
        """Tests deep nesting (5+ levels) with multiple file context switches."""
        input_log = """
        ↘ CALL app.py:1 main() [frame:1][thread:1]
          ▷ app.py:2 load_config()
          ↘ CALL config/loader.py:10 load_config() [frame:2][thread:1]
            ▷ config/loader.py:11 read_file()
            ↘ CALL utils/io.py:5 read_file() [frame:3][thread:1]
              ▷ utils/io.py:6 open(filename)
              ↘ CALL <built-in>:0 open() [frame:4][thread:1]
              ↗ RETURN <built-in> open() → <file> [frame:4]
              ▷ utils/io.py:7 content = f.read()
              ↘ CALL pathlib/_local.py:100 read() [frame:5][thread:1]
                ▷ pathlib/_local.py:101 return self._accessor.read()
              ↗ RETURN pathlib/_local.py read() → 'data' [frame:5]
            ↗ RETURN utils/io.py read_file() → 'data' [frame:3]
            ▷ config/loader.py:12 parse_data(content)
          ↗ RETURN config/loader.py load_config() → {} [frame:2]
          ▷ app.py:3 start_server()
        """

        app_padding = " " * len("app.py")
        config_padding = " " * len("config/loader.py")
        utils_padding = " " * len("utils/io.py")
        builtin_padding = " " * len("<built-in>")
        pathlib_padding = " " * len("pathlib/_local.py")

        expected_output = f"""
        ↘ CALL app.py:1 main() [frame:1][thread:1]
        \t▷ {app_padding}:2 load_config()
        \t↘ CALL config/loader.py:10 load_config() [frame:2][thread:1]
        \t\t▷ {config_padding}:11 read_file()
        \t\t↘ CALL utils/io.py:5 read_file() [frame:3][thread:1]
        \t\t\t▷ {utils_padding}:6 open(filename)
        \t\t\t↘ CALL <built-in>:0 open() [frame:4][thread:1]
        \t\t\t↗ RETURN <built-in> open() → <file> [frame:4]
        \t\t\t▷ {utils_padding}:7 content = f.read()
        \t\t\t↘ CALL pathlib/_local.py:100 read() [frame:5][thread:1]
        \t\t\t\t▷ {pathlib_padding}:101 return self._accessor.read()
        \t\t\t↗ RETURN pathlib/_local.py read() → 'data' [frame:5]
        \t\t↗ RETURN utils/io.py read_file() → 'data' [frame:3]
        \t\t▷ {config_padding}:12 parse_data(content)
        \t↗ RETURN config/loader.py load_config() → {{}} [frame:2]
        \t▷ {app_padding}:3 start_server()
        """
        self._run_test_case(input_log, expected_output)

    def test_multiple_exception_contexts(self) -> None:
        """Tests multiple exception events creating new contexts."""
        input_log = """
        ↘ CALL main.py:10 risky_function() [frame:1][thread:1]
          ▷ main.py:11 try_operation()
          ⚠ EXCEPTION IN try_operation AT main.py:12 ValueError: invalid input [frame:1]
          ▷ main.py:13 handle_error()
          ↘ CALL error/handler.py:5 handle_error() [frame:2][thread:1]
            ▷ error/handler.py:6 log_error()
            ⚠ EXCEPTION IN log_error AT error/handler.py:7 IOError: cannot write [frame:2]
            ▷ error/handler.py:8 fallback_log()
          ↗ RETURN error/handler.py handle_error() → None [frame:2]
          ▷ main.py:14 cleanup()
        """

        main_padding = " " * len("main.py")
        error_padding = " " * len("error/handler.py")
        expected_output = f"""
        ↘ CALL main.py:10 risky_function() [frame:1][thread:1]
        \t▷ {main_padding}:11 try_operation()
        \t⚠ EXCEPTION IN try_operation AT main.py:12 ValueError: invalid input [frame:1]
        \t▷ {main_padding}:13 handle_error()
        \t↘ CALL error/handler.py:5 handle_error() [frame:2][thread:1]
        \t\t▷ {error_padding}:6 log_error()
        \t\t⚠ EXCEPTION IN log_error AT error/handler.py:7 IOError: cannot write [frame:2]
        \t\t▷ {error_padding}:8 fallback_log()
        \t↗ RETURN error/handler.py handle_error() → None [frame:2]
        \t▷ {main_padding}:14 cleanup()
        """
        self._run_test_case(input_log, expected_output)

    def test_long_file_paths(self) -> None:
        """Tests compression with very long file paths."""
        long_path = "very/deeply/nested/directory/structure/with/many/levels/and/subfolders/file.py"
        input_log = f"""
        ↘ CALL {long_path}:100 long_path_function() [frame:1][thread:1]
          ▷ {long_path}:101 first_line()
          ▷ {long_path}:102 second_line()
          ▷ {long_path}:103 third_line()
        """

        long_padding = " " * len(long_path)
        expected_output = f"""
        ↘ CALL {long_path}:100 long_path_function() [frame:1][thread:1]
        \t▷ {long_padding}:101 first_line()
        \t▷ {long_padding}:102 second_line()
        \t▷ {long_padding}:103 third_line()
        """
        self._run_test_case(input_log, expected_output)

    def test_paths_with_special_characters(self) -> None:
        """Tests compression with file paths containing special characters."""
        input_log = """
        ↘ CALL my-app/src/中文文件.py:10 test_unicode() [frame:1][thread:1]
          ▷ my-app/src/中文文件.py:11 unicode_content = "你好"
          ▷ my-app/src/中文文件.py:12 print(unicode_content)
        ↘ CALL path with spaces/file.py:5 space_test() [frame:2][thread:1]
          ▷ path with spaces/file.py:6 handle_spaces()
        """

        unicode_padding = " " * len("my-app/src/中文文件.py")
        spaces_padding = " " * len("path with spaces/file.py")
        expected_output = f"""
        ↘ CALL my-app/src/中文文件.py:10 test_unicode() [frame:1][thread:1]
        \t▷ {unicode_padding}:11 unicode_content = "你好"
        \t▷ {unicode_padding}:12 print(unicode_content)
        ↘ CALL path with spaces/file.py:5 space_test() [frame:2][thread:1]
        \t▷ {spaces_padding}:6 handle_spaces()
        """
        self._run_test_case(input_log, expected_output)

    def test_malformed_indentation(self) -> None:
        """Tests handling of lines with odd spacing (not multiple of 2)."""
        input_log = """
        ↘ CALL main.py:10 normal_func() [frame:1][thread:1]
          ▷ main.py:11 normal_line
           This line has 3 spaces (odd indentation)
         This line has 1 space
            This line has 4 spaces
          ▷ main.py:12 back_to_normal
        """

        main_padding = " " * len("main.py")
        expected_output = f"↘ CALL main.py:10 normal_func() [frame:1][thread:1]\n\t\t\t\t\t▷ main.py:11 normal_line\n           This line has 3 spaces (odd indentation)\n         This line has 1 space\n\t\t\t\t\t\tThis line has 4 spaces\n\t\t\t\t\t▷ main.py:12 back_to_normal"
        self._run_test_case(input_log, expected_output)

    def test_empty_lines_and_whitespace(self) -> None:
        """Tests handling of empty lines and whitespace-only lines."""
        input_log = """
        ↘ CALL main.py:10 test_func() [frame:1][thread:1]
          ▷ main.py:11 line_before_empty

          ▷ main.py:13 line_after_empty
          
          ▷ main.py:15 line_after_whitespace
        """

        main_padding = " " * len("main.py")
        expected_output = f"""
        ↘ CALL main.py:10 test_func() [frame:1][thread:1]
        \t▷ {main_padding}:11 line_before_empty

        \t▷ {main_padding}:13 line_after_empty
        \t
        \t▷ {main_padding}:15 line_after_whitespace
        """
        self._run_test_case(input_log, expected_output)

    def test_multiline_debug_content(self) -> None:
        """Tests handling of very long debug output that might wrap."""
        long_debug = "# Debug: very_long_variable_name_with_lots_of_content={'key1': 'value1', 'key2': 'value2', 'key3': 'value3', 'nested': {'inner_key': 'inner_value', 'another': 'data'}}"
        input_log = f"""
        ↘ CALL debug/test.py:5 debug_heavy_func() [frame:1][thread:1]
          ▷ debug/test.py:6 process_data() {long_debug}
          ▷ debug/test.py:7 more_processing()
        """

        debug_padding = " " * len("debug/test.py")
        expected_output = f"""
        ↘ CALL debug/test.py:5 debug_heavy_func() [frame:1][thread:1]
        \t▷ {debug_padding}:6 process_data() {long_debug}
        \t▷ {debug_padding}:7 more_processing()
        """
        self._run_test_case(input_log, expected_output)

    def test_thread_frame_information(self) -> None:
        """Tests that thread and frame information is preserved correctly."""
        input_log = """
        ↘ CALL worker.py:10 thread_func() [frame:100][thread:12345]
          ▷ worker.py:11 do_work_in_thread()
          ↘ CALL utils.py:5 helper() [frame:101][thread:12345]
            ▷ utils.py:6 helper_work()
          ↗ RETURN utils.py helper() → result [frame:101]
        ↘ CALL main.py:1 main_thread() [frame:1][thread:1]
          ▷ main.py:2 main_work()
        """

        worker_padding = " " * len("worker.py")
        utils_padding = " " * len("utils.py")
        main_padding = " " * len("main.py")
        expected_output = f"""
        ↘ CALL worker.py:10 thread_func() [frame:100][thread:12345]
        \t▷ {worker_padding}:11 do_work_in_thread()
        \t↘ CALL utils.py:5 helper() [frame:101][thread:12345]
        \t\t▷ {utils_padding}:6 helper_work()
        \t↗ RETURN utils.py helper() → result [frame:101]
        ↘ CALL main.py:1 main_thread() [frame:1][thread:1]
        \t▷ {main_padding}:2 main_work()
        """
        self._run_test_case(input_log, expected_output)

    def test_boundary_empty_file(self) -> None:
        """Tests processing of an empty log file."""
        input_log = """
        
        """
        expected_output = """
        
        """
        self._run_test_case(input_log, expected_output)

    def test_single_line_trace(self) -> None:
        """Tests processing of a trace with only one line."""
        input_log = """
        ↘ CALL single.py:1 only_func() [frame:1][thread:1]
        """
        expected_output = """
        ↘ CALL single.py:1 only_func() [frame:1][thread:1]
        """
        self._run_test_case(input_log, expected_output)

    def test_large_log_performance(self) -> None:
        """Tests performance with a large log file (1000+ lines)."""
        # Generate a large log with repetitive patterns
        large_log_lines = []

        # Start with a module
        large_log_lines.append("↘ MODULE main.py:0 <module>() [frame:1][thread:1]")

        # Add many lines in the same context
        for i in range(1, 501):
            large_log_lines.append(f"  ▷ main.py:{i} line_{i}()")

        # Add nested calls
        large_log_lines.append("  ↘ CALL utils.py:10 helper() [frame:2][thread:1]")
        for i in range(11, 511):
            large_log_lines.append(f"    ▷ utils.py:{i} helper_work_{i}()")
        large_log_lines.append("    ↗ RETURN utils.py helper() → result [frame:2]")

        # Add more main context lines
        for i in range(502, 1002):
            large_log_lines.append(f"  ▷ main.py:{i} line_{i}()")

        input_log = "\n".join(large_log_lines)

        # Process and verify it doesn't crash
        with tempfile.NamedTemporaryFile(mode="w+", delete=True, encoding="utf-8", suffix=".log") as tmp_file:
            tmp_file.write(input_log)
            tmp_file.flush()

            # This should complete without errors
            process_log_file(Path(tmp_file.name))

            # Verify output was generated
            actual_output = self.captured_output.getvalue()
            self.assertGreater(len(actual_output), 0)

            # Verify compression worked - should have many tab-indented lines
            tab_lines = [line for line in actual_output.split("\n") if "\t" in line]
            self.assertGreater(len(tab_lines), 500)  # Most lines should be compressed

    def test_repetitive_path_compression(self) -> None:
        """Tests that repetitive paths are efficiently compressed."""
        input_log = """
        ↘ CALL main.py:10 process_data() [frame:1][thread:1]
          ▷ main.py:11 step_1()
          ▷ main.py:12 step_2()
          ▷ main.py:13 step_3()
          ▷ main.py:14 step_4()
          ▷ main.py:15 step_5()
          ▷ main.py:16 step_6()
          ▷ main.py:17 step_7()
          ▷ main.py:18 step_8()
          ▷ main.py:19 step_9()
          ▷ main.py:20 step_10()
        ↗ RETURN main.py process_data() → result [frame:1]
        """

        main_padding = " " * len("main.py")
        expected_output = f"""
        ↘ CALL main.py:10 process_data() [frame:1][thread:1]
        \t▷ {main_padding}:11 step_1()
        \t▷ {main_padding}:12 step_2()
        \t▷ {main_padding}:13 step_3()
        \t▷ {main_padding}:14 step_4()
        \t▷ {main_padding}:15 step_5()
        \t▷ {main_padding}:16 step_6()
        \t▷ {main_padding}:17 step_7()
        \t▷ {main_padding}:18 step_8()
        \t▷ {main_padding}:19 step_9()
        \t▷ {main_padding}:20 step_10()
        ↗ RETURN main.py process_data() → result [frame:1]
        """
        self._run_test_case(input_log, expected_output)

    def test_real_world_trace_patterns(self) -> None:
        """Tests patterns commonly found in real trace logs."""
        input_log = """
        ↘ MODULE my_module.py:0 <module>() [frame:1][thread:123]
          ▷ my_module.py:1 import os
          ▷ my_module.py:2 import sys
          ↘ CALL my_module.py:5 main() [frame:2][thread:123]
            ▷ my_module.py:6 print("Starting")
            ↘ CALL utils/network.py:10 fetch_data() [frame:3][thread:123]
              ▷ utils/network.py:11 import requests
              ↘ CALL <built-in>:0 __import__() [frame:4][thread:123]
              ↗ RETURN <built-in> __import__() → <module> [frame:4]
              ▷ utils/network.py:12 response = requests.get("https://example.com")
              ↘ CALL requests/api.py:100 get() [frame:5][thread:123]
                ▷ requests/api.py:101 session = Session()
                ↘ CALL requests/sessions.py:50 Session() [frame:6][thread:123]
                  ▷ requests/sessions.py:51 self = object.__new__(cls)
                ↗ RETURN requests/sessions.py Session() → <Session> [frame:6]
                ▷ requests/api.py:102 return session.request('GET', url)
              ↗ RETURN requests/api.py get() → <Response> [frame:5]
              ▷ utils/network.py:13 return response.text
            ↗ RETURN utils/network.py fetch_data() → 'data' [frame:3]
            ▷ my_module.py:7 print("Data received")
            ↘ CALL my_module.py:9 process_data() [frame:7][thread:123]
              ▷ my_module.py:10 data = data.upper()
              ↘ CALL <built-in>:0 upper() [frame:8][thread:123]
              ↗ RETURN <built-in> upper() → 'DATA' [frame:8]
              ▷ my_module.py:11 return data
            ↗ RETURN my_module.py process_data() → 'DATA' [frame:7]
            ▷ my_module.py:12 print("Processing complete")
          ↗ RETURN my_module.py main() → None [frame:2]
          ▷ my_module.py:13 sys.exit(0)
        """

        module_padding = " " * len("my_module.py")
        utils_padding = " " * len("utils/network.py")
        builtin_padding = " " * len("<built-in>")
        requests_api_padding = " " * len("requests/api.py")
        requests_sessions_padding = " " * len("requests/sessions.py")

        expected_output = f"""
        ↘ MODULE my_module.py:0 <module>() [frame:1][thread:123]
        \t▷ {module_padding}:1 import os
        \t▷ {module_padding}:2 import sys
        \t↘ CALL my_module.py:5 main() [frame:2][thread:123]
        \t\t▷ {module_padding}:6 print("Starting")
        \t\t↘ CALL utils/network.py:10 fetch_data() [frame:3][thread:123]
        \t\t\t▷ {utils_padding}:11 import requests
        \t\t\t↘ CALL <built-in>:0 __import__() [frame:4][thread:123]
        \t\t\t↗ RETURN <built-in> __import__() → <module> [frame:4]
        \t\t\t▷ {utils_padding}:12 response = requests.get("https://example.com")
        \t\t\t↘ CALL requests/api.py:100 get() [frame:5][thread:123]
        \t\t\t\t▷ {requests_api_padding}:101 session = Session()
        \t\t\t\t↘ CALL requests/sessions.py:50 Session() [frame:6][thread:123]
        \t\t\t\t\t▷ {requests_sessions_padding}:51 self = object.__new__(cls)
        \t\t\t\t↗ RETURN requests/sessions.py Session() → <Session> [frame:6]
        \t\t\t\t▷ {requests_api_padding}:102 return session.request('GET', url)
        \t\t\t↗ RETURN requests/api.py get() → <Response> [frame:5]
        \t\t\t▷ {utils_padding}:13 return response.text
        \t\t↗ RETURN utils/network.py fetch_data() → 'data' [frame:3]
        \t\t▷ {module_padding}:7 print("Data received")
        \t\t↘ CALL my_module.py:9 process_data() [frame:7][thread:123]
        \t\t\t▷ {module_padding}:10 data = data.upper()
        \t\t\t↘ CALL <built-in>:0 upper() [frame:8][thread:123]
        \t\t\t↗ RETURN <built-in> upper() → 'DATA' [frame:8]
        \t\t\t▷ {module_padding}:11 return data
        \t\t↗ RETURN my_module.py process_data() → 'DATA' [frame:7]
        \t\t▷ {module_padding}:12 print("Processing complete")
        \t↗ RETURN my_module.py main() → None [frame:2]
        \t▷ {module_padding}:13 sys.exit(0)
        """
        self._run_test_case(input_log, expected_output)


if __name__ == "__main__":
    unittest.main()
