from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Union

from .logger import get_logger
from .models_anthropic import AnthropicRequest
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


class KimiK2ToolParser:
    """Parser for Kimi K2 tool call format in both streaming and non-streaming modes."""

    def __init__(self):
        # Tool call tokens and patterns
        self.tool_calls_start_token: str = "<|tool_calls_section_begin|>"
        self.tool_calls_end_token: str = "<|tool_calls_section_end|>"

        self.tool_call_start_token: str = "<|tool_call_begin|>"
        self.tool_call_end_token: str = "<|tool_call_end|>"

        self.tool_call_argument_begin_token: str = "<|tool_call_argument_begin|>"

        # Regex patterns for parsing
        self.tool_call_regex = re.compile(
            r"<\|tool_call_begin\|>\s*(?P<tool_call_id>[\w\.-]+:\d+)\s*<\|tool_call_argument_begin\|>\s*(?P<function_arguments>.*?)\s*<\|tool_call_end\|>",
            re.DOTALL,
        )

        self.stream_tool_call_portion_regex = re.compile(
            r"(?P<tool_call_id>[\w\.-]+:\d+)\s*<\|tool_call_argument_begin\|>\s*(?P<function_arguments>.*)", re.DOTALL
        )

        self.stream_tool_call_name_regex = re.compile(r"(?P<tool_call_id>[\w\.-]+:\d+)\s*")

        # Streaming state
        self.current_tool_id: int = -1
        self.current_tool_name_sent: bool = False
        self.streamed_args_for_tool: List[str] = []
        self.prev_tool_call_arr: List[Dict[str, Any]] = []

    def _parse_tool_id(self, tool_id_str: str) -> tuple[str, str]:
        """
        Parse tool ID string into function name and ID.
        Handles formats like 'functions.utils.do_stuff:1' and 'my-func:2'.
        """
        try:
            # Split from the right on the first colon to separate name part from ID
            name_part, tool_id = tool_id_str.rsplit(":", 1)

            if "." in name_part:
                # Assuming a prefix like 'functions.', extract the actual function name.
                # This correctly handles names like 'utils.do_stuff'.
                function_name = name_part.split(".", 1)[1]
            else:
                # No prefix found, the whole name_part is the function name.
                function_name = name_part
            return function_name, tool_id
        except ValueError:
            # This case handles when there is no ':' in the tool_id_str,
            # which is unlikely based on the regex but good for robustness.
            return tool_id_str, tool_id_str

    def extract_tool_calls(
        self,
        model_output: str,
        request: Optional[AnthropicRequest] = None,
    ) -> ExtractedToolCallInfo:
        """
        Extract tool calls from a complete model output string.
        """
        # Quick check to avoid unnecessary processing
        if self.tool_calls_start_token not in model_output:
            return ExtractedToolCallInfo(tools_called=False, tool_calls=[], content=model_output)

        try:
            # Find all tool calls using regex
            matches = self.tool_call_regex.findall(model_output)

            tool_calls = []
            for match in matches:
                tool_call_id, function_args = match

                # Parse tool ID to get function name and ID
                function_name, tool_id = self._parse_tool_id(tool_call_id)

                # Create tool call
                tool_call = ToolCall(
                    id=f"call_{tool_id}",
                    type="function",
                    function=FunctionCall(name=function_name, arguments=function_args),
                )
                tool_calls.append(tool_call)

            # Extract content before tool calls
            content_end = model_output.find(self.tool_calls_start_token)
            content = model_output[:content_end].strip() if content_end > 0 else None

            return ExtractedToolCallInfo(tools_called=bool(tool_calls), tool_calls=tool_calls, content=content)

        except Exception as e:
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
        """
        Extract tool calls from streaming model output.
        """
        # If no tool call tokens in current text, return as regular content
        if self.tool_call_start_token not in current_text:
            # Clean up tool call tokens from delta text
            cleaned_delta = delta_text.replace(self.tool_calls_start_token, "")
            cleaned_delta = cleaned_delta.replace(self.tool_calls_end_token, "")
            return DeltaMessage(content=cleaned_delta)

        # Process tool call tokens
        delta_text = delta_text.replace(self.tool_calls_start_token, "")
        delta_text = delta_text.replace(self.tool_calls_end_token, "")

        try:
            # Count tool call start and end tokens
            prev_tool_start_count = previous_text.count(self.tool_call_start_token)
            prev_tool_end_count = previous_text.count(self.tool_call_end_token)
            cur_tool_start_count = current_text.count(self.tool_call_start_token)
            cur_tool_end_count = current_text.count(self.tool_call_end_token)

            # Case 1: Generating text or finishing tool call
            if (
                cur_tool_start_count == cur_tool_end_count
                and prev_tool_end_count == cur_tool_end_count
                and self.tool_call_end_token not in delta_text
            ):
                return DeltaMessage(content=delta_text)

            # Case 2: Starting a new tool call
            if cur_tool_start_count > cur_tool_end_count and cur_tool_start_count > prev_tool_start_count:
                # Reset state for new tool call
                self.current_tool_id += 1
                self.current_tool_name_sent = False
                self.streamed_args_for_tool.append("")

                # Extract tool call portion
                tool_call_portion = current_text.split(self.tool_call_start_token)[-1]

                # Extract tool ID and name
                name_match = self.stream_tool_call_name_regex.search(tool_call_portion)
                if name_match:
                    tool_id_str = name_match.group("tool_call_id")
                    function_name, tool_id = self._parse_tool_id(tool_id_str)

                    # Send tool call start event
                    self.current_tool_name_sent = True
                    return DeltaMessage(
                        tool_calls=[
                            DeltaToolCall(
                                index=self.current_tool_id,
                                id=f"call_{tool_id}",
                                type="function",
                                function=DeltaFunctionCall(name=function_name),
                            )
                        ]
                    )

            # Case 3: Updating an existing tool call
            elif cur_tool_start_count > cur_tool_end_count and cur_tool_start_count == prev_tool_start_count:
                tool_call_portion = current_text.split(self.tool_call_start_token)[-1]
                matches = self.stream_tool_call_portion_regex.search(tool_call_portion)

                if matches:
                    tool_id_str, function_args = matches.groups()
                    function_name, tool_id = self._parse_tool_id(tool_id_str)

                    # Update previous tool call state
                    if len(self.prev_tool_call_arr) <= self.current_tool_id:
                        self.prev_tool_call_arr.append({})

                    prev_args = self.prev_tool_call_arr[self.current_tool_id].get("arguments", "")

                    # Send arguments delta if available
                    if function_args and len(function_args) > len(prev_args):
                        delta_args = function_args[len(prev_args) :]
                        self.prev_tool_call_arr[self.current_tool_id]["arguments"] = function_args
                        self.streamed_args_for_tool[self.current_tool_id] = function_args

                        return DeltaMessage(
                            tool_calls=[
                                DeltaToolCall(
                                    index=self.current_tool_id, function=DeltaFunctionCall(arguments=delta_args)
                                )
                            ]
                        )

            # Case 4: Finishing a tool call
            elif cur_tool_start_count == cur_tool_end_count and cur_tool_end_count > prev_tool_end_count:
                # Find the complete tool call
                full_tool_call = current_text.split(self.tool_call_start_token)[-1].split(self.tool_call_end_token)[0]
                matches = self.stream_tool_call_portion_regex.search(full_tool_call)

                if matches and self.current_tool_id < len(self.prev_tool_call_arr):
                    tool_id_str, function_args = matches.groups()
                    function_name, tool_id = self._parse_tool_id(tool_id_str)

                    # Send any remaining arguments
                    prev_args = self.prev_tool_call_arr[self.current_tool_id].get("arguments", "")
                    if len(function_args) > len(prev_args):
                        delta_args = function_args[len(prev_args) :]
                        return DeltaMessage(
                            tool_calls=[
                                DeltaToolCall(
                                    index=self.current_tool_id, function=DeltaFunctionCall(arguments=delta_args)
                                )
                            ]
                        )

        except Exception as e:
            logger.exception("Error in streaming tool call extraction.")

        return None
