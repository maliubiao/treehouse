#!/usr/bin/env python3
"""
需要在配置model.json中指定翻译用的大模型
比如{
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
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from colorama import Fore, Style

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

    def _log(self, message: str, level: str = "INFO"):
        """Log message with timestamp and level"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        self.log_buffer.append(log_entry)
        print(log_entry)

    def _generate_paragraph_config(self):
        """Generate paragraph configuration using LLM"""
        prompt = f"@source-paragraph @linenumber @{self.source_file}"
        text = GPTContextProcessor().process_text(prompt)
        try:
            self._log("Generating paragraph configuration using LLM...")
            response = self.model_switch.query("translate", text)
            config_text = response["choices"][0]["message"]["content"].strip()

            # Parse the response as YAML
            self.paragraphs = yaml.safe_load(config_text).get("paragraphs", [])
            self._log(f"Generated {len(self.paragraphs)} paragraph definitions")
            return True
        except Exception as e:
            self._log(f"Failed to generate paragraph config: {e}", "ERROR")
            raise

    def load_files(self):
        """Load source file and optionally YAML config file"""
        try:
            with open(self.source_file, "r", encoding="utf-8") as f:
                self.source_lines = f.readlines()
                self._log(f"Loaded source file: {self.source_file} with {len(self.source_lines)} lines")

            if self.yaml_file:
                with open(self.yaml_file, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                    self.paragraphs = config.get("paragraphs", [])
                    self._log(f"Loaded YAML config: {self.yaml_file} with {len(self.paragraphs)} paragraphs")
            else:
                self._generate_paragraph_config()

        except FileNotFoundError as e:
            self._log(f"Error loading files: {e}", "ERROR")
            raise

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
        prompt_file = {"zh-en": "prompts/translate-zh-eng", "any-zh": "prompts/translate-any-zh"}.get(direction)

        if not prompt_file:
            raise ValueError(f"Unsupported translation direction: {direction}")

        prompt_path = Path(__file__).parent.parent / prompt_file
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()

        return f"{prompt}\n\n{paragraph_text}"

    def _translate_paragraph(self, paragraph: Dict, direction: str) -> Tuple[int, int, str]:
        """Translate a single paragraph using the specified direction"""
        start, end = map(int, paragraph["line_range"].split("-"))
        paragraph_text = "".join(self.source_lines[start - 1 : end])

        try:
            prompt = self._get_translation_prompt(paragraph_text, direction)
            self._log(f"Translating lines {start}-{end} (direction: {direction})")
            response = self.model_switch.query("translate", prompt)
            translated_text = response["choices"][0]["message"]["content"].strip()

            with self.lock:
                self.translation_cache[(start, end)] = translated_text

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
                    gaps.append({"line_range": f"{prev_end+1}-{start-1}", "content": "".join(gap_lines)})
            prev_end = end

        # Check for gap after last paragraph
        if prev_end < len(self.source_lines):
            gap_lines = self.source_lines[prev_end:]
            if not self._is_blank_content(gap_lines):
                gaps.append({"line_range": f"{prev_end+1}-{len(self.source_lines)}", "content": "".join(gap_lines)})

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
        self._log(f"Saved log to: {log_file}")

    def run(self, direction: str = "zh-en", max_workers: int = 5):
        """Main execution flow"""
        try:
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
    parser.add_argument("yaml_file", nargs="?", default=None, help="Optional YAML file with paragraph definitions")
    parser.add_argument("-o", "--output", help="Output file path (default: <source>.translated)")
    parser.add_argument(
        "-d", "--direction", default="zh-en", choices=["zh-en", "any-zh"], help="Translation direction (default: zh-en)"
    )
    parser.add_argument("-w", "--workers", type=int, default=5, help="Maximum parallel workers (default: 5)")

    args = parser.parse_args()

    translator = TranslationWorkflow(args.source_file, args.yaml_file, args.output)
    translator.run(direction=args.direction, max_workers=args.workers)
