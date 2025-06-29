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
    start_lineno: int
    caller_lineno: Optional[int]

    # 调用与返回
    args: Dict[str, Any]
    return_value: Any
    exception: Optional[Dict[str, Any]]

    # 时间与内容
    start_time: float
    end_time: float
    # A unified list of events to preserve the exact execution order.
    # Each item is a dict like {'type': 'line'/'call', 'data': LineEvent/CallRecord}
    events: List[Dict]


class CallAnalyzer:
    """
    分析跟踪事件，构建函数调用树。
    该分析器旨在捕获足够详细的信息，以便于后续自动生成单元测试。
    """

    def __init__(self):
        """
        初始化分析器。
        - call_trees: 存储所有顶层函数调用的记录，按 文件名 -> 函数名 组织。
        - call_stack: 一个栈，用于实时跟踪当前的函数调用链。
        - records_by_frame_id: 通过 frame_id 快速查找 CallRecord。
        """
        self.call_trees: Dict[str, Dict[str, List[CallRecord]]] = defaultdict(lambda: defaultdict(list))
        self.call_stack: List[CallRecord] = []
        self.records_by_frame_id: Dict[int, CallRecord] = {}

    def _reconcile_stack(self, current_frame_id: int, event_type: str):
        """
        在处理事件前，根据当前 frame_id 同步调用栈。
        如果当前事件的 frame 不在栈顶，说明栈顶的 frame 已因未处理的异常而退出。
        """
        # 'call' 事件是进入新帧，不应触发回溯。
        if event_type == "call":
            return

        while self.call_stack:
            top_record = self.call_stack[-1]
            if top_record["frame_id"] == current_frame_id:
                # 栈顶与当前事件的帧匹配，状态一致
                break

            # 栈顶与当前事件的帧不匹配，意味着栈顶的帧已经隐式退出（未捕获的异常）
            popped_record = self.call_stack.pop()

            # 如果记录中没有显式记录异常，则标记为未处理异常退出
            if not popped_record["exception"]:
                last_line_no = popped_record["start_lineno"]
                # Find the last line number from the unified events list
                if popped_record.get("events"):
                    for event in reversed(popped_record["events"]):
                        if event.get("type") == "line":
                            last_line_no = event["data"]["line_no"]
                            break

                popped_record["exception"] = {
                    "type": "UnhandledException",
                    "value": "Frame exited implicitly without a 'return' or 'exception' event.",
                    "lineno": last_line_no,
                }

            popped_record["end_time"] = datetime.datetime.now().timestamp()
            self._add_to_final_tree(popped_record)

    def process_event(self, log_data: Union[str, Dict], event_type: str):
        """
        处理单个跟踪事件，并更新调用树。
        这是挂载到 TraceLogic 上的核心处理函数。

        Args:
            log_data: 从 TraceLogic 传来的日志数据。
            event_type: 事件类型 (e.g., 'call', 'return', 'line', 'exception')。
        """
        if not isinstance(log_data, dict) or "data" not in log_data:
            return

        data = log_data.get("data", {})
        frame_id = data.get("frame_id")
        if frame_id is None:
            return

        # 核心修复：在处理任何事件之前，先同步调用栈状态
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
            # The args string is like "arg1=val1, arg2=val2"
            if isinstance(data.get("args"), str) and data["args"]:
                # This is a simple parser, might fail on complex reprs
                # A more robust solution would require passing structured args
                args_list = data["args"].split(", ")
                for arg_pair in args_list:
                    if "=" in arg_pair:
                        key, value_str = arg_pair.split("=", 1)
                        args_dict[key.strip()] = value_str.strip()
            elif isinstance(data.get("args"), list) and not data["args"]:
                args_dict = {}
            else:
                args_dict = {"raw_args": data.get("args", "")}
        except (ValueError, TypeError):
            args_dict = {"raw_args": data.get("args", "")}

        record: CallRecord = {
            "frame_id": frame_id,
            "func_name": data["func"],
            "filename": data["filename"],
            "original_filename": data["original_filename"],
            "start_lineno": data["lineno"],
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
        # 确保事件属于当前栈顶的帧
        if current_record["frame_id"] == data["frame_id"]:
            line_event: LineEvent = {
                "line_no": data["lineno"],
                "content": data.get("raw_line", data["line"]),
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
        """处理异常事件：只记录异常信息，不改变调用栈"""
        if not self.call_stack:
            return

        frame_id = data["frame_id"]
        # 异常事件应归属于栈顶的帧
        record = self.call_stack[-1]
        if record and record["frame_id"] == frame_id:
            record["exception"] = {
                "type": data["exc_type"],
                "value": data["exc_value"],
                "lineno": data["lineno"],
            }
            # 注意：此处不再弹出堆栈。帧的终结由 _reconcile_stack 或 return/unwind 事件处理。

    def _add_to_final_tree(self, record: CallRecord):
        """将一个已完成的调用记录（正常或异常结束）归档"""
        # 如果是顶层调用，则添加到最终的树中
        if not self.call_stack:
            self.call_trees[record["filename"]][record["func_name"]].append(record)

        # 从快速查找字典中移除，释放内存
        if record["frame_id"] in self.records_by_frame_id:
            del self.records_by_frame_id[record["frame_id"]]

    def get_calls_by_function(self, filename: str, func_name: str) -> List[CallRecord]:
        """
        根据文件名和函数名查询所有调用记录。
        """
        return self.call_trees.get(filename, {}).get(func_name, [])

    def pretty_print_call(self, record: CallRecord, indent: int = 0) -> str:
        """
        以易于阅读的格式递归打印单个调用记录及其子调用。
        """
        prefix = "  " * indent
        duration = (record["end_time"] - record["start_time"]) * 1000 if record["end_time"] > 0 else 0
        args_str = ", ".join(f"{k}={v}" for k, v in record["args"].items())
        output = [
            f"{prefix}📞 Call: {record['func_name']}({args_str}) -> File: {record['filename']}:{record['start_lineno']}"
        ]

        # Iterate over the unified events list, which preserves execution order. No sorting needed.
        for event in record.get("events", []):
            event_type = event.get("type")
            item = event.get("data")

            if event_type == "line":
                line_event = item
                vars_str = f"  // Vars: {line_event['tracked_vars']}" if line_event["tracked_vars"] else ""
                line_content = line_event["content"].rstrip()
                output.append(f"{prefix}  - L{line_event['line_no']}: {line_content}{vars_str}")
            elif event_type == "call":
                sub_call = item
                output.append(self.pretty_print_call(sub_call, indent + 1))

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
        """
        report_data = {}
        for filename, funcs in self.call_trees.items():
            report_data[filename] = {}
            for func_name, records in funcs.items():
                report_data[filename][func_name] = records

        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
            print(f"分析报告已生成: {report_path}")
        except TypeError as e:
            print(f"生成报告失败: {e}. 确保所有被跟踪的数据都是JSON可序列化的。")
        except Exception as e:
            print(f"生成报告时发生未知错误: {e}")
