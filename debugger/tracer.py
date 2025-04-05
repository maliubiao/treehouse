import ast
import datetime
import fnmatch
import importlib.util
import inspect
import linecache
import logging
import os
import queue
import sys
import threading
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import yaml

_MAX_VALUE_LENGTH = 512
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
    "trace": "\033[95m",  # 紫色
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


MAX_ELEMENTS = 5


def _truncate_value(value):
    """智能截断保留关键类型信息"""
    try:
        if isinstance(value, (list, tuple)):
            elements = list(value)[:MAX_ELEMENTS]
            preview = (
                f"{type(value).__name__}({elements}...)"
                if len(value) > MAX_ELEMENTS
                else f"{type(value).__name__}({value})"
            )
        elif isinstance(value, dict):
            keys = list(value.keys())[:MAX_ELEMENTS]
            preview = f"dict(keys={keys}...)" if len(value) > 3 else f"dict({value})"
        elif hasattr(value, "__dict__"):
            attrs = list(vars(value).keys())[:MAX_ELEMENTS]
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


class TraceDispatcher:
    def __init__(self, target_path, config: TraceConfig):
        try:
            self.target_path = Path(target_path).resolve(strict=True)
        except FileNotFoundError:
            logging.error("Target path not found: %s\n%s", target_path, traceback.format_exc())
            raise
        self.config = config
        self.path_cache = {}
        self._logic = TraceLogic(config)
        self._active_frames = set()

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
            return matched
        except (AttributeError, ValueError, OSError) as e:
            logging.debug("Frame check error: %s", str(e))
            return False

    def trace_dispatch(self, frame, event, arg):
        """事件分发器"""
        if event == "call":
            return self._handle_call_event(frame, arg)
        if event == "return":
            return self._handle_return_event(frame, arg)
        if event == "line":
            return self._handle_line_event(frame, arg)
        if event == "exception":
            return self._handle_exception_event(frame, arg)
        return None

    def _handle_call_event(self, frame, arg):
        """处理函数调用事件"""
        if self.is_target_frame(frame):
            self._active_frames.add(frame)
            self._logic.handle_call(frame)
        return self.trace_dispatch

    def _handle_return_event(self, frame, arg):
        """处理函数返回事件"""
        if frame in self._active_frames:
            self._logic.handle_return(frame, arg)
            self._active_frames.discard(frame)
        return self.trace_dispatch

    def _handle_line_event(self, frame, arg):
        """处理行号事件"""
        if frame in self._active_frames:
            self._logic.handle_line(frame)
        return self.trace_dispatch

    def _handle_exception_event(self, frame, arg):
        """处理异常事件"""
        if frame in self._active_frames:
            exc_type, exc_value, exc_traceback = arg
            self._logic.handle_exception(exc_type, exc_value, exc_traceback)
        return self.trace_dispatch

    def start(self):
        """启动跟踪"""
        sys.settrace(self.trace_dispatch)
        self._logic.start()

    def stop(self):
        """停止跟踪"""
        sys.settrace(None)
        self._logic.stop()


class CallTreeHtmlRender:
    """将跟踪日志渲染为美观的HTML页面，支持搜索、折叠等功能"""

    def __init__(self, trace_logic: "TraceLogic"):
        self.trace_logic = trace_logic
        self._messages = []  # 用于收集所有消息
        self._html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Python Trace Report</title>
    <link rel="stylesheet" href="../tracer_styles.css">
</head>
<body>
    <h1>Python Trace Report</h1>
    <div class="summary">
        <p>Generated at: {generation_time}</p>
        <p>Total messages: {message_count}</p>
        <p>Errors: {error_count}</p>
    </div>
    <div id="controls">
        <input type="text" id="search" placeholder="Search messages...">
        <button id="expandAll">Expand All</button>
        <button id="collapseAll">Collapse All</button>
        <button id="exportBtn">Export as HTML</button>
    </div>
    <div id="content">\n{content}\n</div>
    <script src="../tracer_scripts.js"></script>
</body>
</html>"""

    def _message_to_html(self, message, msg_type):
        """将消息转换为HTML片段"""
        content = message.strip()
        indent = len(message) - len(content)
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

        if msg_type == "call":
            return (
                f'<div class="foldable call" style="padding-left:{indent}px">\n'
                f'    <span class="timestamp">[{timestamp}]</span> {content}\n'
                f"</div>\n"
                f'<div class="call-group">\n'
            )
        elif msg_type == "return":
            return (
                f"</div>\n"
                f'<div class="return" style="padding-left:{indent}px">\n'
                f'    <span class="timestamp">[{timestamp}]</span> {content}\n'
                f"</div>\n"
            )
        return (
            f'<div class="{msg_type}" style="padding-left:{indent}px">\n'
            f'    <span class="timestamp">[{timestamp}]</span> {content}\n'
            f"</div>\n"
        )

    def add_message(self, message, msg_type):
        """添加消息到消息列表"""
        self._messages.append((message, msg_type))

    def generate_html(self):
        """生成完整的HTML报告"""
        html_content = []
        for message, msg_type in self._messages:
            html_content.append(self._message_to_html(message, msg_type))

        error_count = sum(1 for _, t in self._messages if t == "error")
        generation_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return self._html_template.format(
            generation_time=generation_time,
            message_count=len(self._messages),
            error_count=error_count,
            content="".join(html_content),
        )

    def save_to_file(self, filename):
        """将HTML报告保存到文件"""
        html = self.generate_html()
        with open(os.path.join(os.path.dirname(__file__), "logs", filename), "w", encoding="utf-8") as f:
            f.write(html)


class TraceLogic:
    def __init__(self, config: TraceConfig):
        self.stack_depth = 0
        self.line_counter = {}
        self._call_stack = []
        self.config = config
        self._log_queue = queue.Queue()
        self._flush_event = threading.Event()
        self._timer_thread = None
        self._running_flag = False
        self._file_name_cache = {}
        self._exception_handler = None
        self._trace_expressions = {}
        self._ast_cache = {}
        self._output_handlers = {"console": self._console_output, "file": self._file_output, "html": self._html_output}
        self._active_outputs = set(["console", "html"])
        self._log_file = None
        self._html_render = CallTreeHtmlRender(self)

    def enable_output(self, output_type: str, **kwargs):
        """启用特定类型的输出"""
        if output_type == "file" and "filename" in kwargs:
            self._log_file = open(kwargs["filename"], "a", encoding="utf-8")
        self._active_outputs.add(output_type)

    def disable_output(self, output_type: str):
        """禁用特定类型的输出"""
        if output_type == "file" and self._log_file:
            self._log_file.close()
            self._log_file = None
        self._active_outputs.discard(output_type)

    def _console_output(self, message, color_type):
        """控制台输出处理"""
        colored_msg = _color_wrap(message, color_type)
        print(colored_msg)

    def _file_output(self, message, color_type):
        """文件输出处理"""
        if self._log_file:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            self._log_file.write(f"[{timestamp}] {message}\n")
            self._log_file.flush()

    def _html_output(self, message, color_type):
        """HTML输出处理"""
        self._html_render.add_message(message, color_type)

    def _add_to_buffer(self, message, color_type):
        """将日志消息添加到队列并立即处理"""
        self._log_queue.put((message, color_type))
        if "html" in self._active_outputs:
            self._html_render.add_message(message, color_type)

    def _flush_buffer(self):
        """刷新队列，输出所有日志"""
        while not self._log_queue.empty():
            try:
                message, color_type = self._log_queue.get_nowait()
                for output_type in self._active_outputs:
                    if output_type in self._output_handlers:
                        self._output_handlers[output_type](message, color_type)
            except queue.Empty:
                break

    def _flush_scheduler(self):
        """定时刷新调度器"""
        while self._running_flag:
            time.sleep(1)
            self._flush_buffer()

    def _get_formatted_filename(self, filename):
        """获取格式化后的文件名"""
        if filename in self._file_name_cache:
            return self._file_name_cache[filename]

        try:
            path = Path(filename)
            if path.name == "__init__.py":
                parts = list(path.parts)
                if len(parts) > 1:
                    formatted = str(Path(*parts[-2:]))
                else:
                    formatted = path.name
            else:
                formatted = path.name
            self._file_name_cache[filename] = formatted
            return formatted
        except Exception:
            return filename

    def _parse_trace_comment(self, line):
        """解析追踪注释"""
        comment_pos = line.rfind("#")
        if comment_pos == -1:
            return None

        comment = line[comment_pos + 1 :].strip()
        if not comment.lower().startswith("trace "):
            return None

        return comment[6:].strip()

    def _get_trace_expression(self, filename, lineno):
        """获取缓存的追踪表达式"""
        if filename not in self._trace_expressions:
            return None
        return self._trace_expressions[filename].get(lineno)

    def _cache_trace_expression(self, filename, lineno, expr):
        """缓存追踪表达式"""
        if filename not in self._trace_expressions:
            self._trace_expressions[filename] = {}
        self._trace_expressions[filename][lineno] = expr

    def _compile_expr(self, expr):
        """编译表达式并缓存结果"""
        if expr in self._ast_cache:
            return self._ast_cache[expr]

        try:
            node = ast.parse(expr, mode="eval")
            compiled = compile(node, "<string>", "eval")
            self._ast_cache[expr] = (node, compiled)
            return node, compiled
        except Exception as e:
            self._add_to_buffer(f"表达式解析失败: {expr}, 错误: {str(e)}", "error")
            raise

    def handle_call(self, frame):
        """增强参数捕获逻辑"""
        if self.stack_depth >= _MAX_CALL_DEPTH:
            self._add_to_buffer(f"{_INDENT * self.stack_depth}⚠ MAX CALL DEPTH REACHED", "error")
            return

        try:
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

            log_msg = f"{_INDENT*self.stack_depth}↘ {log_prefix} {self._get_formatted_filename(frame.f_code.co_filename)}:{frame.f_lineno} {frame.f_code.co_name}({', '.join(args_info)})"
            self._add_to_buffer(log_msg, "call")
            self._call_stack.append(frame.f_code.co_name)
            self.stack_depth += 1
        except Exception as e:
            traceback.print_exc()
            logging.error("Call logging error: %s", str(e))
            self._add_to_buffer(f"⚠ 记录调用时出错: {str(e)}", "error")

    def handle_return(self, frame, return_value):
        """增强返回值记录"""
        try:
            return_str = _truncate_value(return_value)
            log_msg = f"{_INDENT*(self.stack_depth-1)}↗ RETURN {self._get_formatted_filename(frame.f_code.co_filename)}() → {return_str}"
            self._add_to_buffer(log_msg, "return")
            self.stack_depth = max(0, self.stack_depth - 1)
            if self._call_stack:
                self._call_stack.pop()
        except KeyError:
            pass

    def handle_line(self, frame):
        """基础行号跟踪"""
        lineno = frame.f_lineno
        if self.line_counter.get(lineno, 0) >= _MAX_LINE_REPEAT:
            return
        self.line_counter[lineno] = self.line_counter.get(lineno, 0) + 1

        filename = frame.f_code.co_filename
        line = linecache.getline(filename, lineno).strip("\n")
        formatted_filename = self._get_formatted_filename(filename)
        log_msg = f"{_INDENT*self.stack_depth}▷ {formatted_filename}:{lineno} {line}"
        self._add_to_buffer(log_msg, "line")

        # 解析并执行追踪表达式
        expr = self._parse_trace_comment(line)
        cached_expr = self._get_trace_expression(filename, lineno)
        active_expr = expr if expr is not None else cached_expr

        if active_expr:
            try:
                locals_dict = frame.f_locals
                globals_dict = frame.f_globals
                _, compiled = self._compile_expr(active_expr)
                value = eval(compiled, globals_dict, locals_dict)
                formatted = _truncate_value(value)
                trace_msg = f"{_INDENT*(self.stack_depth+1)}↳ TRACE 表达式 {active_expr} -> {formatted}"
                self._add_to_buffer(trace_msg, "trace")
                if expr and expr != cached_expr:
                    self._cache_trace_expression(filename, lineno, expr)
            except Exception as e:
                error_msg = f"{_INDENT*(self.stack_depth+1)}↳ TRACE ERROR: {active_expr} → {str(e)}"
                self._add_to_buffer(error_msg, "error")

        if self.config.capture_vars:
            captured_vars = self.capture_variables(frame)
            if captured_vars:
                var_msg = (
                    f"{_INDENT*(self.stack_depth+1)}↳ 变量: {', '.join(f'{k}={v}' for k, v in captured_vars.items())}"
                )
                self._add_to_buffer(var_msg, "var")

    def handle_exception(self, exc_type, exc_value, exc_traceback):
        """记录异常信息"""
        if exc_traceback:
            frame = exc_traceback.tb_frame
            filename = self._get_formatted_filename(frame.f_code.co_filename)
            lineno = exc_traceback.tb_lineno
            exc_msg = f"{_INDENT*self.stack_depth}⚠ EXCEPTION {filename}:{lineno} {exc_type.__name__}: {str(exc_value)}"
            self._add_to_buffer(exc_msg, "error")

            stack = traceback.extract_tb(exc_traceback)
            for i, frame_info in enumerate(stack):
                if i == 0:
                    continue
                filename = self._get_formatted_filename(frame_info.filename)
                self._add_to_buffer(
                    f"{_INDENT*(self.stack_depth+i)}↳ at {filename}:{frame_info.lineno} in {frame_info.name}", "error"
                )

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
                    _, compiled = self._compile_expr(expr)
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

    def start(self):
        """启动逻辑处理"""
        self._running_flag = True
        self._timer_thread = threading.Thread(target=self._flush_scheduler)
        self._timer_thread.daemon = True
        self._timer_thread.start()

    def stop(self):
        """停止逻辑处理"""
        self._running_flag = False
        if self._timer_thread:
            self._timer_thread.join(timeout=1)
        self._flush_buffer()
        while not self._log_queue.empty():
            self._log_queue.get_nowait()
        if self._log_file:
            self._log_file.close()
            self._log_file = None
        # 新增：停止时自动生成HTML报告
        if "html" in self._active_outputs:
            print("正在生成HTML报告trace_report.html...")
            self._html_render.save_to_file("trace_report.html")


def start_trace(module_path, config: TraceConfig):
    """启动调试跟踪会话

    Args:
        module_path: 目标模块路径
        config: 跟踪配置实例
        immediate_trace: 是否立即开始跟踪
    """
    tracer_core_path = os.path.join(os.path.dirname(__file__), "tracer_core.so")
    if os.path.exists(tracer_core_path):
        try:
            spec = importlib.util.spec_from_file_location("tracer_core", tracer_core_path)
            tracer_core = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tracer_core)
            TraceDispatcher = tracer_core.TraceDispatcher
            tracer = TraceDispatcher(str(module_path), TraceLogic(config), config)
        except Exception as e:
            logging.error("💥 DEBUGGER IMPORT ERROR: %s\n%s", str(e), traceback.format_exc())
            print(_color_wrap(f"❌ 调试器导入错误: {str(e)}\n{traceback.format_exc()}", "error"))
            raise
    else:
        tracer = TraceDispatcher(str(module_path), config)
    try:
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
