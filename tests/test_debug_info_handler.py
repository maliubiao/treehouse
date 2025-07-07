import logging
import sys
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, call, create_autospec, patch

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = str(Path(__file__).resolve().parent.parent / "debugger/lldb")
print(project_root)
sys.path.insert(0, str(project_root))

# Import the class under test
from tracer.debug_info_handler import DebugInfoHandler

# Import other modules that DebugInfoHandler depends on,
# which may be mocked during tests.
try:
    import lldb
except ImportError:
    # If lldb is not available (e.g., in CI without a lldb build), create a mock.
    # This allows tests that reference lldb objects (e.g., spec=lldb.SBFrame) to still run.
    lldb = MagicMock()

try:
    from op_parser import OperandType
except ImportError:
    # Define a minimal OperandType for environments where op_parser might not be fully available,
    # but tests still need to reference OperandType constants.
    class OperandType:
        REGISTER = 1
        MEMREF = 2
        IMMEDIATE = 3
        ADDRESS = 4


class BaseTestDebugInfoHandler(unittest.TestCase):
    """
    Base test class for DebugInfoHandler tests, handling module-level patching
    of external dependencies like lldb, op_parser, sb_value_printer, and Tracer.
    Also provides a common setUp for a mocked tracer and handler instance.
    """

    @classmethod
    def setUpClass(cls):
        """
        Set up module-level mocks for dependencies imported by `debug_info_handler`.
        This ensures that when `DebugInfoHandler` is instantiated, it uses these mocks.
        """
        cls.mock_lldb = MagicMock()
        cls.mock_op_parser = MagicMock()
        cls.mock_sb_value_printer = MagicMock()

        # Configure mock_lldb to return MagicMock class for its attributes
        # This ensures that SBFrame and SBValue can be used as 'spec' in other MagicMock calls.
        cls.mock_lldb.SBFrame = MagicMock
        cls.mock_lldb.SBValue = MagicMock

        # Patch the imports in `tracer.debug_info_handler` module's namespace.
        cls.lldb_patcher = patch("tracer.debug_info_handler.lldb", cls.mock_lldb)
        cls.sb_value_printer_patcher = patch("tracer.debug_info_handler.sb_value_printer", cls.mock_sb_value_printer)

        # Start all patchers
        cls.lldb_patcher.start()
        cls.sb_value_printer_patcher.start()

    @classmethod
    def tearDownClass(cls):
        """Stop all module-level patchers to clean up."""
        cls.sb_value_printer_patcher.stop()
        cls.lldb_patcher.stop()

    def setUp(self):
        """Set up common mock tracer and handler for individual tests."""
        self.mock_tracer = MagicMock()
        self.mock_logger = MagicMock(spec=logging.Logger)
        self.mock_logger.name = "test_logger"  # Critical for logger.name attribute
        self.mock_tracer.logger = self.mock_logger

        # Ensure target and process are available for memory/register operations,
        # as many methods in DebugInfoHandler rely on them.
        self.mock_tracer.target = MagicMock()
        # Default address byte size for common scenarios like 64-bit systems
        self.mock_tracer.target.GetAddressByteSize.return_value = 8
        self.mock_tracer.process = MagicMock()

        self.handler = DebugInfoHandler(self.mock_tracer)
        # Many new tests reset frame_variables, so add it here for consistency
        self.handler.reset_frame_variables()


class TestDebugInfoHandlerInitialization(BaseTestDebugInfoHandler):
    """
    Test initialization behavior of DebugInfoHandler to ensure it correctly sets up
    required attributes using the provided tracer instance.
    (From Existing Code)
    """

    def test_initialization_sets_correct_attributes(self):
        """
        Verify that DebugInfoHandler correctly initializes its attributes:
        - tracer should reference the provided tracer instance
        - logger should reference the tracer's logger
        - frame_variables should be an empty dictionary
        """
        # This test creates its own mock tracer to control setup precisely.
        mock_tracer_local = MagicMock()
        mock_logger_local = create_autospec(logging.Logger, instance=True)
        mock_logger_local.name = "test_logger"  # Set required name attribute
        mock_tracer_local.logger = mock_logger_local

        # Initialize DebugInfoHandler with the mock tracer
        handler = DebugInfoHandler(mock_tracer_local)

        # Verify attribute assignments
        self.assertIs(
            handler.tracer, mock_tracer_local, "tracer attribute should reference the provided tracer instance"
        )
        self.assertIs(handler.logger, mock_logger_local, "logger attribute should reference the tracer's logger")
        self.assertEqual(handler.frame_variables, {}, "frame_variables should be initialized as an empty dictionary")


class TestDebugInfoHandlerValueAndMemoryCapture(BaseTestDebugInfoHandler):
    """
    Unit tests for DebugInfoHandler's variable dumping and complex value/memory capture methods.
    (From New Test Case(s) Block 1)
    """

    def test_dump_locals_handles_variables_correctly(self):
        """
        Verify dump_locals correctly processes frame variables:
        - Skips invalid variables
        - Handles value formatting
        - Skips duplicates using frame_variables state
        - Filters by declaration line
        """
        # Create mock frame and variables, using the globally mocked lldb
        frame = self.mock_lldb.SBFrame()
        var_valid = MagicMock()
        var_duplicate = MagicMock()
        var_invalid = MagicMock()

        # Configure valid variable
        var_valid.IsValid.return_value = True
        var_valid.GetName.return_value = "valid_var"
        var_valid.GetSummary.return_value = None
        var_valid.GetValue.return_value = "42"
        var_valid.GetType.return_value.GetName.return_value = "int"
        var_valid.GetDeclaration.return_value.line = 50  # Below test line

        # Configure duplicate variable (same name/value as previous state)
        var_duplicate.IsValid.return_value = True
        var_duplicate.GetName.return_value = "duplicate_var"
        var_duplicate.GetSummary.return_value = "duplicate_value"
        var_duplicate.GetDeclaration.return_value.line = 50
        self.handler.frame_variables["duplicate_var"] = "duplicate_value"

        # Configure invalid variable
        var_invalid.IsValid.return_value = False

        # Set frame to return our variables
        frame.GetVariables.return_value = [var_invalid, var_duplicate, var_valid]

        # Set return value directly on the mocked format_sbvalue function within the sb_value_printer mock module
        self.mock_sb_value_printer.format_sbvalue.return_value = "formatted_value"

        # Call method under test
        result = self.handler.dump_locals(frame, line=100)

        # Verify results
        self.assertEqual(len(result), 1)
        self.assertIn("(int)valid_var=formatted_value", result)

        # Verify value formatter was called
        self.mock_sb_value_printer.format_sbvalue.assert_called_once_with(var_valid, shallow_aggregate=True)

        # Verify state was updated
        self.assertEqual(self.handler.frame_variables["valid_var"], "formatted_value")

    def test_capture_register_value_handles_floating_point_registers(self):
        """
        Verify floating point registers are captured with appropriate formatting:
        - Vector registers (v*) get float formatting when possible
        - Double registers (d*) get float formatting
        - Single registers (s*) get float formatting
        - Fallback to hex/string when conversion fails
        """
        # Create mock frame using the globally mocked lldb
        frame = self.mock_lldb.SBFrame()

        # Test vector register (v0)
        reg_val_v = MagicMock()
        reg_val_v.GetData.return_value.GetFloat.return_value = 3.14159
        frame.FindRegister.return_value = reg_val_v
        result = self.handler._capture_register_value(frame, "v0")
        self.assertEqual(result, ["$v0=3.14159"])

        # Test double register (d1)
        reg_val_d = MagicMock()
        reg_val_d.GetValue.return_value = "3.1415926535"
        frame.FindRegister.return_value = reg_val_d
        result = self.handler._capture_register_value(frame, "d1")
        self.assertEqual(result, ["$d1=3.14159"])

        # Test single register (s2) with conversion failure
        reg_val_s = MagicMock()
        reg_val_s.GetValue.return_value = "invalid_float"
        frame.FindRegister.return_value = reg_val_s
        result = self.handler._capture_register_value(frame, "s2")
        self.assertIn("$s2=invalid_float", result[0])

    def test_capture_memory_value_reads_memory_correctly(self):
        """
        Verify memory capture correctly:
        - Builds address from base + offset + index
        - Applies shift operations to index
        - Reads memory with appropriate size
        - Formats output string correctly
        """
        # Create mock frame and register values using the globally mocked lldb
        frame = self.mock_lldb.SBFrame()
        base_reg_val = MagicMock()
        base_reg_val.IsValid.return_value = True
        base_reg_val.unsigned = 0x1000
        frame.FindRegister.return_value = base_reg_val

        # Configure memory reference operand
        memref = {"base_reg": "x1", "offset": "#0x10", "index": "x2", "shift_op": "lsl", "shift_amount": "#2"}

        # Configure index register value
        index_reg_val = MagicMock()
        index_reg_val.IsValid.return_value = True
        index_reg_val.unsigned = 0x4
        # Set side_effect for FindRegister to return multiple mocks in sequence
        frame.FindRegister.side_effect = [base_reg_val, index_reg_val]

        # Configure memory read
        self.mock_tracer.process.ReadUnsignedFromMemory.return_value = 0xDEADBEEF

        # Call method under test
        result = self.handler._capture_memory_value(frame, "ldr", memref)

        # Verify results
        self.assertEqual(len(result), 1)
        # Recalculated expected address: base (0x1000) + offset (0x10) + (index 0x4 << shift 2 = 0x10) = 0x1020
        self.assertIn("[x1 + 0x10 + x2 lsl #2] = [0x1020] = 0xdeadbeef", result[0])

        # Verify memory read parameters: 'ldr' without suffix should read address byte size (8 bytes)
        self.mock_tracer.process.ReadUnsignedFromMemory.assert_called_once_with(
            0x1020,  # Corrected address based on calculation
            8,  # Corrected size based on _get_memory_operand_size logic for 'ldr'
            unittest.mock.ANY,
        )


class TestDebugInfoHandlerCaptureRegisterValuesGeneral(BaseTestDebugInfoHandler):
    """
    Tests for DebugInfoHandler's capture_register_values focusing on general behavior
    like handling empty/invalid operands and distinct register capture.
    (Combines New Test Case(s) Blocks 2, 3, 5, 7, 8, 9)
    """

    def test_capture_register_values_empty_operands_returns_empty_list(self):
        """
        Test that capture_register_values correctly returns an empty list
        when there are no operands to process (empty parsed_operands list).
        """
        # Create a local mock frame for this specific test case.
        mock_frame = MagicMock()

        # Call method with empty operands
        result = self.handler.capture_register_values(frame=mock_frame, mnemonic="nop", parsed_operands=[])

        # Verify empty list is returned
        self.assertEqual(result, [])

    def test_ignores_non_register_memref_operands(self):
        """
        Verify capture_register_values ignores operands that are neither
        REGISTER nor MEMREF types and returns an empty list.
        This tests intended behavior where only register and memory reference
        operands should be processed.
        """
        mock_frame = MagicMock()

        # Create a mock operand that's not REGISTER/MEMREF, using the mocked OperandType
        mock_operand = MagicMock()
        mock_operand.type = OperandType.ADDRESS  # Unhandled operand type

        # Execute
        result = self.handler.capture_register_values(frame=mock_frame, mnemonic="bl", parsed_operands=[mock_operand])

        # Assert
        self.assertEqual(result, [])

    def test_capture_register_values_with_two_registers(self):
        """
        Verify capture_register_values correctly captures values for distinct registers
        and returns formatted output for integer registers.
        """
        mock_frame = MagicMock()

        # Create mock registers
        mock_reg_fp = MagicMock()
        mock_reg_fp.IsValid.return_value = True
        mock_reg_fp.GetValue.return_value = "16fd4f380"

        mock_reg_sp = MagicMock()
        mock_reg_sp.IsValid.return_value = True
        mock_reg_sp.GetValue.return_value = "16fd4f370"

        # Configure frame to return registers based on normalized names 'fp' and 'sp'
        def find_register_side_effect(reg_name):
            if reg_name == "fp":
                return mock_reg_fp
            elif reg_name == "sp":
                return mock_reg_sp
            return MagicMock(IsValid=MagicMock(return_value=False))

        mock_frame.FindRegister.side_effect = find_register_side_effect

        # Create operands using the mocked OperandType
        operand1 = MagicMock()
        operand1.type = OperandType.REGISTER
        operand1.value = "x29"  # Should normalize to 'fp'

        operand2 = MagicMock()
        operand2.type = OperandType.REGISTER
        operand2.value = "sp"

        operands = [operand1, operand2]

        # Call method under test
        result = self.handler.capture_register_values(mock_frame, "add", operands)

        # Verify results
        expected = ["$fp=0x16fd4f380", "$sp=0x16fd4f370"]
        self.assertEqual(result, expected)

        # Verify register lookups
        mock_frame.FindRegister.assert_any_call("fp")
        mock_frame.FindRegister.assert_any_call("sp")
        self.assertEqual(mock_frame.FindRegister.call_count, 2)

    def test_capture_register_values_with_register_operands(self):
        """
        Verify capture_register_values processes register operands correctly,
        skips duplicates, and ignores non-register operands.
        """
        mock_frame = MagicMock()
        # Using namedtuple for mock operand structure for clarity
        Operand = namedtuple("Operand", ["type", "value"])
        operands = [
            Operand(type=OperandType.REGISTER, value="w8"),
            Operand(type=OperandType.REGISTER, value="w8"),  # Duplicate
            Operand(type=OperandType.IMMEDIATE, value="#0"),  # Non-register
        ]

        # Configure expected behavior for helper method by patching the instance's method
        with patch.object(self.handler, "_capture_register_value", return_value=["$w8=0xffffff9c"]) as mock_capture_reg:
            result = self.handler.capture_register_values(frame=mock_frame, mnemonic="subs", parsed_operands=operands)

            # Verify register capture was called correctly (only once for the distinct register)
            mock_capture_reg.assert_called_once_with(mock_frame, "w8")

            # Verify result contains expected register value
            self.assertEqual(result, ["$w8=0xffffff9c"])

    def test_capture_register_values_collects_distinct_registers(self):
        """
        Verify capture_register_values correctly processes register operands,
        skips duplicates, and returns formatted register values.
        """
        mock_frame = MagicMock()

        # Create mock operands using the mocked OperandType
        operand1 = MagicMock()
        operand1.type = OperandType.REGISTER
        operand1.value = "x9"

        operand2 = MagicMock()
        operand2.type = OperandType.REGISTER
        operand2.value = "sp"

        parsed_operands = [operand1, operand2]

        # Mock helper method to return expected values, patching the instance's method
        with patch.object(self.handler, "_capture_register_value") as mock_capture:
            mock_capture.side_effect = [
                ["$x9=0x16fd4f370"],  # First call return value for 'x9'
                ["$sp=0x16fd4f370"],  # Second call return value for 'sp'
            ]

            # Call the method under test
            result = self.handler.capture_register_values(mock_frame, "mov", parsed_operands)

        # Verify results match trace output
        self.assertEqual(result, ["$x9=0x16fd4f370", "$sp=0x16fd4f370"])

        # Verify helper was called with correct arguments
        mock_capture.assert_has_calls([call(mock_frame, "x9"), call(mock_frame, "sp")])

    def test_capture_register_values_with_register_operand(self):
        """
        Test capture_register_values correctly captures register values
        for REGISTER operands.
        """
        mock_frame = MagicMock()
        mock_reg_val = MagicMock()
        mock_reg_val.IsValid.return_value = True
        mock_reg_val.GetValue.return_value = "0x1000b3000"
        mock_frame.FindRegister.return_value = mock_reg_val

        # Create operand structure matching trace input using namedtuple and mocked OperandType
        Operand = namedtuple("Operand", ["type", "value"])
        operand = Operand(type=OperandType.REGISTER, value="x0")
        parsed_operands = [operand]

        # Execute method under test
        result = self.handler.capture_register_values(
            frame=mock_frame, mnemonic="adrp", parsed_operands=parsed_operands
        )

        # Verify results match trace output
        self.assertEqual(result, ["$x0=0x1000b3000"])

        # Verify register lookup was called correctly
        mock_frame.FindRegister.assert_called_once_with("x0")


class TestDebugInfoHandlerCaptureRegisterValuesSpecificInstructions(BaseTestDebugInfoHandler):
    """
    Tests for DebugInfoHandler's capture_register_values focusing on specific
    instruction types like stp, ldr, and br.
    (Combines New Test Case(s) Blocks 4, 10, 11)
    """

    def test_capture_register_values_stp_instruction(self):
        """
        Verify capture_register_values correctly processes registers and memory references
        for an 'stp' instruction, including register normalization and memory read operations.
        """
        mock_frame = MagicMock()

        # Setup mock registers
        mock_fp = MagicMock()
        mock_fp.value = "0x16fd4f490"
        mock_fp.unsigned = 0x16FD4F490
        mock_fp.IsValid.return_value = True
        mock_fp.GetValue.return_value = mock_fp.value

        mock_lr = MagicMock()
        mock_lr.value = "0x1000b2404"
        mock_lr.unsigned = 0x1000B2404
        mock_lr.IsValid.return_value = True
        mock_lr.GetValue.return_value = mock_lr.value

        mock_sp = MagicMock()
        mock_sp.value = "0x16fd4f370"
        mock_sp.unsigned = 0x16FD4F370
        mock_sp.IsValid.return_value = True

        # Configure frame.FindRegister to return appropriate registers
        def find_register_side_effect(reg_name):
            if reg_name == "fp":
                return mock_fp
            elif reg_name == "lr":
                return mock_lr
            elif reg_name == "sp":
                return mock_sp
            return MagicMock(IsValid=MagicMock(return_value=False))

        mock_frame.FindRegister.side_effect = find_register_side_effect

        # Setup operands using namedtuple and mocked OperandType
        Operand = namedtuple("Operand", ["type", "value"])
        operands = [
            Operand(OperandType.REGISTER, "x29"),  # Should normalize to fp
            Operand(OperandType.REGISTER, "x30"),  # Should normalize to lr
            Operand(OperandType.MEMREF, {"base_reg": "sp", "offset": "#0x10"}),
        ]

        # Mock memory read operation
        self.mock_tracer.process.ReadUnsignedFromMemory.return_value = 0x8

        # Mock lldb.SBError to simulate successful read (via cls.mock_lldb)
        self.mock_lldb.SBError.return_value.Success.return_value = True

        # Execute the method under test
        result = self.handler.capture_register_values(frame=mock_frame, mnemonic="stp", parsed_operands=operands)

        # Verify results
        expected_addr = mock_sp.unsigned + 0x10  # 0x16fd4f370 + 0x10 = 0x16fd4f380
        expected = ["$fp=0x16fd4f490", "$lr=0x1000b2404", f"[sp + 0x10] = [0x{expected_addr:x}] = 0x8"]
        self.assertEqual(result, expected)

        # Verify memory read was called with correct address and size
        self.mock_tracer.process.ReadUnsignedFromMemory.assert_called_once_with(
            expected_addr,  # sp + 0x10
            8,  # size for 'stp' determined by _get_memory_operand_size
            self.mock_lldb.SBError.return_value,  # The specific mock error object
        )

    def test_capture_register_values_ldr_memref_operand(self):
        """
        Test capture_register_values correctly handles 'ldr' instruction with MEMREF operand.
        Verifies memory value capture when base register is valid and memory read succeeds.
        """
        mock_frame = MagicMock()
        mock_register = MagicMock()
        mock_register.IsValid.return_value = True
        mock_register.unsigned = 0x1000B4000  # Base register value
        mock_frame.FindRegister.return_value = mock_register

        # Setup mock error handling via the patched lldb module
        self.mock_lldb.SBError.return_value.Success.return_value = True

        # Mock operands - first operand skipped (ldr behavior), second is MEMREF
        operand1 = MagicMock()  # Represents the destination register, not captured by trace
        operand2 = MagicMock()
        operand2.type = OperandType.MEMREF  # Uses mocked OperandType
        operand2.value = {"base_reg": "x16"}

        # Mock memory read result
        self.mock_tracer.process.ReadUnsignedFromMemory.return_value = 0x18758FB28

        # Call method under test
        result = self.handler.capture_register_values(
            frame=mock_frame, mnemonic="ldr", parsed_operands=[operand1, operand2]
        )

        # Verify memory read was called correctly
        self.mock_tracer.process.ReadUnsignedFromMemory.assert_called_once_with(
            0x1000B4000,
            8,  # Size for 'ldr' determined by _get_memory_operand_size (64-bit target default)
            self.mock_lldb.SBError.return_value,
        )

        # Verify result matches expected output
        self.assertEqual(result, ["[x16] = [0x1000b4000] = 0x18758fb28"])

    def test_capture_register_values_br_with_register_operand(self):
        """
        Test that capture_register_values correctly captures and formats a register operand
        for a 'br' instruction, returning the expected hex-formatted register value.
        """
        mock_frame = MagicMock()
        mock_reg_val = MagicMock()
        mock_reg_val.IsValid.return_value = True
        mock_reg_val.GetValue.return_value = "18758fb28"  # Hexadecimal value without prefix

        # Configure frame to return mock register
        mock_frame.FindRegister.return_value = mock_reg_val

        # Create operand using namedtuple and mocked OperandType
        Operand = namedtuple("Operand", ["type", "value"])
        operand = Operand(type=OperandType.REGISTER, value="x16")

        # Call method under test
        result = self.handler.capture_register_values(frame=mock_frame, mnemonic="br", parsed_operands=[operand])

        # Verify result
        expected = ["$x16=0x18758fb28"]
        self.assertEqual(result, expected)


class TestDebugInfoHandlerCaptureRegisterValuesMixedOperands(BaseTestDebugInfoHandler):
    """
    Tests for DebugInfoHandler's capture_register_values focusing on scenarios
    with mixed or invalid operand types.
    (From New Test Case(s) Block 6)
    """

    def test_capture_register_values_processes_mixed_operands_correctly(self):
        """
        Test that capture_register_values correctly handles:
        - A register operand that returns no value (invalid)
        - A memory operand that returns a valid value
        Verifies the function collects memory values while skipping invalid registers.
        """
        mock_frame = MagicMock()

        # Define operands: one register (invalid) and one memory ref using namedtuple and mocked OperandType
        Operand = namedtuple("Operand", ["type", "value"])
        operands = [
            Operand(OperandType.REGISTER, "wzr"),
            Operand(OperandType.MEMREF, {"base_reg": "x29", "offset": "#-0x4"}),
        ]

        # Mock helper methods by patching the instance's methods
        with (
            patch.object(self.handler, "_capture_register_value", return_value=[]) as mock_capture_reg,
            patch.object(
                self.handler,
                "_capture_memory_value",
                return_value=["[x29 + -0x4] = [0x16fd4f37c] = 0x6fd4f49000000000"],
            ) as mock_capture_mem,
        ):
            # Call method under test
            result = self.handler.capture_register_values(frame=mock_frame, mnemonic="stur", parsed_operands=operands)

        # Verify results
        expected = ["[x29 + -0x4] = [0x16fd4f37c] = 0x6fd4f49000000000"]
        self.assertEqual(result, expected)

        # Verify helper calls
        mock_capture_reg.assert_called_once_with(mock_frame, "wzr")
        mock_capture_mem.assert_called_once_with(mock_frame, "stur", {"base_reg": "x29", "offset": "#-0x4"})


class TestDebugInfoHandlerRegisterHelpers(BaseTestDebugInfoHandler):
    """
    Unit tests for DebugInfoHandler's private register-related helper methods:
    _capture_register_value and _normalize_register_name.
    (Combines New Test Case(s) Blocks 12, 13, 14, 15, 16)
    """

    def test_capture_register_value_integer_register(self):
        """
        Verify integer register values are correctly captured and formatted as hex.
        Tests the scenario where:
        1. Register name 'x29' is normalized to 'fp'
        2. Register value is valid and in hex string format
        3. Integer formatting branch is executed
        4. Result is correctly formatted as a hex value
        """
        mock_frame = MagicMock()
        mock_reg_val = MagicMock()
        mock_reg_val.IsValid.return_value = True
        mock_reg_val.GetValue.return_value = "16fd4f490"  # Hex value without '0x' prefix

        # Configure frame to return mock register
        mock_frame.FindRegister.return_value = mock_reg_val

        # Execute method under test
        result = self.handler._capture_register_value(mock_frame, "x29")

        # Verify results
        self.assertEqual(result, ["$fp=0x16fd4f490"])
        mock_frame.FindRegister.assert_called_once_with("fp")

    def test_capture_register_value_returns_empty_list_for_invalid_register(self):
        """
        Verify that _capture_register_value returns an empty list when
        frame.FindRegister returns an invalid register value.
        This tests the early exit condition where the register doesn't exist
        or is invalid.
        """
        mock_frame = MagicMock()
        mock_reg_val = MagicMock()
        mock_reg_val.IsValid.return_value = False
        mock_frame.FindRegister.return_value = mock_reg_val

        # Call method under test
        result = self.handler._capture_register_value(mock_frame, "wzr")

        # Assertions
        self.assertEqual(result, [])
        mock_frame.FindRegister.assert_called_once_with("wzr")
        mock_reg_val.IsValid.assert_called_once()

    def test_normalize_register_name_mappings_comprehensive(self):
        """
        Test register name normalization under various conditions, combining
        tests from Blocks 14, 15, and 16.
        Verifies:
        - Special registers x29/x30 are mapped to fp/lr
        - Other register names remain unchanged
        - Case sensitivity is maintained (no normalization for 'X29' or 'X30')
        """
        test_cases = [
            # Special register mappings
            ("x29", "fp"),
            ("x30", "lr"),
            # Unchanged register names
            ("x0", "x0"),
            ("x1", "x1"),
            ("sp", "sp"),
            ("pc", "pc"),
            ("v0", "v0"),
            ("d1", "d1"),
            ("s2", "s2"),
            ("w0", "w0"),
            # Case sensitivity checks (names are not normalized if case doesn't match exactly)
            ("X29", "X29"),
            ("X30", "X30"),
            ("Sp", "Sp"),
            ("Lr", "Lr"),
        ]

        for reg_name, expected in test_cases:
            with self.subTest(reg_name=reg_name, expected=expected):
                result = self.handler._normalize_register_name(reg_name)
                self.assertEqual(result, expected)


class TestDebugInfoHandlerMemoryHelpers(BaseTestDebugInfoHandler):
    """
    Unit tests for DebugInfoHandler's private memory-related helper methods:
    _capture_memory_value, _parse_offset, and _build_expression_string.
    (Combines New Test Case(s) Blocks 17, 18, 19, 20, 21)
    """

    def test_capture_memory_value_simple_memory_read(self):
        """
        Verify _capture_memory_value correctly reads and formats a memory value
        when provided with valid base register and offset without index register.
        """
        mock_frame = MagicMock()
        mock_register = MagicMock()
        mock_register.IsValid.return_value = True
        mock_register.unsigned = 0x16FD4F370  # Base address value
        mock_frame.FindRegister.return_value = mock_register

        # Configure process memory read to return success
        self.mock_tracer.process.ReadUnsignedFromMemory.return_value = 0x8

        # Prepare memref dictionary based on trace
        memref = {"base_reg": "sp", "offset": "#0x10"}

        # Execute the method under test
        result = self.handler._capture_memory_value(mock_frame, "stp", memref)

        # Verify results
        expected_addr = 0x16FD4F370 + 0x10  # Base + offset = 0x16fd4f380
        expected_output = [f"[sp + 0x10] = [0x{expected_addr:x}] = 0x8"]
        self.assertEqual(result, expected_output)

        # Verify register lookup
        mock_frame.FindRegister.assert_called_once_with("sp")

        # Verify memory read parameters (size for 'stp' is 8 bytes)
        self.mock_tracer.process.ReadUnsignedFromMemory.assert_called_once_with(expected_addr, 8, unittest.mock.ANY)


class TestDebugInfoHandlerMemoryHelpers(BaseTestDebugInfoHandler):
    """
    Unit tests for DebugInfoHandler's private memory-related helper methods:
    _capture_memory_value, _parse_offset, and _build_expression_string.
    (Combines New Test Case(s) Blocks 17, 18, 19, 20, 21)
    """

    def test_capture_memory_value_simple_memory_read(self):
        """
        Verify _capture_memory_value correctly reads and formats a memory value
        when provided with valid base register and offset without index register.
        """
        mock_frame = MagicMock()
        mock_register = MagicMock()
        mock_register.IsValid.return_value = True
        mock_register.unsigned = 0x16FD4F370  # Base address value
        mock_frame.FindRegister.return_value = mock_register

        # Configure process memory read to return success
        self.mock_tracer.process.ReadUnsignedFromMemory.return_value = 0x8

        # Prepare memref dictionary based on trace
        memref = {"base_reg": "sp", "offset": "#0x10"}

        # Execute the method under test
        result = self.handler._capture_memory_value(mock_frame, "stp", memref)

        # Verify results
        expected_addr = 0x16FD4F370 + 0x10  # Base + offset = 0x16fd4f380
        expected_output = [f"[sp + 0x10] = [0x{expected_addr:x}] = 0x8"]
        self.assertEqual(result, expected_output)

        # Verify register lookup
        mock_frame.FindRegister.assert_called_once_with("sp")

        # Verify memory read parameters (size for 'stp' is 8 bytes)
        self.mock_tracer.process.ReadUnsignedFromMemory.assert_called_once_with(expected_addr, 8, unittest.mock.ANY)

    def test_build_expression_string_comprehensive(self):
        """
        Verify _build_expression_string correctly formats memory expressions under various conditions,
        combining tests from Blocks 20 and 21.
        """
        test_cases = [
            # (description, base_reg, offset_value, index_reg, memref, expected)
            ("offset_only", "sp", 0x10, None, {"base_reg": "sp"}, "[sp + 0x10]"),
            ("no_offset", "x0", 0x0, None, {"base_reg": "x0"}, "[x0]"),
            ("negative_offset_short", "fp", -0x8, None, {"base_reg": "fp"}, "[fp - 0x8]"),
            (
                "negative_offset_long",
                "x9",
                -0x10,
                None,
                {"base_reg": "x9"},
                "[x9 - 0x10]",
            ),
            ("index_only", "x1", 0x0, "x2", {"base_reg": "x1", "index": "x2"}, "[x1 + x2]"),
            ("offset_and_index", "x3", 0x20, "x4", {"base_reg": "x3", "index": "x4"}, "[x3 + 0x20 + x4]"),
            (
                "index_with_lsl_shift_explicit_index",
                "x5",
                0x0,
                "x6",
                {"base_reg": "x5", "index": "x6", "shift_op": "lsl", "shift_amount": "#2"},
                "[x5 + x6 lsl #2]",
            ),
            (
                "index_with_lsl_shift_implicit_index",
                "x9",
                0x0,
                "x1",
                {"base_reg": "x9", "shift_op": "lsl", "shift_amount": "#2"},
                "[x9 + x1 lsl #2]",
            ),
            (
                "all_components_lsr",
                "x7",
                0x10,
                "x8",
                {"base_reg": "x7", "index": "x8", "shift_op": "lsr", "shift_amount": "#4"},
                "[x7 + 0x10 + x8 lsr #4]",
            ),
        ]

        for desc, base_reg, offset_value, index_reg, memref, expected in test_cases:
            with self.subTest(desc=desc):
                result = self.handler._build_expression_string(base_reg, offset_value, index_reg, memref)
                self.assertEqual(result, expected)


class TestDebugInfoHandlerMemoryOperandSize(BaseTestDebugInfoHandler):
    """
    Unit tests for DebugInfoHandler's _get_memory_operand_size helper method.
    (From New Test Case(s) Block 22)
    """

    def test_get_memory_operand_size_returns_correct_values(self):
        """
        Verify _get_memory_operand_size returns the correct byte size for different
        mnemonic suffixes and falls back to address byte size when no suffix matches.
        """
        test_cases = [
            # Suffix-based cases
            ("ldrb", 1),
            ("strb", 1),
            ("ldrh", 2),
            ("strh", 2),
            ("ldrw", 4),
            ("strw", 4),
            # No suffix cases (fall back to self.tracer_mock.target.GetAddressByteSize.return_value = 8)
            ("stp", 8),
            ("ldp", 8),
            ("mov", 8),  # 'mov' doesn't typically have memory operands, but tests fallback
            ("ldr", 8),  # 'ldr' without suffix implies target address size
            ("", 8),  # Empty mnemonic should also fall back
        ]

        for mnemonic, expected_size in test_cases:
            with self.subTest(mnemonic=mnemonic, expected_size=expected_size):
                # self.handler is configured with mock_tracer.target.GetAddressByteSize.return_value = 8
                result = self.handler._get_memory_operand_size(mnemonic)
                self.assertEqual(result, expected_size)


if __name__ == "__main__":
    unittest.main()
