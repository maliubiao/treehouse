# Chrome Context Tracer

A powerful DOM inspector tool that replicates Chrome DevTools functionality through the Chrome DevTools Protocol (CDP). Get detailed CSS styles, event listeners, and HTML representation for any web element.

## 🌟 Features

### 🎯 Smart Element Selection
- **Mouse Pointer Selection**: Point and click to select elements with hotkey support (`m` key)
- **CSS Selector Mode**: Traditional CSS selector-based element targeting
- **Intelligent Window Detection**: Automatically detects Chrome/Edge browser windows
- **High DPI Support**: Accurate coordinate conversion for all display types (Retina, 4K, etc.)

### 🎨 Complete Style Analysis
- **DevTools-Compatible Output**: Exact same format as Chrome DevTools
- **Source File Information**: Shows which CSS file and line number affects each style
- **Inheritance Chain**: Displays inherited styles from parent elements
- **Style Priority**: Respects CSS cascade and specificity rules
- **Multiple Origins**: Supports user-agent, author, and injected stylesheets

### 🎧 Event Listener Inspection
- **Complete Event Analysis**: Shows all event listeners attached to elements
- **Source Location**: Displays JavaScript file, line number, and function information
- **Event Details**: Capture phase, passive, once flags, and handler information
- **DevTools Format**: Identical output to Chrome DevTools event listener panel

### 🌐 Multi-Browser Support
- **Chrome**: Full support for Google Chrome
- **Microsoft Edge**: Complete compatibility with Edge browser
- **Cross-Platform**: Works on macOS, Windows, and Linux

## 🚀 Installation

### Prerequisites
Ensure you have Python 3.7+ installed.

### Required Dependencies
```bash
pip install aiohttp pyautogui keyboard
```

### Platform-Specific Dependencies

#### Windows
```bash
pip install pygetwindow
```

#### macOS (Optional for enhanced Retina detection)
```bash
pip install pyobjc-framework-Cocoa
```

#### Linux
```bash
# Install wmctrl for window detection
sudo apt-get install wmctrl

# Or on other distributions:
# sudo yum install wmctrl
# sudo pacman -S wmctrl
```

## 🛠️ Setup

### Browser Configuration

#### Chrome
```bash
chrome --remote-debugging-port=9222
```

#### Microsoft Edge
```bash
msedge --remote-debugging-port=9222
```

### Alternative Setup
You can also enable remote debugging through browser flags:
- Launch browser with `--remote-debugging-port=9222` flag
- Or set up a custom port with `--remote-debugging-port=<port>`

## 📖 Usage

### Mouse Pointer Selection Mode (Recommended)
```bash
# Basic element inspection with mouse selection
python dom_inspector.py --url "example.com" --from-pointer

# Complete analysis: styles + events + HTML
python dom_inspector.py --url "example.com" --from-pointer --events --html

# Custom port
python dom_inspector.py --url "localhost:3000" --from-pointer --port 9223
```

**How it works:**
1. Run the command
2. Move your mouse to the target element on the webpage
3. Press `m` key to select the element
4. Press `q` key to exit selection mode

### CSS Selector Mode
```bash
# Target specific elements with CSS selectors
python dom_inspector.py --url "example.com" --selector ".my-class"

# Multiple inspection types
python dom_inspector.py --url "example.com" --selector "#button" --events --html
```

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--url` | URL pattern to match browser tabs | Required |
| `--selector` | CSS selector (if not using `--from-pointer`) | Optional |
| `--from-pointer` | Enable mouse pointer selection mode | False |
| `--events` | Show event listeners information | False |
| `--html` | Show element HTML representation | False |
| `--port` | Browser debugging port | 9222 |

## 📋 Example Output

### CSS Styles
```css
element.style {
}

.param-type {
    display: block;
    font-weight: bold;
}

a, .aside-close-button {
    color: hsl(232, 50%, 45%);
}

用户代理样式表
a:-webkit-any-link {
    color: -webkit-link;
    cursor: pointer;
    text-decoration: underline;
}

继承的样式:
html, body {
    font-family: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif;
    background-color: #fafafa;
}
```

### Event Listeners
```
事件类型: click
----------------------------------------
  捕获阶段: 否
  被动监听: 否
  仅触发一次: 否
  脚本ID: 123
  位置: 行 45, 列 12
  函数: function onClick() { ... }

事件类型: mouseover
----------------------------------------
  捕获阶段: 是
  被动监听: 是
  仅触发一次: 否
  脚本ID: 124
  位置: 行 78, 列 8
```

### HTML Representation
```html
<button class="btn btn-primary" data-toggle="modal" onclick="handleClick()">
  Click me
  <span class="icon"></span>
</button>
```

## 🔧 Technical Details

### Architecture
- **Chrome DevTools Protocol**: Direct communication with browser debugging API
- **Asynchronous Operations**: Built with `aiohttp` for efficient WebSocket communication
- **Cross-Platform Window Management**: Platform-specific window detection and coordinate conversion

### Coordinate System
The tool handles complex coordinate conversions with high precision:

1. **Physical Screen Coordinates**: Raw mouse position in physical pixels
2. **DPI Scaling Detection**: Automatic high-DPI display scaling detection using platform-specific APIs
3. **Browser Window Detection**: Cross-platform window detection using:
   - **macOS**: Objective-C/Cocoa Accessibility APIs and AppleScript fallback
   - **Windows**: pygetwindow library with Win32 API integration
   - **Linux**: wmctrl utility for X11 window management
4. **Browser UI Offset Calculation**: Automatic detection of browser chrome (address bar, tabs, etc.)
5. **Viewport Coordinates**: Final coordinates for DOM API after all conversions

### DPI Support
- **Automatic Detection**: Identifies display scaling factors using native platform APIs
- **Platform-Specific Implementations**:
  - **macOS**: Uses `NSScreen` API for Retina display detection
  - **Windows**: Uses `GetDpiForWindow` and monitor DPI awareness
  - **Linux**: Uses X11 server information and display configuration
- **Common Scales**: Supports 100%, 125%, 150%, 175%, 200%, 225%, 250%, 300%, 400%
- **Dynamic Scaling**: Handles multi-monitor setups with different DPI scaling

### Window Detection Architecture

The window detection system uses a multi-layered approach:

1. **Primary Detection**: Platform-specific native APIs
   - macOS: Accessibility API (AXUIElement) with Objective-C/Cocoa
   - Windows: pygetwindow with Win32 API integration
   - Linux: wmctrl with X11 window management

2. **Fallback Mechanisms**:
   - AppleScript fallback for macOS when Accessibility API fails
   - Process enumeration for browser identification
   - Window filtering by title, class, and visibility

3. **Error Handling**:
   - Graceful degradation when APIs are unavailable
   - Permission handling for accessibility features
   - Cross-platform compatibility checks

### Coordinate Conversion Workflow

```
Physical Screen Coordinates
          ↓
DPI Scaling Application (× scale factor)
          ↓
Browser Window Detection (position + size)
          ↓
Browser UI Offset Calculation (address bar, tabs)
          ↓
Viewport Coordinates (final DOM position)
          ↓
DOM Element Selection
```

This sophisticated coordinate conversion system ensures accurate element selection across all display types and browser configurations.

## 🐛 Troubleshooting

### Common Issues

#### Browser Connection Issues
- **"No browser tabs found"**: 
  - Ensure browser is running with remote debugging: `chrome --remote-debugging-port=9222`
  - Check if the URL pattern matches any open tabs
  - Verify the port number is correct
  - Use `test_manual_browser.py` to debug connection issues

- **"Cannot connect to browser"**:
  - Check if browser is running with the correct debugging port
  - Verify firewall isn't blocking WebSocket connections
  - Try using a different port number

#### Coordinate Conversion Issues
- **"Mouse position doesn't match element"**:
  - The tool automatically handles DPI scaling
  - Ensure the browser window is visible and not minimized
  - Try different elements or refresh the page
  - Run `test_enhanced_coordinate_conversion.py` to validate coordinate accuracy

- **"Cannot find browser window"**:
  - Make sure Chrome/Edge is running and visible
  - On Linux, install `wmctrl`: `sudo apt-get install wmctrl`
  - On Windows, install `pygetwindow`: `pip install pygetwindow`
  - Run `test_window_detection.py` to debug window detection

#### Permission Issues
- **macOS Accessibility Permissions**:
  - Grant accessibility permissions to Terminal/iTerm
  - System Preferences → Security & Privacy → Privacy → Accessibility
  - Run `test_objc_window_detection.py` to test accessibility API permissions

- **File URL Limitations**:
  - File URLs (`file://`) may have security restrictions
  - Use HTTP URLs for testing when possible
  - Run `test_file_url_issue.py` to investigate file URL issues

#### High-DPI Display Issues
- **Incorrect scaling detection**:
  - Run `test_coordinate_finding.py` to validate DPI scaling detection
  - Check if multi-monitor setup is causing issues
  - Verify display scaling settings in system preferences

- **Retina display problems**:
  - macOS Retina displays use 2x scaling by default
  - Run `test_enhanced_coordinate_conversion.py` with precise test elements
  - Check if AppleScript fallback is working correctly

#### Testing-Specific Issues
- **Test failures**:
  - Ensure all dependencies are installed: `pip install aiohttp pyautogui keyboard`
  - Run tests with browser already running on port 9222
  - Check browser console for any error messages

- **AppleScript timeouts**:
  - macOS may prompt for accessibility permissions
  - Grant permissions to terminal application
  - Run `test_frontmost_window.py` to test AppleScript functionality

### Debug Mode

For detailed debugging:

1. **Enable verbose logging**: Modify test files to add `print()` statements
2. **Browser DevTools**: Use browser's developer tools to monitor WebSocket traffic
3. **Coordinate debugging**: Run `test_enhanced_coordinate_conversion.py` with precise test elements
4. **Window detection debugging**: Use `test_objc_window_detection.py` for detailed macOS window information
5. **Accessibility debugging**: Run accessibility permission tests with `test_objc_window_detection.py`

### Test-Specific Troubleshooting

- If `test_dom_inspector.py` fails: Check browser connection and page loading
- If coordinate tests fail: Verify DPI scaling detection and window positioning
- If window detection tests fail: Check platform-specific dependencies and permissions
- If AppleScript tests fail: Grant accessibility permissions to terminal app

## 🔍 Use Cases

### Web Development
- **CSS Debugging**: Understand style inheritance and specificity
- **Performance Analysis**: Identify unused styles and event listeners
- **Cross-Browser Testing**: Verify consistent styling across browsers

### QA Testing
- **Element Inspection**: Verify proper styling and behavior
- **Automated Testing**: Generate selectors and validate DOM structure
- **Accessibility Testing**: Check event handlers and semantic structure

### Learning & Education
- **Understanding CSS**: See how styles cascade and inherit
- **JavaScript Events**: Learn about event delegation and handlers
- **Browser Internals**: Explore how DevTools gather information

## 🧪 Testing

The project includes a comprehensive test suite to verify all functionality. Each test focuses on specific aspects of the DOM inspector.

### Running Tests

#### Run All Tests
```bash
# Run individual test files
python test_dom_inspector.py
python test_coordinate_finding.py
python test_enhanced_coordinate_conversion.py
```

#### Test Categories

##### Core Functionality Tests
- **`test_dom_inspector.py`** - Main comprehensive test suite
  - Tests browser connection, element finding, style extraction, and event listeners
  - Uses a new browser profile for isolated testing
  - Validates all major DOM inspector features

- **`test_manual_browser.py`** - Manual browser connection testing
  - Tests browser connection without auto-launch
  - Validates basic DOM inspector functionality
  - Useful for debugging browser connection issues

- **`test_real_website.py`** - Real website navigation testing
  - Tests navigation to external websites like baidu.com
  - Validates element finding on complex real-world pages
  - Ensures compatibility with production websites

- **`test_advanced_features.py`** - Advanced features testing
  - Tests style extraction on real websites
  - Validates event listener detection
  - Tests complex CSS selector functionality
  - Includes error handling tests

##### Coordinate System Tests
- **`test_coordinate_finding.py`** - Coordinate-based element finding
  - Tests finding elements by screen coordinates
  - Validates coordinate conversion accuracy
  - Tests browser UI offset calculation
  - Tests display scale factor detection

- **`test_enhanced_coordinate_conversion.py`** - High-DPI coordinate conversion
  - Comprehensive coordinate conversion testing
  - Tests with precisely positioned HTML elements
  - Validates DPI scaling detection accuracy
  - Tests screen-to-browser coordinate conversion
  - Includes reverse conversion validation

- **`test_mouse_selection.py`** - Mouse pointer selection functionality
  - Tests mouse-based element selection
  - Validates coordinate conversion for mouse input
  - Tests element selection at specific coordinates

##### Window Detection Tests
- **`test_browser_window_detection.py`** - Cross-platform window detection
  - Tests platform-specific window detection
  - Validates display scale factor detection
  - Tests coordinate system integration
  - Works on macOS, Windows, and Linux

- **`test_frontmost_window.py`** - Frontmost window requirements
  - Tests if browser window needs to be frontmost for detection
  - Uses AppleScript for detailed window information
  - Tests both background and foreground scenarios

- **`test_objc_window_detection.py`** - Objective-C/Cocoa API testing
  - Tests Objective-C/Cocoa API for window detection
  - Supports multiple browsers (Chrome, Edge, Safari, Firefox, Brave, Opera)
  - Tests accessibility API permissions
  - Tests alternative Objective-C approaches

- **`test_window_detection.py`** - Window detection accuracy
  - Tests window detection accuracy over multiple iterations
  - Validates window size and position detection
  - Tests DPI scaling factor detection
  - Tests browser UI offset calculation

##### Issue Investigation Tests
- **`test_file_url_issue.py`** - File URL element finding issues
  - Investigates file:// URL element finding problems
  - Compares file:// URL behavior with HTTP URLs
  - Tests DOM content availability with different URL schemes

### Test Development

When adding new features, follow these testing practices:
1. Create dedicated test files for new functionality
2. Include both unit tests and integration tests
3. Test on multiple platforms (macOS, Windows, Linux)
4. Test with different browsers (Chrome, Edge)
5. Include error handling and edge case testing

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and test thoroughly
4. Commit your changes: `git commit -m 'Add feature-name'`
5. Push to the branch: `git push origin feature-name`
6. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Chrome DevTools Protocol team for the comprehensive API
- Contributors to `aiohttp`, `pyautogui`, and other dependencies
- The web development community for inspiration and feedback

---

**Note**: This tool is for development and educational purposes. Always respect website terms of service and privacy policies when using automated inspection tools.