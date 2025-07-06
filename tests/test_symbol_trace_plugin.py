import sys
import threading
import time
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import tracer.symbol_trace_plugin as st_plugin

# Setup sys.path to allow module imports
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))


class TestSymbolTraceEvent(unittest.TestCase):
    """Unit tests for the SymbolTraceEvent dataclass."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment by patching lldb imports."""
        cls.patcher = patch("tracer.symbol_trace_plugin.lldb", MagicMock())
        cls.patcher.start()
        from tracer.symbol_trace_plugin import SymbolTraceEvent

        cls.SymbolTraceEvent = SymbolTraceEvent

    @classmethod
    def tearDownClass(cls):
        """Clean up after tests."""
        cls.patcher.stop()

    def test_minimal_instantiation(self):
        """Test creating SymbolTraceEvent with required parameters only."""
        mock_frame = MagicMock()
        test_symbol = "test_function"
        test_module = "test_module"
        test_thread_id = 123
        test_timestamp = time.time()

        event = self.SymbolTraceEvent(
            frame=mock_frame, symbol=test_symbol, module=test_module, thread_id=test_thread_id, timestamp=test_timestamp
        )

        self.assertIs(event.frame, mock_frame)
        self.assertEqual(event.symbol, test_symbol)
        self.assertEqual(event.module, test_module)
        self.assertEqual(event.thread_id, test_thread_id)
        self.assertEqual(event.timestamp, test_timestamp)
        self.assertEqual(event.duration, 0.0)
        self.assertEqual(event.depth, 0)

    def test_full_instantiation(self):
        """Test creating SymbolTraceEvent with all parameters."""
        mock_frame = MagicMock()
        test_symbol = "test_function"
        test_module = "test_module"
        test_thread_id = 123
        test_timestamp = time.time()
        test_duration = 1.5
        test_depth = 2

        event = self.SymbolTraceEvent(
            frame=mock_frame,
            symbol=test_symbol,
            module=test_module,
            thread_id=test_thread_id,
            timestamp=test_timestamp,
            duration=test_duration,
            depth=test_depth,
        )

        self.assertIs(event.frame, mock_frame)
        self.assertEqual(event.symbol, test_symbol)
        self.assertEqual(event.module, test_module)
        self.assertEqual(event.thread_id, test_thread_id)
        self.assertEqual(event.timestamp, test_timestamp)
        self.assertEqual(event.duration, test_duration)
        self.assertEqual(event.depth, test_depth)


class TestSymbolTraceInitialization(unittest.TestCase):
    """Unit tests for SymbolTrace initialization functionality."""

    def setUp(self):
        """Save original global state before each test."""
        self.original_instance = getattr(st_plugin, "_SYMBOL_TRACE_INSTANCE", None)

    def tearDown(self):
        """Restore global state after each test."""
        if self.original_instance is None:
            if hasattr(st_plugin, "_SYMBOL_TRACE_INSTANCE"):
                del st_plugin._SYMBOL_TRACE_INSTANCE
        else:
            st_plugin._SYMBOL_TRACE_INSTANCE = self.original_instance

    @patch("tracer.symbol_trace_plugin.register_global_callbacks")
    def test_initialization_success(self, mock_register_global_callbacks):
        """Test successful initialization with valid dependencies and callbacks."""
        mock_register_global_callbacks.return_value = True
        mock_tracer = MagicMock()
        mock_tracer.run_cmd = MagicMock()
        mock_tracer.logger = MagicMock()
        mock_notify_class = MagicMock()

        symbol_trace = st_plugin.SymbolTrace(mock_tracer, mock_notify_class, symbol_info_cache_file=None)

        self.assertEqual(symbol_trace.tracer, mock_tracer)
        self.assertEqual(symbol_trace.notify, mock_notify_class)
        self.assertIsNone(symbol_trace.symbol_info_cache_file)
        self.assertEqual(symbol_trace.regex_cache, {})
        self.assertEqual(symbol_trace.enter_breakpoints, {})
        self.assertEqual(dict(symbol_trace.thread_stacks), {})
        self.assertEqual(st_plugin._SYMBOL_TRACE_INSTANCE, symbol_trace)

        expected_cmd = "script globals()['_symbol_trace_instance'] = tracer.symbol_trace_plugin._SYMBOL_TRACE_INSTANCE"
        mock_tracer.run_cmd.assert_called_once_with(expected_cmd)
        mock_register_global_callbacks.assert_called_once_with(mock_tracer.run_cmd, mock_tracer.logger)

    @patch("tracer.symbol_trace_plugin.register_global_callbacks")
    def test_initialization_failure(self, mock_register_global_callbacks):
        """Test initialization failure when callback registration fails."""
        mock_register_global_callbacks.return_value = False
        mock_tracer = MagicMock()
        mock_tracer.logger = MagicMock()
        mock_notify_class = MagicMock()

        with self.assertRaises(RuntimeError) as context:
            st_plugin.SymbolTrace(mock_tracer, mock_notify_class, symbol_info_cache_file=None)

        self.assertEqual(str(context.exception), "Failed to register global callbacks")
        mock_tracer.logger.error.assert_called_with(
            "SymbolTrace initialization failed due to callback registration failure"
        )

    def test_init_sets_attributes_and_globals(self):
        """Tests that SymbolTrace __init__ correctly initializes attributes and sets global instance."""
        mock_tracer = MagicMock()
        mock_notify_class = MagicMock()
        mock_tracer.logger = MagicMock()
        cache_file = None

        old_instance = getattr(st_plugin, "_SYMBOL_TRACE_INSTANCE", None)
        self.addCleanup(setattr, st_plugin, "_SYMBOL_TRACE_INSTANCE", old_instance)

        with patch("tracer.symbol_trace_plugin.register_global_callbacks", return_value=True) as mock_register:
            instance = st_plugin.SymbolTrace(mock_tracer, mock_notify_class, cache_file)

            self.assertEqual(instance.tracer, mock_tracer)
            self.assertEqual(instance.notify, mock_notify_class)
            self.assertEqual(instance.symbol_info_cache_file, cache_file)
            self.assertEqual(instance.regex_cache, {})
            self.assertEqual(instance.enter_breakpoints, {})
            self.assertIsInstance(instance.thread_stacks, defaultdict)
            self.assertEqual(len(instance.thread_stacks), 0)
            self.assertIsNotNone(instance.lock)
            self.assertIsNotNone(instance.console)
            self.assertIs(st_plugin._SYMBOL_TRACE_INSTANCE, instance)

            expected_cmd = (
                "script globals()['_symbol_trace_instance'] = tracer.symbol_trace_plugin._SYMBOL_TRACE_INSTANCE"
            )
            mock_tracer.run_cmd.assert_called_once_with(expected_cmd)
            mock_register.assert_called_once_with(mock_tracer.run_cmd, mock_tracer.logger)

    def test_init_raises_on_callback_failure(self):
        """Tests that SymbolTrace __init__ raises RuntimeError when callback registration fails."""
        mock_tracer = MagicMock()
        mock_notify_class = MagicMock()
        mock_tracer.logger = MagicMock()

        with patch("tracer.symbol_trace_plugin.register_global_callbacks", return_value=False):
            with self.assertRaises(RuntimeError):
                st_plugin.SymbolTrace(mock_tracer, mock_notify_class, None)


class TestNotifyClass(unittest.TestCase):
    """Test cases for the NotifyClass functionality."""

    def test_notify_class_default_behavior(self):
        """Test that default NotifyClass methods can be called without errors."""
        from tracer.symbol_trace_plugin import NotifyClass

        notify = NotifyClass()
        mock_event = MagicMock()

        notify.symbol_enter(mock_event)
        notify.symbol_leave(mock_event)

        mock_event.assert_not_called()


class TestRegisterGlobalCallbacks(unittest.TestCase):
    """Test cases for the register_global_callbacks function."""

    @patch("tracer.symbol_trace_plugin._CALLBACKS_REGISTERED", False)
    def test_successful_registration(self):
        """Test successful registration of global callbacks when not already registered."""
        mock_run_cmd = MagicMock(return_value=None)
        mock_logger = MagicMock()

        result = st_plugin.register_global_callbacks(mock_run_cmd, mock_logger)

        self.assertTrue(result)
        expected_calls = [
            call("script import tracer"),
            call(
                "script globals()['_on_enter_breakpoint_wrapper'] = tracer.symbol_trace_plugin._on_enter_breakpoint_wrapper"
            ),
            call(
                "script globals()['_on_return_breakpoint_wrapper'] = tracer.symbol_trace_plugin._on_return_breakpoint_wrapper"
            ),
        ]
        mock_run_cmd.assert_has_calls(expected_calls)
        self.assertEqual(mock_run_cmd.call_count, 3)
        mock_logger.error.assert_not_called()

    @patch("tracer.symbol_trace_plugin._CALLBACKS_REGISTERED", True)
    def test_already_registered(self):
        """Test that function returns True without running commands when callbacks are already registered."""
        mock_run_cmd = MagicMock()
        mock_logger = MagicMock()

        result = st_plugin.register_global_callbacks(mock_run_cmd, mock_logger)

        self.assertTrue(result)
        mock_run_cmd.assert_not_called()
        mock_logger.error.assert_not_called()
        mock_logger.info.assert_called_once_with("Global callbacks already registered")

    @patch("tracer.symbol_trace_plugin._CALLBACKS_REGISTERED", False)
    def test_failure_during_registration(self):
        """Test that function returns False and logs error when command execution fails."""
        mock_run_cmd = MagicMock()
        mock_run_cmd.side_effect = Exception("Command error")
        mock_logger = MagicMock()

        result = st_plugin.register_global_callbacks(mock_run_cmd, mock_logger)

        self.assertFalse(result)
        self.assertGreaterEqual(mock_run_cmd.call_count, 1)
        # 修复：确保断言匹配生产代码中 logger.error 的实际调用方式 (f-string 生成单一字符串)
        mock_logger.error.assert_called_once_with("Failed to register global callbacks: Command error")


if __name__ == "__main__":
    unittest.main()
