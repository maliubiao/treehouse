#!/usr/bin/env python3
"""
Integration test for the 'trace' command in dom_inspector.py.

This test script automates the following process:
1.  Creates a temporary HTML file with specific JavaScript code.
    - The JS code includes console.log statements.
    - It has a nested function call structure (funcA -> funcB -> funcC).
    - A 'debugger;' statement is placed in the innermost function (`funcC`)
      along with several local variables.
2.  Launches a browser with remote debugging enabled, navigated to the temp file.
3.  Runs `dom_inspector.py trace` as a subprocess, targeting the test page.
4.  Captures the standard output of the subprocess.
5.  Asserts that the captured output contains:
    - The expected console log messages.
    - The debugger pause notification.
    - The full, correct stack trace.
    - The source code line of the breakpoint, annotated with the values of local variables.
6.  Cleans up by closing the browser and deleting the temporary file.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import List

# Add the parent directory to the path to allow importing dom_inspector
sys.path.append(str(Path(__file__).parent.absolute()))

from dom_inspector import BrowserContextManager

# --- Test Configuration ---
TEST_TIMEOUT: float = 15.0  # seconds

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
            let c = {{ d: 1, e: "nested" }};
            debugger; // The inspector should pause here
            console.log("This should not be printed during the test.");
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
            setTimeout(funcA, 1000); // Delay to ensure inspector is attached
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

    try:
        # Step 1: Create a temporary HTML file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".html", encoding="utf-8") as f:
            temp_html_file = f.name
            f.write(TEST_HTML_CONTENT)

        file_url = Path(temp_html_file).as_uri()
        print(f"✅ Temporary test page created at: {file_url}")

        # Step 2: Launch browser using the context manager for auto-cleanup
        async with BrowserContextManager(browser_type="chrome", auto_cleanup=True) as browser:
            # Step 3: Run dom_inspector.py as a subprocess
            script_path = Path(__file__).parent / "dom_inspector.py"
            command: List[str] = [
                sys.executable,
                str(script_path),
                "trace",
                "--url",
                Path(temp_html_file).name,  # Match by filename is sufficient
            ]

            print(f"🚀 Running command: {' '.join(command)}")

            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Step 4: Capture output with a timeout
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=TEST_TIMEOUT)
            except asyncio.TimeoutError:
                print(f"⌛ Test timed out after {TEST_TIMEOUT} seconds. Terminating process.")
                process.terminate()
                await process.wait()
                # Get whatever output was captured before the timeout
                stdout_bytes = await process.stdout.read() if process.stdout else b""
                stderr_bytes = await process.stderr.read() if process.stderr else b""

            output = stdout_bytes.decode("utf-8")
            errors = stderr_bytes.decode("utf-8")

            print("\n--- Captured STDOUT ---")
            print(output)
            print("--- End of STDOUT ---\n")

            if errors:
                print("--- Captured STDERR ---")
                print(errors)
                print("--- End of STDERR ---\n")

            # Step 5: Assertions
            print("🔬 Verifying output...")
            _verify_output(output)

            success = True

    except Exception as e:
        print(f"\n❌ An unexpected error occurred during the test: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Step 6: Cleanup
        if temp_html_file and os.path.exists(temp_html_file):
            os.remove(temp_html_file)
            print(f"🧹 Cleaned up temporary file: {temp_html_file}")

        if success:
            print("\n✅✅✅ Integration Test Passed! ✅✅✅")
        else:
            print("\n❌❌❌ Integration Test Failed! ❌❌❌")


def _verify_output(output: str) -> None:
    """Run a series of assertions against the captured output."""

    # 1. Verify console message is captured
    assert "Console message from test page: Script starting." in output
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
    # The exact formatting depends on dom_inspector's output logic.
    # Looking at the code: it's `// {name}: {description}, ...`
    var_string_found = False
    for line in output.splitlines():
        if "debugger;" in line and "//" in line:
            var_string_found = True
            assert "a: 10" in line
            assert "b: test string" in line
            # For objects, the default description is 'Object'
            assert "c: Object" in line
            break

    assert var_string_found
    print("✅ Assertion Passed: Local variables were correctly displayed.")

    # 5. Verify execution is resumed
    assert "Resuming execution..." in output
    print("✅ Assertion Passed: Execution was resumed after pause.")


if __name__ == "__main__":
    asyncio.run(run_test())
