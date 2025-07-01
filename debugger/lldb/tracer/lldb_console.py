import os
import re
import sys
import traceback
from typing import List

import lldb
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style


class LLDBCompleter(Completer):
    """
    A prompt_toolkit completer that uses LLDB's built-in completion engine.
    """

    def __init__(self, ci: lldb.SBCommandInterpreter, custom_commands: List[str]):
        self.ci = ci
        self.custom_commands = custom_commands
        # Regex to find the start of the word to be completed
        self._word_boundary_re = re.compile(r"[\s=:]+")

    def get_completions(self, document, complete_event):
        full_text = document.text
        cursor_pos = document.cursor_position

        # Find the start of the word being typed
        match_start_point = self._word_boundary_re.split(full_text[:cursor_pos])[-1]

        # Get completions from LLDB
        matches = lldb.SBStringList()
        descriptions = lldb.SBStringList()
        self.ci.HandleCompletionWithDescriptions(full_text, cursor_pos, 0, -1, matches, descriptions)

        # Yield LLDB completions
        for i in range(matches.GetSize()):
            match_text = matches.GetStringAtIndex(i)
            desc_text = descriptions.GetStringAtIndex(i) if i < descriptions.GetSize() else ""
            # Add a space for commands to allow for faster argument typing
            display_text = match_text + " " if "command" in desc_text.lower() else match_text
            yield Completion(display_text, start_position=-len(match_start_point), display_meta=desc_text or "Argument")

        # Yield custom command completions
        for cmd in self.custom_commands:
            if cmd.startswith(match_start_point):
                yield Completion(cmd + " ", start_position=-len(match_start_point), display_meta="Shell Command")


def show_console(debugger: lldb.SBDebugger):
    """
    Launches an interactive LLDB console.

    This function is intended to be called when the debugger stops at a point
    requiring manual intervention, such as a specific breakpoint exception.

    Args:
        debugger: The active lldb.SBDebugger instance.
    """
    ci: lldb.SBCommandInterpreter = debugger.GetCommandInterpreter()
    if not ci.IsValid():
        print("Error: Could not get a valid LLDB command interpreter.", file=sys.stderr)
        return

    # --- Print Contextual Information ---
    print("\n" + "=" * 60)
    print("  Entering LLDB Interactive Shell".center(60))
    print("=" * 60)

    try:
        # Get Python call stack that led to this shell
        stack = traceback.extract_stack()
        # The last frame is this function, the one before is the caller.
        caller_frame = stack[-2]
        print(f"-> Shell triggered from: {caller_frame.filename}:{caller_frame.lineno} in `{caller_frame.name}`")
    except Exception as e:
        print(f"-> Could not determine call location: {e}")

    print("-" * 60)

    # --- Setup Prompt-toolkit Session ---
    custom_commands = ["quit", "exit", "clear"]
    completer = LLDBCompleter(ci, custom_commands)

    # Define a style for the prompt and output
    style = Style.from_dict(
        {
            "prompt": "ansicyan bold",
            "output": "ansigreen",
            "error": "ansired bold",
        }
    )

    # Key bindings for Ctrl+C (exit) and Ctrl+L (clear screen)
    bindings = KeyBindings()

    @bindings.add("c-c")
    def _(event):
        event.app.exit()

    @bindings.add("c-l")
    def _(event):
        event.app.renderer.clear()

    session = PromptSession(
        "(lldb) ", key_bindings=bindings, completer=completer, complete_while_typing=True, style=style
    )

    print("Type 'help' for LLDB commands. 'quit' or 'exit' to resume program execution.")
    print("-" * 60 + "\n")

    # --- Command Loop ---
    while True:
        try:
            command_line = session.prompt().strip()
            if not command_line:
                continue

            if command_line.lower() in ("q", "quit", "exit"):
                break

            if command_line.lower() == "clear":
                os.system("cls" if os.name == "nt" else "clear")
                continue

            # Execute the command in LLDB
            result = lldb.SBCommandReturnObject()
            ci.HandleCommand(command_line, result)

            # Print output/error
            output = result.GetOutput()
            if output:
                print(output, end="")

            error = result.GetError()
            if error:
                print(error, file=sys.stderr, end="")

            # Ensure a newline after command execution if there wasn't one
            if (output and not output.endswith("\n")) or (error and not error.endswith("\n")):
                print()

        except (EOFError, KeyboardInterrupt):
            break

    print("\n" + "=" * 60)
    print("  Resuming program execution...".center(60))
    print("=" * 60 + "\n")
