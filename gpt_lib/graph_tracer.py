import json
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, TypedDict

try:
    import networkx as nx
except ImportError as exc:
    raise ImportError("networkx is required. Please install it with `pip install networkx`.") from exc


# 使用 Enum 增强类型安全性和代码可读性
class TraceTypes(str, Enum):
    CALL = "call"
    RETURN = "return"
    LINE = "line"
    EXCEPTION = "exception"
    PARTIAL = "partial"  # 代表未完整关闭的帧


# 为复杂字典结构定义 TypedDict，增强代码清晰度和静态检查能力
class IndexEntry(TypedDict):
    """表示索引文件中一行的结构。"""

    type: str
    position: int
    frame_id: int
    filename: str
    lineno: int
    func: str


class FrameInfo(TypedDict):
    """存储已解析的函数帧的完整信息。"""

    filename: str
    lineno: int
    func: str
    start_pos: int
    end_pos: Optional[int]
    status: Optional[Literal["return", "exception", "partial"]]


class ReferenceInfo(TypedDict):
    """表示 lookup 方法返回的引用链中的单个事件。"""

    filename: str
    lineno: int
    func: str
    type: str


class SiblingConfig(TypedDict, total=False):
    """
    配置 `lookup` 方法中对兄弟函数的查找行为。

    Attributes:
        functions (List[str]): 必须匹配的兄弟函数名称列表。
        before (Optional[int]): 在目标函数调用之前，按时间顺序查找最多N个兄弟函数。
                                如果为 None，则查找所有之前的兄弟函数。
        after (Optional[int]): 在目标函数调用之后，按时间顺序查找最多N个兄弟函数。
                               如果为 None，则查找所有之后的兄弟函数。
    """

    functions: List[str]
    before: Optional[int]
    after: Optional[int]


TRACE_LOG_NAME = "trace.log"
# 虚拟根节点的特殊ID
ROOT_FRAME_ID = 0


class GraphTraceLogExtractor:
    """
    通过将日志索引构建为调用图来从调试日志中提取信息。

    该实现通过在第一次查询时解析整个索引文件并构建一个内存中的
    networkx.DiGraph 来优化重复查询。图的构建基于调用栈模型，
    通过模拟 `call` (push) 和 `return` (pop) 事件来重构调用关系，
    这种方法比依赖日志中不稳定的 `parent_frame_id` 更为健壮。

    工作原理:
    1.  在首次调用时，延迟加载并解析索引文件。为了保证时序性，所有
        索引条目会根据其在日志文件中的位置进行排序。
    2.  使用一个栈来模拟调用过程，从而构建一个代表调用关系的图：
        -   图中的每个节点代表一个 frame (一次函数调用)。
        -   当一个 `call` 事件发生时，该帧成为当前栈顶帧的子节点，并被压入栈中。
        -   当一个 `return` 或 `exception` 事件发生时，栈会弹出，直到返回的帧
            被弹出为止，这能正确处理因异常等导致的隐式返回。
    3.  `lookup` 方法在图中搜索匹配的节点。
    4.  `export_trace_graph` 方法可以提取一个子图并使用 Graphviz 将其
        可视化为 SVG 或 PNG 文件，而 `export_trace_graph_text` 则可以
        将其导出为文本格式，便于调试大型图。
    """

    def __init__(self, log_file: str = None):
        """
        初始化日志提取器。

        Args:
            log_file (str, optional): 日志文件路径。默认为 'trace.log'。
        """
        self.log_file: Path = Path(log_file or TRACE_LOG_NAME)
        self.index_file: Path = self.log_file.with_suffix(self.log_file.suffix + ".index")

        if not self.log_file.exists():
            raise FileNotFoundError(f"Log file not found: {self.log_file}")
        if not self.index_file.exists():
            raise FileNotFoundError(f"Index file not found: {self.index_file}")

        self._graph: Optional[nx.DiGraph] = None
        self._frames: Dict[int, FrameInfo] = {}  # frame_id -> frame_data
        self._file_line_to_frames: Dict[Tuple[str, int], List[int]] = defaultdict(list)

    def _parse_index_line(self, line: str) -> Optional[IndexEntry]:
        """
        解析索引行，返回一个字典。

        Args:
            line: 索引文件中的一行。

        Returns:
            包含索引信息的字典，或在解析失败时返回 None。
        """
        try:
            entry = json.loads(line.strip())
            if not isinstance(entry, dict) or "type" not in entry:
                return None
            return entry  # type: ignore
        except json.JSONDecodeError:
            return None

    def _build_graph(self):
        """
        从索引文件构建调用图。
        此方法使用调用栈模型，通过按时间顺序处理事件来重构调用层次结构，
        这比依赖日志中的 `parent_frame_id` 更健壮。
        此方法是幂等的；它只在图尚未构建时执行。
        """
        if self._graph is not None:
            return

        self._graph = nx.DiGraph()
        self._frames.clear()
        self._file_line_to_frames.clear()

        # 添加虚拟根节点
        self._graph.add_node(
            ROOT_FRAME_ID, filename="<root>", lineno=0, func="<root>", start_pos=0, end_pos=0, status=None
        )

        # 读取并按位置排序所有索引条目，以确保严格按时间顺序处理
        index_entries: List[IndexEntry] = []
        with open(self.index_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                entry = self._parse_index_line(line)
                if entry:
                    index_entries.append(entry)
        index_entries.sort(key=lambda e: e["position"])

        call_stack: List[int] = []
        frame_data_cache: Dict[int, IndexEntry] = {}  # 存储 'call' 事件数据

        for entry in index_entries:
            frame_id = entry["frame_id"]
            type_tag = entry["type"]

            if type_tag == TraceTypes.CALL:
                parent_id = call_stack[-1] if call_stack else ROOT_FRAME_ID
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
                frame_data_cache[frame_id] = entry
                self._file_line_to_frames[(entry["filename"], entry["lineno"])].append(frame_id)
                call_stack.append(frame_id)

            elif type_tag in (TraceTypes.RETURN, TraceTypes.EXCEPTION):
                if frame_id in frame_data_cache:
                    start_entry = frame_data_cache[frame_id]
                    self._frames[frame_id] = {
                        "filename": start_entry["filename"],
                        "lineno": start_entry["lineno"],
                        "func": start_entry.get("func", "N/A"),
                        "start_pos": start_entry["position"],
                        "end_pos": entry["position"],
                        "status": type_tag,  # type: ignore
                    }
                    if frame_id in self._graph:
                        self._graph.nodes[frame_id]["end_pos"] = entry["position"]
                        self._graph.nodes[frame_id]["status"] = type_tag

                # 正确处理调用栈：弹出直到找到当前返回的帧。
                # 这能正确处理因异常等原因导致的多个栈帧被一次性弹出的情况。
                if frame_id in call_stack:
                    while call_stack:
                        popped_id = call_stack.pop()
                        if popped_id == frame_id:
                            break  # 找到了匹配的帧，正常返回
                        # 如果弹出的帧不是当前返回的帧，说明它被隐式关闭（如被异常穿透）
                        if popped_id in self._graph and self._graph.nodes[popped_id].get("status") is None:
                            self._graph.nodes[popped_id]["status"] = TraceTypes.PARTIAL.value

        # 将堆栈上剩余的任何帧处理为部分帧（日志不完整）
        all_frame_ids_called = frame_data_cache.keys()
        for frame_id in all_frame_ids_called:
            if frame_id not in self._frames:  # 如果没有被 return/exception 显式关闭
                start_entry = frame_data_cache[frame_id]
                self._frames[frame_id] = {
                    "filename": start_entry["filename"],
                    "lineno": start_entry["lineno"],
                    "func": start_entry.get("func", "N/A"),
                    "start_pos": start_entry["position"],
                    "end_pos": None,
                    "status": TraceTypes.PARTIAL.value,
                }
                if frame_id in self._graph and self._graph.nodes[frame_id].get("status") is None:
                    self._graph.nodes[frame_id]["status"] = TraceTypes.PARTIAL.value

    def _create_reference_event(self, node_id: int, event_type: str) -> ReferenceInfo:
        """根据节点ID和事件类型创建一个引用事件字典。"""
        node_data = self._graph.nodes[node_id]  # type: ignore
        return {
            "filename": node_data["filename"],
            "lineno": node_data["lineno"],
            "func": node_data.get("func", "N/A"),
            "type": event_type,
        }

    def _lookup_by_frame_id(
        self, frame_id: int, next_siblings: Optional[int] = None
    ) -> Tuple[List[str], List[List[ReferenceInfo]]]:
        """
        通过 frame_id 查找单个调用实例，并可选择性地包含其后的兄弟调用。
        """
        if frame_id not in self._graph or frame_id == ROOT_FRAME_ID:
            return [], []

        # 1. 确定所有相关的帧 (目标帧 + 兄弟帧)
        relevant_frames = [frame_id]
        if next_siblings and next_siblings > 0:
            predecessors = list(self._graph.predecessors(frame_id))
            if predecessors and predecessors[0] != ROOT_FRAME_ID:
                parent_id = predecessors[0]
                target_node_data = self._graph.nodes[frame_id]
                target_start_pos = target_node_data["start_pos"]

                all_siblings = [sid for sid in self._graph.successors(parent_id) if sid != frame_id]
                next_sibling_candidates = [
                    s for s in all_siblings if self._graph.nodes[s]["start_pos"] > target_start_pos
                ]

                sorted_next_siblings = sorted(next_sibling_candidates, key=lambda s: self._graph.nodes[s]["start_pos"])
                selected_siblings = sorted_next_siblings[:next_siblings]
                relevant_frames.extend(selected_siblings)

        # 2. 根据所有相关帧确定日志的提取范围
        sorted_relevant_frames = sorted(relevant_frames, key=lambda fid: self._graph.nodes[fid]["start_pos"])
        start_pos = self._graph.nodes[sorted_relevant_frames[0]]["start_pos"]

        all_end_pos = [self._graph.nodes[fid].get("end_pos") for fid in sorted_relevant_frames]
        valid_end_pos = [p for p in all_end_pos if p is not None]
        end_pos = max(valid_end_pos) if valid_end_pos else None

        # 3. 提取日志内容
        log_content = ""
        with open(self.log_file, "r", encoding="utf-8") as f:
            f.seek(start_pos)
            read_size = -1
            if end_pos is not None:
                read_size = end_pos - start_pos if end_pos >= start_pos else 0
            if read_size != 0:
                log_content = f.read(read_size if read_size != -1 else None)

        # 4. 按时间顺序构建引用链
        references: List[ReferenceInfo] = []
        for fid in sorted_relevant_frames:
            # 对于目标帧，包含其完整的子调用链
            if fid == frame_id:
                references.append(self._create_reference_event(fid, TraceTypes.CALL.value))
                children_ids = sorted(
                    list(self._graph.successors(fid)),
                    key=lambda cid: self._graph.nodes[cid].get("start_pos", 0),
                )
                for child_id in children_ids:
                    references.append(self._create_reference_event(child_id, TraceTypes.CALL.value))
                    if status := self._graph.nodes[child_id].get("status"):
                        references.append(self._create_reference_event(child_id, status))
                if status := self._graph.nodes[fid].get("status"):
                    references.append(self._create_reference_event(fid, status))
            # 对于兄弟帧，只包含其自身的调用和返回事件
            else:
                references.append(self._create_reference_event(fid, TraceTypes.CALL.value))
                if status := self._graph.nodes[fid].get("status"):
                    references.append(self._create_reference_event(fid, status))

        return [log_content], [references]

    def _lookup_by_location(
        self,
        filename: str,
        lineno: int,
        sibling_config: Optional[SiblingConfig] = None,
    ) -> Tuple[List[str], List[List[ReferenceInfo]]]:
        """
        通过文件和行号查找调用实例，并可选择性地包含兄弟调用。
        """
        matching_frame_ids = self._file_line_to_frames.get((filename, lineno), [])
        if not matching_frame_ids:
            return [], []

        logs: List[str] = []
        references_group: List[List[ReferenceInfo]] = []

        for frame_id in matching_frame_ids:
            if frame_id not in self._frames:
                continue

            # 1. 查找所有相关的帧（目标帧 + 兄弟帧）
            relevant_frames = [frame_id]
            if sibling_config and sibling_config.get("functions"):
                predecessors = list(self._graph.predecessors(frame_id))
                if predecessors:
                    parent_id = predecessors[0]
                    target_node_data = self._graph.nodes[frame_id]

                    all_siblings = [sid for sid in self._graph.successors(parent_id) if sid != frame_id]
                    candidate_siblings = [
                        sid for sid in all_siblings if self._graph.nodes[sid].get("func") in sibling_config["functions"]
                    ]

                    target_start_pos = target_node_data["start_pos"]
                    before_siblings = sorted(
                        [s for s in candidate_siblings if self._graph.nodes[s]["start_pos"] < target_start_pos],
                        key=lambda s: self._graph.nodes[s]["start_pos"],
                        reverse=True,
                    )
                    after_siblings = sorted(
                        [s for s in candidate_siblings if self._graph.nodes[s]["start_pos"] > target_start_pos],
                        key=lambda s: self._graph.nodes[s]["start_pos"],
                    )

                    selected_siblings = []
                    num_before = sibling_config.get("before")
                    selected_siblings.extend(
                        before_siblings[:num_before] if num_before is not None else before_siblings
                    )
                    num_after = sibling_config.get("after")
                    selected_siblings.extend(after_siblings[:num_after] if num_after is not None else after_siblings)
                    relevant_frames.extend(selected_siblings)

            # 2. 根据所有相关帧确定日志的提取范围
            sorted_by_start = sorted(relevant_frames, key=lambda fid: self._graph.nodes[fid]["start_pos"])
            start_pos = self._graph.nodes[sorted_by_start[0]]["start_pos"]

            all_end_pos = [self._graph.nodes[fid].get("end_pos") for fid in relevant_frames]
            valid_end_pos = [p for p in all_end_pos if p is not None]
            end_pos = max(valid_end_pos) if valid_end_pos else None

            # 3. 提取日志内容
            log_content = ""
            with open(self.log_file, "r", encoding="utf-8") as f:
                f.seek(start_pos)
                read_size = -1
                if end_pos is not None:
                    read_size = end_pos - start_pos if end_pos >= start_pos else 0
                if read_size != 0:
                    log_content = f.read(read_size if read_size != -1 else None)
            logs.append(log_content)

            # 4. 按时间顺序构建引用链
            references: List[ReferenceInfo] = []
            for fid in sorted_by_start:
                if fid == frame_id:
                    references.append(self._create_reference_event(fid, TraceTypes.CALL.value))
                    children_ids = sorted(
                        list(self._graph.successors(fid)),
                        key=lambda cid: self._graph.nodes[cid].get("start_pos", 0),
                    )
                    for child_id in children_ids:
                        references.append(self._create_reference_event(child_id, TraceTypes.CALL.value))
                        if status := self._graph.nodes[child_id].get("status"):
                            references.append(self._create_reference_event(child_id, status))
                    if status := self._graph.nodes[fid].get("status"):
                        references.append(self._create_reference_event(fid, status))
                else:
                    references.append(self._create_reference_event(fid, TraceTypes.CALL.value))
                    if status := self._graph.nodes[fid].get("status"):
                        references.append(self._create_reference_event(fid, status))
            references_group.append(references)

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
        """
        查找日志信息。此方法支持两种互斥的查询模式：
        1. 按 `frame_id` 查找：提供一个唯一的 `frame_id` 来获取该次调用的完整日志和引用链。
        2. 按位置查找：提供 `filename` 和 `lineno` 来查找在该位置发生的所有调用。

        Args:
            filename (str, optional): 文件名 (用于按位置查找)。
            lineno (int, optional): 行号 (用于按位置查找)。
            frame_id (int, optional): 唯一的帧ID (用于按ID查找)。
            sibling_func (list[str], optional): [已弃用] 请使用 `sibling_config`。
                                             为了向后兼容，此参数仍然有效，其行为
                                             等同于 `sibling_config={'functions': sibling_func}`。
            sibling_config (SiblingConfig, optional): 用于配置兄弟函数查找的字典 (仅在按位置查找时有效)。
                - 'functions' (list[str]): 目标兄弟函数的名称。
                - 'before' (int, optional): 在目标之前查找N个兄弟。
                - 'after' (int, optional): 在目标之后查找N个兄弟。
            next_siblings (int, optional): 在按 `frame_id` 查找时，额外包含在该调用之后发生的最多 N 个兄弟调用。
                                         兄弟调用是由同一个父函数发起的调用。此参数仅在 `frame_id` 模式下有效。

        Returns:
            一个元组 (logs, references_group):
            - logs (list[str]): 匹配的日志块列表。
            - references_group (list[list[dict]]): 每个日志块对应的函数引用链，
                                                 按时间顺序排列。

        Raises:
            ValueError: 如果提供了无效或冲突的参数组合。
        """
        self._build_graph()
        assert self._graph is not None, "Graph should be built by _build_graph"

        # --- 参数验证和模式分发 ---
        is_location_mode = filename is not None and lineno is not None
        is_frame_id_mode = frame_id is not None

        if is_frame_id_mode:
            if is_location_mode or sibling_func or sibling_config:
                raise ValueError("Cannot use `frame_id` with `filename`, `lineno`, or sibling configurations.")
            return self._lookup_by_frame_id(frame_id, next_siblings=next_siblings)

        if is_location_mode:
            if next_siblings is not None:
                raise ValueError("`next_siblings` can only be used with `frame_id` lookup.")
            # 向后兼容处理
            if sibling_func and not sibling_config:
                sibling_config = {"functions": sibling_func}
            return self._lookup_by_location(filename, lineno, sibling_config)

        raise ValueError("Must provide either `frame_id` or both `filename` and `lineno` for lookup.")

    def export_trace_graph(self, frame_id: int, output_path: str, show_full_trace: bool = True):
        """
        将指定 frame_id 的调用追踪导出为图像文件 (SVG/PNG)。

        Args:
            frame_id (int): 起始 frame_id。
            output_path (str): 输出文件路径 (e.g., 'trace.svg', 'trace.png')。
            show_full_trace (bool): 如果为 True, 导出包含此 frame 的完整调用树。
                                     如果为 False, 仅导出此 frame 及其后续调用。
        """
        self._build_graph()
        assert self._graph is not None, "Graph should be built by _build_graph"

        if frame_id not in self._graph:
            raise ValueError(f"Frame ID {frame_id} not found in trace graph.")

        subgraph: nx.DiGraph
        if show_full_trace:
            root = frame_id
            while preds := list(self._graph.predecessors(root)):
                if (pred := preds[0]) == ROOT_FRAME_ID:
                    break
                root = pred
            trace_nodes = {root} | nx.descendants(self._graph, root)
        else:
            trace_nodes = {frame_id} | nx.descendants(self._graph, frame_id)

        subgraph = self._graph.subgraph(trace_nodes).copy()
        self._render_graph(subgraph, output_path, highlight_node=frame_id)

    def _format_node_as_text(self, node_id: int, level: int) -> str:
        """将单个图节点格式化为文本树的一行。"""
        node_data = self._graph.nodes[node_id]  # type: ignore
        filename = Path(node_data["filename"]).name
        status = node_data.get("status", "unknown")
        func = node_data.get("func", "N/A")
        lineno = node_data["lineno"]

        indent = "  " * level
        return f"{indent}- {func} ({filename}:{lineno}) [status: {status}, id: {node_id}]"

    def export_trace_graph_text(self, frame_id: int, output_path: str, show_full_trace: bool = True):
        """
        将指定 frame_id 的调用追踪导出为文本文件。

        此方法使用迭代式深度优先搜索，因此对于无法渲染或因递归深度过大而失败的大型图，
        此方法非常有用。它以人类可读的树状格式表示调用层次结构。
        该方法经过重构，将格式化逻辑移至辅助方法以降低复杂度。

        Args:
            frame_id (int): 起始 frame_id。
            output_path (str): 输出文本文件路径 (e.g., 'trace.txt')。
            show_full_trace (bool): 如果为 True, 导出包含此 frame 的完整调用树。
                                     如果为 False, 仅导出此 frame 及其后续调用。
        """
        self._build_graph()
        assert self._graph is not None, "Graph should be built by _build_graph"

        if frame_id not in self._graph:
            raise ValueError(f"Frame ID {frame_id} not found in trace graph.")

        start_node = frame_id
        if show_full_trace:
            root = frame_id
            while preds := list(self._graph.predecessors(root)):
                if (pred := preds[0]) == ROOT_FRAME_ID:
                    break
                root = pred
            start_node = root

        output_lines = []
        # 使用迭代式DFS遍历，避免递归深度限制: (node_id, level)
        stack: List[Tuple[int, int]] = [(start_node, 0)]
        visited: set[int] = set()

        while stack:
            node_id, level = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)

            line = self._format_node_as_text(node_id, level)
            output_lines.append(line)

            # 按时间顺序（start_pos）对子节点排序，并反向压入栈中，以确保按正确顺序访问
            children = sorted(
                list(self._graph.successors(node_id)),
                key=lambda cid: (self._graph.nodes[cid].get("start_pos", 0), cid),
                reverse=True,
            )
            for child_id in children:
                if child_id not in visited:
                    stack.append((child_id, level + 1))

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_lines))
        print(f"Graph text representation exported to {output_path}")

    def _render_graph(self, g: nx.DiGraph, output_path: str, highlight_node: Optional[int] = None):
        """
        使用 pygraphviz 渲染图形。

        Args:
            g (nx.DiGraph): 要渲染的图。
            output_path (str): 输出文件路径。
            highlight_node (int, optional): 要高亮显示的节点 ID。
        """
        if ROOT_FRAME_ID in g:
            g.remove_node(ROOT_FRAME_ID)  # 不在可视化图中绘制虚拟根节点

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
                node.attr["style"] = "rounded,filled,dashed"
                node.attr["fillcolor"] = "lightyellow"
            elif status == TraceTypes.EXCEPTION.value:
                node.attr["fillcolor"] = "lightcoral"
            else:
                node.attr["fillcolor"] = "lightblue"

            if node_id == highlight_node:
                node.attr["fillcolor"] = "lemonchiffon"
                node.attr["penwidth"] = "2.0"

        output_format = Path(output_path).suffix[1:]
        if not output_format:
            raise ValueError("Output path must have a file extension (e.g., .svg, .png).")

        agraph.draw(output_path, format=output_format, prog="dot")
        print(f"Graph exported to {output_path}")
