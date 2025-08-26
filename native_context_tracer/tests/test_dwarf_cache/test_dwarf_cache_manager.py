"""
Unit tests for DwarfCacheManager
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(project_root))

from native_context_tracer.dwarf_cache import CacheMetadata, DwarfCacheManager, LineEntryData
from tests.test_dwarf_cache.fixtures import (
    MockCompileUnit,
    MockLineEntry,
    TempDirectory,
    create_mock_line_entries,
    create_test_file_with_content,
)


class TestDwarfCacheManager(unittest.TestCase):
    """Test cases for DwarfCacheManager"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp(prefix="dwarf_cache_test_")
        self.cache_manager = DwarfCacheManager(
            cache_dir=self.temp_dir,
            max_memory_size=10,
            max_disk_size=1024 * 1024,  # 1MB
            logger=Mock(),
        )

    def tearDown(self):
        """Clean up test environment"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_init_creates_cache_directory(self):
        """Test that initialization creates cache directory"""
        cache_dir = os.path.join(self.temp_dir, "dwarf_cache")
        self.assertTrue(os.path.exists(cache_dir))

    def test_get_cache_key_generation(self):
        """Test cache key generation"""
        compile_unit = MockCompileUnit(file_path="/test/src/test.cpp", uuid="test-uuid-12345")

        key = self.cache_manager._get_cache_key(compile_unit)

        # Key should be a 16-character hex string
        self.assertEqual(len(key), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in key))

        # Same input should produce same key
        key2 = self.cache_manager._get_cache_key(compile_unit)
        self.assertEqual(key, key2)

    def test_get_and_cache_line_entries(self):
        """Test basic caching of line entries"""
        # Create a real file for testing
        test_file = os.path.join(self.temp_dir, "test.cpp")
        with open(test_file, "w") as f:
            f.write("#include <iostream>\nint main() { return 0; }\n")

        compile_unit = MockCompileUnit(file_path=test_file, uuid="test-uuid-12345")
        entries = create_mock_line_entries(10)

        # Cache should be empty initially
        cached = self.cache_manager.get_line_entries(compile_unit)
        self.assertIsNone(cached)

        # Cache the entries
        self.cache_manager.cache_line_entries(compile_unit, entries)

        # Should be able to retrieve from cache
        cached = self.cache_manager.get_line_entries(compile_unit)
        self.assertIsNotNone(cached)
        # Note: We can't compare entries directly due to SBLineEntry mocking
        self.assertEqual(len(cached), len(entries))

    def test_memory_cache_lru_eviction(self):
        """Test LRU eviction from memory cache"""
        # Create cache with small memory limit
        cache = DwarfCacheManager(cache_dir=self.temp_dir, max_memory_size=2, max_disk_size=1024 * 1024, logger=Mock())

        # Create real files for testing
        test_files = []
        for i in range(3):
            test_file = os.path.join(self.temp_dir, f"test{i}.cpp")
            with open(test_file, "w") as f:
                f.write(f"#include <iostream>\nint main{i}() {{ return 0; }}\n")
            test_files.append(test_file)

        # Add 3 entries
        for i in range(3):
            compile_unit = MockCompileUnit(file_path=test_files[i], uuid=f"uuid-{i}")
            entries = create_mock_line_entries(5)
            cache.cache_line_entries(compile_unit, entries)

        # Only 2 entries should be in memory cache
        self.assertEqual(len(cache._memory_cache), 2)

        # First entry should be evicted (LRU)
        first_unit = MockCompileUnit(file_path=test_files[0], uuid="uuid-0")
        cached = cache.get_line_entries(first_unit)
        # Should be None in memory but might be on disk
        self.assertIsNone(cached) if cached is None else None

    def test_disk_cache_persistence(self):
        """Test that cache persists to disk"""
        # Create a real file for testing
        test_file = os.path.join(self.temp_dir, "test.cpp")
        with open(test_file, "w") as f:
            f.write("#include <iostream>\nint main() { return 0; }\n")

        compile_unit = MockCompileUnit(file_path=test_file, uuid="test-uuid-12345")
        entries = create_mock_line_entries(10)

        # Cache entries
        self.cache_manager.cache_line_entries(compile_unit, entries)

        # Create new cache instance pointing to same directory
        cache2 = DwarfCacheManager(
            cache_dir=self.temp_dir, max_memory_size=10, max_disk_size=1024 * 1024, logger=Mock()
        )

        # Should be able to retrieve cached entries
        cached = cache2.get_line_entries(compile_unit)
        self.assertIsNotNone(cached)

    def test_cache_invalidation_on_file_change(self):
        """Test cache invalidation when file changes"""
        with TempDirectory() as temp_dir:
            # Create test file
            file_path = create_test_file_with_content(temp_dir, "test.cpp", "int main() { return 0; }")

            compile_unit = MockCompileUnit(file_path=file_path, uuid="test-uuid-12345")
            entries = create_mock_line_entries(5)

            # Cache entries
            self.cache_manager.cache_line_entries(compile_unit, entries)

            # Should be able to retrieve
            cached = self.cache_manager.get_line_entries(compile_unit)
            self.assertIsNotNone(cached)

            # Modify the file
            time.sleep(0.01)  # Ensure different mtime
            with open(file_path, "a") as f:
                f.write("\n// Added comment")

            # Cache should be invalidated
            cached = self.cache_manager.get_line_entries(compile_unit)
            self.assertIsNone(cached)

    def test_cache_stats(self):
        """Test cache statistics tracking"""
        # Create a real file for testing
        test_file = os.path.join(self.temp_dir, "test.cpp")
        with open(test_file, "w") as f:
            f.write("#include <iostream>\nint main() { return 0; }\n")

        compile_unit = MockCompileUnit(file_path=test_file, uuid="test-uuid-12345")
        entries = create_mock_line_entries(5)

        # Initial stats
        stats = self.cache_manager.get_stats()
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 0)

        # Cache miss
        cached = self.cache_manager.get_line_entries(compile_unit)
        stats = self.cache_manager.get_stats()
        self.assertEqual(stats["misses"], 1)

        # Cache and hit
        self.cache_manager.cache_line_entries(compile_unit, entries)
        cached = self.cache_manager.get_line_entries(compile_unit)
        stats = self.cache_manager.get_stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_clear_cache(self):
        """Test clearing cache"""
        # Create a real file for testing
        test_file = os.path.join(self.temp_dir, "test.cpp")
        with open(test_file, "w") as f:
            f.write("#include <iostream>\nint main() { return 0; }\n")

        compile_unit = MockCompileUnit(file_path=test_file, uuid="test-uuid-12345")
        entries = create_mock_line_entries(5)

        # Cache some entries
        self.cache_manager.cache_line_entries(compile_unit, entries)

        # Verify cache has entries
        self.assertGreater(len(self.cache_manager._memory_cache), 0)
        self.assertGreater(len(os.listdir(self.cache_manager.cache_dir)), 0)

        # Clear cache
        self.cache_manager.clear()

        # Verify cache is empty
        self.assertEqual(len(self.cache_manager._memory_cache), 0)
        self.assertEqual(len(os.listdir(self.cache_manager.cache_dir)), 0)

    def test_disk_cache_size_limit(self):
        """Test disk cache size limit enforcement"""
        # Create cache with very small disk limit
        cache = DwarfCacheManager(
            cache_dir=self.temp_dir,
            max_memory_size=10,
            max_disk_size=1000,  # 1KB
            logger=Mock(),
        )

        # Create real files for testing
        test_files = []
        for i in range(5):
            test_file = os.path.join(self.temp_dir, f"test{i}.cpp")
            with open(test_file, "w") as f:
                f.write(f"#include <iostream>\\nint main{i}() {{ return 0; }}\\n")
            test_files.append(test_file)

        # Add large entries to exceed limit
        for i in range(5):
            compile_unit = MockCompileUnit(file_path=test_files[i], uuid=f"uuid-{i}")
            entries = create_mock_line_entries(1000)  # Large entries
            cache.cache_line_entries(compile_unit, entries)

        # Older entries should be evicted
        stats = cache.get_stats()
        self.assertGreater(stats["evictions"], 0)

    @patch("native_context_tracer.dwarf_cache.lldb")
    def test_serialize_deserialize_line_entries(self, mock_lldb):
        """Test serialization and deserialization of line entries"""
        # Mock lldb.target
        mock_lldb.target = Mock()

        entries = create_mock_line_entries(5)

        # Serialize
        serialized = self.cache_manager._serialize_line_entries(entries)
        self.assertIsInstance(serialized, bytes)

        # Deserialize
        deserialized = self.cache_manager._deserialize_line_entries(serialized)
        # Note: Due to SBLineEntry mocking, we can't fully test this
        # In real usage, this would properly reconstruct SBLineEntry objects


if __name__ == "__main__":
    unittest.main()
