# DWARF Cache Tests

This directory contains comprehensive tests for the DWARF parser cache feature.

## Test Structure

```
test_dwarf_cache/
├── __init__.py
├── fixtures.py          # Test fixtures and mock objects
├── test_dwarf_cache_manager.py  # Unit tests for DwarfCacheManager
├── test_invalidation.py         # Tests for cache invalidation
├── test_integration.py          # Integration tests with SourceHandler
├── test_performance.py          # Performance benchmarks
└── run_tests.py                 # Test runner script
```

## Running Tests

### Run All Tests
```bash
python tests/test_dwarf_cache/run_tests.py
```

### Run Specific Test Types
```bash
# Run only unit tests
python tests/test_dwarf_cache/run_tests.py unit

# Run only invalidation tests
python tests/test_dwarf_cache/run_tests.py invalidation

# Run only integration tests
python tests/test_dwarf_cache/run_tests.py integration

# Run only performance benchmarks
python tests/test_dwarf_cache/run_tests.py performance
```

### Run with Coverage
```bash
python tests/test_dwarf_cache/run_tests.py --coverage
```

## Test Categories

### 1. Unit Tests (test_dwarf_cache_manager.py)
- Cache initialization and directory creation
- Cache key generation
- Basic get/set operations
- Memory cache LRU eviction
- Disk cache persistence
- Cache statistics
- Cache clearing

### 2. Invalidation Tests (test_invalidation.py)
- File modification detection
- Metadata validation
- Cache corruption handling
- Cache cleanup
- Automatic rebuild after invalidation

### 3. Integration Tests (test_integration.py)
- SourceHandler integration
- Configuration options
- Cache enable/disable
- Large compile unit handling
- Custom cache directories

### 4. Performance Tests (test_performance.py)
- Cache hit vs miss performance
- Memory cache performance
- Disk cache performance
- Serialization performance
- Concurrent access performance
- LRU eviction performance

## Test Fixtures

The `fixtures.py` module provides:
- `MockCompileUnit`: Mock SBCompileUnit for testing
- `MockLineEntry`: Mock SBLineEntry for testing
- `TempDirectory`: Context manager for temporary directories
- Helper functions for creating test data

## Writing New Tests

When adding new tests:

1. Use the provided fixtures when possible
2. Test both success and failure cases
3. Clean up temporary files and directories
4. Follow the existing naming conventions
5. Add appropriate assertions

Example:
```python
def test_new_feature(self):
    """Test new feature description"""
    with TempDirectory() as temp_dir:
        # Setup test data
        compile_unit = MockCompileUnit(...)
        
        # Test the feature
        result = self.cache_manager.new_feature(compile_unit)
        
        # Verify results
        self.assertIsNotNone(result)
        self.assertEqual(len(result), expected_count)
```

## Performance Considerations

The performance tests are designed to:
- Measure cache hit/miss ratios
- Verify speed improvements from caching
- Test behavior under load
- Ensure memory usage is reasonable

Performance thresholds are set based on typical debugging scenarios:
- Cache hits should be >10x faster than misses
- Memory cache retrievals should be <1ms
- Disk cache retrievals should be <10ms

## Continuous Integration

These tests can be integrated into CI/CD pipelines:
- Unit and integration tests should pass on every commit
- Performance tests can be used for regression detection
- Coverage should be maintained above 80%