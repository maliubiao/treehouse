import re
from typing import Tuple


class CommandParser:
    @staticmethod
    def split_command_input(input_str: str) -> Tuple[str, str]:
        """
        Split input string into command and question parts using unescaped '::' as delimiter.
        Handles escaped '::' sequences by converting them back to '::'.
        Also handles context markers in the input.
        """
        # First check for context markers
        if "[context start]" in input_str and "[context end]" in input_str:
            input_str = input_str.replace("[context start]", "").replace("[context end]", "")

        parts = re.split(r"(?<!\\)::", input_str, maxsplit=1)
        if len(parts) < 2:
            return ("", input_str)

        command_part = parts[0].replace(r"\::", "::")
        question_part = parts[1].replace(r"\::", "::")
        return (command_part.strip(), question_part.strip())
