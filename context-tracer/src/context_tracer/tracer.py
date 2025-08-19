import ast
import dis
import fnmatch
import functools
import inspect
import json
import linecache
import logging
import os
import queue
import sys
import threading
import time
import traceback
import types
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, Union

from .source_cache import get_statement_info
from .tracer_common import TraceTypes, truncate_repr_value
from .tracer_html import CallTreeHtmlRender
from .utils.path_utils import to_relative_module_path

try:
    from colorama import Fore, Style, just_fix_windows_console
except ImportError:

    class _Dummy:
        def __getattr__(self, _):
            return ""

    Fore = Style = _Dummy()

    def just_fix_windows_console():
        pass


just_fix_windows_console()

if TYPE_CHECKING:

    class MonitoringEvents:
        PY_START: int
        PY_RETURN: int
        PY_YIELD: int
        LINE: int
        RAISE: int
        RERAISE: int
        EXCEPTION_HANDLED: int
        PY_UNWIND: int
        PY_RESUME: int
        PY_THROW: int
        STOP_ITERATION: int
        NO_EVENTS: int
        CALL: int
        C_RETURN: int
        C_RAISE: int
        MISSING: Any

    class MonitoringModule:
        events: MonitoringEvents
        DISABLE: Any
        MISSING: Any

        def get_tool(self, _tool_id: int) -> Optional[str]: ...
        def use_tool_id(self, _tool_id: int, _tool_name: str) -> None: ...
        def set_events(self, _tool_id: int, _event_set: int) -> None: ...
        def register_callback(self, _tool_id: int, _event: int, _callback: Callable[..., Any]) -> None: ...
        def free_tool_id(self, _tool_id: int) -> None: ...


# Constants
_INDENT = "  "
_LOG_DIR = Path.cwd() / "tracer-logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
TRACE_LOG_NAME = _LOG_DIR / "trace.log"
LOG_NAME = _LOG_DIR / "debug.log"
_MAX_CALL_DEPTH = 20
_DEFAULT_REPORT_NAME = "trace_report.html"


# 该字典已被colorama替代

logging.basicConfig(
    filename=str(LOG_NAME),
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
    filemode="w",
)


class TraceConfig:
    """调试跟踪配置类"""

    def __init__(
        self,
        target_files: Optional[List[str]] = None,
        line_ranges: Optional[Dict[str, List[Tuple[int, int]]]] = None,
        skip_vars_on_lines: Optional[List[Dict[str, Any]]] = None,
        capture_vars: Optional[List[str]] = None,
        callback: Optional[callable] = None,
        report_name: str = _DEFAULT_REPORT_NAME,
        exclude_functions: Optional[List[str]] = None,
        enable_var_trace: bool = False,
        ignore_self: bool = True,
        ignore_system_paths: bool = True,
        start_function: Optional[List[str]] = None,
        source_base_dir: Optional[Union[str, Path]] = None,  # Changed type hint
        disable_html: bool = False,
        include_stdlibs: Optional[List[str]] = None,
        trace_c_calls: bool = False,
    ):
        """
        初始化跟踪配置

        Args:
            target_files: 目标文件模式列表，支持通配符
            line_ranges: 文件行号范围字典，key为文件名，value为 (start_line, end_line) 元组列表
            skip_vars_on_lines: 跳过变量捕获的规则列表
            capture_vars: 要捕获的变量表达式列表
            callback: 变量捕获时的回调函数
            report_name: HTML报告文件名
            exclude_functions: 要排除的函数名列表
            enable_var_trace: 是否启用变量操作跟踪
            ignore_self: 是否忽略跟踪器自身的文件
            ignore_system_paths: 是否忽略系统路径和第三方包路径
            start_function: 指定开始跟踪的函数
            source_base_dir: 源代码根目录，用于在报告中显示相对路径
            disable_html: 是否禁用HTML报告生成
            include_stdlibs: 特别包含的标准库模块列表（即使ignore_system_paths=True）
            trace_c_calls: 是否启用C函数调用跟踪
        """
        self.target_files = target_files or []
        self.line_ranges = self._parse_line_ranges(line_ranges or {})
        self.skip_vars_on_lines = skip_vars_on_lines or []
        self.capture_vars = capture_vars or []
        self.callback = callback
        self.report_name = report_name if report_name else _DEFAULT_REPORT_NAME
        self.exclude_functions = exclude_functions or []
        self.enable_var_trace = enable_var_trace
        self.ignore_self = ignore_self
        self.ignore_system_paths = ignore_system_paths
        self._compiled_patterns = [fnmatch.translate(pattern) for pattern in self.target_files]
        self._system_paths = self._get_system_paths() if ignore_system_paths else set()
        self.start_function = start_function
        # Convert source_base_dir to Path object
        self.source_base_dir: Optional[Path] = Path(source_base_dir) if source_base_dir else None
        self.disable_html = disable_html
        self.include_stdlibs = include_stdlibs or []
        self.trace_c_calls = trace_c_calls
        self._skip_vars_cache: Dict[str, bool] = {}

    @staticmethod
    def _get_system_paths() -> Set[str]:
        """获取系统路径和第三方包路径"""
        system_paths = set()
        for path in sys.path:
            try:
                resolved = str(Path(path).resolve())
                if any(
                    part.startswith(("site-packages", "dist-packages", "python")) or "lib/python" in resolved.lower()
                    for part in Path(resolved).parts
                ):
                    system_paths.add(resolved)
            except (ValueError, OSError):
                continue
        return system_paths

    def match_filename(self, filename: str) -> bool:
        """检查文件路径是否匹配目标文件模式"""
        if self.ignore_self and filename == __file__:
            return False
        # 过滤<frozen posixpath>这类特殊文件名
        if filename.startswith("<") and filename.endswith(">") or filename.endswith("sitecustomize.py"):
            return False

        try:
            resolved_path = Path(filename).resolve()
            resolved_str = str(resolved_path)
        except (ValueError, OSError):
            resolved_path = Path(filename)
            resolved_str = filename

        # 新增：检查是否属于特别包含的标准库模块
        if self.ignore_system_paths and self.include_stdlibs:
            # 检查是否属于系统路径
            in_system_path = any(resolved_str.startswith(sys_path) for sys_path in self._system_paths)
            if in_system_path:
                # 使用pathlib.parts来跨平台地检查路径组件
                path_components = set(resolved_path.parts)
                path_components.add(resolved_path.stem)
                is_included_stdlib = any(mod in path_components for mod in self.include_stdlibs)
                if is_included_stdlib:
                    return True  # 即使位于系统路径，但属于特别包含的模块，允许跟踪

        if self.ignore_system_paths:
            if any(part in ("site-packages", "dist-packages") for part in resolved_path.parts):
                return False
            if any(resolved_str.startswith(sys_path) for sys_path in self._system_paths):
                return False

        if not self.target_files:
            return True

        filename_posix = resolved_path.as_posix()
        return any(fnmatch.fnmatch(filename_posix, pattern) for pattern in self.target_files)

    def should_skip_vars(self, filename: str, lineno: int) -> bool:
        """检查是否应跳过给定文件和行号的变量捕獲。"""
        if not self.skip_vars_on_lines:
            return False

        # A simple cache for the check result for a given file/line combo
        cache_key = f"{filename}:{lineno}"
        if cache_key in self._skip_vars_cache:
            return self._skip_vars_cache[cache_key]

        try:
            resolved_path = Path(filename).resolve()
            filename_posix = resolved_path.as_posix()
        except (ValueError, OSError):
            filename_posix = filename  # Fallback for non-file paths like <string>

        for rule in self.skip_vars_on_lines:
            pattern = rule["pattern"]
            start = rule["start"]
            end = rule["end"]

            if fnmatch.fnmatch(filename_posix, pattern) or fnmatch.fnmatch(filename, pattern):
                if start <= lineno <= end:
                    self._skip_vars_cache[cache_key] = True
                    return True

        self._skip_vars_cache[cache_key] = False
        return False

    @classmethod
    def from_yaml(cls, config_path: Union[str, Path]) -> "TraceConfig":
        """
        从YAML配置文件加载配置

        Args:
            config_path: 配置文件路径

        Returns:
            TraceConfig实例

        Raises:
            ValueError: 配置文件格式错误
            FileNotFoundError: 配置文件不存在
        """
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        import yaml

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"配置文件解析失败: {str(e)}") from e

        if not isinstance(config_data, dict):
            raise ValueError("配置文件格式错误：应为字典格式")

        return cls(
            target_files=config_data.get("target_files", []),
            line_ranges=config_data.get("line_ranges", {}),
            skip_vars_on_lines=config_data.get("skip_vars_on_lines", []),
            capture_vars=config_data.get("capture_vars", []),
            callback=config_data.get("callback", None),
            exclude_functions=config_data.get("exclude_functions", []),
            ignore_system_paths=config_data.get("ignore_system_paths", True),
            source_base_dir=config_data.get("source_base_dir", None),
            include_stdlibs=config_data.get("include_stdlibs", []),
            disable_html=config_data.get("disable_html", False),
            trace_c_calls=config_data.get("trace_c_calls", False),
        )

    @staticmethod
    def _parse_line_ranges(line_ranges: Dict) -> defaultdict:
        """
        解析行号范围配置

        Args:
            line_ranges: 原始行号范围配置

        Returns:
            解析后的行号范围字典，key为文件名，value为行号集合

        Raises:
            ValueError: 行号范围配置格式错误
        """
        parsed = defaultdict(set)
        for file_path, ranges in line_ranges.items():
            if not isinstance(ranges, list):
                raise ValueError(f"行号范围配置错误：{file_path} 的值应为列表")
            try:
                abs_path = str(Path(file_path).resolve())
                line_set = set()
                for range_tuple in ranges:
                    if isinstance(range_tuple, (tuple, list)) and len(range_tuple) == 2:
                        start, end = range_tuple
                        if start > end:
                            raise ValueError(f"行号范围错误：起始行号 {start} 大于结束行号 {end}")
                        line_set.update(range(start, end + 1))
                    else:
                        raise ValueError(f"行号格式错误：{range_tuple} 应为 (start, end) 元组")
                parsed[abs_path] = line_set
            except (ValueError, OSError) as e:
                raise ValueError(f"文件路径解析失败: {file_path}, 错误: {str(e)}") from e
        return parsed

    @staticmethod
    def _validate_expressions(expressions: List[str]) -> bool:
        """
        验证表达式合法性

        Args:
            expressions: 要验证的表达式列表

        Returns:
            bool: 所有表达式是否合法

        Raises:
            ValueError: 表达式不合法
        """
        for expr in expressions:
            try:
                ast.parse(expr)
            except SyntaxError as e:
                raise ValueError(f"表达式 '{expr}' 不合法: {str(e)}") from e
        return True

    def validate(self) -> bool:
        """
        验证配置有效性

        Returns:
            bool: 配置是否有效
        """
        is_valid = True
        if not isinstance(self.target_files, list):
            is_valid = False
        if not isinstance(self.line_ranges, dict):
            is_valid = False
        if not isinstance(self.capture_vars, list):
            is_valid = False
        try:
            self._validate_expressions(self.capture_vars)
        except ValueError:
            is_valid = False
        for _, ranges in self.line_ranges.items():
            if not all(isinstance(r, tuple) and len(r) == 2 for r in ranges):
                is_valid = False
            if any(start > end for start, end in ranges):
                is_valid = False
        return is_valid

    def is_excluded_function(self, func_name: str) -> bool:
        """检查函数名是否在排除列表中"""
        return func_name in self.exclude_functions


def color_wrap(text, color_type):
    """包装颜色但不影响日志文件"""
    color_mapping = {
        TraceTypes.COLOR_CALL: Fore.GREEN,
        TraceTypes.COLOR_RETURN: Fore.BLUE,
        TraceTypes.COLOR_VAR: Fore.YELLOW,
        TraceTypes.COLOR_LINE: Style.RESET_ALL,
        TraceTypes.COLOR_ERROR: Fore.RED,
        TraceTypes.COLOR_TRACE: Fore.MAGENTA,
        TraceTypes.COLOR_RESET: Style.RESET_ALL,
        TraceTypes.COLOR_EXCEPTION: Fore.RED,
    }
    return f"{color_mapping.get(color_type, '')}{text}{Style.RESET_ALL}"


class TraceDispatcher:
    def __init__(self, target_path, config: TraceConfig):
        self.target_path = target_path
        self.config = config
        self.path_cache = {}
        self._logic = TraceLogic(config)
        self.active_frames = set()
        self.simple_frames = set()  # For shallow tracing

    def add_target_frame(self, frame):
        if self.is_target_frame(frame):
            self.active_frames.add(frame)

    def is_target_frame(self, frame):
        """精确匹配目标模块路径"""
        if not frame or not frame.f_code:
            if frame:
                frame.f_trace_lines = False
            return False

        if frame.f_code.co_name.startswith("<genexpr>"):
            # one line code, ignore
            return False
        try:
            # 此时 frame 和 frame.f_code 保证不为 None
            if not frame.f_code.co_filename:
                frame.f_trace_lines = False
                return False
            filename = frame.f_code.co_filename
            result = self.path_cache.get(filename, None)
            if result is not None:
                if result is False:
                    frame.f_trace_lines = False
                return result
            frame_path = Path(filename).resolve()
            matched = self.config.match_filename(str(frame_path))
            self.path_cache[filename] = matched
            if not matched:
                frame.f_trace_lines = False
            return matched
        except (AttributeError, ValueError, OSError) as e:
            logging.debug("Frame check error: %s", str(e))
            return False

    def trace_dispatch(self, frame, event, arg):
        """事件分发器"""
        if event == TraceTypes.CALL:
            return self._handle_call_event(frame)
        if event == TraceTypes.RETURN:
            # self._logic.flush_exception()
            return self._handle_return_event(frame, arg)
        if event == TraceTypes.LINE:
            return self._handle_line_event(frame)
        if event == TraceTypes.EXCEPTION:
            return self._handle_exception_event(frame, arg)
        return None

    def _handle_call_event(self, frame, _arg=None):
        """处理函数调用事件"""
        self._logic.init_stack_variables()
        self._logic.maybe_unwanted_frame(frame)

        if self._logic.inside_unwanted_frame(frame):
            return self.trace_dispatch

        if self.is_target_frame(frame):
            self.active_frames.add(frame)
            self._logic.handle_call(frame)
        elif frame.f_back in self.active_frames:
            # Boundary call: from a target frame to a non-target one
            self.simple_frames.add(frame)
            self._logic.handle_call(frame, is_simple=True)

        return self.trace_dispatch

    def _handle_return_event(self, frame, arg):
        """处理返回事件，支持active和simple两种模式"""
        self._logic.leave_unwanted_frame(frame)

        is_simple = frame in self.simple_frames
        is_active = frame in self.active_frames

        if is_active or is_simple:
            self._logic.handle_return(frame, arg, is_simple=is_simple)
            self._logic.frame_cleanup(frame)
            if is_active:
                self.active_frames.remove(frame)
            if is_simple:
                self.simple_frames.remove(frame)

        return self.trace_dispatch

    def _handle_line_event(self, frame, _arg=None):
        """处理行号事件，只对active frame有效"""
        if frame in self.active_frames:
            if self._logic.inside_unwanted_frame(frame):
                return self.trace_dispatch
            self._logic.handle_line(frame)
        return self.trace_dispatch

    def _handle_exception_event(self, frame, arg):
        """处理异常事件，支持active和simple两种模式"""
        is_simple = frame in self.simple_frames
        is_active = frame in self.active_frames

        if is_active or is_simple:
            if self._logic.inside_unwanted_frame(frame):
                return self.trace_dispatch
            exc_type, exc_value, _ = arg
            self._logic.handle_exception(exc_type, exc_value, frame, is_simple=is_simple)
            # Exception implies a return, so we clean up the frame
            self._logic.frame_cleanup(frame)
            if is_active:
                self.active_frames.remove(frame)
            if is_simple:
                self.simple_frames.remove(frame)

        return self.trace_dispatch

    def start(self):
        """启动跟踪"""
        self._logic.start_flush_thread()
        sys.settrace(self.trace_dispatch)
        self._logic.start()

    def stop(self) -> Optional[Path]:
        """停止跟踪并返回报告路径"""
        sys.settrace(None)
        report_path = self._logic.stop()
        logging.info("⏹ DEBUG SESSION ENDED\n")
        print(color_wrap("\n⏹ 调试会话结束", TraceTypes.COLOR_RETURN))
        return report_path


class SysMonitoringTraceDispatcher:
    """Python 3.12+ sys.monitoring based trace dispatcher"""

    def __init__(self, target_path, config: TraceConfig):
        self.target_path = target_path
        self.config = config
        self.path_cache = {}
        self._logic = TraceLogic(config)
        self.active_frames = set()
        self.simple_frames = set()  # For shallow tracing
        self._tool_id = None
        self._registered = False
        self.monitoring_module: MonitoringModule = sys.monitoring
        self.start_function = config.start_function
        self.start_at_enable = False

    def _register_tool(self):
        """Register this tool with sys.monitoring"""
        if self._registered:
            return

        try:
            # Try to find an available tool ID
            for tool_id in range(6):
                if self.monitoring_module.get_tool(tool_id) is None:
                    try:
                        self.monitoring_module.use_tool_id(tool_id, "PythonDebugger")
                        self._tool_id = tool_id
                        self._registered = True
                        break
                    except ValueError:
                        continue

            if not self._registered:
                raise RuntimeError("No available tool IDs in sys.monitoring")

            # Register callbacks for the events we care about
            events = (
                self.monitoring_module.events.PY_START
                | self.monitoring_module.events.PY_RETURN
                | self.monitoring_module.events.PY_YIELD
                | self.monitoring_module.events.LINE
                | self.monitoring_module.events.RAISE
                | self.monitoring_module.events.RERAISE
                | self.monitoring_module.events.EXCEPTION_HANDLED
                | self.monitoring_module.events.PY_UNWIND
                | self.monitoring_module.events.PY_RESUME
                | self.monitoring_module.events.PY_THROW
            )
            if self.config.trace_c_calls:
                events |= (
                    self.monitoring_module.events.CALL
                    | self.monitoring_module.events.C_RETURN
                    | self.monitoring_module.events.C_RAISE
                )

            self.monitoring_module.set_events(self._tool_id, events)

            # Register the callbacks
            self.monitoring_module.register_callback(
                self._tool_id,
                self.monitoring_module.events.PY_START,
                self.handle_py_start,
            )
            self.monitoring_module.register_callback(
                self._tool_id,
                self.monitoring_module.events.PY_RETURN,
                self.handle_py_return,
            )
            self.monitoring_module.register_callback(
                self._tool_id, self.monitoring_module.events.LINE, self.handle_line
            )
            self.monitoring_module.register_callback(
                self._tool_id, self.monitoring_module.events.RAISE, self.handle_raise
            )
            self.monitoring_module.register_callback(
                self._tool_id,
                self.monitoring_module.events.EXCEPTION_HANDLED,
                self.handle_exception_handled,
            )
            # Add handlers for previously unhandled events
            self.monitoring_module.register_callback(
                self._tool_id,
                self.monitoring_module.events.PY_YIELD,
                self.handle_py_yield,
            )
            self.monitoring_module.register_callback(
                self._tool_id,
                self.monitoring_module.events.PY_UNWIND,
                self.handle_py_unwind,
            )
            self.monitoring_module.register_callback(
                self._tool_id,
                self.monitoring_module.events.PY_THROW,
                self.handle_py_throw,
            )
            self.monitoring_module.register_callback(
                self._tool_id,
                self.monitoring_module.events.RERAISE,
                self._handle_reraise,
            )
            self.monitoring_module.register_callback(
                self._tool_id,
                self.monitoring_module.events.PY_RESUME,
                self.handle_py_resume,
            )
            if self.config.trace_c_calls:
                self.monitoring_module.register_callback(
                    self._tool_id, self.monitoring_module.events.CALL, self.handle_call
                )
                self.monitoring_module.register_callback(
                    self._tool_id, self.monitoring_module.events.C_RETURN, self.handle_c_return
                )
                self.monitoring_module.register_callback(
                    self._tool_id, self.monitoring_module.events.C_RAISE, self.handle_c_raise
                )

        except (RuntimeError, ValueError) as e:
            logging.error("Failed to register monitoring tool: %s", str(e))
            raise

    def _unregister_tool(self):
        """Unregister this tool from sys.monitoring"""
        if not self._registered or self._tool_id is None:
            return

        try:
            # Unregister all callbacks
            self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.PY_START, None)
            self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.PY_RETURN, None)
            self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.LINE, None)
            self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.RAISE, None)
            self.monitoring_module.register_callback(
                self._tool_id, self.monitoring_module.events.EXCEPTION_HANDLED, None
            )
            self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.PY_YIELD, None)
            self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.PY_UNWIND, None)
            self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.PY_THROW, None)
            self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.RERAISE, None)
            if self.config.trace_c_calls:
                self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.CALL, None)
                self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.C_RETURN, None)
                self.monitoring_module.register_callback(self._tool_id, self.monitoring_module.events.C_RAISE, None)

            # Disable all events
            self.monitoring_module.set_events(self._tool_id, self.monitoring_module.events.NO_EVENTS)

            # Free the tool ID
            self.monitoring_module.free_tool_id(self._tool_id)
            self._registered = False
            self._tool_id = None

        except (RuntimeError, ValueError) as e:
            logging.error("Failed to unregister monitoring tool: %s", str(e))

    def handle_py_start(self, _code, _offset):
        """Handle PY_START event (function entry)"""
        self._logic.init_stack_variables()

        frame = sys._getframe(1)  # Get the frame of the function being called
        self._logic.maybe_unwanted_frame(frame)

        if self._logic.inside_unwanted_frame(frame):
            return self.monitoring_module.DISABLE

        if self.is_target_frame(frame):
            # If we're waiting for a start function, check if this is it
            if self.start_function and not self.start_at_enable:
                if frame.f_code.co_name in self.start_function:
                    self.start_at_enable = True
                else:
                    return self.monitoring_module.DISABLE  # Not the start function yet

            self.active_frames.add(frame)
            self._logic.handle_call(frame, is_simple=False)
            return None  # Enable all events for this frame
        elif frame.f_back in self.active_frames:
            # Boundary call: from a target frame to a non-target one
            self.simple_frames.add(frame)
            self._logic.handle_call(frame, is_simple=True)
            # For simple frames, we only want RETURN and PY_UNWIND events.
            return self.monitoring_module.events.PY_RETURN | self.monitoring_module.events.PY_UNWIND
        else:
            # Not a target, and not called by a target. Ignore.
            return self.monitoring_module.DISABLE

    def handle_py_resume(self, _code, _offset):
        """Handle PY_RESUME event (function resume)"""
        pass

    def handle_py_return(self, _code, _offset, retval):
        """Handle PY_RETURN event (function return)"""
        frame = sys._getframe(1)
        is_simple = frame in self.simple_frames
        is_active = frame in self.active_frames

        if is_active or is_simple:
            if not self._logic.inside_unwanted_frame(frame):
                self._logic.handle_return(frame, retval, is_simple=is_simple)
            self._logic.frame_cleanup(frame)
            if is_active:
                self.active_frames.discard(frame)
            if is_simple:
                self.simple_frames.discard(frame)
        self._logic.init_stack_variables()
        self._logic.leave_unwanted_frame(frame)

    def handle_line(self, _code, _line_number):
        """Handle LINE event"""
        frame = sys._getframe(1)  # Get the current frame
        if frame in self.active_frames:
            if not self._logic.inside_unwanted_frame(frame):
                self._logic.handle_line(frame)

    def handle_raise(self, _code, _offset, exc):
        """Handle RAISE event (exception raised)"""
        frame = sys._getframe(1)  # Get the frame where exception was raised
        is_simple = frame in self.simple_frames
        is_active = frame in self.active_frames

        if is_active or is_simple:
            if not self._logic.inside_unwanted_frame(frame):
                self._logic.handle_exception(type(exc), exc, frame, is_simple=is_simple)

    def handle_exception_handled(self, _code, _offset, exc):
        """Handle EXCEPTION_HANDLED event"""
        frame = sys._getframe(1)  # Get the frame where exception was handled
        if frame in self.active_frames or frame in self.simple_frames:
            if not self._logic.inside_unwanted_frame(frame):
                self._logic.handle_exception_was_handled(frame)

    def handle_py_yield(self, _code, _offset, value):
        """Handle PY_YIELD event (generator yield)"""
        pass

    def handle_py_throw(self, _code, _offset, exc):
        """Handle PY_THROW event (generator throw)"""
        frame = sys._getframe(1)
        is_simple = frame in self.simple_frames
        is_active = frame in self.active_frames

        if is_active or is_simple:
            if not self._logic.inside_unwanted_frame(frame):
                self._logic.handle_exception(type(exc), exc, frame, is_simple=is_simple)

    def handle_py_unwind(self, *args):
        """Handle PY_UNWIND event (stack unwinding)"""
        frame = sys._getframe(1)
        is_simple = frame in self.simple_frames
        is_active = frame in self.active_frames

        if is_active or is_simple:
            for exception in self._logic.exception_chain:
                self._logic._add_to_buffer(exception[0], exception[1])
            self._logic.frame_cleanup(frame)
            if is_active:
                self.active_frames.discard(frame)
            if is_simple:
                self.simple_frames.discard(frame)
        self._logic.init_stack_variables()
        # These state updates must happen for ALL frames during unwind to keep state consistent.
        self._logic.exception_chain = []
        self._logic.decrement_stack_depth()
        self._logic.leave_unwanted_frame(frame)

    def _handle_reraise(self, _code, _offset, exc):
        """Handle RERAISE event (exception re-raised)"""
        frame = sys._getframe(1)
        is_simple = frame in self.simple_frames
        is_active = frame in self.active_frames

        if is_active or is_simple:
            if not self._logic.inside_unwanted_frame(frame):
                self._logic.handle_exception(type(exc), exc, frame, is_simple=is_simple)

    def handle_call(self, code: Any, offset: int, callable_obj: object, arg0: object) -> None:
        """Handles the CALL event, filtering for C-function calls."""
        # Python functions have a __code__ object, C functions/builtins do not.
        if hasattr(callable_obj, "__code__"):
            return  # This is a Python function, PY_START will handle it.

        # It's a C-call
        frame = sys._getframe(1)  # Caller's frame
        if not self.is_target_frame(frame):
            return

        self._logic.handle_c_call(frame, callable_obj, arg0)

    def handle_c_return(self, code: Any, offset: int, callable_obj: object, retval: object) -> None:
        """Handles the return from a C function."""
        # Python functions have a __code__ object, C functions/builtins do not.
        if hasattr(callable_obj, "__code__"):
            return  # This is a Python function, PY_START will handle it.

        # It's a C-call
        frame = sys._getframe(1)  # Caller's frame
        if not self.is_target_frame(frame):
            return

        # No need to check is_target_frame, assume we trace return if we trace call.
        self._logic.handle_c_return(frame, callable_obj, retval)

    def handle_c_raise(self, code: Any, offset: int, callable_obj: object, exception: BaseException) -> None:
        """Handles an exception raised from a C function."""
        # Python functions have a __code__ object, C functions/builtins do not.
        if hasattr(callable_obj, "__code__"):
            return  # This is a Python function, PY_START will handle it.

        # It's a C-call
        frame = sys._getframe(1)  # Caller's frame
        if not self.is_target_frame(frame):
            return
        self._logic.handle_c_raise(frame, callable_obj, exception)

    def is_target_frame(self, frame):
        """Check if frame matches target files"""
        if self.config.is_excluded_function(frame.f_code.co_name):
            return
        if frame.f_code.co_name.startswith("<genexpr>"):
            # one line code, ignore
            return False
        try:
            if not frame or not frame.f_code or not frame.f_code.co_filename:
                return False

            filename = frame.f_code.co_filename
            result = self.path_cache.get(filename, None)
            if result is not None:
                return result

            frame_path = Path(filename).resolve()
            matched = self.config.match_filename(str(frame_path))
            self.path_cache[filename] = matched
            return matched

        except (AttributeError, ValueError, OSError) as e:
            logging.debug("Frame check error: %s", str(e))
            return False

    def add_target_frame(self, frame):
        """Add a frame to be monitored"""
        if self.is_target_frame(frame):
            self.active_frames.add(frame)

    def start(self):
        """Start monitoring"""
        self._logic.start_flush_thread()
        self._logic.start()
        self._register_tool()

    def stop(self) -> Optional[Path]:
        """Stop monitoring and return report path"""
        self._unregister_tool()
        report_path = self._logic.stop()
        logging.info("⏹ DEBUG SESSION ENDED\n")
        print(color_wrap("\n⏹ 调试会话结束", TraceTypes.COLOR_RETURN))
        return report_path


class TraceLogExtractor:
    """
    日志提取器，用于从调试日志中查找特定文件和行号的日志信息
    工作原理：
    1. 读取日志索引文件(.index)查找匹配的行号和frame id
    2. 根据索引定位到日志文件中的起始和结束位置
    3. 提取该frame id对应的完整调用栈日志
    日志格式为JSON，结构如下：
    {
        "type": "call|return|line|exception",
        "filename": "文件名",
        "lineno": 行号,
        "frame_id": 帧ID,
        "func": "my_func",
    }
    """

    def __init__(self, log_file: str = None):
        """
        初始化日志提取器

        Args:
            log_file: 日志文件路径，默认为trace.log
        """
        self.log_file = log_file or str(TRACE_LOG_NAME)
        self.index_file = self.log_file + ".index"

    def _parse_index_line(self, line: str) -> tuple:
        """
        解析索引行，返回(type, filename, lineno, frame_id, position)元组

        Args:
            line: 索引文件中的一行

        Returns:
            (type, filename, lineno, frame_id, position, func) 元组
        """
        try:
            entry = json.loads(line.strip())
            if not isinstance(entry, dict) or "type" not in entry:
                return None
            return (
                entry["type"],
                entry["filename"],
                entry["lineno"],
                entry["frame_id"],
                entry["position"],
                entry.get("func", ""),  # 新增func字段返回
                entry.get("parent_frame_id", None),
            )
        except json.JSONDecodeError:
            return None

    def lookup(self, filename: str, lineno: int, start_from_func=None) -> list:
        """
        查找指定文件和行号的日志信息

        Args:
            filename: 文件名
            lineno: 行号

        Returns:
            匹配的日志行列表(JSON格式)和调用链参考信息
        """
        target_frame_id = None
        pair = []
        start_position = None
        references_group = []
        references = []
        frame_call_start = {}
        prev_call = None
        with open(self.index_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parsed = self._parse_index_line(line)
                if not parsed:
                    continue
                type_tag, file, line_no, frame_id, position, func, parent_frame_id = parsed
                if type_tag == TraceTypes.CALL:
                    frame_call_start[frame_id] = position
                # 收集调用链参考信息
                if target_frame_id is not None and type_tag in (
                    TraceTypes.CALL,
                    TraceTypes.RETURN,
                    TraceTypes.EXCEPTION,
                ):
                    references.append(
                        {
                            "filename": file,
                            "lineno": line_no,
                            "func": func,
                            "type": type_tag,
                        }
                    )
                if file == filename and line_no == lineno and type_tag == TraceTypes.CALL:
                    target_frame_id = frame_id
                    if parent_frame_id in frame_call_start:
                        start_position = frame_call_start[parent_frame_id]
                    else:
                        start_position = position
                    if start_from_func and prev_call:
                        (
                            prev_type_tag,
                            prev_file,
                            prev_line_no,
                            prev_frame_id,
                            prev_position,
                            prev_func,
                            prev_parent_frame_id,
                        ) = prev_call
                        references.append(
                            {
                                "filename": prev_file,
                                "lineno": prev_line_no,
                                "func": prev_func,
                                "type": prev_type_tag,
                            }
                        )
                        start_position = prev_position
                    references.append(
                        {
                            "filename": file,
                            "lineno": line_no,
                            "func": func,
                            "type": type_tag,
                        }
                    )
                    continue
                if (
                    target_frame_id is not None
                    and target_frame_id == frame_id
                    and type_tag in (TraceTypes.RETURN, TraceTypes.EXCEPTION)
                ):
                    print("找到匹配的返回/异常")
                    pair.append((start_position, position))
                    if references:
                        references_group.append(references)
                    references = []
                    start_position = None
                    target_frame_id = None
                if start_from_func and func in start_from_func:
                    if type_tag == TraceTypes.CALL:
                        prev_call = parsed
        if not pair:
            return [], []

        logs = []
        for start, end in pair:
            with open(self.log_file, "r", encoding="utf-8") as f:
                f.seek(start)
                log_lines = []
                while f.tell() <= end:
                    line = f.readline()
                    if line.startswith("#"):
                        continue
                    log_lines.append(line)
                logs.append("".join(log_lines))
        return logs, references_group


class TraceLogic:
    class _FileCache:
        def __init__(self):
            self._file_name_cache = {}
            self._trace_expressions = defaultdict(dict)
            self._ast_cache = {}
            self._var_ops_cache = {}

    class _FrameData:
        def __init__(self):
            self._frame_locals_map = {}
            self._code_var_ops = {}
            self._frame_id_map = {}
            self._current_frame_id = 0

    class _OutputHandlers:
        def __init__(self, parent: "TraceLogic"):
            self._output_handlers = {
                "console": parent._console_output,
                "file": parent._file_output,
                "html": parent._html_output,
            }
            self._active_outputs = set(["html", "file"])
            self._log_file = None
            self._log_file_index = None

    def __init__(self, config: TraceConfig):
        """初始化实例属性"""
        self.config = config
        self._log_queue = queue.Queue()
        self._flush_event = threading.Event()
        self._timer_thread = None
        self._running_flag = False
        self._html_render = CallTreeHtmlRender(self)
        self._stack_variables = {}
        self._message_id = 0
        self.exception_chain = []
        self._seen_thread_ids: Set[int] = set()
        # 分组属性
        self._file_cache = self._FileCache()
        self._frame_data = self._FrameData()
        self._output = self._OutputHandlers(self)
        self._last_vars_by_frame = {}  # Cache for tracking variable changes
        self.enable_output("file", filename=str(Path(_LOG_DIR) / Path(self.config.report_name).stem) + ".log")
        if self.config.disable_html:
            self.disable_output("html")
        self._local = threading.local()
        self.init_stack_variables()

    def init_stack_variables(self):
        """初始化线程本地堆栈变量"""
        if not hasattr(self._local, "stack_depth"):
            self._local.stack_depth = 0
        if not hasattr(self._local, "bad_frame"):
            self._local.bad_frame = None
        if not hasattr(self._local, "last_message"):
            self._local.last_message = None

    def maybe_unwanted_frame(self, frame):
        if frame.f_code.co_name in self.config.exclude_functions and self._local.bad_frame is None:
            self._local.bad_frame = self.get_or_reuse_frame_id(frame)

    def leave_unwanted_frame(self, frame):
        if self.get_or_reuse_frame_id(frame) == self._local.bad_frame:
            self._local.bad_frame = None

    def inside_unwanted_frame(self, frame):
        return self._local.bad_frame is not None

    def decrement_stack_depth(self):
        """减少堆栈深度（用于异常退出时调用）"""
        self._local.stack_depth = max(0, self._local.stack_depth - 1)

    def get_or_reuse_frame_id(self, frame):
        """获取或为帧分配一个唯一的、持久的ID。"""
        frame_key = id(frame)
        if frame_key not in self._frame_data._frame_id_map:
            self._frame_data._current_frame_id += 1
            self._frame_data._frame_id_map[frame_key] = self._frame_data._current_frame_id
        return self._frame_data._frame_id_map[frame_key]

    def _remove_frame_id(self, frame):
        """移除帧的ID映射（用于异常退出时调用）"""
        frame_key = id(frame)
        if frame_key in self._frame_data._frame_id_map:
            del self._frame_data._frame_id_map[frame_key]

    def enable_output(self, output_type: str, **kwargs):
        """启用特定类型的输出"""
        if output_type == "file" and "filename" in kwargs:
            try:
                # 使用with语句确保文件正确关闭
                self._output._log_file = open(kwargs["filename"], "w+", encoding="utf-8")
                self._output._log_file_index = open(str(kwargs["filename"]) + ".index", "w+", encoding="utf-8")
            except (IOError, OSError, PermissionError) as e:
                logging.error("无法打开日志文件: %s", str(e))
                raise
        self._output._active_outputs.add(output_type)

    def disable_output(self, output_type: str):
        """禁用特定类型的输出"""
        if output_type == "file" and self._output._log_file:
            try:
                self._output._log_file.close()
                self._output._log_file_index.close()
            except (IOError, OSError) as e:
                logging.error("关闭日志文件时出错: %s", str(e))
            finally:
                self._output._log_file = None
        self._output._active_outputs.discard(output_type)

    def _console_output(self, log_data, color_type):
        """控制台输出处理"""
        message = self._format_log_message(log_data)
        if isinstance(log_data, dict) and "data" in log_data:
            thread_id = log_data["data"].get("thread_id")
            # 当有多于一个线程时，才显示线程ID
            if thread_id and len(self._seen_thread_ids) > 1:
                # 移除消息原有的缩进，统一添加
                message_stripped = message.lstrip()
                indent_len = len(message) - len(message_stripped)
                indent = " " * indent_len
                tid_badge = f"[TID:{thread_id}]"
                message = f"{indent}{tid_badge} {message_stripped}"

        colored_msg = color_wrap(message, color_type)
        print(colored_msg)

    def write_log_index(self, log_type, log_data, position):
        """写入日志索引"""
        data = log_data["data"]
        index_entry = {
            "type": log_type,
            "filename": data["original_filename"],
            "lineno": data.get("lineno", 0),
            "frame_id": data["frame_id"],
            "position": position,
            "func": data.get("func", ""),
            "parent_frame_id": data.get("parent_frame_id", 0),
        }
        self._output._log_file_index.write(json.dumps(index_entry) + "\n")

    def _file_output(self, log_data, log_type):
        """文件输出处理"""
        if self._output._log_file:
            msg = self._format_log_message(log_data)
            if log_type == TraceTypes.CALL:
                position = self._output._log_file.tell()
                self.write_log_index(log_type, log_data, position)
            self._output._log_file.write(msg + "\n")
            if log_type in (TraceTypes.RETURN, TraceTypes.EXCEPTION):
                position = self._output._log_file.tell()
                self.write_log_index(log_type, log_data, position)

    def _html_output(self, log_data, color_type):
        """HTML输出处理"""
        self._html_render.add_raw_message(log_data, color_type)

    def _format_log_message(self, log_data):
        """格式化日志消息"""
        if isinstance(log_data, str):
            return log_data
        return log_data["template"].format(**log_data["data"])

    def _add_to_buffer(self, log_data, color_type):
        """将日志数据添加到队列并立即处理"""
        if isinstance(log_data, dict) and "data" in log_data:
            thread_id = log_data["data"].get("thread_id")
            if thread_id is not None:
                self._seen_thread_ids.add(thread_id)
        self._log_queue.put((log_data, color_type))

    def _flush_buffer(self):
        """刷新队列，输出所有日志"""
        while not self._log_queue.empty():
            try:
                log_data, color_type = self._log_queue.get_nowait()
                for output_type in self._output._active_outputs:
                    if output_type in self._output._output_handlers:
                        self._output._output_handlers[output_type](log_data, color_type)
            except queue.Empty:
                break

    def _flush_scheduler(self):
        """定时刷新调度器"""
        while self._running_flag:
            time.sleep(1)
            self._flush_buffer()

    def _get_formatted_filename(self, filename: str) -> str:
        """
        获取格式化后的文件名。
        - 如果设置了 source_base_dir，则尝试生成相对于该目录的路径。
        - 如果文件不在 source_base_dir 内，则显示绝对路径。
        - 如果未设置 source_base_dir，则回退到旧的简化逻辑。
        """
        if filename in self._file_cache._file_name_cache:
            return self._file_cache._file_name_cache[filename]

        try:
            # 处理<string>等非文件路径的特殊情况
            if filename.startswith("<") and filename.endswith(">"):
                self._file_cache._file_name_cache[filename] = filename
                return filename

            file_path = Path(filename).resolve()

            if self.config.source_base_dir:
                try:
                    base_dir = self.config.source_base_dir.resolve()
                    # 如果 file_path 在 base_dir 内，则使用相对路径
                    formatted = str(file_path.relative_to(base_dir))
                except (ValueError, OSError):
                    # 否则，使用绝对路径
                    formatted = str(file_path)
            else:
                formatted = to_relative_module_path(filename)

            self._file_cache._file_name_cache[filename] = formatted
            return formatted
        except (TypeError, ValueError, OSError) as e:
            logging.warning("文件名格式化失败: %s, 错误: %s", filename, str(e))
            self._file_cache._file_name_cache[filename] = filename
            return filename

    def _parse_trace_comment(self, line):
        """解析追踪注释"""
        comment_pos = line.rfind("#")
        if comment_pos == -1:
            return None
        start_tag = "trace:"
        comment = line[comment_pos + 1 :].strip()
        if not comment.lower().startswith(start_tag):
            return None

        return comment[len(start_tag) :].strip()

    def _get_trace_expression(self, filename, lineno):
        """获取缓存的追踪表达式"""
        if filename not in self._file_cache._trace_expressions:
            return None
        return self._file_cache._trace_expressions[filename].get(lineno)

    def _cache_trace_expression(self, filename, lineno, expr):
        """缓存追踪表达式"""
        if filename not in self._file_cache._trace_expressions:
            self._file_cache._trace_expressions[filename] = {}
        self._file_cache._trace_expressions[filename][lineno] = expr

    def _compile_expr(self, expr):
        """编译表达式并缓存结果"""
        if expr in self._file_cache._ast_cache:
            return self._file_cache._ast_cache[expr]
        node = ast.parse(expr, mode="eval")
        compiled = compile(node, "<string>", "eval")
        self._file_cache._ast_cache[expr] = (node, compiled)
        return node, compiled

    def handle_call(self, frame, is_simple: bool = False):
        """增强参数捕获逻辑"""
        self.init_stack_variables()
        self._process_message_with_vars(frame, None, None)

        try:
            is_safe = self.config.should_skip_vars(frame.f_code.co_filename, frame.f_lineno)
            args_info = []
            if frame.f_code.co_name == "<module>":
                log_prefix = TraceTypes.PREFIX_MODULE
            else:
                try:
                    value = inspect.getargvalues(frame)
                    args, _, _, values = value
                    args_to_show = [arg for arg in args if arg not in ("self", "cls")]
                except (TypeError, IndexError):
                    args = []
                    values = {}
                    args_to_show = []
                args_info = [f"{arg}={truncate_repr_value(values[arg], safe=is_safe)}" for arg in args_to_show]
                log_prefix = TraceTypes.PREFIX_CALL

            parent_frame = frame.f_back
            parent_lineno = 0
            if parent_frame is not None:
                parent_frame_id = self.get_or_reuse_frame_id(parent_frame)
                parent_lineno = parent_frame.f_lineno
            else:
                parent_frame_id = 0
            filename = self._get_formatted_filename(frame.f_code.co_filename)
            frame_id = self.get_or_reuse_frame_id(frame)
            self._frame_data._frame_locals_map[frame_id] = frame.f_locals
            self._add_to_buffer(
                {
                    "template": "{indent}↘ {prefix} {filename}:{lineno} {func}({args}) [frame:{frame_id}][thread:{thread_id}]",
                    "data": {
                        "indent": _INDENT * self._local.stack_depth,
                        "prefix": log_prefix,
                        "filename": filename,
                        "original_filename": frame.f_code.co_filename,
                        "lineno": frame.f_lineno,
                        "func": frame.f_code.co_name,
                        "args": ", ".join(args_info),
                        "frame_id": frame_id,
                        "parent_frame_id": parent_frame_id,
                        "caller_lineno": parent_lineno,
                        "thread_id": threading.get_native_id(),
                    },
                },
                TraceTypes.COLOR_CALL,
            )
            self._local.stack_depth += 1

        except (AttributeError, TypeError) as e:
            traceback.print_exc()
            logging.error("Call logging error: %s", str(e))
            self._add_to_buffer(
                {"template": "⚠ 记录调用时出错: {error}", "data": {"error": str(e)}},
                TraceTypes.ERROR,
            )

    def frame_cleanup(self, frame):
        frame_id = self.get_or_reuse_frame_id(frame)
        if frame_id in self._frame_data._frame_locals_map:
            del self._frame_data._frame_locals_map[frame_id]
        if frame_id in self._last_vars_by_frame:
            del self._last_vars_by_frame[frame_id]  # Clean up var cache
        self._remove_frame_id(frame)

    def handle_return(self, frame, return_value, is_simple: bool = False):
        """增强返回值记录"""
        is_safe = self.config.should_skip_vars(frame.f_code.co_filename, frame.f_lineno)
        return_str = truncate_repr_value(return_value, safe=is_safe)
        filename = self._get_formatted_filename(frame.f_code.co_filename)
        frame_id = self.get_or_reuse_frame_id(frame)
        log_prefix = TraceTypes.PREFIX_RETURN

        log_data = {
            "template": "{indent}↗ {prefix} {filename} {func}() → {return_value} [frame:{frame_id}]",
            "data": {
                "indent": _INDENT * (self._local.stack_depth - 1),
                "prefix": log_prefix,
                "filename": filename,
                "lineno": frame.f_lineno,
                "return_value": return_str,
                "frame_id": frame_id,
                "func": frame.f_code.co_name,
                "original_filename": frame.f_code.co_filename,
                "thread_id": threading.get_native_id(),
                "tracked_vars": {},
            },
        }
        # 使用统一的方法处理消息
        self._process_message_with_vars(frame, log_data, TraceTypes.COLOR_RETURN)
        self._local.stack_depth = max(0, self._local.stack_depth - 1)

    def _get_var_ops(self, code_obj):
        """获取代码对象的变量操作分析结果"""
        if code_obj in self._file_cache._var_ops_cache:
            return self._file_cache._var_ops_cache[code_obj]

        from .variable_trace import analyze_variable_ops  # 导入分析函数

        analysis = analyze_variable_ops(code_obj)
        self._file_cache._var_ops_cache[code_obj] = analysis
        return analysis

    def _get_vars_in_range(self, code_obj, start_line, end_line):
        """获取给定代码对象在指定行范围内的所有唯一变量。"""
        if not self.config.enable_var_trace:
            return []

        if code_obj not in self._frame_data._code_var_ops:
            self._frame_data._code_var_ops[code_obj] = self._get_var_ops(code_obj)

        all_line_vars = self._frame_data._code_var_ops[code_obj]

        statement_vars = set()
        for i in range(start_line, end_line + 1):
            statement_vars.update(all_line_vars.get(i, set()))

        return list(statement_vars)

    def cache_eval(self, frame, expr):
        _, compiled = self._compile_expr(expr)
        return eval(compiled, frame.f_globals, frame.f_locals)  # nosec

    def trace_variables(self, frame, var_names):
        """
        Trace variables in the given frame, ignoring special/private ones.

        Args:
            frame: The current frame
            var_names: List of variable names to trace

        Returns:
            Dict[str, str]: Dictionary of variable names and their formatted values
        """
        tracked_vars = {}
        if not var_names:
            return tracked_vars

        is_safe = self.config.should_skip_vars(frame.f_code.co_filename, frame.f_lineno)

        # Filter out special (self, cls) and private (__var) variables
        vars_to_track = [
            v for v in var_names if v not in ("self", "cls") and not (v.startswith("__") and not v.endswith("__"))
        ]

        locals_dict = frame.f_locals
        globals_dict = frame.f_globals

        for var in vars_to_track:
            if var in locals_dict:
                value = locals_dict[var]
            elif var in globals_dict:
                value = globals_dict[var]
            else:
                try:
                    value = self.cache_eval(frame, var)  # nosec
                except (AttributeError, NameError, SyntaxError) as err:
                    continue
            tracked_vars[var] = truncate_repr_value(value, safe=is_safe)

        return tracked_vars

    def handle_line(self, frame):
        """处理行事件，现在能够感知多行语句，并只报告变化的变量。"""
        self.init_stack_variables()

        lineno = frame.f_lineno
        filename = frame.f_code.co_filename
        statement_info = get_statement_info(filename, lineno)
        if statement_info:
            full_statement, start_line, end_line = statement_info
            if end_line - start_line > 10:
                full_statement = "\n".join(full_statement.split("\n")[:10])
        else:
            full_statement = linecache.getline(filename, lineno).strip("\n")
            if not full_statement:
                return
            start_line = end_line = lineno

        if lineno != start_line:
            return

        formatted_filename = self._get_formatted_filename(filename)
        frame_id = self.get_or_reuse_frame_id(frame)
        self._message_id += 1

        indented_statement = full_statement.replace("\n", "\n" + _INDENT * (self._local.stack_depth + 1))

        log_data = {
            "idx": self._message_id,
            "template": "{indent}▷ {filename}:{lineno} {line}",
            "data": {
                "indent": _INDENT * self._local.stack_depth,
                "filename": formatted_filename,
                "lineno": start_line,
                "line": indented_statement,
                "raw_line": full_statement,
                "frame_id": frame_id,
                "original_filename": filename,
                "tracked_vars": {},
                "thread_id": threading.get_native_id(),
            },
        }
        if self.config.enable_var_trace:
            current_statement_vars = self._get_vars_in_range(frame.f_code, start_line, end_line)
        else:
            current_statement_vars = None
        # 使用统一的方法处理消息
        self._process_message_with_vars(
            frame, log_data, TraceTypes.COLOR_LINE, vars_to_delay_eval=current_statement_vars
        )

        for i, line_content in enumerate(full_statement.split("\n")):
            current_line_no = start_line + i
            self._process_trace_expression(frame, line_content, filename, current_line_no)

        if self.config.capture_vars:
            self._process_captured_vars(frame)

    def handle_opcode(self, frame, opcode, name, value):
        if self.config.disable_html:
            return
        self._html_render.add_stack_variable_create(self._message_id, opcode, name, value)

    def _process_message_with_vars(
        self,
        frame: types.FrameType,
        log_data: Optional[Dict[str, Any]],
        color_type: Optional[str],
        vars_to_delay_eval: Optional[List[str]] = None,
        is_exception: bool = False,
    ) -> None:
        """
        处理日志消息，包括刷新延迟消息和处理当前消息。

        此方法是事件处理的核心，它确保在处理新事件（如CALL或RETURN）之前，
        与前一行代码相关的延迟消息会被正确地处理和记录。

        Args:
            frame: 当前事件的帧对象。
            log_data: 当前事件的日志数据，或为None（用于仅刷新）。
            color_type: 当前事件的颜色类型。
            vars_to_delay_eval: 如果提供了变量列表，则当前消息将被延迟处理。
                                 否则，它将被立即处理。
            is_exception: 标志当前事件是否是异常。
        """
        # 1. 首先处理任何待处理的延迟消息
        if self._local.last_message:
            pending_data, pending_color, pending_frame, pending_vars = self._local.last_message
            self._local.last_message = None
            # 使用正确的帧（pending_frame）来评估变量
            if pending_vars:
                all_traced_vars = self.trace_variables(pending_frame, pending_vars)
                if all_traced_vars:
                    pending_data["template"] += " # Debug: {vars}"
                    # 展开f-string以避免潜在问题
                    var_strings = []
                    for k, v in all_traced_vars.items():
                        # 替换换行符并添加注释前缀
                        formatted_value = v.replace("\n", "\n#")
                        var_strings.append(k + "=" + formatted_value)
                    pending_data["data"]["vars"] = ", ".join(var_strings)
                    pending_data["data"]["tracked_vars"] = all_traced_vars
            self._add_to_buffer(pending_data, pending_color)

        # 2. 异常处理前确保处理完所有延迟消息
        if is_exception:
            if log_data:
                self.exception_chain.append((log_data, color_type))
            return  # 不要进一步处理

        # 3. 处理当前消息
        if not log_data:
            return  # 这是仅刷新的情况，例如来自 handle_call

        if vars_to_delay_eval is not None:
            # 延迟当前消息（通常是行事件）
            self._local.last_message = (log_data, color_type, frame, vars_to_delay_eval)
        else:
            # 立即处理不需要延迟变量评估的消息（调用/返回等）
            self._add_to_buffer(log_data, color_type)

    def _process_trace_expression(self, frame, line, filename, lineno):
        """处理追踪表达式"""
        cached_expr = self._get_trace_expression(filename, lineno)
        if not cached_expr:
            cached_expr = self._parse_trace_comment(line)
            self._file_cache._trace_expressions[filename][lineno] = cached_expr
        if not cached_expr:
            return
        try:
            value = self.cache_eval(frame, cached_expr)  # 预编译表达式
        except (AttributeError, NameError, SyntaxError) as e:
            value = f"<Failed to evaluate: {str(e)}>"

        is_safe = self.config.should_skip_vars(filename, lineno)
        formatted = truncate_repr_value(value, safe=is_safe)
        self._add_to_buffer(
            {
                "template": "{indent}↳ Debug Statement {expr}={value} [frame:{frame_id}]",
                "data": {
                    "indent": _INDENT * (self._local.stack_depth),
                    "expr": cached_expr,
                    "value": formatted,
                    "frame_id": self.get_or_reuse_frame_id(frame),
                },
            },
            TraceTypes.COLOR_TRACE,
        )

    def _process_captured_vars(self, frame):
        """处理捕获的变量"""
        captured_vars = self.capture_variables(frame)
        if captured_vars:
            self._add_to_buffer(
                {
                    "template": "{indent}↳ 变量: {vars} [frame:{frame_id}]",
                    "data": {
                        "indent": _INDENT * (self._local.stack_depth + 1),
                        "vars": ", ".join(f"{k}={v}" for k, v in captured_vars.items()),
                        "frame_id": self.get_or_reuse_frame_id(frame),
                    },
                },
                TraceTypes.COLOR_VAR,
            )

    def handle_exception(self, exc_type, exc_value, frame, is_simple: bool = False):
        """
        记录异常信息。
        对于 sys.monitoring，此方法会将异常事件暂存到 exception_chain 中，
        以区分最终被捕获的异常和导致函数终止的异常。
        """
        # 如果当前字节码是 SEND 且异常是 StopIteration，则不算异常
        # 如果当前字节码是 END_ASYNC_FOR 且异常是 StopAsyncIteration，则不算异常
        if exc_type in (StopIteration, StopAsyncIteration):
            current_offset = frame.f_lasti
            target_op = "SEND" if exc_type is StopIteration else "END_ASYNC_FOR"
            for instr in dis.get_instructions(frame.f_code):
                if instr.offset == current_offset and instr.opname == target_op:
                    return

        # 初始化线程本地堆栈深度
        self.init_stack_variables()

        filename = self._get_formatted_filename(frame.f_code.co_filename)
        lineno = frame.f_lineno
        frame_id = self.get_or_reuse_frame_id(frame)
        log_prefix = TraceTypes.PREFIX_EXCEPTION
        # 同一个frame, 不会重复抛出两个exception， 要么handled, 要么unwind, 要么finally reraise
        if len(self.exception_chain) > 0:
            if self.exception_chain[-1][0]["data"]["frame_id"] == frame_id:
                return
        log_data = {
            "template": (
                "{indent}⚠ {prefix} IN {func} AT {filename}:{lineno} {exc_type}: {exc_value} [frame:{frame_id}]"
            ),
            "data": {
                "indent": _INDENT * (self._local.stack_depth - 1),
                "prefix": log_prefix,
                "filename": filename,
                "lineno": lineno,
                "exc_type": exc_type.__name__,
                "exc_value": str(exc_value),
                "frame_id": frame_id,
                "func": frame.f_code.co_name,
                "original_filename": frame.f_code.co_filename,
                "thread_id": threading.get_native_id(),
                "tracked_vars": {},
            },
        }

        # 对于 sys.monitoring 模式，需要特殊处理
        if sys.version_info >= (3, 12):
            self._process_message_with_vars(frame, log_data, TraceTypes.COLOR_EXCEPTION, is_exception=True)
        else:
            # 对于非 sys.monitoring 模式，直接处理
            self._process_message_with_vars(frame, log_data, TraceTypes.COLOR_EXCEPTION, is_exception=True)

    def handle_exception_was_handled(self, frame):
        """
        当一个异常被 `try...except` 块捕获时调用此方法。
        这是 sys.monitoring 的 EXCEPTION_HANDLED 事件的钩子。
        """
        # 初始化线程本地堆栈深度
        self.init_stack_variables()

        if len(self.exception_chain) > 0:
            # 最近引发的异常就是被处理的那个, 不算数
            self.exception_chain.pop()
        # 不再恢复堆栈深度，因为异常被捕获时不减少

    def handle_c_call(self, frame: Any, callable_obj: object, arg0: object) -> None:
        """Handles a call to a C function."""
        self.init_stack_variables()

        try:
            func_name = callable_obj.__name__
        except AttributeError:
            func_name = repr(callable_obj)

        is_safe = self.config.should_skip_vars(frame.f_code.co_filename, frame.f_lineno)
        self._add_to_buffer(
            {
                "template": "{indent}↘ C-CALL {func_name}({arg0}) at {filename}:{lineno} [frame:{frame_id}][thread:{thread_id}]",
                "data": {
                    "indent": _INDENT * self._local.stack_depth,
                    "func_name": func_name,
                    "arg0": truncate_repr_value(arg0, safe=is_safe),
                    "filename": self._get_formatted_filename(frame.f_code.co_filename),
                    "lineno": frame.f_lineno,
                    "original_filename": frame.f_code.co_filename,
                    "frame_id": self.get_or_reuse_frame_id(frame),
                    "thread_id": threading.get_native_id(),
                },
            },
            TraceTypes.COLOR_TRACE,
        )
        self._local.stack_depth += 1

    def handle_c_return(self, frame: Any, callable_obj: object, arg0: object) -> None:
        """Handles the return from a C function."""
        self.init_stack_variables()
        self._local.stack_depth = max(0, self._local.stack_depth - 1)

        try:
            func_name = callable_obj.__name__
        except AttributeError:
            func_name = repr(callable_obj)

        self._add_to_buffer(
            {
                "template": "{indent}↗ C-RETURN from {func_name} [frame:{frame_id}][thread:{thread_id}]",
                "data": {
                    "indent": _INDENT * self._local.stack_depth,
                    "func_name": func_name,
                    "original_filename": frame.f_code.co_filename,
                    "lineno": frame.f_lineno,
                    "frame_id": self.get_or_reuse_frame_id(frame),
                    "thread_id": threading.get_native_id(),
                },
            },
            TraceTypes.COLOR_TRACE,
        )

    def handle_c_raise(self, frame: Any, callable_obj: object, arg0: object) -> None:
        """Handles an exception raised from a C function."""
        self.init_stack_variables()
        self._local.stack_depth = max(0, self._local.stack_depth - 1)

        try:
            func_name = callable_obj.__name__
        except AttributeError:
            func_name = repr(callable_obj)
        self._add_to_buffer(
            {
                "template": "{indent}⚠ C-RAISE from {func_name} [frame:{frame_id}][thread:{thread_id}]",
                "data": {
                    "indent": _INDENT * self._local.stack_depth,
                    "func_name": func_name,
                    "original_filename": frame.f_code.co_filename,
                    "lineno": frame.f_lineno,
                    "frame_id": self.get_or_reuse_frame_id(frame),
                    "thread_id": threading.get_native_id(),
                },
            },
            TraceTypes.COLOR_EXCEPTION,
        )

    def capture_variables(self, frame):
        """捕获并计算变量表达式"""
        if not self.config.capture_vars:
            return {}

        try:
            locals_dict = frame.f_locals
            globals_dict = frame.f_globals
            results = {}
            is_safe = self.config.should_skip_vars(frame.f_code.co_filename, frame.f_lineno)

            for expr in self.config.capture_vars:
                try:
                    _, compiled = self._compile_expr(expr)
                    # 安全警告：eval使用是必要的调试功能
                    value = eval(compiled, globals_dict, locals_dict)  # nosec
                    formatted = truncate_repr_value(value, safe=is_safe)
                    results[expr] = formatted
                except (NameError, SyntaxError, TypeError, AttributeError) as e:
                    self._add_to_buffer(
                        {
                            "template": "表达式求值失败: {expr}, 错误: {error}",
                            "data": {"expr": expr, "error": str(e)},
                        },
                        TraceTypes.ERROR,
                    )
                    results[expr] = f"<求值错误: {str(e)}>"

            if self.config.callback:
                try:
                    self.config.callback(results)
                except (AttributeError, TypeError) as e:
                    logging.error("回调函数执行失败: %s", str(e))

            return results
        except (AttributeError, TypeError) as e:
            logging.error("变量捕获失败: %s", str(e))
            return {}

    def start_flush_thread(self):
        self._timer_thread = threading.Thread(target=self._flush_scheduler)
        self._timer_thread.daemon = True
        self._timer_thread.start()

    def start(self):
        """启动逻辑处理"""
        self._running_flag = True

    def stop(self) -> Optional[Path]:
        """
        停止逻辑处理, 返回最终报告路径
        """
        self._running_flag = False
        if self._timer_thread:
            self._timer_thread.join(timeout=1)

        self._flush_buffer()
        while not self._log_queue.empty():
            self._log_queue.get_nowait()
        self.disable_output("file")

        report_path = None
        if "html" in self._output._active_outputs:
            is_multi_threaded = len(self._seen_thread_ids) > 1
            report_path = self._html_render.save_to_file(self.config.report_name, is_multi_threaded)

        return report_path


def get_tracer(module_path, config: TraceConfig):
    # tracer_core_name = "tracer_core.pyd" if os.name == "nt" else "tracer_core.so"
    # tracer_core_path = os.path.join(os.path.dirname(__file__), tracer_core_name)
    # if os.path.exists(tracer_core_path):
    #     try:
    #         spec = importlib.util.spec_from_file_location("tracer_core", tracer_core_path)
    #         tracer_core = importlib.util.module_from_spec(spec)
    #         spec.loader.exec_module(tracer_core)
    #         trace_dispatcher = tracer_core.TraceDispatcher
    #         return trace_dispatcher(str(module_path), TraceLogic(config), config)
    #     except Exception as e:
    #         logging.error("💥 DEBUGGER IMPORT ERROR: %s", str(e))
    #         print(
    #             color_wrap(
    #                 f"❌ 调试器导入错误: {str(e)}\n{traceback.format_exc()}",
    #                 TraceTypes.COLOR_ERROR,
    #             )
    #         )
    #         raise
    return None


def start_line_trace(exclude: List[str] = None):
    """
    exclude: 排除的函数列表
    """
    return start_trace(
        config=TraceConfig(
            target_files=[sys._getframe().f_back.f_code.co_filename],
            exclude_functions=exclude,
        )
    )


def start_trace(module_path=None, config: TraceConfig = None, **kwargs):
    """启动调试跟踪会话

    Args:
        module_path: 目标模块路径(可选)
        config: 跟踪配置实例(可选)
    """
    if not config:
        if "report_name" not in kwargs:
            log_name = sys._getframe().f_back.f_code.co_name
            report_name = log_name + ".html"
            kwargs["report_name"] = report_name
        if not kwargs.get("target_files"):
            kwargs["target_files"] = [sys._getframe().f_back.f_code.co_filename]
        config = TraceConfig(
            **kwargs,
        )
    tracer = None
    tracer = get_tracer(module_path, config)
    if not tracer:
        if sys.version_info >= (3, 12):
            tracer = SysMonitoringTraceDispatcher(str(module_path), config)
        else:
            tracer = TraceDispatcher(str(module_path), config)
            # 为旧版Python设置线程跟踪
            threading.settrace(tracer.trace_dispatch)

    caller_frame = sys._getframe().f_back
    tracer.add_target_frame(caller_frame)
    try:
        if tracer:
            tracer.start()
        caller_frame.f_trace_lines = True
        caller_frame.f_trace_opcodes = True
        return tracer
    except Exception as e:
        logging.error("💥 DEBUGGER INIT ERROR: %s\n%s", str(e), traceback.format_exc())
        print(
            color_wrap(
                f"❌ 调试器初始化错误: {str(e)}\n{traceback.format_exc()}",
                TraceTypes.COLOR_ERROR,
            )
        )
        raise


class TraceContext:
    """
    一个用于代码块的跟踪上下文管理器。

    使用 'with' 语句来包裹需要跟踪的代码块。

    用法:
        config = TraceConfig(...)
        with TraceContext(config):
            # 这里的代码将被跟踪
            my_function()
    """

    def __init__(self, config: TraceConfig):
        self.config = config
        self.tracer = None

    def __enter__(self):
        print(color_wrap("[tracer] 进入跟踪上下文...", TraceTypes.COLOR_CALL))
        self.tracer = start_trace(config=self.config)
        return self.tracer

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.tracer:
            print(color_wrap("[tracer] ...退出跟踪上下文", TraceTypes.COLOR_RETURN))
            stop_trace(self.tracer)
        # 如果有异常，不抑制它，让它正常传播
        return False


def trace(
    target_files: Optional[List[str]] = None,
    line_ranges: Optional[Dict[str, List[Tuple[int, int]]]] = None,
    skip_vars_on_lines: Optional[List[Dict[str, Any]]] = None,
    capture_vars: Optional[List[str]] = None,
    callback: Optional[callable] = None,
    report_name: str = _DEFAULT_REPORT_NAME,
    exclude_functions: Optional[List[str]] = None,
    enable_var_trace: bool = False,
    ignore_self: bool = True,
    ignore_system_paths: bool = True,
    start_function: Optional[Tuple[str, int]] = None,
    source_base_dir: Optional[Path] = None,
    disable_html: bool = False,
    include_stdlibs: Optional[List[str]] = None,
    trace_c_calls: bool = False,
):
    """函数跟踪装饰器

    Args:
        target_files: 目标文件模式列表，支持通配符
        line_ranges: 文件行号范围字典，key为文件名，value为 (start_line, end_line) 元组列表
        skip_vars_on_lines: 跳过变量捕获的规则列表
        capture_vars: 要捕获的变量表达式列表
        callback: 变量捕获时的回调函数
        report_name: 报告文件名
        exclude_functions: 要排除的函数名列表
        enable_var_trace: 是否启用变量操作跟踪
        ignore_self: 是否忽略跟踪器自身
        ignore_system_paths: 是否忽略系统路径和第三方包路径
        start_function: 起始函数
        source_base_dir: 源代码根目录，用于在报告中显示相对路径
        disable_html: 是否禁用HTML报告
        include_stdlibs: 同时trace一些标准库模块 ["unittest"] 比如
        trace_c_calls: 是否启用C函数调用跟踪
    """
    if not target_files:
        try:
            target_files = [sys._getframe(1).f_code.co_filename]
        except (ValueError, AttributeError):
            target_files = []

    def decorator(func):
        # 创建通用的配置
        # 防御性处理：某些函数对象可能没有 __code__ 属性（如 C 扩展函数）
        target_file = getattr(func, "__code__", None)
        if target_file is not None:
            target_file = target_file.co_filename
        else:
            # 如果无法获取源文件名，则使用模块名或者默认值
            target_file = getattr(func, "__file__", "<unknown>")

        config = TraceConfig(
            target_files=target_files or [target_file],
            line_ranges=line_ranges,
            skip_vars_on_lines=skip_vars_on_lines,
            capture_vars=capture_vars,
            callback=callback,
            report_name=report_name,
            exclude_functions=exclude_functions,
            enable_var_trace=enable_var_trace,
            ignore_self=ignore_self,
            ignore_system_paths=ignore_system_paths,
            start_function=start_function,
            source_base_dir=source_base_dir,
            disable_html=disable_html,
            include_stdlibs=include_stdlibs,
            trace_c_calls=trace_c_calls,
        )
        # 您在文件中添加的 pdb.set_trace()，保留它以便您调试，生产时可移除

        # 检查是否为异步函数
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                print(color_wrap("[start async tracer]", TraceTypes.COLOR_CALL))
                t = start_trace(config=config)
                try:
                    # 使用 await 来正确执行协程，确保在协程执行期间跟踪是活动的
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    # 协程执行完毕后，再停止跟踪
                    if t:
                        print(color_wrap("[stop async tracer]", TraceTypes.COLOR_RETURN))
                        stop_trace(t)

            return async_wrapper

        # 检查是否为生成器函数
        elif inspect.isgeneratorfunction(func):

            @functools.wraps(func)
            def generator_wrapper(*args, **kwargs):
                print(color_wrap("[start generator tracer]", TraceTypes.COLOR_CALL))
                t = start_trace(config=config)
                try:
                    # 使用 yield from 来代理生成器的产出
                    # 这会使 try...finally 的生命周期覆盖整个生成器的迭代过程
                    yield from func(*args, **kwargs)
                finally:
                    # 生成器迭代结束后，再停止跟踪
                    if t:
                        print(color_wrap("[stop generator tracer]", TraceTypes.COLOR_RETURN))
                        stop_trace(t)

            return generator_wrapper

        # 默认是普通的同步函数
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                print(color_wrap("[start sync tracer]", TraceTypes.COLOR_CALL))
                t = start_trace(config=config)
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    if t:
                        print(color_wrap("[stop sync tracer]", TraceTypes.COLOR_RETURN))
                        stop_trace(t)

            return sync_wrapper

    return decorator


def stop_trace(tracer: Union[TraceDispatcher, SysMonitoringTraceDispatcher] = None):
    """停止调试跟踪并清理资源

    Args:
        tracer: 可选的跟踪器实例
    """
    report_path = None
    if tracer:
        report_path = tracer.stop()

    if sys.version_info < (3, 12):
        threading.settrace(None)

    return report_path
