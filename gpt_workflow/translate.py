#!/usr/bin/env python3
"""
需要在配置model.json中指定翻译用的大模型
比如{
    "segment": {
        "key": "sk-**",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_name": "Pro/deepseek-ai/DeepSeek-V3",
        "max_context_size": 131072,
        "max_tokens": 8096,
        "is_thinking": false,
        "temperature": 0.6
     },

    "translate": {
        "key": "sk-**",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_name": "Pro/deepseek-ai/DeepSeek-V3",
        "max_context_size": 131072,
        "max_tokens": 8096,
        "is_thinking": false,
        "temperature": 0.6
     }
}
"""

import concurrent.futures
import json
import os
import re
import threading
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from debugger import tracer
from llm_query import GPTContextProcessor, ModelSwitch


class TranslationWorkflow:
    def __init__(self, source_file: str, yaml_file: Optional[str] = None, output_file: str = None):
        self.source_file = Path(source_file)
        self.yaml_file = Path(yaml_file) if yaml_file else None
        self.output_file = Path(output_file) if output_file else self.source_file.with_suffix(".translated")
        self.source_lines = []
        self.paragraphs = []
        self.translation_cache = {}
        self.lock = threading.Lock()
        self.model_switch = ModelSwitch()
        self.log_buffer = []
        self.translation_log = []  # 新增日志记录翻译前后的内容

    def _test_gap_translation(self):
        """Test gap line translation and indentation preservation with actual translation"""
        test_cases = [
            {
                "original": "    def test():\n        pass\n",
                "expected": "    def test():\n        pass\n",
                "description": "Simple indentation preservation",
            },
            {
                "original": "    if x > 0:\n        return True\n    else:\n        return False\n",
                "expected": "    if x > 0:\n        return True\n    else:\n        return False\n",
                "description": "Multiple indentation levels",
            },
            {
                "original": "    # Comment\n    value = 42\n",
                "expected": "    # Comment\n    value = 42\n",
                "description": "Comments and code",
            },
            {
                "original": "    try:\n        something()\n    except:\n        handle_error()\n",
                "expected": "    try:\n        something()\n    except:\n        handle_error()\n",
                "description": "Complex control flow",
            },
        ]

        for case in test_cases:
            # Clear previous cache
            self.translation_cache.clear()

            # Split into lines and simulate source file
            self.source_lines = case["original"].splitlines(keepends=True)

            # Create a test paragraph covering all lines
            para = {
                "line_range": f"1-{len(self.source_lines)}",
                "type": "code",
                "summary": case["description"],
            }

            # Perform actual translation
            start, end, translated = self._translate_paragraph(para, "zh-en")

            # Build output and check results
            output_lines = self.build_output()
            output_text = "".join(output_lines)

            if output_text != case["expected"]:
                error_msg = (
                    f"Test failed for {case['description']}:\nExpected:\n{case['expected']}\nGot:\n{output_text}"
                )
                self._log(error_msg, "ERROR")
                raise AssertionError(error_msg)
            else:
                self._log(f"Test passed: {case['description']}")

        self._log("All gap translation tests completed successfully")

    def _log(self, message: str, level: str = "INFO"):
        """Log message with timestamp and level"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        self.log_buffer.append(log_entry)
        print(log_entry)

    def _split_large_file(self, content: str, chunk_size: int = 25 * 1024) -> List[Tuple[str, str]]:
        """Split large file content into chunks of approximately chunk_size bytes while preserving complete lines
        Returns a list of tuples (numbered_content, original_content, line_range)"""
        chunks = []
        current_chunk = []
        current_numbered_chunk = []
        current_size = 0
        line_number = 1

        for line in content.splitlines(keepends=True):
            line_size = len(line.encode("utf-8"))
            numbered_line = f"{line_number:4d} | {line}"

            # If adding this line would exceed chunk size and we already have content,
            # finalize the current chunk and start a new one
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

        # Add the last chunk if it has content
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
        self,
        chunk_index: int,
        numbered_chunk: str,
        original_chunk: str,
        endline: int,
        previous_chunk_tail: str,
        previous_numbered_tail: str,
    ) -> Tuple[List[Dict], str, str]:
        """Process a single chunk of the source file"""
        current_chunk = previous_chunk_tail + original_chunk
        current_numbered_chunk = previous_numbered_tail + numbered_chunk

        chunk_file = self.source_file.with_name(f"{self.source_file.stem}_chunk_{chunk_index}{self.source_file.suffix}")
        numbered_chunk_file = self.source_file.with_name(
            f"{self.source_file.stem}_numbered_chunk_{chunk_index}{self.source_file.suffix}"
        )

        with open(chunk_file, "w", encoding="utf-8") as f:
            f.write(current_chunk)
        with open(numbered_chunk_file, "w", encoding="utf-8") as f:
            f.write(current_numbered_chunk)

        try:
            self._log(f"Generating paragraph configuration for chunk {chunk_index} from {numbered_chunk_file}...")
            config = self._get_chunk_config(chunk_index, numbered_chunk_file)
            chunk_paragraphs = self._parse_chunk_config(config)

            if not chunk_paragraphs:
                return None

            # Handle tail content for next chunk
            if chunk_index < len(self.source_lines):
                last_para = chunk_paragraphs[-1]
                start, end = map(int, last_para["line_range"].split("-"))
                previous_chunk_tail = "".join(self.source_lines[start - 1 : endline])
                previous_numbered_tail = "".join(
                    f"{line_num:4d} | {line}"
                    for line_num, line in enumerate(self.source_lines[start - 1 : endline], start=start)
                )

            return chunk_paragraphs, previous_chunk_tail, previous_numbered_tail

        except Exception as e:
            self._log(f"Failed to process chunk {chunk_index}: {e}", "ERROR")
            raise
        finally:
            try:
                os.remove(chunk_file)
                os.remove(numbered_chunk_file)
            except OSError:
                pass

    def _generate_paragraph_config(self):
        """Generate paragraph configuration using LLM"""
        with open(self.source_file, "r", encoding="utf-8") as f:
            content = f.read()

        chunks = self._split_large_file(content)
        self._log(f"Split source file into {len(chunks)} chunks for processing")

        all_paragraphs = []
        previous_chunk_tail = ""
        previous_numbered_tail = ""

        for i, (numbered_chunk, original_chunk, endline) in enumerate(chunks, 1):
            processed_chunk = self._process_single_chunk(
                i,
                numbered_chunk,
                original_chunk,
                endline,
                previous_chunk_tail,
                previous_numbered_tail,
            )
            if processed_chunk:
                chunk_paragraphs, previous_chunk_tail, previous_numbered_tail = processed_chunk
                if i < len(chunks):
                    all_paragraphs.extend(chunk_paragraphs[:-1] if len(chunk_paragraphs) > 1 else [])
                else:
                    all_paragraphs.extend(chunk_paragraphs)

        self.paragraphs = all_paragraphs
        return True

    def _get_chunk_config(self, chunk_index: int, numbered_chunk_file: Path) -> Dict:
        """Get configuration for a single chunk from LLM"""
        prompt = f"@source-paragraph @{numbered_chunk_file}"
        text = GPTContextProcessor().process_text(prompt)
        response = self.model_switch.query("segment", text)
        config_text = response["choices"][0]["message"]["content"]

        try:
            return yaml.safe_load(config_text)
        except yaml.scanner.ScannerError:
            return self._extract_config_from_error(chunk_index, config_text)

    def load_files(self):
        """Load source file and optionally YAML config file"""
        try:
            with open(self.source_file, "r", encoding="utf-8") as f:
                self.source_lines = f.readlines()

                self._log(f"Loaded source file: {self.source_file} with {len(self.source_lines)} lines")

            if self.yaml_file:
                with open(self.yaml_file, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                    self.paragraphs = []
                    for para in config.get("paragraphs", []):
                        if isinstance(para, list) and len(para) >= 4:
                            para_dict = {
                                "type": para[0],
                                "line_range": para[1],
                                "line_count": para[2],
                                "summary": para[3],
                            }
                            self.paragraphs.append(para_dict)
                        elif isinstance(para, dict):
                            self.paragraphs.append(para)
                    self._log(f"Loaded YAML config: {self.yaml_file} with {len(self.paragraphs)} paragraphs")
            else:
                self._generate_paragraph_config()

        except FileNotFoundError as e:
            self._log(f"Error loading files: {e}", "ERROR")
            raise

    @tracer.trace(exclude_functions=["query", "_is_empty_content"], enable_var_trace=True)
    def validate_paragraphs(self):
        """Validate paragraph definitions"""
        covered_lines = set()
        for para in self.paragraphs:
            start, end = map(int, para["line_range"].split("-"))
            if start > end:
                raise ValueError(f"Invalid line range: {para['line_range']}")

            for line in range(start, end + 1):
                if line in covered_lines:
                    raise ValueError(f"Duplicate line coverage: {line}")
                covered_lines.add(line)
        self._log(f"Validated {len(self.paragraphs)} paragraphs covering {len(covered_lines)} lines")

    def _get_translation_prompt(self, paragraph_text: str, direction: str) -> str:
        """Get the appropriate translation prompt based on direction"""
        prompt_file = {
            "zh-en": "prompts/translate-zh-eng",
            "any-zh": "prompts/translate-any-zh",
        }.get(direction)

        if not prompt_file:
            raise ValueError(f"Unsupported translation direction: {direction}")

        prompt_path = Path(__file__).parent.parent / prompt_file
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()

        return f"{prompt}\n\n[input text start]{paragraph_text}[input text end]"

    def _is_empty_content(self, text: str) -> bool:
        """Check if text contains only whitespace, punctuation, or control characters"""
        if not text.strip():
            return True

        stripped = []
        for char in text:
            category = unicodedata.category(char)
            # Filter out whitespace (Z), punctuation (P), and control characters (Cc)
            if category.startswith(("Z", "P")) or category == "Cc":
                continue
            stripped.append(char)

        return not bool("".join(stripped))

    @tracer.trace(exclude_functions=["query", "_is_empty_content"], enable_var_trace=True)
    def _translate_paragraph(self, paragraph: Dict, direction: str) -> Tuple[int, int, str]:
        """Translate a single paragraph using the specified direction"""
        start, end = map(int, paragraph["line_range"].split("-"))
        paragraph_text = "".join(self.source_lines[start - 1 : end])

        # Skip translation if content is empty or only whitespace/punctuation
        if self._is_empty_content(paragraph_text):
            self._log(f"Skipping translation for empty/whitespace-only lines {start}-{end}")
            return start, end, paragraph_text

        # Check cache first
        with self.lock:
            if (start, end) in self.translation_cache:
                self._log(f"Using cached translation for lines {start}-{end}")
                return start, end, self.translation_cache[(start, end)]

        try:
            # Record original indentation for each line
            original_indents = []
            for line in self.source_lines[start - 1 : end]:
                indent = re.match(r"^(\s*)", line).group(1)
                original_indents.append(indent)

            prompt = self._get_translation_prompt(paragraph_text, direction)
            self._log(f"Translating lines {start}-{end} (direction: {direction})")
            response = self.model_switch.query("translate", prompt, verbose=False)
            translated_text = response["choices"][0]["message"]["content"]

            # Restore original indentation
            translated_lines = translated_text.split("\n")
            processed_lines = []
            for i, line in enumerate(translated_lines):
                if i < len(original_indents):
                    # Ensure translated line has same indentation as original
                    current_indent = re.match(r"^(\s*)", line).group(1)
                    if len(current_indent) < len(original_indents[i]):
                        line = original_indents[i] + line.lstrip()
                    elif len(current_indent) > len(original_indents[i]):
                        line = original_indents[i] + line[len(current_indent) :]
                processed_lines.append(line)

            translated_text = "\n".join(processed_lines)

            with self.lock:
                self.translation_cache[(start, end)] = translated_text
                # 记录翻译前后内容
                self.translation_log.append(
                    {
                        "line_range": f"{start}-{end}",
                        "original": paragraph_text,
                        "translated": translated_text,
                        "direction": direction,
                    }
                )

            return start, end, translated_text

        except Exception as e:
            self._log(f"Error translating lines {start}-{end}: {e}", "ERROR")
            return start, end, paragraph_text  # Return original on error

    def translate_parallel(self, direction: str = "zh-en", max_workers: int = 1):
        """Translate paragraphs in parallel"""
        self._log(f"Starting parallel translation with {max_workers} workers")
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self._translate_paragraph, para, direction) for para in self.paragraphs]

            for future in concurrent.futures.as_completed(futures):
                start, end, _ = future.result()
                self._log(f"Completed translation for lines {start}-{end}")

    def _is_blank_content(self, lines: List[str]) -> bool:
        """Check if given lines are blank (whitespace only)"""
        return all(line.strip() == "" for line in lines)

    def _find_gaps(self) -> List[Dict]:
        """Find gaps between paragraphs and create new paragraphs for non-blank content"""
        sorted_paragraphs = sorted(self.paragraphs, key=lambda p: int(p["line_range"].split("-")[0]))
        gaps = []
        prev_end = 0

        for para in sorted_paragraphs:
            start, end = map(int, para["line_range"].split("-"))
            if start > prev_end + 1:
                gap_lines = self.source_lines[prev_end : start - 1]
                if not self._is_blank_content(gap_lines):
                    # Record original indentation for each line
                    original_indents = []
                    for line in gap_lines:
                        indent = re.match(r"^(\s*)", line).group(1)
                        original_indents.append(indent)

                    gap_content = "".join(gap_lines)
                    gaps.append(
                        {
                            "line_range": f"{prev_end + 1}-{start - 1}",
                            "content": gap_content,
                            "original_indents": original_indents,
                        }
                    )
            prev_end = end

        # Check for gap after last paragraph
        if prev_end < len(self.source_lines):
            gap_lines = self.source_lines[prev_end:]
            if not self._is_blank_content(gap_lines):
                # Record original indentation for each line
                original_indents = []
                for line in gap_lines:
                    indent = re.match(r"^(\s*)", line).group(1)
                    original_indents.append(indent)

                gap_content = "".join(gap_lines)
                gaps.append(
                    {
                        "line_range": f"{prev_end + 1}-{len(self.source_lines)}",
                        "content": gap_content,
                        "original_indents": original_indents,
                    }
                )

        return gaps

    def build_output(self) -> List[str]:
        """Build the final output by combining translated and original content"""
        output_lines = []
        current_line = 1

        # Find and process gaps between paragraphs
        gap_paragraphs = self._find_gaps()
        if gap_paragraphs:
            self._log(f"Found {len(gap_paragraphs)} non-blank gaps to translate")
            for gap in gap_paragraphs:
                start, end = map(int, gap["line_range"].split("-"))
                self._log(f"Translating gap lines {start}-{end}")
                _, _, translated_text = self._translate_paragraph({"line_range": f"{start}-{end}"}, "zh-en")
                self.translation_cache[(start, end)] = translated_text

        # Sort translations by start line
        sorted_translations = sorted(self.translation_cache.items(), key=lambda x: x[0][0])

        for (start, end), translated_text in sorted_translations:
            # Add any untranslated lines before this segment
            while current_line < start:
                line_content = self.source_lines[current_line - 1]
                if line_content.strip() == "":  # Only keep blank lines
                    output_lines.append(line_content)
                current_line += 1

            # Add the translated lines
            translated_lines = translated_text.split("\n")
            for i, line in enumerate(translated_lines, start=start):
                if i <= end:  # Only replace lines within the original range
                    output_lines.append(line + "\n")
                else:
                    output_lines.append(line + "\n")
            current_line = end + 1

        # Add any remaining untranslated lines (only if blank)
        while current_line <= len(self.source_lines):
            line_content = self.source_lines[current_line - 1]
            if line_content.strip() == "":
                output_lines.append(line_content)
            current_line += 1

        return output_lines

    def save_output(self):
        """Save the translated output to file"""
        output_lines = self.build_output()
        with open(self.output_file, "w", encoding="utf-8") as f:
            f.writelines(output_lines)
        self._log(f"Saved translation to: {self.output_file}")

        # Save log to file
        log_file = self.output_file.with_suffix(".log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("\n".join(self.log_buffer))
        self._log(f"Saved log to: {self.output_file}")

        # Save translation log to file
        trans_log_file = self.output_file.with_suffix(".trans.log")
        with open(trans_log_file, "w", encoding="utf-8") as f:
            json.dump(self.translation_log, f, indent=2, ensure_ascii=False)
        self._log(f"Saved translation log to: {trans_log_file}")

    def _extract_config_from_error(self, chunk_index: int, config_text: str) -> Dict:
        """Handle config extraction when YAML parsing fails"""
        tmp_file = Path(f"tmp_config_{chunk_index}.txt")
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(config_text)
        try:
            t = GPTContextProcessor().process_text(f"@yaml-extract @{tmp_file}")
            extract_response = self.model_switch.query("segment", t, verbose=False)
            extracted_text = extract_response["choices"][0]["message"]["content"]
            return yaml.safe_load(extracted_text)
        finally:
            tmp_file.unlink()

    def _parse_chunk_config(self, config: Dict) -> List[Dict]:
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

    def run(self, direction: str = "zh-en", max_workers: int = 5):
        """Main execution flow"""
        try:
            # Test gap line translation and indentation
            # self._test_gap_translation()

            self.load_files()
            self.validate_paragraphs()
            self.translate_parallel(direction, max_workers)
            self.save_output()
        except Exception as e:
            self._log(f"Translation failed: {e}", "ERROR")
            raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parallel document translation workflow")
    parser.add_argument("source_file", help="Source file to translate")
    parser.add_argument(
        "yaml_file",
        nargs="?",
        default=None,
        help="Optional YAML file with paragraph definitions",
    )
    parser.add_argument("-o", "--output", help="Output file path (default: <source>.translated)")
    parser.add_argument(
        "-d",
        "--direction",
        default="zh-en",
        choices=["zh-en", "any-zh"],
        help="Translation direction (default: zh-en)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=5,
        help="Maximum parallel workers (default: 5)",
    )

    args = parser.parse_args()

    translator = TranslationWorkflow(args.source_file, args.yaml_file, args.output)
    translator.run(direction=args.direction, max_workers=args.workers)
