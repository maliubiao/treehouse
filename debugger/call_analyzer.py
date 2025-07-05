import datetime
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, TypedDict, Union


class LineEvent(TypedDict):
    """记录单行执行事件的数据结构"""

    line_no: int
    content: str
    timestamp: float
    tracked_vars: Dict[str, Any]


class CallRecord(TypedDict):
    """记录一次函数调用的完整生命周期信息"""

    # 身份信息
    frame_id: int
    func_name: str
    filename: str
    original_filename: str
    original_lineno: int
    caller_lineno: Optional[int]

    # 调用与返回
    args: Dict[str, Any]
    return_value: Any
    exception: Optional[Dict[str, Any]]

    # 时间与内容
    start_time: float
    end_time: float
    # 统一的事件列表，用于保留精确的执行顺序。
    # 每个项目是一个字典，如 {'type': 'line'/'call', 'data': LineEvent/CallRecord}
    events: List[Dict]


class CallAnalyzer:
    """
    分析跟踪事件，构建函数调用树。
    该分析器旨在捕获足够详细的信息，以便于后续自动生成单元测试。
    此版本废弃了不可靠的堆栈推断逻辑，转而依赖跟踪器提供的明确事件流。
    """

    def __init__(self):
        """
        初始化分析器。
        - call_trees: 存储所有函数调用的记录，按 文件名 -> 函数名 组织。
        - call_stack: 一个栈，用于实时跟踪当前的函数调用链。
        - records_by_frame_id: 通过 frame_id 快速查找 CallRecord，即使它已不在调用栈上。
        """
        self.call_trees: Dict[str, Dict[str, List[CallRecord]]] = defaultdict(lambda: defaultdict(list))
        self.call_stack: List[CallRecord] = []
        self.records_by_frame_id: Dict[int, CallRecord] = {}

    def _unwind_stack_to_frame(self, frame_id: int, exception_data: Optional[Dict] = None):
        """
        从调用栈顶部开始回溯，并处理所有弹出的帧。
        这用于处理由未捕获异常导致的堆栈解开（unwinding）。
        当一个未捕获异常发生时，它通常会强制解开整个调用栈。
        """
        # 持续弹出栈顶记录，直到栈为空
        while self.call_stack:
            popped_record = self.call_stack.pop()
            if not popped_record.get("end_time"):
                popped_record["end_time"] = datetime.datetime.now().timestamp()

            # 如果当前弹出的帧是引发特定异常的帧，则记录详细异常信息
            if popped_record["frame_id"] == frame_id and exception_data:
                popped_record["exception"] = {
                    "type": exception_data.get("exc_type", "UnknownException"),
                    "value": exception_data.get("exc_value", "N/A"),
                    "lineno": exception_data.get("lineno"),
                }
                # 一旦处理了引发具体异常的帧，就将 exception_data 清空。
                # 这样，后续弹出的父级帧将被标记为AbnormalTermination，
                # 因为异常已经从它们内部冒泡。
                exception_data = None
            # 否则，如果此帧尚未标记异常（通常是其子调用发生异常导致其异常终止）
            elif not popped_record.get("exception"):
                popped_record["exception"] = {
                    "type": "AbnormalTermination",
                    "value": "Frame exited due to an unhandled exception in a callee.",
                    "lineno": popped_record["original_lineno"],
                }
            self._add_to_final_tree(popped_record)

            # 在处理未捕获异常时，通常意味着栈会完全解开，
            # 因此这里不设置中断条件，以确保所有帧都被正确处理。

    def process_event(self, log_data: Union[str, Dict], event_type: str):
        """
        处理单个跟踪事件，并更新调用树。
        这是挂载到 AnalyzableTraceLogic 上的核心处理函数。
        """
        if not isinstance(log_data, dict) or "data" not in log_data:
            return

        data = log_data.get("data", {})
        frame_id = data.get("frame_id")
        if frame_id is None:
            return

        # 核心逻辑：`exception` 事件表示一个未处理的异常，它会强制解开调用栈
        if event_type == "exception":
            self._unwind_stack_to_frame(frame_id, data)
            return

        # 对于其他事件，我们处理对应的逻辑
        if event_type == "call":
            self._handle_call_event(data)
        elif event_type == "line":
            self._handle_line_event(data)
        elif event_type == "return":
            self._handle_return_event(data)

    def _handle_call_event(self, data: Dict):
        """处理函数调用事件：将新记录压入栈（PUSH操作）。"""
        frame_id = data["frame_id"]
        args_dict = {}
        try:
            # 解析参数字符串
            if isinstance(data.get("args"), str) and data["args"]:
                args_list = data["args"].split(", ")
                for arg_pair in args_list:
                    if "=" in arg_pair:
                        key, value_str = arg_pair.split("=", 1)
                        args_dict[key.strip()] = value_str.strip()
            elif isinstance(data.get("args"), dict):
                args_dict = data["args"]
        except (ValueError, TypeError):
            args_dict = {"raw_args": data.get("args", "")}

        record: CallRecord = {
            "frame_id": frame_id,
            "func_name": data["func"],
            "filename": data["filename"],
            "original_filename": data["original_filename"],
            "original_lineno": data["lineno"],
            "caller_lineno": data.get("caller_lineno"),
            "args": args_dict,
            "return_value": None,
            "exception": None,
            "start_time": datetime.datetime.now().timestamp(),
            "end_time": 0.0,
            "events": [],
        }

        # 如果调用栈不为空，将此调用作为子事件添加到父记录中
        if self.call_stack:
            parent_record = self.call_stack[-1]
            parent_record["events"].append({"type": "call", "data": record})

        self.call_stack.append(record)
        self.records_by_frame_id[frame_id] = record

    def _handle_line_event(self, data: Dict):
        """处理行执行事件，附加到栈顶的调用记录中。"""
        if not self.call_stack:
            return

        # 确保事件属于当前栈顶的帧
        current_record = self.call_stack[-1]
        if current_record["frame_id"] == data["frame_id"]:
            line_event: LineEvent = {
                "line_no": data["lineno"],
                "content": data.get("raw_line", data.get("line", "")),
                "timestamp": datetime.datetime.now().timestamp(),
                "tracked_vars": data.get("tracked_vars", {}),
            }
            current_record["events"].append({"type": "line", "data": line_event})

    def _handle_return_event(self, data: Dict):
        """处理函数返回事件，这是一个明确的帧结束信号（POP操作）。"""
        frame_id = data["frame_id"]
        # 正常返回只可能发生在栈顶帧
        if self.call_stack and self.call_stack[-1]["frame_id"] == frame_id:
            record = self.call_stack.pop()
            record["return_value"] = data["return_value"]
            record["end_time"] = datetime.datetime.now().timestamp()
            self._add_to_final_tree(record)
        # 如果返回的帧不是栈顶，可能意味着之前的帧已异常退出但未被tracer捕获
        # 在新的模型下，我们依赖 'exception' 事件，所以这里不应发生不匹配
        elif frame_id in self.records_by_frame_id:
            # 这是一个安全回退，理论上不应频繁触发
            self._unwind_stack_to_frame(frame_id)

    def _add_to_final_tree(self, record: CallRecord):
        """
        将一个已完成的调用记录（正常、异常或异常终止）归档到顶级索引中。
        """
        self.call_trees[record["filename"]][record["func_name"]].append(record)

    def finalize(self):
        """
        在跟踪结束时调用，确保所有在栈中的调用都已处理完毕。
        这通常用于处理程序提前终止，导致某些函数没有'return'事件的场景。
        """
        # 使用一个不存在的 frame_id 来清空整个调用栈
        self._unwind_stack_to_frame(-1)

    def get_calls_by_function(self, filename: str, func_name: str) -> List[CallRecord]:
        """根据文件名和函数名查询所有调用记录。"""
        return self.call_trees.get(filename, {}).get(func_name, [])

    def pretty_print_call(self, record: CallRecord, indent: int = 0) -> str:
        """以易于阅读的格式递归打印单个调用记录及其子调用。"""
        prefix = "  " * indent
        duration = (record["end_time"] - record["start_time"]) * 1000 if record["end_time"] > 0 else 0
        args_str = ", ".join(f"{k}={v}" for k, v in record["args"].items())
        output = [
            f"{prefix}📞 Call: {record['func_name']}({args_str}) -> File: {record['filename']}:{record['original_lineno']}"
        ]

        for event in record.get("events", []):
            event_type = event.get("type")
            item = event.get("data")

            if event_type == "line":
                line_event: LineEvent = item
                vars_str = f"  // Debug: {line_event['tracked_vars']}" if line_event["tracked_vars"] else ""
                line_content = line_event["content"].rstrip()
                output.append(f"{prefix}  - L{line_event['line_no']}: {line_content}{vars_str}")
            elif event_type == "call":
                sub_call_record: CallRecord = item
                output.append(self.pretty_print_call(sub_call_record, indent + 1))

        if record["exception"]:
            exc = record["exception"]
            exc_type = exc.get("type", "UnknownException")
            exc_value = exc.get("value", "")
            exc_lineno = exc.get("lineno")
            output.append(f"{prefix}💥 Exception at L{exc_lineno}: {exc_type}: {exc_value} (took {duration:.2f}ms)")
        else:
            output.append(f"{prefix}✔️ Return: {record['return_value']} (took {duration:.2f}ms)")

        return "\n".join(output)

    def generate_report(self, report_path: str):
        """
        将分析结果保存为 JSON 文件。
        在生成报告前，会确保所有在栈中的调用都已处理完毕。
        """
        self.finalize()
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(self.call_trees, f, indent=2, ensure_ascii=False, default=str)
        except (TypeError, IOError) as e:
            print(f"Error writing report file: {e}. Ensure all tracked data is serializable.")
