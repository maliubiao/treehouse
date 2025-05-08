import os
import re
import shlex
import tempfile

import lldb
import yaml

from debugger.tracer import trace
from llm_query import GPTContextProcessor, ModelSwitch

from .context.context_collector import ContextCollector, DebugContext
from .command_parser import CommandParser


class CommandValidator:
    def __init__(self, debugger):
        self.debugger = debugger

    def validate(self, args: str) -> str:
        if not args.strip():
            return "Empty input"

        if not re.match(r"^.+?\s*::\s*.+$", args):
            return "Command format error, use 'askgpt <command> :: <question>' format"

        parts = self._split_command_with_escape(args)
        if len(parts) < 2:
            return "Invalid command parts"

        lldb_command, question = parts[0], " ".join(parts[1:])
        if not lldb_command:
            return "LLDB command is required"
        if not question:
            return "Question is required"
        if not re.match(r"^[ -~]+$", lldb_command):
            return "Invalid characters detected in LLDB command"

        validation_result = self._is_valid_command(lldb_command)
        if not validation_result[0]:
            return (
                f"Invalid LLDB command: '{lldb_command}'\n"
                f"Error: {validation_result[1]}\n"
                f"Try 'help' to see available commands"
            )

        return ""

    def _split_command_with_escape(self, args: str) -> list:
        args = args.replace(r"\::", "\x01").replace("::", "\x02")
        parts = [p.replace("\x01", "::").replace("\x02", "::") for p in re.split("\x02", args)]
        return parts

    def _is_valid_command(self, cmd: str) -> tuple:
        ci = self.debugger.GetCommandInterpreter()
        ret = lldb.SBCommandReturnObject()
        ci.ResolveCommand(cmd, ret)
        return (ret.Succeeded(), ret.GetError() if not ret.Succeeded() else "")


class CommandExecutor:
    def __init__(self, debugger):
        self.debugger = debugger

    def execute(self, command: str) -> str:
        return_obj = lldb.SBCommandReturnObject()
        self.debugger.GetCommandInterpreter().HandleCommand(command, return_obj)

        if not return_obj.Succeeded():
            error_msg = return_obj.GetError()
            if not error_msg:
                error_msg = "Command failed with no error message"
            raise RuntimeError(f"LLDB command failed: {error_msg}")

        output = return_obj.GetOutput()
        if not output:
            output = "Command executed successfully but returned no output"

        return output


class GPTIntegrationService:
    def __init__(self, session):
        self.session = session

    def query(
        self, command, command_output: str, common_commands_output: str, context: DebugContext, question: str
    ) -> str:
        temp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as temp_file:
                temp_file.write(f"[lldb command start]\n{command}\n[lldb command end]\n")
                temp_file.write(f"[output start]\n{command_output}\n[output end]\n")
                temp_file.write(
                    f"[lldb context start]\n{yaml.dump(context.to_dict(), allow_unicode=True, default_flow_style=False)}[lldb context end]\n"
                )
                temp_file.write(f"[user question start]\n{question}\n[user question end]\n")
                temp_file_path = temp_file.name

            model = ModelSwitch()
            model.select("qwen3")
            prompt = GPTContextProcessor().process_text(
                f"[some debug commands output]\n{common_commands_output}[some debug commands output end]\n"
                f"lldb context as the following:\n @{temp_file_path} [user question]\n{question}[user question end]"
            )
            print(prompt)
            return model.query_for_text("qwen3", prompt, disable_conversation_history=True)
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)


class AskGptCommand:
    def __init__(self, debugger, session):
        self.debugger = debugger
        self.session = session

    def help(self):
        return """AskGPT Help:
Format: askgpt <lldb_command> :: <question>
Example:
  askgpt memory read 0x16fdd79c0 :: explain this memory
  askgpt thread backtrace :: analyze call stack
  askgpt help :: show this help message"""

    @trace(target_files=["*.py"])
    def __call__(self, debugger, args, exe_ctx, result):
        if not args.strip():
            result.AppendMessage(self.help())
            return

        try:
            validator = CommandValidator(debugger)
            error = validator.validate(args)
            if error:
                result.SetError(error + "\n" + self.help())
                return

            parts = validator._split_command_with_escape(args)
            lldb_command, question = parts[0], " ".join(parts[1:])

            executor = CommandExecutor(debugger)
            command_output = executor.execute(lldb_command)
            sections = []
            for i in ("bt", "settings show target.run-args", "process status", "frame variable", "target variable"):
                try:
                    section = f"command: {i}\noutput: {executor.execute(i)}\n"
                except RuntimeError as e:
                    section = f"command: {i}\noutput: {str(e)}\n"
                sections.append(section)
            common_commands_output = "\n".join(sections)
            collector = ContextCollector()
            context = collector.collect_full_context(debugger)
            gpt = GPTIntegrationService(self.session)
            response = gpt.query(lldb_command, command_output, common_commands_output, context, question)

            result.AppendMessage(response)
        except Exception as e:
            result.SetError(str(e))
            result.AppendMessage(self.help())


class AskGptCompleter:
    def __init__(self, debugger):
        self.debugger = debugger
        self._cached_commands = None

    def _get_command_part(self, current_input: str) -> str:
        command_part, _ = CommandParser.split_command_input(current_input)
        return command_part

    def _cache_commands(self):
        ci = self.debugger.GetCommandInterpreter()
        result = lldb.SBStringList()
        ci.GetCommandNames(result, include_aliases=True, include_hidden=False)
        self._cached_commands = [
            (result.GetStringAtIndex(i), " " in result.GetStringAtIndex(i)) for i in range(result.GetSize())
        ]

    def __call__(self, result, current_input):
        command_part, _ = CommandParser.split_command_input(current_input)
        if not command_part:
            return []

        if not self._cached_commands:
            self._cache_commands()

        ci = self.debugger.GetCommandInterpreter()
        completion_result = lldb.SBStringList()
        ci.HandleCompletion(command_part, len(command_part), 0, -1, completion_result)

        official_suggestions = [completion_result.GetStringAtIndex(i) for i in range(completion_result.GetSize())]

        tokens = shlex.split(command_part)
        if len(tokens) > 1:
            return [cmd for cmd in official_suggestions if cmd.startswith(tokens[-1]) and " " not in cmd]

        return [cmd for cmd in official_suggestions if cmd.startswith(command_part) and " " not in cmd]


def __lldb_init_module(debugger, session):
    debugger.HandleCommand(f"command script add -c {__name__}.AskGptCommand askgpt")
    debugger.HandleCommand("command completion add -c {__name__}.AskGptCompleter askgpt")
