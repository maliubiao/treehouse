import datetime
import unittest
from collections import defaultdict
from unittest.mock import MagicMock

from debugger.call_analyzer import CallAnalyzer


class TestCallAnalyzer(unittest.TestCase):
    def setUp(self):
        """为每个测试创建一个新的CallAnalyzer实例。"""
        self.analyzer = CallAnalyzer(verbose=False)
        self.thread_id = 1
        self.event_id_counter = 1

    def _create_mock_log_data(self, event_type, data):
        """辅助函数，创建模拟的日志数据，并自动添加thread_id和event_id。"""
        if "thread_id" not in data:
            data["thread_id"] = self.thread_id
        if "event_id" not in data:
            data["event_id"] = self.event_id_counter
            self.event_id_counter += 1
        return {"data": data}, event_type

    def test_handle_simple_call_and_return(self):
        """测试处理一个简单的函数调用和返回事件。"""
        # 1. 模拟函数调用
        call_data = {
            "frame_id": 1,
            "func": "my_func",
            "filename": "test.py",
            "original_filename": "/path/to/test.py",
            "lineno": 10,
            "args": "a=1, b='test'",
        }
        self.analyzer.process_event(*self._create_mock_log_data("call", call_data))

        stack = self.analyzer.call_stacks[self.thread_id]
        self.assertEqual(len(stack), 1)
        record = self.analyzer.records_by_frame_id[1]
        self.assertEqual(record["func_name"], "my_func")
        self.assertEqual(record["args"], {"a": "1", "b": "'test'"})

        # 2. 模拟行事件
        line_data = {
            "frame_id": 1,
            "lineno": 11,
            "raw_line": "x = a + 1",
            "tracked_vars": {"x": 2},
        }
        self.analyzer.process_event(*self._create_mock_log_data("line", line_data))

        self.assertEqual(len(record["events"]), 1)
        self.assertEqual(record["events"][0]["type"], "line")
        self.assertEqual(record["events"][0]["data"]["line_no"], 11)

        # 3. 模拟返回
        return_data = {"frame_id": 1, "return_value": "Success"}
        self.analyzer.process_event(*self._create_mock_log_data("return", return_data))

        self.assertEqual(len(stack), 0)
        self.assertTrue(record["end_time"] > 0)
        self.assertEqual(record["return_value"], "Success")
        self.assertIsNone(record["exception"])

        final_records = self.analyzer.call_trees["test.py"]["my_func"]
        self.assertEqual(len(final_records), 1)
        self.assertIs(final_records[0], record)

    def test_handle_nested_calls(self):
        """测试处理嵌套函数调用。"""
        # Parent call
        parent_call = {"frame_id": 10, "func": "parent", "filename": "p.py", "original_filename": "/p.py", "lineno": 5}
        self.analyzer.process_event(*self._create_mock_log_data("call", parent_call))

        # Child call
        child_call = {"frame_id": 11, "func": "child", "filename": "c.py", "original_filename": "/c.py", "lineno": 20}
        self.analyzer.process_event(*self._create_mock_log_data("call", child_call))

        stack = self.analyzer.call_stacks[self.thread_id]
        self.assertEqual(len(stack), 2)
        parent_record = self.analyzer.records_by_frame_id[10]
        child_record = self.analyzer.records_by_frame_id[11]

        self.assertEqual(len(parent_record["events"]), 1)
        self.assertEqual(parent_record["events"][0]["type"], "call")
        self.assertIs(parent_record["events"][0]["data"], child_record)

        # Child return
        child_return = {"frame_id": 11, "return_value": "child_result"}
        self.analyzer.process_event(*self._create_mock_log_data("return", child_return))

        self.assertEqual(len(stack), 1)
        self.assertEqual(child_record["return_value"], "child_result")

        # Parent return
        parent_return = {"frame_id": 10, "return_value": "parent_result"}
        self.analyzer.process_event(*self._create_mock_log_data("return", parent_return))

        self.assertEqual(len(stack), 0)
        self.assertEqual(parent_record["return_value"], "parent_result")

    def test_handle_exception_in_top_level_call(self):
        """测试处理顶层函数调用中的异常。"""
        call_data = {
            "frame_id": 20,
            "func": "fail_func",
            "filename": "fail.py",
            "original_filename": "/f.py",
            "lineno": 1,
        }
        self.analyzer.process_event(*self._create_mock_log_data("call", call_data))
        self.assertEqual(len(self.analyzer.call_stacks[self.thread_id]), 1)

        exception_data = {"frame_id": 20, "exc_type": "ValueError", "exc_value": "Invalid input", "lineno": 5}
        self.analyzer.process_event(*self._create_mock_log_data("exception", exception_data))

        self.assertEqual(len(self.analyzer.call_stacks[self.thread_id]), 0)
        record = self.analyzer.records_by_frame_id[20]
        self.assertIsNotNone(record["exception"])
        self.assertEqual(record["exception"]["type"], "ValueError")

    def test_handle_propagating_exception_in_nested_call(self):
        """测试处理在嵌套调用中向上冒泡的异常。"""
        # Parent call
        parent_call = {
            "frame_id": 30,
            "func": "main_op",
            "filename": "main.py",
            "original_filename": "/main.py",
            "lineno": 10,
        }
        self.analyzer.process_event(*self._create_mock_log_data("call", parent_call))

        # Child call
        child_call = {
            "frame_id": 31,
            "func": "sub_op_fail",
            "filename": "sub.py",
            "original_filename": "/sub.py",
            "lineno": 50,
        }
        self.analyzer.process_event(*self._create_mock_log_data("call", child_call))
        self.assertEqual(len(self.analyzer.call_stacks[self.thread_id]), 2)

        # 1. Exception from child (simulates `except` block in `sub_op_fail`)
        child_exception = {"frame_id": 31, "exc_type": "KeyError", "exc_value": "'missing_key'", "lineno": 55}
        self.analyzer.process_event(*self._create_mock_log_data("exception", child_exception))
        self.assertEqual(len(self.analyzer.call_stacks[self.thread_id]), 1)  # Child is popped

        # 2. Exception propagates to parent (simulates `main_op` not catching it)
        parent_exception = {"frame_id": 30, "exc_type": "KeyError", "exc_value": "'missing_key'", "lineno": 15}
        self.analyzer.process_event(*self._create_mock_log_data("exception", parent_exception))
        self.assertEqual(len(self.analyzer.call_stacks[self.thread_id]), 0)  # Parent is popped

        # Assertions
        child_record = self.analyzer.records_by_frame_id[31]
        self.assertIsNotNone(child_record["exception"])
        self.assertEqual(child_record["exception"]["type"], "KeyError")

        parent_record = self.analyzer.records_by_frame_id[30]
        self.assertIsNotNone(parent_record["exception"])
        self.assertEqual(parent_record["exception"]["type"], "KeyError")

        # Verify main_op is in the final call tree and sub_op_fail is correctly nested as its child.
        self.assertEqual(len(self.analyzer.call_trees["main.py"]["main_op"]), 1)
        main_op_record = self.analyzer.call_trees["main.py"]["main_op"][0]

        # Check that sub_op_fail is a child call within main_op's events
        found_sub_op_fail_as_child = False
        for event in main_op_record["events"]:
            if event["type"] == "call" and event["data"]["func_name"] == "sub_op_fail":
                self.assertIs(event["data"], child_record)  # Ensure it's the exact same record instance
                found_sub_op_fail_as_child = True
                break
        self.assertTrue(found_sub_op_fail_as_child, "sub_op_fail record not found as a child of main_op")

    def test_finalize_clears_stack(self):
        """测试finalize方法能否正确处理未完成的调用。"""
        call_data = {
            "frame_id": 40,
            "func": "hanging_func",
            "filename": "hang.py",
            "original_filename": "/hang.py",
            "lineno": 1,
        }
        self.analyzer.process_event(*self._create_mock_log_data("call", call_data))
        self.assertEqual(len(self.analyzer.call_stacks[self.thread_id]), 1)

        self.analyzer.finalize()

        self.assertEqual(len(self.analyzer.call_stacks[self.thread_id]), 0)
        record = self.analyzer.records_by_frame_id[40]
        self.assertIsNotNone(record["exception"])
        self.assertEqual(record["exception"]["type"], "IncompleteExecution")
        self.assertEqual(len(self.analyzer.call_trees["hang.py"]["hanging_func"]), 1)


if __name__ == "__main__":
    unittest.main()
