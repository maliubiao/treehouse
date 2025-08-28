# Chrome Context Tracer

一个强大的 DOM 检查工具，通过 Chrome DevTools Protocol (CDP) 复制 Chrome DevTools 功能。获取任何网页元素的详细 CSS 样式、事件监听器和 HTML 表示。

## 🌟 功能特性

### 🎯 智能元素选择
- **鼠标指针选择**: 使用热键支持 (`m` 键) 点选元素
- **CSS 选择器模式**: 传统的 CSS 选择器元素定位
- **智能窗口检测**: 自动检测 Chrome/Edge 浏览器窗口
- **高 DPI 支持**: 支持所有显示类型的精确坐标转换 (Retina, 4K 等)

### 🎨 完整样式分析
- **DevTools 兼容输出**: 与 Chrome DevTools 完全相同的格式
- **源文件信息**: 显示哪个 CSS 文件和行号影响每个样式
- **继承链**: 显示从父元素继承的样式
- **样式优先级**: 尊重 CSS 层叠和特异性规则
- **多来源支持**: 支持用户代理、作者和注入的样式表

### 🎧 事件监听器检查
- **完整事件分析**: 显示附加到元素的所有事件监听器
- **源位置**: 显示 JavaScript 文件、行号和函数信息
- **事件详情**: 捕获阶段、被动、一次性标志和处理程序信息
- **DevTools 格式**: 与 Chrome DevTools 事件监听器面板相同的输出

### 🌐 多浏览器支持
- **Chrome**: 全面支持 Google Chrome
- **Microsoft Edge**: 完全兼容 Edge 浏览器
- **跨平台**: 支持 macOS、Windows 和 Linux

## 🚀 安装

### 先决条件
确保已安装 Python 3.7+。

### 必需依赖
```bash
pip install aiohttp pyautogui keyboard
```

### 平台特定依赖

#### Windows
```bash
pip install pygetwindow
```

#### macOS (可选，用于增强 Retina 检测)
```bash
pip install pyobjc-framework-Cocoa
```

#### Linux
```bash
# 安装 wmctrl 用于窗口检测
sudo apt-get install wmctrl
```

## 🛠️ 设置

### 浏览器配置

#### Chrome
```bash
chrome --remote-debugging-port=9222
```

#### Microsoft Edge
```bash
msedge --remote-debugging-port=9222
```

## 📖 使用方法

### 鼠标指针选择模式 (推荐)
```bash
# 基本元素检查，使用鼠标选择
python dom_inspector.py --url "example.com" --from-pointer

# 完整分析: 样式 + 事件 + HTML
python dom_inspector.py --url "example.com" --from-pointer --events --html

# 自定义端口
python dom_inspector.py --url "localhost:3000" --from-pointer --port 9223
```

**工作原理:**
1. 运行命令
2. 将鼠标移动到网页上的目标元素
3. 按 `m` 键选择元素
4. 按 `q` 键退出选择模式

### CSS 选择器模式
```bash
# 使用 CSS 选择器定位特定元素
python dom_inspector.py --url "example.com" --selector ".my-class"

# 多种检查类型
python dom_inspector.py --url "example.com" --selector "#button" --events --html
```

### 命令行选项

| 选项 | 描述 | 默认值 |
|------|------|--------|
| `--url` | 匹配浏览器标签页的 URL 模式 | 必需 |
| `--selector` | CSS 选择器 (如果不使用 `--from-pointer`) | 可选 |
| `--from-pointer` | 启用鼠标指针选择模式 | False |
| `--events` | 显示事件监听器信息 | False |
| `--html` | 显示元素 HTML 表示 | False |
| `--port` | 浏览器调试端口 | 9222 |

## 📋 示例输出

### CSS 样式
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

### 事件监听器
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

### HTML 表示
```html
<button class="btn btn-primary" data-toggle="modal" onclick="handleClick()">
  点击我
  <span class="icon"></span>
</button>
```

## 🔧 技术细节

### 架构
- **Chrome DevTools Protocol**: 与浏览器调试 API 直接通信
- **异步操作**: 使用 `aiohttp` 实现高效的 WebSocket 通信
- **跨平台窗口管理**: 平台特定的窗口检测和坐标转换

### 坐标系统
工具处理复杂的坐标转换：
1. **物理屏幕坐标**: 原始鼠标位置
2. **DPI 缩放**: 自动高 DPI 显示缩放检测
3. **浏览器窗口坐标**: 相对于浏览器窗口
4. **视口坐标**: DOM API 的最终坐标

### 窗口检测架构

窗口检测系统采用多层方法：

1. **主要检测**: 平台特定的原生API
   - macOS: 辅助功能API (AXUIElement) 与 Objective-C/Cocoa
   - Windows: pygetwindow 与 Win32 API 集成
   - Linux: wmctrl 与 X11 窗口管理

2. **备用机制**:
   - macOS 辅助功能API失败时的 AppleScript 备用方法
   - 进程枚举进行浏览器识别
   - 按标题、类和可见性过滤窗口

3. **错误处理**:
   - API不可用时的优雅降级
   - 辅助功能权限处理
   - 跨平台兼容性检查

### 坐标转换工作流程

```
物理屏幕坐标
          ↓
DPI 缩放应用 (× 缩放因子)
          ↓
浏览器窗口检测 (位置 + 大小)
          ↓
浏览器UI偏移计算 (地址栏、标签页)
          ↓
视口坐标 (最终DOM位置)
          ↓
DOM元素选择
```

这种复杂的坐标转换系统确保在所有显示类型和浏览器配置下都能准确选择元素。

## 🐛 故障排除

### 常见问题

#### 浏览器连接问题
- **"未找到浏览器标签页"**: 
  - 确保浏览器正在运行远程调试: `chrome --remote-debugging-port=9222`
  - 检查 URL 模式是否匹配任何打开的标签页
  - 验证端口号是否正确
  - 使用 `test_manual_browser.py` 调试连接问题

- **"无法连接到浏览器"**:
  - 检查浏览器是否使用正确的调试端口运行
  - 验证防火墙是否阻止 WebSocket 连接
  - 尝试使用不同的端口号

#### 坐标转换问题
- **"鼠标位置与元素不匹配"**:
  - 工具自动处理 DPI 缩放
  - 确保浏览器窗口可见且未最小化
  - 尝试不同的元素或刷新页面
  - 运行 `test_enhanced_coordinate_conversion.py` 验证坐标准确性

- **"找不到浏览器窗口"**:
  - 确保 Chrome/Edge 正在运行且可见
  - 在 Linux 上，安装 `wmctrl`: `sudo apt-get install wmctrl`
  - 在 Windows 上，安装 `pygetwindow`: `pip install pygetwindow`
  - 运行 `test_window_detection.py` 调试窗口检测

#### 权限问题
- **macOS 辅助功能权限**:
  - 授予 Terminal/iTerm 辅助功能权限
  - 系统偏好设置 → 安全性与隐私 → 隐私 → 辅助功能
  - 运行 `test_objc_window_detection.py` 测试辅助功能API权限

- **文件URL限制**:
  - 文件URL (`file://`) 可能有安全限制
  - 尽可能使用 HTTP URL 进行测试
  - 运行 `test_file_url_issue.py` 调查文件URL问题

#### 高DPI显示问题
- **缩放检测不正确**:
  - 运行 `test_coordinate_finding.py` 验证DPI缩放检测
  - 检查多显示器设置是否导致问题
  - 验证系统偏好设置中的显示缩放设置

- **Retina显示问题**:
  - macOS Retina 显示默认使用2倍缩放
  - 使用精确测试元素运行 `test_enhanced_coordinate_conversion.py`
  - 检查 AppleScript 备用方法是否正常工作

#### 测试特定问题
- **测试失败**:
  - 确保所有依赖项已安装: `pip install aiohttp pyautogui keyboard`
  - 在端口9222上运行浏览器时运行测试
  - 检查浏览器控制台是否有错误消息

- **AppleScript 超时**:
  - macOS 可能提示辅助功能权限
  - 授予终端应用程序权限
  - 运行 `test_frontmost_window.py` 测试 AppleScript 功能

### 调试模式

要进行详细调试：

1. **启用详细日志记录**: 修改测试文件添加 `print()` 语句
2. **浏览器开发者工具**: 使用浏览器的开发者工具监控 WebSocket 流量
3. **坐标调试**: 使用精确测试元素运行 `test_enhanced_coordinate_conversion.py`
4. **窗口检测调试**: 使用 `test_objc_window_detection.py` 获取详细的 macOS 窗口信息
5. **辅助功能调试**: 使用 `test_objc_window_detection.py` 运行辅助功能权限测试

### 测试特定故障排除

- 如果 `test_dom_inspector.py` 失败: 检查浏览器连接和页面加载
- 如果坐标测试失败: 验证DPI缩放检测和窗口定位
- 如果窗口检测测试失败: 检查平台特定依赖项和权限
- 如果 AppleScript 测试失败: 授予终端应用程序辅助功能权限

## 🔍 使用场景

### Web 开发
- **CSS 调试**: 理解样式继承和特异性
- **性能分析**: 识别未使用的样式和事件监听器
- **跨浏览器测试**: 验证跨浏览器的一致性样式

### QA 测试
- **元素检查**: 验证正确的样式和行为
- **自动化测试**: 生成选择器和验证 DOM 结构
- **可访问性测试**: 检查事件处理程序和语义结构

### 学习与教育
- **理解 CSS**: 查看样式如何层叠和继承
- **JavaScript 事件**: 了解事件委托和处理程序
- **浏览器内部**: 探索 DevTools 如何收集信息

## 📄 许可证

本项目采用 MIT 许可证 - 详见 LICENSE 文件。

## 🙏 致谢

- Chrome DevTools Protocol 团队提供全面的 API
- `aiohttp`、`pyautogui` 和其他依赖项的贡献者
- Web 开发社区的灵感和反馈

---

**注意**: 此工具用于开发和教育目的。使用自动化检查工具时，请始终尊重网站的服务条款和隐私政策。