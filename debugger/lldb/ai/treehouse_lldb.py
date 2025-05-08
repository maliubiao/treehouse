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

        if "::" not in args:
            return ""  # Pure question mode is always valid

        if not re.match(r"^.+?\s*::\s*.+$", args):
            return "Command format error, use 'askgpt <command> :: <question>' or 'askgpt <question>' format"

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
        self.interpreter = debugger.GetCommandInterpreter()

    def execute(self, command: str) -> str:
        return_obj = lldb.SBCommandReturnObject()
        self.interpreter.HandleCommand(command, return_obj)

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
        self.model_switch = ModelSwitch()
        self.current_model = "qwen3"  # 默认模型

    def set_model(self, model_name: str) -> None:
        """设置当前使用的模型"""
        self.current_model = model_name

    def query(
        self, command, command_output: str, common_commands_output: str, context: DebugContext, question: str
    ) -> str:
        temp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as temp_file:
                if command_output:
                    temp_file.write(f"[lldb command start]\n{command}\n[lldb command end]\n")
                    temp_file.write(f"[output start]\n{command_output}\n[output end]\n")
                temp_file.write(
                    f"[lldb context start]\n{yaml.dump(context.to_dict(), allow_unicode=True, default_flow_style=False)}[lldb context end]\n"
                )
                temp_file_path = temp_file.name

            self.model_switch.select(self.current_model)
            prompt = GPTContextProcessor().process_text(
                f"[some debug commands output]\n{common_commands_output}[some debug commands output end]\n"
                f"lldb context as the following:\n @{temp_file_path} \n[user question]\n{question}\n[user question end]"
            )
            print(prompt)
            return self.model_switch.query_for_text(self.current_model, prompt, disable_conversation_history=True)
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)


class ModelSwitchCommand:
    def __init__(self, *args):
        self.model_switch = ModelSwitch()
        from . import gpt_service

        self.gpt_service = gpt_service

    def help(self):
        available_models = "\n  ".join(self.model_switch.models())
        return f"""Model Switch Help:
Usage: modelswitch <model_name>
Available models:
  {available_models}
Current model: {self.gpt_service.current_model}"""

    @trace(target_files=["*.py"])
    def __call__(self, debugger, args, exe_ctx, result):
        if not args.strip():
            result.AppendMessage(self.help())
            return

        model_name = args.strip()
        if model_name not in self.model_switch.models():
            result.SetError(f"Invalid model name: {model_name}\n{self.help()}")
            return

        self.gpt_service.set_model(model_name)
        result.AppendMessage(f"Model switched to: {model_name}")


class AskGptCommand:
    def __init__(self, debugger, session, *args):
        self.debugger = debugger
        self.session = session
        from . import gpt_service

        self.gpt_service = gpt_service

    def help(self):
        return """AskGPT Help:
Usage:
  askgpt <lldb_command> :: <question>  - Execute LLDB command and ask about its output
  askgpt <question>                    - Ask a general question about the current debug session

Examples:
  askgpt memory read 0x16fdd79c0 :: explain this memory
  askgpt thread backtrace :: analyze call stack
  askgpt What's wrong with my program?
  askgpt help"""

    def collect_frame_code(self, debugger):
        target = debugger.GetSelectedTarget()
        process = target.GetProcess()
        thread = process.GetSelectedThread()
        executor = CommandExecutor(debugger)
        result = ["\n"]
        for i in range(thread.num_frames - 1):
            result.append(f"command : frame select {i}\n")
            result.append(executor.execute(f"frame select {i}"))
            result.append("\n")
            frame = thread.GetFrameAtIndex(i)
            result.append(f"frame {i}: {frame}\n")
            for att in ["addr", "args", "compile_unit", "function", "line_entry", "module", "name", "symbol"]:
                result.append(f"{att}: {getattr(frame, att)}\n")
            result.append("disassemble:\n")
            result.append(frame.Disassemble())
            if frame.line_entry.file:
                with open(frame.line_entry.file.fullpath, "r") as f:
                    lines = f.readlines()
                    start_line = max(0, frame.line_entry.line - 10)
                    end_line = min(len(lines), frame.line_entry.line + 10)
                    result.append("\n[source code]:\n")
                    for i in range(start_line, end_line):
                        if i == frame.line_entry.line - 1:
                            result.append(f"{i + 1}: {lines[i].rstrip('\n')} <--\n")
                        else:
                            result.append(f"{i + 1}: {lines[i]}")
                    result.append("\n")
            result.append("\n")
        return "".join(result)

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

            if "::" in args:
                parts = validator._split_command_with_escape(args)
                lldb_command, question = parts[0], " ".join(parts[1:])
                executor = CommandExecutor(debugger)
                command_output = executor.execute(lldb_command)
            else:
                lldb_command = None
                command_output = ""
                question = args.strip()
            executor = CommandExecutor(debugger)
            sections = []
            for i in ("settings show target.run-args", "process status", "bt", "frame variable", "target variable"):
                try:
                    section = f"command: {i}\noutput: {executor.execute(i)}\n"
                except RuntimeError as e:
                    section = f"command: {i}\noutput: {str(e)}\n"
                sections.append(section)
            common_commands_output = "\n".join(sections) + self.collect_frame_code(debugger)
            collector = ContextCollector()
            context = collector.collect_full_context(debugger)
            response = self.gpt_service.query(lldb_command, command_output, common_commands_output, context, question)

            result.AppendMessage(response)
        except Exception as e:
            result.SetError(str(e))
            result.AppendMessage(self.help())


class AskGptCompleter:
    @trace(target_files=["*.py"])
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
