import sys
import unittest
from enum import Enum
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

project_root = Path(__file__).resolve().parent.parent / "debugger/lldb"
sys.path.insert(0, str(project_root))

from op_parser import OperandType
from tracer.config import ConfigManager
from tracer.core import Tracer
from tracer.step_handler import StepAction, StepHandler, SymbolHookMode


# Define custom exception for testing purposes, if used across multiple tests
class ImplicitExit(Exception):
    """Mock exception to simulate frame exit during instruction caching"""


class BaseStepHandlerTest(unittest.TestCase):
    """
    Base class for StepHandler tests, providing common setup for
    mocking Tracer and StepHandler's internal dependencies.
    """

    def setUp(self):
        """
        Set up common mocks for Tracer and StepHandler instance for each test.
        Initializes a mock Tracer and StepHandler, and clears StepHandler's caches.
        """
        # Common mocks for Tracer and its dependencies
        self.mock_tracer = MagicMock(spec=Tracer)
        self.mock_tracer.logger = MagicMock()
        self.mock_tracer.config_manager = MagicMock(spec=ConfigManager)
        self.mock_tracer.target = MagicMock()
        self.mock_tracer.modules = MagicMock()
        self.mock_tracer.source_ranges = MagicMock()
        self.mock_tracer.run_cmd = MagicMock()  # For StepHandler __init__

        # Initialize StepHandler, which will use the mocked tracer
        # Default config returns for StepHandler's init
        self.mock_tracer.config_manager.get_expression_hooks.return_value = []
        self.mock_tracer.config_manager.get_log_mode.return_value = "instruction"  # Default for many tests
        self.mock_tracer.config_manager.get_step_action.return_value = {}
        self.mock_tracer.config_manager.get_source_search_paths.return_value = []
        self.mock_tracer.config_manager.get_source_base_dir.return_value = ""

        # Patch internal StepHandler dependencies for consistent initialization across tests
        # These are usually initialized by the StepHandler constructor, so we need to mock them
        # if the constructor implicitly relies on them being mockable (e.g., if they import lldb)
        self.patcher_source_handler = patch("tracer.step_handler.SourceHandler")
        self.patcher_debug_info_handler = patch("tracer.step_handler.DebugInfoHandler")
        self.patcher_parser_loader = patch("tracer.step_handler.ParserLoader")
        self.patcher_expression_extractor = patch("tracer.step_handler.ExpressionExtractor")

        self.mock_source_handler_cls = self.patcher_source_handler.start()
        self.mock_debug_info_handler_cls = self.patcher_debug_info_handler.start()
        self.mock_parser_loader_cls = self.patcher_parser_loader.start()
        self.mock_expression_extractor_cls = self.patcher_expression_extractor.start()

        # Store the mocks created by StepHandler's __init__ for later use in tests if needed
        self.mock_source_handler_cls.return_value = MagicMock()
        self.mock_debug_info_handler_cls.return_value = MagicMock()
        self.mock_parser_loader_cls.return_value = MagicMock()
        self.mock_expression_extractor_cls.return_value = MagicMock()

        self.step_handler = StepHandler(tracer=self.mock_tracer, bind_thread_id=None)

        # Assign these explicitly to the step_handler mock, as the real constructor would
        self.step_handler.source_handler = self.mock_source_handler_cls.return_value
        self.step_handler.debug_info_handler = self.mock_debug_info_handler_cls.return_value
        self.step_handler.parser_loader = self.mock_parser_loader_cls.return_value
        self.step_handler.expression_extractor = self.mock_expression_extractor_cls.return_value

        # Clear caches for a clean state before each test
        self.step_handler.instruction_info_cache = {}
        self.step_handler.line_cache = {}
        self.step_handler.function_start_addrs = set()
        self.step_handler.function_range_cache = {}
        self.step_handler.addr_to_symbol_cache = {}
        self.step_handler.expression_cache = {}
        self.step_handler.branch_trace_info = {}
        self.step_handler.current_frame_branch_counter = {}
        self.step_handler.current_frame_line_counter = {}
        self.step_handler.before_get_out = False  # Reset flag

        # Reset tracer mocks too
        # The following line was the cause of the test failure.
        # It reset the call count of mock_tracer.config_manager after StepHandler's init
        # had already called get_expression_hooks. Removing it allows the assertion
        # in the test method to correctly verify the call.
        # self.mock_tracer.config_manager.reset_mock()
        self.mock_tracer.modules.reset_mock()
        self.mock_tracer.source_ranges.reset_mock()
        self.mock_source_handler_cls.reset_mock()
        self.mock_debug_info_handler_cls.reset_mock()
        self.mock_parser_loader_cls.reset_mock()
        self.mock_expression_extractor_cls.reset_mock()

    def tearDown(self):
        """Stop all patches started in setUp."""
        self.patcher_source_handler.stop()
        self.patcher_debug_info_handler.stop()
        self.patcher_parser_loader.stop()
        self.patcher_expression_extractor.stop()


class TestStepHandlerCore(BaseStepHandlerTest):
    """
    Test suite for core StepHandler initialization, configuration,
    and fundamental helper functions like breakpoint management.
    """

    def test_init_sets_correct_attributes_and_configurations(self):
        """
        Tests that StepHandler correctly initializes attributes and configuration
        settings during object creation. Verifies:
        - Tracer references and logger are set properly
        - Configuration values are retrieved from config manager
        - Helper objects are initialized correctly
        - Expected LLDB commands are executed
        """
        # Fix: Import 'call' from unittest.mock for assert_has_calls usage.
        # This is a local import to adhere to the "overwrite whole symbol" output mode.
        from unittest.mock import call

        # Mocks are already set up in self.setUp
        handler = self.step_handler
        mock_tracer = self.mock_tracer

        # Verify tracer and logger references
        self.assertEqual(handler.tracer, mock_tracer)
        self.assertEqual(handler.logger, mock_tracer.logger)

        # Verify helper objects initialized (these were mocked in setUp)
        # We check the attributes of the handler, which were populated by the mocks in setUp
        self.assertIsInstance(handler.source_handler, MagicMock)
        self.assertIsInstance(handler.debug_info_handler, MagicMock)
        self.assertIsInstance(handler.parser_loader, MagicMock)
        self.assertIsInstance(handler.expression_extractor, MagicMock)

        # Verify config values
        self.assertEqual(handler.expression_hooks, [])
        self.assertEqual(handler.log_mode, "instruction")
        self.assertEqual(handler.step_action, {})
        self.assertTrue(handler.insutruction_mode)

        # Verify step action constants
        self.assertEqual(handler.step_in, StepAction.STEP_IN)
        self.assertEqual(handler.step_over, StepAction.STEP_OVER)
        self.assertEqual(handler.step_out, StepAction.SOURCE_STEP_OUT)

        # Verify collections initialized empty
        self.assertEqual(handler.instruction_info_cache, {})
        self.assertEqual(handler.line_cache, {})
        self.assertEqual(handler.function_start_addrs, set())
        self.assertEqual(handler.function_range_cache, {})
        self.assertEqual(handler.addr_to_symbol_cache, {})
        self.assertEqual(handler.expression_cache, {})
        self.assertEqual(handler.branch_trace_info, {})
        self.assertEqual(handler.current_frame_branch_counter, {})
        self.assertEqual(handler.current_frame_line_counter, {})

        # Verify thread binding
        self.assertIsNone(handler.bind_thread_id)
        self.assertFalse(handler.before_get_out)

        # Verify LLDB commands executed
        expected_calls = [
            call("script import tracer"),
            call("script globals()['plt_step_over_callback'] = tracer.step_handler.plt_step_over_callback"),
        ]
        mock_tracer.run_cmd.assert_has_calls(expected_calls)
        mock_tracer.config_manager.get_expression_hooks.assert_called_once()
        mock_tracer.config_manager.get_log_mode.assert_called_once()
        mock_tracer.config_manager.get_step_action.assert_called_once()

    @patch("tracer.step_handler.SourceHandler")
    @patch("tracer.step_handler.DebugInfoHandler")
    def test_initialization_with_instruction_log_mode(self, mock_debug_info_handler, mock_source_handler):
        """Test StepHandler initialization when log mode is 'instruction'.

        Verifies that:
        - Handlers are created with the tracer
        - Log mode and step actions are configured correctly
        - Instruction-specific step actions are set
        - Caches are initialized as empty
        - The run_cmd commands are executed
        """
        # Configure mock returns
        self.mock_tracer.config_manager.get_log_mode.return_value = "instruction"
        self.mock_tracer.config_manager.get_step_action.return_value = {"action": "step_over"}

        # Re-initialize StepHandler to apply new config mocks
        # Patching during init to avoid self.setUp's patches interfering if they don't apply.
        with patch("tracer.step_handler.ParserLoader"), patch("tracer.step_handler.ExpressionExtractor"):
            step_handler = StepHandler(self.mock_tracer)

        # Verify handler initialization
        mock_source_handler.assert_called_once_with(self.mock_tracer)
        mock_debug_info_handler.assert_called_once_with(self.mock_tracer)

        # Verify configuration
        self.assertEqual(step_handler.log_mode, "instruction")
        self.assertEqual(step_handler.step_action, {"action": "step_over"})
        self.assertTrue(step_handler.insutruction_mode)

        # Verify step actions
        self.assertEqual(step_handler.step_in, StepAction.STEP_IN)
        self.assertEqual(step_handler.step_over, StepAction.STEP_OVER)
        self.assertEqual(step_handler.step_out, StepAction.SOURCE_STEP_OUT)

        # Verify cache initialization (from general setUp, so should be empty)
        self.assertEqual(step_handler.instruction_info_cache, {})
        self.assertEqual(step_handler.line_cache, {})
        self.assertEqual(step_handler.function_start_addrs, set())
        self.assertEqual(step_handler.function_range_cache, {})
        self.assertEqual(step_handler.addr_to_symbol_cache, {})
        self.assertEqual(step_handler.expression_cache, {})

        # Verify commands executed (reset in setUp, so these are only for this init)
        expected_calls = [
            call("script import tracer"),
            call("script globals()['plt_step_over_callback'] = tracer.step_handler.plt_step_over_callback"),
        ]
        self.mock_tracer.run_cmd.assert_has_calls(expected_calls)

    @patch("tracer.step_handler.SourceHandler")
    @patch("tracer.step_handler.DebugInfoHandler")
    def test_initialization_with_source_log_mode(self, mock_debug_info_handler, mock_source_handler):
        """Test StepHandler initialization when log mode is 'source'.

        Verifies that:
        - Source-specific step actions are configured correctly
        - Instruction mode flag is set to False
        - Bind thread ID is set when provided
        """
        # Configure mock returns
        self.mock_tracer.config_manager.get_log_mode.return_value = "source"
        self.mock_tracer.config_manager.get_step_action.return_value = {}

        # Re-initialize StepHandler to apply new config mocks
        with patch("tracer.step_handler.ParserLoader"), patch("tracer.step_handler.ExpressionExtractor"):
            step_handler = StepHandler(self.mock_tracer, bind_thread_id=123)

        # Verify configuration
        self.assertEqual(step_handler.log_mode, "source")
        self.assertFalse(step_handler.insutruction_mode)
        self.assertEqual(step_handler.bind_thread_id, 123)

        # Verify step actions
        self.assertEqual(step_handler.step_in, StepAction.SOURCE_STEP_IN)
        self.assertEqual(step_handler.step_over, StepAction.SOURCE_STEP_OVER)
        self.assertEqual(step_handler.step_out, StepAction.SOURCE_STEP_OUT)  # Step out is same for source/instruction

    def test_update_lru_breakpoint_successful_creation(self):
        """Test successful breakpoint creation when LR value is new and oneshot is True.

        This test verifies that:
        1. A valid breakpoint is created at the specified address
        2. The breakpoint is configured as one-shot
        3. The LR value is added to breakpoint tracking structures
        4. The method returns True indicating success
        """
        # Setup test data
        lr_value = 4305038948
        oneshot = True

        # Configure tracer to return a valid mock breakpoint
        mock_breakpoint = MagicMock()
        mock_breakpoint.IsValid.return_value = True
        self.mock_tracer.target.BreakpointCreateByAddress.return_value = mock_breakpoint

        self.mock_tracer.breakpoint_seen = set()  # Ensure fresh cache for this test
        self.mock_tracer.breakpoint_table = {}

        # Execute the method under test
        result = self.step_handler._update_lru_breakpoint(lr_value, oneshot)

        # Assert breakpoint creation and configuration
        self.mock_tracer.target.BreakpointCreateByAddress.assert_called_once_with(lr_value)
        mock_breakpoint.SetOneShot.assert_called_once_with(oneshot)

        # Assert state updates
        self.assertIn(lr_value, self.mock_tracer.breakpoint_seen)
        self.assertEqual(self.mock_tracer.breakpoint_table[lr_value], lr_value)

        # Assert return value
        self.assertTrue(result)


class TestHelperComponentInitialization(unittest.TestCase):
    """
    Test suite for initialization and basic functionality of StepHandler's
    auxiliary components like SourceHandler, NodeProcessor, and Enums.
    These tests do not require a full StepHandler instance.
    """

    def test_source_handler_initializes_correctly(self):
        """
        Tests that SourceHandler correctly initializes with:
        1. Tracer instance reference
        2. Logger reference
        3. Source search paths from config
        4. Properly initialized cache dictionaries
        """
        # Setup mock tracer with required attributes
        mock_tracer = MagicMock()
        mock_tracer.logger = MagicMock()
        mock_config_manager = MagicMock()
        mock_config_manager.get_source_search_paths.return_value = ["/search/path1", "/search/path2"]
        mock_tracer.config_manager = mock_config_manager

        # Execute initialization
        from tracer.source_handler import SourceHandler

        handler = SourceHandler(mock_tracer)

        # Verify tracer reference
        self.assertIs(handler.tracer, mock_tracer)

        # Verify logger reference
        self.assertIs(handler.logger, mock_tracer.logger)

        # Verify source search paths
        mock_config_manager.get_source_search_paths.assert_called_once()
        self.assertEqual(handler._source_search_paths, ["/search/path1", "/search/path2"])

        # Verify cache initialization
        self.assertEqual(handler._resolved_path_cache, {})
        self.assertEqual(handler._line_entries_cache, {})
        self.assertEqual(handler._line_to_next_line_cache, {})

    def test_node_processor_init_sets_attributes_correctly(self):
        """
        Tests that NodeProcessor correctly initializes its attributes:
        - extractor reference is properly set
        - handlers dictionary contains expected keys and method references
        """
        # Setup - create mock extractor
        mock_extractor = MagicMock()
        from tracer.node_processor import NodeProcessor

        # Execute - create NodeProcessor instance
        processor = NodeProcessor(mock_extractor)

        # Verify extractor reference
        self.assertIs(processor.extractor, mock_extractor, "Extractor reference not set correctly")

        # Verify handlers dictionary structure
        expected_keys = {
            "declaration",
            "expression_statement",
            "assignment_expression",
            "for_statement",
            "for_range_loop",
            "call_expression",
            "function_declarator",
            "template_instantiation",
        }
        self.assertSetEqual(set(processor.handlers.keys()), expected_keys, "Handlers dictionary missing expected keys")

        # Verify handler methods are bound to instance
        for handler in processor.handlers.values():
            self.assertTrue(callable(handler), "Handler value should be callable")
            self.assertEqual(handler.__self__, processor, "Handler method should be bound to processor instance")

    def test_symbol_hook_mode_enum_values(self):
        """Verify SymbolHookMode enum members have correct values"""
        # Test each enum member's value
        self.assertEqual(SymbolHookMode.NONE.value, "none")
        self.assertEqual(SymbolHookMode.SYMBOL_ENTER.value, "symbol_enter")
        self.assertEqual(SymbolHookMode.SYMBOL_LEAVE.value, "symbol_leave")

    def test_symbol_hook_mode_enum_members(self):
        """Verify SymbolHookMode has correct member count and names"""
        # Test all members exist and are correctly named
        members = list(SymbolHookMode)
        self.assertEqual(len(members), 3)
        self.assertIn(SymbolHookMode.NONE, members)
        self.assertIn(SymbolHookMode.SYMBOL_ENTER, members)
        self.assertIn(SymbolHookMode.SYMBOL_LEAVE, members)

    def test_symbol_hook_mode_enum_type(self):
        """Verify SymbolHookMode is a proper Enum subclass"""
        # Test inheritance and type
        self.assertTrue(issubclass(SymbolHookMode, Enum))
        self.assertIsInstance(SymbolHookMode.NONE, SymbolHookMode)


class TestInstructionAndSourceProcessing(BaseStepHandlerTest):
    """
    Test suite for processing and caching instruction details
    and source code information within StepHandler.
    """

    @patch("tracer.step_handler.lldb")  # Patch lldb for tests that interact with its objects
    def test_cache_instruction_info_populates_cache(self, _mock_lldb):
        """
        Test that _cache_instruction_info correctly processes instructions and
        populates the instruction_info_cache with expected values.
        """
        # Create mock frame and instructions
        mock_frame = MagicMock()
        mock_symbol = MagicMock()
        mock_frame.symbol = mock_symbol

        # Create mock instruction list with 2 instructions
        mock_instruction_list = MagicMock()
        mock_symbol.GetInstructions.return_value = mock_instruction_list
        mock_symbol.GetStartAddress.return_value.GetLoadAddress.return_value = 0x1000  # Function start load address

        # Create mock instructions
        inst1 = MagicMock()
        inst2 = MagicMock()
        mock_instruction_list.__iter__.return_value = [inst1, inst2]
        mock_instruction_list.GetInstructionAtIndex.return_value = inst1  # For internal use if any

        # Setup addresses for instructions
        addr1 = MagicMock()
        addr1.GetLoadAddress.return_value = 0x1000
        addr1.GetFileAddress.return_value = 0x800
        addr1.file_addr = 0x800  # For direct attribute access if any

        addr2 = MagicMock()
        addr2.GetLoadAddress.return_value = 0x1004
        addr2.GetFileAddress.return_value = 0x804
        addr2.file_addr = 0x804

        inst1.GetAddress.return_value = addr1
        inst2.GetAddress.return_value = addr2

        # Setup instruction properties
        inst1.GetMnemonic.return_value = "mov"
        inst1.GetOperands.return_value = "x0, #0"
        inst1.size = 4

        inst2.GetMnemonic.return_value = "add"
        inst2.GetOperands.return_value = "x1, x2, x3"
        inst2.size = 4

        # Execute the method under test
        self.step_handler._cache_instruction_info(mock_frame, 0x1234)

        # Verify results
        self.assertEqual(self.step_handler.function_start_addrs, {0x1000})
        self.assertEqual(len(self.step_handler.instruction_info_cache), 2)

        # First instruction (offset = 0x1000 - 0x800 = 0x800)
        # Loaded address = 0x800 (file) + 0x800 (offset) = 0x1000
        self.assertEqual(
            self.step_handler.instruction_info_cache[0x1000],
            ("mov", "x0, #0", 4, 0),  # Offset relative to start of instruction list, which is 0 for first
        )

        # Second instruction
        # Loaded address = 0x804 (file) + 0x800 (offset) = 0x1004
        # Offset from first = 0x804 - 0x800 = 4 (file address diff)
        self.assertEqual(self.step_handler.instruction_info_cache[0x1004], ("add", "x1, x2, x3", 4, 4))

    @patch("tracer.step_handler.lldb")
    def test_cache_instruction_info_empty_instruction_list(self, _mock_lldb):
        """
        Test that _cache_instruction_info handles empty instruction lists
        without errors and leaves cache unchanged.
        """
        mock_frame = MagicMock()
        mock_symbol = MagicMock()
        mock_frame.symbol = mock_symbol

        mock_instruction_list = MagicMock()
        mock_instruction_list.__iter__.return_value = []  # Empty list
        mock_instruction_list.GetSize.return_value = 0  # Explicitly mock GetSize for empty list scenario
        mock_symbol.GetInstructions.return_value = mock_instruction_list
        mock_symbol.GetStartAddress().GetLoadAddress.return_value = 0x1234  # Dummy start address

        # Execute the method
        self.step_handler._cache_instruction_info(mock_frame, 0x1234)

        # Verify cache remains empty
        self.assertEqual(len(self.step_handler.instruction_info_cache), 0)
        self.assertEqual(len(self.step_handler.function_start_addrs), 0)

    @patch("tracer.step_handler.lldb")
    def test_cache_instruction_info_with_valid_frame(self, _mock_lldb):
        """
        Tests that _cache_instruction_info correctly caches instruction information
        for a valid frame with multiple instructions. Verifies that:
        1. function_start_addrs contains the first instruction's load address
        2. instruction_info_cache contains correct entries for each instruction
        3. Offsets are correctly calculated relative to the first instruction
        """
        # Mock frame and symbol
        frame = MagicMock()
        frame.symbol = MagicMock()
        frame.symbol.GetStartAddress().GetLoadAddress.return_value = 0x100597C58  # First inst load addr

        # Create mock instructions
        inst1 = MagicMock()
        inst1.GetAddress().GetFileAddress.return_value = 0x100001C58
        inst1.GetAddress().GetLoadAddress.return_value = 0x100597C58
        inst1.GetAddress().file_addr = 0x100001C58
        inst1.GetMnemonic.return_value = "sub"
        inst1.GetOperands.return_value = "sp, sp, #0x20"
        inst1.size = 4

        inst2 = MagicMock()
        inst2.GetAddress().GetFileAddress.return_value = 0x100001C5C
        inst2.GetAddress().GetLoadAddress.return_value = 0x100597C5C
        inst2.GetAddress().file_addr = 0x100001C5C
        inst2.GetMnemonic.return_value = "stp"
        inst2.GetOperands.return_value = "x29, x30, [sp, #0x10]"
        inst2.size = 4

        # Mock instruction list and iteration
        instruction_list = MagicMock()
        instruction_list.GetInstructionAtIndex.side_effect = [inst1, inst2]  # Simulate access by index
        instruction_list.__iter__.return_value = [inst1, inst2]
        instruction_list.GetSize.return_value = 2  # Add size for valid lists
        frame.symbol.GetInstructions.return_value = instruction_list

        # Call method under test
        self.step_handler._cache_instruction_info(frame, 0x100597C5C)

        # Verify function_start_addrs contains first instruction's load address
        self.assertIn(0x100597C58, self.step_handler.function_start_addrs)

        # Verify instruction_info_cache contains correct entries
        self.assertEqual(len(self.step_handler.instruction_info_cache), 2)

        # Verify first instruction cache entry
        inst1_info = self.step_handler.instruction_info_cache[0x100597C58]
        self.assertEqual(inst1_info[0], "sub")
        self.assertEqual(inst1_info[1], "sp, sp, #0x20")
        self.assertEqual(inst1_info[2], 4)
        self.assertEqual(inst1_info[3], 0)  # Offset should be 0 for first instruction (relative to file_addr)

        # Verify second instruction cache entry
        inst2_info = self.step_handler.instruction_info_cache[0x100597C5C]
        self.assertEqual(inst2_info[0], "stp")
        self.assertEqual(inst2_info[1], "x29, x30, [sp, #0x10]")
        self.assertEqual(inst2_info[2], 4)
        self.assertEqual(inst2_info[3], 4)  # Offset should be 4 (0x100001c5c - 0x100001c58)

    @patch("tracer.step_handler.lldb")
    def test_cache_instruction_info_with_invalid_frame(self, _mock_lldb):
        """
        Tests that _cache_instruction_info handles invalid frames correctly by:
        1. Not adding anything to function_start_addrs
        2. Leaving instruction_info_cache empty
        """
        # Create frame with invalid symbol
        frame = MagicMock()
        frame.symbol = None  # Invalid symbol

        # Call method under test
        self.step_handler._cache_instruction_info(frame, 0x100597C5C)

        # Verify no changes to caches
        self.assertEqual(len(self.step_handler.function_start_addrs), 0)
        self.assertEqual(len(self.step_handler.instruction_info_cache), 0)

    @patch("tracer.step_handler.lldb")
    def test_cache_instruction_info_caches_instructions_correctly(self, _mock_lldb):
        """
        Tests that _cache_instruction_info correctly processes instructions and caches
        their mnemonic, operands, size, and offset relative to the function start.

        This test verifies:
        1. Function start address is added to function_start_addrs
        2. Correct offset is calculated between loaded and file addresses
        3. Each instruction's info is cached with the proper loaded address
        4. Cache contains the expected instruction information
        """
        # Create mock frame and symbol
        mock_frame = MagicMock()
        mock_symbol = MagicMock()
        mock_frame.symbol = mock_symbol

        # Mock symbol's start address
        mock_start_addr = MagicMock()
        mock_symbol.GetStartAddress.return_value = mock_start_addr
        mock_start_addr.GetLoadAddress.return_value = 0x1000  # Loaded address

        # Create mock instructions
        mock_instructions = MagicMock()
        mock_symbol.GetInstructions.return_value = mock_instructions
        mock_instructions.GetSize.return_value = 3  # Add size for valid lists

        # Create three mock instructions
        mock_inst1, mock_inst2, mock_inst3 = MagicMock(), MagicMock(), MagicMock()
        mock_instructions.__iter__.return_value = [mock_inst1, mock_inst2, mock_inst3]
        mock_instructions.GetInstructionAtIndex.side_effect = [mock_inst1, mock_inst2, mock_inst3]  # For indexing

        # Setup instruction 1
        mock_addr1 = MagicMock()
        mock_inst1.GetAddress.return_value = mock_addr1
        mock_addr1.GetLoadAddress.return_value = 0x1000  # Matches function start
        mock_addr1.GetFileAddress.return_value = 0x800  # File address
        mock_addr1.file_addr = 0x800  # File address attribute
        mock_inst1.GetMnemonic.return_value = "adrp"
        mock_inst1.GetOperands.return_value = "x16, 2"
        mock_inst1.size = 4

        # Setup instruction 2
        mock_addr2 = MagicMock()
        mock_inst2.GetAddress.return_value = mock_addr2
        mock_addr2.GetLoadAddress.return_value = 0x1004
        mock_addr2.GetFileAddress.return_value = 0x804
        mock_addr2.file_addr = 0x804
        mock_inst2.GetMnemonic.return_value = "ldr"
        mock_inst2.GetOperands.return_value = "x16, [x16]"
        mock_inst2.size = 4

        # Setup instruction 3
        mock_addr3 = MagicMock()
        mock_inst3.GetAddress.return_value = mock_addr3
        mock_addr3.GetLoadAddress.return_value = 0x1008
        mock_addr3.GetFileAddress.return_value = 0x808
        mock_addr3.file_addr = 0x808
        mock_inst3.GetMnemonic.return_value = "br"
        mock_inst3.GetOperands.return_value = "x16"
        mock_inst3.size = 4

        # Execute the method under test
        self.step_handler._cache_instruction_info(mock_frame, 0x1234)

        # Verify function start address was added
        self.assertIn(0x1000, self.step_handler.function_start_addrs)

        # Verify cache contents
        self.assertEqual(len(self.step_handler.instruction_info_cache), 3)
        self.assertEqual(
            self.step_handler.instruction_info_cache[0x1000],
            ("adrp", "x16, 2", 4, 0),  # (mnemonic, operands, size, offset)
        )
        self.assertEqual(self.step_handler.instruction_info_cache[0x1004], ("ldr", "x16, [x16]", 4, 4))
        self.assertEqual(self.step_handler.instruction_info_cache[0x1008], ("br", "x16", 4, 8))

    @patch("tracer.step_handler.lldb")
    def test_get_line_entry_cache_hit(self, _mock_lldb):
        """
        Test that cached line entry is returned when pc is found in cache.
        Verifies cache hit behavior and prevents unnecessary frame lookups.
        """
        # Setup
        pc = 0x1000
        mock_frame = MagicMock()
        cached_entry = MagicMock()
        self.step_handler.line_cache[pc] = cached_entry

        # Execute
        result = self.step_handler._get_line_entry(mock_frame, pc)

        # Verify
        self.assertEqual(result, cached_entry, "Should return cached line entry")
        mock_frame.GetLineEntry.assert_not_called()

    @patch("tracer.step_handler.lldb")
    def test_get_line_entry_cache_miss(self, _mock_lldb):
        """
        Test that line entry is fetched from frame and cached when pc is not in cache.
        Verifies cache miss behavior and proper caching of new entries.
        """
        # Setup
        pc = 0x2000
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_frame.GetLineEntry.return_value = mock_line_entry

        # Execute
        result = self.step_handler._get_line_entry(mock_frame, pc)

        # Verify
        mock_frame.GetLineEntry.assert_called_once()
        self.assertEqual(result, mock_line_entry, "Should return new line entry")
        self.assertIn(pc, self.step_handler.line_cache, "Should cache new entry")
        self.assertEqual(self.step_handler.line_cache[pc], mock_line_entry, "Cached entry should match returned value")

    @patch("tracer.step_handler.lldb")
    def test_process_source_info_valid_line_entry(self, _mock_lldb):
        """
        Tests _process_source_info with a valid line entry.
        Verifies correct processing of file paths, line/column info,
        and proper delegation to helper methods.
        """
        # Setup mock objects
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()

        # Configure line entry mock
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = "/original/path/file.c"
        mock_line_entry.GetLine.return_value = 196
        mock_line_entry.GetColumn.return_value = 1

        # Configure source handler mock
        self.step_handler.source_handler.resolve_source_path.return_value = "/resolved/path/file.c"

        # Mock helper methods
        with (
            patch.object(
                self.step_handler, "_build_source_info_string", return_value="file.c:196:1"
            ) as mock_build_info_string,
            patch.object(
                self.step_handler, "_get_source_line", return_value="source code line"
            ) as mock_get_source_line,
        ):
            # Execute method under test
            result = self.step_handler._process_source_info(mock_frame, mock_line_entry)

            # Verify results
            self.assertEqual(result, ("file.c:196:1", "source code line", "/resolved/path/file.c"))

            # Verify interactions
            self.step_handler.source_handler.resolve_source_path.assert_called_once_with("/original/path/file.c")
            mock_build_info_string.assert_called_once_with("/original/path/file.c", "/resolved/path/file.c", 196, 1)
            mock_get_source_line.assert_called_once_with(mock_frame, "/resolved/path/file.c", 196)

    @patch("tracer.step_handler.lldb")
    def test_process_source_info_invalid_line_entry(self, _mock_lldb):
        """
        Test that when line_entry is invalid, it returns empty strings and None.
        This verifies the early exit condition for invalid line entries.
        """
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = False

        result = self.step_handler._process_source_info(mock_frame, mock_line_entry)

        self.assertEqual(result, ("", "", None))
        mock_line_entry.IsValid.assert_called_once()
        self.step_handler.source_handler.resolve_source_path.assert_not_called()

    @patch("tracer.step_handler.lldb")
    def test_process_source_info_with_exception_in_get_source_line(self, _mock_lldb):
        """
        Test that when _get_source_line encounters an exception during source line retrieval,
        it returns the source info string, an empty string for source line, and the resolved file path.
        This scenario verifies error handling when fetching source code fails.
        """
        # Configure mock line entry
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = "/fake/path/file.c"
        mock_line_entry.GetLine.return_value = 64
        mock_line_entry.GetColumn.return_value = 3

        # Configure mock source handler
        self.step_handler.source_handler.resolve_source_path.return_value = "/resolved/path/file.c"

        # Simulate exception in source_handler.get_source_code_for_statement
        self.step_handler.source_handler.get_source_code_for_statement.side_effect = Exception(
            "Frame exited without a 'return' or 'exception' event being traced."
        )

        # Mock the internal helper to return expected source info
        with patch.object(
            self.step_handler, "_build_source_info_string", return_value="/resolved/path/file.c:64:3"
        ) as mock_build_info_string:
            # Call the method with mock frame and line entry
            result = self.step_handler._process_source_info(mock_frame, mock_line_entry)

            # Verify return values
            self.assertEqual(result[0], "/resolved/path/file.c:64:3")
            self.assertEqual(result[1], "")  # Empty string due to exception
            self.assertEqual(result[2], "/resolved/path/file.c")

            # Verify warning was logged
            self.mock_tracer.logger.warning.assert_called_once_with("Failed to get source line: %s", ANY)

            mock_build_info_string.assert_called_once_with("/fake/path/file.c", "/resolved/path/file.c", 64, 3)
            self.step_handler.source_handler.resolve_source_path.assert_called_once_with("/fake/path/file.c")
            # FIX: The actual call in _get_source_line only passes `frame`.
            # The test should reflect this behavior.
            self.step_handler.source_handler.get_source_code_for_statement.assert_called_once_with(mock_frame)

    @patch("tracer.step_handler.lldb")
    def test_process_source_info_with_unresolved_path(self, _mock_lldb):
        """Test valid line entry with unresolved file path uses original path."""
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = "/original/path/file.c"
        mock_line_entry.GetLine.return_value = 65
        mock_line_entry.GetColumn.return_value = 5
        self.step_handler.source_handler.resolve_source_path.return_value = None

        with patch.object(self.step_handler, "_get_source_line", return_value=""):
            result = self.step_handler._process_source_info(mock_frame, mock_line_entry)

        self.assertEqual(result[0], "/original/path/file.c:65:5")
        self.assertEqual(result[1], "")
        self.assertEqual(result[2], None)
        self.step_handler.source_handler.resolve_source_path.assert_called_once_with("/original/path/file.c")

    @patch("tracer.step_handler.lldb")
    def test_process_source_info_with_zero_line_number(self, _mock_lldb):
        """Test valid line entry with line number 0 returns special line indicator."""
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = True
        mock_line_entry.GetFileSpec.return_value.fullpath = "/original/path/file.c"
        mock_line_entry.GetLine.return_value = 0
        mock_line_entry.GetColumn.return_value = 5
        self.step_handler.source_handler.resolve_source_path.return_value = "/resolved/path/file.c"

        with patch.object(self.step_handler, "_get_source_line", return_value=""):
            result = self.step_handler._process_source_info(mock_frame, mock_line_entry)

        self.assertEqual(result[0], "/resolved/path/file.c:<no line>")
        self.assertEqual(result[1], "")
        self.assertEqual(result[2], "/resolved/path/file.c")

    @patch("tracer.step_handler.lldb")
    def test_line_entry_access_raises_exception(self, _mock_lldb):
        """Test exception during line entry access propagates correctly."""
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.side_effect = RuntimeError("Frame exited")

        with self.assertRaises(RuntimeError) as context:
            self.step_handler._process_source_info(mock_frame, mock_line_entry)

        self.assertEqual(str(context.exception), "Frame exited")

    @patch("tracer.step_handler.lldb")
    def test_process_source_info_propagates_resolution_exception(self, _mock_lldb):
        """
        Tests that _process_source_info correctly propagates exceptions raised
        during source path resolution by the SourceHandler.

        Scenario:
        - Valid line entry with a file path
        - SourceHandler's resolve_source_path raises an exception
        - Verifies the exception propagates out of _process_source_info
        """
        # Configure source handler to raise exception
        self.step_handler.source_handler.resolve_source_path.side_effect = RuntimeError("Simulated resolution error")

        # Create mock frame and line entry
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.IsValid.return_value = True

        # Configure file spec chain
        mock_file_spec = MagicMock()
        mock_file_spec.fullpath = "/test/path/file.c"
        mock_line_entry.GetFileSpec.return_value = mock_file_spec

        # Execute test and verify exception propagation
        with self.assertRaises(RuntimeError) as context:
            self.step_handler._process_source_info(mock_frame, mock_line_entry)

        self.assertEqual(
            str(context.exception), "Simulated resolution error", "Should propagate exact exception message"
        )

        # Verify expected interactions
        mock_line_entry.IsValid.assert_called_once()
        mock_line_entry.GetFileSpec.assert_called_once()
        self.step_handler.source_handler.resolve_source_path.assert_called_once_with("/test/path/file.c")

    def test_build_source_info_string_absolute_path_with_valid_line_and_column(self):
        """Test with absolute path, valid line/column numbers, and no source base directory."""
        # Setup (config_manager.get_source_base_dir is mocked in setUp to return '')
        self.mock_tracer.config_manager.get_source_base_dir.return_value = ""

        # Execute
        result = self.step_handler._build_source_info_string("/abs/path/file.c", "/abs/path/file.c", 196, 1)

        # Verify
        self.assertEqual(result, "/abs/path/file.c:196:1")
        self.mock_tracer.config_manager.get_source_base_dir.assert_called_once()

    def test_build_source_info_string_relative_path_conversion(self):
        """Test path conversion to relative when source base directory is set and matches."""
        # Setup
        self.mock_tracer.config_manager.get_source_base_dir.return_value = "/base"

        # Execute
        result = self.step_handler._build_source_info_string("/base/original.c", "/base/resolved.c", 100, 5)

        # Verify
        self.assertEqual(result, "resolved.c:100:5")
        self.mock_tracer.config_manager.get_source_base_dir.assert_called_once()

    def test_build_source_info_string_absolute_path_when_base_doesnt_match(self):
        """Test absolute path used when source base directory doesn't match resolved path."""
        # Setup
        self.mock_tracer.config_manager.get_source_base_dir.return_value = "/other"

        # Execute
        result = self.step_handler._build_source_info_string("/abs/path/file.c", "/abs/path/file.c", 50, 10)

        # Verify
        self.assertEqual(result, "/abs/path/file.c:50:10")
        self.mock_tracer.config_manager.get_source_base_dir.assert_called_once()

    def test_build_source_info_string_invalid_line_number(self):
        """Test handling of invalid (<=0) line numbers."""
        # Setup
        self.mock_tracer.config_manager.get_source_base_dir.return_value = ""

        # Execute
        result = self.step_handler._build_source_info_string("/abs/path/file.c", "/abs/path/file.c", 0, 5)

        # Verify
        self.assertEqual(result, "/abs/path/file.c:<no line>")
        self.mock_tracer.config_manager.get_source_base_dir.assert_called_once()

    def test_build_source_info_string_missing_column_info(self):
        """Test output without column when column number is invalid (<=0)."""
        # Setup
        self.mock_tracer.config_manager.get_source_base_dir.return_value = ""

        # Execute
        result = self.step_handler._build_source_info_string("/abs/path/file.c", "/abs/path/file.c", 100, 0)

        # Verify
        self.assertEqual(result, "/abs/path/file.c:100")
        self.mock_tracer.config_manager.get_source_base_dir.assert_called_once()

    def test_build_source_info_string_fallback_to_original_path(self):
        """Test fallback to original path when resolved path is None."""
        # Setup
        self.mock_tracer.config_manager.get_source_base_dir.return_value = ""

        # Execute
        result = self.step_handler._build_source_info_string("/fallback/path.c", None, 200, 3)

        # Verify
        self.assertEqual(result, "/fallback/path.c:200:3")
        self.mock_tracer.config_manager.get_source_base_dir.assert_called_once()

    def test_build_source_info_string_fallback_to_original_path_when_resolved_empty(self):
        """Test fallback to original path when resolved path is empty string."""
        # Setup
        self.mock_tracer.config_manager.get_source_base_dir.return_value = ""

        # Execute
        result = self.step_handler._build_source_info_string("/fallback/path.c", "", 75, 2)

        # Verify
        self.assertEqual(result, "/fallback/path.c:75:2")
        self.mock_tracer.config_manager.get_source_base_dir.assert_called_once()

    @patch("tracer.step_handler.lldb")
    def test_get_source_line_handles_exception(self, _mock_lldb):
        """
        Test that _get_source_line correctly handles exceptions from
        source_handler.get_source_code_for_statement by returning an empty string
        and logging a warning.
        """
        # Mock frame object
        mock_frame = MagicMock()

        # Configure source_handler.get_source_code_for_statement to raise an exception
        exception_msg = "Frame exited without a 'return' or 'exception' event being traced."
        self.step_handler.source_handler.get_source_code_for_statement.side_effect = Exception(exception_msg)

        # Call the method under test
        result = self.step_handler._get_source_line(mock_frame, "dummy_path", 65)

        # Verify results
        self.assertEqual(result, "")
        self.mock_tracer.logger.warning.assert_called_once_with("Failed to get source line: %s", exception_msg)


class TestExpressionAndDebugInfo(BaseStepHandlerTest):
    """
    Test suite for handling source expressions, debug information,
    and address-to-symbol resolution within StepHandler.
    """

    @patch("builtins.open", new_callable=MagicMock)
    @patch("tracer.step_handler.parse_code_file", new_callable=MagicMock)
    def test_evaluate_source_expressions_with_cached_empty_file(self, mock_parse_code_file, mock_open):
        """
        Test that _evaluate_source_expressions returns an empty list when:
        - The filepath has a valid source extension
        - The file exists in the expression cache
        - The cache entry for the file is an empty dictionary
        - There are no expressions for the given line number
        """
        # Configure test data based on execution trace
        test_filepath = "/Users/richard/code/terminal-llm/debugger/lldb/basic_program/basic_main.c"
        test_line_num = 196

        # Set up the expression cache state (empty dict for this file)
        self.step_handler.expression_cache = {test_filepath: {}}

        # Execute the method under test
        result = self.step_handler._evaluate_source_expressions(MagicMock(), test_filepath, test_line_num)

        # Verify the result matches the expected empty list
        self.assertEqual(result, [])
        mock_open.assert_not_called()
        mock_parse_code_file.assert_not_called()

    @patch("tracer.step_handler.lldb")
    def test_evaluate_source_expressions_returns_empty_list_when_filepath_is_none(self, _mock_lldb):
        """
        Test that empty list is returned when filepath is None.
        Verifies early exit condition when no valid filepath is provided.
        """
        result = self.step_handler._evaluate_source_expressions(MagicMock(), None, 42)
        self.assertEqual(result, [])

    @patch("tracer.step_handler.lldb")
    def test_evaluate_source_expressions_returns_empty_list_for_non_source_file_extension(self, _mock_lldb):
        """
        Test that empty list is returned for non-source file extensions.
        Verifies filtering of non-C/C++ source files.
        """
        result = self.step_handler._evaluate_source_expressions(MagicMock(), "script.py", 42)
        self.assertEqual(result, [])

    @patch("tracer.step_handler.lldb")
    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_evaluate_source_expressions_returns_empty_list_when_file_not_found(self, mock_open, _mock_lldb):
        """
        Test that empty list is returned when source file can't be opened.
        Verifies graceful handling of missing files.
        """
        result = self.step_handler._evaluate_source_expressions(MagicMock(), "missing.c", 42)
        self.assertEqual(result, [])
        mock_open.assert_called_once_with("missing.c", "rb")

    @patch("tracer.step_handler.lldb")
    def test_evaluate_source_expressions_returns_expressions_when_valid_file_and_line(self, _mock_lldb):
        """
        Test that expressions are returned for valid source file and line number.
        Verifies successful extraction and evaluation of expressions.
        """
        # Setup expression cache
        self.step_handler.expression_cache = {"valid.c": {41: [(None, "x", None), (None, "y", None)]}}
        mock_frame = MagicMock()

        # Mock frame locals
        with patch.object(self.step_handler, "_get_frame_locals", return_value={"x": "10", "y": "20"}):
            result = self.step_handler._evaluate_source_expressions(mock_frame, "valid.c", 42)
            self.assertEqual(result, ["x=10", "y=20"])

    @patch("tracer.step_handler.lldb")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("tracer.step_handler.parse_code_file", new_callable=MagicMock)
    def test_evaluate_source_expressions_raises_exception_when_extraction_fails(
        self, mock_parse, mock_file, _mock_lldb
    ):
        """
        Tests that _evaluate_source_expressions propagates exceptions
        raised during expression extraction when parsing fails unexpectedly.

        This simulates a scenario where:
        1. The source file extension is valid (C source file)
        2. The file is not in the expression cache
        3. File reading and parsing succeeds
        4. Expression extraction fails with an unexpected exception
        """
        mock_frame = MagicMock()
        self.step_handler.expression_cache = {}

        # Configure test parameters
        filepath = "/path/to/valid_source.c"
        line_num = 195

        # Mock expression extractor to raise exception
        self.step_handler.expression_extractor.extract.side_effect = RuntimeError("Extraction failed")

        # Mock parser loader to return a valid parser (its get_parser is called internally)
        self.step_handler.parser_loader.get_parser.return_value = (MagicMock(), None, None)

        # Mock file content
        mock_file_content = b"int main() { return 0; }"
        mock_file.return_value.__enter__.return_value.read.return_value = mock_file_content

        # Verify exception propagation
        with self.assertRaises(RuntimeError):
            self.step_handler._evaluate_source_expressions(mock_frame, filepath, line_num)

        # Verify cache wasn't updated after failure
        self.assertNotIn(filepath, self.step_handler.expression_cache)

        # Verify file was accessed correctly
        mock_file.assert_called_once_with(filepath, "rb")

        # Verify parsing was attempted
        mock_parse.assert_called_once()
        self.step_handler.parser_loader.get_parser.assert_called_once_with(filepath)
        self.step_handler.expression_extractor.extract.assert_called_once()

    @patch("tracer.step_handler.lldb")
    def test_process_line_expressions_empty_cache(self, _mock_lldb):
        """Test that when the expression cache for the filepath has no expressions for the given line, an empty list
        is returned.

        This scenario occurs when:
        1. The expression_cache dictionary exists for the filepath but is empty
        2. There are no expressions cached for the specific line number (line_num - 1)
        3. The function should return an empty list immediately
        """
        # Create mock objects
        mock_frame = MagicMock()

        # Set up test data
        test_filepath = "/path/to/test_file.c"
        test_line_num = 196

        # Configure expression cache state (empty for this filepath)
        self.step_handler.expression_cache = {test_filepath: {}}

        # Execute the method under test
        result = self.step_handler._process_line_expressions(mock_frame, test_filepath, test_line_num)

        # Verify the result
        self.assertEqual(result, [])
        self.step_handler.expression_extractor.extract.assert_not_called()

    @patch("tracer.step_handler.lldb")
    def test_process_debug_info_in_instruction_mode(self, _mock_lldb):
        """Test that debug info is correctly processed in instruction mode.

        Verifies that:
        1. In instruction mode, capture_register_values() is called
        2. Source expressions are evaluated
        3. Results are combined and returned correctly
        """
        # Set instruction mode
        self.step_handler.insutruction_mode = True

        # Create test data based on the execution trace
        mock_frame = MagicMock()
        mock_line_entry = MagicMock()
        mock_line_entry.GetLine.return_value = 64
        mock_frame.GetLineEntry.return_value = mock_line_entry

        mnemonic = "ldur"
        parsed_operands = [MagicMock(), MagicMock()]  # Simplified operand objects
        resolved_path = "/mock/path/to/file.c"

        # Mock return values from sub-calls
        register_values = ["$w8=0x0", "[x29 + -0x4] = [0x16f46737c] = 0x6f46749000000000"]
        source_expressions = []

        # Configure mocks
        self.step_handler.debug_info_handler.capture_register_values.return_value = register_values
        with patch.object(
            self.step_handler, "_evaluate_source_expressions", return_value=source_expressions
        ) as mock_eval_source:
            # Execute method under test
            result = self.step_handler._process_debug_info(mock_frame, mnemonic, parsed_operands, resolved_path)

            # Verify debug info handler was called correctly
            self.step_handler.debug_info_handler.capture_register_values.assert_called_once_with(
                mock_frame, mnemonic, parsed_operands
            )

            # Verify source expression evaluation was called
            mock_eval_source.assert_called_once_with(mock_frame, resolved_path, mock_frame.GetLineEntry().GetLine())

            # Verify combined results
            self.assertEqual(result, register_values + source_expressions)

    @patch("tracer.step_handler.lldb")
    def test_process_debug_info_raises_implicit_exit(self, _mock_lldb):
        """Test that _process_debug_info propagates ImplicitExit when debug_info_handler fails"""
        # Set instruction mode
        self.step_handler.insutruction_mode = True

        # Configure mock dependencies
        mock_frame = MagicMock()
        mock_frame.GetLineEntry.return_value.GetLine.return_value = 65
        mock_frame.module.file.fullpath = "/path/to/module"

        # Configure the method that should raise an exception
        self.step_handler.debug_info_handler.capture_register_values.side_effect = ImplicitExit(
            "Frame exited without a 'return' or 'exception' event being traced."
        )

        # Prepare test inputs
        mnemonic = "mov"
        parsed_operands = MagicMock()
        resolved_path = "/Users/richard/code/terminal-llm/debugger/lldb/basic_program/basic_main.c"

        # Test that the exception is propagated
        with self.assertRaises(ImplicitExit) as context:
            self.step_handler._process_debug_info(mock_frame, mnemonic, parsed_operands, resolved_path)

        # Verify exception message
        self.assertEqual(str(context.exception), "Frame exited without a 'return' or 'exception' event being traced.")

        # Verify debug_info_handler was called with expected arguments
        self.step_handler.debug_info_handler.capture_register_values.assert_called_once_with(
            mock_frame, mnemonic, parsed_operands
        )

    @patch("tracer.step_handler.lldb")
    def test_get_address_info_with_invalid_symbol(self, _mock_lldb):
        """Test address resolution when symbol and module information are invalid.

        This test verifies that when:
        1. The address is not in the cache
        2. The resolved symbol is invalid (None)
        3. The resolved module is invalid (None)

        The method correctly:
        - Returns the expected tuple with hex address, 'unknown' module path, and invalid symbol type
        - Updates the internal cache with the resolved information
        - Calls the underlying LLDB API correctly
        """
        # Setup lldb constants
        _mock_lldb.eSymbolTypeInvalid = 0

        # Create test data
        test_addr = 4294974552
        expected_hex = f"0x{test_addr:x}"

        mock_resolved = MagicMock()
        mock_resolved.symbol = None  # Invalid symbol
        mock_resolved.module = None  # Invalid module
        self.mock_tracer.target.ResolveLoadAddress.return_value = mock_resolved

        # Execute the method
        result = self.step_handler._get_address_info(test_addr)

        # Verify results
        self.assertEqual(result, (expected_hex, "unknown", 0))
        self.assertIn(test_addr, self.step_handler.addr_to_symbol_cache)
        self.assertEqual(self.step_handler.addr_to_symbol_cache[test_addr], (expected_hex, "unknown", 0))

        # Verify LLDB API calls
        self.mock_tracer.target.ResolveLoadAddress.assert_called_once_with(test_addr)

    @patch("tracer.step_handler.lldb")
    def test_get_address_info_with_valid_symbol(self, _mock_lldb):
        """
        Tests that _get_address_info correctly resolves address information
        when a valid symbol is found and updates the cache.
        """
        # Create mock resolved address object
        mock_resolved = MagicMock()
        mock_resolved.symbol.name = "printf"
        mock_resolved.symbol.type = 2
        mock_resolved.module.file.fullpath = "/usr/lib/system/libsystem_c.dylib"
        self.mock_tracer.target.ResolveLoadAddress.return_value = mock_resolved

        test_addr = 6565722920

        # Precondition: Address not in cache
        self.assertNotIn(test_addr, self.step_handler.addr_to_symbol_cache)

        # Execute
        result = self.step_handler._get_address_info(test_addr)

        # Verify
        expected = ("printf", "/usr/lib/system/libsystem_c.dylib", 2)
        self.assertEqual(result, expected)
        self.assertEqual(self.step_handler.addr_to_symbol_cache[test_addr], expected)
        self.mock_tracer.target.ResolveLoadAddress.assert_called_once_with(test_addr)

    @patch("tracer.step_handler.lldb")
    def test_get_address_info_with_invalid_symbol_type(self, _mock_lldb):
        """
        Tests that _get_address_info handles cases where no valid symbol
        is found for the address.
        """
        # Create mock resolved address with invalid symbol
        mock_resolved = MagicMock()
        mock_resolved.symbol = None
        mock_resolved.module = None
        self.mock_tracer.target.ResolveLoadAddress.return_value = mock_resolved

        test_addr = 0xDEADBEEF

        # Execute
        result = self.step_handler._get_address_info(test_addr)

        # Verify
        expected_name = f"0x{test_addr:x}"
        self.assertEqual(result[0], expected_name)
        self.assertEqual(result[1], "unknown")
        # Ensure lldb.eSymbolTypeInvalid is correctly mocked/defined for the test context
        self.assertEqual(result[2], _mock_lldb.eSymbolTypeInvalid)
        self.assertEqual(
            self.step_handler.addr_to_symbol_cache[test_addr],
            (expected_name, "unknown", _mock_lldb.eSymbolTypeInvalid),
        )

    @patch("tracer.step_handler.lldb")
    def test_get_address_info_cache_hit(self, _mock_lldb):
        """
        Tests that _get_address_info returns cached results when available
        without calling ResolveLoadAddress.
        """
        test_addr = 6565722920
        cached_value = ("cached_func", "/lib/cached.so", 1)
        self.step_handler.addr_to_symbol_cache[test_addr] = cached_value

        # Execute
        result = self.step_handler._get_address_info(test_addr)

        # Verify
        self.assertEqual(result, cached_value)
        self.mock_tracer.target.ResolveLoadAddress.assert_not_called()

    @patch("tracer.step_handler.lldb")
    def test_get_address_info_when_symbol_not_found(self, _mock_lldb):
        """
        Tests that _get_address_info returns the expected tuple
        (hex address, 'unknown', 0) when symbol resolution fails.
        Verifies both the return value and cache update behavior.
        """
        # Setup mock objects
        mock_resolved_address = MagicMock()

        # Configure mocks for symbol resolution failure scenario
        mock_resolved_address.symbol = None
        mock_resolved_address.module = None
        self.mock_tracer.target.ResolveLoadAddress.return_value = mock_resolved_address

        # Fix: Configure the mock for lldb.eSymbolTypeInvalid to return 0
        _mock_lldb.eSymbolTypeInvalid = 0

        # Address value from the execution trace
        test_addr = 4294974616

        # Execute the method under test
        result = self.step_handler._get_address_info(test_addr)

        # Verify return value matches expected format
        self.assertEqual(result, ("0x100001c98", "unknown", 0))

        # Verify cache was updated with the correct information
        self.assertIn(test_addr, self.step_handler.addr_to_symbol_cache)
        self.assertEqual(self.step_handler.addr_to_symbol_cache[test_addr], ("0x100001c98", "unknown", 0))


class TestStepHitAndLogging(BaseStepHandlerTest):
    """
    Test suite for determining step actions, handling branch instructions,
    and logging the execution trace.
    """

    @patch("tracer.step_handler.lldb.SBFrame", autospec=True)
    @patch("tracer.step_handler.lldb.SBTarget", autospec=True)
    def test_raises_implicit_exit_when_cache_fails(self, _mock_sbtarget, _mock_sbframe):
        """Test that ImplicitExit is raised when instruction caching fails"""
        # Configure mock dependencies
        self.mock_tracer.modules.should_skip_address.return_value = False
        self.step_handler.instruction_info_cache = {}  # Ensure cache miss

        mock_frame = _mock_sbframe()
        mock_frame.GetPCAddress.return_value.GetLoadAddress.return_value = 4305036284
        mock_frame.module.file.fullpath = "/path/to/basic_program"

        # Mock internal method to raise expected exception
        with patch.object(
            self.step_handler,
            "_cache_instruction_info",
            side_effect=ImplicitExit("Frame exited without 'return' or 'exception' event"),
        ):
            # Execute test and verify exception
            with self.assertRaises(ImplicitExit) as context:
                self.step_handler.on_step_hit(mock_frame, "threadplan")

            # Verify exception message
            self.assertIn("Frame exited without", str(context.exception))

        # Verify dependency calls
        self.mock_tracer.modules.should_skip_address.assert_called_once_with(4305036284, "/path/to/basic_program")

    @patch("tracer.step_handler.lldb")
    def test_on_step_hit_with_instruction_mode_and_valid_frame(self, _mock_lldb):
        """
        Test that on_step_hit correctly handles a step event in instruction mode
        with a valid frame, returning STEP_IN action after processing debug info.
        """
        # Create mock tracer (already in setUp, but customize)
        self.mock_tracer.modules.should_skip_address.return_value = False
        self.mock_tracer.source_ranges.should_skip_source_file_by_path.return_value = False

        # Create mock frame
        mock_frame = MagicMock()
        mock_pc_address = MagicMock()
        mock_pc_address.GetLoadAddress.return_value = 4305034348
        mock_frame.GetPCAddress.return_value = mock_pc_address
        mock_frame.module.file.fullpath = "/Users/richard/code/terminal-llm/debugger/lldb/build/basic_program"
        mock_frame.thread.GetNumFrames.return_value = 3
        mock_frame.GetLineEntry.return_value.GetLine.return_value = 64  # For _process_debug_info call

        # Configure StepHandler instance
        self.step_handler.instruction_info_cache = {4305034348: ("ldur", "w8, [x29, #-0x4]", 4, 20)}
        self.step_handler.base_frame_count = 2
        self.step_handler.insutruction_mode = True
        self.step_handler.step_action = {}  # Reset specific test setup

        with (
            patch.object(self.step_handler, "_get_line_entry") as mock_get_line_entry,
            patch.object(self.step_handler, "_process_source_info") as mock_process_source,
            patch.object(self.step_handler, "_process_debug_info") as mock_process_debug,
            patch.object(self.step_handler, "_determine_step_action") as mock_determine,
            patch.object(self.step_handler, "_log_step_info") as mock_log_step,
            patch("tracer.step_handler.parse_operands") as mock_parse_operands,
        ):  # Import from module
            # Configure mock return values
            mock_get_line_entry.return_value = MagicMock()  # Return a mock SBLineEntry
            mock_process_source.return_value = (
                "/Users/richard/code/terminal-llm/debugger/lldb/basic_program/basic_main.c:64:19",
                "// 循环100次，打印当前循环次数",
                "/Users/richard/code/terminal-llm/debugger/lldb/basic_program/basic_main.c",
            )
            mock_process_debug.return_value = [
                "$w8=0x1",
                "[x29 + -0x4] = [0x16f46737c] = 0x6f46749000000001",
            ]
            mock_determine.return_value = StepAction.STEP_IN
            mock_parse_operands.return_value = [MagicMock(), MagicMock()]

            # Execute the method under test
            result = self.step_handler.on_step_hit(mock_frame, "lr_breakpoint")

            # Assert results
            self.assertEqual(result, StepAction.STEP_IN)
            mock_determine.assert_called_once()
            mock_log_step.assert_called_once()
            mock_process_source.assert_called_once_with(mock_frame, mock_get_line_entry.return_value)
            mock_process_debug.assert_called_once_with(
                mock_frame,
                ANY,
                ANY,
                "/Users/richard/code/terminal-llm/debugger/lldb/basic_program/basic_main.c",
            )

    def test_on_step_hit_raises_exception_during_source_processing(self):
        """
        Tests that on_step_hit correctly propagates exceptions raised during
        source information processing. This simulates a scenario where frame
        exit occurs without proper return/exception events, leading to an
        exception during source info processing.
        """
        # Mock tracer and its dependencies are set up in self.setUp

        # Setup instruction cache
        pc = 4305034392
        self.step_handler.instruction_info_cache[pc] = ("ldur", "w8, [x29, #-0x4]", 4, 64)

        # Mock frame object
        mock_frame = MagicMock()
        mock_frame.GetPCAddress.return_value.GetLoadAddress.return_value = pc
        mock_frame.module.file.fullpath = "/Users/richard/code/terminal-llm/debugger/lldb/build/basic_program"

        # Mock helper methods to control behavior
        with (
            patch.object(self.step_handler, "_get_line_entry") as mock_get_line_entry,
            patch.object(self.step_handler, "_process_source_info") as mock_process_source_info,
        ):
            # Setup mock return values and exceptions
            mock_get_line_entry.return_value = "mocked_line_entry"
            mock_process_source_info.side_effect = RuntimeError(
                "Frame exited without a 'return' or 'exception' event being traced."
            )

            # Execute test and verify exception
            with self.assertRaises(RuntimeError) as context:
                self.step_handler.on_step_hit(mock_frame, "lr_breakpoint")

            # Verify exception message
            self.assertEqual(
                str(context.exception), "Frame exited without a 'return' or 'exception' event being traced."
            )

            # Verify internal method calls
            mock_get_line_entry.assert_called_once_with(mock_frame, pc)
            mock_process_source_info.assert_called_once_with(mock_frame, "mocked_line_entry")

        # Verify module skip check was performed. Use assert_any_call because should_skip_address can be called
        # multiple times.
        self.mock_tracer.modules.should_skip_address.assert_any_call(pc, mock_frame.module.file.fullpath)

    def test_log_instruction_mode_with_source_line(self):
        """
        Test that _log_instruction_mode correctly formats and logs
        an instruction with source line information when debug_values is empty.
        """
        # Mocks are set up in setUp
        # Call the method with specific parameters
        self.step_handler._log_instruction_mode(
            indent="",
            pc=4305036288,
            first_inst_offset=32,
            mnemonic="bl",
            operands="0x100001c58",
            source_info="/Users/richard/code/terminal-llm/debugger/lldb/basic_program/basic_main.c:196:1",
            source_line='asm volatile("nop"); loop_100(); /',
            debug_values=[],
        )

        # Verify logger was called with expected parameters
        expected_format = "%s0x%x <+%d> %s %s ; %s // %s%s"
        expected_args = (
            "",
            4305036288,
            32,
            "bl",
            "0x100001c58",
            "/Users/richard/code/terminal-llm/debugger/lldb/basic_program/basic_main.c:196:1",
            'asm volatile("nop"); loop_100(); /',
            "",
        )
        self.mock_tracer.logger.info.assert_called_once_with(expected_format, *expected_args)

    def test_log_instruction_mode_without_source_line(self):
        """Test logging in instruction mode without source line information.

        Verifies that the logger formats and outputs assembly instructions correctly
        when no source line is available, including debug values when present.
        """
        # Mocks are set up in setUp
        # Call method with parameters from the execution trace
        self.step_handler._log_instruction_mode(
            indent="",
            pc=4305038940,
            first_inst_offset=4,
            mnemonic="ldr",
            operands="x16",
            source_info="",
            source_line="",
            debug_values=["[x16] = [0x10099c000] = 0x18758fb28"],
        )

        # Verify logger was called with expected arguments
        expected_debug_part = " -> [x16] = [0x10099c000] = 0x18758fb28"
        self.mock_tracer.logger.info.assert_called_once_with(
            "%s0x%x <+%d> %s %s ; %s%s", "", 4305038940, 4, "ldr", "x16", "", expected_debug_part
        )

    def test_log_step_info_calls_instruction_mode_when_in_instruction_log_mode(self):
        """
        Tests that _log_step_info correctly routes to _log_instruction_mode
        when log_mode is set to 'instruction'.
        """
        # Setup test parameters from the execution trace
        test_args = {
            "indent": "",
            "mnemonic": "ldr",
            "operands": "x16",
            "first_inst_offset": 4,
            "pc": 4305038940,
            "source_info": "",
            "source_line": "",
            "debug_values": ["[x16] = [0x10099c000] = 0x18758fb28"],
        }

        # Execute method under test
        with patch.object(self.step_handler, "_log_instruction_mode") as mock_instruction_mode:
            self.step_handler._log_step_info(**test_args)

            # Verify correct method was called with expected parameters
            mock_instruction_mode.assert_called_once_with(
                "", 4305038940, 4, "ldr", "x16", "", "", ["[x16] = [0x10099c000] = 0x18758fb28"]
            )

    def test_log_step_info_calls_source_mode_when_in_source_log_mode(self):
        """
        Tests that _log_step_info correctly routes to _log_source_mode
        when log_mode is set to 'source' and valid source_info exists.
        """
        # Configure for source mode
        self.mock_tracer.config_manager.get_log_mode.return_value = "source"
        self.step_handler.log_mode = "source"  # Re-set after StepHandler init in setUp
        self.step_handler.insutruction_mode = False

        test_args = {
            "indent": "    ",
            "mnemonic": "mov",  # Mnemonic/operands not used in source mode logging
            "operands": "x0, x1",
            "first_inst_offset": 0,
            "pc": 0x100000000,
            "source_info": "main.c:10:5",
            "source_line": "int x = 5;",
            "debug_values": ["x=5"],
        }

        # Execute method under test
        with patch.object(self.step_handler, "_log_source_mode") as mock_source_mode:
            self.step_handler._log_step_info(**test_args)

            # Verify correct method was called with expected parameters
            mock_source_mode.assert_called_once_with("    ", "main.c:10:5", "int x = 5;", ["x=5"])


class TestBranchHandling(BaseStepHandlerTest):
    """
    Test suite for determining step actions, handling branch instructions,
    and logging the execution trace.
    """

    def test_recognizes_branch_instructions(self):
        """Tests that branch instructions are correctly identified as branch operations."""
        # Known branch instructions from the function's logic
        branch_instructions = ["br", "braa", "brab", "blraa", "blr", "b", "bl"]

        for mnemonic in branch_instructions:
            with self.subTest(mnemonic=mnemonic):
                result = self.step_handler.is_branch_instruction(mnemonic)
                self.assertTrue(result, f"'{mnemonic}' should be recognized as branch instruction")

    def test_rejects_non_branch_instructions(self):
        """Tests that non-branch instructions are correctly rejected as non-branch operations."""
        non_branch_instructions = ["add", "sub", "mov", "ldr", "str", "ret", "nop"]

        for mnemonic in non_branch_instructions:
            with self.subTest(mnemonic=mnemonic):
                result = self.step_handler.is_branch_instruction(mnemonic)
                self.assertFalse(result, f"'{mnemonic}' should NOT be recognized as branch instruction")

    @patch("tracer.step_handler.lldb")
    def test_handle_branch_case_external_function_call(self, _mock_lldb):
        """
        Test branch handling for 'bl' instruction calling an external function.
        Verifies step action is correctly determined for function calls.
        """
        self.step_handler.base_frame_count = -1  # Not relevant here, but from trace

        # Create mock frame and operand objects
        mock_frame = _mock_lldb.SBFrame()
        mock_operand = MagicMock()
        mock_operand.type = OperandType.ADDRESS
        mock_operand.value = "0x100001c58"

        # Configure mock return values based on execution trace
        with (
            patch.object(self.step_handler, "_get_branch_target", return_value=4294974552),
            patch.object(self.step_handler, "_is_internal_branch", return_value=None),
            patch.object(self.step_handler, "_handle_branch_instruction", return_value=StepAction.STEP_IN),
        ):
            # Call the method with test parameters
            result = self.step_handler._handle_branch_case(
                mnemonic="bl",
                parsed_operands=[mock_operand],
                frame=mock_frame,
                pc=4305036288,
                next_pc=4305036292,
                indent="",
            )

            # Verify correct step action is returned
            self.assertEqual(result, StepAction.STEP_IN)
            self.step_handler._get_branch_target.assert_called_once_with("bl", [mock_operand], mock_frame)
            self.step_handler._is_internal_branch.assert_called_once_with(
                mock_frame, 4294974552, 4305036288, 4305036292, "bl", ""
            )  # Added mnemonic in assertion as per function signature
            self.step_handler._handle_branch_instruction.assert_called_once_with(
                "bl", 4294974552, mock_frame, 4305036288, 4305036292, ""
            )

    @patch("tracer.step_handler.lldb")
    def test_get_branch_target_bl_address_operand(self, _mock_lldb):
        """
        Test that _get_branch_target correctly converts an address operand
        string to an integer for 'bl' instructions.
        """
        # Prepare test data
        mnemonic = "bl"
        address_str = "0x100001c58"
        expected_address = int(address_str, 16)  # 4294974552

        # Create operand with ADDRESS type and string value
        mock_operand = MagicMock()
        mock_operand.type = OperandType.ADDRESS
        mock_operand.value = address_str
        parsed_operands = [mock_operand]

        # Mock frame (not used in this branch but required by signature)
        mock_frame = _mock_lldb.SBFrame()

        # Call the method under test
        result = self.step_handler._get_branch_target(mnemonic, parsed_operands, mock_frame)

        # Verify correct integer conversion
        self.assertEqual(result, expected_address)

    @patch("tracer.step_handler.lldb")
    def test_get_branch_target_for_br_register_operand(self, _mock_lldb):
        """Test that _get_branch_target correctly returns the unsigned integer value
        of a register when the mnemonic is 'br' and the first operand is a register.
        """
        # Configure mock frame and register
        mock_frame = _mock_lldb.SBFrame()
        mock_register = MagicMock()
        mock_register.IsValid.return_value = True
        mock_register.unsigned = 0x18758FB28
        mock_frame.FindRegister.return_value = mock_register

        # Create mock operand
        mock_operand = MagicMock()
        # 修复：直接使用枚举成员而非.value
        mock_operand.type = OperandType.REGISTER
        mock_operand.value = "x16"

        # Execute method under test
        result = self.step_handler._get_branch_target("br", [mock_operand], mock_frame)

        # Verify results
        self.assertEqual(result, 0x18758FB28)
        mock_frame.FindRegister.assert_called_once_with("x16")
        mock_register.IsValid.assert_called_once()

    @patch("tracer.step_handler.SourceHandler", autospec=True)
    @patch("tracer.step_handler.DebugInfoHandler", autospec=True)
    @patch("tracer.step_handler.lldb")
    def test_is_internal_branch_when_target_addr_outside_function_range(
        self, _mock_lldb, _mock_debug_info_handler, _mock_source_handler
    ):
        """
        Test that _is_internal_branch returns None when the target address
        is outside the current function's address range.

        This scenario verifies the branch detection logic correctly identifies
        external branches by checking address boundaries.
        """
        # Setup mock frame with symbol information
        mock_frame = _mock_lldb.SBFrame()
        mock_symbol = _mock_lldb.SBSymbol()
        mock_frame.symbol = mock_symbol

        # Configure mock address objects
        mock_start_addr = _mock_lldb.SBAddress()
        mock_end_addr = _mock_lldb.SBAddress()
        mock_symbol.GetStartAddress.return_value = mock_start_addr
        mock_symbol.GetEndAddress.return_value = mock_end_addr

        # Set return values for address calculations
        mock_start_addr.GetLoadAddress.return_value = 4305036256
        mock_end_addr.GetLoadAddress.return_value = 4305036704

        # Call the method with test parameters
        result = self.step_handler._is_internal_branch(
            frame=mock_frame,
            target_addr=4294974552,  # Outside function range
            pc=4305036288,
            next_pc=4305036292,
            mnemonic="bl",  # Added mnemonic as per function signature
            indent="",
        )

        # Verify returns None when condition fails
        self.assertIsNone(result)

        # Verify address calculations were called correctly
        mock_symbol.GetStartAddress.assert_called_once()
        mock_symbol.GetEndAddress.assert_called_once()
        mock_start_addr.GetLoadAddress.assert_called_once_with(self.mock_tracer.target)
        mock_end_addr.GetLoadAddress.assert_called_once_with(self.mock_tracer.target)

    @patch("tracer.step_handler.lldb")
    def test_address_outside_current_function_range(self, _mock_lldb):
        """
        Test that an address outside the current function's range returns False.
        The function should compute the function range, cache it, and return False.
        """
        # Configure mock frame with symbol
        mock_frame = _mock_lldb.SBFrame()
        mock_symbol = _mock_lldb.SBSymbol()
        mock_frame.symbol = mock_symbol

        # Configure start/end addresses
        mock_start_address = _mock_lldb.SBAddress()
        mock_end_address = _mock_lldb.SBAddress()
        mock_symbol.GetStartAddress.return_value = mock_start_address
        mock_symbol.GetEndAddress.return_value = mock_end_address

        # 修复：使用MagicMock替换return_value设置，确保返回值正确
        mock_start_address.GetLoadAddress = MagicMock(return_value=0x1000)
        mock_end_address.GetLoadAddress = MagicMock(return_value=0x2000)

        # Address outside function range
        test_addr = 0x500

        # Execute method under test
        result = self.step_handler._is_address_in_current_function(mock_frame, test_addr)

        # Verify results
        self.assertFalse(result)
        # 修复：使用十六进制值进行断言，确保可读性
        self.assertEqual(self.step_handler.function_range_cache, {test_addr: (0x1000, 0x2000)})

        # Verify lldb API interactions
        mock_symbol.GetStartAddress.assert_called_once()
        mock_symbol.GetEndAddress.assert_called_once()
        mock_start_address.GetLoadAddress.assert_called_once_with(self.mock_tracer.target)
        mock_end_address.GetLoadAddress.assert_called_once_with(self.mock_tracer.target)

    @patch("tracer.step_handler.lldb")
    def test_is_address_in_current_function_cached_range_false(self, _mock_lldb):
        """
        Tests that _is_address_in_current_function returns False when:
        - Address is present in function_range_cache
        - Address is outside the cached [start_addr, end_addr) range
        - Frame has a valid symbol
        """
        # Setup mock frame with symbol and its addresses
        mock_frame = _mock_lldb.SBFrame()
        mock_symbol = _mock_lldb.SBSymbol()
        mock_frame.symbol = mock_symbol

        # Configure start/end address mocks to return integer values in case cache is missed
        mock_symbol.GetStartAddress.return_value.GetLoadAddress.return_value = 4305034328
        mock_symbol.GetEndAddress.return_value.GetLoadAddress.return_value = 4305034424

        # Address that should be in cache but outside its range
        test_addr = 4294974616

        # Setup cache with the *correct* key (integer address) and a range that excludes test_addr
        self.step_handler.function_range_cache = {test_addr: (4305034328, 4305034424)}

        # Call method under test
        result = self.step_handler._is_address_in_current_function(
            mock_frame,
            test_addr,
        )

        # Verify result
        self.assertFalse(result)
        # Verify no calls to GetStartAddress/EndAddress because it was cached
        mock_symbol.GetStartAddress.assert_not_called()
        mock_symbol.GetEndAddress.assert_not_called()

    @patch("tracer.step_handler.lldb")
    def test_handle_branch_instruction_bl_not_skipped(self, _mock_lldb):
        """
        Test handling a 'bl' branch instruction that:
        1. Is not within the current function
        2. Resolves to an address that shouldn't be skipped
        3. Should return STEP_IN action
        """
        # Configure step actions (already done in setUp, but explicitly for clarity)
        self.step_handler.step_in = StepAction.STEP_IN
        mock_frame = _mock_lldb.SBFrame()

        # Mock dependencies
        with (
            patch.object(self.step_handler, "_is_address_in_current_function", return_value=False) as mock_in_current,
            patch.object(
                self.step_handler, "_get_address_info", return_value=("0x100001c58", "unknown", 0)
            ) as mock_get_addr,
            patch.object(self.step_handler, "_should_skip_branch_address", return_value=False) as mock_skip_addr,
            patch.object(self.step_handler, "_update_lru_breakpoint") as mock_update_lru,
        ):
            # Execute the method under test
            result = self.step_handler._handle_branch_instruction(
                mnemonic="bl",
                target_addr=0x100001C58,  # 4294974552 in decimal
                frame=mock_frame,
                _pc=4305036288,
                next_pc=4305036292,
                indent="",
            )

            # Verify return value
            self.assertEqual(result, self.step_handler.step_in)

            # Verify internal method calls
            mock_in_current.assert_called_once_with(mock_frame, 0x100001C58)
            mock_get_addr.assert_called_once_with(0x100001C58)
            mock_skip_addr.assert_called_once_with(0x100001C58, "unknown")
            # According to the _handle_branch_instruction logic, _update_lru_breakpoint is *not* called
            # for 'bl' when skip_address is False. This was the cause of the original test failure.
            # The test should assert that it was NOT called.
            mock_update_lru.assert_not_called()


@patch("tracer.step_handler.lldb")
def test_handle_branch_instruction_b_skip(self, _mock_lldb):
    """Test handling of a 'b' branch instruction to a skipped address returns step_over and logs appropriately."""
    # Create mock frame with symbol
    frame = _mock_lldb.SBFrame()
    symbol = _mock_lldb.SBSymbol()
    symbol.name = "symbol_name"  # 修复：使用测试期望的符号名
    frame.symbol = symbol

    # Mock internal methods
    with (
        patch.object(self.step_handler, "_is_address_in_current_function", return_value=False),
        patch.object(
            self.step_handler, "_get_address_info", return_value=("symbol_name", "module_path", "symbol_type")
        ) as mock_get_addr_info,
        patch.object(self.step_handler, "_should_skip_branch_address", return_value=True) as mock_skip_addr,
        patch.object(self.step_handler, "_update_lru_breakpoint") as mock_update_lru,
    ):
        # Call method under test
        result = self.step_handler._handle_branch_instruction(
            mnemonic="b", target_addr=4294974572, frame=frame, _pc=4305034344, next_pc=4305034348, indent="  "
        )

        # Verify return value
        self.assertEqual(result, StepAction.STEP_OVER)

        # Verify logging
        self.mock_tracer.logger.info.assert_called_once_with("%s%s skipping branch to: %s", "  ", "b", "symbol_name")
        mock_update_lru.assert_not_called()


class TestStepActionDetermination(BaseStepHandlerTest):
    """
    Test suite for logic determining the next step action.
    """

    @patch("tracer.step_handler.lldb")
    def test_handle_branch_instruction_br_skipped(self, _mock_lldb):
        """
        Tests that a 'br' instruction targeting a skipped module:
        1. Returns STEP_OVER action
        2. Checks address in current function
        3. Retrieves address info
        4. Checks if address should be skipped
        5. Sets LRU breakpoint for next PC
        """
        # Setup test parameters from execution trace
        mnemonic = "br"
        target_addr = 6565722920
        next_pc = 4305038948
        indent = "    "

        mock_frame = _mock_lldb.SBFrame()

        # Configure mock return values
        with (
            patch.object(self.step_handler, "_is_address_in_current_function", return_value=False) as mock_is_in_func,
            patch.object(
                self.step_handler, "_get_address_info", return_value=("printf", "/usr/lib/system/libsystem_c.dylib", 2)
            ) as mock_get_addr_info,
            patch.object(self.step_handler, "_should_skip_branch_address", return_value=True) as mock_should_skip,
            patch.object(self.step_handler, "_update_lru_breakpoint") as mock_update_lru,
        ):
            # Execute the method under test
            result = self.step_handler._handle_branch_instruction(mnemonic, target_addr, mock_frame, 0, next_pc, indent)

            # Verify return value
            self.assertEqual(result, StepAction.STEP_OVER)

            # Verify internal method calls
            mock_is_in_func.assert_called_once_with(mock_frame, target_addr)
            mock_get_addr_info.assert_called_once_with(target_addr)
            mock_should_skip.assert_called_once_with(target_addr, "/usr/lib/system/libsystem_c.dylib")
            # The original test asserted with 'oneshot=True', but the actual call in production code
            # only passes 'next_pc' and relies on the default 'oneshot=True'.
            # Correcting the assertion to match the actual function call.
            mock_update_lru.assert_called_once_with(next_pc)

    @patch("tracer.step_handler.lldb")
    def test_handle_branch_instruction_raises_exception_when_skip_check_fails(self, _mock_lldb):
        """Tests that _handle_branch_instruction properly propagates exceptions
        when _should_skip_branch_address fails during branch handling.

        This scenario simulates the case where:
        - Branch instruction is a 'b' (mnemonic)
        - Target address is not in current function
        - _should_skip_branch_address raises an ImplicitExit exception
        """
        # Configure method mocks using context managers
        mock_frame = _mock_lldb.SBFrame()
        with (
            patch.object(self.step_handler, "_is_address_in_current_function", return_value=False),
            patch.object(self.step_handler, "_get_address_info", return_value=("0x100001c98", "unknown", 0)),
            patch.object(self.step_handler, "_should_skip_branch_address") as mock_skip,
        ):
            # Set up the exception to be raised
            mock_skip.side_effect = ImplicitExit("Frame exited without a 'return' or 'exception' event being traced.")

            # Verify the expected exception is raised
            with self.assertRaises(ImplicitExit) as context:
                self.step_handler._handle_branch_instruction(
                    mnemonic="b",
                    target_addr=4294974616,
                    frame=mock_frame,
                    _pc=4305034388,
                    next_pc=4305034392,
                    indent="  ",
                )

            # Verify exception message matches trace
            self.assertEqual(
                str(context.exception), "Frame exited without a 'return' or 'exception' event being traced."
            )

            # Verify helper methods were called with expected arguments
            self.step_handler._is_address_in_current_function.assert_called_once_with(mock_frame, 4294974616)
            self.step_handler._get_address_info.assert_called_once_with(4294974616)
            mock_skip.assert_called_once_with(4294974616, "unknown")

    @patch("tracer.step_handler.lldb")
    def test_non_branch_non_return_returns_step_in(self, _mock_lldb):
        """
        Tests that _determine_step_action returns STEP_IN
        for non-branch and non-return instructions.
        """
        # Prepare method arguments
        mnemonic = "stp"  # Non-branch, non-return instruction
        parsed_operands = [MagicMock(), MagicMock(), MagicMock()]  # Unused in this path
        frame = _mock_lldb.SBFrame()  # Minimal frame mock
        pc = 4305034332
        next_pc = 4305034336
        indent = "  "

        # Execute method under test
        result = self.step_handler._determine_step_action(mnemonic, parsed_operands, frame, pc, next_pc, indent)

        # Verify expected result
        self.assertEqual(result, StepAction.STEP_IN)

    @patch("tracer.step_handler.lldb")
    def test_determine_step_action_branch_instruction(self, _mock_lldb):
        """Tests branch instruction handling returning STEP_OVER action.

        Verifies that:
        1. Branch instructions are correctly identified
        2. Handling delegates to _handle_branch_case
        3. Returns the action from _handle_branch_case
        """
        # Define test data based on execution trace
        test_mnemonic = "br"
        test_operands = [MagicMock(type=OperandType.REGISTER, value="x16")]
        test_frame = _mock_lldb.SBFrame()
        test_pc = 4305038944
        test_next_pc = 4305038948
        test_indent = "    "

        with (
            patch.object(self.step_handler, "is_branch_instruction", return_value=True) as mock_is_branch,
            patch.object(
                self.step_handler, "_handle_branch_case", return_value=StepAction.STEP_OVER
            ) as mock_handle_branch,
        ):
            # Call method under test
            result = self.step_handler._determine_step_action(
                mnemonic=test_mnemonic,
                parsed_operands=test_operands,
                frame=test_frame,
                pc=test_pc,
                next_pc=test_next_pc,
                indent=test_indent,
            )

            # Verify branch identification
            mock_is_branch.assert_called_once_with(test_mnemonic)

            # Verify delegation to branch handler
            mock_handle_branch.assert_called_once_with(
                test_mnemonic, test_operands, test_frame, test_pc, test_next_pc, test_indent
            )

            # Verify correct action is returned
            self.assertEqual(result, StepAction.STEP_OVER)

    @patch("tracer.step_handler.lldb")
    def test_determine_step_action_non_branch_non_return(self, _mock_lldb):
        """Test step action determination for non-branch/non-return instructions.

        Verifies that STEP_IN is returned for standard instructions like 'adrp'
        when not in a branch or return context.
        """
        # Setup mock frame
        mock_frame = _mock_lldb.SBFrame()

        # Call method under test
        result = self.step_handler._determine_step_action(
            mnemonic="adrp", parsed_operands=[], frame=mock_frame, pc=4305038936, next_pc=4305038940, indent=""
        )

        # Verify correct action is returned
        self.assertEqual(result, self.step_handler.step_in)

    @patch("tracer.step_handler.lldb")
    def test_determine_step_action_return_instruction(self, _mock_lldb):
        """Test step action determination for return instructions.

        Verifies that STEP_OUT is returned for 'ret' instructions when
        before_get_out flag is set.
        """
        # Setup mock frame and flags
        mock_frame = _mock_lldb.SBFrame()
        self.step_handler.before_get_out = True

        # Call method under test
        result = self.step_handler._determine_step_action(
            mnemonic="ret", parsed_operands=[], frame=mock_frame, pc=4305038936, next_pc=4305038940, indent=""
        )

        # Verify correct action is returned
        self.assertEqual(result, self.step_handler.step_out)
        self.assertFalse(self.step_handler.before_get_out)  # Flag should be reset

    @patch("tracer.step_handler.lldb")
    def test_determine_step_action_branch_instruction_skips(self, _mock_lldb):
        """Test step action determination for branch instructions.

        Verifies that STEP_OVER is returned for branch instructions when
        target address should be skipped.
        """
        # Setup mocks
        mock_frame = _mock_lldb.SBFrame()
        mock_frame.symbol = _mock_lldb.SBSymbol()
        mock_frame.symbol.GetStartAddress().GetLoadAddress.return_value = 0x1000
        mock_frame.symbol.GetEndAddress().GetLoadAddress.return_value = 0x2000

        # Configure address skipping (mocked tracer in setUp)
        self.mock_tracer.modules.should_skip_address.return_value = True
        self.mock_tracer.source_ranges.should_skip_source_address_dynamic.return_value = True

        # Mock necessary internal methods for this path
        with (
            patch.object(self.step_handler, "_get_branch_target", return_value=0x1500),
            patch.object(
                self.step_handler, "_is_internal_branch", return_value=False
            ),  # Return False, so _handle_branch_instruction is called
            patch.object(self.step_handler, "_handle_branch_instruction", return_value=self.step_handler.step_over),
        ):
            # Call method under test
            result = self.step_handler._determine_step_action(
                mnemonic="bl",
                parsed_operands=[MagicMock(type=OperandType.ADDRESS, value="0x1500")],
                frame=mock_frame,
                pc=4305038936,
                next_pc=4305038940,
                indent="",
            )

            # Verify correct action is returned
            self.assertEqual(result, self.step_handler.step_over)


if __name__ == "__main__":
    unittest.main()
