#!/usr/bin/env python3
"""
Core translation functionality
"""

import concurrent.futures
import re
import threading
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

from .logging import TranslationLogger


def translate_parallel(
    paragraphs: List[Dict],
    source_lines: List[str],
    direction: str,
    max_workers: int,
    logger: TranslationLogger,
    model_switch,
) -> Tuple[Dict[Tuple[int, int], str], List[Dict]]:
    """Translate paragraphs in parallel"""
    logger.info(f"Starting parallel translation with {max_workers} workers")
    translation_cache = {}
    lock = threading.Lock()
    translation_log = []

    def _translate_paragraph(para: Dict) -> Tuple[int, int, str]:
        """Translate a single paragraph"""
        start, end = map(int, para["line_range"].split("-"))
        paragraph_text = "".join(source_lines[start - 1 : end])

        if is_empty_content(paragraph_text):
            logger.info(f"Skipping translation for empty/whitespace-only lines {start}-{end}")
            return start, end, paragraph_text

        with lock:
            if (start, end) in translation_cache:
                logger.info(f"Using cached translation for lines {start}-{end}")
                return start, end, translation_cache[(start, end)]

        try:
            # Record original indentation
            original_indents = []
            for line in source_lines[start - 1 : end]:
                indent = re.match(r"^(\s*)", line).group(1)
                original_indents.append(indent)

            prompt = get_translation_prompt(paragraph_text, direction)
            logger.info(f"Translating lines {start}-{end} (direction: {direction})")
            response = model_switch.query("translate", prompt, verbose=False)
            translated_text = response

            if "[translation start]" in translated_text and "[translation end]" in translated_text:
                translated_text = translated_text.split("[translation start]")[1].split("[translation end]")[0]

            # Restore original indentation
            translated_lines = translated_text.split("\n")
            processed_lines = []
            for i, line in enumerate(translated_lines):
                if i < len(original_indents):
                    current_indent = re.match(r"^(\s*)", line).group(1)
                    if len(current_indent) < len(original_indents[i]):
                        line = original_indents[i] + line.lstrip()
                    elif len(current_indent) > len(original_indents[i]):
                        line = original_indents[i] + line[len(current_indent) :]
                processed_lines.append(line)

            translated_text = "\n".join(processed_lines)

            with lock:
                translation_cache[(start, end)] = translated_text
                translation_log.append(
                    {
                        "line_range": f"{start}-{end}",
                        "original": paragraph_text,
                        "translated": translated_text,
                        "direction": direction,
                        "prompt": prompt,
                    }
                )
                return start, end, translated_text

        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as e:
            logger.error(f"Error translating lines {start}-{end}: {e}")
            return start, end, paragraph_text

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_translate_paragraph, para) for para in paragraphs]
        for future in concurrent.futures.as_completed(futures):
            start, end, _ = future.result()
            logger.info(f"Completed translation for lines {start}-{end}")

    return translation_cache, translation_log


def is_empty_content(text: str) -> bool:
    """Check if text contains only whitespace, punctuation, or control characters"""
    if not text.strip():
        return True

    stripped = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("Z") or category.startswith("P") or category == "Cc":
            continue
        stripped.append(char)

    return not bool("".join(stripped))


def get_translation_prompt(paragraph_text: str, direction: str) -> str:
    """Get the appropriate translation prompt based on direction"""
    prompt_file = {
        "zh-en": "translate-zh-eng",
        "any-zh": "translate-any-zh",
    }.get(direction)

    if not prompt_file:
        raise ValueError(f"Unsupported translation direction: {direction}")

    prompt_path = Path(__file__).parent.parent.parent / "prompts" / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()

    return f"{prompt}\n\n[text start]{paragraph_text}[text end]"


def find_gaps(paragraphs: List[Dict], source_lines: List[str]) -> List[Dict]:
    """Find gaps between paragraphs and create new paragraphs for non-blank content"""
    sorted_paragraphs = sorted(paragraphs, key=lambda p: int(p["line_range"].split("-")[0]))
    gaps = []
    prev_end = 0

    for para in sorted_paragraphs:
        start, end = map(int, para["line_range"].split("-"))
        if start > prev_end + 1:
            gap_lines = source_lines[prev_end : start - 1]
            if not is_blank_content(gap_lines):
                original_indents = []
                for line in gap_lines:
                    indent = re.match(r"^(\s*)", line).group(1)
                    original_indents.append(indent)

                gaps.append(
                    {
                        "line_range": f"{prev_end + 1}-{start - 1}",
                        "content": "".join(gap_lines),
                        "original_indents": original_indents,
                    }
                )
        prev_end = end

    if prev_end < len(source_lines):
        gap_lines = source_lines[prev_end:]
        if not is_blank_content(gap_lines):
            original_indents = []
            for line in gap_lines:
                indent = re.match(r"^(\s*)", line).group(1)
                original_indents.append(indent)

            gaps.append(
                {
                    "line_range": f"{prev_end + 1}-{len(source_lines)}",
                    "content": "".join(gap_lines),
                    "original_indents": original_indents,
                }
            )

    return gaps


def is_blank_content(lines: List[str]) -> bool:
    """Check if given lines are blank (whitespace only)"""
    return all(line.strip() == "" for line in lines)
