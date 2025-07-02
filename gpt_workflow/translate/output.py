#!/usr/bin/env python3
"""
Output building and saving functionality
"""

from pathlib import Path
from typing import Dict, List, Tuple


def build_output(
    translation_cache: Dict[Tuple[int, int], str], source_lines: List[str], direction: str, logger
) -> List[str]:
    """Build the final output by combining translated and original content"""
    output_lines = []
    current_line = 1

    # Sort translations by start line
    sorted_translations = sorted(translation_cache.items(), key=lambda x: x[0][0])

    for (start, end), translated_text in sorted_translations:
        # Add any untranslated lines before this segment
        while current_line < start:
            line_content = source_lines[current_line - 1]
            if line_content.strip() == "":
                output_lines.append(line_content)
            current_line += 1

        # Add the translated lines
        translated_lines = translated_text.split("\n")
        for i, line in enumerate(translated_lines, start=start):
            if i <= end:
                output_lines.append(line + "\n")
            else:
                output_lines.append(line + "\n")
        current_line = end + 1

    # Add any remaining untranslated lines (only if blank)
    while current_line <= len(source_lines):
        line_content = source_lines[current_line - 1]
        if line_content.strip() == "":
            output_lines.append(line_content)
        current_line += 1

    return output_lines


def save_output(output_lines: List[str], output_file: Path, logger):
    """Save the translated output to file"""
    with open(output_file, "w", encoding="utf-8") as f:
        f.writelines(output_lines)
    logger.info(f"Saved translation to: {output_file}")
