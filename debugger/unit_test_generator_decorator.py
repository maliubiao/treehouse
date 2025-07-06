import atexit
import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from colorama import Fore, Style

from debugger.analyzable_tracer import AnalyzableTraceLogic, analyzable_trace
from debugger.call_analyzer import CallAnalyzer


class _LockAcquisitionError(Exception):
    """Custom exception for when a process lock cannot be acquired."""


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
        # POSIX systems
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
            except FileExistsError as exc:
                try:
                    with open(self.lock_file, "r", encoding="utf-8") as f:
                        stale_pid_str = f.read().strip()

                    if not stale_pid_str.isdigit():
                        os.remove(self.lock_file)
                        continue  # Corrupt lock file, retry

                    stale_pid = int(stale_pid_str)
                    if not self._is_pid_running(stale_pid):
                        print(
                            f"{Fore.YELLOW}Detected stale lock from non-existent PID "
                            f"{stale_pid}. Cleaning up.{Style.RESET_ALL}"
                        )
                        os.remove(self.lock_file)
                        continue  # Stale lock removed, retry

                    # If we reach here, the lock is held by another running process.
                    raise _LockAcquisitionError(
                        f"Another instance (PID {stale_pid}) holds the lock: {self.lock_file}"
                    ) from exc
                except (IOError, ValueError):
                    time.sleep(0.2 * (i + 1))
                    continue
            except IOError as e:
                raise _LockAcquisitionError(f"I/O error while acquiring lock {self.lock_file}: {e}") from e
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
    _atexit_registered = False
    default_source_base_dir = Path.cwd()

    def __init__(
        self,
        target_files: Optional[List[str]] = None,
        target_functions: Optional[List[str]] = None,
        output_dir: str = "generated_tests",
        report_dir: str = "call_reports",
        auto_confirm: bool = False,
        enable_var_trace: bool = True,
        verbose_trace: bool = False,
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
            verbose_trace: 是否在运行时实时打印详细的、带缩进的函数调用/返回日志。
                           启用此项还会创建一个包含所有原始事件的 `raw_trace_events.log` 文件用于调试。
            model_name: 用于生成测试的核心语言模型名称。
            checker_model_name: 用于辅助任务（如命名、合并）的模型名称。
            use_symbol_service: 是否使用符号服务获取更精确的代码上下文。
            trace_llm: 是否记录LLM的提示和响应。
            llm_trace_dir: LLM跟踪日志的存储目录。
            num_workers: 并行生成单元测试的工作进程数。0或1表示顺序执行。
        """
        self.target_files = target_files if target_files is not None else ["*.py"]
        self.target_functions = target_functions
        self.output_dir = output_dir
        self.report_dir = report_dir
        self.auto_confirm = auto_confirm
        self.enable_var_trace = enable_var_trace
        self.verbose_trace = verbose_trace
        self.model_name = model_name
        self.checker_model_name = checker_model_name
        self.use_symbol_service = use_symbol_service
        self.trace_llm = trace_llm
        self.llm_trace_dir = llm_trace_dir
        self.num_workers = num_workers if num_workers >= 0 else 0
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)

        if not UnitTestGeneratorDecorator._atexit_registered:
            atexit.register(self._generate_all_tests_on_exit)
            UnitTestGeneratorDecorator._atexit_registered = True

        if UnitTestGeneratorDecorator._lock is None:
            try:
                report_dir_abs = str(Path(self.report_dir).resolve())
                dir_hash = hashlib.md5(report_dir_abs.encode("utf-8")).hexdigest()[:8]
                lock_file_name = f"tllm_unittest_gen_{dir_hash}.lock"
                UnitTestGeneratorDecorator._lock = _ProcessLock(lock_file_name)
            except OSError as e:
                print(
                    f"{Fore.YELLOW}Warning: Could not create unique lock file name, "
                    f"using default. Error: {e}{Style.RESET_ALL}"
                )
                UnitTestGeneratorDecorator._lock = _ProcessLock()

    def __call__(self, func: Callable) -> Callable:
        """装饰器调用方法，设置并启动追踪。"""
        analyzer = CallAnalyzer(verbose=self.verbose_trace)
        # Use qualname for better uniqueness, e.g., "MyClass.my_method"
        func_name = func.__qualname__
        decorated_func_file = str(Path(func.__code__.co_filename).resolve())

        final_target_files = list(set(self.target_files + [decorated_func_file]))

        final_target_functions = list(self.target_functions) if self.target_functions is not None else None
        if final_target_functions is not None and func_name not in final_target_functions:
            final_target_functions.append(func_name)

        # 统一计算导入映射文件的路径，并将其存储在配置中
        import_map_file_path = self.default_source_base_dir / "logs/import_map.json"

        # 将所有配置打包，传递给 analyzable_trace
        config_for_tracer = {
            "analyzer": analyzer,
            "target_files": final_target_files,
            "ignore_system_paths": True,
            "enable_var_trace": self.enable_var_trace,
            "source_base_dir": self.default_source_base_dir,
            "import_map_file": import_map_file_path,  # 传递统一的路径
        }
        traced_func = analyzable_trace(**config_for_tracer)(func)

        # 存储与此装饰器实例相关的配置和分析器
        unique_key = f"{decorated_func_file}::{func_name}"
        self._registry[unique_key] = {
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
                "import_map_file": import_map_file_path,  # 在配置中也存储
            },
        }
        return traced_func

    @classmethod
    def _display_interactive_menu(cls, all_discovered_calls: Dict[str, Dict[str, Any]]) -> Tuple[Dict, Dict]:
        """Prints the interactive menu for function selection and returns mapping dicts."""
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
                func_map[func_key] = (filename, func_name)
                print(f"  [{func_key: >3}] {func_name}")
                func_counter += 1
            file_counter += 1
        return file_map, func_map

    @classmethod
    def _parse_interactive_selection(
        cls, user_input: str, file_map: Dict, func_map: Dict, all_discovered_calls: Dict
    ) -> Optional[Dict[str, List[str]]]:
        """Parses user input from the interactive menu and returns selected targets."""
        if user_input == "Q":
            return None

        if user_input == "A" or not user_input:
            return {filename: list(funcs.keys()) for filename, funcs in all_discovered_calls.items()}

        selected_targets_by_file = defaultdict(list)
        parts = [p.strip() for p in user_input.split(",")]
        for part in parts:
            if part.startswith("F") and part in file_map:
                filename = file_map[part]
                selected_targets_by_file[filename].extend(all_discovered_calls[filename].keys())
            elif part.isdigit() and part in func_map:
                filename, func_name = func_map[part]
                selected_targets_by_file[filename].append(func_name)
            elif part:
                print(Fore.YELLOW + f"Warning: Invalid selection '{part}' ignored.")

        # Remove duplicates
        for filename, funcs in selected_targets_by_file.items():
            selected_targets_by_file[filename] = sorted(list(set(funcs)))

        return dict(selected_targets_by_file)

    @classmethod
    def _interactive_target_selection(
        cls, all_discovered_calls: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, List[str]]]:
        """
        Provides an interactive UI for function selection.
        Returns a dictionary mapping filenames to a list of selected function names.
        """
        if not all_discovered_calls:
            print(Fore.YELLOW + "No executed functions found in the trace report.")
            return {}

        file_map, func_map = cls._display_interactive_menu(all_discovered_calls)

        prompt = (
            f"\n{Style.BRIGHT}Enter your choice:{Style.RESET_ALL}\n"
            f"  - Press {Style.BRIGHT}Enter{Style.RESET_ALL} or type {Style.BRIGHT}'A'{Style.RESET_ALL} "
            "for All discovered functions.\n"
            f"  - Type {Style.BRIGHT}'Q'{Style.RESET_ALL} to Quit without generating tests.\n"
            f"  - Enter numbers or file keys, separated by commas (e.g., {Style.BRIGHT}F1, 3, 5{Style.RESET_ALL}).\n"
            "> "
        )

        try:
            user_input = input(prompt).strip().upper()
        except EOFError:
            print(Fore.YELLOW + "\nNo input received, quitting test generation.")
            user_input = "Q"

        return cls._parse_interactive_selection(user_input, file_map, func_map, all_discovered_calls)

    @classmethod
    def _generate_all_tests_on_exit(cls):
        """
        At program exit, acquires a lock, starts the test generation workflow,
        and cleans up resources.
        """
        if not cls._registry:
            return

        try:
            # The lock is initialized in __init__, so it might not exist if no
            # decorator was ever instantiated.
            if not cls._lock:
                print(
                    f"{Fore.YELLOW}Warning: Lock not initialized. "
                    f"Proceeding without single-instance guarantee.{Style.RESET_ALL}"
                )
                cls._do_generation()
                return

            # If lock exists, use it.
            try:
                with cls._lock:
                    print(f"{Fore.CYAN}Acquired process lock. Starting test generation...{Style.RESET_ALL}")
                    cls._do_generation()
            except _LockAcquisitionError as e:
                print(
                    f"{Fore.YELLOW}Could not acquire lock: {e}. "
                    f"Another process is likely handling test generation.{Style.RESET_ALL}"
                )
            except Exception:
                # This top-level catch is a safety net for the entire generation
                # workflow, which can have many failure points.
                print(f"{Fore.RED}An unexpected error occurred during the locked generation process:{Style.RESET_ALL}")
                traceback.print_exc()
        finally:
            # Ensure tracer resources like the raw event log file are closed.
            AnalyzableTraceLogic.close_event_log()

    @classmethod
    def _merge_traces_and_configs(cls) -> Optional[Tuple[Dict, Dict, List[str], bool]]:
        """Merges all trace data and configurations from the registry."""
        if not cls._registry:
            return None

        master_call_tree = defaultdict(lambda: defaultdict(list))
        all_presets = set()
        is_any_preset_defined = False
        # Use the config from the first registered decorator as the base.
        base_config = next(iter(cls._registry.values()))["config"]

        for data in cls._registry.values():
            analyzer: CallAnalyzer = data["analyzer"]
            # It's crucial to finalize each analyzer to process any remaining events in its stack.
            analyzer.finalize()
            for filename, funcs in analyzer.call_trees.items():
                for func_name, records in funcs.items():
                    master_call_tree[filename][func_name].extend(records)

            preset = data["config"].get("target_functions")
            if preset is not None:
                is_any_preset_defined = True
                all_presets.update(preset)

        return master_call_tree, base_config, sorted(list(all_presets)), is_any_preset_defined

    @classmethod
    def _determine_targets(
        cls, all_discovered_calls, config, all_presets, is_any_preset_defined
    ) -> Tuple[Dict[str, List[str]], List[str]]:
        """Determines the final set of functions to generate tests for."""
        targets_by_file: Dict[str, List[str]] = {}
        final_target_funcs: List[str] = []

        if is_any_preset_defined:
            all_discovered_funcs = {func for funcs in all_discovered_calls.values() for func in funcs.keys()}
            final_target_funcs = [f for f in all_presets if f in all_discovered_funcs]
        elif not config.get("auto_confirm", False):
            selected_targets = cls._interactive_target_selection(all_discovered_calls)
            if selected_targets:
                targets_by_file = selected_targets
        else:  # auto-confirm without presets
            targets_by_file = {filename: list(funcs.keys()) for filename, funcs in all_discovered_calls.items()}

        return targets_by_file, final_target_funcs

    @classmethod
    def _discover_all_calls_from_tree(cls, call_tree: Dict) -> Dict[str, Dict[str, List[Dict]]]:
        """
        [NEW] Traverses a nested call tree and creates a flat dictionary of all function
        executions, grouped by their file and function name. This ensures all executed
        functions are discovered, not just the top-level ones.
        """
        discovered = defaultdict(lambda: defaultdict(list))

        def _visitor(record: Dict):
            # Use original_filename for accuracy as it points to the source file.
            filename = record.get("original_filename")
            func_name = record.get("func_name")

            if filename and func_name:
                discovered[filename][func_name].append(record)

            # Recurse into sub-calls.
            for event in record.get("events", []):
                if event.get("type") == "call" and isinstance(event.get("data"), dict):
                    _visitor(event["data"])

        # Iterate over each top-level entry point in the original tree.
        for funcs_in_file in call_tree.values():
            for records in funcs_in_file.values():
                for top_level_record in records:
                    _visitor(top_level_record)

        # Convert defaultdicts to regular dicts for a cleaner structure.
        return {fname: dict(funcs) for fname, funcs in discovered.items()}

    @classmethod
    def _save_unified_report(cls, data_to_save: Dict, config: Dict) -> Optional[str]:
        """Saves the unified trace data to a report file and returns the path."""
        report_path = str(Path(config["report_dir"]) / "unified_trace_report.json")
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False, default=str)
            return report_path
        except (IOError, TypeError) as e:
            print(f"{Fore.RED}Error writing unified report: {e}{Style.RESET_ALL}")
            return None

    @classmethod
    def _check_for_multithreading(cls, all_discovered_calls: Dict):
        """Checks for and warns about traces from multiple threads."""
        all_thread_ids = {
            record["thread_id"]
            for funcs in all_discovered_calls.values()
            for records in funcs.values()
            for record in records
            if "thread_id" in record
        }
        if len(all_thread_ids) > 1:
            print(
                f"{Fore.YELLOW}Warning: Traces from multiple threads {sorted(list(all_thread_ids))} were detected. "
                f"The generator will attempt to create tests based on all traced executions.{Style.RESET_ALL}"
            )

    @classmethod
    def _verify_and_print_traces(cls, all_discovered_calls: Dict, targets_by_file: Dict, final_target_funcs: List[str]):
        """Prints the final, processed trace data for user verification."""
        try:
            print(f"\n{Fore.MAGENTA}{Style.BRIGHT}--- Verifying Captured Traces ---{Style.RESET_ALL}")
            print(
                f"{Fore.MAGENTA}(This shows the final, processed trace data used for test generation){Style.RESET_ALL}"
            )

            target_funcs = final_target_funcs or [func for funcs in targets_by_file.values() for func in funcs]
            if not target_funcs:
                print(f"{Fore.YELLOW}No target functions were selected for verification.{Style.RESET_ALL}")
                return

            func_to_file_map = {func: filename for filename, funcs in all_discovered_calls.items() for func in funcs}

            for func_to_print in sorted(target_funcs):
                filename = func_to_file_map.get(func_to_print)
                if filename and func_to_print in all_discovered_calls.get(filename, {}):
                    records = all_discovered_calls[filename][func_to_print]
                    print(f"\n{Fore.YELLOW}Trace for: {filename}::{func_to_print}{Style.RESET_ALL}")
                    for i, record in enumerate(records):
                        print(f"{Fore.CYAN}--- Execution Record {i + 1}/{len(records)} ---{Style.RESET_ALL}")
                        analyzer_for_printing = CallAnalyzer()
                        print(analyzer_for_printing.pretty_print_call(record))
                else:
                    print(f"{Fore.YELLOW}Warning: Could not find trace for '{func_to_print}'.{Style.RESET_ALL}")

        except Exception as e:
            # This is a non-critical debug block; prevent it from crashing the generator.
            print(f"{Fore.RED}An error occurred during trace verification: {e}{Style.RESET_ALL}")
            traceback.print_exc()
        finally:
            print(f"\n{Fore.MAGENTA}{Style.BRIGHT}--- Trace Verification Finished ---{Style.RESET_ALL}")

    @classmethod
    def _save_unified_import_map(cls, config: Dict):
        """Saves the unified import map before generation."""
        import_map_path = config.get("import_map_file")
        if not import_map_path:
            return

        try:
            print(f"{Fore.CYAN}Saving unified import map to {import_map_path}...{Style.RESET_ALL}")
            AnalyzableTraceLogic.save_import_map(import_map_path)
        except IOError as e:
            print(f"{Fore.RED}Failed to save import map: {e}{Style.RESET_ALL}")
            # We can continue without it, but tests may have missing imports.

    @classmethod
    def _initialize_generator(cls, config: Dict, report_path: str):
        """Initializes and returns the UnitTestGenerator instance."""
        # pylint: disable=import-outside-toplevel
        from gpt_workflow.unittester import UnitTestGenerator

        try:
            generator = UnitTestGenerator(
                report_path=report_path,
                model_name=config["model_name"],
                checker_model_name=config["checker_model_name"],
                trace_llm=config["trace_llm"],
                llm_trace_dir=config["llm_trace_dir"],
                project_root=cls.default_source_base_dir,
                import_map_path=config.get("import_map_file"),
            )
            # No need to call load_and_parse_report here, it will be called by generator.generate()
            return generator
        except (ImportError, FileNotFoundError, json.JSONDecodeError) as e:
            print(f"{Fore.RED}Failed to initialize UnitTestGenerator: {e}{Style.RESET_ALL}")
            traceback.print_exc()
            return None

    @classmethod
    def _run_generation_tasks(cls, generator, config: Dict, targets_by_file: Dict, final_target_funcs: List[str]):
        """Executes the generation tasks for the selected targets."""
        if targets_by_file:  # Interactive or auto-confirm modes
            print(f"\n{Fore.GREEN}Processing targets for {len(targets_by_file)} file(s).{Style.RESET_ALL}")
            for filename, funcs in targets_by_file.items():
                print(f"\n{Fore.CYAN}--- Generating tests for file: {filename} ---{Style.RESET_ALL}")
                print(f"    Functions: {Style.BRIGHT}{', '.join(sorted(funcs))}{Style.RESET_ALL}")
                generator.generate(
                    target_funcs=funcs,
                    output_dir=config["output_dir"],
                    auto_confirm=config["auto_confirm"],
                    use_symbol_service=config["use_symbol_service"],
                    num_workers=config["num_workers"],
                    target_file=filename,
                )
        elif final_target_funcs:  # Preset mode
            print(
                f"\n{Fore.GREEN}Processing preset targets: "
                f"{Style.BRIGHT}{', '.join(sorted(final_target_funcs))}{Style.RESET_ALL}"
            )
            generator.generate(
                target_funcs=final_target_funcs,
                output_dir=config["output_dir"],
                auto_confirm=config["auto_confirm"],
                use_symbol_service=config["use_symbol_service"],
                num_workers=config["num_workers"],
                target_file=None,  # No specific file context for global presets
            )

    @classmethod
    def _do_generation(cls):
        """Executes the unified test generation workflow, called by the lock-holding process."""
        print(f"\n{Fore.CYAN}{Style.BRIGHT}=== Starting Unified Unit Test Generation Workflow ==={Style.RESET_ALL}")

        merged_data = cls._merge_traces_and_configs()
        if not merged_data:
            return
        master_call_tree, config, all_presets, is_preset_defined = merged_data

        # [MODIFIED] First, discover all calls and flatten the tree.
        all_discovered_calls = cls._discover_all_calls_from_tree(master_call_tree)

        # Filter out special function names (e.g., <module>) which are not valid test targets.
        all_discovered_calls = {
            filename: {
                func_name: records
                for func_name, records in funcs.items()
                if not (func_name.startswith("<") and func_name.endswith(">"))
            }
            for filename, funcs in all_discovered_calls.items()
        }
        # Subsequently, filter out any files that have no functions left after filtering.
        all_discovered_calls = {filename: funcs for filename, funcs in all_discovered_calls.items() if funcs}

        # [MODIFIED] Save the FLATTENED, processed data to the report. This is the key change.
        report_path = cls._save_unified_report(all_discovered_calls, config)
        if not report_path:
            return

        if not all_discovered_calls:
            print(f"{Fore.YELLOW}No function executions found across all traces.{Style.RESET_ALL}")
            return
        cls._check_for_multithreading(all_discovered_calls)

        targets_by_file, final_target_funcs = cls._determine_targets(
            all_discovered_calls, config, all_presets, is_preset_defined
        )

        cls._verify_and_print_traces(all_discovered_calls, targets_by_file, final_target_funcs)

        if not targets_by_file and not final_target_funcs:
            print(f"{Fore.BLUE}No functions selected or test generation cancelled.{Style.RESET_ALL}")
            return

        cls._save_unified_import_map(config)

        generator = cls._initialize_generator(config, report_path)
        if not generator:
            return

        cls._run_generation_tasks(generator, config, targets_by_file, final_target_funcs)

        print(f"\n{Fore.GREEN}{Style.BRIGHT}=== Unit Test Generation Workflow Finished ==={Style.RESET_ALL}")

    @staticmethod
    def _load_calls_from_report(report_path: str) -> Dict[str, Dict[str, List[Dict]]]:
        """Reads a report file and organizes all found function calls by file and function name."""
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                # The report now directly contains the final, nested call tree
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"{Fore.RED}Error: Failed to read or parse report file {report_path}. Details: {e}{Style.RESET_ALL}")
            return {}


# This alias is intended for use as a decorator, where snake_case is idiomatic.
generate_unit_tests = UnitTestGeneratorDecorator  # pylint: disable=invalid-name
