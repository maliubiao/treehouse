import json
import shutil
import sys
import unittest
from pathlib import Path

# 将项目根目录添加到 a Python 路径中以导入 gpt_lib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gpt_lib.graph_tracer import ROOT_FRAME_ID, GraphTraceLogExtractor


class BaseTracerTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_temp_dir_graph")
        self.test_dir.mkdir(exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)


class TestGraphTraceLogExtractor(BaseTracerTest):
    """GraphTraceLogExtractor test suite."""

    def setUp(self):
        super().setUp()
        self.log_file = self.test_dir / "trace.log"
        self.index_file = self.log_file.with_suffix(".log.index")
        self._generate_test_logs()
        self.extractor = GraphTraceLogExtractor(str(self.log_file))

    def _generate_test_logs(self):
        # 创建复杂的日志，模拟真实场景：
        # - 调用链: main -> foo -> bar
        # - 在 main 返回前，发生新的根调用: worker -> process
        # - 部分调用（未完成）: service
        # - 返回事件顺序与调用顺序不完全相反
        log_data = [
            # 调用树 1 开始: main -> foo -> bar
            {"type": "call", "filename": "main.py", "lineno": 5, "frame_id": 100, "parent_frame_id": 0, "func": "main"},
            {"type": "line", "filename": "main.py", "lineno": 6, "frame_id": 100},
            {
                "type": "call",
                "filename": "main.py",
                "lineno": 7,
                "frame_id": 200,
                "parent_frame_id": 100,
                "func": "foo",
            },
            {"type": "line", "filename": "main.py", "lineno": 15, "frame_id": 200},
            {
                "type": "call",
                "filename": "utils.py",
                "lineno": 10,
                "frame_id": 300,
                "parent_frame_id": 200,
                "func": "bar",
            },
            {"type": "line", "filename": "utils.py", "lineno": 11, "frame_id": 300},
            {"type": "return", "filename": "utils.py", "lineno": 10, "frame_id": 300},
            {"type": "return", "filename": "main.py", "lineno": 7, "frame_id": 200},
            # 在 main 返回之前，发生了看似独立的调用，但根据栈模型，它们是 main 的子调用
            {
                "type": "call",
                "filename": "worker.py",
                "lineno": 20,
                "frame_id": 400,
                "parent_frame_id": 100,
                "func": "worker",
            },
            {"type": "line", "filename": "worker.py", "lineno": 21, "frame_id": 400},
            {
                "type": "call",
                "filename": "utils.py",
                "lineno": 30,
                "frame_id": 500,
                "parent_frame_id": 400,
                "func": "process",
            },
            {"type": "line", "filename": "utils.py", "lineno": 31, "frame_id": 500},
            {"type": "return", "filename": "utils.py", "lineno": 30, "frame_id": 500},
            # 部分调用（没有返回事件，其父节点 worker 将返回）
            {
                "type": "call",
                "filename": "service.py",
                "lineno": 40,
                "frame_id": 600,
                "parent_frame_id": 400,
                "func": "service",
            },
            {"type": "line", "filename": "service.py", "lineno": 41, "frame_id": 600},
            # worker 返回，将隐式关闭 service
            {"type": "return", "filename": "worker.py", "lineno": 20, "frame_id": 400},
            # main 最终返回
            {"type": "return", "filename": "main.py", "lineno": 5, "frame_id": 100},
        ]

        with open(self.log_file, "w", encoding="utf-8") as log_f, open(self.index_file, "w", encoding="utf-8") as idx_f:
            pos = 0
            for entry in log_data:
                line_str = json.dumps(entry) + "\n"
                log_f.write(line_str)

                if entry["type"] in ("call", "return", "exception"):
                    index_entry = entry.copy()
                    index_entry["position"] = pos
                    idx_f.write(json.dumps(index_entry) + "\n")

                pos += len(line_str.encode("utf-8"))

    def test_graph_construction(self):
        """测试基于堆栈的图构建是否能正确反映调用时序。"""
        self.extractor._build_graph()
        graph = self.extractor._graph

        self.assertIsNotNone(graph)
        # 虚拟根节点 + 6个真实节点
        self.assertEqual(len(graph.nodes), 7)
        # 栈模型将所有调用构建成一个以 main(100) 为根的单棵树
        # 0->100, 100->200, 200->300, 100->400, 400->500, 400->600
        self.assertEqual(len(graph.edges), 6)

        # 检查重构的树结构
        self.assertTrue(graph.has_edge(ROOT_FRAME_ID, 100))
        # worker(400) 是 main(100) 的子调用，因为它在 main 的生命周期内被调用
        self.assertTrue(graph.has_edge(100, 400))
        self.assertFalse(graph.has_edge(ROOT_FRAME_ID, 400))

        self.assertTrue(graph.has_edge(100, 200))
        self.assertTrue(graph.has_edge(200, 300))
        self.assertTrue(graph.has_edge(400, 500))
        self.assertTrue(graph.has_edge(400, 600))

        # 检查节点状态
        self.assertEqual(graph.nodes[300]["status"], "return")
        self.assertEqual(graph.nodes[400]["status"], "return")
        # service(600) 没有自己的返回事件，但其父节点 worker(400) 返回了，因此它被标记为 'partial'
        self.assertEqual(graph.nodes[600]["status"], "partial")
        self.assertEqual(graph.nodes[100]["status"], "return")

    def test_lookup(self):
        # 测试部分调用（没有返回的节点）
        logs, refs = self.extractor.lookup("service.py", 40)
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)

        # 检查引用链（service 及其子函数）
        # service 没有子函数，应包含 call 和 partial 两个事件
        self.assertEqual(len(refs[0]), 2)
        self.assertEqual(refs[0][0]["func"], "service")
        self.assertEqual(refs[0][0]["type"], "call")
        self.assertEqual(refs[0][1]["func"], "service")
        self.assertEqual(refs[0][1]["type"], "partial")

        # 测试完整调用链
        logs, refs = self.extractor.lookup("utils.py", 10)
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)

        # 检查引用链（bar 及其子函数）
        # bar 没有子函数，应包含 call 和 return 两个事件
        self.assertEqual(len(refs[0]), 2)
        self.assertEqual(refs[0][0]["func"], "bar")
        self.assertEqual(refs[0][0]["type"], "call")
        self.assertEqual(refs[0][1]["func"], "bar")
        self.assertEqual(refs[0][1]["type"], "return")

    def test_lookup_with_sibling_func(self):
        # 测试查找 bar 调用，要求 worker 作为 sibling
        # 'bar'的父节点是'foo'，'worker'不是'foo'的子节点，所以找不到sibling
        logs, refs = self.extractor.lookup("utils.py", 10, sibling_func=["worker"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)
        self.assertEqual(len(refs[0]), 2)  # 仅包含 bar 的 call/return
        self.assertEqual(refs[0][0]["func"], "bar")
        self.assertEqual(refs[0][1]["type"], "return")

        # 测试查找 process 调用，要求其兄弟节点中有 service
        # 引用链应包含 process(call/return) 和 service(call/partial)
        logs, refs = self.extractor.lookup("utils.py", 30, sibling_func=["service"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)
        self.assertEqual(len(refs[0]), 4)
        self.assertEqual(refs[0][0]["func"], "process")  # Target first based on start_pos
        self.assertEqual(refs[0][1]["type"], "return")
        self.assertEqual(refs[0][2]["func"], "service")  # Then sibling
        self.assertEqual(refs[0][3]["type"], "partial")

        # 测试不匹配的情况 - 要求兄弟节点中有不存在函数，但仍返回结果
        logs, refs = self.extractor.lookup("utils.py", 10, sibling_func=["nonexistent"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)
        self.assertEqual(len(refs[0]), 2)  # 仅包含 bar 的 call/return

        # 测试查找 service 调用，要求其兄弟节点中有 process
        # 引用链应包含 process(call/return) 和 service(call/partial)
        logs, refs = self.extractor.lookup("service.py", 40, sibling_func=["process"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)
        self.assertEqual(len(refs[0]), 4)
        self.assertEqual(refs[0][0]["func"], "process")  # Sibling first
        self.assertEqual(refs[0][1]["type"], "return")
        self.assertEqual(refs[0][2]["func"], "service")  # Then target
        self.assertEqual(refs[0][3]["type"], "partial")

    def test_lookup_not_found(self):
        logs, refs = self.extractor.lookup("nonexistent.py", 1)
        self.assertEqual(len(logs), 0)
        self.assertEqual(len(refs), 0)

    def test_build_graph_with_fragmented_log(self):
        """测试一个在日志中没有父节点的调用会被正确地链接到虚拟根节点。"""
        log_file = self.test_dir / "fragment.log"
        index_file = log_file.with_suffix(".log.index")

        log_data = [
            # parent_frame_id=50 在此追踪中未定义, 并且调用栈为空
            {
                "type": "call",
                "filename": "fragment.py",
                "lineno": 10,
                "frame_id": 150,
                "parent_frame_id": 50,
                "func": "fragment_func",
            },
            {"type": "line", "filename": "fragment.py", "lineno": 11, "frame_id": 150},
            {"type": "return", "filename": "fragment.py", "lineno": 10, "frame_id": 150},
        ]

        with open(log_file, "w", encoding="utf-8") as log_f, open(index_file, "w", encoding="utf-8") as idx_f:
            pos = 0
            for entry in log_data:
                line_str = json.dumps(entry) + "\n"
                log_f.write(line_str)
                if entry["type"] in ("call", "return", "exception"):
                    index_entry = entry.copy()
                    index_entry["position"] = pos
                    idx_f.write(json.dumps(index_entry) + "\n")
                pos += len(line_str.encode("utf-8"))

        extractor = GraphTraceLogExtractor(str(log_file))
        extractor._build_graph()

        # 节点 150 应该连接到根节点 (ID 0)，因为在调用它时堆栈为空
        self.assertTrue(extractor._graph.has_edge(ROOT_FRAME_ID, 150))
        # 节点 50 不应该被创建
        self.assertFalse(extractor._graph.has_node(50))

        # 验证 lookup 返回一个包含 call/return 的事件对
        logs, refs = extractor.lookup("fragment.py", 10)
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)
        self.assertEqual(len(refs[0]), 2)
        self.assertEqual(refs[0][0]["func"], "fragment_func")
        self.assertEqual(refs[0][0]["type"], "call")
        self.assertEqual(refs[0][1]["type"], "return")

    def test_export_graph(self):
        try:
            # pylint: disable=import-outside-toplevel, unused-import
            import pygraphviz
        except ImportError:
            self.skipTest("pygraphviz not installed, skipping export test")

        # 导出完整追踪
        output_svg = self.test_dir / "full_trace.svg"
        self.extractor.export_trace_graph(300, str(output_svg))
        self.assertTrue(output_svg.exists())
        self.assertGreater(output_svg.stat().st_size, 0)

        # 导出部分追踪
        output_png = self.test_dir / "partial_trace.png"
        self.extractor.export_trace_graph(400, str(output_png), show_full_trace=False)
        self.assertTrue(output_png.exists())
        self.assertGreater(output_png.stat().st_size, 0)

        # 导出根节点追踪
        output_root = self.test_dir / "root_trace.svg"
        # 传递一个根调用（例如，100）来导出整个图
        self.extractor.export_trace_graph(100, str(output_root))
        self.assertTrue(output_root.exists())

    def test_export_graph_text(self):
        """测试将调用图导出为文本格式的功能。"""
        # 测试导出从内部节点开始的完整追踪
        output_txt = self.test_dir / "full_trace.txt"
        # 从 frame 300 (bar) 开始，但请求完整追踪，应从 main(100) 开始
        self.extractor.export_trace_graph_text(300, str(output_txt), show_full_trace=True)

        self.assertTrue(output_txt.exists())
        content = output_txt.read_text(encoding="utf-8").strip()

        expected_lines = [
            "- main (main.py:5) [status: return, id: 100]",
            "  - foo (main.py:7) [status: return, id: 200]",
            "    - bar (utils.py:10) [status: return, id: 300]",
            "  - worker (worker.py:20) [status: return, id: 400]",
            "    - process (utils.py:30) [status: return, id: 500]",
            "    - service (service.py:40) [status: partial, id: 600]",
        ]
        self.assertEqual(content, "\n".join(expected_lines))

        # 测试导出部分追踪
        output_partial_txt = self.test_dir / "partial_trace.txt"
        self.extractor.export_trace_graph_text(400, str(output_partial_txt), show_full_trace=False)
        self.assertTrue(output_partial_txt.exists())
        content_partial = output_partial_txt.read_text(encoding="utf-8").strip()

        # 修正 expected_partial_lines 以匹配实际的图结构
        # worker (400) 的直接子节点是 process (500) 和 service (600)，它们应该是同级，而不是嵌套关系。
        expected_partial_lines = [
            "- worker (worker.py:20) [status: return, id: 400]",
            "  - process (utils.py:30) [status: return, id: 500]",
            "  - service (service.py:40) [status: partial, id: 600]",
        ]
        self.assertEqual(content_partial, "\n".join(expected_partial_lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)
