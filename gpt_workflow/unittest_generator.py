import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple

import colorama
from colorama import Fore, Style

# Add project root to sys.path to allow importing project modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from gpt_workflow.utils.code_formatter import CodeFormatter
from llm_query import (
    FileSearchResult,
    FileSearchResults,
    MatchResult,
    ModelSwitch,
    query_symbol_service,
)


class UnitTestGenerator:
    """
    Generates unit tests for a Python function based on a runtime analysis report
    produced by the CallAnalyzer.
    """

    def __init__(self, report_path: str, model_name: str = "deepseek-r1", checker_model_name: str = "deepseek-checker"):
        """
        Initializes the UnitTestGenerator.

        Args:
            report_path: Path to the call_analysis_report.json file.
            model_name: The name of the language model to use for core test generation.
            checker_model_name: The name of the model for utility tasks (naming, merging).
        """
        self.report_path = Path(report_path)
        self.model_switch = ModelSwitch()
        self.formatter = CodeFormatter()
        self.generator_model_name = model_name
        self.checker_model_name = checker_model_name
        self.analysis_data = self._load_report()

    def _load_report(self) -> Dict[str, Any]:
        """Loads and validates the analysis JSON report."""
        if not self.report_path.exists():
            print(Fore.RED + f"Error: Report file not found at '{self.report_path}'")
            sys.exit(1)
        try:
            with open(self.report_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(Fore.RED + f"Error: Failed to load or parse report file: {e}")
            sys.exit(1)

    def _extract_code_from_response(self, response: str) -> Optional[str]:
        """
        Extracts a Python code block from the LLM's response using markdown syntax.
        """
        # Regex to find code block ```python ... ```
        match = re.search(r"```python\n(.*?)\n```", response, re.DOTALL)
        if match:
            return match.group(1).strip()

        print(Fore.YELLOW + "Warning: Could not find a '```python ... ```' block. Trying to find any code block.")
        # Fallback to any ```...``` block
        match = re.search(r"```\n(.*?)\n```", response, re.DOTALL)
        if match:
            return match.group(1).strip()

        return None

    def _recursive_search(self, record: Dict, target_func: str, found_calls: List[Dict]):
        """Recursively search for call records of a target function within a call tree."""
        if not isinstance(record, dict):
            return

        # Check if the current record is for the target function
        if record.get("func_name") == target_func:
            found_calls.append(record)

        # Search within nested calls in the 'events' list
        for event in record.get("events", []):
            if event.get("type") == "call" and isinstance(event.get("data"), dict):
                # The data of a 'call' event is another call record
                self._recursive_search(event.get("data"), target_func, found_calls)

    def _find_all_calls_for_function(self, target_func: str) -> List[Dict]:
        """

        Finds all call records for a specific function by traversing the entire analysis data.
        """
        all_calls = []
        # Iterate over all top-level entry points recorded in the analysis data
        for _, funcs in self.analysis_data.items():  # filename not used
            for _, records in funcs.items():  # func_name not used
                for record in records:
                    self._recursive_search(record, target_func, all_calls)
        return all_calls

    def _suggest_test_file_and_class_names(
        self, file_path: str, target_func: str, file_content: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """Asks the LLM to suggest a filename and class name for the test suite."""
        # If file content is not provided, we can't provide context to the LLM.
        # In symbol mode, this might be acceptable if the function name is descriptive.
        source_code_context = ""
        if file_content:
            source_code_context = f"""
**Source Code (for context):**
```python
{file_content}
```
"""

        prompt = dedent(f"""
            You are a Python testing expert. Based on the following function and its source file, suggest a suitable filename and a `unittest.TestCase` class name for its test suite.

            **Source File Path:** {file_path}
            **Target Function Name:** {target_func}
            {source_code_context}

            **Your Task:**
            Provide your suggestions in a JSON format. The filename must follow the `test_*.py` convention. The class name should be descriptive.

            **Example Output:**
            ```json
            {{
              "file_name": "test_my_module.py",
              "class_name": "TestMyModuleFunctionality"
            }}
            ```

            **Response:**
        """).strip()

        print(Fore.CYAN + f"Querying LLM ({self.checker_model_name}) for file and class name suggestions...")
        response_text = self.model_switch.query(self.checker_model_name, prompt, stream=False)

        try:
            # Extract JSON from markdown or raw response
            json_match = re.search(r"```json\n(.*?)\n```", response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Fallback for raw JSON object in the response
                json_str_match = re.search(r"{\s*\"file_name\":.*}", response_text, re.DOTALL)
                if not json_str_match:
                    raise ValueError("No JSON object found in the response.")
                json_str = json_str_match.group(0)

            data = json.loads(json_str)
            file_name = data.get("file_name")
            class_name = data.get("class_name")

            if not (isinstance(file_name, str) and isinstance(class_name, str)):
                raise ValueError("Invalid data types for file_name or class_name in JSON.")

            return file_name, class_name
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(Fore.RED + f"Error: Could not parse suggestions from LLM response: {e}")
            print(Fore.YELLOW + "--- LLM Response ---")
            print(response_text)
            print(Fore.YELLOW + "--------------------")
            return None, None

    def _validate_and_resolve_path(self, output_dir: str, filename: str) -> Optional[Path]:
        """Validates the filename and resolves it to a secure path within the output directory."""
        # Sanitize to prevent path traversal
        base_filename = os.path.basename(filename)
        if base_filename != filename:
            print(Fore.RED + f"Error: Invalid characters in filename '{filename}'. Path traversal is not allowed.")
            return None

        if not base_filename.startswith("test_") or not base_filename.endswith(".py"):
            print(Fore.YELLOW + f"Warning: Filename '{base_filename}' does not follow the 'test_*.py' convention.")

        try:
            output_dir_path = Path(output_dir).resolve()
            output_dir_path.mkdir(parents=True, exist_ok=True)

            output_file_path = (output_dir_path / base_filename).resolve()

            # Security check: ensure the final path is within the intended directory
            if output_dir_path != output_file_path.parent:
                error_msg = (
                    f"Error: Security validation failed. The path '{output_file_path}' "
                    f"is outside the allowed directory '{output_dir_path}'."
                )
                print(Fore.RED + error_msg)
                return None

            return output_file_path
        except (OSError, RuntimeError) as e:
            print(Fore.RED + f"Error resolving path: {e}")
            return None

    def _merge_tests(self, existing_code: str, new_code_block: str, output_path: str) -> Optional[str]:
        """Asks the LLM to merge new test cases into an existing test file."""
        prompt = dedent(f"""
            You are an expert Python developer specializing in refactoring and maintaining test suites. Your task is to intelligently merge new test cases into an existing test file.

            **1. CONTEXT: EXISTING TEST FILE**
            This is the current content of the test file.

            [File Path]: {output_path}
            [Existing Code]:
            ```python
            {existing_code}
            ```

            **2. CONTEXT: NEWLY GENERATED TEST CASES**
            These are new test cases that need to be added to the file. They are already formatted as a complete test class.

            [New Test Code to Add]:
            ```python
            {new_code_block}
            ```

            **3. YOUR TASK: MERGE THE CODE**
            - **Combine Imports:** Merge the imports from both blocks, removing duplicates.
            - **Merge into Class:** Add the new test methods from the new code into the existing `unittest.TestCase` class. If the class names differ, use the existing class name.
            - **Preserve Structure:** Maintain the overall structure and style of the existing file.
            - **Do Not Remove Existing Tests:** Ensure all original tests are kept.
            - **Completeness:** The final output must be a single, complete, and runnable Python file.

            **IMPORTANT**: Your entire response must be only the merged Python code, enclosed within a single Python markdown block (e.g., ```python ... ```). Do not add any explanations or text outside the code block.
        """).strip()

        print(Fore.YELLOW + f"Querying language model ({self.checker_model_name}) to merge test files...")
        response_text = self.model_switch.query(self.checker_model_name, prompt, stream=False)
        return self._extract_code_from_response(response_text)

    def _generate_relative_sys_path_snippet(self, test_file_path: Path, project_root_path: Path) -> str:
        """
        Generates a portable sys.path setup snippet based on the relative
        location of the test file to the project root.
        """
        try:
            # Get the directory of the test file
            test_dir = test_file_path.parent.resolve()
            proj_root = project_root_path.resolve()

            # Calculate the relative path from the test directory to the project root
            relative_path_to_root = os.path.relpath(proj_root, test_dir)

            # Convert the relative path to a sequence of .parent calls
            if relative_path_to_root == ".":
                # Test file is in the project root, so its parent is the root
                path_traversal = "parent"
            else:
                # Count the number of ".." parts to determine how many levels to go up
                depth = len(Path(relative_path_to_root).parts)
                path_traversal = ".".join(["parent"] * depth)

            sys_path_code = f"project_root = Path(__file__).resolve().{path_traversal}"

        except (ValueError, OSError) as e:
            # Fallback for complex cases or errors (e.g., different drives on Windows)
            # This creates a non-portable but functional path.
            print(Fore.YELLOW + f"Warning: Could not determine relative path: {e}. Falling back to absolute path.")
            sys_path_code = f"project_root = Path(r'{project_root_path.resolve()}')"

        return dedent(f"""
        import sys
        from pathlib import Path

        # Add the project root to sys.path to allow for module imports.
        # This is dynamically calculated based on the test file's location.
        {sys_path_code}
        sys.path.insert(0, str(project_root))
        """).strip()

    def _build_prompt(
        self,
        target_func: str,
        call_record: Dict,
        test_class_name: str,
        module_to_test: str,
        project_root_path: str,
        output_file_abs_path: str,
        file_path: Optional[str] = None,
        file_content: Optional[str] = None,
        symbol_context: Optional[Dict[str, Dict]] = None,
        existing_code: Optional[str] = None,
    ) -> str:
        """Dispatcher for building the prompt based on available context."""
        if symbol_context:
            return self._build_symbol_based_prompt(
                symbol_context=symbol_context,
                target_func=target_func,
                call_record=call_record,
                test_class_name=test_class_name,
                module_to_test=module_to_test,
                project_root_path=project_root_path,
                output_file_abs_path=output_file_abs_path,
                existing_code=existing_code,
            )
        elif file_content and file_path:
            return self._build_file_based_prompt(
                file_path=file_path,
                file_content=file_content,
                target_func=target_func,
                call_record=call_record,
                test_class_name=test_class_name,
                module_to_test=module_to_test,
                project_root_path=project_root_path,
                output_file_abs_path=output_file_abs_path,
                existing_code=existing_code,
            )
        else:
            raise ValueError("Either symbol_context or file_content must be provided to build a prompt.")

    def _build_file_based_prompt(
        self,
        file_path: str,
        file_content: str,
        target_func: str,
        call_record: Dict,
        test_class_name: str,
        module_to_test: str,
        project_root_path: str,
        output_file_abs_path: str,
        existing_code: Optional[str] = None,
    ) -> str:
        """Constructs the detailed prompt for the LLM using full file content."""

        sys_path_setup_snippet = self._generate_relative_sys_path_snippet(
            Path(output_file_abs_path), Path(project_root_path)
        )
        call_record_json = json.dumps(call_record, indent=2, default=str)

        action_description, existing_code_section, code_structure_guidance = self._get_common_prompt_sections(
            test_class_name, existing_code
        )

        prompt = dedent(f"""
        You are an expert Python developer specializing in writing clean, modular, and robust unit tests.
        Your task is to {action_description} for the function `{target_func}`.

        **1. CRITICAL INSTRUCTION: HOW TO IMPORT THE CODE TO TEST**
        You MUST NOT copy the source code of the function into the test file. Instead, you MUST import it.
        - **Project Root Directory:** `{project_root_path}`
        - **Module to Test:** `{module_to_test}`
        - **How to Import the Target Function:** `from {module_to_test} import {target_func}`
        - **`sys.path` Setup:** To ensure the import works correctly, you MUST include this exact code snippet at the top of the test file. It dynamically finds the project root.
          ```python
          {sys_path_setup_snippet}
          ```

        **2. CONTEXT: SOURCE CODE (FOR REFERENCE ONLY)**
        This is the content of the file where the target function resides. Use it to understand the function's logic, but DO NOT copy it.

        [File Path]: {file_path}
        [File Content]:
        ```python
        {file_content}
        ```

        **3. CONTEXT: CAPTURED RUNTIME DATA for `{target_func}`**
        This JSON object represents a single execution of the function, including its arguments, return value, and any calls it made to other functions (dependencies).

        [Runtime Call Record]
        ```json
        {call_record_json}
        ```

        **4. INTELLIGENT MOCKING STRATEGY**
        {self._get_mocking_guidance(target_func, module_to_test)}

        **5. YOUR TASK: GENERATE THE TEST CODE**
        {code_structure_guidance}
        {existing_code_section}

        **IMPORTANT**: Your entire response must be only the Python code, enclosed within a single Python markdown block (e.g., ```python ... ```). Do not add any explanations or text outside the code block.
        """).strip()
        return prompt

    def _build_symbol_based_prompt(
        self,
        symbol_context: Dict[str, Dict],
        target_func: str,
        call_record: Dict,
        test_class_name: str,
        module_to_test: str,
        project_root_path: str,
        output_file_abs_path: str,
        existing_code: Optional[str] = None,
    ) -> str:
        """Constructs the detailed prompt for the LLM using precise symbol context."""
        sys_path_setup_snippet = self._generate_relative_sys_path_snippet(
            Path(output_file_abs_path), Path(project_root_path)
        )
        call_record_json = json.dumps(call_record, indent=2, default=str)

        context_code_str = ""
        for name, data in symbol_context.items():
            context_code_str += f"# Symbol: {name}\n"
            context_code_str += f"# File: {data.get('file_path', '?')}:{data.get('start_line', '?')}\n"
            context_code_str += f"{data.get('code', '# Code not found')}\n\n"

        action_description, existing_code_section, code_structure_guidance = self._get_common_prompt_sections(
            test_class_name, existing_code
        )

        prompt = dedent(f"""
        You are an expert Python developer specializing in writing clean, modular, and robust unit tests.
        Your task is to {action_description} for the function `{target_func}`.

        **1. CRITICAL INSTRUCTION: HOW TO IMPORT THE CODE TO TEST**
        You MUST NOT copy the source code of the function into the test file. Instead, you MUST import it.
        - **Project Root Directory:** `{project_root_path}`
        - **Module to Test:** `{module_to_test}`
        - **How to Import the Target Function:** `from {module_to_test} import {target_func}`
        - **`sys.path` Setup:** To ensure the import works correctly, you MUST include this exact code snippet at the top of the test file. It dynamically finds the project root.
          ```python
          {sys_path_setup_snippet}
          ```

        **2. CONTEXT: RELEVANT SOURCE CODE (PRECISION MODE)**
        Instead of the full file, you are given the precise source code for the target function and all other functions it called during a sample execution. Use this context to understand the logic. DO NOT copy this code into the test file; import the target function as instructed.

        [Relevant Code Snippets]
        ```python
        {context_code_str.strip()}
        ```

        **3. CONTEXT: CAPTURED RUNTIME DATA for `{target_func}`**
        This JSON object represents a single execution of the function, including its arguments, return value, and any calls it made to other functions (dependencies).

        [Runtime Call Record]
        ```json
        {call_record_json}
        ```

        **4. INTELLIGENT MOCKING STRATEGY**
        {self._get_mocking_guidance(target_func, module_to_test)}

        **5. YOUR TASK: GENERATE THE TEST CODE**
        {code_structure_guidance}
        {existing_code_section}

        **IMPORTANT**: Your entire response must be only the Python code, enclosed within a single Python markdown block (e.g., ```python ... ```). Do not add any explanations or text outside the code block.
        """).strip()
        return prompt

    def _get_common_prompt_sections(self, test_class_name: str, existing_code: Optional[str]) -> Tuple[str, str, str]:
        """Generates common prompt sections for action, existing code, and structure."""
        if existing_code:
            action_description = f"add a new test method to the existing `unittest.TestCase` class `{test_class_name}`"
            existing_code_section = f"""
[Existing Test File Content]
```python
{existing_code}
```
"""
        else:
            action_description = f"create a new `unittest.TestCase` class named `{test_class_name}`"
            existing_code_section = ""

        code_structure_guidance = (
            "- **Framework:** Use Python's built-in `unittest` module.\n"
            "- **Test Method:** Create a new, descriptively named test method (e.g., `test_..._case_N`).\n"
            "- **Mocking:** Based on the **INTELLIGENT MOCKING STRATEGY**, mock only the necessary dependencies from the `events` list.\n"
            "    - Configure mocks to behave exactly as recorded (return value or exception).\n"
            "    - Verify mocks were called correctly using `mock_instance.assert_called_once_with(...)`.\n"
            "- **Assertions:**\n"
            "    - Use `self.assertEqual()` for return values.\n"
            "    - Use `self.assertRaises()` for exceptions.\n"
            "- **Code Structure:**\n"
            "  - Generate a complete, runnable Python code snippet.\n"
            "  - Include all necessary imports (`unittest`, `unittest.mock`, "
            "the `sys.path` setup, and the function to be tested).\n"
            "  - {action}"
        ).format(
            action="Add the new method to the existing class."
            if existing_code
            else "Define the test class and a main execution block (`if __name__ == '__main__': unittest.main()`)."
        )
        return action_description, existing_code_section, code_structure_guidance

    def _get_mocking_guidance(self, target_func: str, module_to_test: str) -> str:
        """Generates the standard mocking guidance section for the prompt."""
        return dedent(f"""
        Your goal is to create a valuable and robust test. Do not mock everything blindly.
        - **DO Mock:**
            - Functions with external side effects (e.g., network requests, database queries, file I/O, `time.sleep`).
            - Functions that are non-deterministic (e.g., `datetime.now()`, `random.randint()`).
            - Dependencies that are slow or complex, to isolate the function under test.
            - In the provided trace, `faulty_sub_function` is a good candidate for mocking because we want to test how `{target_func}` handles its success and failure cases independently.
        - **DO NOT Mock:**
            - Simple, pure, deterministic helper functions within your own project (e.g., a function that just performs a calculation). Letting these simple functions run makes the test more meaningful and less brittle.

        - **How to Patch:** When using `unittest.mock.patch`, the path must be based on the module where the dependency is *used*. For example, to patch `dependency_func` which is imported and used in `{module_to_test}`, use `patch('{module_to_test}.dependency_func', ...)`.
        """).strip()

    def generate(self, target_func: str, output_dir: str, auto_confirm: bool = False, use_symbol_service: bool = True):
        """
        Generates the unit test file for the specified function.

        Args:
            target_func: The name of the function to generate tests for.
            output_dir: Directory to save the generated test file(s).
            auto_confirm: If True, automatically accept all suggestions without prompting the user.
            use_symbol_service: If True, use symbol service to get precise context.
        """
        all_calls = self._find_all_calls_for_function(target_func)
        if not all_calls:
            print(Fore.RED + f"No call records found for function '{target_func}'")
            return False

        target_file_path = self._resolve_target_file_path(all_calls[0]["original_filename"])
        if not target_file_path:
            return False

        symbol_context = None
        file_content = None
        if use_symbol_service:
            print(Fore.CYAN + "\nUsing symbol service to gather precise code context...")
            symbol_context = self._get_symbols_for_calls(all_calls)
            if not symbol_context:
                print(Fore.YELLOW + "Warning: Failed to get symbol context. Falling back to full file content.")
                file_content = self._read_file_content(target_file_path)
                if not file_content:
                    return False
        else:
            file_content = self._read_file_content(target_file_path)
            if not file_content:
                return False

        suggested_file, suggested_class = self._suggest_test_file_and_class_names(
            str(target_file_path), target_func, file_content
        )
        if not (suggested_file and suggested_class):
            print(Fore.RED + "Could not get suggestions for file/class names.")
            return False

        final_file_name, final_class_name = self._get_final_names(suggested_file, suggested_class, auto_confirm)

        output_path = self._validate_and_resolve_path(output_dir, final_file_name)
        if not output_path:
            return False

        module_to_test = self._get_module_path(target_file_path)
        if not module_to_test:
            return False

        newly_generated_code = self._generate_test_cases(
            all_calls=all_calls,
            target_func=target_func,
            target_file_path=target_file_path,
            file_content=file_content,
            symbol_context=symbol_context,
            test_class_name=final_class_name,
            module_to_test=module_to_test,
            output_path=output_path,
        )
        if not newly_generated_code:
            return False

        final_code_to_write = self._handle_existing_file(output_path, newly_generated_code, auto_confirm)
        if not final_code_to_write:
            return False

        return self._write_final_code(output_path, final_code_to_write)

    def _get_symbols_for_calls(self, all_calls: List[Dict]) -> Optional[Dict[str, Dict]]:
        """
        Gathers all unique function locations from call records and fetches their
        source code using the symbol service.
        """
        locations = set()
        for record in all_calls:
            # Add the target function itself
            if "original_filename" in record and "original_lineno" in record:
                locations.add((record["original_filename"], record["original_lineno"]))

            # Add all sub-calls from the events trace
            for event in record.get("events", []):
                if event.get("type") == "call":
                    data = event.get("data", {})
                    if "filename" in data and "lineno" in data:
                        # Exclude calls to self to avoid redundant lookups
                        if data.get("func_name") != record.get("func_name"):
                            locations.add((data["filename"], data["lineno"]))

        if not locations:
            print(Fore.YELLOW + "No symbol locations found in call records.")
            return None

        file_to_lines = defaultdict(list)
        for filename, lineno in locations:
            if isinstance(filename, str) and isinstance(lineno, int):
                file_to_lines[filename].append(lineno)

        file_results = []
        for filename, lines in file_to_lines.items():
            matches = [MatchResult(line=lineno, column_range=(0, 0), text="") for lineno in lines]
            file_results.append(FileSearchResult(file_path=filename, matches=matches))

        if not file_results:
            return None

        search_results = FileSearchResults(results=file_results)

        print(Fore.CYAN + f"Querying symbol service for {len(locations)} unique locations...")
        symbol_results = query_symbol_service(search_results, 128 * 1024)

        if symbol_results and isinstance(symbol_results, dict):
            print(Fore.GREEN + f"Successfully retrieved {len(symbol_results)} symbols.")
            return symbol_results
        else:
            print(Fore.RED + "Failed to retrieve symbol information from the service.")
            return None

    def _resolve_target_file_path(self, original_filename: str) -> Optional[Path]:
        """Resolve and validate the target file path."""
        target_file_path = Path(original_filename)
        print(Fore.GREEN + f"Found calls from file '{target_file_path}'")

        if not target_file_path.is_absolute():
            project_root_path = project_root.resolve()
            target_file_path = (project_root_path / target_file_path).resolve()

        return target_file_path

    def _read_file_content(self, file_path: Path) -> Optional[str]:
        """Read and return file content with error handling."""
        try:
            return file_path.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            print(Fore.RED + f"File not found: {file_path}: {e}")
        except UnicodeDecodeError as e:
            print(Fore.RED + f"Encoding error in {file_path}: {e}")
        return None

    def _get_final_names(self, suggested_file: str, suggested_class: str, auto_confirm: bool) -> tuple[str, str]:
        """Get final file and class names with user confirmation."""
        print(Fore.GREEN + Style.BRIGHT + "\nLLM Suggestions:")
        print(f"  - Suggested File Name: {suggested_file}")
        print(f"  - Suggested Class Name: {suggested_class}")

        if auto_confirm:
            print(Fore.YELLOW + "Auto-confirming suggestions")
            return suggested_file, suggested_class

        file_name_input = input(Fore.CYAN + f"Enter file name or press Enter to accept [{suggested_file}]: ").strip()
        class_name_input = input(Fore.CYAN + f"Enter class name or press Enter to accept [{suggested_class}]: ").strip()
        return file_name_input or suggested_file, class_name_input or suggested_class

    def _get_module_path(self, target_file_path: Path) -> Optional[str]:
        """Get module import path relative to project root."""
        try:
            project_root_path = project_root.resolve()
            module_path = target_file_path.relative_to(project_root_path).with_suffix("").as_posix().replace("/", ".")
            if module_path.endswith(".__init__"):
                module_path = module_path[:-9]
            return module_path
        except ValueError:
            error_msg = (
                f"Could not determine module path. Is '{target_file_path}' "
                f"outside of project root '{project_root_path}'?"
            )
            print(Fore.RED + f"Error: {error_msg}")
            return None

    def _generate_test_cases(
        self,
        all_calls: list,
        target_func: str,
        target_file_path: Path,
        test_class_name: str,
        module_to_test: str,
        output_path: Path,
        file_content: Optional[str],
        symbol_context: Optional[Dict[str, Dict]],
    ) -> Optional[str]:
        """Generate test cases for all call records."""
        newly_generated_code = None
        total_cases = len(all_calls)

        for i, call_record in enumerate(all_calls):
            print(Fore.CYAN + f"\nGenerating Test Case {i + 1}/{total_cases} for '{target_func}'")
            print(Fore.CYAN + f"Querying LLM ({self.generator_model_name})...")

            prompt = self._build_prompt(
                file_path=str(target_file_path),
                file_content=file_content,
                symbol_context=symbol_context,
                target_func=target_func,
                call_record=call_record,
                test_class_name=test_class_name,
                module_to_test=module_to_test,
                project_root_path=str(project_root.resolve()),
                output_file_abs_path=str(output_path.resolve()),
                existing_code=newly_generated_code,
            )

            response_text = self.model_switch.query(self.generator_model_name, prompt, stream=False)
            extracted_code = self._extract_code_from_response(response_text)

            if extracted_code:
                newly_generated_code = extracted_code
                print(Fore.GREEN + f"Successfully generated test case {i + 1}")
            else:
                print(Fore.RED + f"Failed to extract code for test case {i + 1}")
                continue

        return newly_generated_code

    def _handle_existing_file(self, output_path: Path, new_code: str, auto_confirm: bool) -> Optional[str]:
        """Handle existing test file with merge/overwrite options."""
        if not output_path.exists():
            return new_code

        print(Fore.YELLOW + f"\nFile '{output_path}' already exists")

        if auto_confirm:
            print(Fore.YELLOW + "Auto-selecting [M]erge")
            choice = "M"
        else:
            choice = self._get_user_choice()
            if choice == "C":
                return None

        if choice == "M":
            print(Fore.CYAN + "Merging new tests into existing file...")
            existing_code = output_path.read_text(encoding="utf-8")
            return self._merge_tests(existing_code, new_code, str(output_path))

        return new_code if choice == "O" else None

    def _get_user_choice(self) -> str:
        """Get user choice for file conflict resolution."""
        while True:
            user_input = (
                input(Fore.CYAN + "Do you want to [M]erge, [O]verwrite or [C]ancel? (Default: M) ").strip().upper()
            )
            if not user_input:
                return "M"
            if user_input in ["M", "O", "C"]:
                return user_input
            print(Fore.RED + "Invalid choice. Please enter M, O, or C")

    def _write_final_code(self, output_path: Path, code: str) -> bool:
        """Formats and writes the final code to a file."""
        try:
            print(Fore.CYAN + "\nFormatting generated code with ruff...")
            formatted_code = self.formatter.format_code(code)

            print(Fore.GREEN + f"Saving tests to '{output_path}'...")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(formatted_code)
            print(Fore.GREEN + "Done!")
            return True
        except IOError as e:
            print(Fore.RED + f"Failed to write file: {e}")
            return False


def parse_args():
    """Parses command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate Unit Tests from a Call Analysis Report.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--report-file",
        required=True,
        help="Path to the call_analysis_report.json file generated by the tracer.",
    )
    parser.add_argument(
        "--target-function",
        required=True,
        help="The name of the function to generate tests for.",
    )
    parser.add_argument(
        "--output-dir",
        default="generated_tests",
        help="Directory to save the generated test file(s). Default: 'generated_tests'",
    )
    parser.add_argument(
        "--model",
        default="deepseek-r1",
        help="Specify the main language model for test generation (e.g., deepseek-r1, gpt-4).",
    )
    parser.add_argument(
        "--checker-model",
        default="deepseek-checker",
        help="Specify the model for utility tasks like suggesting names "
        "and merging files. Defaults to a faster/cheaper model.",
    )
    parser.add_argument(
        "--use-symbol-service",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable using the symbol service to fetch precise code context. "
        "Use --no-use-symbol-service to disable. (default: enabled)",
    )
    parser.add_argument(
        "-y",
        "--auto-confirm",
        action="store_true",
        help="Automatically confirm all interactive prompts, such as file/class name suggestions and merge choices.",
    )
    return parser.parse_args()


def main():
    """Main entry point for the unit test generator."""
    args = parse_args()

    print(Fore.BLUE + Style.BRIGHT + "\nStarting Unit Test Generation Workflow")
    print(Fore.BLUE + "=" * 50)
    print(f"{'Report File:':<20} {args.report_file}")
    print(f"{'Target Function:':<20} {args.target_function}")
    print(f"{'Output Directory:':<20} {args.output_dir}")
    print(f"{'Generator Model:':<20} {args.model}")
    print(f"{'Checker Model:':<20} {args.checker_model}")
    print(f"{'Symbol Service:':<20} {'Enabled' if args.use_symbol_service else 'Disabled'}")
    if args.auto_confirm:
        print(f"{'Auto Confirm:':<20} {Fore.YELLOW}Enabled")
    print(Fore.BLUE + "=" * 50)

    generator = UnitTestGenerator(
        report_path=args.report_file, model_name=args.model, checker_model_name=args.checker_model
    )
    generator.generate(
        target_func=args.target_function,
        output_dir=args.output_dir,
        auto_confirm=args.auto_confirm,
        use_symbol_service=args.use_symbol_service,
    )


if __name__ == "__main__":
    main()
