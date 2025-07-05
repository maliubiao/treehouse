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
    此版本采用了更健壮的堆栈管理和异常处理逻辑，以精确地模型化Python的执行流程。
    """

    def __init__(self):
        """
        初始化分析器。
        - call_trees: 存储所有已完成的函数调用记录，按 文件名 -> 函数名 组织。
        - call_stack: 一个实时栈，跟踪当前的函数调用链。每个元素都是一个 CallRecord。
        - records_by_frame_id: 通过 frame_id 快速查找任何已创建的 CallRecord，无论它是否还在调用栈上。
        """
        self.call_trees: Dict[str, Dict[str, List[CallRecord]]] = defaultdict(lambda: defaultdict(list))
        self.call_stack: List[CallRecord] = []
        self.records_by_frame_id: Dict[int, CallRecord] = {}

    def _handle_exit_event(self, frame_id: int, is_clean_exit: bool, event_data: Dict):
        """
        终结位于调用栈顶的帧。

        此方法精确处理Python的 `return` 或 `exception` 事件。它假定Python的追踪器
        会为每个被异常回溯的帧都触发一个相应的事件。因此，我们只处理与栈顶匹配的帧。

        Args:
            frame_id: 目标帧的ID，即触发`return`或`exception`事件的帧。
            is_clean_exit: 如果为 True，表示是`return`事件；否则是`exception`事件。
            event_data: 与事件相关的原始数据 (包含返回值或异常详情)。
        """
        if not self.call_stack:
            return

        # 目标帧必须在栈顶。如果不是，说明我们的调用栈跟踪逻辑出现了偏差，
        # 或者是事件流本身有问题。在单线程同步执行中，这不应该发生。
        record = self.call_stack[-1]
        if record["frame_id"] != frame_id:
            return

        # 弹出正确的帧进行终结。
        record = self.call_stack.pop()
        if not record.get("end_time"):
            record["end_time"] = datetime.datetime.now().timestamp()

        if is_clean_exit:
            record["return_value"] = event_data.get("return_value")
            # 一个正常返回的函数不能有未处理的异常。
            # 这适用于函数内部的 try/except 吞掉了异常的场景。
            record["exception"] = None
        else:
            record["exception"] = {
                "type": event_data.get("exc_type"),
                "value": str(event_data.get("exc_value")),
                "lineno": event_data.get("lineno"),
            }
            record["return_value"] = None

        # 只有当这个调用是顶级调用时（即，没有父级），才将其添加到最终的树中。
        # 子调用已经作为事件嵌套在其父调用中。
        if not self.call_stack:
            self._add_to_final_tree(record)

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

        # 'exception' 和 'return' 都是帧的终结事件。
        if event_type == "exception" or event_type == "return":
            self._handle_exit_event(frame_id, is_clean_exit=(event_type == "return"), event_data=data)
        elif event_type == "call":
            self._handle_call_event(data)
        elif event_type == "line":
            self._handle_line_event(data)

    def _handle_call_event(self, data: Dict):
        """处理函数调用事件：将新记录压入栈（PUSH操作）。"""
        frame_id = data["frame_id"]
        args_dict = {}
        try:
            # 解析参数
            raw_args = data.get("args")
            if isinstance(raw_args, str) and raw_args:
                args_list = raw_args.split(", ")
                for arg_pair in args_list:
                    if "=" in arg_pair:
                        key, value_str = arg_pair.split("=", 1)
                        args_dict[key.strip()] = value_str.strip()
            elif isinstance(raw_args, dict):
                args_dict = raw_args
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

        # 如果调用栈不为空，将此调用作为子事件添加到父记录中。
        # 由于`record`是可变的，后续对`record`的修改（如添加返回值）会反映在此处。
        if self.call_stack:
            parent_record = self.call_stack[-1]
            parent_record["events"].append({"type": "call", "data": record})

        self.call_stack.append(record)
        self.records_by_frame_id[frame_id] = record

    def _handle_line_event(self, data: Dict):
        """处理行执行事件，附加到栈顶的调用记录中。"""
        if not self.call_stack:
            return

        # 确保事件属于当前栈顶的帧。
        current_record = self.call_stack[-1]
        if current_record["frame_id"] == data["frame_id"]:
            line_event: LineEvent = {
                "line_no": data["lineno"],
                "content": data.get("raw_line", data.get("line", "")),
                "timestamp": datetime.datetime.now().timestamp(),
                "tracked_vars": data.get("tracked_vars", {}),
            }
            current_record["events"].append({"type": "line", "data": line_event})

    def _add_to_final_tree(self, record: CallRecord):
        """
        将一个已完成的顶级调用记录归档到最终的调用树中。
        """
        self.call_trees[record["filename"]][record["func_name"]].append(record)

    def finalize(self):
        """
        在跟踪结束时调用，确保所有仍在栈中的调用都被处理完毕。
        这主要用于处理程序提前终止，导致某些函数没有'return'或'exception'事件的场景。
        """
        while self.call_stack:
            record = self.call_stack.pop()
            if not record.get("end_time"):
                record["end_time"] = datetime.datetime.now().timestamp()

            if not record.get("exception"):
                record["exception"] = {
                    "type": "IncompleteExecution",
                    "value": "The trace ended before this function could return or raise an exception.",
                    "lineno": None,
                }

            # Only top-level calls (which would be the last ones on the stack)
            # are added to the final tree.
            if not self.call_stack:
                self._add_to_final_tree(record)

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
            exc_lineno_str = f" at L{exc.get('lineno')}" if exc.get("lineno") else ""
            output.append(f"{prefix}💥 Exception{exc_lineno_str}: {exc_type}: {exc_value} (took {duration:.2f}ms)")
        else:
            output.append(f"{prefix}✔️ Return: {repr(record['return_value'])} (took {duration:.2f}ms)")

        return "\n".join(output)

    def generate_report(self, report_path: str):
        """
        将分析结果保存为 JSON 文件。
        在生成报告前，会确保所有在栈中的调用都已处理完毕。
        """
        self.finalize()
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                # 只保存顶级调用树，因为所有子调用都已嵌套在内
                json.dump(self.call_trees, f, indent=2, ensure_ascii=False, default=str)
        except (TypeError, IOError) as e:
            print(f"Error writing report file: {e}. Ensure all tracked data is serializable.")
