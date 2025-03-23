import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from debugger.tracer import TraceConfig, TraceCore


class TestTracer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.tmp_path = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_filename_pattern_matching(self):
        test_file = self.tmp_path / "test_file.py"
        test_file.write_text("def foo():\n    pass\n")

        config = TraceConfig(target_files=["*test_*.py"], line_ranges={}, capture_vars=[])
        tracer = TraceCore(test_file, config=config)

        frame = Mock(f_code=Mock(co_filename=str(test_file)))
        self.assertTrue(tracer.is_target_frame(frame))

    def test_line_range_filtering(self):
        test_file = self.tmp_path / "test_file.py"
        test_file.write_text("def foo():\n    pass\n")

        config = TraceConfig(target_files=[], line_ranges={str(test_file): [(1, 2)]}, capture_vars=[])
        tracer = TraceCore(test_file, config=config)

        frame = Mock(f_code=Mock(co_filename=str(test_file)), f_lineno=1)
        tracer.log_line(frame)  # Should capture
        frame.f_lineno = 3
        tracer.log_line(frame)  # Should ignore

    def test_variable_capture(self):
        test_file = self.tmp_path / "test_file.py"
        test_file.write_text("def foo():\n    x = 42\n    y = 'hello'\n")

        config = TraceConfig(target_files=[], line_ranges={}, capture_vars=["x", "y"])
        tracer = TraceCore(test_file, config=config)

        frame = Mock(
            f_code=Mock(co_filename=str(test_file)),
            f_locals={"x": 42, "y": "hello"},
            f_lineno=1,
            f_globals={"__name__": "__main__"},
        )
        captured = tracer.capture_variables(frame)
        self.assertEqual(captured, {"x": "42", "y": "'hello'"})

    def test_callback_trigger(self):
        test_file = self.tmp_path / "test_file.py"
        test_file.write_text("def foo():\n    x = 42\n")

        callback_called = False

        def callback(_):
            nonlocal callback_called
            callback_called = True

        config = TraceConfig(target_files=[], line_ranges={}, capture_vars=["x"], callback=callback)
        tracer = TraceCore(test_file, config=config)
        tracer.tracing_enabled = True

        frame = Mock(
            f_code=Mock(co_filename=str(test_file)),
            f_locals={"x": 42},
            f_lineno=1,
            f_globals={"__name__": "__main__"},
        )
        tracer.log_line(frame)
        self.assertTrue(callback_called)

    def test_performance_large_file(self):
        test_file = self.tmp_path / "large_file.py"
        with open(test_file, "w") as f:
            for i in range(10000):
                f.write(f"x{i} = {i}\n")

        config = TraceConfig(target_files=[], line_ranges={str(test_file): [(1, 10000)]}, capture_vars=[])
        tracer = TraceCore(test_file, config=config)

        start_time = time.time()
        frame = Mock(f_code=Mock(co_filename=str(test_file)), f_lineno=10000)
        tracer.log_line(frame)
        elapsed_time = time.time() - start_time
        self.assertLess(elapsed_time, 0.1)

    def test_multiple_file_patterns(self):
        files = [self.tmp_path / "test1.py", self.tmp_path / "test2.py", self.tmp_path / "ignore.py"]
        for f in files:
            f.write_text("def foo():\n    pass\n")

        config = TraceConfig(target_files=["*test*.py"], line_ranges={}, capture_vars=[])
        for f in files:
            tracer = TraceCore(f, config=config)
            frame = Mock(f_code=Mock(co_filename=str(f)))
            if f.name.startswith("test"):
                self.assertTrue(tracer.is_target_frame(frame))
            else:
                self.assertFalse(tracer.is_target_frame(frame))

    def test_variable_capture_expressions(self):
        test_file = self.tmp_path / "test_file.py"
        test_file.write_text("def foo():\n    x = 42\n    y = 'hello'\n")

        config = TraceConfig(target_files=[], line_ranges={}, capture_vars=["x + 1", "y.upper()"])
        tracer = TraceCore(test_file, config=config)

        frame = Mock(
            f_code=Mock(co_filename=str(test_file)),
            f_locals={"x": 42, "y": "hello"},
            f_lineno=1,
            f_globals={"__name__": "__main__"},
        )
        captured = tracer.capture_variables(frame)
        self.assertEqual(captured, {"x + 1": "43", "y.upper()": "'HELLO'"})

    def test_callback_with_variables(self):
        test_file = self.tmp_path / "test_file.py"
        test_file.write_text("def foo():\n    x = 42\n")

        captured_vars = None

        def callback(captured_variables):
            nonlocal captured_vars
            captured_vars = captured_variables

        config = TraceConfig(target_files=[], line_ranges={}, capture_vars=["x"], callback=callback)
        tracer = TraceCore(test_file, config=config)
        tracer.tracing_enabled = True
        frame = Mock(
            f_code=Mock(co_filename=str(test_file)),
            f_locals={"x": 42},
            f_globals={"__name__": "__main__"},
            f_lineno=1,
        )
        tracer.log_line(frame)
        self.assertEqual(captured_vars, {"x": "42"})

    def test_max_line_repeat(self):
        test_file = self.tmp_path / "test_file.py"
        test_file.write_text("def foo():\n    x = 42\n")

        config = TraceConfig(target_files=[], line_ranges={}, capture_vars=[])
        tracer = TraceCore(test_file, config=config)
        tracer.tracing_enabled = True
        frame = Mock(f_code=Mock(co_filename=str(test_file)), f_lineno=1)
        for _ in range(5):
            tracer.log_line(frame)
        self.assertEqual(tracer.line_counter[1], 5)


if __name__ == "__main__":
    unittest.main()
