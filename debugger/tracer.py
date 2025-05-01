import ast
import base64
import datetime
import dis
import fnmatch
import functools
import html
import importlib.util
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
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import yaml
from colorama import Fore, Style, just_fix_windows_console

just_fix_windows_console()

_MAX_VALUE_LENGTH = 512
_INDENT = "  "
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_NAME = _LOG_DIR / "debug.log"
_MAX_CALL_DEPTH = 20

# 该字典已被colorama替代

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
        report_name: str = "trace_report.html",
        exclude_functions: List[str] = None,
        enable_var_trace: bool = False,  # 新增配置项
    ):
        """
        初始化跟踪配置

        Args:
            target_files: 目标文件模式列表，支持通配符
            line_ranges: 文件行号范围字典，key为文件名，value为 (start_line, end_line) 元组列表
            capture_vars: 要捕获的变量表达式列表
            callback: 变量捕获时的回调函数
            exclude_functions: 要排除的函数名列表
            enable_var_trace: 是否启用变量操作跟踪
        """
        self.target_files = target_files or []
        self.line_ranges = self._parse_line_ranges(line_ranges or {})
        self.capture_vars = capture_vars or []
        self.callback = callback
        self.exclude_functions = exclude_functions or []
        self.enable_var_trace = enable_var_trace  # 新增属性
        self._compiled_patterns = [fnmatch.translate(pattern) for pattern in self.target_files]
        if report_name:
            self.report_name = report_name
        else:
            self.report_name = "tracer_report.html"

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
            exclude_functions=config_data.get("exclude_functions", []),
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
        if filename == __file__:
            return False
        if not self.target_files:
            return True
        filename_posix = Path(filename).as_posix()
        return any(fnmatch.fnmatch(filename_posix, pattern) for pattern in self.target_files)

    def is_excluded_function(self, func_name: str) -> bool:
        """检查函数名是否在排除列表中"""
        return func_name in self.exclude_functions


def truncate_repr_value(value, keep_elements=10):
    """智能截断保留关键类型信息"""
    preview = "..."

    try:
        # Ignore function, module, and class types
        if inspect.isfunction(value) or inspect.ismodule(value) or inspect.isclass(value):
            preview = f"{type(value).__name__}(...)"
        elif isinstance(value, (list, tuple)):
            if len(value) <= keep_elements:
                preview = repr(value)
            else:
                keep_list = []
                for i in range(value[:keep_elements]):
                    keep_list.append(value[i])
                preview = f"[{keep_list} ...]"
        elif isinstance(value, dict):
            if len(value) <= keep_elements:
                preview = repr(value)
            else:
                keep_dict = {}
                i = keep_elements
                it = iter(value)
                while i > 0 and value:
                    key = next(it)
                    keep_dict[key] = value[key]
                    i -= 1
                s = repr(keep_dict)
                preview = "%s ...}" % s[:-1]
        elif hasattr(value, "__dict__"):
            if len(value.__dict__) <= keep_elements:
                preview = f"{type(value).__name__}.({repr(value.__dict__)})"
            else:
                keep_attrs = {}
                i = keep_elements
                it = iter(value.__dict__)
                while i > 0 and value.__dict__:
                    key = next(it)
                    keep_attrs[key] = value.__dict__[key]
                    i -= 1
                s = repr(keep_attrs)
                preview = f"{type(value).__name__}(%s ...)" % s[:-1]
        else:
            preview = repr(value)
    except (AttributeError, TypeError, ValueError) as e:
        return f"capture error: {str(e)}"

    if len(preview) > _MAX_VALUE_LENGTH:
        preview = preview[:_MAX_VALUE_LENGTH] + "..."
    return preview


def color_wrap(text, color_type):
    """包装颜色但不影响日志文件"""
    color_mapping = {
        "call": Fore.GREEN,
        "return": Fore.BLUE,
        "var": Fore.YELLOW,
        "line": Style.RESET_ALL,
        "error": Fore.RED,
        "trace": Fore.MAGENTA,
        "reset": Style.RESET_ALL,
    }
    return f"{color_mapping.get(color_type, '')}{text}{Style.RESET_ALL}"


class TraceDispatcher:
    def __init__(self, target_path, config: TraceConfig):
        self.target_path = target_path
        self.config = config
        self.path_cache = {}
        self._logic = TraceLogic(config)
        self.active_frames = set()
        self.bad_frame = None

    def add_target_frame(self, frame):
        if self.is_target_frame(frame):
            self.active_frames.add(frame)

    def is_target_frame(self, frame):
        """精确匹配目标模块路径"""
        try:
            if not frame or not frame.f_code or not frame.f_code.co_filename:
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
        if event == "call":
            return self._handle_call_event(frame)
        if event == "return":
            return self._handle_return_event(frame, arg)
        if event == "line":
            return self._handle_line_event(frame)
        if event == "exception":
            return self._handle_exception_event(frame, arg)
        return None

    def _handle_call_event(self, frame, arg=None):
        """处理函数调用事件"""
        if frame.f_code.co_name in self.config.exclude_functions:
            frame.f_trace_lines = False
            self.bad_frame = frame
            return None
        if self.is_target_frame(frame):
            self.active_frames.add(frame)
            self._logic.handle_call(frame)
        return self.trace_dispatch

    def _handle_return_event(self, frame, arg):
        """处理函数返回事件"""
        if frame == self.bad_frame:
            self.bad_frame = None
        if frame in self.active_frames:
            self._logic.handle_return(frame, arg)
            self.active_frames.discard(frame)
        return self.trace_dispatch

    def _handle_line_event(self, frame, arg=None):
        """处理行号事件"""
        if self.bad_frame:
            return self.trace_dispatch
        if frame in self.active_frames:
            self._logic.handle_line(frame)
        return self.trace_dispatch

    def _handle_exception_event(self, frame, arg):
        """处理异常事件"""
        if self.bad_frame:
            return self.trace_dispatch
        if frame in self.active_frames:
            exc_type, exc_value, exc_traceback = arg
            self._logic.handle_exception(exc_type, exc_value, exc_traceback)
        return self.trace_dispatch

    def start(self):
        """启动跟踪"""
        self._logic.start_flush_thread()
        sys.settrace(self.trace_dispatch)
        self._logic.start()

    def stop(self):
        """停止跟踪"""
        sys.settrace(None)
        self._logic.stop()
        logging.info("⏹ DEBUG SESSION ENDED\n")
        print(color_wrap(f"\n⏹ 调试会话结束", "return"))


class CallTreeHtmlRender:
    """将跟踪日志渲染为美观的HTML页面，支持搜索、折叠等功能"""

    def __init__(self, trace_logic: "TraceLogic"):
        self.trace_logic = trace_logic
        self._messages = []  # 存储(message, msg_type, log_data)三元组
        self._executed_lines = defaultdict(lambda: defaultdict(set))  # 使用集合避免重复记录
        self._frame_executed_lines = defaultdict(lambda: defaultdict(set))
        self._source_files = {}  # 存储源代码文件内容
        self._stack_variables = {}  # 键改为元组(frame_id, filename, lineno)
        self._comments_data = defaultdict(lambda: defaultdict(list))
        self.current_message_id = 0
        self._html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Python Trace Report</title>
    <link rel="stylesheet" href="../tracer_styles.css">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css" rel="stylesheet" id="prism-theme">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/line-numbers/prism-line-numbers.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/toolbar/prism-toolbar.min.css" rel="stylesheet">
</head>
<body>
    <div id="sourceDialog" class="source-dialog">
        <div class="floating-close-btn" id="dialogCloseBtn">&times;</div>
        <div class="close-overlay"></div>
        <div class="source-header">
            <div class="source-title" id="sourceTitle"></div>
        </div>
        <div class="source-content" id="sourceContent"></div>

    </div>
    <h1>Python Trace Report</h1>
    <div class="summary">
        <p>Generated at: {generation_time}</p>
        <p>Total messages: {message_count}</p>
        <p>Errors: {error_count}</p>
        <div class="theme-selector">
            <label>Theme: </label>
            <select id="themeSelector">
                <!-- Options will be populated by JavaScript -->
            </select>
        </div>
    </div>
    <div id="controls">
        <input type="text" id="search" placeholder="Search messages...">
        <button id="expandAll">Expand All</button>
        <button id="collapseAll">Collapse All</button>
        <button id="exportBtn">Export as HTML</button>
    </div>
    <div id="content">\n{content}\n</div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-core.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/autoloader/prism-autoloader.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/line-numbers/prism-line-numbers.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/toolbar/prism-toolbar.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/copy-to-clipboard/prism-copy-to-clipboard.min.js"></script>
    <script src="../tracer_scripts.js"></script>
    <script>
        window.executedLines = {executed_lines_data};
        window.sourceFiles = {source_files_data};
        window.commentsData = {comments_data};
    </script>
</body>
</html>"""

    def _get_nested_dict_value(self, data_dict, filename, frame_id=None):
        """获取嵌套字典中的值"""
        try:
            return data_dict[filename] if frame_id is None else data_dict[filename][frame_id]
        except KeyError:
            return None

    def _set_nested_dict_value(self, data_dict, filename, value, frame_id=None):
        """设置嵌套字典中的值"""
        if frame_id is not None:
            data_dict[filename][frame_id].add(value)
        else:
            data_dict[filename] = value

    def format_stack_variables(self, variables):
        if not variables:
            return ""
        text = []
        seen = set()
        for opcode, var_name, value in variables:
            if "CALL" == dis.opname[opcode]:
                is_method = value[-1]
                value = value[:-1]
                instance_name = ""
                if is_method:
                    instance = value[0]
                    if getattr(instance, "__name__", None):
                        instance_name = instance.__name__
                    elif getattr(instance, "__class__", None):
                        instance_name = instance.__class__.__name__
                    else:
                        instance_name = repr(instance)
                    value = value[1:]
                args = ", ".join(f"{truncate_repr_value(arg)}" for arg in value)
                if getattr(var_name, "__code__", None):
                    item = f"{var_name.__code__.co_name}({args})"
                elif getattr(var_name, "__name__", None):
                    item = f"{var_name.__name__}({args})"
                else:
                    item = f"{var_name}({args})"
                if instance_name:
                    item = f"{instance_name}.{item}"
            elif "STORE_SUBSCR" == dis.opname[opcode]:
                item = f"[{var_name}]={truncate_repr_value(value)}"
            else:
                item = f"{var_name}={truncate_repr_value(value)}"
            if item not in seen:
                seen.add(item)
                text.append(item)
        return " ".join(text)

    def _message_to_html(self, message, msg_type, log_data):
        """将消息转换为HTML片段"""
        stripped_message = message.lstrip()
        indent = len(message) - len(stripped_message)
        escaped_content = html.escape(stripped_message).replace(" ", "&nbsp;")

        data = log_data.get("data", {}) if isinstance(log_data, dict) else {}
        original_filename = data.get("original_filename")
        line_number = data.get("lineno")
        frame_id = data.get("frame_id")
        comment_html = ""
        idx = log_data.get("idx", None)
        if self._stack_variables.get(idx):
            comment = self.format_stack_variables(self._stack_variables[idx])
            comment_id = f"comment_{idx}"
            comment_html = self._build_comment_html(comment_id, comment) if comment else ""
        view_source_html = self._build_view_source_html(original_filename, line_number, frame_id)
        html_parts = []
        if msg_type == "call":
            html_parts.extend(
                [
                    f'<div class="foldable call" style="padding-left:{indent}px">',
                    f"    {escaped_content}{view_source_html}{comment_html}",
                    "</div>",
                    '<div class="call-group">',
                ]
            )
        elif msg_type == "return":
            html_parts.extend(
                [
                    "</div>",
                    f'<div class="return" style="padding-left:{indent}px">',
                    f"    {escaped_content}{comment_html}",
                    "</div>",
                ]
            )
        else:
            html_parts.extend(
                [
                    f'<div class="{msg_type}" style="padding-left:{indent}px">',
                    f"    {escaped_content}{view_source_html}{comment_html}",
                    "</div>",
                ]
            )
        return "\n".join(html_parts) + "\n"

    def _build_comment_html(self, comment_id, comment):
        """构建评论HTML片段"""
        is_long = len(comment) > 64
        short_comment = comment[:64] + "..." if is_long else comment
        short_comment_escaped = html.escape(short_comment)
        full_comment_escaped = html.escape(comment)
        return f'<span class="comment" id="{comment_id}" onclick="event.stopPropagation(); toggleCommentExpand(\'{comment_id}\', event)"><span class="comment-preview">{short_comment_escaped}</span><span class="comment-full">{full_comment_escaped}</span></span>'

    def _build_view_source_html(self, filename, line_number, frame_id):
        """构建查看源代码按钮HTML片段"""
        if not filename or not line_number:
            return ""
        # Escape backslashes in filenames (important for Windows paths)
        escaped_filename = filename.replace("\\", "\\\\").replace("'", "\\'")
        return f'<span class="view-source-btn" onclick="showSource(\'{escaped_filename}\', {line_number}, {frame_id})">view source</span>'

    def _load_source_file(self, filename):
        """加载源代码文件内容"""
        if filename in self._source_files:
            return
        try:
            with open(filename, "rb") as f:
                content = base64.b64encode(f.read()).decode("utf-8")
                self._source_files[filename] = content
        except (IOError, OSError) as e:
            self._source_files[filename] = f"// Error loading source file: {str(e)}"

    def add_message(self, message, msg_type, log_data=None):
        """添加消息到消息列表"""
        self._messages.append((message, msg_type, log_data))

    def add_stack_variable_create(self, idx, opcode, var_name, value):
        if idx not in self._stack_variables:
            self._stack_variables[idx] = []
        self._stack_variables[idx].append((opcode, var_name, value))

    def add_raw_message(self, log_data, color_type):
        """添加原始日志数据并处理"""
        if isinstance(log_data, str):
            message = log_data
        else:
            # 预缓存格式化结果避免重复格式化
            message = log_data["template"].format(**log_data["data"])

        if color_type == "line" and isinstance(log_data, dict) and "lineno" in log_data.get("data", {}):
            data = log_data["data"]
            original_filename = data.get("original_filename")
            lineno = data["lineno"]
            frame_id = data.get("frame_id")
            if original_filename and lineno:
                self._executed_lines[original_filename][frame_id].add(lineno)
                self._load_source_file(original_filename)
        self._messages.append((message, color_type, log_data))

    def generate_html(self):
        """生成完整的HTML报告"""
        buffer = []
        error_count = 0

        for idx, (message, msg_type, log_data) in enumerate(self._messages):
            buffer.append(self._message_to_html(message, msg_type, log_data))
            if msg_type == "error":
                error_count += 1

        generation_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        executed_lines_data = {
            filename: {frame_id: list(lines) for frame_id, lines in frames.items()}
            for filename, frames in self._executed_lines.items()
        }
        executed_lines_json = json.dumps(executed_lines_data)

        source_files_json = json.dumps(self._source_files)
        comments_json = json.dumps(self._comments_data)

        return self._html_template.format(
            generation_time=generation_time,
            message_count=len(self._messages),
            error_count=error_count,
            content="".join(buffer),
            executed_lines_data=executed_lines_json,
            source_files_data=source_files_json,
            comments_data=comments_json,
        )

    def save_to_file(self, filename):
        """将HTML报告保存到文件"""
        p = Path(filename)
        if p.is_absolute():
            # If it's an absolute path, ensure parent directories exist
            p.parent.mkdir(parents=True, exist_ok=True)
            html_content = self.generate_html()
            p.write_text(html_content, encoding="utf-8")
            log_path = str(p)
        else:
            html_content = self.generate_html()
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, filename)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        print(f"正在生成HTML报告 {log_path} ...")


class TraceLogic:
    class _FileCache:
        def __init__(self):
            self._file_name_cache = {}
            self._trace_expressions = {}
            self._ast_cache = {}
            self._var_ops_cache = {}

    class _FrameData:
        def __init__(self):
            self._frame_id_map = {}
            self._frame_locals_map = {}
            self._current_frame_id = 0
            self._code_var_ops = {}

    class _OutputHandlers:
        def __init__(self, parent):
            self._output_handlers = {
                "console": parent._console_output,
                "file": parent._file_output,
                "html": parent._html_output,
            }
            self._active_outputs = set(["html", "file"])
            self._log_file = None

    def __init__(self, config: TraceConfig):
        """初始化实例属性"""
        self.stack_depth = 0
        self.line_counter = {}
        self._call_stack = []
        self.config = config
        self._log_queue = queue.Queue()
        self._flush_event = threading.Event()
        self._timer_thread = None
        self._running_flag = False
        self._exception_handler = None
        self._log_data_cache = {}
        self._html_render = CallTreeHtmlRender(self)
        self._stack_variables = {}
        self._message_id = 0
        # 分组属性
        self._file_cache = self._FileCache()
        self._frame_data = self._FrameData()
        self._output = self._OutputHandlers(self)

    def _get_frame_id(self, frame):
        """获取当前帧ID"""
        frame_key = id(frame)
        if frame_key not in self._frame_data._frame_id_map:
            self._frame_data._current_frame_id += 1
            self._frame_data._frame_id_map[frame_key] = self._frame_data._current_frame_id
        return self._frame_data._frame_id_map[frame_key]

    def enable_output(self, output_type: str, **kwargs):
        """启用特定类型的输出"""
        if output_type == "file" and "filename" in kwargs:
            try:
                # 使用with语句确保文件正确关闭
                self._output._log_file = open(kwargs["filename"], "a", encoding="utf-8")
            except (IOError, OSError, PermissionError) as e:
                logging.error("无法打开日志文件: %s", str(e))
                raise

        self._output._active_outputs.add(output_type)

    def disable_output(self, output_type: str):
        """禁用特定类型的输出"""
        if output_type == "file" and self._output._log_file:
            try:
                self._output._log_file.close()
            except (IOError, OSError) as e:
                logging.error("关闭日志文件时出错: %s", str(e))
            finally:
                self._output._log_file = None
        self._output._active_outputs.discard(output_type)

    def _console_output(self, log_data, color_type):
        """控制台输出处理"""
        message = self._format_log_message(log_data)
        colored_msg = color_wrap(message, color_type)
        print(colored_msg)

    def _file_output(self, log_data, _):
        """文件输出处理"""
        if self._output._log_file:
            message = self._format_log_message(log_data)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            self._output._log_file.write(f"[{timestamp}] {message}\n")
            self._output._log_file.flush()

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

    def _get_formatted_filename(self, filename):
        """获取格式化后的文件名"""
        if filename in self._file_cache._file_name_cache:
            return self._file_cache._file_name_cache[filename]

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
            self._file_cache._file_name_cache[filename] = formatted
            return formatted
        except (TypeError, ValueError) as e:
            logging.warning("文件名格式化失败: %s", str(e))
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

        try:
            node = ast.parse(expr, mode="eval")
            compiled = compile(node, "<string>", "eval")
            self._file_cache._ast_cache[expr] = (node, compiled)
            return node, compiled
        except (SyntaxError, ValueError) as e:
            self._add_to_buffer(
                {"template": "表达式解析失败: {expr}, 错误: {error}", "data": {"expr": expr, "error": str(e)}}, "error"
            )
            raise

    def handle_call(self, frame):
        """增强参数捕获逻辑"""
        if self.stack_depth >= _MAX_CALL_DEPTH:
            self._add_to_buffer(
                {"template": "{indent}⚠ MAX CALL DEPTH REACHED", "data": {"indent": _INDENT * self.stack_depth}},
                "error",
            )
            return
        frame.f_trace_opcodes = True
        try:
            args_info = []
            if frame.f_code.co_name == "<module>":
                log_prefix = "MODULE"
            else:
                try:
                    args, _, _, values = inspect.getargvalues(frame)
                    args_info = [f"{arg}={truncate_repr_value(values[arg])}" for arg in args]
                except (AttributeError, TypeError) as e:
                    self._add_to_buffer({"template": "参数解析失败: {error}", "data": {"error": str(e)}}, "error")
                    args_info.append("<参数解析错误>")
                log_prefix = "CALL"

            filename = self._get_formatted_filename(frame.f_code.co_filename)
            frame_id = self._get_frame_id(frame)
            self._frame_data._frame_locals_map[frame_id] = frame.f_locals
            self._add_to_buffer(
                {
                    "template": "{indent}↘ {prefix} {filename}:{lineno} {func}({args}) [frame:{frame_id}]",
                    "data": {
                        "indent": _INDENT * self.stack_depth,
                        "prefix": log_prefix,
                        "filename": filename,
                        "original_filename": frame.f_code.co_filename,
                        "lineno": frame.f_lineno,
                        "func": frame.f_code.co_name,
                        "args": ", ".join(args_info),
                        "frame_id": frame_id,
                    },
                },
                "call",
            )
            self._call_stack.append((frame.f_code.co_name, frame_id))
            self.stack_depth += 1
        except (AttributeError, TypeError) as e:
            traceback.print_exc()
            logging.error("Call logging error: %s", str(e))
            self._add_to_buffer({"template": "⚠ 记录调用时出错: {error}", "data": {"error": str(e)}}, "error")

    def handle_return(self, frame, return_value):
        """增强返回值记录"""
        try:
            return_str = truncate_repr_value(return_value)
            filename = self._get_formatted_filename(frame.f_code.co_filename)
            frame_id = self._get_frame_id(frame)
            comment = self.get_locals_change(frame_id, frame)
            if frame_id in self._frame_data._frame_locals_map:
                del self._frame_data._frame_locals_map[frame_id]
            self._add_to_buffer(
                {
                    "template": "{indent}↗ RETURN {filename}() → {return_value} [frame:{frame_id}]",
                    "data": {
                        "indent": _INDENT * (self.stack_depth - 1),
                        "filename": filename,
                        "return_value": return_str,
                        "frame_id": frame_id,
                        "comment": comment,
                        "original_filename": frame.f_code.co_filename,
                    },
                },
                "return",
            )
            self.stack_depth = max(0, self.stack_depth - 1)
            if self._call_stack:
                self._call_stack.pop()
        except KeyError:
            pass

    def get_locals_change(self, _frame_id, _frame):
        """获取局部变量变化"""
        return ""

    def _get_var_ops(self, code_obj):
        """获取代码对象的变量操作分析结果"""
        if code_obj in self._file_cache._var_ops_cache:
            return self._file_cache._var_ops_cache[code_obj]

        from .variable_trace import analyze_variable_ops  # 导入分析函数

        analysis = analyze_variable_ops(code_obj)
        self._file_cache._var_ops_cache[code_obj] = analysis
        return analysis

    def _get_line_vars(self, frame):
        """获取当前行需要跟踪的变量"""
        if not self.config.enable_var_trace:
            return []

        code_obj = frame.f_code
        if code_obj not in self._frame_data._code_var_ops:
            self._frame_data._code_var_ops[code_obj] = self._get_var_ops(code_obj)

        line_ops = self._frame_data._code_var_ops[code_obj].get(frame.f_lineno - 1, {})
        return line_ops.get("loads", []) + line_ops.get("stores", [])

    def handle_line(self, frame):
        """基础行号跟踪"""
        lineno = frame.f_lineno
        filename = frame.f_code.co_filename
        line = linecache.getline(filename, lineno).strip("\n")
        formatted_filename = self._get_formatted_filename(filename)
        frame_id = self._get_frame_id(frame)
        comment = self.get_locals_change(frame_id, frame)
        self._message_id += 1

        # 新增变量跟踪逻辑
        tracked_vars = {}
        if self.config.enable_var_trace:
            var_names = self._get_line_vars(frame)
            if var_names:
                locals_dict = frame.f_locals
                globals_dict = frame.f_globals
                for var in var_names:
                    try:
                        # 安全警告：eval使用是必要的调试功能
                        value = eval(var, globals_dict, locals_dict)  # nosec
                        tracked_vars[var] = truncate_repr_value(value)
                    except Exception as e:
                        tracked_vars[var] = f"<Error: {str(e)}>"

        log_data = {
            "idx": self._message_id,
            "template": "{indent}▷ {filename}:{lineno} {line}",
            "data": {
                "indent": _INDENT * self.stack_depth,
                "filename": formatted_filename,
                "lineno": lineno,
                "line": line,
                "frame_id": frame_id,
                "comment": comment,
                "original_filename": filename,
                "tracked_vars": tracked_vars,  # 新增跟踪变量数据
            },
        }

        if tracked_vars:
            log_data["template"] += " # Debug: {vars}"
            log_data["data"]["vars"] = ", ".join([f"{k}={v}" for k, v in tracked_vars.items()])

        self._add_to_buffer(log_data, "line")

        self._process_trace_expression(frame, line, filename, lineno)
        if self.config.capture_vars:
            self._process_captured_vars(frame)

    def handle_opcode(self, frame, opcode, name, value):
        self._html_render.add_stack_variable_create(self._message_id, opcode, name, value)

    def _process_trace_expression(self, frame, line, filename, lineno):
        """处理追踪表达式"""
        expr = self._parse_trace_comment(line)
        cached_expr = self._get_trace_expression(filename, lineno)
        active_expr = expr if expr is not None else cached_expr

        if not active_expr:
            return

        try:
            locals_dict = frame.f_locals
            globals_dict = frame.f_globals
            _, compiled = self._compile_expr(active_expr)
            # 安全警告：eval使用是必要的调试功能
            value = eval(compiled, globals_dict, locals_dict)  # nosec
            formatted = truncate_repr_value(value)
            self._add_to_buffer(
                {
                    "template": "{indent}↳ TRACE 表达式 {expr} -> {value} [frame:{frame_id}]",
                    "data": {
                        "indent": _INDENT * (self.stack_depth + 1),
                        "expr": active_expr,
                        "value": formatted,
                        "frame_id": self._get_frame_id(frame),
                    },
                },
                "trace",
            )
            if expr and expr != cached_expr:
                self._cache_trace_expression(filename, lineno, expr)
        except (NameError, SyntaxError, TypeError, AttributeError) as e:
            self._add_to_buffer(
                {
                    "template": "{indent}↳ TRACE ERROR: {expr} → {error} [frame:{frame_id}]",
                    "data": {
                        "indent": _INDENT * (self.stack_depth + 1),
                        "expr": active_expr,
                        "error": str(e),
                        "frame_id": self._get_frame_id(frame),
                    },
                },
                "error",
            )

    def _process_captured_vars(self, frame):
        """处理捕获的变量"""
        captured_vars = self.capture_variables(frame)
        if captured_vars:
            self._add_to_buffer(
                {
                    "template": "{indent}↳ 变量: {vars} [frame:{frame_id}]",
                    "data": {
                        "indent": _INDENT * (self.stack_depth + 1),
                        "vars": ", ".join(f"{k}={v}" for k, v in captured_vars.items()),
                        "frame_id": self._get_frame_id(frame),
                    },
                },
                "var",
            )

    def handle_exception(self, exc_type, exc_value, exc_traceback):
        """记录异常信息"""
        if exc_traceback:
            frame = exc_traceback.tb_frame
            filename = self._get_formatted_filename(frame.f_code.co_filename)
            lineno = exc_traceback.tb_lineno
            frame_id = self._get_frame_id(frame)
            self._add_to_buffer(
                {
                    "template": "{indent}⚠ EXCEPTION {filename}:{lineno} {exc_type}: {exc_value} [frame:{frame_id}]",
                    "data": {
                        "indent": _INDENT * self.stack_depth,
                        "filename": filename,
                        "lineno": lineno,
                        "exc_type": exc_type.__name__,
                        "exc_value": str(exc_value),
                        "frame_id": frame_id,
                        "original_filename": frame.f_code.co_filename,
                    },
                },
                "error",
            )

            stack = traceback.extract_tb(exc_traceback)
            for i, frame_info in enumerate(stack):
                if i == 0:
                    continue
                filename = self._get_formatted_filename(frame_info.filename)
                self._add_to_buffer(
                    {
                        "template": "{indent}↳ at {filename}:{lineno} in {func} [frame:{frame_id}]",
                        "data": {
                            "indent": _INDENT * (self.stack_depth + i),
                            "filename": filename,
                            "lineno": frame_info.lineno,
                            "func": frame_info.name,
                            "frame_id": frame_id,
                        },
                    },
                    "error",
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
                    # 安全警告：eval使用是必要的调试功能
                    value = eval(compiled, globals_dict, locals_dict)  # nosec
                    formatted = truncate_repr_value(value)
                    results[expr] = formatted
                except (NameError, SyntaxError, TypeError, AttributeError) as e:
                    self._add_to_buffer(
                        {"template": "表达式求值失败: {expr}, 错误: {error}", "data": {"expr": expr, "error": str(e)}},
                        "error",
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

    def stop(self):
        """停止逻辑处理"""
        self._running_flag = False
        if self._timer_thread:
            self._timer_thread.join(timeout=1)
        self._flush_buffer()
        while not self._log_queue.empty():
            self._log_queue.get_nowait()
        if self._output._log_file:
            self._output._log_file.close()
            self._output._log_file = None
        if "html" in self._output._active_outputs:
            self._html_render.save_to_file(self.config.report_name)


def get_tracer(module_path, config: TraceConfig):
    tracer_core_name = "tracer_core.pyd" if os.name == "nt" else "tracer_core.so"
    tracer_core_path = os.path.join(os.path.dirname(__file__), tracer_core_name)
    if os.path.exists(tracer_core_path):
        try:
            spec = importlib.util.spec_from_file_location("tracer_core", tracer_core_path)
            tracer_core = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tracer_core)
            trace_dispatcher = tracer_core.TraceDispatcher
            return trace_dispatcher(str(module_path), TraceLogic(config), config)
        except Exception as e:
            logging.error("💥 DEBUGGER IMPORT ERROR: %s\n%s", str(e), traceback.format_exc())
            print(color_wrap(f"❌ 调试器导入错误: {str(e)}\n{traceback.format_exc()}", "error"))
            raise
    return None


def start_line_trace(exclude: List[str] = None):
    """
    exclude: 排除的函数列表
    """
    return start_trace(
        config=TraceConfig(target_files=[sys._getframe().f_back.f_code.co_filename], exclude_functions=exclude)
    )


def start_trace(module_path=None, config: TraceConfig = None, **kwargs):
    """启动调试跟踪会话

    Args:
        module_path: 目标模块路径(可选)
        config: 跟踪配置实例(可选)
    """
    if not config:
        log_name = sys._getframe().f_back.f_code.co_name
        config = TraceConfig(
            target_files=[sys._getframe().f_back.f_code.co_filename], report_name=log_name + ".html", **kwargs
        )
    tracer = None
    tracer = get_tracer(module_path, config)
    if not tracer:
        tracer = TraceDispatcher(str(module_path), config)
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
        print(color_wrap(f"❌ 调试器初始化错误: {str(e)}\n{traceback.format_exc()}", "error"))
        raise


class Counter:
    counter = 0
    lock = threading.Lock()

    @classmethod
    def increse(self):
        with Counter.lock:
            Counter.counter += 1
            return Counter.counter


def trace(target_files: List[str] = None, **okwargs):
    """函数跟踪装饰器

    Args:
        config: 跟踪配置实例(可选)
    """
    if not target_files:
        target_files = [sys._getframe().f_back.f_code.co_filename]

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            print(color_wrap("[start tracer]", "call"))
            config = TraceConfig(
                report_name=f"{func.__name__}_{Counter.increse()}.html",
                **okwargs,
            )
            t = start_trace(config=config)
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                if t:
                    print(color_wrap("[stop tracer]", "return"))
                    t.stop()

        return wrapper

    return decorator


def stop_trace(tracer: TraceDispatcher = None):
    """停止调试跟踪并清理资源

    Args:
        tracer: 可选的跟踪器实例
    """
    if tracer:
        tracer.stop()
