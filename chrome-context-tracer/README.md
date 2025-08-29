# Chrome Context Tracer

A powerful command-line tool that brings Chrome DevTools functionality to your terminal. Built on the Chrome DevTools Protocol (CDP), it allows you to inspect DOM elements, analyze CSS, trace event listeners, and debug JavaScript execution without leaving your terminal.

## 🌟 Features

### 🕵️‍♀️ DOM Inspection (`inspect`)
- **Smart Element Selection**:
  - **Mouse Pointer Mode**: A browser overlay allows you to simply click on any element to select it for inspection. This is implemented via robust JavaScript injection, making it fully cross-platform.
  - **CSS Selector Mode**: Target elements precisely using standard CSS selectors.
- **Complete Style Analysis**:
  - **DevTools-Compatible Output**: Get CSS styles in the exact same format as the Chrome DevTools "Styles" pane.
  - **Source Information**: See which CSS file and line number each style originates from.
  - **Inheritance Chain**: View styles inherited from parent elements.
- **Event Listener Inspection**:
  - **Full Event Analysis**: List all event listeners attached to an element and its ancestors (up to `window`).
  - **Source Location**: Pinpoint the exact JavaScript file, line number, and function for each listener.

### 🐛 JavaScript Debugging (`trace`)
- **Debugger Tracing**: Activate a trace mode that listens for `debugger;` statements in your JavaScript code.
- **Rich Call Stacks**: When a `debugger;` statement is hit, it prints a complete, easy-to-read call stack.
- **Variable Inspection**: The output includes the names and values of local variables within each scope of the call stack at the moment of pause.
- **Automatic Resume**: The script automatically resumes execution after printing the stack trace, allowing for non-intrusive logging.

### 🌐 General
- **Multi-Browser Support**: Works seamlessly with Google Chrome and Microsoft Edge.
- **Cross-Platform**: Fully functional on macOS, Windows, and Linux.
- **Auto-Launch Browser**: Can automatically launch a browser instance with remote debugging enabled if one isn't already running.

## 🚀 Installation

### Prerequisites
- Python 3.7+
- An installed version of Google Chrome or Microsoft Edge.

### Dependencies
The tool has one core dependency: `aiohttp`.

```bash
pip install aiohttp
```

## 🛠️ Setup

To allow the tool to connect, you need to launch your browser with the remote debugging port enabled.

#### Chrome
```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

#### Microsoft Edge
The command is similar, just replace the executable name (e.g., `msedge`).

**Tip**: The tool can also attempt to **auto-launch** a browser for you if it can't find a running instance on the specified port.

## 📖 Usage

The tool is split into two main commands: `inspect` and `trace`.

### `inspect` - Inspecting DOM Elements
This command is for analyzing the HTML, CSS, and event listeners of a specific element.

#### Using Mouse Pointer Selection (Recommended)
This is the easiest way to select an element.
```bash
# Inspect styles, events, and HTML of an element by clicking on it
python dom_inspector.py inspect --url "example.com" --from-pointer --events --html
```
**How it works:**
1. Run the command. A browser overlay will activate.
2. Move your mouse to highlight elements.
3. **Click** on the target element to select it.
4. Press the `ESC` key to cancel selection.

#### Using a CSS Selector
```bash
# Inspect only the styles for an element with the ID 'main-content'
python dom_inspector.py inspect --url "example.com" --selector "#main-content"

# Get events and HTML for an element with the class '.btn-primary'
python dom_inspector.py inspect --url "example.com" --selector ".btn-primary" --events --html
```

### `trace` - Tracing JavaScript Execution
This command listens for `debugger;` statements and prints the call stack.

```bash
# Attach to a tab and wait for debugger statements
python dom_inspector.py trace --url "example.com"
```
Once attached, any time a `debugger;` statement is executed in the page's JavaScript, its context will be printed to your terminal.

## 命令行选项

### Global Options
| Option | Description | Default |
|--------|-------------|---------|
| `--port` | The port for the browser's remote debugging protocol. | `9222` |

### `inspect` Command
| Option | Description |
|--------|-------------|
| `--url` | A URL pattern to find the target browser tab. If omitted, you can choose from a list. |
| `--selector` | The CSS selector for the element to inspect. |
| `--from-pointer` | Use the interactive, in-browser mouse selection mode. |
| `--events` | Display the event listeners attached to the element. |
| `--html` | Display the outer HTML of the element. |

*Note: You must provide either `--selector` or `--from-pointer`.*

### `trace` Command
| Option | Description |
|--------|-------------|
| `--url` | A URL pattern to find the target browser tab. If omitted, you can choose from a list. |

## 📋 Example Output

### CSS Styles (`inspect`)
```
element.style {
}

main.css:12
.button {
    background-color: #007bff;
    color: white;
}

user agent stylesheet
button {
    cursor: pointer;
}
```

### Event Listeners (`inspect`)
```
📍 脚本位置组 #1
==================================================
🎯 事件类型: click (1个)
🔗 绑定对象: button#my-button.btn.btn-primary
📄 脚本ID: 25
📍 位置: 行 15, 列 8
🌐 脚本URL: http://example.com/assets/main.js
⚙️  监听属性: 捕获=否, 被动=否, 一次=否
📝 相关代码:
    → 15:     button.addEventListener('click', () => {
      16:         console.log('Button clicked!');
      17:     });
```

### Debugger Trace (`trace`)
```
==================== Paused on debugger statement ====================
Reason: debuggerStatement

--- Stack Trace ---
  [0] funcC at test.html:15:13
  [1] funcB at test.html:21:13
  [2] funcA at test.html:25:13

--- Frame 0: funcC (test.html:15:13) ---
Source Context:
   13 |     let b = "test string";
   14 |     let c = { d: 1, e: "nested" };
-> 15 |     debugger;    // a: 10, b: "test string", c: Object
   16 | }
   17 | 

--- Frame 1: funcB (test.html:21:13) ---
Source Context:
   19 | function funcB() {
   20 |     let z = 99;
-> 21 |     funcC();
   22 | }
   23 | 

==================================================================
Resuming execution...
```

## 🔧 Technical Details

This tool communicates directly with the browser using the **Chrome DevTools Protocol (CDP)** over WebSockets.

The interactive element selection mode (`--from-pointer`) is achieved by injecting a JavaScript module into the target page. This script overlays the page, highlights elements under the cursor, and captures clicks. When an element is selected, the script sends a `console.log` message with a unique prefix and the element's unique CSS selector. The Python backend listens for this specific console message, parses the selector, and uses it to perform the inspection via CDP. This approach avoids brittle OS-level screen coordinate calculations and works reliably across all platforms and display resolutions.

## 🧪 Testing

The project includes a comprehensive test suite to ensure reliability.

### Running Tests
You can run tests individually:
```bash
python test_dom_inspector.py
python test_debugger_trace.py
```

### Test Overview
- **`test_dom_inspector.py`**: End-to-end tests for the `inspect` command, covering element finding, style extraction, and event listeners.
- **`test_debugger_trace.py`**: An integration test for the `trace` command, verifying that it correctly captures `debugger;` statements and prints the stack with variables.
- ... and many others for connection, utilities, and specific features.

## 🤝 Contributing

Contributions are welcome! Please feel free to fork the repository, make your changes, and submit a pull request.

## 📄 License

This project is licensed under the MIT License.