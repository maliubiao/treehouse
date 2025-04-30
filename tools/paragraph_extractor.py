#!/usr/bin/env python3
import sys
from pathlib import Path

import yaml


class ParagraphExtractor:
    def __init__(self, source_file: str, yaml_file: str):
        self.source_file = Path(source_file)
        self.yaml_file = Path(yaml_file)
        self.source_lines = []
        self.paragraphs = []

    def load_files(self):
        """Load both source file and YAML config file"""
        try:
            with open(self.source_file, "r", encoding="utf-8") as f:
                self.source_lines = f.readlines()

            with open(self.yaml_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                self.paragraphs = config.get("paragraphs", [])

        except FileNotFoundError as e:
            print(f"Error loading files: {e}")
            sys.exit(1)

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

        total_lines = len(self.source_lines)
        coverage = len(covered_lines) / total_lines * 100
        if coverage != 100:
            print(f"Warning: Line coverage is {coverage:.1f}%")

    def extract_paragraphs(self):
        """Extract and display paragraphs with line numbers"""
        for para in self.paragraphs:
            start, end = map(int, para["line_range"].split("-"))
            print(f"\n=== Paragraph: {para['description']} ===")
            print(f"Type: {para['type']}, Lines: {para['line_range']}\n")

            for i in range(start - 1, end):
                if i < len(self.source_lines):
                    line_num = i + 1
                    content = self.source_lines[i].rstrip()
                    print(f"{line_num:4d} | {content}")

    def run(self):
        """Main execution flow"""
        self.load_files()
        try:
            self.validate_paragraphs()
            self.extract_paragraphs()
        except ValueError as e:
            print(f"Validation error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: paragraph_extractor.py <source_file> <yaml_file>")
        sys.exit(1)

    extractor = ParagraphExtractor(sys.argv[1], sys.argv[2])
    extractor.run()
