# Known Bugs and Fixes

## Bug: skip_symbols Not Working

### Description
The `skip_symbols` parameter was not functioning as expected when trying to skip specific symbols during transformation application.

### Root Cause
- The `skip_symbols` set contained simple symbol names (e.g. `'add'`)
- The code was comparing these against full path-style symbol keys (e.g. `/path/to/file.cpp/add`)
- The mismatch in formats caused the skip condition to always evaluate to false

### Fix Details
1. Modified `TransformApplier` to normalize skip symbols into two formats:
   - Full path format: `/path/to/file.cpp/symbol_name`
   - Name-only format: `//symbol_name` (special prefix)
2. Updated symbol skipping logic to check both formats
3. Added debug logging to help diagnose skip decisions

### Affected Files
- `transform_applier.py`
- `README.en.md` (updated documentation)

### Verification
The fix was verified by:
1. Running test cases with both skip symbol formats
2. Checking debug output to confirm correct skip decisions
3. Verifying transformations were properly skipped

Example test command:
```bash
# Skip by name only (applies to all files)
python gpt_workflow/code_trace --apply-transform --skip-symbols add

# Skip by full path (specific file)
python gpt_workflow/code_trace --apply-transform --skip-symbols /path/to/test.cpp/add
```

### Related Changes
- Updated documentation to explain both skip symbol formats
- Added more verbose logging for skip decisions