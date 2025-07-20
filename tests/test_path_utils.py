import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# Import the module under test
from debugger.utils.path_utils import _path_result_cache, to_relative_module_path


class TestToRelativeModulePath(unittest.TestCase):
    """Unit tests for the to_relative_module_path function."""

    def setUp(self) -> None:
        """Reset caches before each test to ensure isolation."""
        _path_result_cache.clear()

    def test_absolute_path_within_sys_path(self):
        """Test conversion of a path that is directly under a sys.path entry."""
        mock_sys_paths = [os.path.abspath("/a/b/c")]
        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", mock_sys_paths):
            test_path = os.path.abspath("/a/b/c/package/module.py")
            expected = "package/module.py"
            result = to_relative_module_path(test_path)
            self.assertEqual(result, expected)

    def test_absolute_path_at_sys_path_root(self):
        """Test conversion of a path that is at the root of a sys.path entry."""
        mock_sys_paths = [os.path.abspath("/a/b/c")]
        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", mock_sys_paths):
            test_path = os.path.abspath("/a/b/c/module.py")
            expected = "module.py"
            result = to_relative_module_path(test_path)
            self.assertEqual(result, expected)

    def test_absolute_path_outside_sys_path(self):
        """Test conversion of a path outside any sys.path entry returns basename."""
        mock_sys_paths = [os.path.abspath("/a/b/c")]
        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", mock_sys_paths):
            test_path = os.path.abspath("/d/e/f/module.py")
            expected = "module.py"
            result = to_relative_module_path(test_path)
            self.assertEqual(result, expected)

    def test_absolute_path_outside_sys_path_init(self):
        """Test conversion of __init__.py outside sys.path returns package/__init__.py."""
        mock_sys_paths = [os.path.abspath("/a/b/c")]
        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", mock_sys_paths):
            test_path = os.path.abspath("/d/e/f/package/__init__.py")
            expected = "package/__init__.py"
            result = to_relative_module_path(test_path)
            self.assertEqual(result, expected)

    def test_absolute_path_outside_sys_path_root_init(self):
        """Test conversion of __init__.py at root outside sys.path returns __init__.py."""
        mock_sys_paths = [os.path.abspath("/a/b/c")]
        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", mock_sys_paths):
            test_path = os.path.abspath("/__init__.py")
            expected = "__init__.py"
            result = to_relative_module_path(test_path)
            self.assertEqual(result, expected)

    @unittest.skipIf(os.name != "nt", "This test is specific to Windows path handling")
    def test_windows_path_handling(self):
        """Test conversion of a Windows path with backslashes."""
        mock_sys_paths = ["C:\\sys\\path"]
        test_path = "C:\\sys\\path\\package\\module.py"
        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", mock_sys_paths):
            expected = "package/module.py"
            result = to_relative_module_path(test_path)
            self.assertEqual(result, expected)

    def test_caching_behavior(self):
        """Test that results are cached and reused."""
        mock_sys_paths = [os.path.abspath("/a/b/c")]
        test_path = os.path.abspath("/a/b/c/cached_module.py")

        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", mock_sys_paths):
            # First call, should compute and cache
            result1 = to_relative_module_path(test_path)
            self.assertIn(test_path, _path_result_cache)

            # To prove it used the cache, we mock a function that would be called
            # on a cache miss and ensure it's not called the second time.
            with mock.patch("os.path.relpath") as mock_relpath:
                result2 = to_relative_module_path(test_path)
                mock_relpath.assert_not_called()

            self.assertEqual(result1, result2)

    def test_empty_sys_path(self):
        """Test behavior when sys.path is empty."""
        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", []):
            test_path = os.path.abspath("/some/path/module.py")
            expected = "module.py"
            result = to_relative_module_path(test_path)
            self.assertEqual(result, expected)

    def test_longest_path_match(self):
        """Test that the longest matching sys.path entry is used."""
        base_path = os.path.abspath("/base")
        nested_path = os.path.abspath("/base/nested")

        # The function relies on _cached_sorted_paths being sorted by length descending
        mock_cached_paths = sorted([base_path, nested_path], key=len, reverse=True)

        with mock.patch("debugger.utils.path_utils._cached_sorted_paths", mock_cached_paths):
            # Test path inside the most specific (longest) sys.path entry
            test_path_nested = os.path.abspath("/base/nested/module.py")
            expected_nested = "module.py"
            result_nested = to_relative_module_path(test_path_nested)
            self.assertEqual(result_nested, expected_nested)

            # Test a file in the less specific (shorter) base path
            _path_result_cache.clear()
            test_path_base = os.path.abspath("/base/another.py")
            expected_base = "another.py"
            result_base = to_relative_module_path(test_path_base)
            self.assertEqual(result_base, expected_base)


if __name__ == "__main__":
    unittest.main()
