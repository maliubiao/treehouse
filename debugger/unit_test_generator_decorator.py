import atexit
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from colorama import Fore, Style

from debugger.analyzable_tracer import analyzable_trace
from debugger.call_analyzer import CallAnalyzer
from gpt_workflow.unittest_generator import UnitTestGenerator


class UnitTestGeneratorDecorator:
    """
    为函数添加单元测试生成能力的装饰器类

    使用示例:
        @generate_unit_tests(
            target_functions=["complex_sub_function"],
            output_dir="generated_tests",
            auto_confirm=True
        )
        def main_entrypoint():
            # 函数实现...
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
        checker_model_name: str = "deepseek-checker",
        use_symbol_service: bool = True,
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
        """
        self.target_functions = target_functions
        self.output_dir = output_dir
        self.report_dir = report_dir
        self.auto_confirm = auto_confirm
        self.enable_var_trace = enable_var_trace
        self.model_name = model_name
        self.checker_model_name = checker_model_name
        self.use_symbol_service = use_symbol_service

        # 确保目录存在
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)

        # 注册退出处理函数
        if not hasattr(UnitTestGeneratorDecorator, "_atexit_registered"):
            atexit.register(self._generate_all_tests_on_exit)
            UnitTestGeneratorDecorator._atexit_registered = True

    def __call__(self, func: Callable) -> Callable:
        """装饰器调用方法"""
        # 为每个装饰的函数创建独立的CallAnalyzer
        analyzer = CallAnalyzer()
        func_name = func.__name__

        # 使用analyzable_trace装饰目标函数
        traced_func = analyzable_trace(
            analyzer=analyzer, enable_var_trace=self.enable_var_trace, report_name=f"{func_name}_report.html"
        )(func)

        # 注册函数信息
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
            },
        }

        return traced_func

    def _generate_all_tests_on_exit(self):
        """程序退出时生成所有单元测试"""
        print(f"\n{Fore.CYAN}{Style.BRIGHT}\n=== 开始单元测试生成流程 ===")
        print(f"检测到 {len(self._registry)} 个装饰函数{Style.RESET_ALL}")

        for func_name, data in self._registry.items():
            print(f"\n{Fore.YELLOW}处理函数: {func_name}{Style.RESET_ALL}")
            analyzer = data["analyzer"]
            target_functions = data["target_functions"]
            config = data["config"]

            # 为每个目标函数生成报告和测试
            for target_func in target_functions:
                print(f"{Fore.BLUE}生成目标函数 {target_func} 的单元测试...{Style.RESET_ALL}")

                # 生成报告文件路径
                report_filename = f"{func_name}_{target_func}_report.json"
                report_path = str(Path(config["report_dir"]) / report_filename)

                # 保存分析报告
                analyzer.generate_report(report_path)
                print(f"{Fore.GREEN}✓ 分析报告已保存到: {report_path}{Style.RESET_ALL}")

                # 生成单元测试
                generator = UnitTestGenerator(
                    report_path=report_path,
                    model_name=config["model_name"],
                    checker_model_name=config["checker_model_name"],
                )

                generator.generate(
                    target_func=target_func,
                    output_dir=config["output_dir"],
                    auto_confirm=config["auto_confirm"],
                    use_symbol_service=config["use_symbol_service"],
                )

        print(f"\n{Fore.GREEN}{Style.BRIGHT}=== 单元测试生成完成 ==={Style.RESET_ALL}")


# 装饰器别名
generate_unit_tests = UnitTestGeneratorDecorator
