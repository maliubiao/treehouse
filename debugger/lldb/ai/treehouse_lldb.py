import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import lldb
import yaml

from debugger.tracer import trace
from llm_query import (
    CmdNode,
    GPTContextProcessor,
    ModelSwitch,
    save_to_obsidian,
)

from .context.context_collector import ContextCollector, DebugContext


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

        # Strip ANSI color codes from the output
        output = re.sub(r"\x1b\[\d+(;\d+)*m", "", output)

        return output


class GPTIntegrationService:
    def __init__(self, session):
        self.session = session
        self.model_switch = ModelSwitch()
        self.current_model = "qwen3"  # 默认模型
        self.processor = None

    def set_model(self, model_name: str) -> None:
        """设置当前使用的模型"""
        self.current_model = model_name

    def set_processor(self, processor: GPTContextProcessor) -> None:
        """设置当前使用的上下文处理器"""
        self.processor = processor

    def query(
        self, command, command_output: str, common_commands_output: str, context: DebugContext, question: str
    ) -> str:
        temp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as temp_file:
                if command_output:
                    temp_file.write(f"[lldb command start]\n{command}\n[lldb command end]\n")
                    temp_file.write(f"[output start]\n{command_output}\n[output end]\n")
                context_dict = context.to_dict()
                context_yaml = yaml.dump(context_dict, allow_unicode=True, default_flow_style=False)
                temp_file.write(f"[lldb context start]\n{context_yaml}[lldb context end]\n")
                temp_file_path = temp_file.name

            self.model_switch.select(self.current_model)
            role_prompt_path = Path(os.path.join(os.environ["GPT_PATH"], "prompts/lldb-rule"))
            role_prompt = role_prompt_path.read_text("utf-8")
            context_string = (
                f"[some debug commands output]\n{common_commands_output}"
                f"[some debug commands output end]\n"
                f"lldb context as the following:\n @{temp_file_path} \n"
                f"[user question]\n {question} \n[user question end]"
            )
            # 去除控制台色彩控制字符
            clean_prompt = role_prompt + self.processor.process_text(context_string)
            clean_prompt = re.sub(r"\x1b\[[0-9;]*[mK]", "", clean_prompt)
            print(clean_prompt)
            os.environ["GPT_UUID_CONVERSATION"] = uuid.uuid4().hex
            response_text = self.model_switch.query(
                self.current_model,
                clean_prompt,
                disable_conversation_history=False,
            )
            save_to_obsidian(
                os.path.join(os.environ["GPT_PATH"], "obsidian"),
                response_text,
                clean_prompt,
                f"{command} :: {question}",
            )
            return response_text
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
        self.processor = GPTContextProcessor()
        from . import gpt_service

        self.gpt_service = gpt_service
        self.gpt_service.set_processor(self.processor)
        self._register_commands()

    def _register_commands(self):
        """注册自定义命令处理器"""
        self.processor.register_command("frames", self._handle_frames_command)
        self.processor.register_command("frame", self._handle_frame_command)
        self.processor.register_command("status", self._handle_status_command)

    def _handle_frames_command(self, cmd: CmdNode) -> str:
        """处理@frames命令，返回所有帧的详细信息"""
        return self.collect_frame_code(self.debugger)

    def _handle_frame_command(self, cmd: CmdNode) -> str:
        """处理@frame命令，返回当前帧的详细信息"""
        target = self.debugger.GetSelectedTarget()
        process = target.GetProcess()
        thread = process.GetSelectedThread()
        frame = thread.GetSelectedFrame()

        result = []
        frame_str = str(frame)
        result.append(f"Current frame: {frame_str}\n")

        # 使用临时变量避免f-string中的反斜杠
        frame_attrs = ["addr", "args", "compile_unit", "function", "line_entry", "module", "name", "symbol"]
        for att in frame_attrs:
            att_value = getattr(frame, att)
            result.append(f"{att}: {att_value}\n")

        result.append("disassemble:\n")
        result.append(frame.Disassemble())

        if frame.line_entry.file:
            file_path = frame.line_entry.file.fullpath
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    start_line = max(0, frame.line_entry.line - 10)
                    end_line = min(len(lines), frame.line_entry.line + 10)
                    result.append("\n[source code]:\n")
                    for i in range(start_line, end_line):
                        line_num = i + 1
                        line_text = lines[i].rstrip("\n")
                        if i == frame.line_entry.line - 1:
                            result.append(f"{line_num}: {line_text} <--\n")
                        else:
                            result.append(f"{line_num}: {line_text}\n")
                    result.append("\n")
            except Exception as e:
                result.append(f"Error reading source file: {str(e)}\n")
        return "".join(result)

    def _handle_status_command(self, cmd: CmdNode) -> str:
        """处理@status命令，返回调试状态信息"""
        executor = CommandExecutor(self.debugger)
        sections = []
        commands = ("settings show target.run-args", "process status", "bt", "frame variable", "target variable")
        for cmd_str in commands:
            try:
                output = executor.execute(cmd_str)
                section = f"command: {cmd_str}\noutput: {output}\n"
            except RuntimeError as e:
                section = f"command: {cmd_str}\noutput: {str(e)}\n"
            sections.append(section)
        return "\n".join(sections)

    def collect_frame_code(self, debugger):
        target = debugger.GetSelectedTarget()
        process = target.GetProcess()
        thread = process.GetSelectedThread()
        executor = CommandExecutor(debugger)
        result = ["\n"]

        for i in range(thread.num_frames - 1):
            frame_select_cmd = f"frame select {i}"
            result.append(f"command : {frame_select_cmd}\n")
            result.append(executor.execute(frame_select_cmd))
            result.append("\n")
            frame = thread.GetFrameAtIndex(i)
            frame_str = str(frame)
            result.append(f"frame {i}: {frame_str}\n")

            frame_attrs = ["addr", "args", "compile_unit", "function", "line_entry", "module", "name", "symbol"]
            for att in frame_attrs:
                att_value = getattr(frame, att)
                result.append(f"{att}: {att_value}\n")

            result.append("disassemble:\n")
            result.append(frame.Disassemble())

            if frame.line_entry.file:
                file_path = frame.line_entry.file.fullpath
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        start_line = max(0, frame.line_entry.line - 10)
                        end_line = min(len(lines), frame.line_entry.line + 10)
                        result.append("\n[source code]:\n")
                        for j in range(start_line, end_line):
                            line_num = j + 1
                            line_text = lines[j].rstrip("\n")
                            if j == frame.line_entry.line - 1:
                                result.append(f"{line_num}: {line_text} <--\n")
                            else:
                                result.append(f"{line_num}: {line_text}\n")
                        result.append("\n")
                except Exception as e:
                    result.append(f"Error reading source file: {str(e)}\n")
            result.append("\n")
        return "".join(result)

    @trace(target_files=["*.py"], enable_var_trace=True)
    def __call__(self, debugger, args, exe_ctx, result):
        if len(args) == 0:
            result.AppendMessage(self.get_help())
            return

        try:
            validator = CommandValidator(debugger)
            error = validator.validate(args)
            if error:
                result.SetError(error + "\n" + self.get_help())
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

            collector = ContextCollector()
            context = collector.collect_full_context(debugger)
            response = self.gpt_service.query(lldb_command, command_output, "", context, question)

            result.AppendMessage(response)
        except Exception as e:  # pylint: disable=broad-except
            result.SetError(f"Error: {str(e)}\n{self.get_help()}")

    def get_help(self):
        return """AskGPT Help:
Usage:
  askgpt <lldb_command> :: <question>  - Execute LLDB command and ask about its output
  askgpt <question>                    - Ask a general question about the current debug session
  askgpt @frames                       - Show all frames information
  askgpt @frame                        - Show current frame details
  askgpt @status                       - Show debug session status

Examples:
  askgpt memory read 0x16fdd79c0 :: explain this memory
  askgpt thread backtrace :: analyze call stack
  askgpt What's wrong with my program?
  askgpt @frames
  askgpt @status
  askgpt help"""
