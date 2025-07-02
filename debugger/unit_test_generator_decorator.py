import atexit
import errno
import hashlib
import json
import multiprocessing
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from colorama import Fore, Style

from debugger.analyzable_tracer import analyzable_trace
from debugger.call_analyzer import CallAnalyzer


class _LockAcquisitionError(Exception):
    """Custom exception for when a process lock cannot be acquired."""

    pass


class _ProcessLock:
    """
    A simple cross-platform process lock using a file to ensure only one
    test generation process runs at a time. It includes stale lock detection
    by checking the PID written in the lock file.
    """

    def __init__(self, lock_file_name: str = "tllm_generator.lock"):
        self.lock_file = Path(tempfile.gettempdir()) / lock_file_name
        self.pid = os.getpid()
        self._is_locked = False

    def _is_pid_running(self, pid: int) -> bool:
        """Check if a process with the given PID is running."""
        if sys.platform == "win32":
            try:
                # On Windows, use 'tasklist' to check for the PID.
                # CREATE_NO_WINDOW flag prevents a console window from popping up.
                output = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,
                ).decode("utf-8", "ignore")
                return str(pid) in output
            except (subprocess.CalledProcessError, FileNotFoundError):
                return False
        else:  # POSIX systems
            try:
                # A signal of 0 tests for process existence without sending a signal.
                os.kill(pid, 0)
            except OSError as e:
                # ESRCH means the process does not exist.
                return e.errno != errno.ESRCH
            return True

    def acquire(self):
        """
        Attempt to acquire the lock. Raises _LockAcquisitionError on failure.
        Handles stale lock files left by crashed processes.
        """
        retry_count = 3
        for i in range(retry_count):
            try:
                # Atomically create and open the file in exclusive mode.
                with open(self.lock_file, "x", encoding="utf-8") as f:
                    f.write(str(self.pid))
                self._is_locked = True
                return  # Lock acquired
            except FileExistsError:
                try:
                    with open(self.lock_file, "r", encoding="utf-8") as f:
                        stale_pid_str = f.read().strip()

                    if not stale_pid_str.isdigit():
                        os.remove(self.lock_file)
                        continue  # Retry

                    stale_pid = int(stale_pid_str)
                    if not self._is_pid_running(stale_pid):
                        print(
                            f"{Fore.YELLOW}Detected stale lock from non-existent PID {stale_pid}. Cleaning up.{Style.RESET_ALL}"
                        )
                        os.remove(self.lock_file)
                        continue  # Retry
                    else:
                        raise _LockAcquisitionError(
                            f"Another instance (PID {stale_pid}) holds the lock: {self.lock_file}"
                        )
                except (IOError, ValueError):
                    time.sleep(0.2 * (i + 1))
                    continue
            except IOError as e:
                raise _LockAcquisitionError(f"I/O error while acquiring lock {self.lock_file}: {e}")
        raise _LockAcquisitionError(f"Failed to acquire lock {self.lock_file} after multiple retries.")

    def release(self):
        """Release the lock if it is held by the current process."""
        if self._is_locked and self.lock_file.exists():
            try:
                with open(self.lock_file, "r", encoding="utf-8") as f:
                    pid_in_file = int(f.read().strip())
                if pid_in_file == self.pid:
                    os.remove(self.lock_file)
                    self._is_locked = False
            except (IOError, ValueError, PermissionError) as e:
                print(
                    f"{Fore.YELLOW}Warning: Could not release lock file {self.lock_file}. Reason: {e}{Style.RESET_ALL}"
                )

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class UnitTestGeneratorDecorator:
    """
    为函数添加单元测试生成能力的装饰器类。

    该装饰器会自动追踪指定文件模式下所有函数的执行，并在程序退出时，
    通过一个跨进程锁确保只有一个实例会启动交互式界面，让用户选择为哪些函数生成单元测试。

    NOTE: 为了更方便使用，建议使用 `debugger.presets` 中提供的快捷装饰器，
    例如 `generate_for_file`, `generate_for_function`。
    """

    _registry = defaultdict(dict)
    _lock: Optional[_ProcessLock] = None

    def __init__(
        self,
        target_files: Optional[List[str]] = None,
        target_functions: Optional[List[str]] = None,
        output_dir: str = "generated_tests",
        report_dir: str = "call_reports",
        auto_confirm: bool = False,
        enable_var_trace: bool = True,
        model_name: str = "deepseek-r1",
        checker_model_name: str = "deepseek-v3",
        use_symbol_service: bool = True,
        trace_llm: bool = False,
        llm_trace_dir: str = "llm_traces",
        num_workers: int = 0,
    ):
        """
        初始化装饰器。

        Args:
            target_files: 需要追踪的文件模式列表 (e.g., ["project_name/**/*.py"])。
                          如果为 `[]`，则仅追踪被装饰函数所在的文件。
                          如果为 `None` (默认), 则使用 `["*.py"]` 作为默认值。
            target_functions: 预设要生成测试的函数列表。如果为 `[]`，则仅为被装饰的函数生成测试。
                              如果为 `None` (默认), 则进入交互模式或自动选择所有函数。
            output_dir: 生成的单元测试文件输出目录。
            report_dir: 调用分析报告存储目录。
            auto_confirm: 是否自动确认所有LLM建议和文件覆盖提示。
            enable_var_trace: 是否启用变量跟踪。
            model_name: 用于生成测试的核心语言模型名称。
            checker_model_name: 用于辅助任务（如命名、合并）的模型名称。
            use_symbol_service: 是否使用符号服务获取更精确的代码上下文。
            trace_llm: 是否记录LLM的提示和响应。
            llm_trace_dir: LLM跟踪日志的存储目录。
            num_workers: 并行生成单元测试的工作进程数。0或1表示顺序执行。
        """
        # 如果为 None，使用默认值。如果提供了列表(即使是空的)，则使用该列表。
        self.target_files = target_files if target_files is not None else ["*.py"]
        self.target_functions = target_functions
        self.output_dir = output_dir
        self.report_dir = report_dir
        self.auto_confirm = auto_confirm
        self.enable_var_trace = enable_var_trace
        self.model_name = model_name
        self.checker_model_name = checker_model_name
        self.use_symbol_service = use_symbol_service
        self.trace_llm = trace_llm
        self.llm_trace_dir = llm_trace_dir
        self.num_workers = num_workers if num_workers >= 0 else 0

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)

        if not hasattr(UnitTestGeneratorDecorator, "_atexit_registered"):
            atexit.register(self._generate_all_tests_on_exit)
            UnitTestGeneratorDecorator._atexit_registered = True

        if UnitTestGeneratorDecorator._lock is None:
            try:
                report_dir_abs = str(Path(self.report_dir).resolve())
                dir_hash = hashlib.md5(report_dir_abs.encode("utf-8")).hexdigest()[:8]
                lock_file_name = f"tllm_unittest_gen_{dir_hash}.lock"
                UnitTestGeneratorDecorator._lock = _ProcessLock(lock_file_name)
            except Exception as e:
                print(
                    f"{Fore.YELLOW}Warning: Could not create unique lock file name, using default. Error: {e}{Style.RESET_ALL}"
                )
                UnitTestGeneratorDecorator._lock = _ProcessLock()

    def __call__(self, func: Callable) -> Callable:
        """装饰器调用方法，设置并启动追踪。"""
        analyzer = CallAnalyzer()
        func_name = func.__name__
        decorated_func_file = func.__code__.co_filename

        # 核心逻辑：总是将被装饰函数所在的文件加入追踪列表
        final_target_files = list(set(self.target_files + [decorated_func_file]))

        # 核心逻辑：如果提供了 target_functions 列表(即使为空)，就自动把被装饰函数加进去
        final_target_functions = list(self.target_functions) if self.target_functions is not None else None
        if final_target_functions is not None and func_name not in final_target_functions:
            final_target_functions.append(func_name)

        traced_func = analyzable_trace(
            analyzer=analyzer,
            target_files=final_target_files,
            ignore_system_paths=True,
            enable_var_trace=self.enable_var_trace,
            report_name=f"{func_name}_trace_report.html",
        )(func)

        self._registry[func_name] = {
            "analyzer": analyzer,
            "original_func": func,
            "traced_func": traced_func,
            "config": {
                "output_dir": self.output_dir,
                "report_dir": self.report_dir,
                "auto_confirm": self.auto_confirm,
                "model_name": self.model_name,
                "checker_model_name": self.checker_model_name,
                "use_symbol_service": self.use_symbol_service,
                "trace_llm": self.trace_llm,
                "llm_trace_dir": self.llm_trace_dir,
                "num_workers": self.num_workers,
                "target_functions": final_target_functions,
            },
        }
        return traced_func

    @classmethod
    def _interactive_target_selection(cls, all_discovered_calls: Dict[str, Dict[str, Any]]) -> Optional[List[str]]:
        """提供一个交互式界面，让用户选择要为其生成测试的函数。"""
        if not all_discovered_calls:
            print(Fore.YELLOW + "No executed functions found in the trace report.")
            return []

        print(f"\n{Style.BRIGHT}Discovered functions with execution traces:{Style.RESET_ALL}")
        print("Please select which functions you want to generate unit tests for.")

        file_map, func_map = {}, {}
        file_counter, func_counter = 1, 1
        sorted_files = sorted(all_discovered_calls.keys())

        for filename in sorted_files:
            file_key = f"F{file_counter}"
            file_map[file_key] = filename
            print(f"\n{Fore.CYAN}[{file_key}]{Style.RESET_ALL} {filename}")

            sorted_funcs = sorted(all_discovered_calls[filename].keys())
            for func_name in sorted_funcs:
                func_key = str(func_counter)
                func_map[func_key] = func_name
                print(f"  [{func_key: >3}] {func_name}")
                func_counter += 1
            file_counter += 1

        prompt = (
            f"\n{Style.BRIGHT}Enter your choice:{Style.RESET_ALL}\n"
            f"  - Press {Style.BRIGHT}Enter{Style.RESET_ALL} or type {Style.BRIGHT}'A'{Style.RESET_ALL} for All discovered functions.\n"
            f"  - Type {Style.BRIGHT}'Q'{Style.RESET_ALL} to Quit without generating tests.\n"
            f"  - Enter numbers or file keys, separated by commas (e.g., {Style.BRIGHT}F1, 3, 5{Style.RESET_ALL}).\n"
            f"> "
        )

        try:
            user_input = input(prompt).strip().upper()
        except EOFError:
            print(Fore.YELLOW + "No input received, defaulting to selecting all functions.")
            user_input = "A"

        if user_input == "Q":
            return None
        if user_input == "A" or not user_input:
            return list({func for funcs in all_discovered_calls.values() for func in funcs.keys()})

        selected_targets = set()
        parts = [p.strip() for p in user_input.split(",")]
        for part in parts:
            if part in file_map:
                selected_targets.update(all_discovered_calls[file_map[part]].keys())
            elif part in func_map:
                selected_targets.add(func_map[part])
            elif part:
                print(Fore.YELLOW + f"Warning: Invalid selection '{part}' ignored.")
        return list(selected_targets)

    @classmethod
    def _generate_all_tests_on_exit(cls):
        """
        [REFACTORED] 程序退出时，获取进程锁并启动测试生成工作流。
        如果锁被其他进程持有，则优雅退出。
        """
        if not cls._registry:
            return

        if cls._lock is None:
            print(
                f"{Fore.YELLOW}Warning: Lock not initialized. Proceeding without single-instance guarantee.{Style.RESET_ALL}"
            )
            cls._do_generation()
            return

        try:
            with cls._lock:
                print(f"{Fore.CYAN}Acquired process lock. Starting test generation...{Style.RESET_ALL}")
                cls._do_generation()
        except _LockAcquisitionError as e:
            print(
                f"{Fore.YELLOW}Could not acquire lock: {e}. Another process is likely handling test generation.{Style.RESET_ALL}"
            )
        except Exception as e:
            import traceback

            print(
                f"{Fore.RED}An unexpected error occurred during the locked generation process: {e}\n{traceback.format_exc()}{Style.RESET_ALL}"
            )

    @classmethod
    def _do_generation(cls):
        """
        [NEW] 执行测试生成的核心逻辑，由持有锁的进程调用。
        """
        from gpt_workflow.unittest_generator import UnitTestGenerator

        print(f"\n{Fore.CYAN}{Style.BRIGHT}=== Starting Unit Test Generation Workflow ===")
        print(f"Detected {len(cls._registry)} decorated entry point(s)...{Style.RESET_ALL}")

        for entry_func_name, data in cls._registry.items():
            print(f"\n{Fore.YELLOW}Processing entry point: {entry_func_name}{Style.RESET_ALL}")
            analyzer: CallAnalyzer = data["analyzer"]
            config = data["config"]
            target_functions = config.get("target_functions")

            report_filename = f"{entry_func_name}_trace_report.json"
            report_path = str(Path(config["report_dir"]) / report_filename)
            analyzer.generate_report(report_path)

            final_test_cases = cls._deduplicate_and_load_calls(report_path)
            if not final_test_cases:
                print(f"{Fore.YELLOW}No unique function executions found for this entry point.{Style.RESET_ALL}")
                continue

            all_discovered_funcs = {func for funcs in final_test_cases.values() for func in funcs.keys()}
            if target_functions is not None:
                targets_for_generation = [f for f in target_functions if f in all_discovered_funcs]
            elif not config["auto_confirm"]:
                targets_for_generation = cls._interactive_target_selection(final_test_cases)
            else:
                targets_for_generation = list(all_discovered_funcs)

            if targets_for_generation is None:
                print(f"{Fore.BLUE}Test generation cancelled by user for '{entry_func_name}'.{Style.RESET_ALL}")
                continue
            if not targets_for_generation:
                print(f"{Fore.YELLOW}No functions selected for test generation.{Style.RESET_ALL}")
                continue

            print(
                f"\n{Fore.GREEN}Targets selected for generation: {Style.BRIGHT}{', '.join(targets_for_generation)}{Style.RESET_ALL}"
            )

            file_to_funcs_map = defaultdict(list)
            for filename, funcs in final_test_cases.items():
                for func_name in funcs:
                    if func_name in targets_for_generation:
                        file_to_funcs_map[filename].append(func_name)

            for filename, funcs_to_test in file_to_funcs_map.items():
                print(
                    f"\n{Fore.MAGENTA}--- Generating tests for file: '{filename}' ---\nFunctions: {', '.join(funcs_to_test)}{Style.RESET_ALL}"
                )
                try:
                    generator = UnitTestGenerator(
                        report_path=report_path,
                        model_name=config["model_name"],
                        checker_model_name=config["checker_model_name"],
                        trace_llm=config["trace_llm"],
                        llm_trace_dir=config["llm_trace_dir"],
                    )
                    if not generator.load_and_parse_report():
                        continue
                    generator.generate(
                        target_funcs=list(set(funcs_to_test)),
                        output_dir=config["output_dir"],
                        auto_confirm=config["auto_confirm"],
                        use_symbol_service=config["use_symbol_service"],
                        num_workers=config["num_workers"],
                    )
                except Exception as e:
                    import traceback

                    print(
                        f"{Fore.RED}Failed to generate tests for '{filename}': {e}\n{traceback.format_exc()}{Style.RESET_ALL}"
                    )

        print(f"\n{Fore.GREEN}{Style.BRIGHT}=== Unit Test Generation Workflow Finished ==={Style.RESET_ALL}")

    @staticmethod
    def _deduplicate_and_load_calls(report_path: str) -> Dict[str, Dict[str, List[Dict]]]:
        """读取报告，根据执行路径去重，并返回所有唯一的、可测试的函数调用。"""
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                call_trees = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"{Fore.RED}Error: Failed to read or parse report file {report_path}. Details: {e}{Style.RESET_ALL}")
            return {}

        final_test_cases = defaultdict(lambda: defaultdict(list))
        total_calls, unique_calls = 0, 0

        for filename, funcs in call_trees.items():
            for func_name, records in funcs.items():
                if re.match(r"^<.*?>$", func_name):
                    continue

                total_calls += len(records)
                seen_signatures = set()
                for record in records:
                    lines = frozenset(
                        evt["data"]["line_no"] for evt in record.get("events", []) if evt.get("type") == "line"
                    )
                    exc_type = record.get("exception", {}).get("type") if record.get("exception") else None
                    signature = (lines, exc_type)

                    if signature not in seen_signatures:
                        final_test_cases[filename][func_name].append(record)
                        seen_signatures.add(signature)
                        unique_calls += 1

        if total_calls > 0:
            print(
                f"{Fore.BLUE}Trace analysis: Found {unique_calls} unique execution paths from {total_calls} total function calls.{Style.RESET_ALL}"
            )
        return final_test_cases


generate_unit_tests = UnitTestGeneratorDecorator
