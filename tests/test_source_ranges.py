import fnmatch  # Imported because it's patched in tracer.source_ranges module
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the project root to sys.path to allow for module imports.
# This is dynamically calculated based on the test file's location.
project_root = str(Path(__file__).resolve().parent.parent / "native_context_tracer/src")
print(project_root)
sys.path.insert(0, str(project_root))

from native_context_tracer import SourceRangeManager


# A base class to encapsulate common setup for SourceRangeManager tests.
# This promotes reusability and avoids redundant mock setup in each test.
class BaseTestSourceRangeManager(unittest.TestCase):
    def setUp(self):
        self.mock_target = MagicMock()
        self.mock_logger = MagicMock()
        self.mock_config_manager = MagicMock()

        def mock_get_config(key, default=None):
            if key == "skip_source_files":
                return []
            if key == "cache_dir":
                return "test_cache_dir"
            if key == "source_files_list_file":
                return "source_files.yaml"
            if key == "skip_modules":
                return []
            return default

        self.mock_config_manager.config.get.side_effect = mock_get_config

    def _create_manager(self):
        """
        Helper method to instantiate SourceRangeManager with the common mocks.
        """
        return SourceRangeManager(
            target=self.mock_target, logger=self.mock_logger, config_manager=self.mock_config_manager
        )


class TestSourceRangeManagerInitialization(BaseTestSourceRangeManager):
    def test_initialization_sets_attributes_and_initializes_dependencies(self):
        """
        Verify SourceRangeManager correctly initializes its attributes and dependencies
        from constructor arguments and configuration.
        - Sets core attributes from constructor arguments.
        - Retrieves skip_source_files from config manager.
        - Initializes Console and SourceCacheManager dependencies.
        - Initializes cache dictionaries to empty.
        """
        # Configure config manager to return specific skip patterns for this test
        mock_skip_source_files = ["*skip_me*", "ignore_this*"]

        # Patch dependencies (Console and SourceCacheManager) where they are used within
        # the tracer.source_ranges module's namespace.
        # Also, patch the 'get' method on the mocked config_manager.config object.
        with (
            patch("native_context_tracer.source_ranges.Console") as MockConsole,
            patch("native_context_tracer.source_ranges.SourceCacheManager") as MockCacheManager,
            patch.object(self.mock_config_manager.config, "get") as MockConfigGet,
        ):
            # Define a new side_effect for MockConfigGet within this test's scope
            # to return the desired mock_skip_source_files.
            def test_specific_get_config(key, default=None):
                if key == "skip_source_files":
                    return mock_skip_source_files
                # For any other config keys that might be queried during initialization
                # (though based on tracer, only 'skip_source_files' is),
                # return the default value passed to config.get.
                return default

            MockConfigGet.side_effect = test_specific_get_config

            # Create mock instances that the patched classes will return when called
            mock_console_instance = MockConsole.return_value
            mock_cache_manager_instance = MockCacheManager.return_value

            # Initialize SourceRangeManager using the helper
            manager = self._create_manager()

            # Verify core attribute assignments
            self.assertIs(manager._target, self.mock_target)
            self.assertIs(manager.logger, self.mock_logger)
            self.assertIs(manager.config_manager, self.mock_config_manager)

            # Verify configuration retrieval and assignment
            # Now, MockConfigGet (which is the patched self.mock_config_manager.config.get)
            # should have been called and returned the expected value.
            MockConfigGet.assert_called_once_with("skip_source_files", [])
            self.assertEqual(manager._skip_source_files, mock_skip_source_files)

            # Verify dependency initialization and assignment
            MockConsole.assert_called_once()
            self.assertIs(manager._console, mock_console_instance)

            MockCacheManager.assert_called_once_with(self.mock_target, self.mock_logger, self.mock_config_manager)
            self.assertIs(manager.cache_manager, mock_cache_manager_instance)

            # Verify internal cache dictionaries are initialized as empty
            self.assertEqual(manager._address_decision_cache, {})
            self.assertEqual(manager._file_skip_cache, {})


class TestSourceRangeManagerFileSkipping(BaseTestSourceRangeManager):
    def test_should_skip_file_cache_miss_no_matching_patterns(self):
        """
        Test `should_skip_source_file_by_path` when the file is not in the cache and
        no skip patterns match. It should return False and cache this result.
        """
        # Configure config manager with non-matching patterns for this test scenario
        self.mock_config_manager.config.get.return_value = ["*.txt", "*.log"]

        manager = self._create_manager()
        file_path = "/path/to/file.c"

        # Execute the method under test
        result = manager.should_skip_source_file_by_path(file_path)

        # Verify the outcome and cache state
        self.assertFalse(result, "File should not be skipped when no patterns match")
        self.assertIn(file_path, manager._file_skip_cache, "File path should be cached")
        self.assertFalse(manager._file_skip_cache[file_path], "Cache should store False for non-skipped file")
        self.assertEqual(len(manager._file_skip_cache), 1, "Cache should have exactly one entry")

    def test_should_skip_file_cache_hit_returns_cached_decision(self):
        """
        Test `should_skip_source_file_by_path` when the file path is already in the cache.
        It should return the cached decision without re-evaluating skip patterns.
        """
        manager = self._create_manager()
        file_path = "/path/to/file.c"
        # Pre-populate the cache to simulate a cache hit
        manager._file_skip_cache = {file_path: False}

        # Patch fnmatch.fnmatch to ensure it's not called, proving cache was used
        with patch("native_context_tracer.source_ranges.fnmatch.fnmatch") as mock_fnmatch:
            # Execute the method under test
            result = manager.should_skip_source_file_by_path(file_path)

            # Verify no pattern matching occurred due to cache hit
            mock_fnmatch.assert_not_called()
            # Verify the cached value was returned
            self.assertFalse(result, "Should return the cached False value")
            # Verify the cache remains unchanged
            self.assertEqual(len(manager._file_skip_cache), 1, "Cache should remain unchanged")


class TestSourceRangeManagerAddressSkipping(BaseTestSourceRangeManager):
    def test_should_skip_source_address_dynamic_cache_miss_invalid_line_entry_returns_false(self):
        """
        Test `should_skip_source_address_dynamic` when an address is not cached,
        and `ResolveLoadAddress` returns a valid SBAddress but with an invalid line entry (None).
        The function should return False and update the cache accordingly.
        """
        # Ensure skip_source_files is empty for this test to not interfere with file skipping logic
        self.mock_config_manager.config.get.return_value = []

        # Create a mock SBAddress object simulating a valid address but no line entry
        mock_sb_addr = MagicMock()
        mock_sb_addr.IsValid.return_value = True
        mock_sb_addr.GetLineEntry.return_value = None  # Simulate an invalid line entry

        # Configure the target mock to return our mock SBAddress for any resolved address
        self.mock_target.ResolveLoadAddress.return_value = mock_sb_addr

        manager = self._create_manager()
        manager._address_decision_cache = {}  # Ensure cache is empty initially

        # Test address
        address = 0x100002000  # Example address

        # Execute the method under test
        result = manager.should_skip_source_address_dynamic(address)

        # Assertions
        self.assertFalse(result, "Should not skip if line entry is invalid")
        self.assertIn(address, manager._address_decision_cache, "Address should be cached")
        self.assertFalse(manager._address_decision_cache[address], "Cache should store False for this address")
        self.mock_target.ResolveLoadAddress.assert_called_once_with(address)
        mock_sb_addr.GetLineEntry.assert_called_once()

    def test_should_skip_source_address_dynamic_cache_hit_returns_cached_value(self):
        """
        Test `should_skip_source_address_dynamic` when the address already exists in the cache.
        It should return the cached value directly without further processing or calls to LLDB.
        """
        manager = self._create_manager()
        address = 0x100003000  # Example address
        # Pre-populate the cache with a known decision
        manager._address_decision_cache = {address: False}

        # Execute the method under test
        result = manager.should_skip_source_address_dynamic(address)

        # Assertions
        self.assertFalse(result, "Should return the cached False value")
        # Verify that ResolveLoadAddress was NOT called, indicating cache hit
        self.mock_target.ResolveLoadAddress.assert_not_called()
        # Verify the cache state remains unchanged
        self.assertEqual(len(manager._address_decision_cache), 1, "Cache should remain unchanged")


if __name__ == "__main__":
    unittest.main()
