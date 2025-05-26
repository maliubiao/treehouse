```
python gpt_workflow/code_trace --prompt-debug /Users/richard/code/terminal-llm/prompt_cache/20250515-113840_28dfa42a.json
```

## Transformation Workflow Example

### 1. Create a config file (config.yaml):
```yaml
source_files:
  - "gpt_workflow/code_trace/test.cpp"
  - "gpt_workflow/code_trace/test1.cpp"

verify_cmd: "g++ gpt_workflow/code_trace/test.cpp gpt_workflow/code_trace/test1.cpp -o test && ./test"
```

### 2. Run the transformation:
```bash
python gpt_workflow/code_trace --config config.yaml --parallel --skip-symbols add,print_thread_info
```

### Symbol Skipping Syntax

You can skip symbols in two ways:
1. **Full path format**: `path/to/file.cpp/symbol_name`
2. **Symbol name only**: `symbol_name` (will skip all symbols with this name)

Example:
```bash
# Skip 'add' function in any file
python gpt_workflow/code_trace --skip-symbols add

# Skip all symbols starting with 'test_' in any file
python gpt_workflow/code_trace --skip-symbols '*/test_*'

# Preview which symbols would be skipped (dry-run)
python gpt_workflow/code_trace --skip-symbols '*/test_*' --dry-run
```

### Dry-Run Mode

Use `--dry-run` to preview which symbols would be skipped without actually applying any changes:

```bash
python gpt_workflow/code_trace --apply-transform --skip-symbols '*/test_*,add' --dry-run
```

### 3. Expected Transformation:
The tracer will process both C++ files in parallel and may transform functions like:

test.cpp:
```cpp
// Original
int add(int a, int b) {
    return a + b;
}

// Transformed (example)
int add(int a, int b) {
    std::cout << "Adding " << a << " and " << b << std::endl;
    return a + b;
}
```

test1.cpp:
```cpp
// Original
void print_thread_info(int thread_id) {
    std::cout << "Thread " << thread_id << " started" << std::endl;
    int result = factorial(thread_id);
    std::cout << "Thread " << thread_id << " result: " << result << std::endl;
}

// Transformed (example)
void print_thread_info(int thread_id) {
    auto start = std::chrono::high_resolution_clock::now();
    std::cout << "Thread " << thread_id << " started" << std::endl;
    int result = factorial(thread_id);
    auto end = std::chrono::high_resolution_clock::now();
    std::cout << "Thread " << thread_id << " result: " << result 
              << " (took " << std::chrono::duration_cast<std::chrono::milliseconds>(end-start).count() 
              << "ms)" << std::endl;
}
```

### 4. Verify the changes:
The verify command will compile and run both programs to ensure they work together.

### 5. Inspect transformations:
```bash
# View all transformations
python gpt_workflow/code_trace --inspect-transform

# View transformations for specific files
python gpt_workflow/code_trace --inspect-transform --inspect-file gpt_workflow/code_trace/test.cpp
python gpt_workflow/code_trace --inspect-transform --inspect-file gpt_workflow/code_trace/test1.cpp
```

## Configuration Example

```yaml
# Example config.yaml
source_files:
  - "**/*.cpp"
  - "**/*.h"
  - "**/*.py"

exclude_patterns:
  - "**/third_party/**"
  - "**/generated/**"
  - "**/test/**"
  - "**/*_test.cpp"
  - "**/*_test.py"

verify_cmd: "make test"
skip_crc32:
  - "12345678"
  - "87654321"
```

### Configuration Options

- `source_files`: List of glob patterns to specify which files to process
- `exclude_patterns`: List of glob patterns to exclude from processing (files matching these patterns will be skipped)
- `verify_cmd`: Command to run after processing to verify the changes
- `skip_crc32`: List of CRC32 values to skip (useful for problematic symbols)

### Applying Transformations Directly

You can apply transformations directly from the log file without querying GPT:

```bash
python gpt_workflow/code_trace --apply-transform --skip-symbols symbol1,symbol2
```

Options:
- `--apply-transform`: Apply transformations directly from file-specific transformation files
- `--skip-symbols`: Comma-separated list of symbols to skip (supports both full path and name-only formats)
- `--transform-file`: Path to custom transformation file (default: trace_debug/file_transformations/<filename>_transformations.json)

### Inspecting Transformations

After running the tracer, you can inspect code transformations with:

```bash
# View transformations for all processed files
python gpt_workflow/code_trace --inspect-transform

# View transformations for a specific file
python gpt_workflow/code_trace --inspect-transform --inspect-file path/to/file.py

# View transformations from a specific transformation file
python gpt_workflow/code_trace --inspect-transform --transform-file path/to/transform_file.json
```

The output will be colorized and formatted for easy reading of code changes.

#### Transformation Storage

Transformations are now stored per-file in:
```
trace_debug/
  file_transformations/
    <filename>_transformations.json
    ...
```

Each transformation file contains:
- Original and transformed code for each symbol
- File path and symbol name
- Change status (MODIFIED/UNCHANGED)

#### Transformation Report Example

The transformation report provides:
1. Summary statistics showing total symbols processed and transformation rate
2. Detailed view for each symbol showing:
   - Symbol path and status (MODIFIED/UNCHANGED)
   - Original code (highlighted in white)
   - Transformed code (highlighted in green if changed)
3. Visual separators between symbols for better readability

#### Filtering Transformations

You can filter transformations by file path:

```bash
python gpt_workflow/code_trace --inspect-transform --inspect-file src/utils.py
```

This will only show transformations from files containing "src/utils.py" in their path.

#### Understanding the Output

- **MODIFIED** symbols show both original and transformed code
- **UNCHANGED** symbols only show the original code
- The transformation rate helps identify how much of your codebase was actually modified
- Color coding makes it easy to spot changes at a glance

## Multi-file Parallel Processing

The system supports parallel processing of multiple files with thread-safe transformation storage:

1. Each file is processed in a separate thread
2. Transformations are stored in separate JSON files under `trace_debug/file_transformations/`
3. The verification command can test all transformed files together
4. You can inspect transformations per-file or across all files

Example parallel processing command:
```bash
python gpt_workflow/code_trace --config config.yaml --parallel
```

Key features:
- Thread-safe file operations
- Per-file transformation tracking
- Cross-file symbol reference support
- Consolidated verification

## Testing Transformations

You can test the transformation functionality using the included test script:

```bash
./gpt_workflow/code_trace/test_apply_transform.sh
```

The test script will:
1. Create a temporary test environment
2. Generate sample C++ files (test.cpp and test1.cpp)
3. Create a configuration file (config.yaml)
4. Run initial transformations
5. Test applying transformations with symbol filtering
6. Verify the transformations were applied correctly
7. Clean up temporary files (while keeping output for inspection)

The test script demonstrates:
- Basic transformation workflow
- Applying transformations with symbol filtering
- Using specific transformation files
- Verifying transformations were applied correctly

For debugging purposes, the test script keeps the output files in `/tmp/code_trace_test` for inspection after the test completes.