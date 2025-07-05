import datetime
import json
import logging
import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional, TypedDict, Union

from colorama import Fore, Style


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
    thread_id: int
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
    分析跟踪事件，构建函数调用树，并提供可选的实时日志输出。

    该分析器旨在捕获足够详细的信息，以便于后续自动生成单元测试。
    此版本采用了更健壮的堆栈管理和异常处理逻辑，以精确地模型化Python的执行流程。
    新增的 verbose 模式可以在程序执行时，实时打印带缩进的函数调用、返回和异常日志。
    此版本增加了多线程支持，为每个线程维护一个独立的调用栈。
    """

    def __init__(self, verbose: bool = False):
        """
        初始化分析器。

        Args:
            verbose: 如果为 True, 将在标准输出中实时打印详细的、带缩进的跟踪日志。
        """
        self.call_trees: Dict[str, Dict[str, List[CallRecord]]] = defaultdict(lambda: defaultdict(list))
        # 为每个线程维护一个独立的调用栈
        self.call_stacks: Dict[int, List[CallRecord]] = defaultdict(list)
        self.records_by_frame_id: Dict[int, CallRecord] = {}
        self.verbose = verbose
        self.colors = {"call": Fore.BLUE, "return": Fore.GREEN, "exception": Fore.RED, "info": Fore.YELLOW}
        # 锁，用于保护 verbose 模式下的 print 输出，防止多线程输出混乱
        self.verbose_lock = threading.Lock()

    def _handle_exit_event(self, frame_id: int, is_clean_exit: bool, event_data: Dict, thread_id: int):
        """
        增强的退出事件处理：支持在栈中任意位置匹配帧ID
        """
        stack = self.call_stacks[thread_id]
        if not stack:
            return

        # 首先检查栈顶是否匹配
        top_record = stack[-1]
        if top_record["frame_id"] == frame_id:
            # 正常情况：栈顶匹配
            self._process_matched_exit(top_record, is_clean_exit, event_data, stack)
            return

        # 栈顶不匹配时，搜索整个调用栈
        matched_index = -1
        for i in range(len(stack) - 1, -1, -1):
            if stack[i]["frame_id"] == frame_id:
                matched_index = i
                break

        if matched_index == -1:
            # 没有找到匹配的帧
            if self.verbose:
                with self.verbose_lock:
                    stack_ids = [str(r["frame_id"]) for r in stack]
                    print(
                        f"{self.colors['info']}⚠️ UNMATCHED EXIT: Frame {frame_id} not found in stack: {', '.join(stack_ids)} [EID:{event_data.get('event_id')}]{Style.RESET_ALL}"
                    )
            return

        # 处理找到的匹配帧
        self._process_deep_exit(stack, matched_index, is_clean_exit, event_data)

    def _process_matched_exit(self, record: CallRecord, is_clean_exit: bool, event_data: Dict, stack: List[CallRecord]):
        """处理栈顶匹配的正常退出"""
        if self.verbose:
            with self.verbose_lock:
                indent = "  " * (len(stack) - 1)
                func_name = record["func_name"]
                event_id = event_data.get("event_id", -1)
                if is_clean_exit:
                    return_value = event_data.get("return_value")
                    return_repr = repr(return_value)
                    if len(return_repr) > 120:
                        return_repr = return_repr[:120] + "..."
                    print(
                        f"{self.colors['return']}{indent}✔️ RETURN from {func_name} (FrameID:{record['frame_id']}) -> {return_repr} "
                        f"[EID:{event_id}]{Style.RESET_ALL}"
                    )
                else:
                    exc_type = event_data.get("exc_type")
                    exc_value = str(event_data.get("exc_value"))
                    print(
                        f"{self.colors['exception']}{indent}💥 EXCEPTION in {func_name} (FrameID:{record['frame_id']}): "
                        f"{exc_type}: {exc_value} [EID:{event_id}]{Style.RESET_ALL}"
                    )

        # 弹出正确的帧进行终结。
        stack.pop()
        if not record.get("end_time"):
            record["end_time"] = datetime.datetime.now().timestamp()

        if is_clean_exit:
            record["return_value"] = event_data.get("return_value")
            record["exception"] = None
        else:
            record["exception"] = {
                "type": event_data.get("exc_type"),
                "value": str(event_data.get("exc_value")),
                "lineno": event_data.get("lineno"),
            }
            record["return_value"] = None

        # 只有当这个调用是顶级调用时（即，没有父级），才将其添加到最终的树中。
        if not stack:
            self._add_to_final_tree(record)

    def _process_deep_exit(self, stack: List[CallRecord], index: int, is_clean_exit: bool, event_data: Dict):
        """处理在栈深处找到的匹配帧的退出"""
        record = stack[index]
        if self.verbose:
            with self.verbose_lock:
                indent = "  " * index
                func_name = record["func_name"]
                event_id = event_data.get("event_id", -1)
                depth = len(stack) - index
                if is_clean_exit:
                    return_value = event_data.get("return_value")
                    return_repr = (
                        repr(return_value)[:120] + "..." if len(repr(return_value)) > 120 else repr(return_value)
                    )
                    print(
                        f"{self.colors['return']}{indent}⚠️ DEEP RETURN from {func_name} (FrameID:{record['frame_id']}, depth={depth}) -> {return_repr} "
                        f"[EID:{event_id}]{Style.RESET_ALL}"
                    )
                else:
                    exc_type = event_data.get("exc_type")
                    exc_value = str(event_data.get("exc_value"))
                    print(
                        f"{self.colors['exception']}{indent}⚠️ DEEP EXCEPTION in {func_name} (FrameID:{record['frame_id']}, depth={depth}): "
                        f"{exc_type}: {exc_value} [EID:{event_id}]{Style.RESET_ALL}"
                    )

        # 标记结束时间
        if not record.get("end_time"):
            record["end_time"] = datetime.datetime.now().timestamp()

        # 设置返回或异常信息
        if is_clean_exit:
            record["return_value"] = event_data.get("return_value")
            record["exception"] = None
        else:
            record["exception"] = {
                "type": event_data.get("exc_type"),
                "value": str(event_data.get("exc_value")),
                "lineno": event_data.get("lineno"),
            }
            record["return_value"] = None

        # 从栈中移除该帧及其上方的所有帧
        removed_frames = stack[index:]
        del stack[index:]

        # 处理被移除的未完成帧
        for frame in removed_frames:
            if frame is not record:  # 跳过当前记录（已处理）
                if not frame.get("end_time"):
                    frame["end_time"] = datetime.datetime.now().timestamp()
                if not frame.get("exception"):
                    frame["exception"] = {
                        "type": "ForcedUnwind",
                        "value": "Function terminated early due to deep stack unwind",
                        "lineno": None,
                    }

        # 如果移除后栈为空，添加到最终树
        if not stack:
            self._add_to_final_tree(record)

    def process_event(self, log_data: Union[str, Dict], event_type: str):
        """
        处理单个跟踪事件，并更新相应线程的调用树。
        这是挂载到 AnalyzableTraceLogic 上的核心处理函数。

        新增: 忽略以 "DEBUG_STACK" 开头的调试事件
        """
        if not isinstance(log_data, dict) or "data" not in log_data:
            return

        data = log_data.get("data", {})
        frame_id = data.get("frame_id")
        thread_id = data.get("thread_id")

        if frame_id is None or thread_id is None:
            # 必须有 frame_id 和 thread_id 才能处理
            return

        # 'exception' 和 'return' 都是帧的终结事件。
        if event_type == "exception" or event_type == "return":
            self._handle_exit_event(
                frame_id, is_clean_exit=(event_type == "return"), event_data=data, thread_id=thread_id
            )
        elif event_type == "call":
            self._handle_call_event(data, thread_id)
        elif event_type == "line":
            self._handle_line_event(data, thread_id)

    def _handle_call_event(self, data: Dict, thread_id: int):
        """处理函数调用事件：将新记录压入指定线程的栈（PUSH操作）。"""
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
            "thread_id": thread_id,
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

        stack = self.call_stacks[thread_id]

        if self.verbose:
            with self.verbose_lock:
                indent = "  " * len(stack)
                args_str = ", ".join(f"{k}={v}" for k, v in record["args"].items())
                func_name = record["func_name"]
                location = f"{record['filename']}:{record['original_lineno']}"
                event_id = data.get("event_id", -1)
                print(
                    f"{self.colors['call']}{indent}📞 CALL: {func_name}({args_str}) at {location} "
                    f"[FrameID:{frame_id}] [TID:{thread_id}] [EID:{event_id}]{Style.RESET_ALL}"
                )

        # 如果调用栈不为空，将此调用作为子事件添加到父记录中。
        if stack:
            parent_record = stack[-1]
            parent_record["events"].append({"type": "call", "data": record})

        stack.append(record)
        self.records_by_frame_id[frame_id] = record

    def _handle_line_event(self, data: Dict, thread_id: int):
        """处理行执行事件，附加到指定线程栈顶的调用记录中。"""
        stack = self.call_stacks[thread_id]
        if not stack:
            return

        # 确保事件属于当前栈顶的帧。
        current_record = stack[-1]
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
        此方法本身是线程安全的，因为事件队列保证了串行处理。
        """
        self.call_trees[record["filename"]][record["func_name"]].append(record)

    def finalize(self):
        """
        在跟踪结束时调用，确保所有线程中仍在栈内的调用都被处理完毕。
        这主要用于处理程序提前终止，导致某些函数没有'return'或'exception'事件的场景。
        """
        for thread_id, stack in self.call_stacks.items():
            while stack:
                record = stack.pop()
                if not record.get("end_time"):
                    record["end_time"] = datetime.datetime.now().timestamp()

                if not record.get("exception"):
                    record["exception"] = {
                        "type": "IncompleteExecution",
                        "value": "The trace ended before this function could return or raise an exception.",
                        "lineno": None,
                    }

                # 只有顶层调用（即栈清空时的最后一个）才被添加到最终树中
                if not stack:
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
            f"{prefix}📞 Call: {record['func_name']}({args_str}) -> File: {record['filename']}:{record['original_lineno']} [FrameID:{record['frame_id']}]"
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
