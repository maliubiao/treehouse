import json
import shutil
import sys
import unittest
from pathlib import Path

# 将项目根目录添加到 a Python 路径中以导入 gpt_lib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gpt_lib.graph_tracer import GraphTraceLogExtractor


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
        # 创建更复杂的日志，包含多个根调用和部分调用
        log_data = [
            # 第一个调用树
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
            # 第二个调用树（独立的）
            {
                "type": "call",
                "filename": "worker.py",
                "lineno": 20,
                "frame_id": 400,
                "parent_frame_id": 0,
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
            # 部分调用（没有返回）
            {
                "type": "call",
                "filename": "service.py",
                "lineno": 40,
                "frame_id": 600,
                "parent_frame_id": 0,
                "func": "service",
            },
            {"type": "line", "filename": "service.py", "lineno": 41, "frame_id": 600},
            {"type": "return", "filename": "worker.py", "lineno": 20, "frame_id": 400},
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
        self.extractor._build_graph()
        self.assertIsNotNone(self.extractor._graph)
        # 虚拟根节点 + 6个真实节点
        self.assertEqual(len(self.extractor._graph.nodes), 7)
        # 5条边: root->100, 100->200, 200->300, root->400, 400->500, root->600
        self.assertEqual(len(self.extractor._graph.edges), 6)

        # 检查根节点连接
        self.assertTrue(self.extractor._graph.has_edge(0, 100))
        self.assertTrue(self.extractor._graph.has_edge(0, 400))
        self.assertTrue(self.extractor._graph.has_edge(0, 600))

    def test_lookup(self):
        # 测试部分调用（没有返回的节点）
        logs, refs = self.extractor.lookup("service.py", 40)
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)

        # 检查调用链（应跳过虚拟根节点）
        self.assertEqual(len(refs[0]), 1)
        self.assertEqual(refs[0][0]["func"], "service")

        # 测试完整调用链
        logs, refs = self.extractor.lookup("utils.py", 10)
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)

        # 检查调用链（应包含3个节点，跳过根节点）
        self.assertEqual(len(refs[0]), 3)
        self.assertEqual(refs[0][0]["func"], "main")
        self.assertEqual(refs[0][1]["func"], "foo")
        self.assertEqual(refs[0][2]["func"], "bar")

    def test_lookup_with_start_from_func(self):
        # 对 bar (frame 300) 的调用来自 foo
        logs, refs = self.extractor.lookup("utils.py", 10, start_from_func=["foo"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0][-1]["func"], "bar")

        # 这不应该匹配，因为 bar 不是直接从 'main' 调用的
        logs, refs = self.extractor.lookup("utils.py", 10, start_from_func=["main"])
        self.assertEqual(len(logs), 0)

    def test_lookup_not_found(self):
        logs, refs = self.extractor.lookup("nonexistent.py", 1)
        self.assertEqual(len(logs), 0)
        self.assertEqual(len(refs), 0)

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
        self.extractor.export_trace_graph(500, str(output_png), show_full_trace=False)
        self.assertTrue(output_png.exists())
        self.assertGreater(output_png.stat().st_size, 0)

        # 导出根节点追踪
        output_root = self.test_dir / "root_trace.svg"
        self.extractor.export_trace_graph(0, str(output_root))
        self.assertTrue(output_root.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
