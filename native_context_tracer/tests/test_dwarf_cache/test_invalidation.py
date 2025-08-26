"""
Tests for DWARF cache invalidation
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from native_context_tracer.dwarf_cache import CacheMetadata, DwarfCacheManager
from tests.test_dwarf_cache.fixtures import (
    MockCompileUnit,
    TempDirectory,
    create_mock_line_entries,
    create_test_file_with_content,
)


class TestCacheInvalidation(unittest.TestCase):
    """Test cases for cache invalidation logic"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp(prefix="dwarf_cache_test_")
        self.cache_manager = DwarfCacheManager(
            cache_dir=self.temp_dir, max_memory_size=10, max_disk_size=1024 * 1024, logger=Mock()
        )

    def tearDown(self):
        """Clean up test environment"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_metadata_validation_valid_cache(self):
        """Test that valid metadata passes validation"""
        with TempDirectory() as temp_dir:
            file_path = create_test_file_with_content(temp_dir, "test.cpp", "int main() { return 0; }")

            # Get file stats
            mtime = os.path.getmtime(file_path)
            size = os.path.getsize(file_path)

            metadata = CacheMetadata(
                module_uuid="test-uuid",
                module_path=file_path,
                file_mtime=mtime,
                file_size=size,
                dwarf_section_hash="hash123",
            )

            # Should validate successfully
            is_valid = self.cache_manager._validate_metadata(metadata)
            self.assertTrue(is_valid)

    def test_metadata_validation_file_not_exists(self):
        """Test cache invalidation when file doesn't exist"""
        metadata = CacheMetadata(
            module_uuid="test-uuid",
            module_path="/nonexistent/file.cpp",
            file_mtime=1234567890,
            file_size=100,
            dwarf_section_hash="hash123",
        )

        is_valid = self.cache_manager._validate_metadata(metadata)
        self.assertFalse(is_valid)

    def test_metadata_validation_mtime_mismatch(self):
        """Test cache invalidation when modification time changes"""
        with TempDirectory() as temp_dir:
            file_path = create_test_file_with_content(temp_dir, "test.cpp", "int main() { return 0; }")

            # Get current mtime
            mtime = os.path.getmtime(file_path)
            size = os.path.getsize(file_path)

            metadata = CacheMetadata(
                module_uuid="test-uuid",
                module_path=file_path,
                file_mtime=mtime - 100,  # Older mtime
                file_size=size,
                dwarf_section_hash="hash123",
            )

            is_valid = self.cache_manager._validate_metadata(metadata)
            self.assertFalse(is_valid)

    def test_metadata_validation_size_mismatch(self):
        """Test cache invalidation when file size changes"""
        with TempDirectory() as temp_dir:
            file_path = create_test_file_with_content(temp_dir, "test.cpp", "int main() { return 0; }")

            mtime = os.path.getmtime(file_path)
            size = os.path.getsize(file_path)

            metadata = CacheMetadata(
                module_uuid="test-uuid",
                module_path=file_path,
                file_mtime=mtime,
                file_size=size + 100,  # Different size
                dwarf_section_hash="hash123",
            )

            is_valid = self.cache_manager._validate_metadata(metadata)
            self.assertFalse(is_valid)

    def test_cache_invalidates_after_file_modification(self):
        """Test that cache is invalidated after file is modified"""
        with TempDirectory() as temp_dir:
            file_path = create_test_file_with_content(temp_dir, "test.cpp", "int main() { return 0; }")

            compile_unit = MockCompileUnit(file_path=file_path, uuid="test-uuid-12345")
            entries = create_mock_line_entries(5)

            # Cache entries
            self.cache_manager.cache_line_entries(compile_unit, entries)

            # Verify cache works
            cached = self.cache_manager.get_line_entries(compile_unit)
            self.assertIsNotNone(cached)

            # Wait a moment to ensure different mtime
            time.sleep(0.01)

            # Modify the file
            with open(file_path, "a") as f:
                f.write("\n// Added comment")

            # Cache should now be invalid
            cached = self.cache_manager.get_line_entries(compile_unit)
            self.assertIsNone(cached)

    def test_cache_works_after_rebuild(self):
        """Test that cache works correctly after being rebuilt"""
        with TempDirectory() as temp_dir:
            file_path = create_test_file_with_content(temp_dir, "test.cpp", "int main() { return 0; }")

            compile_unit = MockCompileUnit(file_path=file_path, uuid="test-uuid-12345")
            entries = create_mock_line_entries(5)

            # Cache entries
            self.cache_manager.cache_line_entries(compile_unit, entries)

            # Modify file to invalidate cache
            time.sleep(0.01)
            with open(file_path, "a") as f:
                f.write("\n// Added comment")

            # Cache should be invalid
            cached = self.cache_manager.get_line_entries(compile_unit)
            self.assertIsNone(cached)

            # Re-cache with new entries
            new_entries = create_mock_line_entries(10)
            self.cache_manager.cache_line_entries(compile_unit, new_entries)

            # Should work again
            cached = self.cache_manager.get_line_entries(compile_unit)
            self.assertIsNotNone(cached)

    def test_cleanup_old_entries(self):
        """Test cleanup of old cache entries"""
        # Create multiple cache entries
        for i in range(5):
            compile_unit = MockCompileUnit(file_path=f"/test/src/test{i}.cpp", uuid=f"uuid-{i}")
            entries = create_mock_line_entries(10)
            self.cache_manager.cache_line_entries(compile_unit, entries)

        # Manually set old access times on some entries
        cache_dirs = list(self.cache_manager.cache_dir.iterdir())
        for cache_dir in cache_dirs[:2]:  # Make first 2 entries old
            metadata_path = cache_dir / "metadata.json"
            if metadata_path.exists():
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                metadata["last_accessed"] = time.time() - 86400 * 7  # 7 days ago
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f)

        # Set very small disk size to force cleanup
        self.cache_manager.max_disk_size = 100

        # Run cleanup
        self.cache_manager._cleanup_old_entries()

        # Some entries should have been cleaned up
        remaining_dirs = list(self.cache_manager.cache_dir.iterdir())
        self.assertLess(len(remaining_dirs), 5)

    def test_corrupted_cache_handling(self):
        """Test handling of corrupted cache files"""
        compile_unit = MockCompileUnit(file_path="/test/src/test.cpp", uuid="test-uuid-12345")
        entries = create_mock_line_entries(5)

        # Cache entries
        self.cache_manager.cache_line_entries(compile_unit, entries)

        # Corrupt the data file
        cache_key = self.cache_manager._get_cache_key(compile_unit)
        data_path = self.cache_manager._get_data_path(cache_key, "line_entries")
        # Ensure parent directory exists
        data_path.parent.mkdir(parents=True, exist_ok=True)
        with open(data_path, "w") as f:
            f.write("corrupted data")

        # Should handle corruption gracefully
        cached = self.cache_manager.get_line_entries(compile_unit)
        self.assertIsNone(cached)


if __name__ == "__main__":
    unittest.main()
