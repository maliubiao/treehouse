import argparse
import datetime
import json
import multiprocessing
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple

from colorama import Fore, Style

# Add project root to sys.path to allow importing project modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from debugger import tracer
from gpt_workflow.utils.code_formatter import CodeFormatter
from llm_query import (
    FileSearchResult,
    FileSearchResults,
    MatchResult,
    ModelSwitch,
    query_symbol_service,
)


class TracingModelSwitch(ModelSwitch):
    """
    A wrapper around ModelSwitch that adds logging for LLM queries.
    """

    def __init__(self, trace_llm: bool = False, trace_dir: str = "llm_traces", **kwargs):
        """
        Initializes the TracingModelSwitch.

        Args:
            trace_llm: If True, log LLM prompts and responses.
            trace_dir: Directory to save LLM traces.
            **kwargs: Arguments to pass to the parent ModelSwitch constructor.
        """
        super().__init__(**kwargs)
        self.trace_llm = trace_llm
        self.trace_run_dir: Optional[Path] = None
        if self.trace_llm:
            trace_dir_path = Path(trace_dir)
            run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.trace_run_dir = trace_dir_path / run_timestamp
            self.trace_run_dir.mkdir(parents=True, exist_ok=True)

    def query(self, model_name: str, prompt: str, **kwargs) -> str:
        """
        Executes a query and logs the prompt and response if tracing is enabled.
        """
        # The parent query method returns a string, despite its 'dict' type hint.
        response_content = super().query(model_name, prompt, **kwargs)

        if self.trace_llm and self.trace_run_dir:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            # Sanitize model_name for filename
            safe_model_name = re.sub(r'[\\/*?:"<>|]', "_", model_name)
            trace_file_path = self.trace_run_dir / f"{timestamp}_{safe_model_name}.log"

            log_parts = [
                "--- PROMPT ---",
                f"Model: {model_name}",
                f"Timestamp: {datetime.datetime.now().isoformat()}",
                "----------------",
                "",
                prompt,
                "",
                "",
                "--- RESPONSE ---",
                "----------------",
                "",
                response_content,
            ]
            trace_content = "\n".join(log_parts)

            try:
                with trace_file_path.open("w", encoding="utf-8") as f:
                    f.write(trace_content)
                print(Fore.YELLOW + f"LLM trace saved to: {trace_file_path}")
            except IOError as e:
                print(Fore.RED + f"Error saving LLM trace: {e}")

        return response_content


class UnitTestGenerator:
    """
    Generates unit tests for a Python function based on a runtime analysis report
    produced by the CallAnalyzer.
    """

    def __init__(
        self,
        report_path: str,
        model_name: str = "deepseek-r1",
        checker_model_name: str = "deepseek-checker",
        trace_llm: bool = False,
        llm_trace_dir: str = "llm_traces",
    ):
        """
        Initializes the UnitTestGenerator.

        Args:
            report_path: Path to the call_analysis_report.json file.
            model_name: The name of the language model to use for core test generation.
            checker_model_name: The name of the model for utility tasks (naming, merging).
            trace_llm: If True, log LLM prompts and responses.
            llm_trace_dir: Directory to save LLM traces.
        """
        self.report_path = Path(report_path)
        self.model_switch = TracingModelSwitch(trace_llm=trace_llm, trace_dir=llm_trace_dir)
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

    def _find_all_calls_for_targets(self, target_funcs: List[str]) -> Dict[str, List[Dict]]:
        """
        Finds all call records for a list of target functions by traversing the
        entire analysis data tree once. This is more efficient than searching
        for each function individually.

        Returns:
            A dictionary mapping each found target function name to a list of its call records.
        """
        target_set = set(target_funcs)
        calls_by_func = defaultdict(list)
        frame_id_seen = set()

        def _recursive_search(record: Dict):
            """Inner recursive helper to traverse the call tree."""
            if not isinstance(record, dict):
                return

            # Check if the current record is for one of the target functions
            func_name = record.get("func_name")
            if func_name in target_set:
                if record["frame_id"] not in frame_id_seen:
                    frame_id_seen.add(record["frame_id"])
                    calls_by_func[func_name].append(record)

            # Search within nested calls in the 'events' list
            for event in record.get("events", []):
                if event.get("type") == "call" and isinstance(event.get("data"), dict):
                    # The data of a 'call' event is another call record
                    _recursive_search(event.get("data"))

        # Iterate over all top-level entry points recorded in the analysis data
        for funcs_data in self.analysis_data.values():
            for records in funcs_data.values():
                for record in records:
                    _recursive_search(record)

        return calls_by_func

    def _suggest_test_file_and_class_names(
        self, file_path: str, target_funcs: List[str], file_content: Optional[str] = None
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
        target_funcs_str = ", ".join(f"`{f}`" for f in target_funcs)
        prompt = dedent(f"""
            You are a Python testing expert. Based on the following functions and their source file, suggest a suitable
            filename and a `unittest.TestCase` class name for their test suite.

            **Source File Path:** {file_path}
            **Target Function Names:** {target_funcs_str}
            {source_code_context}

            **Your Task:**
            Provide your suggestions in a JSON format. The filename must follow the `test_*.py` convention. The class
            name should be descriptive and encompass all target functions.

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
            You are an expert Python developer specializing in refactoring and maintaining test suites.
            Your task is to intelligently merge new test cases into an existing test file.

            **1. CONTEXT: EXISTING TEST FILE**
            This is the current content of the test file.

            [File Path]: {output_path}
            [Existing Code]:
            ```python
            {existing_code}
            ```

            **2. CONTEXT: NEWLY GENERATED TEST CASES**
            These are new test cases that need to be added to the file.
            They are already formatted as a complete test class.

            [New Test Code to Add]:
            ```python
            {new_code_block}
            ```

            **3. YOUR TASK: MERGE THE CODE**
            - **Combine Imports:** Merge the imports from both blocks, removing duplicates.
            - **Merge into Class:** Add the new test methods from the new code into the existing `unittest.TestCase`
              class. If the class names differ, use the existing class name.
            - **Preserve Structure:** Maintain the overall structure and style of the existing file.
            - **Do Not Remove Existing Tests:** Ensure all original tests are kept.
            - **Completeness:** The final output must be a single, complete, and runnable Python file.

            **IMPORTANT**: Your entire response must be only the merged Python code, enclosed within a single
            Python markdown block (e.g., ```python ... ```). Do not add any explanations or text outside the code block.
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

    def _format_call_record_as_text(self, call_record: Dict[str, Any]) -> str:
        """
        Formats a single call record from the analysis report into a compact,
        human-readable text trace. This format is easier for LLMs to parse than full JSON.

        Args:
            call_record: A dictionary representing a single function call record.

        Returns:
            A formatted string representing the execution trace.
        """
        trace_lines = []

        func_name = call_record.get("func_name", "N/A")
        original_filename = call_record.get("original_filename", "N/A")
        args = call_record.get("args", {})
        return_value = call_record.get("return_value")
        exception = call_record.get("exception")

        # --- Header ---
        trace_lines.append(f"Execution trace for `{func_name}` from `{original_filename}`:")

        # --- Call Signature ---
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items()) if args else ""
        trace_lines.append(f"\n[CALL] {func_name}({args_str})")

        # --- Body: Executed Lines and Sub-calls ---
        events = call_record.get("events", [])
        if events:
            trace_lines.append("\n[TRACE]")
            for event in events:
                event_type = event.get("type")
                data = event.get("data", {})

                if event_type == "line":
                    line_no = data.get("line_no")
                    # content has original indentation, rstrip removes trailing newlines
                    content = data.get("content", "").rstrip()
                    tracked_vars = data.get("tracked_vars")

                    line_str = f"  L{line_no:<4} {content}"

                    if tracked_vars:
                        # Format tracked variables for readability
                        vars_str = ", ".join(f"{k}={repr(v)}" for k, v in tracked_vars.items())
                        line_str += f"    >> VARS: {vars_str}"

                    trace_lines.append(line_str)

                elif event_type == "call":
                    sub_call_data = data
                    sub_func_name = sub_call_data.get("func_name", "N/A")
                    sub_args = sub_call_data.get("args", {})
                    sub_return = sub_call_data.get("return_value")
                    sub_exception = sub_call_data.get("exception")
                    caller_lineno = sub_call_data.get("caller_lineno", "?")

                    sub_args_str = ", ".join(f"{k}={repr(v)}" for k, v in sub_args.items()) if sub_args else ""

                    call_summary = f"{sub_func_name}({sub_args_str})"
                    if sub_exception:
                        result_summary = f"RAISED {repr(sub_exception)}"
                    else:
                        result_summary = f"RETURNED {repr(sub_return)}"

                    # This line represents a dependency that might need to be mocked.
                    sub_call_line = f"  L{caller_lineno:<4} [SUB-CALL] {call_summary} -> {result_summary}"
                    trace_lines.append(sub_call_line)

        # --- Footer: Return Value or Exception ---
        if exception:
            trace_lines.append(f"\n[FINAL] RAISES: {repr(exception)}")
        else:
            trace_lines.append(f"\n[FINAL] RETURNS: {repr(return_value)}")

        return "\n".join(trace_lines)

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
        if file_content and file_path:
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
        call_record_text = self._format_call_record_as_text(call_record)

        action_description, existing_code_section, code_structure_guidance = self._get_common_prompt_sections(
            test_class_name, existing_code
        )

        prompt_part1 = dedent(f"""
            You are an expert Python developer specializing in writing clean, modular, and robust unit tests.
            Your task is to {action_description} for the function `{target_func}`.

            **1. CRITICAL INSTRUCTION: HOW TO IMPORT THE CODE TO TEST**
            You MUST NOT copy the source code of the function into the test file. Instead, you MUST import it.
            - **Project Root Directory:** `{project_root_path}`
            - **Module to Test:** `{module_to_test}`
            - **How to Import the Target Function:** `from {module_to_test} import {target_func}`
            - **`sys.path` Setup:** To ensure the import works correctly, you MUST include this exact code
              snippet at the top of the test file. It dynamically finds the project root.
              ```python
              {sys_path_setup_snippet}
              ```

            **2. CONTEXT: SOURCE CODE (FOR REFERENCE ONLY)**
            This is the content of the file where the target function resides. Use it to understand the
            function's logic, but DO NOT copy it.

            [File Path]: {file_path}
            [File Content]:
            ```python
            {file_content}
            ```
        """).strip()

        prompt_part2 = dedent(f"""
            **3. CONTEXT: RUNTIME EXECUTION TRACE for `{target_func}`**
            This is a compact text trace representing a single execution of the function.
            It shows the arguments, the lines of code executed (`L...`), captured variable
            states (`>> VARS:`), any sub-calls made to other functions (`[SUB-CALL]`),
            and the final return value or exception. Use this to understand the test case.

            [Runtime Execution Trace]
            ```text
            {call_record_text}
            ```

            **4. INTELLIGENT MOCKING STRATEGY**
            {self._get_mocking_guidance(target_func, module_to_test)}

            **5. YOUR TASK: GENERATE THE TEST CODE**
            {code_structure_guidance}
            {existing_code_section}

            **IMPORTANT**: Your entire response must be only the Python code, enclosed within a single Python
            markdown block (e.g., ```python ... ```). Do not add any explanations or text outside the code block.
        """).strip()

        return f"{prompt_part1}\n\n{prompt_part2}"

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
        call_record_text = self._format_call_record_as_text(call_record)

        context_code_str = ""
        for name, data in symbol_context.items():
            context_code_str += f"# Symbol: {name}\n"
            context_code_str += f"# File: {data.get('file_path', '?')}:{data.get('start_line', '?')}\n"
            context_code_str += f"{data.get('code', '# Code not found')}\n\n"

        action_description, existing_code_section, code_structure_guidance = self._get_common_prompt_sections(
            test_class_name, existing_code
        )

        prompt_part1 = dedent(f"""
            You are an expert Python developer specializing in writing clean, modular, and robust unit tests.
            Your task is to {action_description} for the function `{target_func}`.

            **1. CRITICAL INSTRUCTION: HOW TO IMPORT THE CODE TO TEST**
            You MUST NOT copy the source code of the function into the test file. Instead, you MUST import it.
            - **Project Root Directory:** `{project_root_path}`
            - **Module to Test:** `{module_to_test}`
            - **How to Import the Target Function:** `from {module_to_test} import {target_func}`
            - **`sys.path` Setup:** To ensure the import works correctly, you MUST include this exact code
              snippet at the top of the test file. It dynamically finds the project root.
              ```python
              {sys_path_setup_snippet}
              ```

            **2. CONTEXT: RELEVANT SOURCE CODE (PRECISION MODE)**
            Instead of the full file, you are given the precise source code for the target function and all other
            functions it called during a sample execution. Use this context to understand the logic.
            DO NOT copy this code into the test file; import the target function as instructed.

            [Relevant Code Snippets]
            ```python
            {context_code_str.strip()}
            ```
        """).strip()

        prompt_part2 = dedent(f"""
            **3. CONTEXT: RUNTIME EXECUTION TRACE for `{target_func}`**
            This is a compact text trace representing a single execution of the function.
            It shows the arguments, the lines of code executed (`L...`), captured variable
            states (`>> VARS:`), any sub-calls made to other functions (`[SUB-CALL]`),
            and the final return value or exception. Use this to understand the test case.

            [Runtime Execution Trace]
            ```text
            {call_record_text}
            ```

            **4. INTELLIGENT MOCKING STRATEGY**
            {self._get_mocking_guidance(target_func, module_to_test)}

            **5. YOUR TASK: GENERATE THE TEST CODE**
            {code_structure_guidance}
            {existing_code_section}

            **IMPORTANT**: Your entire response must be only the Python code, enclosed within a single Python
            markdown block (e.g., ```python ... ```). Do not add any explanations or text outside the code block.
        """).strip()
        return f"{prompt_part1}\n\n{prompt_part2}"

    def _get_common_prompt_sections(self, test_class_name: str, existing_code: Optional[str]) -> Tuple[str, str, str]:
        """Generates common prompt sections for action, existing code, and structure."""
        if existing_code:
            action_description = f"add a new test method to the existing `unittest.TestCase` class `{test_class_name}`"
            action_verb = "Add the new method to the existing class."
            existing_code_section = f"""
[Existing Test File Content]
```python
{existing_code}
```
"""
        else:
            action_description = f"create a new `unittest.TestCase` class named `{test_class_name}`"
            action_verb = (
                "Define the test class and a main execution block (`if __name__ == '__main__': unittest.main()`)."
            )
            existing_code_section = ""

        code_structure_guidance = (
            "- **Framework:** Use Python's built-in `unittest` module.\n"
            "- **Test Method:** Create a new, descriptively named test method (e.g., `test_..._case_N`).\n"
            "- **Mocking:** Based on the **INTELLIGENT MOCKING STRATEGY**, mock only the necessary\n"
            "  dependencies, which are shown as `[SUB-CALL]` lines in the execution trace.\n"
            "    - Configure mocks to behave exactly as recorded (return value or exception).\n"
            "    - Verify mocks were called correctly using `mock_instance.assert_called_once_with(...)`.\n"
            "- **Assertions:**\n"
            "    - Use `self.assertEqual()` for return values.\n"
            "    - Use `self.assertRaises()` for exceptions.\n"
            "- **Code Structure:**\n"
            "  - Generate a complete, runnable Python code snippet.\n"
            "  - Include all necessary imports (`unittest`, `unittest.mock`, the `sys.path` setup, "
            "and the function to be tested).\n"
            f"  - {action_verb}"
        )
        return action_description, existing_code_section, code_structure_guidance

    def _get_mocking_guidance(self, target_func: str, module_to_test: str) -> str:
        """Generates the standard mocking guidance section for the prompt."""
        guidance = dedent(f"""
        Your goal is to create a valuable and robust test. Do not mock everything blindly.
        - **DO Mock:**
            - Functions with external side effects (e.g., network requests, database queries).
            - Functions that are non-deterministic (e.g., `datetime.now()`, `random.randint()`).
            - Dependencies that are slow or complex, to isolate the function under test.
            - In the provided trace, any dependency shown as a `[SUB-CALL]` is a good candidate for mocking,
              allowing you to test how `{target_func}` handles its success and failure cases independently.
        - **DO NOT Mock:**
            - I/O operations that your can use a tempdir, tempfile to avoid side affect.
            - Simple, pure, deterministic helper functions within your own project (e.g., a function
              that just performs a calculation). Letting these simple functions run makes the test more
              meaningful and less brittle.

        - **How to Patch:** When using `unittest.mock.patch`, the path must be based on the module where
          the dependency is *used*. For example, to patch `dependency_func` which is imported and used in
          `{module_to_test}`, use `patch('{module_to_test}.dependency_func', ...)`.
        """).strip()
        return guidance

    @tracer.trace(
        target_files=["*.py"],
        enable_var_trace=True,
        report_name="unittest_generate.html",
        ignore_self=False,
        ignore_system_paths=True,
        disable_html=False,
        # include_stdlibs=["unittest"],
    )
    def generate(
        self,
        target_funcs: List[str],
        output_dir: str,
        auto_confirm: bool = False,
        use_symbol_service: bool = True,
        num_workers: int = 0,
    ) -> bool:
        """
        [REFACTORED] Generates the unit test file for the specified functions, with parallel execution support.

        The process is as follows:
        1.  **Setup Phase (Serial):** Find all call records, get user confirmation for file/class names,
            and resolve paths. This is done once to avoid race conditions.
        2.  **Task Preparation:** Create a list of atomic, self-contained tasks, one for each call record.
        3.  **Generation Phase (Parallel/Serial):**
            - If num_workers > 1, a multiprocessing pool is used to generate test cases in parallel.
            - Each worker generates a complete, runnable test code block for one case.
        4.  **Aggregation Phase (Serial):** The generated code blocks from all tasks are intelligently
            merged into a single, cohesive test file.
        5.  **Finalization Phase (Serial):** The final code is formatted and written to disk.

        Args:
            target_funcs: The names of the functions to generate tests for.
            output_dir: Directory to save the generated test file(s).
            auto_confirm: If True, automatically accept all suggestions without prompting the user.
            use_symbol_service: If True, use symbol service to get precise context.
            num_workers: Number of parallel processes to use for test generation.
                         If 0 or 1, generation is sequential.
        """
        if not target_funcs:
            print(Fore.RED + "No target functions specified.")
            return False

        all_calls_by_func = self._find_all_calls_for_targets(target_funcs)
        all_calls_by_func = {f: calls for f, calls in all_calls_by_func.items() if calls}

        if not all_calls_by_func:
            print(Fore.RED + f"No call records found for specified functions: {', '.join(target_funcs)}")
            return False

        # --- 1. Setup Phase (Serial) ---
        setup_data = self._setup_generation_environment(all_calls_by_func, use_symbol_service, output_dir, auto_confirm)
        if not setup_data:
            return False
        (target_file_path, file_content, symbol_context, output_path, final_class_name, module_to_test) = setup_data

        # --- 2. Task Preparation (Serial) ---
        tasks = self._prepare_generation_tasks(
            all_calls_by_func,
            target_file_path,
            file_content,
            symbol_context,
            final_class_name,
            module_to_test,
            output_path,
        )

        # --- 3. Generation Phase (Parallel or Serial) ---
        newly_generated_code = self._execute_generation_tasks(tasks, num_workers)
        if not newly_generated_code:
            print(Fore.RED + "No test code was generated.")
            return False

        # --- 4. File Writing / Merging Phase (Serial) ---
        final_code_to_write = self._handle_existing_file(output_path, newly_generated_code, auto_confirm)
        if not final_code_to_write:
            return False

        # --- 5. Finalization ---
        return self._write_final_code(output_path, final_code_to_write)

    def _setup_generation_environment(
        self, all_calls_by_func: Dict, use_symbol_service: bool, output_dir: str, auto_confirm: bool
    ) -> Optional[Tuple]:
        """Prepares all necessary context and paths for test generation."""
        first_func = next(iter(all_calls_by_func))
        target_file_path = self._resolve_target_file_path(all_calls_by_func[first_func][0]["original_filename"])
        if not target_file_path:
            return None

        symbol_context, file_content = None, None
        if use_symbol_service:
            print(Fore.CYAN + "\nUsing symbol service to gather precise code context...")
            all_calls_flat = [call for calls in all_calls_by_func.values() for call in calls]
            symbol_context = self._get_symbols_for_calls(all_calls_flat)
            if not symbol_context:
                print(Fore.YELLOW + "Warning: Failed to get symbol context. Falling back to full file content.")
        if not symbol_context:  # Fallback if service disabled or failed
            file_content = self._read_file_content(target_file_path)
            if not file_content:
                return None

        suggested_file, suggested_class = self._suggest_test_file_and_class_names(
            str(target_file_path), list(all_calls_by_func.keys()), file_content
        )
        if not (suggested_file and suggested_class):
            print(Fore.RED + "Could not get suggestions for file/class names.")
            return None

        final_file_name, final_class_name = self._get_final_names(suggested_file, suggested_class, auto_confirm)

        output_path = self._validate_and_resolve_path(output_dir, final_file_name)
        if not output_path:
            return None

        module_to_test = self._get_module_path(target_file_path)
        if not module_to_test:
            return None

        return target_file_path, file_content, symbol_context, output_path, final_class_name, module_to_test

    def _get_symbols_for_calls(self, all_calls: List[Dict]) -> Optional[Dict[str, Dict]]:
        """
        Gathers unique function locations and fetches their source code via the symbol service.
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
                    # Add only if location info is present and it's not a self-recursive call
                    if (
                        "original_filename" in data
                        and "original_lineno" in data
                        and data.get("func_name") != record.get("func_name")
                    ):
                        locations.add((data["original_filename"], data["original_lineno"]))

        if not locations:
            print(Fore.YELLOW + "No symbol locations found in call records.")
            return None

        file_to_lines = defaultdict(list)
        for filename, lineno in locations:
            if isinstance(filename, str) and isinstance(lineno, int):
                file_to_lines[filename].append(lineno)

        file_results = [
            FileSearchResult(
                file_path=filename,
                matches=[MatchResult(line=lineno, column_range=(0, 0), text="") for lineno in lines],
            )
            for filename, lines in file_to_lines.items()
        ]

        if not file_results:
            return None

        search_results = FileSearchResults(results=file_results)

        print(Fore.CYAN + f"Querying symbol service for {len(locations)} unique locations...")
        # The 'model_switch' keyword argument is removed to fix the pylint error.
        # This may prevent LLM call tracing for this specific operation.

        symbol_results = query_symbol_service(search_results, 128 * 1024)

        if symbol_results and isinstance(symbol_results, dict):
            print(Fore.GREEN + f"Successfully retrieved {len(symbol_results)} symbols.")
            return symbol_results

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

    def _prepare_generation_tasks(
        self,
        all_calls_by_func: Dict[str, List[Dict]],
        target_file_path: Path,
        file_content: Optional[str],
        symbol_context: Optional[Dict[str, Dict]],
        test_class_name: str,
        module_to_test: str,
        output_path: Path,
    ) -> List[Dict]:
        """Creates a list of task dictionaries for parallel processing."""
        tasks = []
        for target_func, call_records in all_calls_by_func.items():
            for i, call_record in enumerate(call_records):
                task = {
                    "case_number": len(tasks) + 1,
                    "target_func": target_func,
                    "call_record": call_record,
                    "total_calls": len(call_records),
                    "call_index": i + 1,
                    # Pass all necessary context for the worker
                    "target_file_path": str(target_file_path),
                    "file_content": file_content,
                    "symbol_context": symbol_context,
                    "test_class_name": test_class_name,
                    "module_to_test": module_to_test,
                    "project_root_path": str(project_root.resolve()),
                    "output_file_abs_path": str(output_path.resolve()),
                    "generator_model_name": self.generator_model_name,
                    "checker_model_name": self.checker_model_name,
                    "trace_llm": self.model_switch.trace_llm,
                    "trace_dir": self.model_switch.trace_run_dir.parent if self.model_switch.trace_run_dir else None,
                }
                tasks.append(task)
        return tasks

    def _execute_generation_tasks(self, tasks: List[Dict], num_workers: int) -> Optional[str]:
        """Executes prepared tasks either serially or in parallel."""
        if not tasks:
            return None

        # [REFACTORED] Parallel/Serial execution logic is now centralized here.
        if num_workers > 1:
            print(
                Fore.MAGENTA
                + f"\nStarting parallel test case generation with {num_workers} workers..."
                + Style.RESET_ALL
            )
            try:
                with multiprocessing.Pool(processes=num_workers) as pool:
                    # map_async is used to show progress, but simple map works too
                    results = pool.map(UnitTestGenerator._generation_worker, tasks)
            except Exception as e:
                print(Fore.RED + f"A critical error occurred during parallel processing: {e}")
                return None
        else:
            print(Fore.MAGENTA + "\nStarting serial test case generation..." + Style.RESET_ALL)
            results = [UnitTestGenerator._generation_worker(task) for task in tasks]

        # Aggregate results
        generated_code = None
        for i, code_snippet in enumerate(results):
            if code_snippet:
                print(Fore.GREEN + f"Successfully generated code for case {i + 1}/{len(tasks)}." + Style.RESET_ALL)
                if generated_code is None:
                    generated_code = code_snippet
                else:
                    # Merge the new snippet into the accumulated code
                    generated_code = self._merge_tests(
                        existing_code=generated_code,
                        new_code_block=code_snippet,
                        output_path=tasks[0]["output_file_abs_path"],
                    )
                    if not generated_code:
                        print(
                            Fore.RED
                            + f"Failed to merge code from case {i + 1}. Aborting further merges."
                            + Style.RESET_ALL
                        )
                        break
            else:
                print(Fore.RED + f"Failed to generate code for case {i + 1}/{len(tasks)}." + Style.RESET_ALL)

        return generated_code

    @staticmethod
    def _generation_worker(task: Dict) -> Optional[str]:
        """
        [NEW] Static worker for parallel test generation. It's self-contained.
        It generates a *complete, runnable* code block for a single test case.
        """
        # Unpack task dictionary
        target_func = task["target_func"]
        call_record = task["call_record"]
        case_num = task["case_number"]
        call_idx = task["call_index"]
        total_calls = task["total_calls"]

        # Re-create a minimal generator instance inside the worker process
        # This is necessary because the full instance isn't picklable.
        # We pass model names and trace settings to reconstruct it.
        worker_generator = UnitTestGenerator(
            report_path="",  # Not needed, as we have the record
            model_name=task["generator_model_name"],
            checker_model_name=task["checker_model_name"],
            trace_llm=task["trace_llm"],
            llm_trace_dir=str(task["trace_dir"]) if task["trace_dir"] else "llm_traces",
        )
        # Hack to avoid re-reading the report
        worker_generator.analysis_data = {}

        print(
            Fore.CYAN + f"[Worker-{os.getpid()}] Generating Test Case {case_num} for '{target_func}' "
            f"(call {call_idx}/{total_calls})" + Style.RESET_ALL
        )

        prompt = worker_generator._build_prompt(
            target_func=target_func,
            call_record=call_record,
            # For the first case, `existing_code` is None. For subsequent merges,
            # the main process will handle it. Here, we generate a self-contained block.
            existing_code=None,
            **{
                k: v
                for k, v in task.items()
                if k
                in [
                    "test_class_name",
                    "module_to_test",
                    "project_root_path",
                    "output_file_abs_path",
                    "target_file_path",
                    "file_content",
                    "symbol_context",
                ]
            },
        )

        response_text = worker_generator.model_switch.query(task["generator_model_name"], prompt, stream=False)
        return worker_generator._extract_code_from_response(response_text)

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
        "--target-functions",
        nargs="+",
        required=True,
        help="One or more names of the functions to generate tests for.",
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
    parser.add_argument(
        "--trace-llm",
        action="store_true",
        help="Enable logging of LLM prompts and responses to a directory. (Default: disabled)",
    )
    parser.add_argument(
        "--llm-trace-dir",
        default="llm_traces",
        help="Directory to save LLM traces if --trace-llm is enabled. (Default: 'llm_traces')",
    )
    # [NEW] Argument for parallel processing
    parser.add_argument(
        "--num-workers",
        type=int,
        default=0,
        help="Number of worker processes for parallel test generation. Default: 0 (serial execution).",
    )
    return parser.parse_args()


def main():
    """Main entry point for the unit test generator."""
    args = parse_args()

    print(Fore.BLUE + Style.BRIGHT + "\nStarting Unit Test Generation Workflow")
    print(Fore.BLUE + "=" * 50)
    print(f"{'Report File:':<20} {args.report_file}")
    print(f"{'Target Functions:':<20} {', '.join(args.target_functions)}")
    print(f"{'Output Directory:':<20} {args.output_dir}")
    print(f"{'Generator Model:':<20} {args.model}")
    print(f"{'Checker Model:':<20} {args.checker_model}")
    print(f"{'Symbol Service:':<20} {'Enabled' if args.use_symbol_service else 'Disabled'}")
    print(f"{'Parallel Workers:':<20} {args.num_workers if args.num_workers > 0 else 'Serial'}")
    if args.auto_confirm:
        print(f"{'Auto Confirm:':<20} {Fore.YELLOW}Enabled{Style.RESET_ALL}")
    if args.trace_llm:
        print(f"{'LLM Tracing:':<20} {Fore.YELLOW}Enabled (dir: {args.llm_trace_dir}){Style.RESET_ALL}")
    print(Fore.BLUE + "=" * 50)

    generator = UnitTestGenerator(
        report_path=args.report_file,
        model_name=args.model,
        checker_model_name=args.checker_model,
        trace_llm=args.trace_llm,
        llm_trace_dir=args.llm_trace_dir,
    )
    generator.generate(
        target_funcs=args.target_functions,
        output_dir=args.output_dir,
        auto_confirm=args.auto_confirm,
        use_symbol_service=args.use_symbol_service,
        num_workers=args.num_workers,
    )


if __name__ == "__main__":
    main()
