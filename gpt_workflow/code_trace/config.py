import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Set, Tuple

from llm_query import ModelSwitch, process_patch_response

verify_lock = threading.Lock()
repair_lock = threading.Lock()


class TraceConfig:
    def __init__(self, config_file: str):
        self.config_file = config_file
        self.source_files: List[str] = []
        self.verify_cmd: str = ""
        self.traced_files: Set[str] = set()
        self.failed_files: List[str] = []

        self.stop_event = threading.Event()
        self.skip_crc32: Set[str] = set()
        self.staged_files: Set[str] = set()
        self.git_root = self._get_git_root()
        self.load_config()
        self.load_staged_files()

    def _get_git_root(self) -> str:
        try:
            result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
            return os.getcwd()
        except Exception as e:
            print(f"Error getting git root: {str(e)}")
            return os.getcwd()

    def _to_absolute_path(self, path: str) -> str:
        if not os.path.isabs(path):
            path = os.path.join(self.git_root, path)
        return os.path.normpath(os.path.abspath(path))

    def load_config(self) -> None:
        try:
            import yaml

            with open(self.config_file, "r") as f:
                config = yaml.safe_load(f)
            source_patterns = config.get("source_files", [])
            for pattern in source_patterns:
                matched_files = glob.glob(pattern, recursive=True)
                self.source_files.extend([Path(f).resolve() for f in matched_files])
            self.verify_cmd = config.get("verify_cmd", "")
            self.skip_crc32 = set(config.get("skip_crc32", []))
        except Exception as e:
            print(f"Error loading config file: {str(e)}")
            raise

    def load_staged_files(self) -> None:
        try:
            result = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
            if result.returncode == 0:
                self.staged_files = set(
                    self._to_absolute_path(line.strip()) for line in result.stdout.splitlines() if line.strip()
                )
        except Exception as e:
            print(f"Error getting staged files: {str(e)}")

    def restore_file(self, file_path: str) -> None:
        try:
            subprocess.run(["git", "restore", file_path], check=True)
            print(f"Restored {file_path} using git restore")
        except subprocess.CalledProcessError as e:
            print(f"git restore failed: {str(e)}, trying git checkout")
            try:
                subprocess.run(["git", "checkout", "--", file_path], check=True)
                print(f"Checked out {file_path} to discard changes")
            except subprocess.CalledProcessError as e2:
                print(f"Failed to restore {file_path}: {str(e2)}")

    def save_failed_symbols(self, file_path: str, symbols: List[str], crc32_list: List[str]) -> None:
        if not symbols:
            return
        debug_dir = Path("trace_debug")
        debug_dir.mkdir(exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_file = debug_dir / f"failed_symbols_{file_path.replace('/', '_')}_{timestamp}.json"
        try:
            with open(debug_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "file_path": file_path,
                        "failed_symbols": symbols,
                        "crc32_list": crc32_list,
                        "timestamp": timestamp,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            print(f"Saved failed symbols with CRC32 to {debug_file}")
        except Exception as e:
            print(f"Error saving failed symbols: {str(e)}")

    def mark_as_traced(self, file_path: str) -> None:
        abs_path = self._to_absolute_path(file_path)
        self.traced_files.add(abs_path)

    def verify_trace(self) -> Tuple[bool, str]:
        if not self.verify_cmd:
            return (True, "")

        with verify_lock:
            try:
                print(f"Running verify command: {self.verify_cmd}")
                result = subprocess.run(self.verify_cmd, shell=True, check=False, capture_output=True, text=True)
                output = result.stdout + "\n" + result.stderr
                return (result.returncode == 0, output)
            except Exception as e:
                print(f"Error running verify command: {str(e)}")
                return (False, str(e))

    def _find_error_lines(self, output: str) -> List[str]:
        error_pattern = re.compile(r"([^ \n]+?):(\d+):\d+")
        error_lines = []
        bad_files = set()
        for match in error_pattern.finditer(output):
            file_path = os.path.abspath(match.group(1))
            if os.path.exists(file_path):
                bad_files.add(file_path)
            lineno = int(match.group(2))
            try:
                with open(file_path, "r") as f:
                    lines = f.readlines()
                    if 0 < lineno <= len(lines):
                        error_line = lines[lineno - 1].strip()
                        error_lines.append(error_line)
            except Exception as e:
                print(f"Error reading error line: {str(e)}")
        for file_path in bad_files:
            self.restore_file(file_path)
        return error_lines

    def _filter_problematic_responses(self, responses: List[str], error_lines: List[str]) -> List[str]:
        problematic = []
        for resp in responses:
            for line in error_lines:
                if line in resp:
                    problematic.append(resp)
                    break
        return problematic

    def _retry_with_filtered_responses(self, tracer, original_responses: List[str], error_lines: List[str]) -> bool:
        problematic = self._filter_problematic_responses(original_responses, error_lines)
        if not problematic:
            return False

        print(f"Found {len(problematic)} problematic response blocks, retrying...")
        filtered_responses = [r for r in original_responses if r not in problematic]

        # Restore original file before applying filtered patches
        self.restore_file(tracer.file_path)

        # Re-apply filtered responses
        process_patch_response(
            "\n".join(filtered_responses),
            tracer.symbol_detail_map,
            ignore_new_symbol=True,
            no_mix=True,
            confirm="y",
            change_log=False,
        )
        return True

    def trace_single_file(self, file_path: str) -> Tuple[bool, Optional[str]]:
        from .tracer import CodeTracer

        if self.stop_event.is_set():
            return (False, file_path)
        abs_path = self._to_absolute_path(file_path)
        if abs_path in self.staged_files:
            print(f"Skipping staged file: {abs_path}")
            return (True, None)

        print(f"Processing file: {abs_path}")
        tracer = CodeTracer(abs_path, stop_event=self.stop_event, skip_crc32=self.skip_crc32)
        tracer.process()
        processed_symbols = tracer.processed_symbols
        print("Processed symbols:", processed_symbols)
        original_responses = tracer.responses.copy()
        with repair_lock:
            print("Verifying trace...")
            _, verify_output = self.verify_trace()
            print(verify_output)
            error_lines = self._find_error_lines(verify_output)
            if error_lines:
                print("error lines", error_lines)
                self._retry_with_filtered_responses(tracer, original_responses, error_lines)
                _, retry_output = self.verify_trace()
                lines = self._find_error_lines(retry_output)
                if lines:
                    print("Retry failed with error lines", lines)
                    self.restore_file(abs_path)
                    crc_list = []
                    self.save_failed_symbols(abs_path, processed_symbols, crc_list)
                    self.failed_files.append(abs_path)
                    self.stop_event.set()
                    return (False, abs_path)
                self.mark_as_traced(abs_path)
                print("Retry succeeded, no error lines found")
                return (True, None)
            else:
                self.mark_as_traced(abs_path)
                return (True, None)

    def trace_all_files(self, parallel: bool = True) -> Tuple[bool, Optional[str]]:
        remaining_files = []
        for file in self.source_files:
            abs_path = Path(file).resolve()
            if abs_path not in self.staged_files and os.path.exists(abs_path):
                remaining_files.append(abs_path)
            else:
                print(f"File {abs_path} is staged or does not exist, skipping")

        if not remaining_files:
            print("All files have been processed successfully or do not exist.")
            return (True, None)

        print(f"Found {len(remaining_files)} files to process")

        if not parallel:
            for file in remaining_files:
                if self.stop_event.is_set():
                    break
                success, failed_file = self.trace_single_file(file)
                if not success:
                    return (False, failed_file)
            return (True, None)
        for file in remaining_files:
            self.trace_single_file(file)
        return (True, None)
        print(f"Processing {len(remaining_files)} files in parallel")
        with ThreadPoolExecutor(max_workers=32) as pool:
            futures = {pool.submit(self.trace_single_file, file): file for file in remaining_files}

            for future in as_completed(futures):
                success, failed_file = future.result()
                if not success:
                    self.stop_event.set()
                    for f in futures:
                        f.cancel()
                    return (False, failed_file)

        return (True, None)
