import ast
import fnmatch
import inspect
import linecache
import logging
import queue
import sys
import threading
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import yaml

_MAX_VALUE_LENGTH = 100
_INDENT = "  "
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_NAME = _LOG_DIR / "debug.log"
_MAX_LINE_REPEAT = 5
_STACK_TRACK_INTERVAL = 0.1
_MAX_CALL_DEPTH = 20
_COLORS = {
    "call": "\033[92m",  # 绿色
    "return": "\033[94m",  # 蓝色
    "var": "\033[93m",  # 黄色
    "line": "\033[0m",  # 白色
    "error": "\033[91m",  # 红色
    "reset": "\033[0m",
}

logging.basicConfig(
    filename=str(_LOG_NAME),
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
    filemode="w",
)


class TraceConfig:
    """调试跟踪配置类"""

    def __init__(
        self,
        target_files: List[str] = None,
        line_ranges: Dict[str, List[Tuple[int, int]]] = None,
        capture_vars: List[str] = None,
        callback: Optional[callable] = None,
    ):
        """
        初始化跟踪配置

        Args:
            target_files: 目标文件模式列表，支持通配符
            line_ranges: 文件行号范围字典，key为文件名，value为 (start_line, end_line) 元组列表
            capture_vars: 要捕获的变量表达式列表
            callback: 变量捕获时的回调函数
        """
        self.target_files = target_files or []
        self.line_ranges = self._parse_line_ranges(line_ranges or {})
        self.capture_vars = capture_vars or []
        self.callback = callback
        self._compiled_patterns = [fnmatch.translate(pattern) for pattern in self.target_files]

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
            capture_vars=config_data.get("capture_vars", []),
            callback=config_data.get("callback", None),
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
            except Exception as e:
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

    def match_filename(self, filename: str) -> bool:
        """检查文件路径是否匹配目标文件模式"""
        if not self.target_files:
            return True
        filename_posix = Path(filename).as_posix()
        return any(fnmatch.fnmatch(filename_posix, pattern) for pattern in self.target_files)


def _truncate_value(value):
    """智能截断保留关键类型信息"""
    try:
        if isinstance(value, (list, tuple)):
            preview = f"{type(value).__name__}(len={len(value)})"
        elif isinstance(value, dict):
            keys = list(value.keys())[:3]
            preview = f"dict(keys={keys}...)" if len(value) > 3 else f"dict({value})"
        elif hasattr(value, "__dict__"):
            attrs = list(vars(value).keys())[:3]
            preview = f"{type(value).__name__}({attrs}...)"
        else:
            preview = repr(value)
    except (AttributeError, TypeError, ValueError):
        preview = "<unrepresentable>"

    if len(preview) > _MAX_VALUE_LENGTH:
        return preview[:_MAX_VALUE_LENGTH] + "..."
    return preview


def _color_wrap(text, color_type):
    """包装颜色但不影响日志文件"""
    return f"{_COLORS[color_type]}{text}{_COLORS['reset']}" if sys.stdout.isatty() else text


class TraceCore:
    def __init__(self, target_path, config: TraceConfig, immediate_trace=False):
        """
        初始化跟踪核心

        Args:
            target_path: 目标文件路径
            config: 跟踪配置实例
            immediate_trace: 是否立即开始跟踪
        """
        try:
            self.target_path = Path(target_path).resolve(strict=True)
        except FileNotFoundError:
            logging.error("Target path not found: %s\n%s", target_path, traceback.format_exc())
            raise
        self.in_target = False
        self.stack_depth = 0
        self.line_counter = {}
        self.last_locals = {}
        self._active_frames = set()
        self._last_log_time = {}
        self._call_stack = []
        self.tracing_enabled = immediate_trace
        self.immediate_trace = immediate_trace
        self.path_cache = {}
        self._current_line = None
        self.start_time = time.time()
        self._expr_cache = {}
        self.config = config
        self._log_queue = queue.Queue()
        self._flush_event = threading.Event()
        self._timer_thread = None
        self._running_flag = False

    def _add_to_buffer(self, message, color_type):
        """将日志消息添加到队列"""
        self._log_queue.put((message, color_type))

    def _flush_buffer(self):
        """刷新队列，输出所有日志"""
        while not self._log_queue.empty():
            try:
                message, color_type = self._log_queue.get_nowait()
                colored_msg = _color_wrap(message, color_type)
                logging.debug(message)
                print(colored_msg)
            except queue.Empty:
                break

    def _flush_scheduler(self):
        """定时刷新调度器"""
        while self._running_flag:
            time.sleep(1)
            self._flush_buffer()

    def is_target_frame(self, frame):
        """精确匹配目标模块路径"""
        try:
            if not frame or not frame.f_code or not frame.f_code.co_filename:
                return False

            result = self.path_cache.get(frame.f_code.co_filename, None)
            if result is not None:
                return result
            frame_path = Path(frame.f_code.co_filename).resolve()
            matched = self.config.match_filename(str(frame_path))
            self.path_cache[frame.f_code.co_filename] = matched
            if matched:
                self._add_to_buffer(f"Matched target file: {frame_path}", "call")
            return matched
        except (AttributeError, ValueError, OSError) as e:
            logging.debug("Frame check error: %s", str(e))
            return False

    def capture_variables(self, frame):
        """捕获并计算变量表达式"""
        if not self.config.capture_vars:
            return {}

        try:
            locals_dict = frame.f_locals
            globals_dict = frame.f_globals
            results = {}

            for expr in self.config.capture_vars:
                try:
                    node = ast.parse(expr, mode="eval")
                    compiled = compile(node, "<string>", "eval")
                    value = eval(compiled, globals_dict, locals_dict)
                    formatted = _truncate_value(value)
                    results[expr] = formatted
                except (NameError, SyntaxError, TypeError) as e:
                    self._add_to_buffer(f"表达式求值失败: {expr}, 错误: {str(e)}", "error")
                    results[expr] = f"<求值错误: {str(e)}>"

            if self.config.callback:
                try:
                    self.config.callback(results)
                except Exception as e:
                    logging.error("回调函数执行失败: %s", str(e))

            return results
        except Exception as e:
            logging.error("变量捕获失败: %s", str(e))
            return {}

    def _log_call(self, frame):
        """增强参数捕获逻辑"""
        if not self.tracing_enabled:
            return
        if self.stack_depth >= _MAX_CALL_DEPTH:
            self._add_to_buffer(f"{_INDENT * self.stack_depth}⚠ MAX CALL DEPTH REACHED", "error")
            return

        try:
            locals_dict = frame.f_locals
            args_info = []

            if frame.f_code.co_name == "<module>":
                log_prefix = "MODULE"
            else:
                try:
                    args, _, _, values = inspect.getargvalues(frame)
                    for arg in args:
                        if arg in values:
                            args_info.append(f"{arg}={_truncate_value(values[arg])}")
                except Exception as e:
                    self._add_to_buffer(f"参数解析失败: {str(e)}", "error")
                    args_info.append("<参数解析错误>")

                log_prefix = "CALL"

            log_msg = f"{_INDENT*self.stack_depth}↘ {log_prefix} {frame.f_code.co_name}({', '.join(args_info)})"
            self._add_to_buffer(log_msg, "call")

            self.last_locals[frame] = locals_dict.copy()
            self._call_stack.append(frame.f_code.co_name)
            self._last_log_time[hash(frame)] = time.time()
        except Exception as e:
            traceback.print_exc()
            logging.error("Call logging error: %s", str(e))
            self._add_to_buffer(f"⚠ 记录调用时出错: {str(e)}", "error")

    def _log_return(self, frame, return_value):
        """增强返回值记录"""
        if not self.tracing_enabled:
            return

        try:
            return_str = _truncate_value(return_value)
            log_msg = f"{_INDENT*self.stack_depth}↗ RETURN {frame.f_code.co_name}() " f"→ {return_str}"
            self._add_to_buffer(log_msg, "return")

            self.stack_depth = max(0, self.stack_depth - 1)
            self.last_locals.pop(frame, None)
            self._active_frames.discard(frame)
            if self._call_stack:
                self._call_stack.pop()
        except KeyError:
            pass

    def log_line(self, frame):
        """基础行号跟踪"""
        if not self.is_target_frame(frame):
            return
        lineno = frame.f_lineno
        if self.line_counter.get(lineno, 0) >= _MAX_LINE_REPEAT:
            return
        self.line_counter[lineno] = self.line_counter.get(lineno, 0) + 1
        line = linecache.getline(frame.f_code.co_filename, lineno).strip("\n")
        log_msg = f"{_INDENT*self.stack_depth}▷ 执行行 {lineno}: {line}"
        self._add_to_buffer(log_msg, "line")

        if self.config.capture_vars:
            captured_vars = self.capture_variables(frame)
            if captured_vars:
                var_msg = (
                    f"{_INDENT*(self.stack_depth+1)}↳ 变量: {', '.join(f'{k}={v}' for k, v in captured_vars.items())}"
                )
                self._add_to_buffer(var_msg, "var")

    def trace_dispatch(self, frame, event, arg):
        """事件分发器"""
        if event == "call":
            return self._handle_call_event(frame, arg)
        if event == "return":
            return self._handle_return_event(frame, arg)
        if event == "line":
            return self._handle_line_event(frame, arg)
        return None

    def _handle_call_event(self, frame, arg):
        """处理函数调用事件"""
        if not self.in_target and self.is_target_frame(frame):
            self.in_target = True
            logging.info("🚀 ENTER TARGET MODULE: %s", self.target_path)
            self._add_to_buffer(f"\n🔍 开始追踪目标模块: {self.target_path}", "call")
        if self.is_target_frame(frame):
            self.stack_depth += 1
            self._log_call(frame)
            self._active_frames.add(frame)
        return self.trace_dispatch

    def _handle_return_event(self, frame, arg):
        """处理函数返回事件"""
        if frame in self._active_frames:
            self._log_return(frame, arg)
        return self.trace_dispatch

    def _handle_line_event(self, frame, arg):
        """处理行号事件"""
        if self.tracing_enabled and frame in self._active_frames:
            self.log_line(frame)
        return self.trace_dispatch

    def start(self):
        """启动跟踪"""
        sys.settrace(self.trace_dispatch)
        logging.info("🔄 START DEBUG SESSION FOR: %s", self.target_path)
        self._add_to_buffer(f"\n▶ 开始调试会话 [{time.strftime('%H:%M:%S')}]", "call")
        self._running_flag = True
        self._timer_thread = threading.Thread(target=self._flush_scheduler)
        self._timer_thread.daemon = True
        self._timer_thread.start()

    def stop(self):
        """停止跟踪"""
        sys.settrace(None)
        logging.info("⏹ DEBUG SESSION ENDED\n")
        self._add_to_buffer(f"\n⏹ 调试会话结束", "return")
        self._running_flag = False
        if self._timer_thread:
            self._timer_thread.join(timeout=1)
        self._flush_buffer()
        while not self._log_queue.empty():
            self._log_queue.get_nowait()


def start_trace(module_path, config: TraceConfig, immediate_trace=True):
    """启动调试跟踪会话

    Args:
        module_path: 目标模块路径
        config: 跟踪配置实例
        immediate_trace: 是否立即开始跟踪
    """
    try:
        tracer = TraceCore(module_path, config=config, immediate_trace=immediate_trace)
        tracer.start()
        return tracer
    except Exception as e:
        logging.error("💥 DEBUGGER INIT ERROR: %s\n%s", str(e), traceback.format_exc())
        print(_color_wrap(f"❌ 调试器初始化错误: {str(e)}\n{traceback.format_exc()}", "error"))
        raise


def stop_trace():
    """停止调试跟踪并清理资源"""
    sys.settrace(None)
    logging.info("⏹ DEBUG SESSION ENDED\n")
    print(_color_wrap(f"\n⏹ 调试会话结束", "return"))
