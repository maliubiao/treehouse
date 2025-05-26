# Code Trace Workflow

A tool for tracing and transforming code symbols with parallel processing support.

## Installation

```bash
# Clone the repository
git clone https://github.com/your-repo/terminal-llm.git
cd terminal-llm

# Install dependencies
pip install -e .
```

## Quick Start

### Basic Usage
```bash
# Trace a single file
python -m gpt_workflow.code_trace --file path/to/file.cpp

# Trace multiple files using config
python -m gpt_workflow.code_trace --config config.yaml
```

### Example Workflow

1. Create a config file (config.yaml):
```yaml
source_files:
  - "src/**/*.cpp"
  - "include/**/*.h"

exclude_patterns:
  - "**/third_party/**"
  - "**/test/**"

verify_cmd: "make test"
```

2. Run the transformation:
```bash
python -m gpt_workflow.code_trace --config config.yaml --parallel
```

## Features

### Symbol Skipping
Skip specific symbols during transformation:
```bash
# Skip 'add' function in any file
python -m gpt_workflow.code_trace --skip-symbols add

# Skip all symbols starting with 'test_' 
python -m gpt_workflow.code_trace --skip-symbols '*/test_*'
```

### Dry-Run Mode
Preview transformations without applying:
```bash
python -m gpt_workflow.code_trace --apply-transform --skip-symbols '*/test_*' --dry-run
```

### Transformation Inspection
View applied transformations:
```bash
# View all transformations
python -m gpt_workflow.code_trace --inspect-transform

# View transformations for specific file
python -m gpt_workflow.code_trace --inspect-transform --inspect-file src/utils.cpp
```

## Testing

Run the test script to verify functionality:
```bash
./gpt_workflow/code_trace/test_apply_transform.sh
```

The test script will:
1. Create test C++ files
2. Run transformations
3. Verify the results
4. Keep output in /tmp/code_trace_test for inspection

## Architecture

See [DESIGN.md](DESIGN.md) for system architecture details.

## Known Issues

See [BUG.md](BUG.md) for known issues and fixes.