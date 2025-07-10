import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from colorama import Fore, Style

from .analyzable_tracer import AnalyzableTraceLogic, TraceConfig
from .call_analyzer import CallAnalyzer
from .tracer import SysMonitoringTraceDispatcher, TraceDispatcher
from .unit_test_generator_decorator import UnitTestGeneratorDecorator

_active_session: Dict[str, Any] = {"tracer": None, "analyzer": None, "config": None}


def start_trace_for_test_gen(
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
    手动启动一个用于生成单元测试的全局追踪会话。

    这提供了一种替代装饰器的方案，适用于需要更精细控制追踪生命周期的场景。
    在调用此函数后，程序中的所有符合 `target_files` 的代码执行都将被追踪。

    Args:
        target_files: 需要追踪的文件模式列表 (e.g., ["project_name/**/*.py"])。
        target_functions: 预设要生成测试的函数列表。
        ... (所有参数与 UnitTestGeneratorDecorator 的构造函数相同)
    """
    if _active_session.get("tracer"):
        print(f"{Fore.YELLOW}Warning: A trace session is already active. Please stop it first.{Style.RESET_ALL}")
        return

    print(f"{Fore.CYAN}Starting manual test generation trace...{Style.RESET_ALL}")

    analyzer = CallAnalyzer(verbose=verbose_trace)

    # 将所有配置参数打包，以便传递给生成器工作流
    generator_config = {
        "target_files": target_files,
        "target_functions": target_functions,
        "output_dir": output_dir,
        "report_dir": report_dir,
        "auto_confirm": auto_confirm,
        "enable_var_trace": enable_var_trace,
        "verbose_trace": verbose_trace,
        "model_name": model_name,
        "checker_model_name": checker_model_name,
        "use_symbol_service": use_symbol_service,
        "trace_llm": trace_llm,
        "llm_trace_dir": llm_trace_dir,
        "num_workers": num_workers,
    }

    # 为追踪器本身创建配置
    trace_config_params = {
        "target_files": target_files if target_files is not None else ["*.py"],
        "enable_var_trace": enable_var_trace,
        "ignore_system_paths": True,
        "source_base_dir": UnitTestGeneratorDecorator.default_source_base_dir,
    }
    trace_config = TraceConfig(**trace_config_params)

    import_map_file_path = UnitTestGeneratorDecorator.default_source_base_dir / "logs/import_map.json"
    generator_config["import_map_file"] = import_map_file_path

    logic_instance = AnalyzableTraceLogic(trace_config, analyzer, import_map_file_path)

    tracer: Optional[Union[TraceDispatcher, SysMonitoringTraceDispatcher]] = None
    if sys.version_info >= (3, 12):
        tracer = SysMonitoringTraceDispatcher(None, trace_config)
    else:
        tracer = TraceDispatcher(None, trace_config)
    tracer._logic = logic_instance

    tracer.start()  # 设置全局追踪函数

    _active_session["tracer"] = tracer
    _active_session["analyzer"] = analyzer
    _active_session["config"] = generator_config


def stop_and_generate_tests():
    """
    停止当前的追踪会话，并立即启动单元测试生成工作流。
    """
    tracer = _active_session.get("tracer")
    if not tracer:
        print(f"{Fore.YELLOW}Warning: No active trace session found to stop.{Style.RESET_ALL}")
        return

    print(f"{Fore.CYAN}Stopping tracer and initiating test generation...{Style.RESET_ALL}")

    try:
        tracer.stop()  # 停止并移除全局追踪函数

        analyzer = _active_session["analyzer"]
        config = _active_session["config"]

        # 清理会话，以便可以开始下一次追踪
        _active_session["tracer"] = None
        _active_session["analyzer"] = None
        _active_session["config"] = None

        # 调用为手动模式设计的核心生成逻辑
        UnitTestGeneratorDecorator.run_manual_generation(analyzer, config)

    except Exception:
        print(f"{Fore.RED}An unexpected error occurred during manual test generation:{Style.RESET_ALL}")
        traceback.print_exc()
    finally:
        # 确保追踪器资源（如原始事件日志文件）被关闭
        AnalyzableTraceLogic.close_event_log()
        print(f"{Fore.CYAN}Manual generation process finished.{Style.RESET_ALL}")
