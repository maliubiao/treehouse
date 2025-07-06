import logging
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import yaml

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = str(Path(__file__).resolve().parent.parent / "debugger/lldb")
print(project_root)
sys.path.insert(0, str(project_root))


from tracer.config import ConfigManager
from tracer.core import Tracer

# Imported for ConfigManager-specific tests


class BaseTestTracer(unittest.TestCase):
    """
    Base class for Tracer tests, providing common setup for mocking
    Tracer's external dependencies like lldb, LogManager, and ConfigManager.
    This ensures Tracer's __init__ can run during tests without real external dependencies.
    """

    def setUp(self):
        # Create a mock for lldb and its components
        self.mock_lldb = MagicMock()
        self.mock_lldb.SBDebugger.Create.return_value = MagicMock()
        self.mock_lldb.SBDebugger.Initialize.return_value = True
        self.mock_lldb.SBDebugger.SetAsync.return_value = None
        self.mock_lldb.SBListener.return_value = MagicMock(name="mock_sb_listener")
        # Set constants for lldb states needed by Tracer
        self.mock_lldb.eStateStopped = 1
        self.mock_lldb.eStateRunning = 2
        self.mock_lldb.SBCommandReturnObject = MagicMock(name="mock_sb_command_return_object")  # Used by run_cmd
        self.mock_lldb.SBError = MagicMock(name="mock_sb_error")  # Used by attach

        # Mock the LogManager and its instance
        self.mock_log_manager_class = MagicMock()
        self.mock_log_manager_instance = MagicMock()
        self.mock_log_manager_class.return_value = self.mock_log_manager_instance
        # The Tracer expects the LogManager instance to have a logger attribute
        self.mock_logger = MagicMock(spec=logging.Logger)  # Use spec for more robust mock
        self.mock_logger.name = "TestTracerLogger"  # Added: Explicitly set a name for the mocked logger
        self.mock_log_manager_instance.logger = self.mock_logger

        # Mock the ConfigManager and its instance
        self.mock_config_manager_class = MagicMock()
        self.mock_config_manager_instance = MagicMock()
        self.mock_config_manager_class.return_value = self.mock_config_manager_instance
        # Set an empty config by default, can be overridden by specific tests
        self.mock_config_manager_instance.config = {}
        # Ensure default behavior for methods Tracer might call
        self.mock_config_manager_instance.get_log_level.return_value = logging.INFO
        self.mock_config_manager_instance.get_config.return_value = {}
        self.mock_config_manager_instance.get_bool.return_value = True  # Default for forward_stdin etc.
        self.mock_config_manager_instance.get_skip_source_files.return_value = []
        self.mock_config_manager_instance.get_skip_modules.return_value = []
        self.mock_config_manager_instance.get_symbol_trace_patterns.return_value = []

        # Start patching core dependencies within the Tracer module
        self.patchers = [
            patch("tracer.core.lldb", self.mock_lldb),
            patch("tracer.core.LogManager", self.mock_log_manager_class),
            patch("tracer.core.ConfigManager", self.mock_config_manager_class),
            # Patch time.sleep globally for any Tracer calls
            patch("tracer.core.time.sleep", return_value=None),
        ]
        for patcher in self.patchers:
            patcher.start()

        # Initialize Tracer after mocks are patched
        from tracer.core import Tracer

        self.tracer = Tracer(program_path="/mock/program/path")  # Provide a dummy program_path

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()


class TestTracerContinueToMain(unittest.TestCase):
    """
    Test suite for Tracer.continue_to_main functionality.
    Tests validate behavior around waiting for the entry point breakpoint event.
    These tests use a minimalistic Tracer instance for focused testing.
    """

    def test_continue_to_main_event_already_set(self):
        """
        Test that when the entry point event is already set,
        continue_to_main exits immediately without processing.
        """
        # Create Tracer instance without invoking full constructor
        tracer = Tracer.__new__(Tracer)
        tracer.entry_point_breakpoint_event = MagicMock()
        tracer.entry_point_breakpoint_event.is_set.return_value = True
        tracer.process = MagicMock()

        tracer.continue_to_main()

        # Verify no processing occurred
        tracer.process.Continue.assert_not_called()

    def test_continue_to_main_wait_and_continue(self):
        """
        Test that continue_to_main waits for the event while
        continuing the process and sleeping between checks.
        """
        # Create Tracer instance without invoking full constructor
        tracer = Tracer.__new__(Tracer)
        tracer.entry_point_breakpoint_event = MagicMock()
        tracer.entry_point_breakpoint_event.is_set.side_effect = [False, False, True]
        tracer.process = MagicMock()

        # Patch time.sleep to avoid actual sleeping
        with patch("tracer.core.time.sleep") as mock_sleep:
            tracer.continue_to_main()

        # Verify Continue called twice and sleep called with 0.1
        self.assertEqual(tracer.process.Continue.call_count, 2)
        mock_sleep.assert_has_calls([call(0.1), call(0.1)])

    def test_continue_to_main_no_process(self):
        """
        Test behavior when process is None - should sleep but not attempt to continue.
        """
        # Create Tracer instance without invoking full constructor
        tracer = Tracer.__new__(Tracer)
        tracer.entry_point_breakpoint_event = MagicMock()
        tracer.entry_point_breakpoint_event.is_set.side_effect = [False, False, True]
        tracer.process = None  # No process available

        # Patch time.sleep to avoid actual sleeping
        with patch("tracer.core.time.sleep") as mock_sleep:
            tracer.continue_to_main()

        # Verify sleep still occurs but no Continue attempted
        mock_sleep.assert_has_calls([call(0.1), call(0.1)])


class TestTracerInitialization(BaseTestTracer):
    """Test cases for Tracer class initialization."""

    def test_init_sets_correct_attributes_and_relationships(self):
        mock_debugger = self.mock_lldb.SBDebugger.Create.return_value
        self.mock_log_manager_class.return_value = self.mock_log_manager_instance
        self.mock_config_manager_class.return_value = self.mock_config_manager_instance
        self.mock_config_manager_instance.config = {"test": "config"}

        self.mock_log_manager_class.reset_mock()
        self.mock_config_manager_class.reset_mock()
        self.mock_lldb.SBDebugger.Create.reset_mock()
        self.mock_lldb.SBListener.reset_mock()

        tracer = Tracer(
            program_path="/test/program",
            program_args=["arg1", "arg2"],
            logfile="test.log",
            config_file="test_config.yaml",
        )

        self.assertEqual(tracer.program_path, "/test/program")
        self.assertEqual(tracer.program_args, ["arg1", "arg2"])
        self.assertEqual(tracer.logfile, "test.log")
        self.assertIsInstance(tracer.entry_point_breakpoint_event, threading.Event)
        self.assertIsInstance(tracer.die_event, threading.Event)
        self.assertEqual(tracer.breakpoint_table, {})
        self.assertEqual(tracer.breakpoint_seen, set())

        self.mock_log_manager_class.assert_called_once_with(None, "test.log")
        self.assertEqual(tracer.log_manager, self.mock_log_manager_instance)
        self.assertEqual(tracer.logger, self.mock_log_manager_instance.logger)

        self.mock_config_manager_class.assert_called_once_with("test_config.yaml", tracer.logger)
        self.assertEqual(tracer.config_manager, self.mock_config_manager_instance)

        self.assertEqual(tracer.log_manager.config, {"test": "config"})

        self.mock_lldb.SBDebugger.Create.assert_called_once()
        mock_debugger.Initialize.assert_called_once()
        mock_debugger.SetAsync.assert_called_once_with(True)
        self.mock_lldb.SBListener.assert_called_once_with("TracerListener")
        self.assertEqual(tracer.debugger, mock_debugger)
        self.assertEqual(tracer.listener, self.mock_lldb.SBListener.return_value)

        self.assertIsNone(tracer.modules)
        self.assertIsNone(tracer.source_ranges)
        self.assertIsNone(tracer.step_handler)
        self.assertIsNone(tracer.breakpoint_handler)
        self.assertIsNone(tracer.event_loop)

    def test_init_with_minimal_args(self):
        self.mock_log_manager_class.reset_mock()
        self.mock_config_manager_class.reset_mock()
        self.mock_lldb.SBDebugger.Create.reset_mock()

        tracer = Tracer()

        self.assertIsNone(tracer.program_path)
        self.assertEqual(tracer.program_args, [])
        self.assertIsNone(tracer.attach_pid)

        self.mock_log_manager_class.assert_called_once_with(None, None)

        self.mock_config_manager_class.assert_called_once_with(None, tracer.logger)

        self.mock_lldb.SBDebugger.Create.assert_called()


class TestTracerStdinForwarding(BaseTestTracer):
    """Test cases for the Tracer class's stdin forwarding functionality."""

    def test_start_stdin_forwarding_no_valid_process(self):
        """Tests that stdin forwarding isn't started when process is invalid."""
        # Setup - override the Tracer instance from BaseTestTracer to simulate no process
        tracer = Tracer(program_path=None, config_file=None, logfile=None)
        tracer.process = None  # Simulate no valid process
        tracer.logger = self.mock_logger  # Use the mocked logger from base

        # Execute
        tracer._start_stdin_forwarding()

        # Verify
        tracer.logger.warning.assert_called_once_with("Cannot start stdin forwarding - no valid process")
        self.assertIsNone(tracer.stdin_forwarding_thread)

    @patch("tracer.core.threading.Thread")
    def test_start_stdin_forwarding_successful_start(self, mock_thread_class):
        """Tests successful stdin forwarding thread creation and start."""
        # Setup
        self.tracer.process = MagicMock()
        self.tracer.process.IsValid.return_value = True
        self.tracer.stdin_forwarding_stop = MagicMock(spec=threading.Event)

        mock_thread_instance = mock_thread_class.return_value

        # Execute
        self.tracer._start_stdin_forwarding()

        # Verify
        self.mock_logger.info.assert_called_once_with("Starting stdin forwarding to debugged process")
        self.tracer.stdin_forwarding_stop.clear.assert_called_once()
        mock_thread_class.assert_called_once_with(
            target=self.tracer._stdin_forwarding_loop, name="stdin_forwarding", daemon=True
        )
        mock_thread_instance.start.assert_called_once()
        self.assertEqual(self.tracer.stdin_forwarding_thread, mock_thread_instance)

    @patch("tracer.core.get_platform_stdin_listener")
    def test_stdin_forwarding_loop_normal_operation(self, mock_get_listener):
        """Tests the stdin forwarding loop under normal operating conditions."""
        # Setup
        self.tracer.process = MagicMock()
        self.tracer.stdin_forwarding_stop = MagicMock(spec=threading.Event)
        self.tracer.stdin_forwarding_stop.is_set.side_effect = [False, False, True]  # Break loop

        # Mock stdin listener
        mock_listener = MagicMock()
        mock_listener.has_input.side_effect = [True, False, False]  # Input then no more
        mock_listener.read.return_value = b"test input"
        mock_get_listener.return_value = mock_listener

        # Execute
        self.tracer._stdin_forwarding_loop()

        # Verify
        self.assertEqual(mock_listener.has_input.call_count, 2)  # Called twice for first False, then True (before read)
        mock_listener.read.assert_called_once()
        self.tracer.process.PutSTDIN.assert_called_once_with(b"test input")
        self.mock_logger.debug.assert_called_once_with("Forwarded %d bytes to debugged process", 10)
        # time.sleep is already patched in BaseTestTracer setup
        # self.mock_time_sleep.assert_called_with(0.05) # If we had direct access to that mock

    @patch("tracer.core.get_platform_stdin_listener")
    def test_stdin_forwarding_loop_os_error(self, mock_get_listener):
        """Tests loop termination on OSError during input reading."""
        # Setup
        self.tracer.process = MagicMock()
        self.tracer.stdin_forwarding_stop = MagicMock(spec=threading.Event)
        self.tracer.stdin_forwarding_stop.is_set.side_effect = [False, True]  # Break after error

        # Mock stdin listener to raise OSError
        mock_listener = MagicMock()
        mock_listener.has_input.return_value = True
        mock_listener.read.side_effect = OSError("Test error")
        mock_get_listener.return_value = mock_listener

        # Execute
        self.tracer._stdin_forwarding_loop()

        # Verify
        self.mock_logger.error.assert_called_once_with("OS error in stdin forwarding: %s", "Test error")
        self.mock_logger.info.assert_called_once_with("Stdin forwarding stopped")

    @patch("tracer.core.get_platform_stdin_listener")
    def test_stdin_forwarding_loop_generic_exception(self, mock_get_listener):
        """
        Tests that unexpected exceptions during input reading are properly handled
        and logged without crashing the loop. Validates exception safety.
        """
        # Setup
        self.tracer.process = MagicMock()
        self.tracer.process.IsValid.return_value = True
        self.tracer.stdin_forwarding_stop = MagicMock(spec=threading.Event)
        self.tracer.stdin_forwarding_stop.is_set.side_effect = [False, True]

        # Mock listener to simulate unexpected error
        mock_listener = MagicMock()
        mock_listener.has_input.return_value = True
        mock_listener.read.side_effect = ValueError("Test Unexpected Error")
        mock_get_listener.return_value = mock_listener

        # Execute
        self.tracer._stdin_forwarding_loop()

        # Validate
        self.mock_logger.error.assert_called_once_with(
            "Unexpected error in stdin forwarding: %s", "Test Unexpected Error"
        )
        self.tracer.process.PutSTDIN.assert_not_called()
        self.mock_logger.info.assert_called_once_with("Stdin forwarding stopped")

    @patch("tracer.core.get_platform_stdin_listener")
    def test_stdin_forwarding_loop_process_invalid(self, mock_get_listener):
        """Tests loop termination when process becomes invalid."""
        # Setup
        self.tracer.process = MagicMock()
        self.tracer.process.IsValid.return_value = False  # Process becomes invalid
        self.tracer.stdin_forwarding_stop = MagicMock(spec=threading.Event)
        self.tracer.stdin_forwarding_stop.is_set.return_value = False

        # Mock stdin listener
        mock_listener = MagicMock()
        mock_get_listener.return_value = mock_listener

        # Execute
        self.tracer._stdin_forwarding_loop()

        # Verify
        self.mock_logger.info.assert_called_once_with("Stdin forwarding stopped")


class TestTracerRunCmd(BaseTestTracer):
    """Test cases for the Tracer.run_cmd method."""

    def setUp(self):
        super().setUp()
        self.tracer.debugger = MagicMock()
        self.tracer.logger = self.mock_logger

        self.mock_command_interpreter = MagicMock()
        self.tracer.debugger.GetCommandInterpreter.return_value = self.mock_command_interpreter

    def test_run_cmd_success_with_output(self):
        mock_result = MagicMock()
        mock_result.Succeeded.return_value = True
        mock_result.GetOutput.return_value = "Command output"
        mock_result.GetError.return_value = ""

        with patch("tracer.core.lldb.SBCommandReturnObject", return_value=mock_result):
            self.tracer.run_cmd("valid command")

        self.tracer.logger.info.assert_any_call("Running LLDB command: %s", "valid command")
        self.tracer.logger.info.assert_any_call("Command output: %s", "Command output")
        self.tracer.logger.error.assert_not_called()
        self.tracer.logger.warning.assert_not_called()

    def test_run_cmd_success_without_output(self):
        mock_result = MagicMock()
        mock_result.Succeeded.return_value = True
        mock_result.GetOutput.return_value = ""
        mock_result.GetError.return_value = ""

        with patch("tracer.core.lldb.SBCommandReturnObject", return_value=mock_result):
            self.tracer.run_cmd("valid command")

        self.tracer.logger.info.assert_called_once_with("Running LLDB command: %s", "valid command")
        self.tracer.logger.error.assert_not_called()
        self.tracer.logger.warning.assert_not_called()

    def test_run_cmd_failure_raises_exception(self):
        mock_result = MagicMock()
        mock_result.Succeeded.return_value = False
        mock_result.GetOutput.return_value = "Partial output"
        mock_result.GetError.return_value = "Command failed"

        with patch("tracer.core.lldb.SBCommandReturnObject", return_value=mock_result):
            with self.assertRaisesRegex(ValueError, "Command failed: Command failed"):
                self.tracer.run_cmd("invalid command", raise_on_error=True)

        self.tracer.logger.info.assert_any_call("Running LLDB command: %s", "invalid command")
        self.tracer.logger.info.assert_any_call("Command output: %s", "Partial output")
        self.tracer.logger.error.assert_called_once_with("Command failed: %s", "Command failed")

    def test_run_cmd_failure_logs_warning(self):
        mock_result = MagicMock()
        mock_result.Succeeded.return_value = False
        mock_result.GetOutput.return_value = "Partial output"
        mock_result.GetError.return_value = "Command failed"

        with patch("tracer.core.lldb.SBCommandReturnObject", return_value=mock_result):
            self.tracer.run_cmd("invalid command", raise_on_error=False)

        self.tracer.logger.info.assert_any_call("Running LLDB command: %s", "invalid command")
        self.tracer.logger.info.assert_any_call("Command output: %s", "Partial output")
        self.tracer.logger.warning.assert_called_once_with("Command failed (non-fatal): %s", "Command failed")

    def test_run_cmd_empty_command(self):
        self.tracer.run_cmd("")

        self.tracer.logger.warning.assert_called_once_with("Empty command provided")
        self.tracer.debugger.GetCommandInterpreter.assert_not_called()

    def test_run_cmd_debugger_not_initialized(self):
        self.tracer.debugger = None

        self.tracer.run_cmd("any command")

        self.tracer.logger.error.assert_called_once_with("Debugger is not initialized")


class TestTracerInitializeComponents(BaseTestTracer):
    """Unit tests for the Tracer class component initialization."""

    @patch("tracer.core.ModuleManager")
    @patch("tracer.core.SourceRangeManager")
    @patch("tracer.core.StepHandler")
    @patch("tracer.core.BreakpointHandler")
    @patch("tracer.core.EventLoop")
    @patch("tracer.core.prepare_hooker")
    def test_initialize_components_sets_all_dependencies(
        self,
        mock_prepare_hooker,
        MockEventLoop,
        MockBreakpointHandler,
        MockStepHandler,
        MockSourceRangeManager,
        MockModuleManager,
    ):
        """Tests that _initialize_components correctly initializes all tracer components with proper dependencies."""
        # The tracer instance is already created in BaseTestTracer's setUp.
        # Ensure target, logger, config_manager, listener are set on self.tracer
        self.tracer.target = MagicMock()
        self.tracer.logger = self.mock_logger
        self.tracer.config_manager = self.mock_config_manager_instance
        self.tracer.listener = self.mock_lldb.SBListener.return_value

        # Call the method under test
        Tracer._initialize_components(self.tracer)

        # Verify component initialization with correct dependencies
        MockModuleManager.assert_called_once_with(self.tracer.target, self.tracer.logger, self.tracer.config_manager)
        MockSourceRangeManager.assert_called_once_with(
            self.tracer.target, self.tracer.logger, self.tracer.config_manager
        )
        MockStepHandler.assert_called_once_with(self.tracer)
        MockBreakpointHandler.assert_called_once_with(self.tracer)
        MockEventLoop.assert_called_once_with(self.tracer, self.tracer.listener, self.tracer.logger)
        mock_prepare_hooker.assert_called_once_with(self.tracer)

        # Verify components are assigned to tracer instance
        self.assertIs(self.tracer.modules, MockModuleManager.return_value)
        self.assertIs(self.tracer.source_ranges, MockSourceRangeManager.return_value)
        self.assertIs(self.tracer.step_handler, MockStepHandler.return_value)
        self.assertIs(self.tracer.breakpoint_handler, MockBreakpointHandler.return_value)
        self.assertIs(self.tracer.event_loop, MockEventLoop.return_value)


class TestTracerInstall(BaseTestTracer):
    """Test cases for Tracer.install functionality."""

    def test_install_runs_required_commands(self):
        """Test that install runs required LLDB configuration commands."""
        mock_target = MagicMock()
        # Patch run_cmd directly on the Tracer class for this test
        with patch.object(Tracer, "run_cmd") as mock_run_cmd:
            # self.tracer.run_cmd = mock_run_cmd  # Ensure this instance uses the patched method
            # Call the install method
            self.tracer.install(mock_target)

            # Verify required commands were executed
            expected_calls = [
                call("command script import --allow-reload tracer"),
                call("settings set target.use-fast-stepping true", raise_on_error=False),
                call("settings set target.process.follow-fork-mode child", raise_on_error=False),
                call("settings set use-color false", raise_on_error=False),
            ]
            mock_run_cmd.assert_has_calls(expected_calls, any_order=False)

    @patch.object(Tracer, "_set_entrypoint_breakpoint")
    def test_install_sets_entrypoint_breakpoint(self, mock_set_entrypoint):
        """Test that install sets the entrypoint breakpoint in standard mode."""
        mock_target = MagicMock()

        def side_effect_func():
            self.tracer.breakpoint = MagicMock(name="mock_breakpoint_set_by_install")

        mock_set_entrypoint.side_effect = side_effect_func

        self.tracer.install(mock_target)

        mock_set_entrypoint.assert_called_once_with()
        self.assertIsNotNone(self.tracer.breakpoint)

    @patch.object(Tracer, "_set_entrypoint_breakpoint")
    def test_attach_mode_sets_symbol_breakpoint(self, mock_set_entrypoint):
        """Test that attach mode correctly sets symbol breakpoint to 'main'."""
        mock_target = MagicMock()
        self.tracer.attached = True  # Simulate attach mode

        # Configure config manager mock for this test
        self.mock_config_manager_instance.get_config.return_value = {
            "entry_point": {"type": "symbol", "symbol_name": "main"}
        }

        # Call the install method
        self.tracer.install(mock_target)

        # Verify configuration was updated and logged
        self.mock_logger.info.assert_called_with("Using 'main' symbol as entry point in attach mode")
        mock_set_entrypoint.assert_called_once_with()

    def test_breakpoint_logging_when_enabled(self):
        """Test that breakpoint info is logged when configured."""
        mock_target = MagicMock()
        # Configure config manager to enable breakpoint logging
        # Directly modify the config dictionary as Tracer.install reads from it
        self.mock_config_manager_instance.config["log_breakpoint_details"] = True

        # Call the install method
        self.tracer.install(mock_target)

        # Verify breakpoint info was logged
        self.mock_log_manager_instance.log_breakpoint_info.assert_called_once()

    def test_breakpoint_logging_when_disabled(self):
        """Test that breakpoint info is not logged when disabled."""
        mock_target = MagicMock()
        # Configure config manager to disable breakpoint logging
        self.mock_config_manager_instance.get_bool.side_effect = (
            lambda key, default: False if key == "log_breakpoint_info" else default
        )

        # Call the install method
        self.tracer.install(mock_target)

        # Verify breakpoint info was not logged
        self.mock_log_manager_instance.log_breakpoint_info.assert_not_called()


class TestTracerEntryPointBreakpoint(BaseTestTracer):
    """Test cases for Tracer._set_entrypoint_breakpoint functionality."""

    def test_set_entrypoint_breakpoint_success(self):
        """Test successful creation of entrypoint breakpoint at 'main'."""
        # Create a mock breakpoint object
        mock_bp = MagicMock()
        mock_bp.IsValid.return_value = True

        # Configure target to return the mock breakpoint
        self.tracer.target = MagicMock()  # Ensure tracer.target is mocked for this specific test
        self.tracer.target.BreakpointCreateByName.return_value = mock_bp

        # Execute the method under test
        self.tracer._set_entrypoint_breakpoint()

        # Verify breakpoint creation parameters
        self.tracer.target.BreakpointCreateByName.assert_called_once_with(
            "main", os.path.basename(self.tracer.program_path)
        )

        # Verify breakpoint configuration
        mock_bp.SetOneShot.assert_called_once_with(True)

        # Verify breakpoint assignment
        self.assertEqual(self.tracer.breakpoint, mock_bp)

        # Verify logging
        self.mock_logger.info.assert_called_once_with("Set entry point breakpoint at %s", mock_bp)

    def test_set_entrypoint_breakpoint_failure(self):
        """Test failure case when breakpoint creation fails."""
        # Create an invalid breakpoint mock
        mock_bp = MagicMock()
        mock_bp.IsValid.return_value = False

        # Configure target to return the invalid breakpoint
        self.tracer.target = MagicMock()  # Ensure tracer.target is mocked for this specific test
        self.tracer.target.BreakpointCreateByName.return_value = mock_bp

        # Verify assertion failure
        with self.assertRaises(AssertionError) as context:
            self.tracer._set_entrypoint_breakpoint()

        # Verify error message
        self.assertEqual(str(context.exception), "Failed to create entry point breakpoint")


class TestTracerSymbolTrace(BaseTestTracer):
    """Test cases for Tracer symbol tracing functionality."""

    @patch("tracer.core.register_global_callbacks")
    @patch("tracer.core.SymbolTrace")
    def test_use_symbol_trace_registers_symbols(self, MockSymbolTrace, mock_register_callbacks):
        """Tests that symbol tracing is properly initialized and patterns are registered.

        This validates that when symbol tracing is enabled with configured patterns:
        1. Global callbacks are registered with the correct arguments
        2. SymbolTrace instance is created with proper parameters
        3. Each configured pattern is registered with SymbolTrace
        """
        # Set up a clean tracer instance for this test to avoid side effects from base setup
        # Re-initialize Tracer to ensure its attributes are set for this specific test's patches
        tracer = Tracer()
        tracer.run_cmd = MagicMock()
        tracer.logger = self.mock_logger
        tracer.step_handler = MagicMock()
        tracer.config_manager = self.mock_config_manager_instance  # Use mocked config manager

        # Configure symbol trace patterns
        pattern1 = MagicMock(module="libc.so", regex="malloc|free")
        pattern2 = MagicMock(module="libpthread.so", regex="pthread_.*")
        self.mock_config_manager_instance.get_symbol_trace_patterns.return_value = [pattern1, pattern2]
        self.mock_config_manager_instance.get_symbol_trace_cache_file.return_value = "symbol_cache.json"

        # Execute the method under test
        tracer.use_symbol_trace()

        # Verify global callbacks were registered
        mock_register_callbacks.assert_called_once_with(tracer.run_cmd, tracer.logger)

        # Verify SymbolTrace was initialized correctly
        MockSymbolTrace.assert_called_once_with(tracer, tracer.step_handler, "symbol_cache.json")

        # Verify patterns were registered
        symbol_trace_instance = MockSymbolTrace.return_value
        expected_calls = [call("libc.so", "malloc|free", False), call("libpthread.so", "pthread_.*", False)]
        symbol_trace_instance.register_symbols.assert_has_calls(expected_calls)

        # Verify symbol_trace attribute was set
        self.assertEqual(tracer.symbol_trace, symbol_trace_instance)


class TestConfigManagerLoadingAndBasicValidation(unittest.TestCase):
    """Unit tests for ConfigManager configuration loading and basic validation."""

    @patch("tracer.config.logging.getLogger")
    def test_load_config_file_not_found(self, mock_get_logger):
        """Test that default config is used when config file is missing."""
        # Setup
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        # Execute
        config_manager = ConfigManager(config_file="missing.yaml", logger=mock_logger)

        # Verify
        # Corrected: Match the actual logging format with %s
        mock_logger.warning.assert_called_once_with(
            "Config file '%s' not found. Using default settings.", "missing.yaml"
        )
        self.assertEqual(config_manager.config["max_steps"], 100)  # Default value
        self.assertEqual(config_manager.config["log_mode"], "instruction")  # Default value

    @patch("tracer.config.open", new_callable=MagicMock)  # Using MagicMock for mock_open
    @patch("tracer.config.os.path.exists", return_value=True)
    @patch("tracer.config.yaml.safe_load")
    def test_load_config_valid_file(self, mock_safe_load, mock_exists, mock_open):
        """Test that valid config file updates default configuration."""
        # Setup
        mock_safe_load.return_value = {"max_steps": 500, "log_mode": "source"}

        # Execute
        config_manager = ConfigManager(config_file="valid.yaml")

        # Verify
        self.assertEqual(config_manager.config["max_steps"], 500)
        self.assertEqual(config_manager.config["log_mode"], "source")

    @patch("tracer.config.open", side_effect=OSError("Permission denied"))
    @patch("tracer.config.os.path.exists", return_value=True)
    def test_load_config_os_error(self, mock_exists, mock_open):
        """Test error handling when file exists but can't be opened."""
        # Setup
        mock_logger = MagicMock()

        # Execute
        config_manager = ConfigManager(config_file="restricted.yaml", logger=mock_logger)

        # Verify
        # Corrected: Use assert_any_call as there might be multiple error logs (e.g., skip symbols file)
        mock_logger.error.assert_any_call("Error loading config file '%s': %s", "restricted.yaml", unittest.mock.ANY)
        self.assertEqual(config_manager.config["max_steps"], 100)  # Default value

    @patch("tracer.config.open", new_callable=MagicMock)  # Using MagicMock for mock_open
    @patch("tracer.config.os.path.exists", return_value=True)
    @patch("tracer.config.yaml.safe_load", side_effect=yaml.YAMLError("Invalid YAML"))
    def test_load_config_yaml_error(self, mock_safe_load, mock_exists, mock_open):
        """Test error handling for invalid YAML files."""
        # Setup
        mock_logger = MagicMock()

        # Execute
        config_manager = ConfigManager(config_file="invalid.yaml", logger=mock_logger)

        # Verify
        # Corrected: Use assert_any_call as there might be multiple error logs
        mock_logger.error.assert_any_call("Error loading config file '%s': %s", "invalid.yaml", unittest.mock.ANY)
        self.assertEqual(config_manager.config["max_steps"], 100)  # Default value

    def test_handles_missing_config_files_gracefully(self):
        """Tests that missing config files don't break initialization and use defaults."""
        # Create mock logger
        mock_logger = MagicMock()

        # Initialize with non-existent config file
        config = ConfigManager(config_file="missing.yaml", logger=mock_logger)

        # Verify warning was logged
        mock_logger.warning.assert_called_with("Config file '%s' not found. Using default settings.", "missing.yaml")

        # Verify default values are intact
        self.assertEqual(config.get_log_mode(), "instruction")
        self.assertEqual(config.get_skip_source_files(), [])


class TestConfigManagerPathAndPatternValidation(unittest.TestCase):
    """Unit tests for ConfigManager path normalization and pattern merging/validation."""

    def test_merges_skip_patterns_from_multiple_files(self):
        """Tests that skip patterns are correctly merged from main config and skip symbols file."""
        # Create temporary files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create main config file
            main_config_path = os.path.join(tmpdir, "config.yaml")
            with open(main_config_path, "w") as f:
                yaml.dump(
                    {
                        "skip_source_files": ["/libc/*", "/stdlib/*"],
                        "skip_symbols_file": os.path.join(tmpdir, "skip_symbols.yaml"),
                    },
                    f,
                )

            # Create skip symbols file
            skip_path = os.path.join(tmpdir, "skip_symbols.yaml")
            with open(skip_path, "w") as f:
                yaml.dump({"skip_source_files": ["/usr/include/*", "/stdlib/*"]}, f)

            # Create mock logger
            mock_logger = MagicMock()

            # Initialize ConfigManager
            config = ConfigManager(config_file=main_config_path, logger=mock_logger)

            # Verify merged patterns
            patterns = config.get_skip_source_files()
            self.assertCountEqual(
                patterns,
                ["/libc/*", "/stdlib/*", "/usr/include/*"],
                "Should merge patterns from both files and remove duplicates",
            )

            # Verify info logging
            # Corrected: Match the actual logging format with %s
            mock_logger.info.assert_any_call("Loaded config from '%s'.", main_config_path)
            mock_logger.info.assert_any_call("Loaded and merged skip patterns from '%s'.", skip_path)
            mock_logger.error.assert_not_called()

    def test_validates_and_normalizes_paths(self):
        """Test that relative paths are converted to absolute paths during validation."""
        # Create mock logger
        mock_logger = MagicMock()

        # Create temp config file
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.yaml")
            rel_path = "relative/path"

            with open(config_path, "w") as f:
                yaml.dump(
                    {
                        "source_base_dir": rel_path,
                        "expression_hooks": [{"path": "hook/path", "line": 10, "expr": "some_expr"}],
                    },
                    f,
                )

            # Initialize ConfigManager
            config = ConfigManager(config_file=config_path, logger=mock_logger)

            # Verify paths were normalized
            # This assertion currently expects the correct behavior (path relative to config file).
            # The test output indicates ConfigManager itself resolves relative to CWD, which is a bug in ConfigManager.
            # Keeping the assertion as is to indicate desired behavior.
            expected_abs_source_base = os.path.abspath(os.path.join(os.path.dirname(config_path), rel_path))
            self.assertEqual(config.get_source_base_dir(), expected_abs_source_base)

            # Verify hook path was normalized
            hook = config.get_expression_hooks()[0]
            expected_abs_hook_path = os.path.abspath(os.path.join(os.path.dirname(config_path), "hook/path"))
            self.assertEqual(hook["path"], expected_abs_hook_path)

            # Verify normalization was logged
            # Corrected: Use assert_any_call as there might be multiple info logs and match %s format
            mock_logger.info.assert_any_call(
                "Converted relative source_base_dir '%s' to absolute path '%s'.", rel_path, expected_abs_source_base
            )

    def test_handles_invalid_config_structures(self):
        """Tests that invalid configuration structures are handled gracefully."""
        # Create temp config file with invalid data
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.yaml")
            with open(config_path, "w") as f:
                f.write("invalid: yaml: :")

            # Create mock logger
            mock_logger = MagicMock()

            # Initialize ConfigManager
            config = ConfigManager(config_file=config_path, logger=mock_logger)

            # Verify error was logged
            mock_logger.error.assert_called_with(
                "Error loading config file '%s': %s",
                config_path,
                unittest.mock.ANY,  # Error message varies by environment
            )

            # Verify defaults are still set
            self.assertEqual(config.get_log_mode(), "instruction")

    def test_skip_symbols_loading_with_empty_file(self):
        """Tests handling of empty skip symbols file."""
        # Create temporary files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create main config
            main_config_path = os.path.join(tmpdir, "config.yaml")
            with open(main_config_path, "w") as f:
                yaml.dump(
                    {"skip_symbols_file": os.path.join(tmpdir, "empty.yaml"), "skip_source_files": ["/existing/*"]}, f
                )

            # Create empty skip file
            skip_path = os.path.join(tmpdir, "empty.yaml")
            with open(skip_path, "w") as f:
                f.write("")

            # Create mock logger
            mock_logger = MagicMock()

            # Initialize ConfigManager
            config = ConfigManager(config_file=main_config_path, logger=mock_logger)

            # Verify patterns unchanged
            self.assertEqual(config.get_skip_source_files(), ["/existing/*"])

            # Verify no error logs
            mock_logger.error.assert_not_called()

    def test_validate_symbol_trace_patterns(self):
        """Test validation of symbol trace patterns configuration."""
        # Setup
        mock_logger = MagicMock()
        config_manager = ConfigManager(logger=mock_logger)
        invalid_config = [
            {"invalid_key": "test"},  # Missing required keys
            "not_a_dict",  # Invalid type
            {"module": "test", "regex": "valid"},  # Valid item
        ]

        # Execute
        config_manager.config["symbol_trace_patterns"] = invalid_config
        config_manager._validate_config()
        validated = config_manager.get_symbol_trace_patterns()

        # Verify
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0].module, "test")
        self.assertEqual(validated[0].regex, "valid")
        # Corrected: Match the actual logging format and messages
        mock_logger.warning.assert_has_calls(
            [
                call("Skipping invalid symbol_trace_pattern item: %s", {"invalid_key": "test"}),
                call("Skipping invalid symbol_trace_pattern item: %s", "not_a_dict"),
            ]
        )

    def test_validate_expression_hooks(self):
        """Test validation and normalization of expression hooks."""
        # Setup
        mock_logger = MagicMock()
        config_manager = ConfigManager(logger=mock_logger)

        test_hooks = [
            {"path": "rel/path", "line": 10, "expr": "test_expr"},  # Valid
            {"path": "/abs/path", "line": 20, "expr": "test_expr2"},  # Valid
            {"missing_keys": True},  # Invalid
            42,  # Invalid type
            {"path": 123, "line": "invalid", "expr": True},  # Invalid types
        ]

        # Execute
        config_manager.config["expression_hooks"] = test_hooks
        config_manager._validate_config()
        validated = config_manager.get_expression_hooks()

        # Verify
        self.assertEqual(len(validated), 2)
        # Check that relative path was normalized relative to the current working directory
        expected_abs_path = os.path.abspath("rel/path")
        self.assertEqual(validated[0]["path"], expected_abs_path)
        self.assertEqual(validated[1]["path"], "/abs/path")
        # Corrected: Match the actual logging format and messages (esp. 'item')
        mock_logger.error.assert_has_calls(
            [
                call(
                    "Skipping invalid expression_hook (missing 'path', 'line', or 'expr'): %s", {"missing_keys": True}
                ),
                call("Skipping invalid expression_hook item (not a dict): %s", 42),  # Added 'item'
                call(
                    "Skipping invalid expression_hook ('path' must be a string): %s",
                    {"path": 123, "line": "invalid", "expr": True},
                ),
            ]
        )

    # Removed: This test assumes ConfigManager directly triggers LogManager updates via a setter,
    # which is not how Tracer orchestrates these components.
    # The relevant behavior is already tested in TestTracerInitialization.test_init_sets_correct_attributes_and_relationships.
    # def test_config_update_triggers_logger_update(self):
    #     """Test that config updates propagate to LogManager."""
    #     # Setup
    #     mock_open = MagicMock()
    #     mock_exists = MagicMock(return_value=True)
    #     mock_safe_load = MagicMock(return_value={'log_buffer_size': 20})

    #     with patch('tracer.config.open', new=mock_open), \
    #          patch('tracer.config.os.path.exists', return_value=True), \
    #          patch('tracer.config.yaml.safe_load', new=mock_safe_load):

    #         config_manager = ConfigManager(config_file="update.yaml")
    #         mock_log_manager = MagicMock()
    #         config_manager.log_manager = mock_log_manager  # Simulate Tracer's log manager setting this

    #         # Verify: the setter for log_manager calls update_config on the log_manager
    #         mock_log_manager.update_config.assert_called_once_with(config_manager.config)
    #         self.assertEqual(mock_log_manager.config['log_buffer_size'], 20)


if __name__ == "__main__":
    unittest.main()
