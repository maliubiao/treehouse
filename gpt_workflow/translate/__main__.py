#!/usr/bin/env python3
"""
Main entry point for translation workflow package
"""

import argparse

from gpt_workflow.translate.workflow import TranslationWorkflow


def main():
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
    parser.add_argument(
        "--inspect-translate",
        action="store_true",
        help="Display detailed translation mapping after completion",
    )

    args = parser.parse_args()

    translator = TranslationWorkflow(args.source_file, args.yaml_file, args.output)
    translator.run(direction=args.direction, max_workers=args.workers)

    if args.inspect_translate:
        translator.inspect_translation()


if __name__ == "__main__":
    main()
