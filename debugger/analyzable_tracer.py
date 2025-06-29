import functools
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .call_analyzer import CallAnalyzer
from .tracer import SysMonitoringTraceDispatcher, TraceConfig, TraceDispatcher, TraceLogic, TraceTypes, color_wrap


class AnalyzableTraceLogic(TraceLogic):
    """
    一个继承自 TraceLogic 的特殊逻辑类，它将事件转发给一个 CallAnalyzer 实例。
    """

    def __init__(self, config: TraceConfig, analyzer: CallAnalyzer):
        """
        初始化时，除了常规配置外，还需要一个 CallAnalyzer 实例。

        Args:
            config: 跟踪配置。
            analyzer: 用于分析事件的 CallAnalyzer 实例。
        """
        super().__init__(config)
        self.analyzer = analyzer

    def _add_to_buffer(self, log_data: Any, color_type: str):
        """
        重写此方法以实现“挂载”分析器。

        在将日志数据添加到原始的输出缓冲区之前，先将其传递给 CallAnalyzer 进行处理。
        """
        # 1. 将事件发送给分析器进行结构化处理
        try:
            # 将事件类型从颜色转换为标准类型
            event_map = {
                TraceTypes.COLOR_CALL: TraceTypes.CALL,
                TraceTypes.COLOR_RETURN: TraceTypes.RETURN,
                TraceTypes.COLOR_LINE: TraceTypes.LINE,
                TraceTypes.COLOR_EXCEPTION: TraceTypes.EXCEPTION,
                TraceTypes.COLOR_ERROR: TraceTypes.ERROR,
            }
            event_type = event_map.get(color_type, color_type)
            self.analyzer.process_event(log_data, event_type)
        except Exception as e:
            # 确保分析器的任何错误都不会中断正常的日志记录
            import traceback

            error_msg = f"CallAnalyzer process_event failed: {e}\n{traceback.format_exc()}"
            super()._add_to_buffer({"template": "⚠ {error}", "data": {"error": error_msg}}, TraceTypes.ERROR)

        # 2. 调用父类方法，保持原有的日志输出功能
        super()._add_to_buffer(log_data, color_type)


def start_analyzable_trace(analyzer: CallAnalyzer, module_path=None, config: TraceConfig = None, **kwargs):
    """
    启动一个带有调用分析功能的调试跟踪会话。

    此函数与 tracer.start_trace 类似，但它使用 AnalyzableTraceLogic
    来注入 CallAnalyzer。

    Args:
        analyzer: 用于分析事件的 CallAnalyzer 实例。
        module_path: 目标模块路径 (可选)。
        config: 跟踪配置实例 (可选)。
    """
    if not config:
        # 自动推断调用者文件名作为目标
        caller_frame = sys._getframe().f_back
        caller_filename = caller_frame.f_code.co_filename
        if "report_name" not in kwargs:
            log_name = caller_frame.f_code.co_name
            kwargs["report_name"] = log_name + ".html"
        config = TraceConfig(target_files=[caller_filename], **kwargs)

    # 使用我们自定义的 AnalyzableTraceLogic
    logic_instance = AnalyzableTraceLogic(config, analyzer)

    tracer = None
    # 此处我们不能直接使用 get_tracer, 因为它内部创建了 TraceLogic
    # 我们需要直接创建 Dispatcher 并传入我们的 logic_instance
    if sys.version_info >= (3, 12):
        tracer = SysMonitoringTraceDispatcher(str(module_path), config)
        tracer._logic = logic_instance
    else:
        tracer = TraceDispatcher(str(module_path), config)
        tracer._logic = logic_instance

    caller_frame = sys._getframe().f_back
    tracer.add_target_frame(caller_frame)
    try:
        if tracer:
            tracer.start()
        caller_frame.f_trace_lines = True
        caller_frame.f_trace_opcodes = True
        return tracer
    except Exception as e:
        import traceback

        logging.error("💥 ANALYZER DEBUGGER INIT ERROR: %s\n%s", str(e), traceback.format_exc())
        print(
            color_wrap(
                f"❌ 分析调试器初始化错误: {str(e)}\n{traceback.format_exc()}",
                TraceTypes.COLOR_ERROR,
            )
        )
        raise


def analyzable_trace(
    analyzer: CallAnalyzer,
    target_files: Optional[List[str]] = None,
    line_ranges: Optional[Dict[str, List[Tuple[int, int]]]] = None,
    capture_vars: Optional[List[str]] = None,
    report_name: str = "analyzed_trace_report.html",
    exclude_functions: Optional[List[str]] = None,
    enable_var_trace: bool = False,
    ignore_self: bool = True,
    ignore_system_paths: bool = True,
    source_base_dir: Optional[Path] = None,
    disable_html: bool = False,
):
    """
    一个功能强大的函数跟踪装饰器，集成了调用分析功能。

    Args:
        analyzer: 一个 CallAnalyzer 实例，用于收集和分析数据。
        ... (其他参数与 tracer.trace 装饰器相同)
    """
    # 如果未指定目标文件，则自动将装饰器所在的文件设为目标
    if not target_files:
        # a bit of magic to get the filename of the decorated function
        try:
            target_files = [sys._getframe(1).f_code.co_filename]
        except (ValueError, AttributeError):
            target_files = []

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # If target_files is still empty, get it from the function object
            final_target_files = target_files or [func.__code__.co_filename]

            print(color_wrap("[start analyzable tracer]", TraceTypes.COLOR_CALL))
            config = TraceConfig(
                target_files=final_target_files,
                line_ranges=line_ranges,
                capture_vars=capture_vars,
                callback=None,  # 回调逻辑现在由 analyzer 处理
                report_name=report_name,
                exclude_functions=exclude_functions,
                enable_var_trace=enable_var_trace,
                ignore_self=ignore_self,
                ignore_system_paths=ignore_system_paths,
                start_function=None,
                source_base_dir=source_base_dir,
                disable_html=disable_html,
            )

            # 使用新的启动函数，并传入 analyzer
            t = start_analyzable_trace(analyzer=analyzer, config=config)

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                if t:
                    print(color_wrap("[stop analyzable tracer]", TraceTypes.COLOR_RETURN))
                    t.stop()

        return wrapper

    return decorator
