#!/usr/bin/env python3
"""
Main translation workflow implementation
"""

import json
import threading
from pathlib import Path
from typing import List, Optional

from llm_query import ModelSwitch

from .config import load_config, validate_paragraphs
from .logging import TranslationLogger
from .output import build_output, save_output
from .translation import get_translation_prompt, translate_parallel


class TranslationWorkflow:
    def __init__(self, source_file: str, yaml_file: Optional[str] = None, output_file: str = None):
        self.source_file = Path(source_file)
        self.yaml_file = Path(yaml_file) if yaml_file else None
        self.output_file = Path(output_file) if output_file else self.source_file.with_suffix(".translated")
        self.source_lines = []
        self.paragraphs = []
        self.logger = TranslationLogger()
        self.translation_cache = {}
        self.translation_log = []
        self.lock = threading.Lock()
        self.model_switch = ModelSwitch()
        self.model_switch.select("translate")

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
            self.translation_cache.clear()
            self.source_lines = case["original"].splitlines(keepends=True)
            para = {
                "line_range": f"1-{len(self.source_lines)}",
                "type": "code",
                "summary": case["description"],
            }

            # Perform actual translation
            prompt = get_translation_prompt(case["original"], "zh-en")
            response = self.model_switch.query("translate", prompt, verbose=False)
            translated_text = response["choices"][0]["message"]["content"]

            if "[translation start]" in translated_text:
                translated_text = translated_text.split("[translation start]")[1].split("[translation end]")[0].strip()

            self.translation_cache[(1, len(self.source_lines))] = translated_text

            output_lines = build_output(self.translation_cache, self.source_lines, "zh-en", self.logger)
            output_text = "".join(output_lines)

            if output_text != case["expected"]:
                error_msg = (
                    f"Test failed for {case['description']}:\nExpected:\n{case['expected']}\nGot:\n{output_text}"
                )
                self.logger.error(error_msg)
                raise AssertionError(error_msg)
            else:
                self.logger.info(f"Test passed: {case['description']}")

        self.logger.info("All gap translation tests completed successfully")

    def load_files(self):
        """Load source file and optionally YAML config file"""
        self.source_lines, self.paragraphs = load_config(self.source_file, self.yaml_file, self.logger)

    def validate_paragraphs(self):
        """Validate paragraph definitions"""
        validate_paragraphs(self.paragraphs, self.source_lines, self.logger)

    def translate_parallel(self, direction: str = "zh-en", max_workers: int = 1):
        """Translate paragraphs in parallel"""
        self.translation_cache, self.translation_log = translate_parallel(
            self.paragraphs, self.source_lines, direction, max_workers, self.logger, self.model_switch
        )

    def build_output(self, direction: str) -> List[str]:
        """Build the final output by combining translated and original content"""
        output_lines = build_output(self.translation_cache, self.source_lines, direction, self.logger)

        # Ensure trailing newline matches original
        if self.source_lines and not self.source_lines[-1].endswith("\n"):
            if output_lines and output_lines[-1].endswith("\n"):
                output_lines[-1] = output_lines[-1].rstrip("\n")

        return output_lines

    def save_output(self, direction: str):
        """Save the translated output to file"""
        output_lines = self.build_output(direction)
        save_output(output_lines, self.output_file, self.logger)

        # Save log to file
        log_file = self.output_file.with_suffix(".log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("\n".join(self.logger.log_buffer))
        self.logger.info(f"Saved log to: {log_file}")

        # Save translation log to file
        trans_log_file = self.output_file.with_suffix(".trans.log")
        with open(trans_log_file, "w", encoding="utf-8") as f:
            json.dump(self.translation_log, f, indent=2, ensure_ascii=False)
        self.logger.info(f"Saved translation log to: {trans_log_file}")

    def inspect_translation(self):
        """Display translation mapping with colored output"""
        self.logger.inspect_translation()

    def run(self, direction: str = "zh-en", max_workers: int = 5):
        """Main execution flow"""
        try:
            self.load_files()
            self.validate_paragraphs()
            self.translate_parallel(direction, max_workers)
            self.save_output(direction)
        except Exception as e:
            self.logger.error(f"Translation failed: {e}")
            raise
