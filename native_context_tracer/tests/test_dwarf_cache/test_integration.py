"""
Integration tests for DWARF cache with SourceHandler
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from native_context_tracer.config import ConfigManager
from native_context_tracer.source_handler import SourceHandler
from tests.test_dwarf_cache.fixtures import (
    MockCompileUnit,
    MockLineEntry,
    TempDirectory,
    create_mock_line_entries,
    create_test_file_with_content,
)


class TestSourceHandlerIntegration(unittest.TestCase):
    """Test cases for SourceHandler integration with DWARF cache"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp(prefix="dwarf_cache_test_")

        # Create mock tracer
        self.mock_tracer = Mock()
        self.mock_tracer.logger = Mock()
        self.mock_tracer.config_manager = Mock()
        self.mock_tracer.config_manager.config = {
            "cache_dir": self.temp_dir,
            "dwarf_cache_enabled": True,
            "dwarf_cache_memory_size": 10,
            "dwarf_cache_disk_size": 1024 * 1024,
        }
        self.mock_tracer.config_manager.get_source_search_paths.return_value = []

        # Create source handler
        self.source_handler = SourceHandler(self.mock_tracer)

    def tearDown(self):
        """Clean up test environment"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch("native_context_tracer.source_handler.lldb")
    def test_get_compile_unit_line_entries_uses_cache(self, mock_lldb):
        """Test that _get_compile_unit_line_entries uses DWARF cache"""
        # Create a temporary file for the module
        test_file = os.path.join(self.temp_dir, "test_module")
        with open(test_file, "w") as f:
            f.write("dummy module content")

        # Setup mock compile unit
        mock_compile_unit = Mock()
        mock_compile_unit.GetFileSpec.return_value.GetDirectory.return_value = "/test/src"
        mock_compile_unit.GetFileSpec.return_value.GetFilename.return_value = "test.cpp"
        mock_compile_unit.GetNumLineEntries.return_value = 100

        # Setup module mock
        mock_module = Mock()
        mock_module.GetUUIDString.return_value = "test-uuid-12345"
        mock_module_file = Mock()
        mock_module_file.fullpath = test_file
        mock_module.GetFileSpec.return_value = mock_module_file
        mock_compile_unit.GetModule.return_value = mock_module

        # Create mock line entries
        mock_entries = []
        for i in range(10):
            entry = Mock()
            entry.IsValid.return_value = True
            entry.GetLine.return_value = i + 1
            entry.GetColumn.return_value = 1

            # Mock file spec with proper string attributes
            file_spec = Mock()
            file_spec.fullpath = "/test/src/test.cpp"
            entry.GetFileSpec.return_value = file_spec

            # Mock start and end addresses
            start_addr = Mock()
            start_addr.IsValid.return_value = False
            entry.GetStartAddress.return_value = start_addr

            end_addr = Mock()
            end_addr.IsValid.return_value = False
            entry.GetEndAddress.return_value = end_addr

            mock_entries.append(entry)

        # Mock GetLineEntryAtIndex to return our entries
        def mock_get_entry(idx):
            if idx < len(mock_entries):
                return mock_entries[idx]
            # Return invalid entry for out of range
            entry = Mock()
            entry.IsValid.return_value = False
            entry.GetLine.return_value = 0
            return entry

        mock_compile_unit.GetLineEntryAtIndex.side_effect = mock_get_entry

        # First call - should cache the results
        entries1 = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)
        self.assertEqual(len(entries1), 10)

        # Verify cache was used
        cache_stats = self.source_handler.get_dwarf_cache_stats()
        self.assertEqual(cache_stats["misses"], 1)

        # Second call - should use cache
        entries2 = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)
        self.assertEqual(len(entries2), 10)

        # Verify cache hit
        cache_stats = self.source_handler.get_dwarf_cache_stats()
        self.assertEqual(cache_stats["hits"], 1)

    def test_dwarf_cache_can_be_disabled(self):
        """Test that DWARF cache can be disabled via config"""
        # Disable cache
        self.mock_tracer.config_manager.config["dwarf_cache_enabled"] = False

        # Create new source handler with disabled cache
        source_handler = SourceHandler(self.mock_tracer)

        # Cache stats should be empty
        stats = source_handler.get_dwarf_cache_stats()
        self.assertEqual(stats, {})

    def test_clear_dwarf_cache(self):
        """Test clearing DWARF cache through source handler"""
        # Create a temporary file for the module
        test_file = os.path.join(self.temp_dir, "test_module")
        with open(test_file, "w") as f:
            f.write("dummy module content")

        # Add something to cache first
        mock_compile_unit = Mock()
        mock_compile_unit.GetFileSpec.return_value.GetDirectory.return_value = "/test/src"
        mock_compile_unit.GetFileSpec.return_value.GetFilename.return_value = "test.cpp"
        mock_compile_unit.GetNumLineEntries.return_value = 0

        # Setup module mock
        mock_module = Mock()
        mock_module.GetUUIDString.return_value = "test-uuid-12345"
        mock_module_file = Mock()
        mock_module_file.fullpath = test_file
        mock_module.GetFileSpec.return_value = mock_module_file
        mock_compile_unit.GetModule.return_value = mock_module

        # This should create a cache entry
        self.source_handler._get_compile_unit_line_entries(mock_compile_unit)

        # Verify cache has entries
        stats = self.source_handler.get_dwarf_cache_stats()
        self.assertGreaterEqual(stats["misses"], 1)

        # Clear cache
        self.source_handler.clear_dwarf_cache()

        # Verify cache is cleared
        stats = self.source_handler.get_dwarf_cache_stats()
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 0)

    @patch("native_context_tracer.source_handler.lldb")
    def test_cache_with_real_line_entries(self, mock_lldb):
        """Test caching with more realistic line entry scenarios"""
        # Mock target for address resolution
        mock_target = Mock()
        mock_lldb.target = mock_target

        # Create a temporary file for the module
        test_file = os.path.join(self.temp_dir, "test_module")
        with open(test_file, "w") as f:
            f.write("dummy module content")

        # Setup compile unit with mixed valid/invalid entries
        mock_compile_unit = Mock()
        mock_compile_unit.GetFileSpec.return_value.GetDirectory.return_value = "/test/src"
        mock_compile_unit.GetFileSpec.return_value.GetFilename.return_value = "test.cpp"
        mock_compile_unit.GetNumLineEntries.return_value = 20

        # Setup module mock
        mock_module = Mock()
        mock_module.GetUUIDString.return_value = "test-uuid-12345"
        mock_module_file = Mock()
        mock_module_file.fullpath = test_file
        mock_module.GetFileSpec.return_value = mock_module_file
        mock_compile_unit.GetModule.return_value = mock_module

        # Create entries with some invalid ones
        mock_entries = []
        for i in range(20):
            entry = Mock()
            if i % 3 == 0:  # Every 3rd entry is invalid
                entry.IsValid.return_value = False
                entry.GetLine.return_value = 0
            else:
                entry.IsValid.return_value = True
                entry.GetLine.return_value = i + 1
                entry.GetColumn.return_value = 1

                # Mock address
                start_addr = Mock()
                start_addr.IsValid.return_value = True
                start_addr.GetLoadAddress.return_value = 0x1000 + i * 4
                entry.GetStartAddress.return_value = start_addr

                end_addr = Mock()
                end_addr.IsValid.return_value = True
                end_addr.GetLoadAddress.return_value = 0x1004 + i * 4
                entry.GetEndAddress.return_value = end_addr

            mock_entries.append(entry)

        # Mock GetLineEntryAtIndex to return our entries or invalid entry for out of range
        def mock_get_entry(idx):
            if idx < len(mock_entries):
                return mock_entries[idx]
            # Return invalid entry for out of range
            entry = Mock()
            entry.IsValid.return_value = False
            entry.GetLine.return_value = 0
            return entry

        mock_compile_unit.GetLineEntryAtIndex.side_effect = mock_get_entry

        # Get entries - should cache only valid ones
        entries = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)

        # Should have filtered out invalid entries
        expected_valid = sum(1 for e in mock_entries if e.IsValid())
        self.assertEqual(len(entries), expected_valid)

    def test_cache_config_options(self):
        """Test various cache configuration options"""
        # Test custom cache sizes
        self.mock_tracer.config_manager.config.update(
            {
                "dwarf_cache_memory_size": 5,
                "dwarf_cache_disk_size": 512 * 1024,  # 512KB
                "cache_dir": os.path.join(self.temp_dir, "custom_cache"),
            }
        )

        # Create source handler with custom config
        source_handler = SourceHandler(self.mock_tracer)

        # Verify custom cache directory is used
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "custom_cache", "dwarf_cache")))

        # Verify memory size limit is respected
        self.assertEqual(source_handler._dwarf_cache.max_memory_size, 5)

    @patch("native_context_tracer.source_handler.lldb")
    def test_large_compile_unit_handling(self, mock_lldb):
        """Test handling of compile units with many line entries"""
        # Mock target
        mock_target = Mock()
        mock_lldb.target = mock_target

        # Create compile unit with many entries
        mock_compile_unit = Mock()
        mock_compile_unit.GetFileSpec.return_value.GetDirectory.return_value = "/test/src"
        mock_compile_unit.GetFileSpec.return_value.GetFilename.return_value = "large_file.cpp"
        mock_compile_unit.GetNumLineEntries.return_value = 100

        # Setup module mock
        mock_module = Mock()
        mock_module.GetUUIDString.return_value = "test-uuid-large-12345"
        test_file = os.path.join(self.temp_dir, "large_test_module")
        with open(test_file, "w") as f:
            f.write("dummy large module content")
        mock_module_file = Mock()
        mock_module_file.fullpath = test_file
        mock_module.GetFileSpec.return_value = mock_module_file
        mock_compile_unit.GetModule.return_value = mock_module

        # Create many mock entries - match the number with GetNumLineEntries
        mock_entries = []
        for i in range(100):
            entry = Mock()
            entry.IsValid.return_value = True
            entry.GetLine.return_value = i + 1
            entry.GetColumn.return_value = 1

            start_addr = Mock()
            start_addr.IsValid.return_value = True
            start_addr.GetLoadAddress.return_value = 0x1000 + i * 4
            entry.GetStartAddress.return_value = start_addr

            end_addr = Mock()
            end_addr.IsValid.return_value = True
            end_addr.GetLoadAddress.return_value = 0x1004 + i * 4
            entry.GetEndAddress.return_value = end_addr

            mock_entries.append(entry)

        # Mock GetLineEntryAtIndex to return our entries
        mock_compile_unit.GetLineEntryAtIndex.side_effect = lambda idx: mock_entries[idx]

        # Should handle large number of entries efficiently
        entries = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)
        self.assertEqual(len(entries), 100)

        # Should be cached for fast retrieval
        cached = self.source_handler._get_compile_unit_line_entries(mock_compile_unit)
        self.assertEqual(len(cached), 100)

        # Verify cache performance
        stats = self.source_handler.get_dwarf_cache_stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)


if __name__ == "__main__":
    unittest.main()
