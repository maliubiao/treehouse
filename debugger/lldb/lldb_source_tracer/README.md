# LLDB Source Code Tracer

## Overview
This tool provides enhanced source code tracing capabilities for LLDB, including:
- Step-by-step execution logging with timestamps
- Function call/return tracing with parameter capture
- Pretty-printed variable values
- Call graph generation (Mermaid format)
- Interactive HTML reports
- Library function filtering
- React-based trace viewer

## Features
- **Detailed Execution Logging**: Records every step with source locations
- **Smart Value Inspection**: Pretty-prints complex data structures
- **Performance Metrics**: Tracks function execution times
- **Multi-Format Output**: Generates logs, call graphs, and HTML reports
- **Configurable Tracing**: Skip library functions to focus on application code
- **Interactive Viewer**: Visualize execution traces in a web-based UI

## Installation
1. Ensure LLDB is installed (macOS: `xcode-select --install`, Linux: `sudo apt-get install lldb`)
2. Install Node.js (v16+) for the trace viewer: [Node.js Download](https://nodejs.org/)
3. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/lldb-source-tracer.git
   cd lldb-source-tracer
   ```
4. Install viewer dependencies:
   ```bash
   cd trace-viewer
   npm install
   ```

## Usage
### Basic Tracing
```bash
python3 lldb_source_tracer.py /path/to/executable [program-args]
```

### Advanced Options
```bash
python3 lldb_source_tracer.py /path/to/executable \
    --output-dir custom_output \
    --log-file custom.log \
    --html-file report.html \
    --include-libs \
    --verbose
```

### Using the Trace Viewer
1. Generate a JSON trace file:
   ```bash
   python3 lldb_source_tracer.py /path/to/executable --json-file trace.json
   ```
   
2. Start the viewer using any of these methods:
   ```bash
   # Method 1: Use the start script (recommended)
   ./start_viewer.sh
   
   # Method 2: Manual start
   cd trace-viewer
   npm run dev
   
   # Method 3: Preview production build
   cd trace-viewer
   npm run preview
   ```
   
3. Open http://localhost:5173 in your browser
4. Click "Open Trace File" and select the generated trace.json

### Example Output Files
- `trace_output/trace.log`: Text-based execution log
- `trace_output/callgraph.mmd`: Mermaid-format call graph
- `trace_output/trace.html`: Interactive HTML report
- `trace_output/trace.json`: JSON data for trace viewer

## Examples
### Tracing a Simple Program
```bash
# Compile example
cd examples
make

# Run tracer
cd ..
python3 lldb_source_tracer.py examples/simple
```

### Viewing Outputs
1. **Log File**:
   ```
   [14:25:36.812] CALL main at simple.c:10
     x=5, y=10
   [14:25:36.815] CALL add at simple.c:3
     a=5, b=10
   [14:25:36.817] STEP add at simple.c:4
     result=15
   [14:25:36.819] RETURN add -> 15 at simple.c:5
   ```

2. **Call Graph** (Mermaid):
   ```mermaid
   graph TD
       main -->|1| add
   ```

3. **HTML Report**: Open `trace_output/trace.html` in browser

4. **Trace Viewer**: Open `trace-viewer` and load `trace_output/trace.json`

## Testing
Run the test suite:
```bash
cd test
./run_tests.sh
```

Tests include:
- Basic step tracing
- Function parameter capture
- Return value detection
- Call graph generation
- HTML report generation
- JSON data generation

## Design
See [DESIGN.md](DESIGN.md) for implementation details and design decisions.

## Limitations
- Best results with Clang-compiled programs (`-g -O0`)
- Return value capture limited by architecture support
- Complex C++ objects may not be fully inspected

## Contributing
Contributions are welcome! Please open issues or pull requests for:
- Additional architecture support
- Enhanced value inspection
- Performance improvements
- UI enhancements for the trace viewer