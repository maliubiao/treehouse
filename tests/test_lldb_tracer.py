import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

import yaml

# Add the tracer directory to the Python path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "native_context_tracer/src")))
from native_context_tracer.config import ConfigManager

# --- Test Cases ---


class LLDBTracerBaseTestCase(unittest.TestCase):
    """
    A base class for all tracer tests. It sets up a mocked environment
    at the class level, ensuring that tests are isolated and self-contained.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up a mocked environment before any tests in this class are run.

        This method patches critical modules like 'lldb' and then imports the
        application modules under test. These modules are stored as class
        attributes, making them available to all test methods in subclasses.
        """
        cls.mock_lldb = MagicMock()
        cls.mock_lldb.eStateStopped = 5
        cls.mock_lldb.eStateRunning = 6
        cls.mock_lldb.eBroadcastBitStateChanged = 1
        cls.mock_lldb.eBroadcastBitSTDOUT = 2
        cls.mock_lldb.eBroadcastBitSTDERR = 4
        cls.mock_lldb.eStopReasonPlanComplete = 8
        cls.mock_lldb.eStopReasonBreakpoint = 3
        cls.mock_lldb.eStopReasonNone = 1
        cls.mock_lldb.LLDB_INVALID_ADDRESS = -1

        cls.module_patcher = patch.dict(
            sys.modules,
            {
                "lldb": cls.mock_lldb,
                "op_parser": MagicMock(),
                "tree": MagicMock(),
                "ai": MagicMock(),
            },
        )
        cls.module_patcher.start()

        # With the mocks in place, we can now safely import the application modules.
        # They are assigned to class attributes for easy access in test methods.
        from native_context_tracer.config import ConfigManager
        from native_context_tracer.core import Tracer
        from native_context_tracer.event_loop import EventLoop
        from native_context_tracer.modules import ModuleManager
        from native_context_tracer.step_handler import StepAction, StepHandler

        cls.ConfigManager = ConfigManager
        cls.Tracer = Tracer
        cls.StepHandler = StepHandler
        cls.StepAction = StepAction
        cls.ModuleManager = ModuleManager
        cls.EventLoop = EventLoop

        # Assign the mocked op_parser module for convenient access in tests.
        cls.op_parser = sys.modules["op_parser"]

    @classmethod
    def tearDownClass(cls):
        """
        Clean up the mocked environment after all tests in this class have run.
        """
        cls.module_patcher.stop()


class TestConfigManager(LLDBTracerBaseTestCase):
    """Tests for the ConfigManager class."""

    def setUp(self):
        """Set up a temporary directory and a mock logger for each test."""
        self.mock_logger = MagicMock()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_data = {
            "max_steps": 500,
            "log_target_info": False,
            "skip_modules": ["/usr/lib/system/*", "*libsystem*"],
            "environment": {"TEST_VAR": "123", "ANOTHER_VAR": "abc"},
            "expression_hooks": [{"path": "/app/src/main.c", "line": 42, "expr": "my_var"}],
        }
        self.temp_config_path = os.path.join(self.temp_dir.name, "tracer_config.yaml")
        with open(self.temp_config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.config_data, f)

    def tearDown(self):
        """Clean up the temporary directory."""
        self.temp_dir.cleanup()

    def test_init_with_defaults(self):
        """Test that ConfigManager initializes with default values when no file is provided."""
        with patch("threading.Thread"):
            manager = ConfigManager(logger=self.mock_logger)
            self.assertEqual(manager.config["max_steps"], 100)
            self.assertTrue(manager.config["log_target_info"])
            self.assertEqual(manager.config_file, "tracer_config.yaml")

    def test_load_config_from_file(self):
        """Test loading configuration from a specified YAML file."""
        with patch("threading.Thread"):
            manager = ConfigManager(config_file=self.temp_config_path, logger=self.mock_logger)
            self.assertEqual(manager.config["max_steps"], 500)
            self.assertFalse(manager.config["log_target_info"])
            self.assertIn("/usr/lib/system/*", manager.config["skip_modules"])
            self.assertTrue(self.mock_logger.info.called)

    def test_load_skip_symbols(self):
        """Test that skip symbols are correctly loaded and merged."""
        main_config_path = os.path.join(self.temp_dir.name, "config.yaml")
        skip_symbols_path = os.path.join(self.temp_dir.name, "skips.yaml")

        # Use an absolute path for skip_symbols_file to make the test robust
        main_config_data = {"skip_symbols_file": skip_symbols_path, "skip_source_files": ["initial/skip.c"]}
        with open(main_config_path, "w", encoding="utf-8") as f:
            yaml.dump(main_config_data, f)

        skip_symbols_data = {"skip_source_files": ["new/skip.c", "another/skip.cpp"]}
        with open(skip_symbols_path, "w", encoding="utf-8") as f:
            yaml.dump(skip_symbols_data, f)

        # The patches for os.path.exists and os.getcwd are removed as they are
        # misleading and not needed when using an absolute path.
        with patch("threading.Thread"):
            manager = ConfigManager(config_file=main_config_path, logger=self.mock_logger)
            expected_skips = {"initial/skip.c", "new/skip.c", "another/skip.cpp"}
            self.assertSetEqual(set(manager.config["skip_source_files"]), expected_skips)
            # Check that the log message uses the correct (absolute) path
            self.mock_logger.info.assert_any_call("Loaded and merged skip patterns from '%s'.", skip_symbols_path)

    def test_validate_expression_hooks(self):
        """Test the validation logic for expression_hooks."""
        manager = ConfigManager(logger=self.mock_logger)
        self.assertEqual(manager._validate_expression_hooks([]), [])

        valid_hook = [{"path": "/tmp/test.c", "line": 10, "expr": "x"}]
        with patch("os.path.abspath", return_value="/tmp/test.c"):
            validated = manager._validate_expression_hooks(valid_hook)
            self.assertEqual(validated[0]["path"], "/tmp/test.c")

        invalid_hooks = [
            "not_a_dict",
            {"line": 10, "expr": "x"},
            {"path": "/tmp/test.c", "expr": "x"},
            {"path": "/tmp/test.c", "line": 10},
            {"path": 123, "line": 10, "expr": "x"},
        ]
        self.assertEqual(manager._validate_expression_hooks(invalid_hooks), [])
        self.assertGreaterEqual(self.mock_logger.error.call_count, 4)

    def test_get_environment_list(self):
        """Test the retrieval of environment variables as a list."""
        with patch("threading.Thread"):
            manager = ConfigManager(config_file=self.temp_config_path, logger=self.mock_logger)
            env_list = manager.get_environment_list()
            self.assertIn("TEST_VAR=123", env_list)
            self.assertIn("ANOTHER_VAR=abc", env_list)
            self.assertEqual(len(env_list), 2)

    def test_get_source_base_dir(self):
        """Test source_base_dir validation and retrieval."""
        manager = ConfigManager(logger=self.mock_logger)
        with patch("os.path.abspath", return_value="/abs/some/relative/path") as mock_abspath:
            validated_path = manager._validate_source_base_dir("some/relative/path")
            self.assertTrue(os.path.isabs(validated_path))
            self.assertEqual(validated_path, "/abs/some/relative/path")

        abs_path = os.path.abspath("absolute/path")
        self.assertEqual(manager._validate_source_base_dir(abs_path), abs_path)
        self.assertEqual(manager._validate_source_base_dir(""), "")


class TestCore(LLDBTracerBaseTestCase):
    """Tests for the Tracer core class."""

    def setUp(self):
        self.mock_logger = MagicMock()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.yaml")
        with open(self.config_path, "w") as f:
            yaml.dump({}, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_tracer(self):
        """Helper to create a fully mocked Tracer instance."""
        with patch("native_context_tracer.core.lldb.SBDebugger.Create", return_value=MagicMock()):
            tracer = self.Tracer(config_file=self.config_path, logfile=None)
        tracer.logger = self.mock_logger
        tracer.debugger = MagicMock()
        tracer.target = MagicMock()
        tracer.process = MagicMock()
        tracer.listener = MagicMock()
        tracer.config_manager = self.ConfigManager(config_file=self.config_path, logger=self.mock_logger)
        tracer.modules = MagicMock(spec=self.ModuleManager)
        tracer.source_ranges = MagicMock()
        return tracer

    @patch("native_context_tracer.core.LogManager")
    @patch("native_context_tracer.core.ConfigManager")
    @patch("native_context_tracer.core.lldb.SBDebugger.Create")
    def test_core_init(self, mock_debugger_create, mock_config_manager, mock_log_manager):
        """Test the initialization of the Tracer class."""
        mock_debugger_instance = MagicMock()
        mock_debugger_create.return_value = mock_debugger_instance

        with patch("threading.Thread"):
            tracer = self.Tracer()
            mock_debugger_create.assert_called_once()
            mock_debugger_instance.Initialize.assert_called_once()
            mock_debugger_instance.SetAsync.assert_called_with(True)
            mock_debugger_instance.SetInternalVariable.assert_called_once_with(
                "target.process.extra-startup-command", "QSetLogging:bitmask=LOG_ALL", tracer.logger.name
            )

    def test_install_calls(self):
        """Test that the install method makes the correct sequence of `run_cmd` calls."""
        mock_tracer = self._create_mock_tracer()
        mock_tracer.run_cmd = MagicMock()
        mock_bp = MagicMock()
        mock_tracer.target.BreakpointCreateByName.return_value = mock_bp
        mock_tracer.program_path = "/path/to/program"

        mock_tracer.install(mock_tracer.target)

        expected_calls = [
            call("command script import native_context_tracer"),
            call("settings set target.use-fast-stepping true", raise_on_error=False),
            call("settings set target.process.follow-fork-mode child", raise_on_error=False),
            call("settings set use-color false", raise_on_error=False),
        ]
        mock_tracer.run_cmd.assert_has_calls(expected_calls, any_order=False)
        mock_tracer.target.BreakpointCreateByName.assert_called_once_with("main", "program")
        mock_bp.SetOneShot.assert_called_once_with(True)
        self.assertEqual(mock_tracer.breakpoint, mock_bp)

    @patch("native_context_tracer.core.os.getcwd", return_value="/fake/dir")
    @patch("threading.Thread")
    @patch("native_context_tracer.lldb_console.show_console")
    def test_start_launch_process(self, mock_show_console, mock_thread, mock_getcwd):
        """Test that the start method correctly launches a process."""
        from unittest.mock import ANY

        mock_tracer = self._create_mock_tracer()
        mock_tracer.program_path = "build/basic_program"
        mock_tracer.program_args = ["arg1", "arg2"]
        mock_tracer._initialize_components = MagicMock()
        mock_tracer.install = MagicMock()
        mock_tracer._start_stdin_forwarding = MagicMock()
        mock_tracer.event_loop = MagicMock()

        mock_process = MagicMock()
        # Use the defined eStateStopped value from setUp
        mock_process.GetState.return_value = 5
        mock_tracer.target.Launch.return_value = mock_process
        mock_tracer.debugger.CreateTarget.return_value = mock_tracer.target

        result = mock_tracer.start()

        self.assertTrue(result)
        mock_tracer._initialize_components.assert_called_once()
        mock_tracer.install.assert_called_once_with(mock_tracer.target)

        env_list = mock_tracer.config_manager.get_environment_list()
        mock_tracer.target.Launch.assert_called_once_with(
            mock_tracer.listener,
            ["arg1", "arg2"],
            env_list,
            None,
            None,
            None,
            "/fake/dir",
            False,
            True,
            ANY,  # 修复：使用 ANY 匹配任何 SBError 实例
        )
        mock_tracer._start_stdin_forwarding.assert_called_once()
        mock_tracer.event_loop.run.assert_called_once()


class TestModuleManager(LLDBTracerBaseTestCase):
    """Tests for the ModuleManager class."""

    def setUp(self):
        self.mock_logger = MagicMock()
        # 修复：移除无效的spec参数，直接创建MagicMock对象
        mock_target = MagicMock()
        mock_config_manager = MagicMock()
        mock_config_manager.config = {"skip_modules": []}
        self.module_manager = self.ModuleManager(
            target=mock_target, logger=self.mock_logger, config_manager=mock_config_manager
        )

    def test_should_skip_address_based_on_log(self):
        """Test should_skip_address logic based on scenarios from trace.log."""
        # Scenario 1: Address in a skipped module
        self.module_manager.config_manager.config["skip_modules"] = ["/usr/lib/system/*"]
        self.assertTrue(self.module_manager.should_skip_address(0x1803177AC, "/usr/lib/system/libsystem_c.dylib"))

        # Scenario 2: Address in a non-skipped module
        self.module_manager.config_manager.config["skip_modules"] = ["/usr/lib/system/*"]
        self.assertFalse(self.module_manager.should_skip_address(0x104FB0F30, "/path/to/libso3.dylib"))

        # Scenario 3: Address in a range that is explicitly skipped
        self.module_manager._skip_ranges = [{"start_addr": 0x1000, "end_addr": 0x2000}]
        self.module_manager._skip_addresses = [0x1000]
        self.assertTrue(self.module_manager.should_skip_address(0x1500, "/path/to/some.dylib"))
        self.assertFalse(self.module_manager.should_skip_address(0x2500, "/path/to/some.dylib"))


class TestStepHandler(LLDBTracerBaseTestCase):
    """Tests for the StepHandler class."""

    def setUp(self):
        """Provides a StepHandler instance with a mocked tracer."""
        mock_tracer = MagicMock()
        mock_tracer.config_manager.get_log_mode.return_value = "instruction"
        mock_tracer.config_manager.get_step_action.return_value = {}
        mock_tracer.config_manager.get_expression_hooks.return_value = []
        mock_tracer.config_manager.get_source_base_dir.return_value = ""
        mock_tracer.run_cmd = MagicMock()
        mock_tracer.modules.should_skip_address = MagicMock()
        mock_tracer.target = MagicMock()

        self.mock_tracer = mock_tracer
        self.handler = self.StepHandler(tracer=mock_tracer)
        self.handler.source_handler = MagicMock()
        self.handler.debug_info_handler = MagicMock()
        import op_parser

        self.op_parser = op_parser

    def test_init(self):
        """Test StepHandler initialization logic."""
        self.assertEqual(self.handler.tracer, self.mock_tracer)
        self.assertEqual(self.handler.logger, self.mock_tracer.logger)
        self.assertTrue(self.handler.insutruction_mode)
        self.assertEqual(self.handler.step_in, self.StepAction.STEP_IN)
        self.assertEqual(self.handler.step_over, self.StepAction.STEP_OVER)

        expected_calls = [
            call("script import native_context_tracer"),
            call(
                "script globals()['plt_step_over_callback'] = native_context_tracer.step_handler.plt_step_over_callback"
            ),
        ]
        self.mock_tracer.run_cmd.assert_has_calls(expected_calls)

    def test_is_branch_instruction(self):
        """Test identification of branch instructions."""
        test_cases = [
            ("b", True),
            ("bl", True),
            ("br", True),
            ("blr", True),
            ("braa", True),
            ("mov", False),
            ("add", False),
            ("ldr", False),
        ]
        for mnemonic, expected in test_cases:
            with self.subTest(mnemonic=mnemonic):
                self.assertEqual(self.handler.is_branch_instruction(mnemonic), expected)

    def test_is_return_instruction(self):
        """Test identification of return instructions."""
        test_cases = [
            ("ret", True),
            ("retl", True),
            ("retq", True),
            ("b", False),
            ("bl", False),
        ]
        for mnemonic, expected in test_cases:
            with self.subTest(mnemonic=mnemonic):
                self.assertEqual(self.handler.is_return_instruction(mnemonic), expected)

    def test_on_step_hit_should_skip(self):
        """Test that on_step_hit correctly handles skippable addresses."""
        mock_frame = MagicMock()
        mock_frame.GetPCAddress.return_value.GetLoadAddress.return_value = 0x1000
        mock_frame.module.file.fullpath = "/usr/lib/system/libdyld.dylib"

        self.mock_tracer.modules.should_skip_address.return_value = True
        self.handler.go_back_to_normal_frame = MagicMock(return_value=True)

        self.handler.on_step_hit(mock_frame, "some_reason")

        self.mock_tracer.modules.should_skip_address.assert_called_once_with(0x1000, "/usr/lib/system/libdyld.dylib")
        self.handler.go_back_to_normal_frame.assert_called_once_with(mock_frame)

    def test_determine_step_action_for_branch_to_skipped_address(self):
        """Replicate the 'br' to skipped address scenario from trace.log."""
        mock_frame = MagicMock()
        mock_reg = MagicMock()
        mock_reg.unsigned = 6863681452
        mock_reg.IsValid.return_value = True  # 确保寄存器有效
        mock_frame.FindRegister.return_value = mock_reg

        mock_symbol = MagicMock()
        mock_start_addr = MagicMock()
        mock_start_addr.GetLoadAddress.return_value = 0x1000
        mock_end_addr = MagicMock()
        mock_end_addr.GetLoadAddress.return_value = 0x2000
        mock_symbol.GetStartAddress.return_value = mock_start_addr
        mock_symbol.GetEndAddress.return_value = mock_end_addr
        mock_frame.symbol = mock_symbol

        self.handler._get_address_info = MagicMock(return_value=("rewind", "/usr/lib/system/libsystem_c.dylib", 2))
        self.handler._should_skip_branch_address = MagicMock(return_value=True)
        self.handler._update_lru_breakpoint = MagicMock()

        # 修改这里：确保_get_branch_target返回预期地址
        self.handler._get_branch_target = MagicMock(return_value=6863681452)

        mock_operand = MagicMock(type=self.op_parser.OperandType.REGISTER, value="x16")
        action = self.handler._determine_step_action("br", [mock_operand], mock_frame, 0, 4, "")

        self.handler._should_skip_branch_address.assert_called_with(6863681452, "/usr/lib/system/libsystem_c.dylib")
        self.handler._update_lru_breakpoint.assert_called_once_with(4)
        self.assertEqual(action, self.StepAction.STEP_OVER)


class TestEventLoop(LLDBTracerBaseTestCase):
    """Tests for the EventLoop class."""

    def setUp(self):
        """Provides an EventLoop instance with a mocked tracer."""
        self.mock_tracer = MagicMock()
        self.mock_tracer.step_handler = MagicMock(spec=self.StepHandler)
        self.mock_tracer.listener = MagicMock()
        self.mock_tracer.show_console = MagicMock()
        self.mock_logger = MagicMock()
        self.event_loop = self.EventLoop(
            tracer=self.mock_tracer, listener=self.mock_tracer.listener, logger=self.mock_logger
        )
        self.mock_tracer.main_thread_id = 0

    def test_handle_plan_complete_calls_on_step_hit(self):
        """Verify that a 'plan complete' event triggers on_step_hit."""
        mock_thread = MagicMock()
        mock_frame = MagicMock()
        mock_thread.GetFrameAtIndex.return_value = mock_frame

        self.mock_tracer.entry_point_breakpoint_event.is_set.return_value = True
        self.mock_tracer.step_handler.on_step_hit.return_value = self.StepAction.STEP_IN
        self.event_loop.action_handle = MagicMock()

        self.event_loop._handle_plan_complete(mock_thread)

        self.mock_tracer.step_handler.on_step_hit.assert_called_once_with(mock_frame, "threadplan")
        self.event_loop.action_handle.assert_called_once_with(self.StepAction.STEP_IN, mock_thread)

    def test_handle_stopped_state_routes_to_plan_complete(self):
        """Test that a stopped state with reason PlanComplete is routed correctly."""
        mock_process = MagicMock()
        mock_thread = MagicMock()
        mock_process.GetSelectedThread.return_value = mock_thread
        mock_thread.GetStopReason.return_value = self.mock_lldb.eStopReasonPlanComplete

        self.event_loop._handle_plan_complete = MagicMock()
        self.event_loop._handle_stopped_state(mock_process, MagicMock())
        self.event_loop._handle_plan_complete.assert_called_once_with(mock_thread)


if __name__ == "__main__":
    unittest.main()
