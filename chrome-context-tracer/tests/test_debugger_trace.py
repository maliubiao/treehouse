#!/usr/bin/env python3
"""
Integration test for the 'trace' command in the chrome_context_tracer.

This test script automates the following process:
1.  Creates a temporary HTML file with specific JavaScript code.
    - The JS code includes console.log statements.
    - It has a nested function call structure (funcA -> funcB -> funcC).
    - A 'debugger;' statement is placed in the innermost function (`funcC`)
      along with several local variables.
2.  Launches a browser with remote debugging enabled, navigated to the temp file.
3.  Directly invokes the DOMInspector's tracing capabilities in-process.
4.  Captures the standard output of the inspector in memory.
5.  Asserts that the captured output contains:
    - The expected console log messages.
    - The debugger pause notification.
    - The full, correct stack trace.
    - The source code line of the breakpoint, annotated with the values of local variables.
6.  Cleans up by closing the browser and deleting the temporary file.
"""

import asyncio
import contextlib
import io
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

# Add the 'src' directory to the path to allow importing the package
# The test file is in tests/, src/ is in the parent directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chrome_context_tracer import BrowserContextManager, DOMInspector
from chrome_context_tracer.i18n import _

# --- Test Configuration ---
TEST_TIMEOUT: float = 20.0  # Increased timeout to be more robust
STOP_SIGNAL = _("Resuming execution...")

TEST_HTML_CONTENT: str = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Debugger Trace Test</title>
</head>
<body>
    <h1>Testing the Debugger Trace</h1>
    <script>
        function funcC() {
            console.log("Inside funcC, before debugger.");
            let a = 10;
            let b = "test string";
            let c = { d: 1, e: "nested" };
            debugger; // The inspector should pause here
        }

        function funcB() {
            // This function creates a new scope
            let z = 99;
            funcC();
        }

        function funcA() {
            funcB();
        }

        window.onload = function() {
            console.log("Console message from test page: Script starting.");
            setTimeout(funcA, 1500); // Delay to ensure inspector is attached
        };
    </script>
</body>
</html>
"""


async def run_test() -> None:
    """Main function to orchestrate the integration test."""
    print("--- Starting Debugger Trace Integration Test ---")
    success = False
    temp_html_file = None
    output = ""
    errors = ""

    try:
        # Step 1: Create a temporary HTML file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".html", encoding="utf-8") as f:
            temp_html_file = f.name
            f.write(TEST_HTML_CONTENT)

        file_url = Path(temp_html_file).as_uri()
        print(f"✅ Temporary test page created at: {file_url}")

        # Step 2: Launch browser using the context manager for auto-cleanup and start_url
        async with BrowserContextManager(browser_type="chrome", auto_cleanup=True, start_url=file_url) as browser:
            url_pattern = Path(temp_html_file).name  # Match by filename

            output_buffer = io.StringIO()
            inspector: Optional[DOMInspector] = None

            # Redirect stdout/stderr to capture all prints from the inspector
            with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
                try:
                    # Step 3: Run inspector logic in-process
                    websocket_url = browser.get_main_websocket_url()
                    if not websocket_url:
                        raise RuntimeError("Test setup failed: No websocket URL from BrowserContextManager.")

                    inspector = DOMInspector(websocket_url)
                    await inspector.connect()

                    # Find the specific tab using the filename pattern, even though the context manager opened it for us.
                    # This ensures the inspector's own discovery logic is tested.
                    target_id = await inspector.find_tab_by_url(url_pattern)
                    if not target_id:
                        raise RuntimeError(f"Test setup failed: Could not find tab with pattern '{url_pattern}'.")

                    session_id = await inspector.attach_to_tab(target_id)
                    if not session_id:
                        raise RuntimeError("Test setup failed: Could not attach to tab.")

                    # Enable console listening to capture log messages for assertions
                    await inspector.start_console_listening()

                    print("\n✅ Inspector attached. Waiting for debugger event...")

                    # Step 4: Wait for the debugger event to be processed
                    start_time = time.time()
                    while STOP_SIGNAL not in output_buffer.getvalue():
                        if time.time() - start_time > TEST_TIMEOUT:
                            raise asyncio.TimeoutError(f"Test timed out after {TEST_TIMEOUT}s waiting for stop signal.")
                        await asyncio.sleep(0.1)

                    print(f"✅ Stop signal '{STOP_SIGNAL}' detected.")

                finally:
                    # Ensure inspector connection is closed
                    if inspector:
                        await inspector.close()

            # Retrieve captured output
            output = output_buffer.getvalue()

            print("\n--- Captured Output ---")
            print(output)
            print("--- End of Output ---\n")

            # Step 5: Assertions
            print("🔬 Verifying output...")
            _verify_output(output)

            success = True

    except Exception as e:
        print(f"\n❌ An unexpected error occurred during the test: {e}")
        import traceback

        traceback.print_exc()
        errors = str(e)
    finally:
        # Step 6: Cleanup
        if temp_html_file and os.path.exists(temp_html_file):
            os.remove(temp_html_file)
            print(f"🧹 Cleaned up temporary file: {temp_html_file}")

        if success:
            print("\n✅✅✅ Integration Test Passed! ✅✅✅")
        else:
            print("\n❌❌❌ Integration Test Failed! ❌❌❌")
            if output:
                print("\n--- Final Captured Output on Failure ---")
                print(output)
            if errors:
                print("\n--- Error on Failure ---")
                print(errors)
            sys.exit(1)  # Exit with error code on failure


def _verify_output(output: str) -> None:
    """Run a series of assertions against the captured output."""

    # 1. Verify console message is captured
    # The output format is `CONSOLE.LOG: <message>`
    assert "CONSOLE.LOG: Console message from test page: Script starting." in output
    print("✅ Assertion Passed: Initial console message was captured.")

    # 2. Verify debugger pause header
    assert "Paused on debugger statement" in output
    print("✅ Assertion Passed: Debugger pause was detected.")

    # 3. Verify stack trace
    assert "[0] funcC" in output
    assert "[1] funcB" in output
    assert "[2] funcA" in output
    print("✅ Assertion Passed: Stack trace is correct.")

    # 4. Verify variables are displayed as comments
    # The order of variables might change, so check for each part.
    # The exact formatting depends on the application's output logic.
    # Looking at the code: it's `// {name}: {description}, ...`
    var_string_found = False
    for line in output.splitlines():
        if "debugger;" in line and "//" in line:
            var_string_found = True
            assert "a: 10" in line
            assert 'b: "test string"' in line or "b: test string" in line
            # For objects, the default description is 'Object'
            assert "c: Object" in line
            break

    assert var_string_found, "Did not find the annotated line with local variable values."
    print("✅ Assertion Passed: Local variables were correctly displayed.")

    # 5. Verify execution is resumed
    assert "Resuming execution..." in output
    print("✅ Assertion Passed: Execution was resumed after pause.")


if __name__ == "__main__":
    asyncio.run(run_test())
