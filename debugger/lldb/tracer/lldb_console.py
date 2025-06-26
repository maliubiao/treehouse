import os
import re
import sys
import traceback
from typing import List, Optional

import lldb
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings

try:
    from colorama import Fore, Style, init

    init(autoreset=True)
except ImportError:

    class ColorFallback:
        def __getattr__(self, name):
            return ""

    Fore = ColorFallback()
    Style = ColorFallback()
    print("Warning: colorama not found. Console output will not be colored.", file=sys.stderr)


class LLDBCompleter(Completer):
    def __init__(self, ci: lldb.SBCommandInterpreter, custom_commands: List[str]):
        self.ci = ci
        self.custom_commands = custom_commands
        # Pre-compiled regex for finding the start of the word to complete
        self._word_boundary_re = re.compile(r"[\s=:]+")

    def _get_current_word_start(self, text: str, cursor_pos: int) -> int:
        """Find the start of the word at the cursor."""
        start_index = cursor_pos
        while start_index > 0:
            if self._word_boundary_re.match(text[start_index - 1]):
                break
            start_index -= 1
        return start_index

    def get_completions(self, document, complete_event):
        full_text = document.text
        cursor_pos = document.cursor_position

        # Find the start of the word to complete
        match_start_point = self._get_current_word_start(full_text, cursor_pos)
        word_to_complete = full_text[match_start_point:cursor_pos]

        # Use LLDB's built-in completer
        matches = lldb.SBStringList()
        descriptions = lldb.SBStringList()

        self.ci.HandleCompletionWithDescriptions(
            full_text,
            cursor_pos,
            match_start_point,
            100,  # max_return_elements
            matches,
            descriptions,
        )

        # Yield completions from LLDB
        for i in range(matches.GetSize()):
            match = matches.GetStringAtIndex(i)
            description = descriptions.GetStringAtIndex(i) if i < descriptions.GetSize() else ""
            yield Completion(match, start_position=-len(word_to_complete), display_meta=description or "Argument")

        # Add custom commands
        for cmd in self.custom_commands:
            if cmd.startswith(word_to_complete):
                yield Completion(cmd, start_position=-len(word_to_complete), display_meta="Custom Command")


def show_console(
    debugger: lldb.SBDebugger,
    python_line: Optional[int] = None,
    python_traceback_str: Optional[str] = None,
    initial_message: str = "Entering LLDB interactive shell due to an event.",
    prompt: str = "(lldb-shell) ",
):
    """
    Launches an interactive LLDB console.

    Args:
        debugger: The active lldb.SBDebugger instance.
        python_line: The Python line number where the event occurred (if applicable).
        python_traceback_str: The Python traceback string (if applicable).
        initial_message: A message to display when the console starts.
        prompt: The prompt string for the interactive shell.
    """
    print(f"\n{Fore.CYAN}{Style.BRIGHT}--- LLDB Interactive Console ---{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}{initial_message}{Style.RESET_ALL}")

    if python_line is not None:
        print(f"{Fore.MAGENTA}Python execution paused at line: {python_line}{Style.RESET_ALL}")
    if python_traceback_str:
        print(f"{Fore.MAGENTA}Python Traceback:\n{python_traceback_str}{Style.RESET_ALL}")

    ci = debugger.GetCommandInterpreter()
    if not ci.IsValid():
        print(f"{Fore.RED}Error: Could not get a valid LLDB command interpreter.{Style.RESET_ALL}")
        return

    custom_commands = ["q", "exit", "clear"]
    completer = LLDBCompleter(ci, custom_commands)

    help_message = (
        f"{Fore.GREEN}Type 'help' for LLDB commands, "
        f"'q' or 'exit' to quit. Use 'clear' or Ctrl+L "
        f"to clear screen.{Style.RESET_ALL}"
    )
    print(help_message)

    # Define keybindings for the session
    bindings = KeyBindings()

    @bindings.add("c-c")
    def _exit_handler(event):
        """Handle Ctrl+C to exit."""
        event.app.exit()

    @bindings.add("c-l")
    def _clear_screen_handler(event):
        """Handle Ctrl+L to clear the screen."""
        event.app.renderer.clear()

    session = PromptSession(key_bindings=bindings, completer=completer, complete_while_typing=True)

    while True:
        try:
            command_line = session.prompt(f"{Fore.BLUE}{prompt}{Style.RESET_ALL}").strip()
            if not command_line:
                continue

            if command_line.lower() in ("q", "exit"):
                print(f"{Fore.CYAN}Exiting LLDB interactive console.{Style.RESET_ALL}")
                break

            if command_line.lower() == "clear":
                os.system("clear")
                continue

            result = lldb.SBCommandReturnObject()
            ci.HandleCommand(command_line, result)

            if result.Succeeded():
                if result.GetOutputSize() > 0:
                    sys.stdout.write(result.GetOutput())
                if result.GetErrorSize() > 0:
                    sys.stderr.write(result.GetError())
            else:
                if result.GetOutputSize() > 0:
                    sys.stdout.write(result.GetOutput())
                if result.GetErrorSize() > 0:
                    sys.stderr.write(f"{Fore.RED}{result.GetError()}{Style.RESET_ALL}")
                else:
                    sys.stderr.write(f"{Fore.RED}Command failed: {command_line}{Style.RESET_ALL}\n")

        except EOFError:
            print(f"\n{Fore.CYAN}Exiting LLDB interactive console (EOF).{Style.RESET_ALL}")
            break
        except KeyboardInterrupt:
            print(f"\n{Fore.CYAN}Exiting LLDB interactive console (KeyboardInterrupt).{Style.RESET_ALL}")
            break
        except (ValueError, RuntimeError) as e:
            print(f"{Fore.RED}An error occurred: {e}{Style.RESET_ALL}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
