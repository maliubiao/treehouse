import functools
import json
import logging
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from gpt_workflow.unittester.imports_resolve import resolve_imports

from .call_analyzer import CallAnalyzer
from .tracer import (
    _LOG_DIR,
    SysMonitoringTraceDispatcher,
    TraceConfig,
    TraceDispatcher,
    TraceLogic,
    TraceTypes,
    color_wrap,
)


class AnalyzableTraceLogic(TraceLogic):
    """
    一个增强的TraceLogic，它将事件转发给CallAnalyzer，并为单元测试生成目的解析模块导入。
    此版本通过重写 _add_to_buffer 方法，将所有最终的日志事件分发给分析器，
    确保分析器与日志系统看到完全一致的事件流。
    此版本使用类变量来聚合所有跟踪会话的导入信息。
    新增功能：为每个事件分配唯一ID，并在 verbose 模式下将原始事件记录到文件。
    """

    # --- 类级别的共享状态 ---
    _resolved_imports: Dict[str, Any] = {}
    _resolved_files: set = set()
    _imports_lock: threading.Lock = threading.Lock()

    # 用于事件溯源和调试的类级别状态
    _event_counter: int = 0
    _event_log_file = None
    _event_log_path = Path(_LOG_DIR) / "raw_trace_events.log"
    _event_lock: threading.Lock = threading.Lock()
    # ---

    def __init__(
        self,
        config: TraceConfig,
        analyzer: CallAnalyzer,
        import_map_file: Optional[Union[str, Path]],
    ):
        """
        初始化时，除了常规配置外，还需要一个 CallAnalyzer 实例。

        Args:
            config: 跟踪配置。
            analyzer: 用于分析事件的 CallAnalyzer 实例。
            import_map_file: 用于存储导入映射的文件路径。此路径应由上层（如装饰器）提供。
        """
        super().__init__(config)
        self.analyzer = analyzer
        self._thread_local = threading.local()

        if isinstance(import_map_file, str):
            self.import_map_file = Path(import_map_file)
        elif isinstance(import_map_file, Path):
            self.import_map_file = import_map_file
        else:
            self.import_map_file = Path(_LOG_DIR) / "import_map.json"

        # 根据分析器的 verbose 设置，决定是否启用原始事件日志记录
        self.log_raw_events = self.analyzer.verbose
        if self.log_raw_events:
            self._ensure_event_log_open()

    def handle_call(self, frame):
        """
        在处理函数调用前，先解析该文件中的导入依赖。
        """
        if getattr(self._thread_local, "is_resolving", False):
            return

        filename = frame.f_code.co_filename

        if not (filename.startswith("<") and filename.endswith(">")):
            with AnalyzableTraceLogic._imports_lock:
                is_resolved = filename in AnalyzableTraceLogic._resolved_files

            if not is_resolved:
                setattr(self._thread_local, "is_resolving", True)
                try:
                    imports = resolve_imports(frame)
                    with AnalyzableTraceLogic._imports_lock:
                        if imports:
                            AnalyzableTraceLogic._resolved_imports[filename] = imports
                        AnalyzableTraceLogic._resolved_files.add(filename)
                except Exception as e:
                    logging.error(f"Failed to resolve imports for {filename}: {e}\n{traceback.format_exc()}")
                    with AnalyzableTraceLogic._imports_lock:
                        AnalyzableTraceLogic._resolved_files.add(filename)
                finally:
                    setattr(self._thread_local, "is_resolving", False)

        super().handle_call(frame)

    def _add_to_buffer(self, log_data: Any, color_type: str):
        """
        重写此方法以实现对分析器的事件分发和事件溯源。

        在将日志数据添加到原始的输出缓冲区之前，它会：
        1. 为事件分配一个全局唯一的、原子递增的ID。
        2. 将此ID注入到事件数据中，以便下游消费者（如CallAnalyzer）使用。
        3. 如果启用了原始事件日志，将带ID的事件写入 `raw_trace_events.log` 文件。
        4. 将事件传递给 CallAnalyzer 进行处理。
        """
        with AnalyzableTraceLogic._event_lock:
            AnalyzableTraceLogic._event_counter += 1
            new_id = AnalyzableTraceLogic._event_counter

            # 始终注入事件ID，以确保分析器可以访问它
            if isinstance(log_data, dict) and isinstance(log_data.get("data"), dict):
                log_data["data"]["event_id"] = new_id

            # 如果启用了详细模式，则将原始事件写入日志文件
            if self.log_raw_events and AnalyzableTraceLogic._event_log_file:
                try:
                    log_line = json.dumps(log_data, default=lambda o: f"<unserializable: {type(o).__name__}>")
                    AnalyzableTraceLogic._event_log_file.write(f"[EID: {new_id}] {log_line}\n")
                    # 立即刷新以确保在崩溃时也能看到日志
                    AnalyzableTraceLogic._event_log_file.flush()
                except Exception as e:
                    # 确保日志记录失败不会中断跟踪
                    AnalyzableTraceLogic._event_log_file.write(f"[EID: {new_id}] LOGGING_ERROR: {e}\n")

        try:
            event_map = {
                TraceTypes.COLOR_CALL: "call",
                TraceTypes.COLOR_RETURN: "return",
                TraceTypes.COLOR_LINE: "line",
                TraceTypes.COLOR_EXCEPTION: "exception",
                TraceTypes.COLOR_ERROR: "error",
            }
            event_type = event_map.get(color_type, color_type)
            self.analyzer.process_event(log_data, event_type)
        except Exception as e:
            error_msg = f"CallAnalyzer process_event failed: {e}\n{traceback.format_exc()}"
            logging.error(error_msg)
            super()._add_to_buffer(
                {"template": "⚠ ANALYZER ERROR: {error}", "data": {"error": error_msg}}, TraceTypes.ERROR
            )

        super()._add_to_buffer(log_data, color_type)

    def stop(self):
        """
        停止跟踪时，确保分析器完成处理。
        导入映射和原始事件日志的保存/关闭由atexit处理程序调用。
        """
        self.analyzer.finalize()
        super().stop()

    @classmethod
    def _ensure_event_log_open(cls):
        """确保原始事件日志文件只被打开一次。"""
        with cls._event_lock:
            if cls._event_log_file is None:
                try:
                    cls._event_log_path.parent.mkdir(parents=True, exist_ok=True)
                    # 以写模式打开，清空上次运行的日志
                    cls._event_log_file = open(cls._event_log_path, "w", encoding="utf-8")
                    print(
                        f"{color_wrap(f'📝 Raw event logging enabled. View details at: {cls._event_log_path}', TraceTypes.COLOR_TRACE)}"
                    )
                except IOError as e:
                    print(f"{color_wrap(f'❌ Could not open raw event log file: {e}', TraceTypes.COLOR_ERROR)}")

    @classmethod
    def close_event_log(cls):
        """在程序退出时关闭原始事件日志文件。"""
        with cls._event_lock:
            if cls._event_log_file:
                cls._event_log_file.close()
                cls._event_log_file = None

    @classmethod
    def save_import_map(cls, import_map_file: Union[str, Path]):
        """
        将所有已解析的导入依赖映射保存到文件。
        此方法应在程序退出前、所有跟踪结束后调用。
        """
        path = Path(import_map_file)
        with cls._imports_lock:
            if cls._resolved_imports:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8") as f:
                        json.dump(cls._resolved_imports, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    logging.error(f"Failed to save import map to {path}: {e}")
                    print(f"{color_wrap(f'❌ Error saving import map: {e}', TraceTypes.COLOR_ERROR)}")


def start_analyzable_trace(analyzer: CallAnalyzer, module_path=None, config: TraceConfig = None, **kwargs):
    """
    启动一个带有调用分析和依赖解析功能的调试跟踪会话。

    此函数与 tracer.start_trace 类似，但它使用 AnalyzableTraceLogic
    来注入 CallAnalyzer 和依赖解析逻辑。

    Args:
        analyzer: 用于分析事件的 CallAnalyzer 实例。
        module_path: 目标模块路径 (可选)。
        config: 跟踪配置实例 (可选)。
        **kwargs: 将传递给 TraceConfig 构造函数。
                  `import_map_file` 应在此处提供。
    """
    if not config:
        # 自动推断调用者文件名作为目标
        caller_frame = sys._getframe().f_back
        caller_filename = caller_frame.f_code.co_filename
        if "report_name" not in kwargs:
            log_name = caller_frame.f_code.co_name
            kwargs["report_name"] = log_name + ".html"
        config = TraceConfig(target_files=[caller_filename], **kwargs)

    # 使用我们自定义的 AnalyzableTraceLogic，并传入 import_map_file 路径
    logic_instance = AnalyzableTraceLogic(config, analyzer, kwargs.get("import_map_file"))

    tracer = None
    # 我们需要直接创建 Dispatcher 并传入我们的 logic_instance
    if sys.version_info >= (3, 12):
        tracer = SysMonitoringTraceDispatcher(str(module_path), config)
        tracer._logic = logic_instance
    else:
        tracer = TraceDispatcher(str(module_path), config)
        tracer._logic = logic_instance

    # 关键修复：使用 f_back 获取调用者帧
    caller_frame = sys._getframe().f_back
    tracer.add_target_frame(caller_frame)
    try:
        if tracer:
            tracer.start()
        caller_frame.f_trace_lines = True
        caller_frame.f_trace_opcodes = True
        return tracer
    except Exception as e:
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
    include_stdlibs: Optional[List[str]] = None,
    import_map_file: Optional[Union[str, Path]] = None,
):
    """
    一个功能强大的函数跟踪装饰器，集成了调用分析和依赖解析功能。

    Args:
        analyzer: 一个 CallAnalyzer 实例，用于收集和分析数据。
        target_files: 目标文件模式列表，支持通配符
        line_ranges: 文件行号范围字典
        capture_vars: 要捕获的变量表达式列表
        report_name: 报告文件名
        exclude_functions: 要排除的函数名列表
        enable_var_trace: 是否启用变量操作跟踪
        ignore_self: 是否忽略跟踪器自身
        ignore_system_paths: 是否忽略系统路径和第三方包路径
        source_base_dir: 源代码根目录
        disable_html: 是否禁用HTML报告
        include_stdlibs: 特别包含的标准库模块列表
        import_map_file: 用于存储导入映射的文件路径。
    """
    # 如果未指定目标文件，则自动将装饰器所在的文件设为目标
    if not target_files:
        try:
            target_files = [sys._getframe(1).f_code.co_filename]
        except (ValueError, AttributeError):
            target_files = []

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 如果 target_files 仍然为空，从函数对象获取
            final_target_files = target_files or [func.__code__.co_filename]

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
                include_stdlibs=include_stdlibs,
            )
            # 使用新的启动函数，并传入 analyzer 和 import_map_file
            t = start_analyzable_trace(analyzer=analyzer, config=config, import_map_file=import_map_file)

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                if t:
                    t.stop()

        return wrapper

    return decorator
