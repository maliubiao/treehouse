import atexit
import json
import multiprocessing
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from colorama import Fore, Style

from debugger.analyzable_tracer import analyzable_trace
from debugger.call_analyzer import CallAnalyzer


class UnitTestGeneratorDecorator:
    """
    为函数添加单元测试生成能力的装饰器类。

    该装饰器会自动追踪指定文件模式下所有函数的执行，并在程序退出时，
    提供一个交互式界面，让用户选择为哪些函数生成单元测试。

    使用示例:
        # 示例 1: 追踪文件，交互式选择函数
        @generate_unit_tests(
            target_files=["my_app/**/*.py"], # 追踪 my_app 下所有 .py 文件
            auto_confirm=False,
        )
        def main_entrypoint():
            # ... 你的应用主逻辑 ...
            # main_entrypoint 自身及其调用的、在 target_files 范围内的函数都会被追踪。

        # 示例 2: 预先指定要生成测试的函数
        @generate_unit_tests(
            target_functions=["my_func1", "my_func2"], # 直接指定目标函数
            auto_confirm=True, # 通常与非交互模式一起使用
        )
        def run_specific_tests():
            # ...
    """

    _registry = defaultdict(dict)

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
            target_files: 需要追踪的文件模式列表 (支持 glob 通配符, e.g., ["project_name/**/*.py"])。
                          如果为 None, 默认为 ["*.py"]。
            target_functions: [新] 需要生成单元测试的函数名列表。如果提供此参数，
                              将跳过交互式选择，并自动为这些函数（以及被装饰的函数）生成测试。
                              这优先于 `auto_confirm`（对于函数选择）。
            output_dir: 生成的单元测试文件输出目录。
            report_dir: 调用分析报告存储目录。
            auto_confirm: 是否自动确认所有LLM建议和文件覆盖提示。如果提供了 `target_functions`，此参数对函数选择无效。
            enable_var_trace: 是否启用变量跟踪。
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

    def __call__(self, func: Callable) -> Callable:
        """装饰器调用方法，设置并启动追踪。"""
        analyzer = CallAnalyzer()
        func_name = func.__name__

        # 确保被装饰的函数本身一定在追踪范围内
        decorated_func_file = func.__code__.co_filename
        final_target_files = list(set(self.target_files + [decorated_func_file]))

        # [NEW] Handle target_functions to determine generation targets ahead of time
        final_target_functions = list(self.target_functions) if self.target_functions is not None else None
        if final_target_functions is not None:
            # Automatically add the decorated function to the generation targets if not already present
            if func_name not in final_target_functions:
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
        """
        提供一个交互式界面，让用户选择要为其生成测试的函数。
        """
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
        except EOFError:  # Handle non-interactive environments
            print(Fore.YELLOW + "No input received, defaulting to selecting all functions.")
            user_input = "A"

        if user_input == "Q":
            return None
        if user_input == "A" or not user_input:
            selected_funcs = [func for funcs in all_discovered_calls.values() for func in funcs.keys()]
            return list(set(selected_funcs))

        selected_targets = set()
        parts = [p.strip() for p in user_input.split(",")]
        for part in parts:
            if part in file_map:
                filename = file_map[part]
                selected_targets.update(all_discovered_calls[filename].keys())
            elif part in func_map:
                selected_targets.add(func_map[part])
            elif part:
                print(Fore.YELLOW + f"Warning: Invalid selection '{part}' ignored.")

        return list(selected_targets)

    @classmethod
    def _generate_all_tests_on_exit(cls):
        """
        [REFACTORED] 程序退出时，发现并选择目标，然后为每个文件启动一次测试生成。
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

            # [REFACTORED] Determine generation targets based on priority:
            # 1. `target_functions` if provided.
            # 2. Interactive selection if not in `auto_confirm` mode.
            # 3. All discovered functions if in `auto_confirm` mode.
            targets_for_generation = None
            all_discovered_funcs = {func for funcs in final_test_cases.values() for func in funcs.keys()}

            if target_functions:
                targets_for_generation = [f for f in target_functions if f in all_discovered_funcs]
            elif not config["auto_confirm"]:
                targets_for_generation = cls._interactive_target_selection(final_test_cases)
            else:  # auto_confirm is True and no target_functions
                targets_for_generation = list(all_discovered_funcs)

            if targets_for_generation is None:
                print(f"{Fore.BLUE}Test generation cancelled by user for '{entry_func_name}'.{Style.RESET_ALL}")
                continue
            if not targets_for_generation:
                print(f"{Fore.YELLOW}No functions selected for test generation.{Style.RESET_ALL}")
                continue

            print(
                f"\n{Fore.GREEN}Targets selected for generation: "
                f"{Style.BRIGHT}{', '.join(targets_for_generation)}{Style.RESET_ALL}"
            )

            file_to_funcs_map = defaultdict(list)
            for filename, funcs in final_test_cases.items():
                for func_name in funcs:
                    if func_name in targets_for_generation:
                        file_to_funcs_map[filename].append(func_name)

            for filename, funcs_to_test in file_to_funcs_map.items():
                print(
                    f"\n{Fore.MAGENTA}--- Generating tests for file: '{filename}' ---\n"
                    f"Functions: {', '.join(funcs_to_test)}{Style.RESET_ALL}"
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

                    error_msg = f"Failed to generate tests for '{filename}': {e}\n{traceback.format_exc()}"
                    print(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")

        print(f"\n{Fore.GREEN}{Style.BRIGHT}=== Unit Test Generation Workflow Finished ==={Style.RESET_ALL}")

    @staticmethod
    def _deduplicate_and_load_calls(report_path: str) -> Dict[str, Dict[str, List[Dict]]]:
        """
        [REFACTORED] 读取报告，根据执行路径去重，并返回所有唯一的、可测试的函数调用。
        """
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
                # [FIX] Filter out special function names like '<module>' or '<lambda>'
                # that are not suitable for test generation.
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
                f"{Fore.BLUE}Trace analysis: Found {unique_calls} unique execution paths "
                f"from {total_calls} total function calls.{Style.RESET_ALL}"
            )
        return final_test_cases


generate_unit_tests = UnitTestGeneratorDecorator
