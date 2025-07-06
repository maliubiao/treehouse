from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple

from .file_utils import generate_relative_sys_path_snippet
from .format_call_record import format_call_record_as_text


def build_suggestion_prompt(file_path: str, target_funcs: List[str], file_content: Optional[str] = None) -> str:
    """Builds the prompt to ask the LLM for test file and class name suggestions."""
    source_code_context = ""
    if file_content:
        source_code_context = f"""
**Source Code (for context):**
```python
{file_content}
```
"""
    target_funcs_str = ", ".join(f"`{f}`" for f in target_funcs)
    return dedent(f"""
        You are a Python testing expert. Based on the following functions and their source file, suggest a suitable
        filename and a `unittest.TestCase` class name for their test suite.

        **Source File Path:** {file_path}
        **Target Function Names:** {target_funcs_str}
        {source_code_context}

        **Your Task:**
        Provide your suggestions in a JSON object. The filename must follow the `test_*.py` convention.
        The JSON object MUST be enclosed in `[start]` and `[end]` tags.

        **Example Output:**
        [start]
        {{
          "file_name": "test_my_module.py",
          "class_name": "TestMyModuleFunctionality"
        }}
        [end]

        **Response:**
    """).strip()


def build_merge_prompt(
    existing_code: str, new_code_snippets: List[str], output_path: str, generation_guidance: str
) -> str:
    """
    [MODIFIED] Builds the prompt to ask the LLM to merge new test cases into existing code.
    It now includes instructions for intelligent refactoring and explicitly passes in the
    original generation guidance to ensure consistency.
    """
    new_blocks_str = ""
    for i, snippet in enumerate(new_code_snippets):
        new_blocks_str += dedent(f"""
        ---
        [New Test Case(s) Block {i + 1}]
        ---
        [start]
        {snippet}
        [end]
        """)

    task_description = (
        "intelligently merge new test cases into an existing test file, refactoring for clarity and maintainability."
    )
    if len(new_code_snippets) > 1:
        task_description = "intelligently merge MULTIPLE new test cases from several blocks into an existing test file, refactoring for clarity and maintainability."

    return dedent(f"""
        You are an expert Python developer specializing in refactoring and maintaining test suites.
        Your task is to {task_description}

        **1. CONTEXT: EXISTING TEST FILE**
        This is the current content of the test file.

        [File Path]: {output_path}
        [Existing Code]:
        [start]
        {existing_code}
        [end]

        **2. CONTEXT: NEWLY GENERATED TEST CASES**
        These are new test cases that need to be added to the file.
        Each block might contain one or more test cases within a complete, runnable script, OR just a single new test method.

        [New Test Code to Add]:
        {new_blocks_str.strip()}

        **3. STANDARDS FOR THE MERGED CODE**
        The new test code was generated following specific rules. You MUST ensure the final, merged code also adheres to these standards. These rules supersede any conflicting styles in the existing code.

        [Generation Standards]:
        [start]
        {generation_guidance}
        [end]

        **4. YOUR TASK: REFACTOR AND MERGE**
        Your primary goal is to create a clean, well-organized, and robust test suite by integrating the new test cases.

        - **Step 1: Analyze All Test Cases:** Review all test methods, both from the "Existing Code" and all "New Test Code" blocks. Understand the purpose of each test.

        - **Step 2: Group and Refactor into Classes:**
          - **Group by Functionality:** Group test methods based on the specific behavior or scenario they test (e.g., API contract, edge cases, error handling).
          - **Class Size Limit:** A single test class SHOULD NOT contain more than 10 test methods. If merging would exceed this limit, you MUST split the tests into multiple, logically-named classes (e.g., `TestFunctionSuccess`, `TestFunctionFailures`).
          - **Use Inheritance for Common Setup:** If multiple test classes share common setup logic (e.g., creating a common object), create a base test class with a `setUp` method. The specialized test classes should then inherit from this base class to avoid code duplication.
            *Example:* `class TestMyModuleBase(unittest.TestCase): ...`, then `class TestApiCases(TestMyModuleBase): ...`

        - **Step 3: Combine and Clean Imports:** Merge all imports from the existing and new code. Remove duplicates and organize them according to PEP 8 (standard library, third-party, local application). Combine imports from the same module (e.g., `from unittest.mock import patch, MagicMock`).

        - **Step 4: Apply and Validate Standards:**
          - Ensure every test method (new and old) has a clear docstring.
          - Re-validate all mocking against the "Generation Standards". All mocks MUST be correctly scoped using `with` blocks or decorators. Remove any invalid or global mocks.
          - **Validate Test Method Signatures:** This is a critical quality check. A standard `unittest` test method has the signature `def test_my_behavior(self):`. It should only accept extra arguments if it is decorated (e.g., with `@patch`).
            - **Verify all method signatures:** For every `test_...` method, you MUST ensure that the number of arguments in its signature matches the mock objects passed by its decorators.
            - **Correct mismatches:** If a method incorrectly accepts an argument (e.g., `mock_db`) without a corresponding `@patch` decorator, you MUST fix the signature by removing the unused argument. A test method without decorators must only have `self` as its parameter.
            - **Example:** `def test_logic(self, mock_db):` is **INVALID** unless a decorator like `@patch('module.db')` is present. You must fix this.
          - **Adhere to the "STRICT PROHIBITIONS" in the standards.** Do not mock mocks or non-existent objects.

        - **Step 5: Preserve and Finalize:**
          - **Do Not Remove Existing Tests:** Ensure all original test logic is preserved, even if it's moved to a different class.
          - **Completeness:** The final output must be a single, complete, and runnable Python file, including the `if __name__ == '__main__':` block.

        **IMPORTANT**: 
        1. Your entire response MUST be only the merged and refactored Python code
        2. Enclose the code within a single `[start]` and `[end]` block
        3. **DO NOT** use markdown ``` syntax to wrap the code
    """).strip()


def _format_import_context(import_context: Optional[Dict[str, Dict]]) -> str:
    """Formats the import context into a markdown block for the prompt."""
    if not import_context:
        return ""

    lines = [
        "The following symbols are imported from other modules into the file under test. This is critical for creating correct mock targets.",
        "When you need to mock a function or object that was imported, you must patch it where it is *looked up*, which is in the namespace of the file under test.",
        "",
        f"**Example:** If the file under test is `my_app/logic.py` (module `my_app.logic`), and it contains `from my_app.utils import helper_func`, then a call to `helper_func()` inside `logic.py` must be mocked with `patch('my_app.logic.helper_func')`.",
        "---",
        "**Detected Imports:**",
    ]
    for symbol, info in sorted(import_context.items()):
        lines.append(
            f"- The name `{symbol}` comes from module `{info.get('module', 'N/A')}`, the module path is `{info['path']}`."
        )

    return "\n".join(lines)


def build_generation_guidance(
    module_to_test: str,
    test_class_name: str,
    existing_code: Optional[str] = None,
    import_context: Optional[Dict[str, Dict]] = None,
) -> str:
    """
    [REFACTORED] Assembles the core guidance for test generation, to be used in both
    generation and merge prompts for consistency. It now includes import context.
    """
    _, _, code_structure_guidance = _get_common_prompt_sections(test_class_name, existing_code)
    mocking_guidance = _get_mocking_guidance(module_to_test)
    import_context_guidance = _format_import_context(import_context)

    guidance = f"""
        **INTELLIGENT MOCKING STRATEGY**
        {mocking_guidance}
    """
    if import_context_guidance:
        guidance += f"""

        **IMPORT CONTEXT AND MOCK TARGETS**
        {import_context_guidance}
        """

    guidance += f"""

        **YOUR TASK: GENERATE THE TEST CODE**
        {code_structure_guidance}
    """
    return dedent(guidance).strip()


def build_prompt_for_generation(
    target_func: str,
    call_records: List[Dict],
    test_class_name: str,
    module_to_test: str,
    project_root_path: Path,
    output_file_abs_path: Path,
    is_incremental: bool,
    file_path: Optional[str] = None,
    file_content: Optional[str] = None,
    symbol_context: Optional[Dict[str, Dict]] = None,
    existing_code: Optional[str] = None,
    import_context: Optional[Dict[str, Dict]] = None,
    max_trace_chars: Optional[int] = None,
) -> str:
    """[REFACTORED] Dispatcher for building the generation prompt. Now handles a list of call records."""
    if is_incremental:
        return _build_incremental_generation_prompt(
            target_func=target_func,
            call_records=call_records,
            test_class_name=test_class_name,
            module_to_test=module_to_test,
            symbol_context=symbol_context,
            file_path=file_path,
            file_content=file_content,
            import_context=import_context,
            max_trace_chars=max_trace_chars,
        )
    if symbol_context:
        return _build_symbol_based_prompt(
            symbol_context=symbol_context,
            target_func=target_func,
            call_records=call_records,
            test_class_name=test_class_name,
            module_to_test=module_to_test,
            project_root_path=project_root_path,
            output_file_abs_path=output_file_abs_path,
            existing_code=existing_code,
            import_context=import_context,
            max_trace_chars=max_trace_chars,
        )
    if file_content and file_path:
        return _build_file_based_prompt(
            file_path=file_path,
            file_content=file_content,
            target_func=target_func,
            call_records=call_records,
            test_class_name=test_class_name,
            module_to_test=module_to_test,
            project_root_path=project_root_path,
            output_file_abs_path=output_file_abs_path,
            existing_code=existing_code,
            import_context=import_context,
            max_trace_chars=max_trace_chars,
        )
    raise ValueError("Either symbol_context or file_content must be provided to build a prompt.")


def _get_test_writing_philosophy_guidance() -> str:
    """[NEW] Generates the prompt section explaining how to write focused, high-value tests."""
    return dedent("""
        **CORE MISSION: WRITE FOCUSED, INTENT-DRIVEN, HIGH-VALUE TESTS**

        Your goal is to be a discerning software engineer, not a mindless test generator. The quality of your tests is more important than the quantity.

        ***

        **1. FROM TRACE TO INTENT (The "Why")**
        The provided execution trace is your starting point, not your final goal. Your mission is to write a test that validates the *intended behavior* of the function, even if it means exposing a bug in the current code.

        - **Infer Intent:** From the source code (name, docstring, logic), determine what the function is *supposed* to do. (e.g., a function `add_positive_numbers` should reject negative inputs).
        - **Critique the Trace:** Compare this intent with the execution trace. Does the trace show the function behaving as intended?
            - **If the trace reveals a bug** (e.g., `add_positive_numbers(5, -2)` returned `3` instead of raising an error), your test MUST assert the **correct, intended behavior**. This test is designed to **fail** when run against the buggy code, thus highlighting the flaw. This is a high-value test.
            - **If the trace reflects correct behavior**, your test should confirm that outcome.
        - **Special Case - `KeyboardInterrupt`**: If the trace ends with a `KeyboardInterrupt`, DO NOT test for it. This is a user interruption, not a programmatic error. Analyze the trace *before* the interruption and test the function's logical behavior.

        ***

        **2. FOCUSED, NOT FRAGMENTED, TESTING (The "What")**
        A single, well-written test is better than many trivial ones. Focus on the core logic and avoid "over-testing".

        - **WHAT TO TEST:**
          - **Primary Logic ("Happy Path"):** Does the function work correctly with typical inputs?
          - **Key Edge Cases:** Test for conditions directly relevant to the function's logic (e.g., `None` inputs, empty lists, zero values, state transitions).
          - **Expected Error Conditions:** If the function is supposed to raise specific errors, test for them using `assertRaises`.

        - **WHAT TO AVOID TESTING IN A *UNIT* TEST:**
          - **Over-splitting Logic:** Do not create separate tests for every minor variation or `if` branch if they can be tested more cohesively. A single test can and should follow a logical path through the code.
          - **System State:** Avoid testing for conditions that are the responsibility of the larger application, not the unit. For example, "what if the database connection object is `None`?" is often an integration concern, not a unit test concern, unless the function's explicit purpose is to handle that state. Assume the function's pre-conditions are met.
          - **Library Behavior:** Do not test that a third-party library works. Mock it, and test that your code *uses* it correctly.

        ***

        **3. EXAMPLE: FOCUSED VS. FRAGMENTED TESTING**

        Consider this simple function:
        ```python
        # In tracer.core
        def continue_to_main(self) -> None:
            # Wait for the main entry point breakpoint to be hit
            while not self.entry_point_breakpoint_event.is_set():
                if self.process:
                    self.process.Continue()
                time.sleep(0.1)
        ```

        **BAD - FRAGMENTED AND LOW-VALUE:**
        This approach creates too many tests for one simple loop, and tests an irrelevant edge case (`process is None`).

        ```python
        # BAD EXAMPLE - DO NOT DO THIS
        def test_continue_to_main_event_already_set(self):
            # Trivial: tests the loop is never entered.
            tracer.entry_point_breakpoint_event.is_set.return_value = True
            tracer.continue_to_main()
            tracer.process.Continue.assert_not_called()

        def test_continue_to_main_wait_and_continue(self):
            # Tests the loop runs.
            tracer.entry_point_breakpoint_event.is_set.side_effect = [False, True]
            tracer.continue_to_main()
            tracer.process.Continue.assert_called_once()

        def test_continue_to_main_no_process(self):
            # Low-value: This state (no process) should likely be handled
            # at a higher level and is not the core focus of this function.
            tracer.process = None
            tracer.entry_point_breakpoint_event.is_set.side_effect = [False, True]
            tracer.continue_to_main()
            # ... asserts sleep was called ...
        ```

        **GOOD - FOCUSED AND HIGH-VALUE:**
        This single test verifies the core responsibility of the function: it waits for an event, continues the process during the wait, and then exits.

        ```python
        # GOOD EXAMPLE - AIM FOR THIS
        def test_continue_to_main_waits_for_event_and_continues_process(self):
            \"\"\"
            Verify continue_to_main continues the process until the event is set.
            \"\"\"
            tracer = Tracer.__new__(Tracer)
            tracer.process = MagicMock()
            tracer.entry_point_breakpoint_event = MagicMock()
            # Simulate the event being unset for 2 checks, then set on the 3rd.
            tracer.entry_point_breakpoint_event.is_set.side_effect = [False, False, True]

            with patch('tracer.core.time.sleep') as mock_sleep:
                tracer.continue_to_main()

            # Verify the core logic: the process was continued twice before the loop exited.
            self.assertEqual(tracer.process.Continue.call_count, 2)
            # Verify that it doesn't wait unnecessarily after the event is set.
            self.assertEqual(mock_sleep.call_count, 2)
        ```
    """).strip()


def _format_multiple_traces(call_records: List[Dict], max_total_chars: Optional[int]) -> str:
    """Formats a list of call records into a single string, respecting a total character budget."""
    num_records = len(call_records)
    if num_records == 0:
        return "No traces provided."

    # Distribute character budget, giving a bit more to earlier traces if budget is tight
    per_trace_budget = int(max_total_chars / num_records) if max_total_chars else None

    trace_texts = []
    for i, record in enumerate(call_records):
        trace_header = f"--- TRACE {i + 1} of {num_records} ---"
        formatted_trace = format_call_record_as_text(record, max_chars=per_trace_budget)
        trace_texts.append(f"{trace_header}\n{formatted_trace}")

    return "\n\n".join(trace_texts)


def _build_file_based_prompt(
    file_path: str,
    file_content: str,
    target_func: str,
    call_records: List[Dict],
    test_class_name: str,
    module_to_test: str,
    project_root_path: Path,
    output_file_abs_path: Path,
    existing_code: Optional[str] = None,
    import_context: Optional[Dict[str, Dict]] = None,
    max_trace_chars: Optional[int] = None,
) -> str:
    """[REFACTORED] Constructs prompt for a new file, using multiple traces to generate multiple tests."""
    sys_path_setup_snippet = generate_relative_sys_path_snippet(output_file_abs_path, project_root_path)
    call_records_text = _format_multiple_traces(call_records, max_trace_chars)  # FIXED: removed keyword arg
    action_description, existing_code_section, _ = _get_common_prompt_sections(test_class_name, existing_code)
    generation_guidance = build_generation_guidance(module_to_test, test_class_name, existing_code, import_context)
    philosophy_guidance = _get_test_writing_philosophy_guidance()

    # Create a new, more specific task description for multiple traces
    num_traces = len(call_records)
    multi_trace_task = dedent(f"""
        Your task is to create a new `unittest.TestCase` class named `{test_class_name}` for the function `{target_func}`.
        You have been provided with {num_traces} unique execution traces. You MUST generate one distinct `def test_...` method for EACH trace.
        Each test method must have a descriptive name reflecting the scenario in its corresponding trace.
    """).strip()

    prompt_part1 = dedent(f"""
        You are an expert Python developer specializing in writing clean, modular, and robust unit tests.
        
        **A. TEST GENERATION PHILOSOPHY**
        {philosophy_guidance}

        **B. YOUR TASK**
        {multi_trace_task}

        **C. CRITICAL INSTRUCTION: HOW TO IMPORT THE CODE TO TEST**
        You MUST NOT copy the source code of the function into the test file. Instead, you MUST import it.
        - **Project Root Directory:** `{project_root_path}`
        - **Module to Test:** `{module_to_test}`
        - **How to Import the Target Function:** `from {module_to_test} import {target_func.split(".")[-1]}`
        - **`sys.path` Setup:** To ensure the import works correctly, you MUST include this exact code snippet at the top of the test file.
          ```python
          {sys_path_setup_snippet}
          ```
        **D. CONTEXT: SOURCE CODE (FOR REFERENCE ONLY)**
        [File Path]: {file_path}
        [File Content]:
        [start]
        {file_content}
        [end]
    """).strip()

    prompt_part2 = dedent(f"""
        **E. CONTEXT: MULTIPLE RUNTIME EXECUTION TRACES for `{target_func}`**
        These are {num_traces} distinct blueprints for the test cases you must generate.
        [Runtime Execution Traces]
        [start]
        {call_records_text}
        [end]

        **F. TEST GENERATION REQUIREMENTS**
        {generation_guidance}
        {existing_code_section}

        **IMPORTANT**: 
        1. Your entire response must be only the Python code
        2. Enclose the code within a single `[start]` and `[end]` block
        3. **DO NOT** use markdown ``` syntax to wrap the code
    """).strip()
    return f"{prompt_part1}\n\n{prompt_part2}"


def _build_symbol_based_prompt(
    symbol_context: Dict[str, Dict],
    target_func: str,
    call_records: List[Dict],
    test_class_name: str,
    module_to_test: str,
    project_root_path: Path,
    output_file_abs_path: Path,
    existing_code: Optional[str] = None,
    import_context: Optional[Dict[str, Dict]] = None,
    max_trace_chars: Optional[int] = None,
) -> str:
    """[REFACTORED] Constructs prompt with symbol context, using multiple traces to generate multiple tests."""
    sys_path_setup_snippet = generate_relative_sys_path_snippet(output_file_abs_path, project_root_path)
    call_records_text = _format_multiple_traces(call_records, max_trace_chars)  # FIXED: removed keyword arg
    context_code_str = ""
    for name, data in symbol_context.items():
        context_code_str += f"# Symbol: {name}\n# File: {data.get('file_path', '?')}:{data.get('start_line', '?')}\n{data.get('code', '# Code not found')}\n\n"

    _, existing_code_section, _ = _get_common_prompt_sections(test_class_name, existing_code)
    generation_guidance = build_generation_guidance(module_to_test, test_class_name, existing_code, import_context)
    philosophy_guidance = _get_test_writing_philosophy_guidance()

    # Create a new, more specific task description for multiple traces
    num_traces = len(call_records)
    multi_trace_task = dedent(f"""
        Your task is to create a new `unittest.TestCase` class named `{test_class_name}` for the function `{target_func}`.
        You have been provided with {num_traces} unique execution traces. You MUST generate one distinct `def test_...` method for EACH trace.
        Each test method must have a descriptive name reflecting the scenario in its corresponding trace.
    """).strip()

    prompt_part1 = dedent(f"""
        You are an expert Python developer specializing in writing clean, modular, and robust unit tests.

        **A. TEST GENERATION PHILOSOPHY**
        {philosophy_guidance}

        **B. YOUR TASK**
        {multi_trace_task}
        
        **C. CRITICAL INSTRUCTION: HOW TO IMPORT THE CODE TO TEST**
        - **Project Root Directory:** `{project_root_path}`
        - **Module to Test:** `{module_to_test}`
        - **`sys.path` Setup:** You MUST include this exact code snippet at the top of the test file.
          ```python
          {sys_path_setup_snippet}
          ```
        **D. CONTEXT: RELEVANT SOURCE CODE (PRECISION MODE)**
        [Relevant Code Snippets]
        [start]
        {context_code_str.strip()}
        [end]
    """).strip()

    prompt_part2 = dedent(f"""
        **E. CONTEXT: MULTIPLE RUNTIME EXECUTION TRACES for `{target_func}`**
        These are {num_traces} distinct blueprints for the test cases you must generate.
        [Runtime Execution Traces]
        [start]
        {call_records_text}
        [end]

        **F. TEST GENERATION REQUIREMENTS**
        {generation_guidance}
        {existing_code_section}

        **IMPORTANT**: 
        1. Your entire response must be only the Python code
        2. Enclose the code within a single `[start]` and `[end]` block
        3. **DO NOT** use markdown ``` syntax to wrap the code
    """).strip()
    return f"{prompt_part1}\n\n{prompt_part2}"


def _build_incremental_generation_prompt(
    target_func: str,
    call_records: List[Dict],
    test_class_name: str,
    module_to_test: str,
    symbol_context: Optional[Dict[str, Dict]] = None,
    file_path: Optional[str] = None,
    file_content: Optional[str] = None,
    import_context: Optional[Dict[str, Dict]] = None,
    max_trace_chars: Optional[int] = None,
) -> str:
    """[REFACTORED] Builds a prompt to generate multiple new test methods for an existing test suite."""
    call_records_text = _format_multiple_traces(call_records, max_trace_chars)  # FIXED: removed keyword arg
    philosophy_guidance = _get_test_writing_philosophy_guidance()
    num_traces = len(call_records)

    # Context can come from symbols (preferred) or the full file
    if symbol_context:
        context_code_str = ""
        for name, data in symbol_context.items():
            context_code_str += f"# Symbol: {name}\n# File: {data.get('file_path', '?')}:{data.get('start_line', '?')}\n{data.get('code', '# Code not found')}\n\n"
        context_section = f"""
        **C. CONTEXT: RELEVANT SOURCE CODE (PRECISION MODE)**
        [Relevant Code Snippets]
        [start]
        {context_code_str.strip()}
        [end]
        """
    elif file_content and file_path:
        context_section = f"""
        **C. CONTEXT: SOURCE CODE (FOR REFERENCE ONLY)**
        [File Path]: {file_path}
        [File Content]:
        [start]
        {file_content}
        [end]
        """
    else:
        context_section = "**C. CONTEXT: SOURCE CODE**\nNo source code provided."

    import_context_guidance = _format_import_context(import_context)
    import_context_section = (
        f"**E. IMPORT CONTEXT AND MOCK TARGETS**\n{import_context_guidance}" if import_context_guidance else ""
    )

    return dedent(f"""
        You are an expert Python developer writing new test cases for an existing test suite.
        
        **A. TEST GENERATION PHILOSOPHY**
        {philosophy_guidance}

        **B. YOUR TASK: GENERATE NEW TEST METHODS**
        - You have been provided with {num_traces} unique execution traces for the function `{target_func}`.
        - You must generate one new, distinct `def test_...` method for EACH trace.
        - The test file and class (`{test_class_name}`) already exist.
        - You must **ONLY** generate the Python code for the new test method(s).
        - **DO NOT** generate the class definition (`class ...:`), imports, `sys.path` setup, or `if __name__ == '__main__':`.
        - Each method MUST be correctly indented to be placed inside a class.
        - Each method MUST have a clear docstring explaining the test case.
        - **MOCKING MUST BE SCOPED:** Use `with` blocks for mocks to ensure they are cleaned up after use.

        **C. CONTEXT: HOW THE FUNCTION IS IMPORTED**
        - The function `{target_func}` is imported from the module `{module_to_test}`.
        - You will need `unittest.mock.patch` to mock dependencies.

        {context_section}

        **D. CONTEXT: MULTIPLE RUNTIME EXECUTION TRACES for `{target_func}`**
        These {num_traces} traces are the blueprints for the new test cases.
        [Runtime Execution Traces]
        [start]
        {call_records_text}
        [end]
        {import_context_section}

        **F. INTELLIGENT MOCKING STRATEGY**
        {_get_mocking_guidance(module_to_test)}
        
        **Example of correct output for multiple traces:**
        [start]
        def test_func_with_specific_input(self):
            \"\"\"Test func_to_test with a=5 and b=3, expecting return value 16.\"\"\"
            with patch('module.dependency') as mock_dep:
                mock_dep.return_value = 10
                result = func_to_test(5, 3)
                self.assertEqual(result, 16)

        def test_func_handles_error_case(self):
            \"\"\"Verify that the function raises ValueError with negative input.\"\"\"
            with self.assertRaises(ValueError):
                func_to_test(-1, 3)
        [end]

        **IMPORTANT**: 
        1. Your entire response must be only the Python methods.
        2. Enclose the methods within a single `[start]` and `[end]` block.
        3. **DO NOT** use markdown code syntax (triple backticks) to wrap the code.
    """).strip()


def build_duplicate_check_prompt(existing_code: str, call_record: Dict, max_trace_chars: Optional[int] = None) -> str:
    """[NEW] Builds a prompt to ask the LLM if a test case already exists."""
    call_record_text = format_call_record_as_text(call_record, max_chars=max_trace_chars)
    func_name = call_record.get("func_name", "N/A")
    args = call_record.get("args", {})
    args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
    result = (
        repr(call_record.get("return_value"))
        if not call_record.get("exception")
        else f"raise {repr(call_record.get('exception'))}"
    )

    return dedent(f"""
        You are a meticulous code analysis expert. Your task is to determine if a specific test scenario is already covered in a given test file.

        **1. Existing Test File Content:**
        Here is the code for the existing test file.
        [start]
        {existing_code}
        [end]

        **2. New Test Scenario to Check:**
        I want to add a test for the function `{func_name}`.
        - **Function Call:** `{func_name}({args_str})`
        - **Expected Outcome:** The call should result in: `{result}`.
        - **Full Execution Trace (for detailed context):**
          {call_record_text}

        **3. Your Task:**
        Analyze the "Existing Test File Content" and determine if it already contains a test method that validates this exact scenario (same function, same inputs, and same expected outcome).

        **Answer with only "YES" or "NO".** Do not provide any explanation.
    """).strip()


def _get_common_prompt_sections(test_class_name: str, existing_code: Optional[str]) -> Tuple[str, str, str]:
    """[REFACTORED] Generates common prompt sections with improved code style guidance."""
    if existing_code:
        action_description = f"add a new test method to the existing `unittest.TestCase` class `{test_class_name}`"
        action_verb = "Add the new method to the existing class."
        existing_code_section = f"""
[Existing Test File Content]
[start]
{existing_code}
[end]
"""
    else:
        action_description = f"create a new `unittest.TestCase` class named `{test_class_name}`"
        action_verb = "Define the test class and a main execution block (`if __name__ == '__main__': unittest.main()`)."
        existing_code_section = ""

    code_structure_guidance = dedent(f"""
        - **Framework:** Use Python's built-in `unittest` module.
        - **Test Method:** Create a new, descriptively named test method (e.g., `test_..._case_N`).
        - **Docstring:** CRITICAL - Each test method MUST have a clear and concise docstring that explains the specific scenario being tested, especially if it's designed to expose a bug.
        - **Mocking:** Based on the **INTELLIGENT MOCKING STRATEGY**, mock only necessary dependencies (`[SUB-CALL]`).
        - **Assertions:** Use `self.assertEqual()` for return values and `self.assertRaises()` for exceptions, based on your analysis of the code's intent vs. the runtime trace.
        - **Code Structure and Style:**
          - Generate a complete, runnable Python script.
          - **Imports:** Place all imports (`unittest`, `unittest.mock`, the `sys.path` snippet, the function to test) at the top of the file. Group them logically (standard library, third-party, local) and combine imports from the same module (e.g., `from unittest.mock import patch, MagicMock`).
          - **Output Format:** 
            * Enclose the entire output within `[start]` and `[end]` tags
            * **DO NOT** use markdown code blocks (triple backticks)
          - {action_verb}
    """).strip()
    return action_description, existing_code_section, code_structure_guidance


def _get_mocking_guidance(module_to_test: str) -> str:
    """
    [REFACTORED] Generates enhanced mocking guidance. The unnecessary `target_func`
    parameter has been removed to make this function more generic. It now includes
    strict prohibitions against invalid mocking patterns and guidance for handling loops.
    """
    return dedent(f"""
    Your goal is to create a valuable and robust test, not a brittle one that just checks implementation details.
    - **Principle: Test Behavior, Not Implementation.** Focus on the *outcome* of the function (its return value, state changes, or exceptions) based on the provided inputs. The `[SUB-CALL]` entries in the trace are *candidates* for mocking, not a mandate to mock everything.
    - **What to Mock (Good Candidates):**
      - **External Systems:** Any interaction with networks, databases, or the file system.
      - **Non-deterministic Code:** Functions like `datetime.now()` or `random.random()`.
      - **Slow or Complex Dependencies:** Components that are slow, require complicated setup, or are outside the scope of the current test.
    - **What to AVOID Mocking (Bad Candidates):**
      - **Internal Helpers:** Do not mock simple, pure, deterministic helper functions within your own project. Testing the function with its real helpers provides more value.
      - **Data Objects:** Avoid mocking simple data structures or classes.
    - **How to Patch:**
      - Patch dependencies where they are *used*, not where they are defined. For a function in `{module_to_test}`, you will likely be patching targets like `patch('{module_to_test}.dependency_name', ...)`.
      - **Avoid excessive `assert_called_with`**. Only verify calls if the *interaction itself* is a critical part of the function's contract. A test that only checks mocks is often a poor test.

    **Special Handling for `logging.Logger`**
    - A common error is mocking a component that provides a logger, but failing to configure the mock logger object. Code often accesses `logger.name`, which causes `AttributeError: Mock object has no attribute 'name'` if the mock is not prepared.
    - **Solution:** When you mock a component that provides a logger (e.g., a `LogManager`), you must ensure the mock logger it returns has the necessary attributes.
      *Example:* If the class under test does `self.logger = self.log_manager.logger`, you must mock `LogManager` to provide a pre-configured logger.
      ```python
      # In your test setup, you MUST ensure the mock logger has a .name attribute.
      import logging
      from unittest.mock import MagicMock, patch

      # Correct way to set up the mock:
      # 1. Create a mock for the logger itself and set critical attributes.
      mock_logger = MagicMock(spec=logging.Logger)
      mock_logger.name = 'test_logger'

      # 2. Create a mock for the manager that provides the logger.
      mock_log_manager = MagicMock()
      mock_log_manager.logger = mock_logger

      # 3. Patch the manager class to return your pre-configured mock instance.
      with patch('path.to.your_app.LogManager', return_value=mock_log_manager):
          # Now, when your code under test does this:
          #   self.log_manager = LogManager()
          #   self.logger = self.log_manager.logger
          #   some_library_call(self.logger.name)
          # The call will succeed because self.logger.name is 'test_logger'.
          instance = ClassUnderTest()
          # ... rest of your test
      ```

    **Handling Loops and Long-Running Functions**
    - Functions with `while` or `for` loops can run infinitely during tests if the termination condition isn't correctly mocked. You must prevent this.
    - **Primary Goal:** Your main mock should control the loop's execution (e.g., by mocking a network call that would eventually terminate the loop).
    - **Safety-Net Mock (Circuit Breaker):** To guarantee termination, you can add a "circuit-breaker" mock. Patch a function *inside* the loop. Use the `side_effect` attribute of a `MagicMock` to make it raise a specific exception after a certain number of calls. Your test should then expect and catch this specific exception as a sign of successful, controlled termination.
      *Example:* For a function `function_with_endless_loop()` that repeatedly calls `do_work()`:
      ```python
      # In a test for a function like: while True: do_work()
      mock_do_work = MagicMock(side_effect=[1, 2, ValueError("Safety Break")])
      with patch('module.do_work', new=mock_do_work):
          with self.assertRaisesRegex(ValueError, "Safety Break"):
              function_with_endless_loop()
          # Assert that the function was called as many times as you expected before breaking.
          self.assertEqual(mock_do_work.call_count, 3)
      ```
    - This ensures the test terminates reliably, even if your primary mock on the loop condition fails.

    **CRITICAL MOCKING RULES**
    - **SCOPED MOCKS ONLY:** All mocks MUST be contained within the smallest possible scope. Use `with unittest.mock.patch(...):` blocks or the `@patch` decorator on individual test methods.
    - **NO GLOBAL MOCKS:** NEVER mock at the module level (e.g., by altering `sys.modules` or setting global variables). This includes avoiding any mock setup outside of test methods.
    - **MOCKS MUST BE CLEANED UP:** Ensure mocks are automatically cleaned up when leaving their scope. Context managers (`with` blocks) are preferred for this reason.

    **STRICT PROHIBITIONS (VIOLATING THESE WILL CAUSE TEST FAILURES)**
    1.  **DO NOT MOCK A MOCK OBJECT.** You cannot apply `patch` to an object that is already a mock. This indicates a deep misunderstanding of the code and results in nonsensical tests.
    2.  **DO NOT MOCK NON-EXISTENT OBJECTS.** Only mock objects that are explicitly mentioned in the source code context or the `[SUB-CALL]` trace. Inventing a dependency to mock (e.g., `patch('some.module.that_does_not_exist')`) will cause the test to fail with an `AttributeError` or `ModuleNotFoundError`. This is an unacceptable error.

    **Example of Correct Mocking:**
    [start]
    # Good: Using a context manager within a test
    def test_my_function(self):
        with patch('mymodule.other_function', return_value=42):
            result = my_function()
            self.assertEqual(result, 42)

    # Good: Using a decorator
    @patch('mymodule.other_function', return_value=42)
    def test_my_function(self, mock_other):
        result = my_function()
        self.assertEqual(result, 42)
    [end]

    **Example of Forbidden Mocking:**
    [start]
    # BAD: Global mock that affects other tests (STRICTLY FORBIDDEN)
    # At the top of the test file:
    #   import sys
    #   sys.modules['rich'] = MagicMock()
    #
    # Or in setUp method without cleanup:
    #   self.global_mock = patch('module.dependency').start()
    [end]
    """).strip()
