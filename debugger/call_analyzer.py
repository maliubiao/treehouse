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
    """

    def __init__(self):
        """
        初始化分析器。
        - call_trees: 存储所有函数调用的记录，按 文件名 -> 函数名 组织。
                      这是一个扁平化的调用索引，通过嵌套的 'events' 保留了调用树的层级关系。
                      这种双重结构（扁平索引+嵌套树）可能导致数据在序列化时出现冗余，
                      消费者需要进行去重处理。
        - call_stack: 一个栈，用于实时跟踪当前的函数调用链。
        - records_by_frame_id: 通过 frame_id 快速查找 CallRecord，即使它已不在调用栈上。
        """
        self.call_trees: Dict[str, Dict[str, List[CallRecord]]] = defaultdict(lambda: defaultdict(list))
        self.call_stack: List[CallRecord] = []
        self.records_by_frame_id: Dict[int, CallRecord] = {}

    def _reconcile_stack(self, current_frame_id: int, event_type: str):
        """
        在处理事件前，根据当前 frame_id 同步调用栈。
        如果当前事件的 frame 不在栈顶，说明栈顶的 frame 已因未被跟踪到的返回或
        被捕获的异常而退出（即“隐式退出”）。这是处理异常导致函数退出的关键逻辑。
        """
        if event_type == "call":
            return

        while self.call_stack:
            top_record = self.call_stack[-1]
            if top_record["frame_id"] == current_frame_id:
                break

            popped_record = self.call_stack.pop()

            # 如果记录没有被标记为正常返回或已有异常，则标记为“隐式退出”。
            if not popped_record.get("exception") and popped_record.get("end_time", 0.0) == 0.0:
                # [BUG FIX] 隐式退出的行号应为该帧内最后执行的行，而不是函数定义的第一行。
                # 这对于准确定位异常或退出点至关重要。
                last_line_no = popped_record["original_lineno"]
                if popped_record.get("events"):
                    for event in reversed(popped_record["events"]):
                        if event.get("type") == "line":
                            last_line_no = event["data"]["line_no"]
                            break

                popped_record["exception"] = {
                    "type": "ImplicitExit",
                    "value": "Frame exited without a 'return' or 'exception' event being traced.",
                    "lineno": last_line_no,
                }

            if popped_record.get("end_time", 0.0) == 0.0:
                popped_record["end_time"] = datetime.datetime.now().timestamp()

            # 将被弹出的记录（无论是何种退出方式）归档。
            # 这是确保在异常等非标准流程中，调用数据不丢失的关键。
            self._add_to_final_tree(popped_record)

    def process_event(self, log_data: Union[str, Dict], event_type: str):
        """
        处理单个跟踪事件，并更新调用树。
        这是挂载到 TraceLogic 上的核心处理函数。
        """
        if not isinstance(log_data, dict) or "data" not in log_data:
            return

        data = log_data.get("data", {})
        frame_id = data.get("frame_id")
        if frame_id is None:
            return

        self._reconcile_stack(frame_id, event_type)

        if event_type == "call":
            self._handle_call_event(data)
        elif event_type == "line":
            self._handle_line_event(data)
        elif event_type == "return":
            self._handle_return_event(data)
        elif event_type == "exception":
            self._handle_exception_event(data)

    def _handle_call_event(self, data: Dict):
        """处理函数调用事件：将新记录压入栈"""
        frame_id = data["frame_id"]
        args_dict = {}
        try:
            # 尝试解析参数字符串，如果失败则保留原始字符串
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

        if self.call_stack:
            parent_record = self.call_stack[-1]
            parent_record["events"].append({"type": "call", "data": record})

        self.call_stack.append(record)
        self.records_by_frame_id[frame_id] = record

    def _handle_line_event(self, data: Dict):
        """处理行执行事件"""
        if not self.call_stack:
            return

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
        """处理函数返回事件：这是一个明确的“离开帧”信号"""
        frame_id = data["frame_id"]
        if self.call_stack and self.call_stack[-1]["frame_id"] == frame_id:
            record = self.call_stack.pop()
            record["return_value"] = data["return_value"]
            record["end_time"] = datetime.datetime.now().timestamp()
            self._add_to_final_tree(record)

    def _handle_exception_event(self, data: Dict):
        """
        处理异常事件：记录异常信息。
        异常事件可能在栈的任何深度发生，因此通过 frame_id 直接查找并更新记录，
        而不是假定它在栈顶。帧的终结交由 `return` 或 `_reconcile_stack` 处理。
        """
        if not self.call_stack:
            return

        frame_id = data["frame_id"]
        if frame_id in self.records_by_frame_id:
            record = self.records_by_frame_id[frame_id]
            record["exception"] = {
                "type": data["exc_type"],
                "value": data["exc_value"],
                "lineno": data["lineno"],
            }

    def _add_to_final_tree(self, record: CallRecord):
        """

        将一个已完成的调用记录（正常、异常或隐式退出）归档到顶级索引中。
        这个方法是整个分析器的关键枢纽，它创建了一个扁平化的、可直接查询的
        函数调用索引。
        """
        # 注意：此处没有检查重复。如果分析器逻辑有误，可能导致同一个调用被添加多次。
        # 消费方（如 UnitTestGeneratorDecorator）需要具备去重能力以保证健壮性。
        self.call_trees[record["filename"]][record["func_name"]].append(record)

        # 暂不删除，因为可能有延迟的事件（如exception）需要访问它。
        # 清理可以在整个跟踪结束后进行。
        # if record["frame_id"] in self.records_by_frame_id:
        #     del self.records_by_frame_id[record["frame_id"]]

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
                vars_str = f"  // Vars: {line_event['tracked_vars']}" if line_event["tracked_vars"] else ""
                line_content = line_event["content"].rstrip()
                output.append(f"{prefix}  - L{line_event['line_no']}: {line_content}{vars_str}")
            elif event_type == "call":
                sub_call_record: CallRecord = item
                output.append(self.pretty_print_call(sub_call_record, indent + 1))

        if record["exception"]:
            exc = record["exception"]
            output.append(
                f"{prefix}💥 Exception at L{exc['lineno']}: {exc['type']}: {exc['value']} (took {duration:.2f}ms)"
            )
        else:
            output.append(f"{prefix}✔️ Return: {record['return_value']} (took {duration:.2f}ms)")

        return "\n".join(output)

    def generate_report(self, report_path: str):
        """
        将分析结果保存为 JSON 文件。
        在生成报告前，会确保所有在栈中的调用都已处理完毕。
        """
        # 使用一个无效的 frame_id 来清空整个调用栈，确保所有未正常关闭的帧都被处理和归档。
        self._reconcile_stack(-1, "eof")

        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(self.call_trees, f, indent=2, ensure_ascii=False, default=str)
        except (TypeError, IOError) as e:
            print(f"Error writing report file: {e}. Ensure all tracked data is serializable.")
