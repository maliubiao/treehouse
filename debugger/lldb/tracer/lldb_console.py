import os
import re
import sys
import traceback
from typing import List, Optional

import lldb
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML, FormattedText  # 新增导入
from prompt_toolkit.key_binding import KeyBindings

try:
    from colorama import Fore, Style, init

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
        # 添加命令后缀空格模式
        self._command_pattern = re.compile(r"^\w+$")  # 简单匹配命令单词

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

            # 修复：返回完整匹配项而不是后缀
            if match.startswith(word_to_complete):
                # 判断是否是命令补全（简单通过描述文本判断）
                is_command = "Command" in description or self._command_pattern.match(match)

                # 命令补全添加空格后缀，参数补全不加
                display = match + (" " if is_command else "")

                # 设置start_position为负的当前词长度，确保完整替换
                yield Completion(display, start_position=-len(word_to_complete), display_meta=description or "Argument")

        # Add custom commands
        for cmd in self.custom_commands:
            if cmd.startswith(word_to_complete):
                # 自定义命令也返回完整命令
                # 自定义命令也添加空格后缀
                yield Completion(cmd + " ", start_position=-len(word_to_complete), display_meta="Custom Command")


def show_console(debugger: lldb.SBDebugger):
    """
    Launches an interactive LLDB console with fixed default messages.

    Args:
        debugger: The active lldb.SBDebugger instance.
    """
    initial_message = "Entering LLDB interactive shell due to an event."
    prompt = "(lldb-shell) "

    print(f"\n{Fore.CYAN}{Style.BRIGHT}--- LLDB Interactive Console ---{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}{initial_message}{Style.RESET_ALL}")

    # Automatically determine call location and stack trace
    try:
        # Get the frame that called this function (skip show_console frame)
        frame = sys._getframe(1)
        python_line = frame.f_lineno
        python_file = frame.f_code.co_filename

        # Format stack trace excluding this function's frame
        stack_trace = []
        while frame:
            # Skip internal frames of the debugger itself
            if "__name__" in frame.f_globals and frame.f_globals["__name__"] == __name__:
                frame = frame.f_back
                continue

            stack_trace.append(f'  File "{frame.f_code.co_filename}", line {frame.f_lineno}, in {frame.f_code.co_name}')
            frame = frame.f_back

        python_traceback_str = "\n".join(reversed(stack_trace))

        print(f"{Fore.MAGENTA}Python execution paused at: {python_file}:{python_line}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}Python Traceback:\n{python_traceback_str}{Style.RESET_ALL}")

    except Exception as e:
        print(f"{Fore.RED}Could not determine call location: {e}{Style.RESET_ALL}")

    ci: lldb.SBCommandInterpreter = debugger.GetCommandInterpreter()
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

    # 使用FormattedText处理样式
    prompt_text = FormattedText(
        [
            ("#0080ff", prompt)  # 蓝色提示符
        ]
    )

    session = PromptSession(key_bindings=bindings, completer=completer, complete_while_typing=True)

    while True:
        try:
            # 使用FormattedText而不是原始ANSI序列
            command_line = session.prompt(prompt_text).strip()
            if not command_line:
                continue

            if command_line.lower() in ("q", "exit"):
                print(f"{Fore.CYAN}Exiting LLDB interactive console.{Style.RESET_ALL}")
                break

            if command_line.lower() == "clear":
                os.system("clear")
                continue

            result: lldb.SBCommandReturnObject = lldb.SBCommandReturnObject()
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
