#!/usr/bin/env python3
"""
Configuration loading and validation
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from llm_query import GPTContextProcessor, ModelSwitch

from .logging import TranslationLogger


def load_config(
    source_file: Path, yaml_file: Optional[Path], logger: TranslationLogger
) -> Tuple[List[str], List[Dict]]:
    """Load source file and optionally YAML config file"""
    try:
        with open(source_file, "r", encoding="utf-8") as f:
            source_lines = f.readlines()
            logger.info(f"Loaded source file: {source_file} with {len(source_lines)} lines")

        if not yaml_file:
            return source_lines, generate_paragraph_config(source_file, logger)

        with open(yaml_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            paragraphs = []
            for para in config.get("paragraphs", []):
                if isinstance(para, list) and len(para) >= 4:
                    para_dict = {
                        "type": para[0],
                        "line_range": para[1],
                        "line_count": para[2],
                        "summary": para[3],
                    }
                    paragraphs.append(para_dict)
                elif isinstance(para, dict):
                    paragraphs.append(para)
            logger.info(f"Loaded YAML config: {yaml_file} with {len(paragraphs)} paragraphs")
        return source_lines, paragraphs

    except FileNotFoundError as e:
        logger.error(f"Error loading files: {e}")
        raise


def _filter_overlapping_ranges(paragraphs: List[Dict]) -> List[Dict]:
    """Filter out paragraphs whose line ranges are fully contained within other ranges"""
    if not paragraphs:
        return []

    # Convert line ranges to tuples and sort by start line
    sorted_paragraphs = sorted(paragraphs, key=lambda p: tuple(map(int, p["line_range"].split("-"))))

    filtered = []
    prev_start, prev_end = 0, 0

    for para in sorted_paragraphs:
        start, end = map(int, para["line_range"].split("-"))

        # Skip if fully contained within previous range
        if start >= prev_start and end <= prev_end:
            continue

        filtered.append(para)
        prev_start, prev_end = start, end

    return filtered


def _split_large_file(content: str, chunk_size: int = 25 * 1024) -> List[Tuple[str, str, int]]:
    """Split large file content into chunks while preserving complete lines"""
    chunks = []
    current_chunk = []
    current_numbered_chunk = []
    current_size = 0
    line_number = 1

    for line in content.splitlines(keepends=True):
        line_size = len(line.encode("utf-8"))
        numbered_line = f"{line_number:4d} | {line}"

        if current_size + line_size > chunk_size and current_chunk:
            chunks.append(
                (
                    "".join(current_numbered_chunk),
                    "".join(current_chunk),
                    line_number - 1,
                )
            )
            current_chunk = [line]
            current_numbered_chunk = [numbered_line]
            current_size = line_size
            line_number += 1
        else:
            current_chunk.append(line)
            current_numbered_chunk.append(numbered_line)
            current_size += line_size
            line_number += 1

    if current_chunk:
        chunks.append(
            (
                "".join(current_numbered_chunk),
                "".join(current_chunk),
                line_number - 1,
            )
        )

    return chunks


def _process_single_chunk(
    chunk_index: int,
    numbered_chunk: str,
    original_chunk: str,
    endline: int,
    previous_chunk_tail: str,
    previous_numbered_tail: str,
    logger: TranslationLogger,
) -> Tuple[List[Dict], str, str]:
    """Process a single chunk of the source file"""
    # Combine with previous tail content
    current_chunk = previous_chunk_tail + original_chunk
    current_numbered_chunk = previous_numbered_tail + numbered_chunk

    # Create temp files context
    with (
        tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as chunk_file,
        tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as numbered_chunk_file,
    ):
        chunk_file.write(current_chunk)
        numbered_chunk_file.write(current_numbered_chunk)
        chunk_path = Path(chunk_file.name)
        numbered_path = Path(numbered_chunk_file.name)

    try:
        logger.info(f"Generating paragraph configuration for chunk {chunk_index}...")
        config = _get_chunk_config(numbered_path, logger)
        chunk_paragraphs = _parse_chunk_config(config)

        if not chunk_paragraphs:
            return [], "", ""

        # Process tail content if needed
        if chunk_index < endline:
            last_para = chunk_paragraphs[-1]
            start = int(last_para["line_range"].split("-")[0])
            tail_slice = slice(start - 1, endline)

            previous_chunk_tail = current_chunk[tail_slice]
            previous_numbered_tail = "".join(
                f"{line_num:4d} | {line}" for line_num, line in enumerate(current_chunk[tail_slice], start=start)
            )

        return chunk_paragraphs, previous_chunk_tail, previous_numbered_tail

    except Exception as e:
        logger.error(f"Failed to process chunk {chunk_index}: {e}")
        raise
    finally:
        try:
            os.unlink(chunk_path)
            os.unlink(numbered_path)
        except OSError:
            pass


def generate_paragraph_config(source_file: Path, logger: TranslationLogger) -> List[Dict]:
    """Generate paragraph configuration using LLM"""
    with open(source_file, "r", encoding="utf-8") as f:
        content = f.read()

    chunks = _split_large_file(content)
    logger.info(f"Split source file into {len(chunks)} chunks for processing")

    all_paragraphs = []
    previous_chunk_tail = ""
    previous_numbered_tail = ""

    for i, (numbered_chunk, original_chunk, endline) in enumerate(chunks, 1):
        processed_chunk = _process_single_chunk(
            i, numbered_chunk, original_chunk, endline, previous_chunk_tail, previous_numbered_tail, logger
        )
        if processed_chunk:
            chunk_paragraphs, previous_chunk_tail, previous_numbered_tail = processed_chunk
            if i < len(chunks):
                all_paragraphs.extend(chunk_paragraphs[:-1] if len(chunk_paragraphs) > 1 else [])
            else:
                all_paragraphs.extend(chunk_paragraphs)

    return _filter_overlapping_ranges(all_paragraphs)


def _get_chunk_config(numbered_chunk_file: Path, logger: TranslationLogger) -> Dict:
    """Get configuration for a single chunk from LLM"""
    prompt = f"@source-paragraph @{numbered_chunk_file}"
    text = GPTContextProcessor().process_text(prompt)
    response = ModelSwitch().query("segment", text)
    config_text = response

    try:
        return yaml.safe_load(config_text)
    except yaml.scanner.ScannerError:
        return _extract_config_from_error(config_text, logger)


def _extract_config_from_error(config_text: str, logger: TranslationLogger) -> Dict:
    """Handle config extraction when YAML parsing fails"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as tmp_file:
        tmp_file.write(config_text)
        tmp_path = Path(tmp_file.name)

    try:
        t = GPTContextProcessor().process_text(f"@yaml-extract @{tmp_path}")
        extract_response = ModelSwitch().query("segment", t, verbose=False)
        extracted_text = extract_response
        return yaml.safe_load(extracted_text)
    except Exception as e:
        logger.error(f"Failed to extract config from error: {e}")
        raise
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _parse_chunk_config(config: Dict) -> List[Dict]:
    """Parse the chunk configuration into paragraph dictionaries"""
    chunk_paragraphs = []
    for para in config.get("paragraphs", []):
        if isinstance(para, list) and len(para) >= 4:
            para_dict = {
                "type": para[0],
                "line_range": para[1],
                "line_count": para[2],
                "summary": para[3],
            }
            chunk_paragraphs.append(para_dict)
        elif isinstance(para, dict):
            chunk_paragraphs.append(para)
    return chunk_paragraphs


def validate_paragraphs(paragraphs: List[Dict], source_lines: List[str], logger: TranslationLogger):
    """Validate paragraph definitions"""
    filtered_paragraphs = _filter_overlapping_ranges(paragraphs)
    if len(filtered_paragraphs) != len(paragraphs):
        logger.warning(f"Filtered out {len(paragraphs) - len(filtered_paragraphs)} overlapping paragraphs")

    covered_lines = set()
    for para in filtered_paragraphs:
        start, end = map(int, para["line_range"].split("-"))
        if start > end:
            raise ValueError(f"Invalid line range: {para['line_range']}")

        for line in range(start, end + 1):
            if line in covered_lines:
                raise ValueError(f"Duplicate line coverage: {line}")
            covered_lines.add(line)
    logger.info(f"Validated {len(filtered_paragraphs)} paragraphs covering {len(covered_lines)} lines")
