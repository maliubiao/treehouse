# LLDB Trace Viewer

React-based visualization tool for LLDB trace data.

## Installation

```bash
cd trace-viewer
npm install
```

## Development

Start the development server:

```bash
# From project root:
../start_viewer.sh

# Or manually:
npm run dev
```

Open http://localhost:5173 in your browser.

## Building for Production

```bash
npm run build
```

The build artifacts will be stored in the `dist/` directory.

## Preview Production Build

```bash
npm run preview
```

## Usage

1. Generate a trace file using `lldb_source_tracer.py`:
   ```bash
   python3 lldb_source_tracer.py /path/to/executable --json-file trace.json
   ```
   
2. Open the Trace Viewer in your browser
3. Click "Open Trace File" and select the generated `trace.json` file
4. Explore the execution timeline, source code, and call graph

## Features

- Interactive execution timeline
- Source code viewer with highlighted execution points
- Call graph visualization
- Performance statistics
- Local variable inspection