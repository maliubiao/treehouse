import json
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, TypedDict

try:
    import networkx as nx
except ImportError as exc:
    raise ImportError("networkx is required. Please install it with `pip install networkx`.") from exc


class TraceTypes(str, Enum):
    CALL = "call"
    RETURN = "return"
    LINE = "line"
    EXCEPTION = "exception"
    PARTIAL = "partial"


class IndexEntry(TypedDict):
    type: str
    position: int
    frame_id: int
    filename: str
    lineno: int
    func: str


class FrameInfo(TypedDict):
    filename: str
    lineno: int
    func: str
    start_pos: int
    end_pos: Optional[int]
    status: Optional[Literal["return", "exception", "partial"]]


class ReferenceInfo(TypedDict):
    filename: str
    lineno: int
    func: str
    type: str


class SiblingConfig(TypedDict, total=False):
    functions: List[str]
    before: Optional[int]
    after: Optional[int]


TRACE_LOG_NAME = "trace.log"
ROOT_FRAME_ID = 0


class _CallStackState:
    """封装调用栈状态和缓存，用于图构建过程"""

    def __init__(self):
        self.stack: List[int] = []
        self.frame_data_cache: Dict[int, IndexEntry] = {}
        self.partial_frames: Set[int] = set()
        self.all_frame_ids: Set[int] = set()


class GraphTraceLogExtractor:
    def __init__(self, log_file: str = None):
        self.log_file: Path = Path(log_file or TRACE_LOG_NAME)
        self.index_file: Path = self.log_file.with_suffix(self.log_file.suffix + ".index")

        if not self.log_file.exists():
            raise FileNotFoundError(f"Log file not found: {self.log_file}")
        if not self.index_file.exists():
            raise FileNotFoundError(f"Index file not found: {self.index_file}")

        self._graph: Optional[nx.DiGraph] = None
        self._frames: Dict[int, FrameInfo] = {}
        self._file_line_to_frames: Dict[Tuple[str, int], List[int]] = defaultdict(list)

    def _parse_index_line(self, line: str) -> Optional[IndexEntry]:
        try:
            entry = json.loads(line.strip())
            return entry if isinstance(entry, dict) and "type" in entry else None
        except json.JSONDecodeError:
            return None

    def _load_index_entries(self) -> List[IndexEntry]:
        """加载并排序索引条目"""
        entries = []
        with open(self.index_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.startswith("#"):
                    if entry := self._parse_index_line(line):
                        entries.append(entry)
        return sorted(entries, key=lambda e: e["position"])

    def _add_frame_node(self, entry: IndexEntry, parent_id: int):
        """添加新的帧节点到图中"""
        frame_id = entry["frame_id"]
        self._graph.add_node(
            frame_id,
            filename=entry["filename"],
            lineno=entry["lineno"],
            func=entry.get("func", "N/A"),
            start_pos=entry["position"],
            end_pos=None,
            status=None,
        )
        self._graph.add_edge(parent_id, frame_id)
        self._file_line_to_frames[(entry["filename"], entry["lineno"])].append(frame_id)

    def _process_call_event(self, entry: IndexEntry, state: _CallStackState):
        """处理调用事件"""
        parent_id = state.stack[-1] if state.stack else ROOT_FRAME_ID
        self._add_frame_node(entry, parent_id)
        state.frame_data_cache[entry["frame_id"]] = entry
        state.all_frame_ids.add(entry["frame_id"])
        state.stack.append(entry["frame_id"])

    def _process_return_event(self, entry: IndexEntry, state: _CallStackState):
        """处理返回/异常事件"""
        frame_id = entry["frame_id"]
        if frame_id in state.frame_data_cache:
            start_entry = state.frame_data_cache[frame_id]
            self._update_frame_info(frame_id, start_entry, entry["position"], entry["type"])

        # 弹出栈直到找到匹配的帧
        if frame_id in state.stack:
            while state.stack:
                popped_id = state.stack.pop()
                if popped_id == frame_id:
                    break
                state.partial_frames.add(popped_id)

    def _update_frame_info(self, frame_id: int, start_entry: IndexEntry, end_pos: int, status: str):
        """更新帧的结束位置和状态"""
        frame_info = {
            "filename": start_entry["filename"],
            "lineno": start_entry["lineno"],
            "func": start_entry.get("func", "N/A"),
            "start_pos": start_entry["position"],
            "end_pos": end_pos,
            "status": status,
        }
        self._frames[frame_id] = frame_info

        if frame_id in self._graph:
            self._graph.nodes[frame_id]["end_pos"] = end_pos
            self._graph.nodes[frame_id]["status"] = status

    def _mark_partial_frames(self, state: _CallStackState):
        """标记未关闭的帧为部分帧"""
        for frame_id in state.partial_frames:
            if frame_id in state.frame_data_cache:
                start_entry = state.frame_data_cache[frame_id]
                self._update_frame_info(frame_id, start_entry, None, TraceTypes.PARTIAL.value)

    def _detect_cycles(self):
        """检测图中的环并记录到日志文件"""
        try:
            visited = set()
            rec_stack = set()
            parent_map = {}

            def dfs(node, parent=None):
                visited.add(node)
                rec_stack.add(node)
                parent_map[node] = parent

                for neighbor in self._graph.successors(node):
                    if neighbor not in visited:
                        if dfs(neighbor, node):
                            return True
                    elif neighbor in rec_stack:
                        self._log_cycle(neighbor, node, parent_map)
                        return True

                rec_stack.remove(node)
                return False

            for node in list(self._graph.nodes):
                if node != ROOT_FRAME_ID and node not in visited:
                    if dfs(node):
                        break
        except Exception as e:
            print(f"WARNING: Error during cycle detection: {str(e)}")

    def _log_cycle(self, cycle_start: int, current: int, parent_map: Dict[int, int]):
        """记录环的详细信息到日志文件"""
        cycle_path = []
        temp = current

        while temp != cycle_start and temp is not None:
            cycle_path.append(temp)
            temp = parent_map.get(temp)

        if temp is not None:
            cycle_path.append(cycle_start)
            cycle_path.reverse()

            cycle_info = []
            for i, frame_id in enumerate(cycle_path):
                node_data = self._graph.nodes[frame_id]
                cycle_info.append(
                    f"Cycle Node {i + 1}: frame_id={frame_id}\n"
                    f"  Function: {node_data.get('func', 'N/A')}\n"
                    f"  Location: {node_data.get('filename', 'N/A')}:{node_data.get('lineno', 'N/A')}\n"
                    f"  Log Position: {node_data.get('start_pos', 'N/A')}"
                )

            error_report = (
                "ERROR: Cycle detected in call graph!\n"
                f"Log File: {self.log_file}\n"
                f"Index File: {self.index_file}\n"
                "Cycle Path:\n" + "\n".join(cycle_info) + "\n\n"
                "This cycle suggests incorrect logging behavior."
            )

            cycle_log_file = self.log_file.with_suffix(".cycle.log")
            with open(cycle_log_file, "w", encoding="utf-8") as f:
                f.write(error_report)

            print(f"WARNING: Cycle detected! Details written to {cycle_log_file}")

    def _build_graph(self):
        if self._graph is not None:
            return

        self._graph = nx.DiGraph()
        self._frames.clear()
        self._file_line_to_frames.clear()

        # 添加虚拟根节点
        self._graph.add_node(
            ROOT_FRAME_ID, filename="<root>", lineno=0, func="<root>", start_pos=0, end_pos=0, status=None
        )

        index_entries = self._load_index_entries()
        state = _CallStackState()

        for entry in index_entries:
            frame_id = entry["frame_id"]
            type_tag = entry["type"]

            if type_tag == TraceTypes.CALL:
                self._process_call_event(entry, state)
            elif type_tag in (TraceTypes.RETURN, TraceTypes.EXCEPTION):
                self._process_return_event(entry, state)

        # 标记部分帧并检测环
        state.partial_frames.update(set(state.stack))
        self._mark_partial_frames(state)
        self._detect_cycles()

    def _create_reference_event(self, node_id: int, event_type: str) -> ReferenceInfo:
        node_data = self._graph.nodes[node_id]
        return {
            "filename": node_data["filename"],
            "lineno": node_data["lineno"],
            "func": node_data.get("func", "N/A"),
            "type": event_type,
        }

    def _get_descendant_events(self, frame_id: int) -> List[ReferenceInfo]:
        events = []
        stack: List[Tuple[int, int, Tuple[int, ...]]] = [(frame_id, 0, (frame_id,))]
        visited: Set[int] = set()

        while stack:
            node_id, state, path = stack.pop()

            if state == 0:  # 处理调用事件
                events.append(self._create_reference_event(node_id, TraceTypes.CALL.value))
                stack.append((node_id, 1, path))  # 标记为待处理结束事件

                # 按时间顺序处理子节点
                children = sorted(
                    self._graph.successors(node_id),
                    key=lambda cid: self._graph.nodes[cid].get("start_pos", 0),
                    reverse=True,
                )

                for child_id in children:
                    if child_id not in path:  # 避免环
                        stack.append((child_id, 0, path + (child_id,)))
            else:  # state == 1, 处理结束事件
                status = self._graph.nodes[node_id].get("status", TraceTypes.PARTIAL.value)
                events.append(self._create_reference_event(node_id, status))
                visited.add(node_id)

        return events

    def _get_relevant_frames(self, frame_id: int, next_siblings: Optional[int]) -> List[int]:
        """获取目标帧及其兄弟帧"""
        relevant_frames = [frame_id]

        if next_siblings and next_siblings > 0:
            predecessors = list(self._graph.predecessors(frame_id))
            if predecessors and predecessors[0] != ROOT_FRAME_ID:
                parent_id = predecessors[0]
                target_start_pos = self._graph.nodes[frame_id]["start_pos"]

                siblings = [
                    sid
                    for sid in self._graph.successors(parent_id)
                    if sid != frame_id and self._graph.nodes[sid]["start_pos"] > target_start_pos
                ]

                sorted_siblings = sorted(siblings, key=lambda s: self._graph.nodes[s]["start_pos"])
                relevant_frames.extend(sorted_siblings[:next_siblings])

        return relevant_frames

    def _get_log_content(self, start_pos: int, end_pos: Optional[int]) -> str:
        """从日志文件中提取指定范围的内容"""
        if end_pos is not None and end_pos <= start_pos:
            return ""

        with open(self.log_file, "r", encoding="utf-8") as f:
            f.seek(start_pos)
            return f.read(end_pos - start_pos if end_pos else None)

    def _lookup_by_frame_id(
        self, frame_id: int, next_siblings: Optional[int] = None
    ) -> Tuple[List[str], List[List[ReferenceInfo]]]:
        if frame_id not in self._graph or frame_id == ROOT_FRAME_ID:
            return [], []

        relevant_frames = self._get_relevant_frames(frame_id, next_siblings)
        sorted_frames = sorted(relevant_frames, key=lambda fid: self._graph.nodes[fid]["start_pos"])

        # 计算日志范围
        start_pos = self._graph.nodes[sorted_frames[0]]["start_pos"]
        valid_end_positions = [
            self._graph.nodes[fid].get("end_pos")
            for fid in sorted_frames
            if self._graph.nodes[fid].get("end_pos") is not None
        ]
        end_pos = max(valid_end_positions) if valid_end_positions else None

        log_content = self._get_log_content(start_pos, end_pos)
        references = self._build_reference_chain(sorted_frames, frame_id)

        return [log_content], [references]

    def _build_reference_chain(self, frame_ids: List[int], target_frame_id: int) -> List[ReferenceInfo]:
        """为帧列表构建引用链"""
        references = []

        for fid in frame_ids:
            if fid == target_frame_id:
                references.extend(self._get_descendant_events(fid))
            else:
                references.append(self._create_reference_event(fid, TraceTypes.CALL.value))
                if status := self._graph.nodes[fid].get("status"):
                    references.append(self._create_reference_event(fid, status))

        return references

    def _get_sibling_frames(self, frame_id: int, sibling_config: SiblingConfig) -> List[int]:
        """根据配置获取兄弟帧"""
        relevant_frames = [frame_id]
        predecessors = list(self._graph.predecessors(frame_id))

        if not predecessors:
            return relevant_frames

        parent_id = predecessors[0]
        target_data = self._graph.nodes[frame_id]
        target_start_pos = target_data["start_pos"]

        all_siblings = [
            sid
            for sid in self._graph.successors(parent_id)
            if sid != frame_id and self._graph.nodes[sid].get("func") in sibling_config["functions"]
        ]

        # 获取之前的兄弟帧
        before_siblings = sorted(
            [s for s in all_siblings if self._graph.nodes[s]["start_pos"] < target_start_pos],
            key=lambda s: self._graph.nodes[s]["start_pos"],
            reverse=True,
        )

        # 获取之后的兄弟帧
        after_siblings = sorted(
            [s for s in all_siblings if self._graph.nodes[s]["start_pos"] > target_start_pos],
            key=lambda s: self._graph.nodes[s]["start_pos"],
        )

        # 应用数量限制
        num_before = sibling_config.get("before")
        num_after = sibling_config.get("after")

        selected = (before_siblings[:num_before] if num_before is not None else before_siblings) + (
            after_siblings[:num_after] if num_after is not None else after_siblings
        )

        relevant_frames.extend(selected)
        return relevant_frames

    def _lookup_by_location(
        self,
        filename: str,
        lineno: int,
        sibling_config: Optional[SiblingConfig] = None,
    ) -> Tuple[List[str], List[List[ReferenceInfo]]]:
        matching_frame_ids = self._file_line_to_frames.get((filename, lineno), [])
        if not matching_frame_ids:
            return [], []

        logs = []
        references_group = []

        for frame_id in matching_frame_ids:
            if frame_id not in self._frames:
                continue

            relevant_frames = [frame_id]
            if sibling_config and sibling_config.get("functions"):
                relevant_frames = self._get_sibling_frames(frame_id, sibling_config)

            sorted_frames = sorted(relevant_frames, key=lambda fid: self._graph.nodes[fid]["start_pos"])

            # 计算日志范围
            start_pos = self._graph.nodes[sorted_frames[0]]["start_pos"]
            valid_end_positions = [
                self._graph.nodes[fid].get("end_pos")
                for fid in sorted_frames
                if self._graph.nodes[fid].get("end_pos") is not None
            ]
            end_pos = max(valid_end_positions) if valid_end_positions else None

            logs.append(self._get_log_content(start_pos, end_pos))
            references_group.append(self._build_reference_chain(sorted_frames, frame_id))

        return logs, references_group

    def lookup(
        self,
        filename: Optional[str] = None,
        lineno: Optional[int] = None,
        frame_id: Optional[int] = None,
        sibling_func: Optional[List[str]] = None,
        sibling_config: Optional[SiblingConfig] = None,
        next_siblings: Optional[int] = None,
    ) -> Tuple[List[str], List[List[ReferenceInfo]]]:
        self._build_graph()
        assert self._graph is not None

        if frame_id is not None:
            if filename or lineno or sibling_func or sibling_config:
                raise ValueError("Cannot use `frame_id` with `filename`, `lineno`, or sibling configurations.")
            return self._lookup_by_frame_id(frame_id, next_siblings=next_siblings)

        if filename is not None and lineno is not None:
            if next_siblings is not None:
                raise ValueError("`next_siblings` can only be used with `frame_id` lookup.")
            if sibling_func and not sibling_config:
                sibling_config = {"functions": sibling_func}
            return self._lookup_by_location(filename, lineno, sibling_config)

        raise ValueError("Must provide either `frame_id` or both `filename` and `lineno` for lookup.")

    def export_trace_graph(self, frame_id: int, output_path: str, show_full_trace: bool = True):
        self._build_graph()
        assert self._graph is not None

        if frame_id not in self._graph:
            raise ValueError(f"Frame ID {frame_id} not found in trace graph.")

        root = self._find_trace_root(frame_id) if show_full_trace else frame_id
        trace_nodes = self._get_trace_subgraph(root, show_full_trace)
        subgraph = self._graph.subgraph(trace_nodes).copy()
        self._render_graph(subgraph, output_path, highlight_node=frame_id)

    def _find_trace_root(self, frame_id: int) -> int:
        """查找完整追踪的根节点"""
        current = frame_id
        while preds := list(self._graph.predecessors(current)):
            if (pred := preds[0]) == ROOT_FRAME_ID:
                break
            current = pred
        return current

    def _get_trace_subgraph(self, start_node: int, full_trace: bool) -> Set[int]:
        """获取追踪子图的节点集合"""
        if full_trace:
            return {start_node} | nx.descendants(self._graph, start_node)
        return {start_node} | nx.descendants(self._graph, start_node)

    def _format_node_text(self, node_id: int, level: int) -> str:
        node_data = self._graph.nodes[node_id]
        filename = Path(node_data["filename"]).name
        status = node_data.get("status", "unknown")
        func = node_data.get("func", "N/A")
        lineno = node_data["lineno"]
        return f"{'  ' * level}- {func} ({filename}:{lineno}) [status: {status}, id: {node_id}]"

    def export_trace_graph_text(self, frame_id: int, output_path: str, show_full_trace: bool = True):
        self._build_graph()
        assert self._graph is not None

        if frame_id not in self._graph:
            raise ValueError(f"Frame ID {frame_id} not found in trace graph.")

        start_node = self._find_trace_root(frame_id) if show_full_trace else frame_id
        output_lines = []  # 直接输出树结构，移除标题和分隔线

        stack: List[Tuple[int, int]] = [(start_node, 0)]
        visited: Set[int] = set()

        while stack:
            node_id, level = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)

            output_lines.append(self._format_node_text(node_id, level))

            children = sorted(
                self._graph.successors(node_id),
                key=lambda cid: self._graph.nodes[cid].get("start_pos", 0),
                reverse=True,
            )
            for child_id in children:
                if child_id not in visited:
                    stack.append((child_id, level + 1))

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))
        print(f"Graph text representation exported to {output_path}")

    def _render_graph(self, g: nx.DiGraph, output_path: str, highlight_node: Optional[int] = None):
        if ROOT_FRAME_ID in g:
            g.remove_node(ROOT_FRAME_ID)

        agraph = nx.nx_agraph.to_agraph(g)
        agraph.graph_attr.update(rankdir="TB", splines="ortho")
        agraph.node_attr.update(shape="box", style="rounded,filled", fillcolor="lightblue", fontname="Helvetica")
        agraph.edge_attr.update(color="gray", arrowhead="normal")

        for node in agraph.nodes():
            node_id = int(node)
            data = g.nodes[node_id]
            filename = Path(data["filename"]).name
            label = f"{data.get('func', 'N/A')}\n{filename}:{data['lineno']}"
            node.attr["label"] = label

            status = data.get("status")
            if status == TraceTypes.PARTIAL.value:
                node.attr.update(style="rounded,filled,dashed", fillcolor="lightyellow")
            elif status == TraceTypes.EXCEPTION.value:
                node.attr["fillcolor"] = "lightcoral"
            else:
                node.attr["fillcolor"] = "lightblue"

            if node_id == highlight_node:
                node.attr.update(fillcolor="lemonchiffon", penwidth="2.0")

        output_format = Path(output_path).suffix[1:]
        if not output_format:
            raise ValueError("Output path must have a file extension (e.g., .svg, .png).")

        agraph.draw(output_path, format=output_format, prog="dot")
        print(f"Graph exported to {output_path}")
