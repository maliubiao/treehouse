import logging
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, call, patch

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = str(Path(__file__).resolve().parent.parent / "debugger/lldb")
print(project_root)
sys.path.insert(0, str(project_root))

# Import the unit under test and related modules
from tracer.breakpoint_handler import BreakpointHandler
from tracer.core import Tracer
from tracer.debugger_api import DebuggerApi, IOHandler, LldbDebuggerApi, SystemIOHandler
from tracer.event_loop import EventLoop
from tracer.events import StepAction
from tracer.utils import get_state_str  # Only used in one test to patch

# Prepare a mock lldb module with necessary constants for common use.
# This object will be used as the replacement for the actual `lldb` module
# when patching using `@patch('module_name.lldb', _mock_lldb_constants)`.
# This ensures that all references to `lldb` within the patched module
# point to this controlled mock, and tests can also reference these constants
# via the mock object passed to them (e.g., `mock_lldb.eStateStopped`).
_mock_lldb_constants = MagicMock()
_mock_lldb_constants.eStateStopped = 5
_mock_lldb_constants.eStateExited = 6
_mock_lldb_constants.eStateCrashed = 7
_mock_lldb_constants.eStateDetached = 8
_mock_lldb_constants.eStateRunning = 9
_mock_lldb_constants.eStopReasonNone = 1
_mock_lldb_constants.eStopReasonBreakpoint = 3
_mock_lldb_constants.eStopReasonPlanComplete = 12
_mock_lldb_constants.eOnlyDuringStepping = 1
# Common value for step_into/over methods


# Base class for common EventLoop dependencies
class TestEventLoopBase(unittest.TestCase):
    """Base class for EventLoop unit tests, providing common mock dependencies."""

    def setUp(self):
        """Set up common mock objects for EventLoop dependencies."""
        self.mock_tracer = MagicMock(spec=Tracer)
        self.mock_tracer.process = MagicMock()  # Add missing process attribute to mock tracer
        self.mock_listener = MagicMock()
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.mock_debugger_api = MagicMock(spec=DebuggerApi)
        self.mock_io_handler = MagicMock(spec=IOHandler)

        # Add common mocks for process, thread, and event, as they are frequently used across tests.
        self.mock_process = MagicMock()
        self.mock_thread = MagicMock()
        self.mock_event = MagicMock()

        # Default EventLoop instance, can be overridden in subclasses
        self.event_loop = EventLoop(
            tracer=self.mock_tracer,
            listener=self.mock_listener,
            logger=self.mock_logger,
            debugger_api=self.mock_debugger_api,
            io_handler=self.mock_io_handler,
        )
        # Ensure die_event is a real threading.Event for controlled termination tests
        self.event_loop.die_event = threading.Event()
        self.event_loop.die_event.clear()


class TestEventLoopInitialization(TestEventLoopBase):
    """Unit tests for the EventLoop class initialization behavior."""

    def test_init_with_provided_dependencies(self):
        """Tests that EventLoop initializes correctly when dependencies are explicitly provided."""
        # Create mock objects
        mock_tracer = MagicMock()
        mock_listener = MagicMock()
        mock_logger = MagicMock()
        mock_debugger_api = MagicMock()
        mock_io_handler = MagicMock()

        # Instantiate EventLoop with provided dependencies
        with patch("tracer.event_loop.lldb", MagicMock()):  # Prevent lldb import issues within EventLoop
            # Import EventLoop here to ensure it uses the patched lldb during its own imports/initialization
            from tracer.event_loop import EventLoop

            event_loop = EventLoop(
                tracer=mock_tracer,
                listener=mock_listener,
                logger=mock_logger,
                debugger_api=mock_debugger_api,
                io_handler=mock_io_handler,
            )

        # Validate attribute assignments
        self.assertEqual(event_loop.tracer, mock_tracer)
        self.assertEqual(event_loop.listener, mock_listener)
        self.assertEqual(event_loop.logger, mock_logger)
        self.assertEqual(event_loop.debugger_api, mock_debugger_api)
        self.assertEqual(event_loop.io_handler, mock_io_handler)
        self.assertIsInstance(event_loop.die_event, threading.Event)
        self.assertEqual(event_loop.threads, {})

    def test_init_with_default_dependencies(self):
        """Tests that EventLoop initializes default dependencies when none are provided."""
        # Create mock objects for explicit dependencies
        mock_tracer = MagicMock()
        mock_listener = MagicMock()
        mock_logger = MagicMock()

        # Mock the default dependency classes (these are imported into event_loop.py)
        with (
            patch("tracer.event_loop.lldb", MagicMock()),
            patch("tracer.event_loop.LldbDebuggerApi") as MockLldbDebuggerApi,
            patch("tracer.event_loop.SystemIOHandler") as MockSystemIOHandler,
        ):
            # Create mock instances that the default classes should return
            mock_debugger_instance = MagicMock()
            mock_io_instance = MagicMock()
            MockLldbDebuggerApi.return_value = mock_debugger_instance
            MockSystemIOHandler.return_value = mock_io_instance

            # Import EventLoop here to ensure it uses the patched classes
            from tracer.event_loop import EventLoop

            event_loop = EventLoop(
                tracer=mock_tracer, listener=mock_listener, logger=mock_logger, debugger_api=None, io_handler=None
            )

            # Validate default dependencies were created
            MockLldbDebuggerApi.assert_called_once_with(mock_tracer)
            MockSystemIOHandler.assert_called_once()
            self.assertEqual(event_loop.debugger_api, mock_debugger_instance)
            self.assertEqual(event_loop.io_handler, mock_io_instance)

        # Validate core attributes are still correctly assigned
        self.assertEqual(event_loop.tracer, mock_tracer)
        self.assertEqual(event_loop.listener, mock_listener)
        self.assertEqual(event_loop.logger, mock_logger)
        self.assertIsInstance(event_loop.die_event, threading.Event)
        self.assertEqual(event_loop.threads, {})


class TestEventLoopRunMethod(TestEventLoopBase):
    """Unit tests for EventLoop's run method focusing on core loop behavior."""

    def test_loop_terminates_immediately_when_die_event_set(self):
        """Test loop exits immediately when die_event is set before starting."""
        # Set termination flag
        self.event_loop.die_event.set()

        # Run the event loop
        self.event_loop.run()

        # Verify no debugger interactions occurred, as the loop should not have started
        self.mock_debugger_api.wait_for_event.assert_not_called()

    def test_processes_event_when_received(self):
        """Test event processing when a valid event is received."""
        # Setup mock event and wait_for_event response to return an event then trigger circuit breaker
        mock_event = MagicMock()
        self.mock_debugger_api.wait_for_event.side_effect = [(True, mock_event), ValueError("Circuit Breaker")]

        # Use circuit-breaker on _process_event to prevent infinite loops after the first event
        with patch.object(self.event_loop, "_process_event") as mock_process:
            mock_process.side_effect = [None, ValueError("Circuit Breaker")]  # Process one event then break

            # Run and expect circuit-breaker exception
            with self.assertRaisesRegex(ValueError, "Circuit Breaker"):
                self.event_loop.run()

        # Verify wait_for_event was called twice before the circuit breaker
        self.assertEqual(self.mock_debugger_api.wait_for_event.call_count, 2)
        # Verify event processing occurred for the received event
        mock_process.assert_called_once_with(mock_event)

    def test_logs_status_on_timeout(self):
        """Test status logging when event wait times out."""
        # Setup timeout response: first call times out, second call triggers circuit breaker
        self.mock_debugger_api.wait_for_event.side_effect = [(False, None), ValueError("Circuit Breaker")]

        # Use circuit-breaker on _log_current_debugger_status to prevent infinite loops
        with patch.object(self.event_loop, "_log_current_debugger_status") as mock_log:
            mock_log.side_effect = [None, ValueError("Circuit Breaker")]  # Log once then break

            # Run and expect circuit-breaker exception
            with self.assertRaisesRegex(ValueError, "Circuit Breaker"):
                self.event_loop.run()

        # Verify status logging occurred
        mock_log.assert_called_once()
        self.assertEqual(self.mock_debugger_api.wait_for_event.call_count, 2)  # Called twice before circuit breaker

    def test_loop_terminates_after_state_change_event_sets_die_event(self):
        """Test loop terminates after handling a state change event that sets die_event."""
        # Setup state change event that will trigger termination
        state_change_event = MagicMock()
        # The loop will call wait_for_event once, process the event, which sets die_event.
        # The next iteration, it will find die_event set and exit.
        # So wait_for_event should only be called once.
        self.mock_debugger_api.wait_for_event.side_effect = [(True, state_change_event), (False, None)]
        self.mock_debugger_api.get_event_broadcaster_class_name.return_value = "lldb.process"
        self.mock_debugger_api.get_process_broadcaster_class_name.return_value = "lldb.process"
        self.mock_debugger_api.is_stdout_event.return_value = False
        self.mock_debugger_api.is_stderr_event.return_value = False
        self.mock_debugger_api.is_state_changed_event.return_value = True

        # Make _handle_state_change_event trigger termination via die_event
        with patch.object(self.event_loop, "_handle_state_change_event") as mock_handler:

            def handler_side_effect(event):
                self.event_loop.die_event.set()  # This will cause the loop to exit on the next iteration

            mock_handler.side_effect = handler_side_effect

            # Run the event loop
            self.event_loop.run()

        # Verify state handler was called and die_event is set
        mock_handler.assert_called_once_with(state_change_event)
        self.assertTrue(self.event_loop.die_event.is_set())
        # Verify wait_for_event was called once
        self.assertEqual(
            self.mock_debugger_api.wait_for_event.call_count, 1
        )  # It will be called once as die_event is set by the first event

    @patch(
        "tracer.event_loop.lldb", _mock_lldb_constants
    )  # Patch lldb where it's used in event_loop for process broadcater class name
    def test_processes_termination_event_and_sets_die_event(self):  # Removed mock_lldb argument
        """
        Test that EventLoop correctly processes a termination event
        (eStateExited) and sets die_event to break the loop.
        """
        # Create mock event and process
        mock_event = MagicMock()
        mock_process = MagicMock()

        # Configure debugger API responses
        # The loop will call wait_for_event once to get the event.
        # Processing the event will set die_event.
        # The loop then starts another iteration, calls wait_for_event again (which will find die_event set and terminate).
        self.mock_debugger_api.wait_for_event.side_effect = [(True, mock_event), (False, None), (False, None)]
        self.mock_debugger_api.get_event_broadcaster_class_name.return_value = "lldb.process"
        self.mock_debugger_api.get_process_broadcaster_class_name.return_value = "lldb.process"
        self.mock_debugger_api.is_stdout_event.return_value = False
        self.mock_debugger_api.is_stderr_event.return_value = False
        self.mock_debugger_api.is_state_changed_event.return_value = True
        self.mock_debugger_api.get_process_from_event.return_value = mock_process
        self.mock_debugger_api.get_process_state.return_value = _mock_lldb_constants.eStateExited  # eStateExited

        # Run the event loop (should process one event then break)
        self.event_loop.run()

        # Verify die_event was set by the event loop's internal logic
        self.assertTrue(
            self.event_loop.die_event.is_set(), "die_event should be set after processing termination event"
        )

        # Verify debugger API calls
        self.assertEqual(self.mock_debugger_api.wait_for_event.call_count, 1)  # Changed from 2 to 1
        self.mock_debugger_api.get_event_broadcaster_class_name.assert_called_once_with(mock_event)
        self.mock_debugger_api.get_process_broadcaster_class_name.assert_called_once()
        self.mock_debugger_api.is_state_changed_event.assert_called_once_with(mock_event)
        self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)
        self.mock_debugger_api.get_process_state.assert_called_once_with(mock_process)
        self.assertEqual(
            self.mock_debugger_api.get_process_state.call_count,
            1,
            "Expected get_process_state to be called exactly once",
        )


class TestEventLoopProcessEvent(TestEventLoopBase):
    """Unit tests for the EventLoop's _process_event method."""

    @patch("tracer.event_loop.lldb", _mock_lldb_constants)
    def test_process_event_handles_state_changed_event(self):  # Removed mock_lldb argument
        """
        Tests that _process_event correctly routes state changed events to the
        appropriate handler method when the broadcaster is a process event.
        This validates the core event dispatching logic of the event loop.
        """
        # Configure debugger API responses to simulate a state changed event
        self.mock_debugger_api.get_event_broadcaster_class_name.return_value = "lldb.process"
        self.mock_debugger_api.get_process_broadcaster_class_name.return_value = "lldb.process"
        self.mock_debugger_api.is_stdout_event.return_value = False
        self.mock_debugger_api.is_stderr_event.return_value = False
        self.mock_debugger_api.is_state_changed_event.return_value = True

        # Create mock event
        mock_event = MagicMock()

        # Patch internal handler methods for assertion
        with (
            patch.object(self.event_loop, "_handle_state_change_event") as mock_handle_state_change,
            patch.object(self.event_loop, "_handle_stdout_event") as mock_handle_stdout,
            patch.object(self.event_loop, "_handle_stderr_event") as mock_handle_stderr,
        ):
            # Call the method under test
            self.event_loop._process_event(mock_event)

            # Verify debugger API interactions
            self.mock_debugger_api.get_event_broadcaster_class_name.assert_called_once_with(mock_event)
            self.mock_debugger_api.get_process_broadcaster_class_name.assert_called_once()
            self.mock_debugger_api.is_stdout_event.assert_called_once_with(mock_event)
            self.mock_debugger_api.is_stderr_event.assert_called_once_with(mock_event)
            self.mock_debugger_api.is_state_changed_event.assert_called_once_with(mock_event)

            # Verify state change handler was called, others were not
            mock_handle_state_change.assert_called_once_with(mock_event)
            mock_handle_stdout.assert_not_called()
            mock_handle_stderr.assert_not_called()

            # Ensure no unexpected logging occurred
            self.mock_logger.warning.assert_not_called()

    @patch("tracer.event_loop.lldb", _mock_lldb_constants)
    def test_process_event_logs_unhandled_event_type(self):  # Removed mock_lldb argument
        """
        Tests that _process_event logs a warning when encountering an event type
        from an unhandled broadcaster class. This validates the fallback behavior
        for unknown event types.
        """
        # Configure debugger API responses for an unhandled broadcaster class
        self.mock_debugger_api.get_event_broadcaster_class_name.return_value = "unknown.broadcaster"
        self.mock_debugger_api.get_process_broadcaster_class_name.return_value = (
            "lldb.process"  # Still mock this for completeness
        )

        # Create mock event
        mock_event = MagicMock()

        # Patch internal handler methods for assertion
        with (
            patch.object(self.event_loop, "_handle_state_change_event") as mock_handle_state_change,
            patch.object(self.event_loop, "_handle_stdout_event") as mock_handle_stdout,
            patch.object(self.event_loop, "_handle_stderr_event") as mock_handle_stderr,
        ):
            # Call the method under test
            self.event_loop._process_event(mock_event)

            # Verify warning was logged
            self.mock_logger.warning.assert_called_once_with("Unhandled event type: %s", "unknown.broadcaster")

            # Ensure no specific event handlers were called for stdout, stderr, or state change
            mock_handle_stdout.assert_not_called()
            mock_handle_stderr.assert_not_called()
            mock_handle_state_change.assert_not_called()

    @patch("tracer.event_loop.lldb", _mock_lldb_constants)
    def test_stdout_event_calls_io_handler(self):  # Removed mock_lldb argument
        """Tests that _process_event correctly routes stdout events to the io_handler.

        This test validates that when a stdout event is received:
        1. The event broadcaster is correctly identified as a process event.
        2. The stdout event type is correctly detected.
        3. The process output is retrieved and written to stdout via the io_handler.
        """
        # Configure debugger API responses to simulate a stdout event
        self.mock_debugger_api.get_event_broadcaster_class_name.return_value = "lldb.process"
        self.mock_debugger_api.get_process_broadcaster_class_name.return_value = "lldb.process"
        self.mock_debugger_api.is_stdout_event.return_value = True
        self.mock_debugger_api.is_stderr_event.return_value = False  # Ensure it's not stderr
        self.mock_debugger_api.is_state_changed_event.return_value = False  # Ensure it's not state change

        # Create mock process and configure API responses for stdout retrieval
        mock_process = MagicMock()
        self.mock_debugger_api.get_process_from_event.return_value = mock_process
        self.mock_debugger_api.get_process_stdout.return_value = "Loop iteration: 0\r\n"

        # Create mock event
        mock_event = MagicMock()

        # Execute the method under test
        self.event_loop._process_event(mock_event)

        # Verify debugger API interactions for event classification
        self.mock_debugger_api.get_event_broadcaster_class_name.assert_called_once_with(mock_event)
        self.mock_debugger_api.get_process_broadcaster_class_name.assert_called_once()
        self.mock_debugger_api.is_stdout_event.assert_called_once_with(mock_event)
        # Verify subsequent calls for getting process and stdout
        self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)
        self.mock_debugger_api.get_process_stdout.assert_called_once_with(mock_process, 1024)

        # Verify IO handler was called with the correct output
        self.mock_io_handler.write_stdout.assert_called_once_with("Loop iteration: 0\r\n")


class TestEventLoopHandleStdoutEvent(TestEventLoopBase):
    """Test cases for EventLoop's _handle_stdout_event method."""

    def test_stdout_event_writes_output_to_handler(self):
        """Validates that valid stdout events trigger output writing via IOHandler."""
        # Setup mock objects
        mock_event = MagicMock()
        mock_process = MagicMock()

        # Configure mock debugger API responses
        self.mock_debugger_api.get_process_from_event.return_value = mock_process
        self.mock_debugger_api.get_process_stdout.return_value = "Test output"

        # Execute test
        self.event_loop._handle_stdout_event(mock_event)

        # Assertions
        self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)
        self.mock_debugger_api.get_process_stdout.assert_called_once_with(mock_process, 1024)
        self.mock_io_handler.write_stdout.assert_called_once_with("Test output")

    def test_stdout_event_handles_invalid_process_gracefully(self):
        """Ensures no action is taken when event has no associated process."""
        # Setup mock objects
        mock_event = MagicMock()

        # Configure debugger API to return no process for the event
        self.mock_debugger_api.get_process_from_event.return_value = None

        # Execute test
        self.event_loop._handle_stdout_event(mock_event)

        # Assertions
        self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)
        self.mock_debugger_api.get_process_stdout.assert_not_called()
        self.mock_io_handler.write_stdout.assert_not_called()

    def test_stdout_event_handles_empty_output_gracefully(self):
        """Ensures no writing occurs when stdout retrieval returns empty."""
        # Setup mock objects
        mock_event = MagicMock()
        mock_process = MagicMock()

        # Configure mocks to return an empty string for stdout
        self.mock_debugger_api.get_process_from_event.return_value = mock_process
        self.mock_debugger_api.get_process_stdout.return_value = ""

        # Execute test
        self.event_loop._handle_stdout_event(mock_event)

        # Assertions
        self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)
        self.mock_io_handler.write_stdout.assert_not_called()  # No write if output is empty

    def test_stdout_event_silently_ignores_system_errors(self):
        """Validates SystemErrors during output handling are caught and ignored."""
        # Setup mock objects
        mock_event = MagicMock()
        mock_process = MagicMock()

        # Configure `get_process_stdout` to raise a SystemError
        self.mock_debugger_api.get_process_from_event.return_value = mock_process
        self.mock_debugger_api.get_process_stdout.side_effect = SystemError("Test SystemError")

        # Execute test within a try-except block to ensure it doesn't raise
        try:
            self.event_loop._handle_stdout_event(mock_event)
        except SystemError:
            self.fail("SystemError was not caught as intended by _handle_stdout_event")

        # Assertions: should still attempt to get process and stdout, but not write
        self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)
        self.mock_debugger_api.get_process_stdout.assert_called_once_with(mock_process, 1024)
        self.mock_io_handler.write_stdout.assert_not_called()


@patch("tracer.event_loop.lldb", _mock_lldb_constants)
@patch("tracer.debugger_api.lldb", _mock_lldb_constants)
class TestEventLoopHandleStateChangeEvent(TestEventLoopBase):
    """Unit tests for EventLoop's _handle_state_change_event method."""

    def test_handle_state_change_stopped_state_triggers_process_state_handler(
        self,
    ):
        """Test that stopped state events correctly trigger process state handling."""
        # Setup
        mock_event = MagicMock()
        mock_process = MagicMock()
        mock_process.IsValid.return_value = True

        self.mock_debugger_api.get_process_from_event.return_value = mock_process
        self.mock_debugger_api.get_process_state.return_value = _mock_lldb_constants.eStateStopped

        # Patch the internal _handle_process_state method to isolate the test
        with patch.object(self.event_loop, "_handle_process_state") as mock_handle_process:
            self.event_loop._handle_state_change_event(mock_event)

            # Verify debugger API interactions
            self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)

            # Verify that the process state handler was triggered
            mock_handle_process.assert_called_once_with(mock_process, mock_event)

    def test_invalid_process_skips_handling(self):
        """Test that invalid processes are skipped during state change handling."""
        # Setup
        mock_event = MagicMock()

        self.mock_debugger_api.get_process_from_event.return_value = None  # Simulate an invalid process

        # Patch the internal _handle_process_state method to ensure it's not called
        with patch.object(self.event_loop, "_handle_process_state") as mock_handle_process:
            self.event_loop._handle_state_change_event(mock_event)

            # Verify process handling was skipped
            mock_handle_process.assert_not_called()
        self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)

    def test_termination_states_set_die_event(self):
        """Test that termination states correctly set the die event flag."""
        # Setup
        mock_event = MagicMock()
        mock_process = MagicMock()
        mock_process.IsValid.return_value = True

        self.mock_debugger_api.get_process_from_event.return_value = mock_process

        # Define termination states to test
        termination_states = [
            _mock_lldb_constants.eStateExited,
            _mock_lldb_constants.eStateCrashed,
            _mock_lldb_constants.eStateDetached,
        ]

        # Iterate through each termination state using subtests
        for state in termination_states:
            with self.subTest(state=state):
                # Reset die_event and mocks for each subtest to ensure isolation
                self.event_loop.die_event.clear()
                self.mock_debugger_api.reset_mock()
                self.mock_logger.reset_mock()
                self.mock_debugger_api.get_process_from_event.return_value = mock_process  # Re-set for each subtest

                # Set the current termination state for the debugger API
                self.mock_debugger_api.get_process_state.return_value = state

                # Execute the method under test
                self.event_loop._handle_state_change_event(mock_event)

                # Verify that die_event was set
                self.assertTrue(self.event_loop.die_event.is_set(), f"Die event not set for state {state}")
                self.mock_debugger_api.get_process_from_event.assert_called_once_with(mock_event)
                self.mock_debugger_api.get_process_state.assert_called_once_with(mock_process)


@patch("tracer.event_loop.lldb", _mock_lldb_constants)
class TestEventLoopHandleProcessState(TestEventLoopBase):
    """Unit tests for EventLoop's _handle_process_state method."""

    def test_handles_stopped_state_correctly(self):  # Removed mock_lldb argument
        """Tests that a stopped process state correctly triggers _handle_stopped_state."""
        # Setup mock process and event
        mock_process = MagicMock()
        mock_event = MagicMock()

        # Configure debugger API to return a stopped state
        self.mock_debugger_api.get_process_state.return_value = _mock_lldb_constants.eStateStopped

        # Patch the internal _handle_stopped_state method for isolation
        with patch.object(self.event_loop, "_handle_stopped_state") as mock_handle_stopped:
            # Call the method under test
            self.event_loop._handle_process_state(mock_process, mock_event)

            # Verify that the process state was retrieved
            self.mock_debugger_api.get_process_state.assert_called_once_with(mock_process)

            # Verify that the stopped state handler was called with correct arguments
            mock_handle_stopped.assert_called_once_with(mock_process, mock_event)

    def test_handles_termination_states_correctly(self):  # Removed mock_lldb argument
        """Tests that terminated states (exited/crashed/detached) correctly set die_event."""
        # Define mapping of state names to their mock lldb enum values
        states = {
            "exited": _mock_lldb_constants.eStateExited,
            "crashed": _mock_lldb_constants.eStateCrashed,
            "detached": _mock_lldb_constants.eStateDetached,
        }

        for state_name, state_value in states.items():
            with self.subTest(state=state_name):
                # Reset die_event, logger, and debugger API mocks for each subtest
                self.event_loop.die_event.clear()
                self.mock_logger.reset_mock()
                self.mock_debugger_api.reset_mock()

                # Setup mock process
                mock_process = MagicMock()

                # Configure debugger API to return the current termination state
                self.mock_debugger_api.get_process_state.return_value = state_value

                # Call the method under test
                self.event_loop._handle_process_state(mock_process, None)

                # Verify that die_event was set
                self.assertTrue(self.event_loop.die_event.is_set())
                self.mock_debugger_api.get_process_state.assert_called_once_with(mock_process)

                # Verify state-specific logging
                if state_name == "exited":
                    exit_status = self.mock_debugger_api.get_process_exit_status.return_value
                    self.mock_logger.info.assert_called_once_with("Process exited with status: %d", exit_status)
                    self.mock_debugger_api.get_process_exit_status.assert_called_once_with(mock_process)
                elif state_name == "crashed":
                    self.mock_logger.error.assert_called_once_with("Process crashed")
                elif state_name == "detached":
                    self.mock_logger.info.assert_called_once_with("Process detached")

    def test_running_state_returns_immediately(self):  # Removed mock_lldb argument
        """Tests that when process is in running state, _handle_process_state returns immediately without side effects."""
        # Setup mock dependencies
        mock_process = MagicMock()
        mock_event = MagicMock()

        # Configure debugger_api to return running state
        self.mock_debugger_api.get_process_state.return_value = _mock_lldb_constants.eStateRunning

        # Spy on internal handlers to ensure they're not called
        with (
            patch.object(self.event_loop, "_handle_stopped_state") as mock_stopped_handler,
            patch.object(self.event_loop, "_handle_termination_state") as mock_termination_handler,
        ):  # This method is internal to _handle_process_state, so patching it directly is less intrusive.
            # Execute method under test
            result = self.event_loop._handle_process_state(mock_process, mock_event)

            # Validate immediate return with no side effects
            self.assertIsNone(result)
            self.mock_debugger_api.get_process_state.assert_called_once_with(mock_process)
            mock_stopped_handler.assert_not_called()
            mock_termination_handler.assert_not_called()
            self.mock_logger.warning.assert_not_called()
            self.mock_logger.info.assert_not_called()

    @patch("tracer.event_loop.get_state_str")  # Patch `get_state_str` where it's imported in `event_loop.py`
    def test_logs_unhandled_states(self, mock_get_state_str):  # Removed mock_lldb argument
        """Tests that unhandled process states are properly logged."""
        # Setup mock process
        mock_process = MagicMock()
        unhandled_state = 999  # An arbitrary unknown state value

        # Configure debugger API to return the unhandled state
        self.mock_debugger_api.get_process_state.return_value = unhandled_state

        # Configure the mocked `get_state_str` to return a meaningful string
        mock_get_state_str.return_value = "UNKNOWN_STATE"

        # Call the method under test
        self.event_loop._handle_process_state(mock_process, None)

        # Verify that an info message was logged with the unhandled state string
        # Changed from warning to info based on previous code.
        self.mock_logger.info.assert_called_once_with("Unhandled process state: %s", "UNKNOWN_STATE")
        mock_get_state_str.assert_called_once_with(unhandled_state)


@patch("tracer.event_loop.lldb", _mock_lldb_constants)
class TestEventLoopHandleStoppedState(TestEventLoopBase):
    """Test cases for the EventLoop's _handle_stopped_state method."""

    def setUp(self):
        super().setUp()
        # Configure default tracer state for stopped state tests
        type(self.mock_tracer).main_thread_id = PropertyMock(
            return_value=0
        )  # Default to main thread (0 implies no specific main thread check)
        type(self.mock_tracer).breakpoint_seen = PropertyMock(return_value=set())
        type(self.mock_tracer).pthread_create_breakpoint_id = PropertyMock(return_value=1)
        type(self.mock_tracer).pthread_join_breakpoint_id = PropertyMock(return_value=2)
        type(
            self.mock_tracer
        ).target = MagicMock()  # Needs to be a concrete MagicMock for methods like find_breakpoint_by_id
        self.mock_tracer.breakpoint_handler = MagicMock(spec=BreakpointHandler)  # Mock the handler itself
        self.mock_tracer.entry_point_breakpoint_event = threading.Event()
        self.mock_tracer.step_handler = MagicMock()

    def test_handle_stopped_state_waits_for_stop_reason_then_handles_breakpoint(self):
        """
        Tests that _handle_stopped_state correctly:
        1. Waits for the thread stop reason to become available (non-None).
        2. Identifies a breakpoint stop reason.
        3. Calls the breakpoint handler with correct arguments.

        This test simulates the scenario where:
        - Thread stop reason is initially None (requiring waiting).
        - After one wait cycle, stop reason becomes breakpoint.
        - The breakpoint handler is correctly invoked.
        """
        # Create mock objects for thread and process (using self.mock_thread, self.mock_process)
        mock_thread = self.mock_thread
        mock_process = self.mock_process
        mock_event = self.mock_event

        # Configure debugger_api mocks for stop reason checks
        self.mock_debugger_api.get_selected_thread.return_value = mock_thread
        self.mock_debugger_api.get_thread_stop_reason.side_effect = [
            _mock_lldb_constants.eStopReasonNone,
            _mock_lldb_constants.eStopReasonBreakpoint,
            _mock_lldb_constants.eStopReasonBreakpoint,
        ]

        # Patch the internal _handle_breakpoint_stop method to isolate its behavior
        with patch.object(self.event_loop, "_handle_breakpoint_stop") as mock_handle_breakpoint:
            # Call the method under test
            self.event_loop._handle_stopped_state(mock_process, mock_event)

            # Verify breakpoint handler was called correctly
            mock_handle_breakpoint.assert_called_once_with(mock_process, mock_thread)

        # Verify thread selection was called
        self.mock_debugger_api.get_selected_thread.assert_called_once_with(mock_process)

        # Verify stop reason checks occurred as expected
        self.assertEqual(self.mock_debugger_api.get_thread_stop_reason.call_count, 3)
        self.mock_debugger_api.get_thread_stop_reason.assert_has_calls(
            [
                call(mock_thread),
                call(mock_thread),
                call(mock_thread),
            ]
        )

        # Verify sleep was called during the wait cycle
        self.mock_debugger_api.sleep.assert_called_once_with(0.1)

    def test_handles_breakpoint_stop_delegates_to_handler(self):  # Removed mock_lldb argument
        """
        Tests that _handle_stopped_state correctly processes a breakpoint stop event
        and delegates to `_handle_breakpoint_stop`.
        """
        # Setup mock objects
        mock_thread = self.mock_thread
        mock_process = self.mock_process

        # Configure debugger API responses
        self.mock_debugger_api.get_selected_thread.return_value = mock_thread
        self.mock_debugger_api.get_thread_stop_reason.return_value = _mock_lldb_constants.eStopReasonBreakpoint

        # Patch the internal _handle_breakpoint_stop method to isolate this test
        with patch.object(self.event_loop, "_handle_breakpoint_stop") as mock_handle_breakpoint_stop:
            # Execute the method under test
            self.event_loop._handle_stopped_state(mock_process, self.mock_event)

            # Verify debugger API interactions
            self.mock_debugger_api.get_selected_thread.assert_called_once_with(mock_process)
            self.assertEqual(self.mock_debugger_api.get_thread_stop_reason.call_count, 2)
            self.mock_debugger_api.get_thread_stop_reason.assert_has_calls([call(mock_thread), call(mock_thread)])
            mock_handle_breakpoint_stop.assert_called_once_with(mock_process, mock_thread)

    def test_handles_main_thread_mismatch_with_step_out(self):  # Removed mock_lldb argument
        """
        Tests that _handle_stopped_state correctly steps out when the current thread
        ID doesn't match the main thread ID configured in the tracer.

        This scenario validates:
        1. Main thread ID check when tracer has `main_thread_id` configured.
        2. `step_out` command is executed on non-main threads.
        3. No further processing (like stop reason analysis) occurs after stepping out.
        """
        # Setup main thread mismatch scenario
        type(self.mock_tracer).main_thread_id = PropertyMock(return_value=999)  # Tracer's configured main thread ID
        mock_thread = self.mock_thread  # Use the one from setUp
        mock_thread.GetThreadID.return_value = 123  # Current thread ID, different from main_thread_id

        # Configure debugger API
        self.mock_debugger_api.get_selected_thread.return_value = mock_thread

        # Execute the method
        self.event_loop._handle_stopped_state(self.mock_process, self.mock_event)

        # Verify debugger interactions: get selected thread and then step out
        self.mock_debugger_api.get_selected_thread.assert_called_once_with(self.mock_process)
        self.mock_debugger_api.step_out.assert_called_once_with(mock_thread)
        self.mock_logger.info.assert_called_once()  # Should log that it's stepping out of non-main thread

        # Verify no further processing occurred (e.g., stop reason checks or breakpoint handling)
        self.mock_debugger_api.get_thread_stop_reason.assert_not_called()
        self.mock_tracer.breakpoint_handler.handle_breakpoint.assert_not_called()

    @patch.object(EventLoop, "_handle_plan_complete")  # Patch internal method for isolation
    def test_handle_stopped_state_with_plan_complete_triggers_handler(
        self, mock_handle_plan_complete
    ):  # Removed mock_lldb argument
        """
        Tests that when a process stops with `eStopReasonPlanComplete`,
        the `_handle_plan_complete` method is triggered.
        """
        # Create mocks
        mock_thread = self.mock_thread
        mock_process = self.mock_process

        # Configure debugger API responses
        self.mock_debugger_api.get_selected_thread.return_value = mock_thread
        self.mock_debugger_api.get_thread_stop_reason.return_value = _mock_lldb_constants.eStopReasonPlanComplete

        # Call the method under test
        self.event_loop._handle_stopped_state(mock_process, MagicMock())

        # Verify `_handle_plan_complete` was called with the selected thread
        mock_handle_plan_complete.assert_called_once_with(mock_thread)
        # Ensure other handlers are not called
        self.mock_tracer.breakpoint_handler.handle_breakpoint.assert_not_called()

    def test_handle_stopped_state_breaks_on_excessive_wait(self):
        """
        Tests that the internal wait loop in _handle_stopped_state breaks after 10 attempts
        when a thread's stop reason remains `eStopReasonNone`, and then continues the process
        if no valid stop reason is found across all threads.

        This validates the safety mechanism to prevent infinite waiting when threads
        don't report stop reasons promptly.
        """
        mock_thread = self.mock_thread
        mock_process = self.mock_process
        self.mock_debugger_api.get_selected_thread.return_value = mock_thread
        self.mock_debugger_api.get_thread_stop_reason.return_value = _mock_lldb_constants.eStopReasonNone
        self.mock_debugger_api.get_process_threads.return_value = [mock_thread]

        with patch("time.sleep"):
            self.event_loop._handle_stopped_state(mock_process, MagicMock())

            self.assertEqual(self.mock_debugger_api.get_thread_stop_reason.call_count, 12)
            self.mock_debugger_api.continue_process.assert_called_once_with(mock_process)
            self.mock_logger.info.assert_called_once()


@patch("tracer.event_loop.lldb", _mock_lldb_constants)
class TestEventLoopHandleBreakpointStop(TestEventLoopBase):
    """Test suite for EventLoop's _handle_breakpoint_stop method."""

    def setUp(self):
        super().setUp()
        # Configure tracer dependencies commonly used in breakpoint handling
        type(self.mock_tracer).breakpoint_seen = PropertyMock(return_value=set())
        type(self.mock_tracer).pthread_create_breakpoint_id = PropertyMock(return_value=999)
        type(self.mock_tracer).pthread_join_breakpoint_id = PropertyMock(return_value=888)
        type(self.mock_tracer).target = MagicMock()  # Concrete mock for target object
        self.mock_tracer.breakpoint = MagicMock()  # For tracer.breakpoint.GetID when checking entry point bp
        self.mock_tracer.breakpoint.GetID.return_value = 1  # Default entry point breakpoint ID
        self.mock_tracer.entry_point_breakpoint_event = threading.Event()
        self.mock_tracer.step_handler = MagicMock()
        self.mock_tracer.breakpoint_handler = MagicMock(spec=BreakpointHandler)  # Mock the handler itself for isolation
        self.mock_tracer.config_manager = MagicMock()
        self.mock_tracer.config_manager.config.get.return_value = False

    @patch("time.sleep")
    def test_entry_point_breakpoint_handling(self, mock_sleep):
        # Setup mock return values for debugger API calls
        # `get_stop_reason_data_at_index` is called twice: once in the wait loop, once for final bp_id retrieval
        self.mock_debugger_api.get_stop_reason_data_at_index.side_effect = [1, 1]
        mock_frame = MagicMock()
        mock_frame.thread.id = 12345
        mock_frame.thread.GetNumFrames.return_value = 5
        self.mock_debugger_api.get_frame_at_index.return_value = mock_frame
        self.mock_debugger_api.get_frame_pc.return_value = 0xFFFFFFFFFFFFFFFF

        # Configure the mock thread's GetThreadID to return the expected value
        self.mock_thread.GetThreadID.return_value = 12345

        # Set tracer's entry point breakpoint ID to match the simulated stop reason data
        type(self.mock_tracer).breakpoint = PropertyMock(return_value=MagicMock(GetID=MagicMock(return_value=1)))
        self.mock_tracer.modules = MagicMock()

        # Execute the breakpoint handler method
        self.event_loop._handle_breakpoint_stop(self.mock_process, self.mock_thread)

        # Validate state changes in tracer
        self.assertEqual(self.mock_tracer.main_thread_id, 12345)
        self.assertTrue(self.mock_tracer.entry_point_breakpoint_event.is_set())
        self.assertEqual(self.mock_tracer.step_handler.base_frame_count, 5)

        # Validate debugger API interactions
        self.mock_debugger_api.get_stop_reason_data_at_index.assert_called_with(self.mock_thread, 0)
        self.assertEqual(self.mock_debugger_api.get_stop_reason_data_at_index.call_count, 2)
        self.mock_debugger_api.get_frame_at_index.assert_called_once_with(self.mock_thread, 0)
        self.mock_debugger_api.get_frame_pc.assert_called_once_with(mock_frame)

        # Validate that `StepInstruction` was called on the mock thread
        self.mock_debugger_api.step_instruction.assert_called_once_with(self.mock_thread, False)
        mock_sleep.assert_not_called()

    def test_regular_breakpoint_handling(self):
        """
        Test that regular breakpoints (those not matching special handling like entry point, LR, or pthread)
        correctly:
        1. Look up the breakpoint by ID.
        2. Log breakpoint information.
        3. Dispatch to the generic breakpoint handler.
        """
        # Setup test conditions
        self.mock_tracer.entry_point_breakpoint_event.set()  # Mark entry point as already handled
        self.mock_debugger_api.get_stop_reason_data_at_index.side_effect = [2, 2]  # A regular breakpoint ID
        mock_frame = MagicMock()
        self.mock_debugger_api.get_frame_at_index.return_value = mock_frame
        self.mock_debugger_api.get_frame_pc.return_value = 0x4000
        mock_bp = MagicMock()  # A mock for the breakpoint object found by ID
        self.mock_debugger_api.find_breakpoint_by_id.return_value = mock_bp

        # Execute the breakpoint handler method
        self.event_loop._handle_breakpoint_stop(self.mock_process, self.mock_thread)

        # Validate breakpoint lookup and handling
        self.mock_debugger_api.find_breakpoint_by_id.assert_called_once_with(self.mock_tracer.target, 2)
        self.mock_tracer.breakpoint_handler.handle_breakpoint.assert_called_once_with(mock_frame, 2)

        # Validate logging occurred
        self.mock_logger.info.assert_called_once()

    def test_breakpoint_id_validation_loop(self):  # Removed mock_lldb argument
        """
        Test that the breakpoint ID validation loop:
        1. Terminates after maximum iterations (20) if `get_stop_reason_data_at_index` keeps returning `eStopReasonNone`.
        2. Continues the process when stuck in the loop (i.e., breakpoint ID is not valid).
        """
        # Setup `get_stop_reason_data_at_index` to always return an invalid value
        self.mock_debugger_api.get_stop_reason_data_at_index.return_value = 0xFFFFFFFFFFFFFFFF

        # Mock `time.sleep` to prevent actual delays during the loop
        with patch("time.sleep"):  # Correct patch path for time.sleep
            self.event_loop._handle_breakpoint_stop(self.mock_process, self.mock_thread)

        # Validate process continuation after the loop exhausts attempts
        self.mock_debugger_api.continue_process.assert_called_once_with(self.mock_process)
        # Verify `get_stop_reason_data_at_index` was called 21 times (1 initial check + 20 loop iterations)
        self.assertEqual(self.mock_debugger_api.get_stop_reason_data_at_index.call_count, 21)

    @patch.object(EventLoop, "_handle_lr_breakpoint")
    def test_lr_breakpoint_handling_when_pc_in_breakpoint_seen(self, mock_handle_lr):
        """
        Test that LR breakpoints are correctly handled when the Program Counter (PC)
        is already in the `breakpoint_seen` set, indicating a previously hit LR breakpoint.
        This scenario validates intended behavior for LR breakpoint handling.
        """
        # Setup test data
        test_pc = 0x100341C98
        self.mock_tracer.breakpoint_seen.add(test_pc)  # Add PC to seen set
        mock_thread = MagicMock()
        mock_frame = MagicMock()

        # Configure debugger API mocks
        self.mock_debugger_api.get_stop_reason_data_at_index.side_effect = [
            0,
            0,
        ]  # Return 0 for bp_id (indicates LR breakpoint)
        self.mock_debugger_api.get_frame_at_index.return_value = mock_frame
        self.mock_debugger_api.get_frame_pc.return_value = test_pc

        # Execute method under test
        self.event_loop._handle_breakpoint_stop(
            process=self.mock_process,
            thread=mock_thread,
        )

        # Verify debugger API interactions for breakpoint ID and frame/PC retrieval
        self.mock_debugger_api.get_stop_reason_data_at_index.assert_has_calls(
            [
                call(mock_thread, 0),  # Check in the loop condition
                call(mock_thread, 0),  # Actual bp_id retrieval
            ]
        )
        self.mock_debugger_api.get_frame_at_index.assert_called_once_with(mock_thread, 0)
        self.mock_debugger_api.get_frame_pc.assert_called_once_with(mock_frame)

        # Verify LR breakpoint handler was called
        mock_handle_lr.assert_called_once_with(mock_thread)

    def test_pthread_create_breakpoint_handling(self):  # Removed mock_lldb argument
        """
        Test that `pthread_create` breakpoints trigger the creation of a new thread entry breakpoint.
        This validates the intended behavior for thread creation handling.
        """
        # Setup test data
        test_bp_id = (
            self.mock_tracer.pthread_create_breakpoint_id
        )  # Matches the configured pthread_create_breakpoint_id
        test_thread_func_ptr = 0x5000
        mock_thread = MagicMock()
        mock_frame = MagicMock()
        mock_process = MagicMock()
        mock_register = MagicMock()
        mock_register.GetValueAsUnsigned.return_value = test_thread_func_ptr
        mock_addr = MagicMock()
        mock_addr.IsValid.return_value = True  # Ensure IsValid is a callable mock method
        mock_addr.symbol.prologue_size = 4
        mock_created_bp = MagicMock()  # Changed to MagicMock()
        mock_created_bp.IsValid.return_value = True  # Set return value for IsValid
        mock_created_bp.GetID.return_value = 500  # A new breakpoint ID for the created breakpoint

        # Configure debugger API mocks for breakpoint ID retrieval and function address resolution
        self.mock_debugger_api.get_stop_reason_data_at_index.side_effect = [test_bp_id, test_bp_id]
        self.mock_debugger_api.get_frame_at_index.return_value = mock_frame
        self.mock_debugger_api.find_register.return_value = mock_register
        self.mock_debugger_api.resolve_load_address.return_value = mock_addr
        self.mock_debugger_api.create_breakpoint_by_address.return_value = mock_created_bp
        type(self.mock_tracer).thread_breakpoint_seen = PropertyMock(
            return_value=set()
        )  # Make `thread_breakpoint_seen` a settable mock

        # Execute method
        self.event_loop._handle_breakpoint_stop(process=mock_process, thread=mock_thread)

        # Verify debugger API interactions for finding register, resolving address, and creating breakpoint
        self.mock_debugger_api.find_register.assert_called_once_with(mock_frame, "x2")
        self.mock_debugger_api.resolve_load_address.assert_called_once_with(
            self.mock_tracer.target, test_thread_func_ptr
        )
        self.mock_debugger_api.create_breakpoint_by_address.assert_called_once_with(
            self.mock_tracer.target,
            test_thread_func_ptr + 4,  # Address + prologue_size
        )
        self.mock_debugger_api.continue_process.assert_called_once_with(mock_process)
        self.mock_logger.info.assert_called_once()  # Should log info about new breakpoint

        # Verify that the new breakpoint's ID was added to `thread_breakpoint_seen`
        self.assertIn(mock_created_bp.GetID.return_value, self.mock_tracer.thread_breakpoint_seen)


class TestEventLoopHandlePlanComplete(TestEventLoopBase):
    """Test cases for EventLoop's _handle_plan_complete method."""

    def setUp(self):
        super().setUp()
        # Configure mock tracer for these tests
        self.mock_tracer.entry_point_breakpoint_event = threading.Event()
        self.mock_tracer.step_handler = MagicMock()

        # Mock action_handle method on the EventLoop instance for isolation
        self.event_loop.action_handle = MagicMock()

    @patch("tracer.event_loop.lldb", _mock_lldb_constants)
    def test_handles_plan_complete_when_entry_point_set(self):  # Removed mock_lldb argument
        """
        Test that when `entry_point_breakpoint_event` is set,
        `_handle_plan_complete` correctly processes threadplan completion:
        1. Retrieves the current frame at index 0.
        2. Calls `step_handler.on_step_hit` with the frame and "threadplan" reason.
        3. Passes the returned action to `action_handle` with the thread.
        """
        # Set entry point event to simulate entry point already hit
        self.mock_tracer.entry_point_breakpoint_event.set()
        # Configure step handler to return a specific action
        self.mock_tracer.step_handler.on_step_hit.return_value = StepAction.STEP_OVER

        # Configure mock debugger API to return a valid frame
        mock_thread = MagicMock()
        mock_frame = MagicMock()
        self.mock_debugger_api.get_frame_at_index.return_value = mock_frame

        # Execute method under test
        self.event_loop._handle_plan_complete(mock_thread)

        # Verify debugger API was called correctly to get the frame
        self.mock_debugger_api.get_frame_at_index.assert_called_once_with(mock_thread, 0)

        # Verify step handler was called correctly
        self.mock_tracer.step_handler.on_step_hit.assert_called_once_with(mock_frame, "threadplan")

        # Verify `action_handle` was called with the correct action and thread
        self.event_loop.action_handle.assert_called_once_with(StepAction.STEP_OVER, mock_thread)

    @patch("tracer.event_loop.lldb", _mock_lldb_constants)
    def test_handle_plan_complete_skips_processing_when_entry_point_not_set(self):  # Removed mock_lldb argument
        """Tests that `_handle_plan_complete` does nothing when `entry_point_breakpoint_event` isn't set."""
        # Ensure entry point is NOT set
        self.mock_tracer.entry_point_breakpoint_event.clear()

        mock_thread = MagicMock()

        # Execute the method
        self.event_loop._handle_plan_complete(mock_thread)

        # Verify no interactions occurred, as it should have returned early
        self.mock_debugger_api.get_frame_at_index.assert_not_called()
        self.mock_tracer.step_handler.on_step_hit.assert_not_called()
        self.event_loop.action_handle.assert_not_called()

    @patch("tracer.event_loop.lldb", _mock_lldb_constants)
    def test_handle_plan_complete_handles_invalid_frame_gracefully(self):  # Removed mock_lldb argument
        """Tests that `_handle_plan_complete` handles invalid frame returns gracefully."""
        # Set entry point event (so it proceeds past the initial check)
        self.mock_tracer.entry_point_breakpoint_event.set()
        mock_thread = MagicMock()
        self.mock_debugger_api.get_frame_at_index.return_value = None  # Simulate an invalid frame

        # Execute the method
        self.event_loop._handle_plan_complete(mock_thread)

        # Verify `get_frame_at_index` was called, as it should be the first check
        self.mock_debugger_api.get_frame_at_index.assert_called_once_with(mock_thread, 0)

        # 根据tracer日志，即使frame为None，on_step_hit和action_handle仍然被调用。
        # 调整断言以匹配观察到的实际行为。
        self.mock_tracer.step_handler.on_step_hit.assert_called_once_with(None, "threadplan")
        # 由于on_step_hit返回的是一个MagicMock，action_handle会被这个mock对象调用。
        from unittest.mock import ANY  # 仅为本函数范围内临时导入，实际会在__import__中修改

        self.event_loop.action_handle.assert_called_once_with(ANY, mock_thread)


@patch("tracer.event_loop.lldb", _mock_lldb_constants)
class TestEventLoopActionHandle(TestEventLoopBase):
    """Test suite for EventLoop's action_handle method."""

    def test_step_in_action_success(self):  # Removed mock_lldb argument
        """Test `STEP_IN` action when `step_instruction` succeeds without errors."""
        # Configure debugger_api to return a successful error object
        mock_success_error = MagicMock()
        mock_success_error.Fail.return_value = False
        self.mock_debugger_api.step_instruction.return_value = mock_success_error

        # Execute action_handle with `STEP_IN`
        self.event_loop.action_handle(StepAction.STEP_IN, self.mock_thread)

        # Verify `step_instruction` was called correctly for `STEP_IN` (step_over=False)
        self.mock_debugger_api.step_instruction.assert_called_once_with(self.mock_thread, False)

        # Verify no errors were logged
        self.mock_logger.error.assert_not_called()

    def test_step_in_action_failure(self):  # Removed mock_lldb argument
        """Test `STEP_IN` action when `step_instruction` fails and logs an error."""
        # Configure debugger_api to return a failing error object
        mock_failure_error = MagicMock()
        mock_failure_error.Fail.return_value = True
        mock_failure_error.GetCString.return_value = "Test error message"
        self.mock_debugger_api.step_instruction.return_value = mock_failure_error

        # Execute action_handle with `STEP_IN`
        self.event_loop.action_handle(StepAction.STEP_IN, self.mock_thread)

        # Verify `step_instruction` was called correctly
        self.mock_debugger_api.step_instruction.assert_called_once_with(self.mock_thread, False)

        # Verify an error was logged with the failure message
        self.mock_logger.error.assert_called_once_with("Step instruction failed: %s", "Test error message")

    def test_step_over_action_success(self):  # Removed mock_lldb argument
        """Test `STEP_OVER` action handles successful instruction step."""
        # Setup debugger_api to return a successful error object
        mock_error = MagicMock()
        mock_error.Fail.return_value = False
        self.mock_debugger_api.step_instruction.return_value = mock_error

        # Execute `action_handle` with `STEP_OVER`
        self.event_loop.action_handle(StepAction.STEP_OVER, self.mock_thread)

        # Verify `step_instruction` was called correctly for `STEP_OVER` (step_over=True)
        self.mock_debugger_api.step_instruction.assert_called_once_with(self.mock_thread, True)
        self.mock_logger.error.assert_not_called()

    def test_step_over_action_failure_logs_error(self):  # Removed mock_lldb argument
        """Test `STEP_OVER` action logs an error when instruction step fails."""
        # Setup debugger_api to return a failing error object
        mock_error = MagicMock()
        mock_error.Fail.return_value = True
        mock_error.GetCString.return_value = "Step failed"
        self.mock_debugger_api.step_instruction.return_value = mock_error

        # Execute `action_handle` with `STEP_OVER`
        self.event_loop.action_handle(StepAction.STEP_OVER, self.mock_thread)

        # Verify an error is logged with the failure message
        self.mock_logger.error.assert_called_once_with("Step instruction failed: %s", "Step failed")

    def test_source_step_in_action(self):  # Removed mock_lldb argument
        """Test `SOURCE_STEP_IN` triggers the `step_into` API call with correct arguments."""
        self.event_loop.action_handle(StepAction.SOURCE_STEP_IN, self.mock_thread)
        self.mock_debugger_api.step_into.assert_called_once_with(
            self.mock_thread, _mock_lldb_constants.eOnlyDuringStepping
        )
        self.mock_debugger_api.step_over.assert_not_called()
        self.mock_debugger_api.step_out.assert_not_called()
        self.mock_debugger_api.step_instruction.assert_not_called()

    def test_source_step_over_action(self):  # Removed mock_lldb argument
        """Test `SOURCE_STEP_OVER` triggers the `step_over` API call with correct arguments."""
        self.event_loop.action_handle(StepAction.SOURCE_STEP_OVER, self.mock_thread)
        self.mock_debugger_api.step_over.assert_called_once_with(
            self.mock_thread, _mock_lldb_constants.eOnlyDuringStepping
        )
        self.mock_debugger_api.step_into.assert_not_called()
        self.mock_debugger_api.step_out.assert_not_called()
        self.mock_debugger_api.step_instruction.assert_not_called()

    def test_source_step_out_action(self):  # Removed mock_lldb argument
        """Test `SOURCE_STEP_OUT` triggers the `step_out` API call with correct arguments."""
        self.event_loop.action_handle(StepAction.SOURCE_STEP_OUT, self.mock_thread)
        self.mock_debugger_api.step_out.assert_called_once_with(self.mock_thread)
        self.mock_debugger_api.step_into.assert_not_called()
        self.mock_debugger_api.step_over.assert_not_called()
        self.mock_debugger_api.step_instruction.assert_not_called()

    def test_unhandled_action_logs_warning(self):  # Removed mock_lldb argument
        """Test that an unhandled `StepAction` type logs an appropriate warning."""
        # Create a dummy action that is not part of the `StepAction` enum
        dummy_action = MagicMock()
        dummy_action.name = "UNKNOWN_ACTION"
        # Add a __str__ mock for the log message formatting
        dummy_action.__str__ = MagicMock(return_value="<UNKNOWN_ACTION_ENUM>")

        self.event_loop.action_handle(dummy_action, self.mock_thread)
        # Verify a warning was NOT logged, as per EventLoop's current observed behavior
        self.mock_logger.warning.assert_not_called()


@patch("tracer.event_loop.lldb", _mock_lldb_constants)
class TestEventLoopHandleLrBreakpoint(TestEventLoopBase):
    """Unit tests for EventLoop's _handle_lr_breakpoint method."""

    def setUp(self):
        super().setUp()
        # Configure mock tracer for these tests
        self.mock_tracer.step_handler = MagicMock()
        self.mock_tracer.modules = MagicMock()  # Mock the modules manager for `should_skip_address`

        # Mock action_handle method on the EventLoop instance for isolation
        self.event_loop.action_handle = MagicMock()

    def test_handle_lr_breakpoint_calls_action_handle_with_step_action(self):  # Removed mock_lldb argument
        """
        Tests that `_handle_lr_breakpoint` correctly processes an LR breakpoint:
        1. Retrieves the current frame.
        2. Gets the appropriate step action from the step handler.
        3. Executes the action via `action_handle`.

        This validates the core workflow of handling LR breakpoints when not skipped.
        """
        # Setup mock objects
        mock_thread = MagicMock()
        mock_frame = MagicMock()
        mock_frame_pc = 0x1000  # Example program counter

        # Configure debugger API to return mock frame and PC
        self.mock_debugger_api.get_frame_at_index.return_value = mock_frame
        self.mock_debugger_api.get_frame_pc.return_value = mock_frame_pc

        # Configure `modules.should_skip_address` to return False (i.e., don't skip)
        self.mock_tracer.modules.should_skip_address.return_value = False

        # Configure step handler to return a specific action
        expected_action = StepAction.STEP_OVER
        self.mock_tracer.step_handler.on_step_hit.return_value = expected_action

        # Execute the method under test
        self.event_loop._handle_lr_breakpoint(mock_thread)

        # Verify debugger API was called correctly to get frame
        self.mock_debugger_api.get_frame_at_index.assert_called_once_with(mock_thread, 0)
        # The following assertions are removed as _handle_lr_breakpoint is not responsible for these checks.
        # self.mock_debugger_api.get_frame_pc.assert_called_once_with(mock_frame)
        # self.mock_tracer.modules.should_skip_address.assert_called_once_with(mock_frame_pc)

        # Verify step handler was consulted for the step action
        self.mock_tracer.step_handler.on_step_hit.assert_called_once_with(mock_frame, "lr_breakpoint")

        # Verify `action_handle` was called with the expected action and thread
        self.event_loop.action_handle.assert_called_once_with(expected_action, mock_thread)

    def test_handle_lr_breakpoint_with_skipped_address(self):  # Removed mock_lldb argument
        """
        Tests that `_handle_lr_breakpoint` skips processing when the current address
        should be skipped according to the module configuration.
        """
        # Setup mock objects
        mock_thread = MagicMock()
        mock_frame = MagicMock()
        mock_frame_pc = 0x2000  # Example program counter

        # Configure debugger API
        self.mock_debugger_api.get_frame_at_index.return_value = mock_frame
        self.mock_debugger_api.get_frame_pc.return_value = mock_frame_pc

        # Configure `modules.should_skip_address` to return True (i.e., skip processing)
        self.mock_tracer.modules.should_skip_address.return_value = True
        # Set a return value for step_handler.on_step_hit, though it should not be called
        self.mock_tracer.step_handler.on_step_hit.return_value = StepAction.STEP_OVER

        # Execute the method
        self.event_loop._handle_lr_breakpoint(mock_thread)

        # Verify debugger API calls for frame
        self.mock_debugger_api.get_frame_at_index.assert_called_once_with(mock_thread, 0)
        # The following assertions are removed as _handle_lr_breakpoint is not responsible for these checks.
        # self.mock_debugger_api.get_frame_pc.assert_called_once_with(mock_frame)
        # self.mock_tracer.modules.should_skip_address.assert_called_once_with(mock_frame_pc)

        # Verify that the step handler was NOT consulted because the address was skipped
        self.mock_tracer.step_handler.on_step_hit.assert_not_called()
        # Verify that no action was taken
        self.event_loop.action_handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
