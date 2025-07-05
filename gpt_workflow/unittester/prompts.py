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
    call_record: Dict,
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
) -> str:
    """Dispatcher for building the generation prompt based on context and mode (full/incremental)."""
    if is_incremental:
        return _build_incremental_generation_prompt(
            target_func=target_func,
            call_record=call_record,
            test_class_name=test_class_name,
            module_to_test=module_to_test,
            symbol_context=symbol_context,
            file_path=file_path,
            file_content=file_content,
            import_context=import_context,
        )
    if symbol_context:
        return _build_symbol_based_prompt(
            symbol_context=symbol_context,
            target_func=target_func,
            call_record=call_record,
            test_class_name=test_class_name,
            module_to_test=module_to_test,
            project_root_path=project_root_path,
            output_file_abs_path=output_file_abs_path,
            existing_code=existing_code,
            import_context=import_context,
        )
    if file_content and file_path:
        return _build_file_based_prompt(
            file_path=file_path,
            file_content=file_content,
            target_func=target_func,
            call_record=call_record,
            test_class_name=test_class_name,
            module_to_test=module_to_test,
            project_root_path=project_root_path,
            output_file_abs_path=output_file_abs_path,
            existing_code=existing_code,
            import_context=import_context,
        )
    raise ValueError("Either symbol_context or file_content must be provided to build a prompt.")


def _get_intent_driven_testing_guidance() -> str:
    """[NEW] Generates the prompt section explaining how to write intent-driven tests."""
    return dedent("""
        **A. CORE MISSION: FROM TRACE TO INTENT-DRIVEN TEST**
        The provided execution trace is your starting point, not your final goal. Your mission is to write a test that validates the *intended behavior* of the function, even if it means exposing a bug in the current code.

        **Your Critical Thought Process:**
        1.  **Infer Intent:** From the source code (name, docstring, logic), determine what the function is *supposed* to do. (e.g., a function `add_positive_numbers` should reject negative inputs).
        2.  **Critique the Trace:** Compare this intent with the execution trace. Does the trace show the function behaving as intended?
            - **If the trace reveals a bug** (e.g., `add_positive_numbers(5, -2)` returned `3` instead of raising an error), your test MUST assert the **correct, intended behavior**. This test is designed to **fail** when run against the buggy code, thus highlighting the flaw. This is a high-value test.
            - **If the trace reflects correct behavior**, your test should confirm that outcome.
        3.  **Action:** Do not write tests that simply replicate a buggy execution. Write tests that enforce the code's logical contract.
    """).strip()


def _build_file_based_prompt(
    file_path: str,
    file_content: str,
    target_func: str,
    call_record: Dict,
    test_class_name: str,
    module_to_test: str,
    project_root_path: Path,
    output_file_abs_path: Path,
    existing_code: Optional[str] = None,
    import_context: Optional[Dict[str, Dict]] = None,
) -> str:
    """
    [REFACTORED] Constructs the detailed prompt for the LLM using full file content.
    Now uses the centralized `build_generation_guidance` and includes intent-driven testing.
    """
    sys_path_setup_snippet = generate_relative_sys_path_snippet(output_file_abs_path, project_root_path)
    call_record_text = format_call_record_as_text(call_record)
    action_description, existing_code_section, _ = _get_common_prompt_sections(test_class_name, existing_code)
    generation_guidance = build_generation_guidance(module_to_test, test_class_name, existing_code, import_context)
    intent_guidance = _get_intent_driven_testing_guidance()

    prompt_part1 = dedent(f"""
        You are an expert Python developer specializing in writing clean, modular, and robust unit tests.
        {intent_guidance}

        Your task is to {action_description} for the function `{target_func}`.

        **B. CRITICAL INSTRUCTION: HOW TO IMPORT THE CODE TO TEST**
        You MUST NOT copy the source code of the function into the test file. Instead, you MUST import it.
        - **Project Root Directory:** `{project_root_path}`
        - **Module to Test:** `{module_to_test}`
        - **How to Import the Target Function:** `from {module_to_test} import {target_func.split(".")[-1]}`
        - **`sys.path` Setup:** To ensure the import works correctly, you MUST include this exact code snippet at the top of the test file.
          ```python
          {sys_path_setup_snippet}
          ```
        **C. CONTEXT: SOURCE CODE (FOR REFERENCE ONLY)**
        [File Path]: {file_path}
        [File Content]:
        [start]
        {file_content}
        [end]
    """).strip()

    prompt_part2 = dedent(f"""
        **D. CONTEXT: RUNTIME EXECUTION TRACE for `{target_func}`**
        This is a compact text trace of the function's execution. It is the **blueprint** for the test case you must generate.
        [Runtime Execution Trace]
        [start]
        {call_record_text}
        [end]

        **E. TEST GENERATION REQUIREMENTS**
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
    call_record: Dict,
    test_class_name: str,
    module_to_test: str,
    project_root_path: Path,
    output_file_abs_path: Path,
    existing_code: Optional[str] = None,
    import_context: Optional[Dict[str, Dict]] = None,
) -> str:
    """
    [REFACTORED] Constructs the detailed prompt for the LLM using precise symbol context.
    Now uses the centralized `build_generation_guidance` and includes intent-driven testing.
    """
    sys_path_setup_snippet = generate_relative_sys_path_snippet(output_file_abs_path, project_root_path)
    call_record_text = format_call_record_as_text(call_record)
    context_code_str = ""
    for name, data in symbol_context.items():
        context_code_str += f"# Symbol: {name}\n# File: {data.get('file_path', '?')}:{data.get('start_line', '?')}\n{data.get('code', '# Code not found')}\n\n"

    action_description, existing_code_section, _ = _get_common_prompt_sections(test_class_name, existing_code)
    generation_guidance = build_generation_guidance(module_to_test, test_class_name, existing_code, import_context)
    intent_guidance = _get_intent_driven_testing_guidance()

    prompt_part1 = dedent(f"""
        You are an expert Python developer specializing in writing clean, modular, and robust unit tests.
        {intent_guidance}

        Your task is to {action_description} for the function `{target_func}`.
        
        **B. CRITICAL INSTRUCTION: HOW TO IMPORT THE CODE TO TEST**
        - **Project Root Directory:** `{project_root_path}`
        - **Module to Test:** `{module_to_test}`
        - **`sys.path` Setup:** You MUST include this exact code snippet at the top of the test file.
          ```python
          {sys_path_setup_snippet}
          ```
        **C. CONTEXT: RELEVANT SOURCE CODE (PRECISION MODE)**
        [Relevant Code Snippets]
        [start]
        {context_code_str.strip()}
        [end]
    """).strip()

    prompt_part2 = dedent(f"""
        **D. CONTEXT: RUNTIME EXECUTION TRACE for `{target_func}`**
        This is a compact text trace of the function's execution. It is the **blueprint** for the test case.
        [Runtime Execution Trace]
        [start]
        {call_record_text}
        [end]

        **E. TEST GENERATION REQUIREMENTS**
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
    call_record: Dict,
    test_class_name: str,
    module_to_test: str,
    symbol_context: Optional[Dict[str, Dict]] = None,
    file_path: Optional[str] = None,
    file_content: Optional[str] = None,
    import_context: Optional[Dict[str, Dict]] = None,
) -> str:
    """[NEW & REFACTORED] Builds a prompt to generate only a single new test method, with intent-driven logic."""
    call_record_text = format_call_record_as_text(call_record)
    intent_guidance = _get_intent_driven_testing_guidance()

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
        You are an expert Python developer writing a new test case for an existing test suite.
        {intent_guidance}

        Your task is to generate a SINGLE new test method for the function `{target_func}` based on your analysis.

        **B. CONTEXT: HOW THE FUNCTION IS IMPORTED**
        - The function `{target_func}` is imported from the module `{module_to_test}`.
        - You will need `unittest.mock.patch` to mock dependencies.

        {context_section}

        **D. CONTEXT: RUNTIME EXECUTION TRACE for `{target_func}`**
        This trace is the **blueprint** for the new test case.
        [Runtime Execution Trace]
        [start]
        {call_record_text}
        [end]
        {import_context_section}

        **F. INTELLIGENT MOCKING STRATEGY**
        {_get_mocking_guidance(module_to_test)}

        **G. YOUR TASK: GENERATE *ONLY* THE NEW TEST METHOD**
        - The test file and class (`{test_class_name}`) already exist.
        - You must **ONLY** generate the Python code for the new test method.
        - **DO NOT** generate the class definition (`class ...:`).
        - **DO NOT** generate imports or `sys.path` setup.
        - **DO NOT** generate `if __name__ == '__main__':`.
        - Your output must be a single, complete `def test_...` method, correctly indented to be placed inside a class.
        - The method MUST have a clear docstring explaining the test case, especially if it's designed to expose a bug.
        - **MOCKING MUST BE SCOPED:** Use `with` blocks for mocks to ensure they are cleaned up after use.

        **Example of correct output:**
        [start]
    def test_func_to_test_with_specific_input(self):
        \"\"\"Test func_to_test with a=5 and b=3, expecting return value 16.\"\"\"
        with patch('module.dependency') as mock_dep:
            mock_dep.return_value = 10
            result = func_to_test(5, 3)
            self.assertEqual(result, 16)
        [end]

        **IMPORTANT**: 
        1. Your entire response must be only the Python method
        2. Enclose the method within a `[start]` and `[end]` block
        3. **DO NOT** use markdown code syntax (triple backticks) to wrap the method
    """).strip()


def build_duplicate_check_prompt(existing_code: str, call_record: Dict) -> str:
    """[NEW] Builds a prompt to ask the LLM if a test case already exists."""
    call_record_text = format_call_record_as_text(call_record)
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
    strict prohibitions against invalid mocking patterns.
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
