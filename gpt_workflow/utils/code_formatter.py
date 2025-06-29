import shutil
import subprocess
from textwrap import dedent


class CodeFormatter:
    """
    A utility class to format Python code using an external tool like Ruff.
    """

    def __init__(self, tool_name: str = "ruff"):
        """
        Initializes the CodeFormatter.

        Args:
            tool_name: The name of the formatting tool command (e.g., "ruff", "black").
        """
        self.tool_name = tool_name
        self.is_available = self._check_availability()

    def _check_availability(self) -> bool:
        """Checks if the formatting tool is available in the system's PATH."""
        return shutil.which(self.tool_name) is not None

    def format_code(self, code: str) -> str:
        """
        Formats a string of Python code.

        If the formatting tool is not available or an error occurs, it returns
        the original code.

        Args:
            code: The Python code string to format.

        Returns:
            The formatted code string, or the original code if formatting fails.
        """
        if not self.is_available:
            # Silently return original code if formatter is not installed.
            # A warning could be added here if desired.
            return code

        try:
            # Use --stdin-filename to provide a hint for config discovery
            # and to ensure the tool processes the input as a Python file.
            process = subprocess.run(
                [self.tool_name, "format", "--stdin-filename", "temp.py", "-"],
                input=code,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,  # Raise CalledProcessError on non-zero exit codes
            )
            # The formatted code is in stdout
            return process.stdout
        except FileNotFoundError:
            # This case is mostly handled by _check_availability, but serves as a fallback.
            print(f"Warning: Formatter command '{self.tool_name}' not found.")
            return code
        except subprocess.CalledProcessError as e:
            # This occurs if ruff encounters a syntax error or other issue.
            # We return the original code and print a warning.
            error_message = dedent(f"""
            --------------------------------------------------
            Warning: Code formatting with '{self.tool_name}' failed.
            This usually indicates a syntax error in the LLM-generated code.
            Returning the original, unformatted code.
            
            Ruff Error:
            {e.stderr}
            --------------------------------------------------
            """).strip()
            print(f"\033[93m{error_message}\033[0m")
            return code
        except Exception as e:
            print(f"An unexpected error occurred during code formatting: {e}")
            return code
