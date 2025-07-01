import atexit
import json
import multiprocessing
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from colorama import Fore, Style

from debugger.analyzable_tracer import analyzable_trace
from debugger.call_analyzer import CallAnalyzer


class UnitTestGeneratorDecorator:
    """
    为函数添加单元测试生成能力的装饰器类

    使用示例:
        @generate_unit_tests(
            target_functions=["complex_sub_function"],
            output_dir="generated_tests",
            auto_confirm=True,
            trace_llm=True,
            num_workers=2  # [REFACTORED] 控制并行生成的工作进程数
        )
        def main_entrypoint():
            # 函数实现...
            # 'main_entrypoint' 自身也会被自动作为测试目标
    """

    # 注册表跟踪所有装饰的函数
    _registry = defaultdict(dict)

    def __init__(
        self,
        target_functions: List[str],
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
        初始化装饰器

        :param target_functions: 需要为其生成单元测试的目标函数名列表
        :param output_dir: 生成的单元测试文件输出目录
        :param report_dir: 调用分析报告存储目录
        :param auto_confirm: 是否自动确认所有提示
        :param enable_var_trace: 是否启用变量跟踪
        :param model_name: 主模型名称
        :param checker_model_name: 检查器模型名称
        :param use_symbol_service: 是否使用符号服务
        :param trace_llm: 是否记录LLM的提示和响应
        :param llm_trace_dir: LLM跟踪日志的存储目录
        :param num_workers: [REFACTORED] 并行生成单元测试的工作进程数。如果为0或1，则顺序执行。
        """
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
        self.num_workers = num_workers

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)

        if not hasattr(UnitTestGeneratorDecorator, "_atexit_registered"):
            atexit.register(self._generate_all_tests_on_exit)
            UnitTestGeneratorDecorator._atexit_registered = True

    def __call__(self, func: Callable) -> Callable:
        """装饰器调用方法"""
        analyzer = CallAnalyzer()
        func_name = func.__name__

        # [NEW FEATURE] 自动将被装饰的入口函数加入测试目标列表
        if func_name not in self.target_functions:
            self.target_functions.append(func_name)

        traced_func = analyzable_trace(
            analyzer=analyzer,
            target_files=["*.py"],
            ignore_system_paths=True,
            enable_var_trace=self.enable_var_trace,
            report_name=f"{func_name}_report.html",
        )(func)

        self._registry[func_name] = {
            "analyzer": analyzer,
            "original_func": func,
            "traced_func": traced_func,
            "target_functions": self.target_functions,
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
            },
        }

        return traced_func

    @classmethod
    def _generate_all_tests_on_exit(cls):
        """
        [REFACTORED] 程序退出时生成所有单元测试。
        此方法现在仅负责协调，将具体的生成逻辑（包括并行处理）完全委托给 UnitTestGenerator。
        """
        # 延迟导入，避免循环依赖，并确保在多进程环境中工作正常
        from gpt_workflow.unittest_generator import UnitTestGenerator

        print(f"\n{Fore.CYAN}{Style.BRIGHT}=== 开始单元测试生成流程 ===")
        print(f"检测到 {len(cls._registry)} 个装饰的入口函数...{Style.RESET_ALL}")

        for entry_func_name, data in cls._registry.items():
            print(f"\n{Fore.YELLOW}处理入口函数: {entry_func_name}{Style.RESET_ALL}")
            analyzer: CallAnalyzer = data["analyzer"]
            entry_point_targets = data["target_functions"]
            config = data["config"]

            # 1. 生成原始调用报告
            raw_report_filename = f"{entry_func_name}_raw_trace_report.json"
            raw_report_path = str(Path(config["report_dir"]) / raw_report_filename)
            analyzer.generate_report(raw_report_path)
            print(f"{Fore.GREEN}✓ 原始调用报告已保存到: {raw_report_path}{Style.RESET_ALL}")

            # 2. 去重，生成清理后的报告
            clean_report_filename = f"{entry_func_name}_clean_trace_report.json"
            clean_report_path = str(Path(config["report_dir"]) / clean_report_filename)
            final_test_cases = cls._deduplicate_calls(raw_report_path, clean_report_path, entry_point_targets)

            if not final_test_cases:
                print(f"{Fore.YELLOW}没有找到可生成测试的目标函数调用。{Style.RESET_ALL}")
                continue

            # 3. 按目标文件分组，为每个文件启动一次生成任务
            file_to_funcs_map = defaultdict(list)
            for filename, funcs in final_test_cases.items():
                for func_name in funcs.keys():
                    file_to_funcs_map[filename].append(func_name)

            for filename, funcs_to_test in file_to_funcs_map.items():
                print(
                    f"\n{Fore.MAGENTA}准备为文件 '{filename}' 中的函数 "
                    f"({', '.join(funcs_to_test)}) 生成测试...{Style.RESET_ALL}"
                )
                try:
                    generator = UnitTestGenerator(
                        report_path=clean_report_path,
                        model_name=config["model_name"],
                        checker_model_name=config["checker_model_name"],
                        trace_llm=config["trace_llm"],
                        llm_trace_dir=config["llm_trace_dir"],
                    )

                    # 4. 调用生成器，由它内部处理并行逻辑
                    generator.generate(
                        target_funcs=funcs_to_test,
                        output_dir=config["output_dir"],
                        auto_confirm=config["auto_confirm"],
                        use_symbol_service=config["use_symbol_service"],
                        num_workers=config["num_workers"],
                    )
                except Exception as e:
                    import traceback

                    error_msg = f"为 '{filename}' 生成测试时发生意外错误: {e}\n{traceback.format_exc()}"
                    print(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")

        print(f"\n{Fore.GREEN}{Style.BRIGHT}=== 单元测试生成完成 ==={Style.RESET_ALL}")

    @staticmethod
    def _deduplicate_calls(
        raw_report_path: str, clean_report_path: str, targets: List[str]
    ) -> Dict[str, Dict[str, List[Dict]]]:
        """
        读取原始报告，根据执行路径去重，并保存为清理后的报告。
        一个“独特的执行路径”由执行的代码行集合和最终的异常类型（或无异常）共同定义。
        """
        try:
            with open(raw_report_path, "r", encoding="utf-8") as f:
                call_trees = json.load(f)

            final_test_cases = defaultdict(lambda: defaultdict(list))
            total_calls = 0
            unique_calls = 0

            for filename, funcs in call_trees.items():
                for func_name, records in funcs.items():
                    if func_name in targets:
                        total_calls += len(records)
                        seen_signatures = set()
                        unique_records = []
                        for record in records:
                            # 创建一个能代表执行路径的签名
                            lines = frozenset(
                                evt["data"]["line_no"] for evt in record.get("events", []) if evt.get("type") == "line"
                            )
                            exc_type = record.get("exception", {}).get("type") if record.get("exception") else None
                            signature = (lines, exc_type)

                            if signature not in seen_signatures:
                                unique_records.append(record)
                                seen_signatures.add(signature)

                        if unique_records:
                            final_test_cases[filename][func_name].extend(unique_records)
                            unique_calls += len(unique_records)

            with open(clean_report_path, "w", encoding="utf-8") as f:
                json.dump(final_test_cases, f, indent=2, default=str)

            print(
                f"{Fore.BLUE}✓ 调用记录去重完成: 从 {total_calls} 次目标调用中筛选出 {unique_calls} 个独特执行路径。{Style.RESET_ALL}"
            )
            print(f"{Fore.GREEN}✓ 清理后的报告已保存到: {clean_report_path}{Style.RESET_ALL}")
            return final_test_cases

        except (IOError, json.JSONDecodeError) as e:
            print(f"{Fore.RED}错误: 无法处理报告文件 {raw_report_path}。错误: {e}{Style.RESET_ALL}")
            return {}


# 装饰器别名
generate_unit_tests = UnitTestGeneratorDecorator
