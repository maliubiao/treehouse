# Chrome Context Tracer

一个强大的命令行工具，可将 Chrome DevTools 的核心功能带到您的终端。它基于 Chrome DevTools Protocol (CDP) 构建，允许您在不离开终端的情况下检查 DOM 元素、分析 CSS、追踪事件监听器以及调试 JavaScript 执行。

## 🌟 功能特性

### 🕵️‍♀️ DOM 检查 (`inspect`)
- **智能元素选择**:
  - **鼠标指针模式**: 通过一个浏览器内覆盖层，您只需点击页面上的任何元素即可选中并进行检查。该功能通过稳定的 JavaScript 注入实现，完全跨平台。
  - **CSS 选择器模式**: 使用标准的 CSS 选择器精确定位目标元素。
- **完整的样式分析**:
  - **DevTools 兼容输出**: 以与 Chrome DevTools "样式" 面板完全相同的格式获取 CSS 样式。
  - **来源信息**: 查看每个样式来源于哪个 CSS 文件以及具体的行号。
  - **继承链**: 查看从父元素继承的样式。
- **事件监听器检查**:
  - **全面的事件分析**: 列出附加到元素及其祖先（直到 `window` 对象）的所有事件监听器。
  - **来源定位**: 精确显示每个监听器所在的 JavaScript 文件、行号和函数。

### 🐛 JavaScript 调试 (`trace`)
- **Debugger 追踪**: 激活追踪模式，监听您 JavaScript 代码中的 `debugger;` 语句。
- **丰富的调用栈**: 当命中 `debugger;` 语句时，工具会打印出一个完整且易于阅读的调用栈。
- **变量检查**: 输出内容包含暂停时刻调用栈中每个作用域内的局部变量名及其值。
- **自动恢复**: 在打印调用栈信息后，脚本会自动恢复执行，从而实现非侵入式的调试日志记录。

### 🌐 通用特性
- **多浏览器支持**: 与 Google Chrome 和 Microsoft Edge 无缝协作。
- **跨平台**: 在 macOS、Windows 和 Linux 上功能完整。
- **自动启动浏览器**: 如果在指定端口上找不到正在运行的浏览器实例，它可以自动为您启动一个启用了远程调试的浏览器。

## 🚀 安装

### 先决条件
- Python 3.7+
- 已安装的 Google Chrome 或 Microsoft Edge 浏览器。

### 依赖
该工具只有一个核心依赖：`aiohttp`。

```bash
pip install aiohttp
```

## 🛠️ 设置

为了让工具能够连接，您需要启动浏览器并启用远程调试端口。

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
命令类似，只需替换可执行文件名（例如 `msedge`）。

**提示**: 如果工具在指定端口上找不到正在运行的实例，它也会尝试为您**自动启动**一个浏览器。

## 📖 使用方法

该工具分为两个主要命令：`inspect` 和 `trace`。

### `inspect` - 检查 DOM 元素
此命令用于分析特定元素的 HTML、CSS 和事件监听器。

#### 使用鼠标指针选择 (推荐)
这是选择元素最简单的方式。
```bash
# 通过点击元素来检查其样式、事件和 HTML
python dom_inspector.py inspect --url "example.com" --from-pointer --events --html
```
**工作原理:**
1. 运行命令，浏览器内将激活一个覆盖层。
2. 移动鼠标以高亮显示元素。
3. **点击** 目标元素以选中它。
4. 按 `ESC` 键可取消选择。

#### 使用 CSS 选择器
```bash
# 仅检查 ID 为 'main-content' 的元素的样式
python dom_inspector.py inspect --url "example.com" --selector "#main-content"

# 获取 class 为 '.btn-primary' 的元素的事件和 HTML
python dom_inspector.py inspect --url "example.com" --selector ".btn-primary" --events --html
```

### `trace` - 追踪 JavaScript 执行
此命令监听 `debugger;` 语句并打印调用栈。

```bash
# 附加到一个标签页并等待 debugger 语句
python dom_inspector.py trace --url "example.com"
```
一旦附加成功，页面 JavaScript 中任何时候执行 `debugger;` 语句，其上下文信息都将被打印到您的终端。

## 命令行选项

### 全局选项
| 选项 | 描述 | 默认值 |
|--------|-------------|---------|
| `--port` | 浏览器远程调试协议的端口。 | `9222` |

### `inspect` 命令
| 选项 | 描述 |
|--------|-------------|
| `--url` | 用于查找目标浏览器标签页的 URL 模式。如果省略，将提供列表供您选择。 |
| `--selector` | 要检查的元素的 CSS 选择器。 |
| `--from-pointer` | 使用交互式的、基于浏览器内鼠标操作的选择模式。 |
| `--events` | 显示附加到该元素的事件监听器。 |
| `--html` | 显示该元素的 outer HTML。 |

*注意: 您必须提供 `--selector` 或 `--from-pointer` 中的一个。*

### `trace` 命令
| 选项 | 描述 |
|--------|-------------|
| `--url` | 用于查找目标浏览器标签页的 URL 模式。如果省略，将提供列表供您选择。 |

## 📋 示例输出

### CSS 样式 (`inspect`)
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

### 事件监听器 (`inspect`)
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

### Debugger 追踪 (`trace`)
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

## 🔧 技术细节

该工具通过 WebSocket 直接使用 **Chrome DevTools Protocol (CDP)** 与浏览器进行通信。

交互式元素选择模式 (`--from-pointer`) 是通过向目标页面注入一个 JavaScript 模块来实现的。该脚本会在页面上创建一个覆盖层，高亮鼠标下的元素并捕获点击事件。当用户选择一个元素时，脚本会通过 `console.log` 发送一条带有唯一前缀和该元素唯一 CSS 选择器的消息。Python 后端会监听这条特定的控制台消息，解析出选择器，然后通过 CDP 使用该选择器执行检查。这种方法避免了脆弱的、依赖操作系统的屏幕坐标计算，并且能在所有平台和显示分辨率下可靠地工作。

## 🧪 测试

项目包含一个全面的测试套件以确保其可靠性。

### 运行测试
您可以单独运行测试文件：
```bash
python test_dom_inspector.py
python test_debugger_trace.py
```

### 测试概览
- **`test_dom_inspector.py`**: `inspect` 命令的端到端测试，覆盖元素查找、样式提取和事件监听器。
- **`test_debugger_trace.py`**: `trace` 命令的集成测试，验证它能正确捕获 `debugger;` 语句并打印带变量的调用栈。
- ... 以及许多其他针对连接、工具函数和特定功能的测试。

## 🤝 贡献

欢迎贡献！请随时 Fork 本仓库，进行修改，然后提交 Pull Request。

## 📄 许可证

本项目采用 MIT 许可证。