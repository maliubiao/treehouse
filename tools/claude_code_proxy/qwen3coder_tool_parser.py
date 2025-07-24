# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
# SPDX-FileCopyrightText: Copyright contributors to the Claude Code Proxy project

import json
import re
import uuid
from collections.abc import Generator
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Union

from .logger import get_logger
from .models_openai import ExtractedToolCallInfo
from .models_openai import (
    OpenAIChatMessageDelta as DeltaMessage,
)
from .models_openai import (
    OpenAIFunctionCall as FunctionCall,
)
from .models_openai import (
    OpenAIFunctionCallDelta as DeltaFunctionCall,
)
from .models_openai import (
    OpenAIRequest as ChatCompletionRequest,
)
from .models_openai import (
    OpenAITool as ChatCompletionToolsParam,
)
from .models_openai import (
    OpenAIToolCall as ToolCall,
)
from .models_openai import (
    OpenAIToolCallDelta as DeltaToolCall,
)

logger = get_logger(__name__)


class Qwen3CoderToolParser:
    """Parser for Qwen3 Coder tool call format in both streaming and non-streaming modes."""

    def __init__(self):
        # Sentinel tokens for streaming mode
        self.tool_call_start_token: str = "<tool_call>"
        self.tool_call_end_token: str = "</tool_call>"
        self.tool_call_prefix: str = "<function="
        self.function_end_token: str = "</function>"
        self.parameter_prefix: str = "<parameter="
        self.parameter_end_token: str = "</parameter>"

        # Streaming state variables
        self.is_tool_call_started: bool = False
        self.current_tool_index: int = 0
        self.header_sent: bool = False
        self.current_tool_string_id: Optional[str] = None
        self.current_function_name: Optional[str] = None
        self.current_param_name: Optional[str] = None
        self.current_param_value: str = ""
        self.param_count: int = 0
        self.in_param: bool = False
        self.in_function: bool = False
        self.accumulated_text: str = ""
        self.json_started: bool = False
        self.json_closed: bool = False
        self.prev_tool_call_arr: list[dict] = []

        # Enhanced streaming state - reset for each new message
        self._reset_streaming_state()

        # Regex patterns
        self.tool_call_complete_regex = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
        self.tool_call_regex = re.compile(
            r"<tool_call>(.*?)</tool_call>|<tool_call>(.*?)$", re.DOTALL
        )  # 修复了正则，使其能匹配到内容
        self.tool_call_function_regex = re.compile(r"<function=(.*?)</function>|<function=(.*)$", re.DOTALL)
        self.tool_call_parameter_regex = re.compile(r"<parameter=(.*?)</parameter>|<parameter=(.*?)$", re.DOTALL)

    def _generate_tool_call_id(self) -> str:
        """Generate a unique tool call ID."""
        return f"call_{uuid.uuid4().hex[:24]}"

    def _reset_streaming_state(self):
        """Reset all streaming state."""
        self.current_tool_index = 0
        self.is_tool_call_started = False
        self.header_sent = False
        self.current_tool_string_id = None
        self.current_function_name = None
        self.current_param_name = None
        self.current_param_value = ""
        self.param_count = 0
        self.in_param = False
        self.in_function = False
        self.accumulated_text = ""
        self.json_started = False
        self.json_closed = False
        self.prev_tool_call_arr.clear()

    def _parse_xml_function_call(
        self, function_call_str: str, tools: Optional[list[ChatCompletionToolsParam]]
    ) -> Optional[ToolCall]:
        # --- MODIFIED get_arguments_config ---
        def get_arguments_config(func_name: str) -> dict:
            """
            Retrieves the argument schema for a given function name,
            compatible with AnthropicTool (input_schema) structure.
            """
            if tools is None:
                return {}
            for config in tools:
                # 确保按工具名称精确匹配
                if config.name == func_name:
                    if hasattr(config, "input_schema") and isinstance(config.input_schema, dict):
                        params_schema = config.input_schema
                        if isinstance(params_schema, dict) and "properties" in params_schema:
                            return params_schema["properties"]
                    # Fallback to original vLLM structure check
                    elif hasattr(config, "type") and hasattr(config, "function"):
                        if (
                            config.type == "function"
                            and hasattr(config.function, "name")
                            and config.function.name == func_name
                        ):
                            if hasattr(config.function, "parameters"):
                                params = config.function.parameters
                                if isinstance(params, dict) and "properties" in params:
                                    return params["properties"]
                                elif isinstance(params, dict):
                                    return params
                            return {}
            logger.warning("Tool '%s' is not defined in the tools list.", func_name)
            return {}

        # --- END MODIFIED get_arguments_config ---

        def convert_param_value(param_value: str, param_name: str, param_config: dict, func_name: str) -> Any:
            """Convert parameter value based on JSON schema type."""
            if param_value.lower() == "null":
                return None

            # 获取参数类型定义
            param_schema = param_config.get(param_name, {})
            param_type = param_schema.get("type", "string")

            try:
                # 根据类型进行转换
                if param_type == "number":
                    return float(param_value)
                elif param_type == "integer":
                    return int(param_value)
                elif param_type == "boolean":
                    return bool(param_value.lower() == "true")
                else:  # string or other types
                    return param_value
            except (ValueError, TypeError):
                logger.warning(
                    "Failed to convert parameter '%s' to type '%s' for tool '%s'. Keeping as string.",
                    param_name,
                    param_type,
                    func_name,
                )
                return param_value

        # Extract function name
        end_index = function_call_str.index(">")
        function_name = function_call_str[:end_index]
        param_config = get_arguments_config(function_name)
        parameters = function_call_str[end_index + 1 :]
        param_dict = {}
        for match in self.tool_call_parameter_regex.findall(parameters):
            match_text = match[0] if match[0] else match[1]
            idx = match_text.index(">")
            param_name = match_text[:idx]
            param_value = str(match_text[idx + 1 :])
            # Remove prefix and trailing \n
            if param_value.startswith("\n"):
                param_value = param_value[1:]
            if param_value.endswith("\n"):
                param_value = param_value[:-1]

            param_dict[param_name] = convert_param_value(param_value, param_name, param_config, function_name)
        return ToolCall(
            id=self._generate_tool_call_id(),
            type="function",
            function=FunctionCall(name=function_name, arguments=json.dumps(param_dict, ensure_ascii=False)),
        )

    def _get_function_calls(self, model_output: str) -> list[str]:
        """Extracts raw function call strings from the model output."""
        # Find all complete tool calls (with both start and end tokens)
        tool_call_matches = self.tool_call_complete_regex.findall(model_output)

        if not tool_call_matches:
            # If no complete tool calls found, check for partial ones
            tool_call_matches = [match[1] for match in self.tool_call_regex.findall(model_output) if match[1]]

        if not tool_call_matches:
            return []

        raw_function_calls = []
        for tool_call_content in tool_call_matches:
            # Find function calls within each tool call block
            func_matches = self.tool_call_function_regex.findall(tool_call_content)
            for match in func_matches:
                func_content = match[0] if match[0] else match[1]
                if func_content.strip():
                    raw_function_calls.append(func_content)

        return raw_function_calls

    def extract_tool_calls(
        self,
        model_output: str,
        request: ChatCompletionRequest,
    ) -> ExtractedToolCallInfo:
        # Quick check to avoid unnecessary processing
        if self.tool_call_prefix not in model_output:
            return ExtractedToolCallInfo(tools_called=False, tool_calls=[], content=model_output)

        try:
            function_calls = self._get_function_calls(model_output)
            if len(function_calls) == 0:
                return ExtractedToolCallInfo(tools_called=False, tool_calls=[], content=model_output)

            tool_calls = [
                self._parse_xml_function_call(function_call_str, request.tools)
                for function_call_str in function_calls
                if self._parse_xml_function_call(function_call_str, request.tools) is not None
            ]

            # Populate prev_tool_call_arr for serving layer to set
            # finish_reason
            self.prev_tool_call_arr.clear()
            for tool_call in tool_calls:
                if tool_call:
                    self.prev_tool_call_arr.append(
                        {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        }
                    )

            # Extract content before tool calls
            content_index = model_output.find(self.tool_call_start_token)
            content_index = content_index if content_index >= 0 else model_output.find(self.tool_call_prefix)
            content = model_output[:content_index]

            return ExtractedToolCallInfo(
                tools_called=(len(tool_calls) > 0),
                tool_calls=tool_calls,
                content=content if content else None,
            )

        except Exception:
            logger.exception("Error in extracting tool call from response.")
            return ExtractedToolCallInfo(tools_called=False, tool_calls=[], content=model_output)

    def extract_tool_calls_streaming(
        self,
        previous_text: str,
        current_text: str,
        delta_text: str,
        previous_token_ids: Sequence[int],
        current_token_ids: Sequence[int],
        delta_token_ids: Sequence[int],
        request: ChatCompletionRequest,
    ) -> Union[DeltaMessage, None]:
        # If no delta text, return None unless it's an EOS token after tool
        # calls
        if not delta_text:
            # Check if this is an EOS token after all tool calls are complete
            # We check for tool calls in the text even if is_tool_call_started
            # is False because it might have been reset after processing all
            # tools
            if delta_token_ids and self.tool_call_end_token not in delta_token_ids:
                # Count complete tool calls
                complete_calls = len(self.tool_call_complete_regex.findall(current_text))

                # If we have completed tool calls and populated
                # prev_tool_call_arr
                if complete_calls > 0 and len(self.prev_tool_call_arr) > 0:
                    # Check if all tool calls are closed
                    open_calls = current_text.count(self.tool_call_start_token) - current_text.count(
                        self.tool_call_end_token
                    )
                    if open_calls == 0:
                        # Return empty delta message to allow finish_reason
                        # processing
                        return DeltaMessage(content="")
                elif not self.is_tool_call_started and current_text:
                    # This is a regular content response that's now complete
                    return DeltaMessage(content="")
            return None

        # Check if this is the first call (reset state if needed)
        if not previous_text:
            self._reset_streaming_state()

        # Update accumulated text
        self.accumulated_text = current_text

        # Check if we need to advance to next tool
        if self.json_closed and not self.in_function:
            # Check if this tool call has ended
            tool_ends = current_text.count(self.tool_call_end_token)
            if tool_ends > self.current_tool_index:
                # This tool has ended, advance to next
                self.current_tool_index += 1
                self.header_sent = False
                self.param_count = 0
                self.json_started = False
                self.json_closed = False

                # Check if there are more tool calls
                tool_starts_count = current_text.count(self.tool_call_start_token)
                if self.current_tool_index >= tool_starts_count:
                    # No more tool calls
                    self.is_tool_call_started = False
                # Continue processing next tool
                return None

        # Handle normal content before tool calls
        if not self.is_tool_call_started:
            # Check if tool call is starting
            if self.tool_call_start_token in delta_text:
                self.is_tool_call_started = True
                # Return any content before the tool call
                if self.tool_call_start_token in delta_text:
                    content_before = delta_text[: delta_text.index(self.tool_call_start_token)]
                    if content_before:
                        return DeltaMessage(content=content_before)
                return None
            else:
                # Check if we're between tool calls - skip whitespace
                if current_text.rstrip().endswith(self.tool_call_end_token) and delta_text.strip() == "":
                    # We just ended a tool call, skip whitespace
                    return None
                # Normal content, no tool call
                return DeltaMessage(content=delta_text)

        # Check if we're between tool calls (waiting for next one)
        # Count tool calls we've seen vs processed
        tool_starts_count = current_text.count(self.tool_call_start_token)
        if self.current_tool_index >= tool_starts_count:
            # We're past all tool calls, shouldn't be here
            return None

        # We're in a tool call, find the current tool call portion
        # Need to find the correct tool call based on current_tool_index
        tool_starts: list[int] = []
        idx = 0
        while True:
            idx = current_text.find(self.tool_call_start_token, idx)
            if idx == -1:
                break
            tool_starts.append(idx)
            idx += len(self.tool_call_start_token)

        if self.current_tool_index >= len(tool_starts):
            # No more tool calls to process yet
            return None

        tool_start_idx = tool_starts[self.current_tool_index]
        # Find where this tool call ends (or current position if not ended yet)
        tool_end_idx = current_text.find(self.tool_call_end_token, tool_start_idx)
        if tool_end_idx == -1:
            tool_text = current_text[tool_start_idx:]
        else:
            tool_text = current_text[tool_start_idx : tool_end_idx + len(self.tool_call_end_token)]

        # Looking for function header
        if not self.header_sent:
            if self.tool_call_prefix in tool_text:
                func_start = tool_text.find(self.tool_call_prefix) + len(self.tool_call_prefix)
                func_end = tool_text.find(">", func_start)

                if func_end != -1:
                    # Found complete function name
                    self.current_function_name = tool_text[func_start:func_end]
                    self.current_tool_string_id = self._generate_tool_call_id()
                    self.header_sent = True
                    self.in_function = True

                    # IMPORTANT: Add to prev_tool_call_arr immediately when we
                    # detect a tool call. This ensures
                    # finish_reason="tool_calls" even if parsing isn't complete
                    already_added = any(
                        tool.get("name") == self.current_function_name for tool in self.prev_tool_call_arr
                    )
                    if not already_added:
                        self.prev_tool_call_arr.append(
                            {
                                "name": self.current_function_name,
                                "arguments": "{}",  # Placeholder, will be updated later
                            }
                        )

                    # Send header with function info
                    return DeltaMessage(
                        tool_calls=[
                            DeltaToolCall(
                                index=self.current_tool_index,
                                id=self.current_tool_string_id,
                                function=DeltaFunctionCall(name=self.current_function_name, arguments=""),
                                type="function",
                            )
                        ]
                    )
            return None

        # We've sent header, now handle function body
        if self.in_function:
            # Send opening brace if not sent yet
            if not self.json_started and self.parameter_prefix not in delta_text:
                self.json_started = True
                return DeltaMessage(
                    tool_calls=[
                        DeltaToolCall(
                            index=self.current_tool_index,
                            function=DeltaFunctionCall(arguments="{"),
                        )
                    ]
                )

            # Make sure json_started is set if we're processing parameters
            if not self.json_started:
                self.json_started = True

            # Check for function end in accumulated text
            if not self.json_closed and self.function_end_token in tool_text:
                # Close JSON
                self.json_closed = True

                # Extract the complete tool call to update prev_tool_call_arr
                # with final arguments. Find the function content
                func_start = tool_text.find(self.tool_call_prefix) + len(self.tool_call_prefix)
                func_content_end = tool_text.find(self.function_end_token, func_start)
                if func_content_end != -1:
                    func_content = tool_text[func_start:func_content_end]
                    # Parse to get the complete arguments
                    try:
                        parsed_tool = self._parse_xml_function_call(func_content, request.tools if request else None)
                        if parsed_tool:
                            # Update existing entry in prev_tool_call_arr with
                            # complete arguments
                            for i, tool in enumerate(self.prev_tool_call_arr):
                                if tool.get("name") == parsed_tool.function.name:
                                    self.prev_tool_call_arr[i]["arguments"] = parsed_tool.function.arguments
                                    break
                    except Exception:
                        pass  # Ignore parsing errors during streaming

                result = DeltaMessage(
                    tool_calls=[
                        DeltaToolCall(
                            index=self.current_tool_index,
                            function=DeltaFunctionCall(arguments="}"),
                        )
                    ]
                )

                # Reset state for next tool
                self.in_function = False
                self.json_closed = True

                return result

            # Look for parameters
            # Count how many complete parameters we have processed
            complete_params = tool_text.count(self.parameter_end_token)

            # Check if we should start a new parameter
            if not self.in_param and self.param_count < complete_params:
                # Find the unprocessed parameter
                # Count parameter starts
                param_starts = []
                idx = 0
                while True:
                    idx = tool_text.find(self.parameter_prefix, idx)
                    if idx == -1:
                        break
                    param_starts.append(idx)
                    idx += len(self.parameter_prefix)

                if len(param_starts) > self.param_count:
                    # Process the next parameter
                    param_idx = param_starts[self.param_count]
                    param_start = param_idx + len(self.parameter_prefix)
                    remaining = tool_text[param_start:]

                    if ">" in remaining:
                        # We have the complete parameter name
                        name_end = remaining.find(">")
                        self.current_param_name = remaining[:name_end]

                        # Find the parameter value
                        value_start = param_start + name_end + 1
                        value_text = tool_text[value_start:]
                        if value_text.startswith("\n"):
                            value_text = value_text[1:]

                        # Find where this parameter ends
                        param_end_idx = value_text.find(self.parameter_end_token)
                        if param_end_idx != -1:
                            # Complete parameter found
                            param_value = value_text[:param_end_idx]
                            if param_value.endswith("\n"):
                                param_value = param_value[:-1]

                            # Build complete JSON fragment for this parameter
                            if self.param_count == 0:
                                json_fragment = (
                                    '"' + self.current_param_name + '": "' + json.dumps(param_value)[1:-1] + '"'
                                )
                            else:
                                json_fragment = (
                                    ', "' + self.current_param_name + '": "' + json.dumps(param_value)[1:-1] + '"'
                                )

                            self.param_count += 1

                            return DeltaMessage(
                                tool_calls=[
                                    DeltaToolCall(
                                        index=self.current_tool_index,
                                        function=DeltaFunctionCall(arguments=json_fragment),
                                    )
                                ]
                            )

            # Continue parameter value
            if self.in_param:
                if self.parameter_end_token in delta_text:
                    # End of parameter
                    end_idx = delta_text.find(self.parameter_end_token)
                    value_chunk = delta_text[:end_idx]

                    # Skip past > if at start
                    if not self.current_param_value and ">" in value_chunk:
                        gt_idx = value_chunk.find(">")
                        value_chunk = value_chunk[gt_idx + 1 :]

                    if not self.current_param_value and value_chunk.startswith("\n"):
                        value_chunk = value_chunk[1:]

                    # Calculate incremental JSON
                    full_value = self.current_param_value + value_chunk
                    prev_escaped = json.dumps(self.current_param_value)[1:-1] if self.current_param_value else ""
                    full_escaped = json.dumps(full_value)[1:-1]
                    delta_escaped = full_escaped[len(prev_escaped) :]

                    self.in_param = False
                    self.current_param_value = ""

                    return DeltaMessage(
                        tool_calls=[
                            DeltaToolCall(
                                index=self.current_tool_index,
                                function=DeltaFunctionCall(arguments=delta_escaped + '"'),
                            )
                        ]
                    )
                else:
                    # Continue accumulating value
                    value_chunk = delta_text

                    # Handle first chunk after param name
                    if not self.current_param_value and ">" in value_chunk:
                        gt_idx = value_chunk.find(">")
                        value_chunk = value_chunk[gt_idx + 1 :]

                    if not self.current_param_value and value_chunk.startswith("\n"):
                        value_chunk = value_chunk[1:]

                    if value_chunk:
                        # Stream the escaped delta
                        prev_escaped = json.dumps(self.current_param_value)[1:-1] if self.current_param_value else ""
                        self.current_param_value += value_chunk
                        full_escaped = json.dumps(self.current_param_value)[1:-1]
                        delta_escaped = full_escaped[len(prev_escaped) :]

                        if delta_escaped:
                            return DeltaMessage(
                                tool_calls=[
                                    DeltaToolCall(
                                        index=self.current_tool_index,
                                        function=DeltaFunctionCall(arguments=delta_escaped),
                                    )
                                ]
                            )

        return None
