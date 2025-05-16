#!/usr/bin/env python3
"""
Logging and inspection functionality
"""

from datetime import datetime
from typing import Dict, List

from colorama import Fore, Style


class TranslationLogger:
    def __init__(self):
        self.log_buffer = []
        self.translation_log = []

    def info(self, message: str):
        self._log(message, "INFO")

    def warning(self, message: str):
        self._log(message, "WARNING")

    def error(self, message: str):
        self._log(message, "ERROR")

    def success(self, message: str):
        self._log(message, "SUCCESS")

    def _log(self, message: str, level: str = "INFO"):
        """Log message with timestamp and level"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color_map = {
            "INFO": Fore.BLUE,
            "WARNING": Fore.YELLOW,
            "ERROR": Fore.RED,
            "SUCCESS": Fore.GREEN,
        }
        color = color_map.get(level, Fore.WHITE)
        log_entry = f"{color}[{timestamp}] [{level}] {message}{Style.RESET_ALL}"
        self.log_buffer.append(log_entry)
        print(log_entry)

    def add_translation_log(self, line_range: str, original: str, translated: str, direction: str, prompt: str):
        """Add a translation log entry"""
        self.translation_log.append(
            {
                "line_range": line_range,
                "original": original,
                "translated": translated,
                "direction": direction,
                "prompt": prompt,
            }
        )

    def inspect_translation(self):
        """Display translation mapping with colored output"""
        if not self.translation_log:
            self.warning("No translation log available")
            return

        self.success("\nTranslation Inspection Report:")
        self.success("=" * 50)

        for entry in self.translation_log:
            self.info(f"\nLines: {entry['line_range']} (Direction: {entry['direction']})")
            print(f"{Fore.YELLOW}Original:{Style.RESET_ALL}")
            print(Fore.RED + entry["original"] + Style.RESET_ALL)
            print(f"\n{Fore.GREEN}Translated:{Style.RESET_ALL}")
            print(Fore.BLUE + entry["translated"] + Style.RESET_ALL)
            print(f"\n{Fore.CYAN}Prompt used:{Style.RESET_ALL}")
            print(Fore.MAGENTA + entry["prompt"] + Style.RESET_ALL)
            print("-" * 50)
