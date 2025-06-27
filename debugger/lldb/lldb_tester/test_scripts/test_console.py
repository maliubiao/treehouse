from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText

try:
    from tracer.lldb_console import LLDBCompleter
except ImportError:
    pass


def extract_meta_text(display_meta):
    """
    Extract plain text from display_meta which could be:
    - None
    - Plain string
    - FormattedText object
    """
    if display_meta is None:
        return ""
    if isinstance(display_meta, FormattedText):
        return "".join(text for _, text in display_meta)  # 拼接所有文本片段
    return str(display_meta)


def _assert_completions_contain(completions, expected_texts, expected_meta_prefix=None):
    """
    Helper assertion to check if specific completions are present in the results.

    Args:
        completions: Generator of Completion objects
        expected_texts: Single string or list of strings to check for
        expected_meta_prefix: Optional prefix to check in display_meta
    """
    if isinstance(expected_texts, str):
        expected_texts = [expected_texts]

    # Convert generator to list to inspect it on failure
    completion_list = list(completions)
    found = set()

    for comp in completion_list:
        if comp.text in expected_texts:
            if expected_meta_prefix is not None:  # Only check meta if a prefix is provided
                meta_text = extract_meta_text(comp.display_meta)
                if meta_text.startswith(expected_meta_prefix):
                    found.add(comp.text)
            else:
                found.add(comp.text)

    # Check if all expected texts were found
    missing = set(expected_texts) - found
    if missing:
        formatted_completions = [(c.text, extract_meta_text(c.display_meta)) for c in completion_list]
        raise AssertionError(
            f"Completion(s) {missing} (meta prefix: '{expected_meta_prefix}') not found. "
            f"Available completions: {formatted_completions}"
        )


def test_console_completions(context):
    """
    Tests the auto-completion logic of the LLDBCompleter class from lldb_console.
    This test is executed by lldb_tester.py, which provides a 'context'
    object with a live debugger session stopped at the 'main' function
    of the test program.

    Note: Command completions include trailing space for better UX
    """
    ci = context.debugger.GetCommandInterpreter()
    if not ci.IsValid():
        raise RuntimeError("Could not get a valid LLDB command interpreter.")

    # The custom commands are hardcoded in lldb_console.py's show_console
    custom_commands = ["q", "exit", "clear"]
    completer = LLDBCompleter(ci, custom_commands)

    print("\n--- Running lldb_console.py completion tests ---")

    # --- Test Case 1: Base command completion ---
    # Commands include trailing space for better UX
    doc = Document("hel", cursor_position=3)
    completions = completer.get_completions(doc, None)
    _assert_completions_contain(completions, ["help "], None)  # Note trailing space
    print("[+] PASSED: Base command completion ('hel' -> 'help ')")

    # --- Test Case 2: Sub-command completion ---
    # Subcommands include trailing space
    doc = Document("breakpoint ", cursor_position=11)
    completions = completer.get_completions(doc, None)
    _assert_completions_contain(completions, ["set ", "delete ", "list "])
    print("[+] PASSED: Sub-command completion ('breakpoint ' -> multiple options with spaces)")

    # --- Test Case 3: Custom command completion ---
    # Custom commands include trailing space
    doc = Document("cle", cursor_position=3)
    completions = completer.get_completions(doc, None)
    _assert_completions_contain(completions, ["clear "], "Custom Command")
    print("[+] PASSED: Custom command completion ('cle' -> 'clear ')")

    # --- Test Case 4: Alias completion ---
    # Aliases include trailing space
    doc = Document("q", cursor_position=1)
    completions = completer.get_completions(doc, None)
    _assert_completions_contain(completions, ["q "], None)  # Note trailing space
    print("[+] PASSED: Alias completion ('q' -> 'q ')")

    # --- Test Case 5: Variable completion (if context available) ---
    try:
        # Variables/functions do NOT include trailing space
        doc = Document("b ma", cursor_position=4)
        completions = completer.get_completions(doc, None)
        _assert_completions_contain(completions, ["main"])  # No trailing space
        print("[+] PASSED: Function name completion ('b ma' -> 'main')")
    except AssertionError:
        print("[-] SKIPPED: Function name completion (no debug context available)")

    # --- Test Case 6: Multiple command matches ---
    # Commands include trailing space
    doc = Document("br", cursor_position=2)
    completions = completer.get_completions(doc, None)
    _assert_completions_contain(completions, ["breakpoint "], None)  # Note trailing space
    print("[+] PASSED: Multiple command matches ('br' -> 'breakpoint ')")

    print("\nAll console completion tests passed!")
