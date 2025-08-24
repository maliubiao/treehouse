import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = Path(__file__).resolve().parent.parent / "native_context_tracer/src"
sys.path.insert(0, str(project_root))

# Import the module under test and specific functions as needed
import native_context_tracer.tracer_main as tracer_main
from native_context_tracer.tracer_main import parse_args


class TestTracerMainFunction(unittest.TestCase):
    """Test suite for the main function in tracer_main.py"""

    @patch("native_context_tracer.tracer_main.parse_args")
    @patch("native_context_tracer.tracer_main.Tracer")
    def test_main_keyboard_interrupt_during_tracer_start(self, mock_tracer, mock_parse_args):
        """
        Tests that main function properly handles KeyboardInterrupt
        when raised during Tracer.start() execution.
        """
        # Setup mock command-line arguments
        mock_args = MagicMock(spec=argparse.Namespace)
        mock_args.program_path = "dummy_program"
        mock_args.program_args = []
        mock_args.logfile = "dummy.log"
        mock_args.config_file = "dummy_config.yaml"
        mock_args.condition = None
        mock_args.verbose = False
        mock_args.attach_pid = None
        mock_args.dump_modules_for_skip = False
        mock_args.dump_source_files_for_skip = False
        mock_parse_args.return_value = mock_args

        # Configure Tracer mock to raise KeyboardInterrupt on start()
        mock_tracer_instance = MagicMock()
        mock_tracer.return_value = mock_tracer_instance
        mock_tracer_instance.start.side_effect = KeyboardInterrupt

        # Execute test and verify exception
        with self.assertRaises(KeyboardInterrupt):
            tracer_main.main()

        # Verify Tracer was initialized correctly
        mock_tracer.assert_called_once_with(
            program_path="dummy_program",
            program_args=[],
            logfile="dummy.log",
            config_file="dummy_config.yaml",
            attach_pid=None,
        )

        # Verify start() was called
        mock_tracer_instance.start.assert_called_once()


class TestParseArgsFunction(unittest.TestCase):
    """Test suite for the parse_args function in tracer_main.py"""

    def test_parse_args_basic(self):
        """Test basic argument parsing with minimal required arguments.

        This test verifies that the parser correctly handles the minimal required
        arguments as shown in the execution trace.
        """
        test_args = [
            "tracer_main.py",
            "-e",
            "build/basic_program",
            "--logfile",
            "basic.log",
            "--config-file",
            "tracer_config_basic.yaml",
        ]
        with patch.object(sys, "argv", test_args):
            args = parse_args()

            self.assertEqual(args.program_path, "build/basic_program")
            self.assertEqual(args.program_args, [])
            self.assertEqual(args.logfile, "basic.log")
            self.assertEqual(args.config_file, "tracer_config_basic.yaml")
            self.assertIsNone(args.condition)
            self.assertFalse(args.verbose)
            self.assertIsNone(args.attach_pid)
            self.assertFalse(args.dump_modules_for_skip)
            self.assertFalse(args.dump_source_files_for_skip)

    def test_parse_args_with_attach_pid(self):
        """Test argument parsing when attaching to an existing process.

        Verifies that the --attach-pid flag is correctly parsed and other
        required parameters are properly handled.
        """
        test_args = ["tracer_main.py", "-e", "build/program", "--attach-pid", "12345", "--logfile", "attach.log"]
        with patch.object(sys, "argv", test_args):
            args = parse_args()

            self.assertEqual(args.program_path, "build/program")
            self.assertEqual(args.attach_pid, 12345)
            self.assertEqual(args.logfile, "attach.log")
            # Ensure other flags are at their default values if not provided
            self.assertEqual(args.program_args, [])
            self.assertIsNone(args.config_file)
            self.assertIsNone(args.condition)
            self.assertFalse(args.verbose)
            self.assertFalse(args.dump_modules_for_skip)
            self.assertFalse(args.dump_source_files_for_skip)

    def test_parse_args_with_dump_flags(self):
        """Test that dump flags are correctly parsed when present.

        Verifies that both --dump-modules-for-skip and --dump_source_files_for_skip
        flags are properly recognized.
        """
        test_args = ["tracer_main.py", "-e", "build/program", "--dump-modules-for-skip", "--dump_source_files_for_skip"]
        with patch.object(sys, "argv", test_args):
            args = parse_args()

            self.assertTrue(args.dump_modules_for_skip)
            self.assertTrue(args.dump_source_files_for_skip)
            # Ensure other flags are at their default values if not provided
            self.assertEqual(args.program_args, [])
            self.assertIsNone(args.logfile)
            self.assertIsNone(args.config_file)
            self.assertIsNone(args.condition)
            self.assertFalse(args.verbose)
            self.assertIsNone(args.attach_pid)

    def test_parse_args_with_program_args(self):
        """Test parsing of program arguments using the -a/--program-args flag.

        Verifies that repeated -a arguments are correctly collected into a list.
        """
        test_args = ["tracer_main.py", "-e", "build/program", "-a", "arg1", "-a", "arg2", "-a", "arg3"]
        with patch.object(sys, "argv", test_args):
            args = parse_args()

            self.assertEqual(args.program_args, ["arg1", "arg2", "arg3"])
            # Ensure other flags are at their default values if not provided
            self.assertIsNone(args.logfile)
            self.assertIsNone(args.config_file)
            self.assertIsNone(args.condition)
            self.assertFalse(args.verbose)
            self.assertIsNone(args.attach_pid)
            self.assertFalse(args.dump_modules_for_skip)
            self.assertFalse(args.dump_source_files_for_skip)

    def test_parse_args_with_verbose(self):
        """Test that the --verbose flag is correctly parsed."""
        test_args = ["tracer_main.py", "-e", "build/program", "--verbose"]
        with patch.object(sys, "argv", test_args):
            args = parse_args()

            self.assertTrue(args.verbose)
            # Ensure other flags are at their default values if not provided
            self.assertEqual(args.program_args, [])
            self.assertIsNone(args.logfile)
            self.assertIsNone(args.config_file)
            self.assertIsNone(args.condition)
            self.assertIsNone(args.attach_pid)
            self.assertFalse(args.dump_modules_for_skip)
            self.assertFalse(args.dump_source_files_for_skip)


if __name__ == "__main__":
    unittest.main()
