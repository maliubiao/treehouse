# Treehouse Code Completer

[![VS Code Extension Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://marketplace.visualstudio.com/items?itemName=local-dev.treehouse-code-completer)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**目录**

-   [概述](#概述)
-   [核心特性](#核心特性)
-   [高级特性](#高级特性)
-   [性能优化](#性能优化)
-   [国际化支持](#国际化支持)
-   [工作流演示](#工作流演示)
-   [命令与快捷键](#命令与快捷键)
-   [配置指南](#配置指南)
-   [工作原理](#工作原理)
-   [开发者指南](#开发者指南)
-   [错误处理与日志](#错误处理与日志)
-   [许可证](#许可证)

**Treehouse Code Completer** 是一款功能强大且直观的 VS Code 插件，它将大型语言模型（LLM）无缝集成到您的日常编码工作流中。通过简单的自然语言指令，您就可以重构、增强或生成代码片段。

## 概述

您是否厌倦了重复的编码任务？需要添加文档、编写测试，或将函数转换为不同的范式？Treehouse Code Completer 是您的 AI 工程伙伴。只需选中一个代码块（或让插件智能选择上下文），提供一条指令，然后在清晰的交互式差异（Diff）视图中审查 AI 生成的建议，最后决定是否应用。

## 核心特性

-   **指令驱动的代码生成**：选中任意代码，按下快捷键，然后告诉 AI 您想做什么（例如，"添加错误处理"或"将此转换为异步函数"）。
-   **智能上下文感知（包括Imports）**：插件不仅能自动识别光标所在位置的函数/类作为上下文，还能**自动提取并更新`import`语句**。如果代码修改需要新的依赖，AI 会一并处理。
-   **交互式差异视图**：AI 的建议从不盲目应用。插件会呈现一个清晰的并排差异视图，让您在接受前审查每一处更改。
-   **直观的UI界面**：当AI建议准备好时，会在差异视图旁边自动显示一个美观的Webview面板，提供清晰的接受/拒绝按钮和快捷键提示。
-   **图形化设置界面**：一个用户友好的 Webview 界面，用于管理多个 AI 服务配置、测试 API 连接、自定义提示词，甚至在"游乐场"中进行实验。
-   **可中断的操作**：支持在代码生成过程中取消操作，立即中止请求并清理资源。
-   **流式响应处理**：实时显示AI生成的代码片段，无需等待完整响应，提升用户体验。
-   **详细的token使用统计**：在操作完成后显示精确的token使用量和预估成本（基于用户配置的定价）。
-   **高度可配置**：轻松配置 API 端点、密钥和模型，以适配任何与 OpenAI 兼容的服务（如 DeepSeek, Groq, Ollama等）。
-   **可定制的提示词**：量身定制主系统提示词并添加自定义规则，以强制执行特定的编码风格或架构原则。
-   **安全撤销**：提供专门的命令，可立即撤销上一次 AI 驱动的更改，确保一切尽在掌控。
-   **代理支持**：自动检测并使用VS Code的HTTP代理设置，确保在企业网络环境中也能正常工作。
-   **AST-based 上下文检测**：使用文档抽象语法树解析，精确定位光标所在的函数、类或方法。
-   **多语言导入支持**：智能识别各种编程语言的导入语句，包括多行导入和带括号/大括号的导入块。
-   **Shebang 和注释处理**：自动跳过文件头的 shebang 行和文档注释，准确提取导入语句。
-   **标签状态跟踪**：智能监控差异视图标签页的状态，处理手动关闭和标签切换。
-   **选择位置恢复**：应用更改后尝试恢复原始光标位置和选区。

## 高级特性

-   **前缀完成模式**：可选的配置模式，将选中的代码视为完成的前缀而非替换目标，AI 将在此基础上继续编写代码。
-   **调试流式数据**：开发者选项，可记录原始流式响应数据，便于调试和问题排查。
-   **上下文键系统**：使用 VS Code 上下文键（`treehouseCodeCompleter.diffViewActive`）管理 UI 状态，实现更精确的界面控制。
-   **临时文件管理**：智能的临时文件创建和清理系统，确保差异视图的顺畅运行。
-   **会话持久化**：跨操作维护会话状态，支持标签页切换后的状态恢复。
-   **面板生命周期管理**：精细的 Webview 面板生命周期控制，包括显示、隐藏和销毁。
-   **成本跟踪**：基于用户配置的定价信息，实时计算并显示 API 调用成本。

## 性能优化

-   **大文件智能处理**：对于超过 32KB 的文件，自动启用智能上下文模式，仅发送相关代码片段。
-   **流式响应处理**：使用 StreamingAccumulator 类实现高效的流式数据处理，提供即时反馈。
-   **上下文裁剪**：智能裁剪上下文以避免超出 token 限制，同时保持相关性。
-   **资源自动清理**：操作完成后自动清理临时文件和会话状态，防止内存泄漏。

## 国际化支持

-   **多语言界面**：完整支持英文和中文界面。
-   **动态语言切换**：支持运行时语言切换，无需重启插件。
-   **本地化字符串**：所有 UI 元素都支持本地化，包括错误消息和提示文本。
-   **Webview 国际化**：Webview 界面继承 VS Code 的语言设置，提供一致的用户体验。

## 工作流演示

主要工作流程被设计得简洁且无干扰。

1.  **选择代码 (可选)**：高亮一段代码。如果您不这样做，插件将自动寻找光标所在的函数/类。
2.  **触发命令**：按下 `Cmd+Alt+I` (macOS) 或 `Ctrl+Alt+I` (Windows/Linux)。
3.  **提供指令**：屏幕顶部会出现一个输入框。输入您的指令（例如，“添加完整的 JSDoc 注释"）并按 `Enter`。
4.  **监控进度**：在与 AI 通信期间，屏幕右下角会显示进度通知，显示已生成的 token 数量。您可以随时点击取消按钮来中止操作。
    -   **流式响应**：您将看到代码逐步生成，而不是等待完整响应。
    -   **实时token统计**：随着生成进行，token计数会实时更新。
5.  **审查差异**：插件与 AI 通信后，会打开一个新标签页，显示您的原始代码与 AI 建议之间的差异。这包括对您代码和`import`语句的任何更改。
6.  **接受或拒绝**：一个直观的Webview面板会在差异视图旁边自动打开，提供清晰的接受/拒绝按钮和快捷键提示。
    -   点击 **✓ 接受更改** 按钮将更改应用到您的源文件中。
    -   点击 **✗ 拒绝更改** 按钮将丢弃建议并关闭差异视图。
    -   也可以使用快捷键：`Cmd/Ctrl+Alt+Y` 接受，`Cmd/Ctrl+Alt+N` 拒绝。

## 命令与快捷键

| 命令标题 | 命令 ID | 默认快捷键 |
| --- | --- | --- |
| Treehouse: 生成/重构代码 | `treehouse-code-completer.generateCode` | `Cmd/Ctrl+Alt+I` |
| Treehouse: 打开设置 | `treehouse-code-completer.openSettings` | (无) |
| Treehouse: 撤销上次生成 | `treehouse-code-completer.undoLastGeneration` | (无) |
| Treehouse: 打开Webview开发者工具 | `treehouse-code-completer.openWebviewDeveloperTools` | (无) |
| Treehouse: 接受AI建议 | `treehouse-code-completer.acceptChanges` | `Cmd/Ctrl+Alt+Y` |
| Treehouse: 拒绝AI建议 | `treehouse-code-completer.rejectChanges` | `Cmd/Ctrl+Alt+N` |

## 配置指南

推荐通过 **图形化设置界面** 来配置本插件。

### 图形化设置界面 (推荐)

1.  打开命令面板 (`Cmd/Ctrl+Shift+P`)。
2.  运行命令 `Treehouse: Open Settings`。
3.  在此 Webview 中，您可以：
    -   **添加、编辑和删除** 多个 AI 服务配置。
    -   **设置一个活动服务** 用于代码 generation。
    -   为任何服务 **测试 API 连接**，以确保您的凭据正确无误。
    -   将所有服务配置 **导入/导出** 为一个 JSON 文件。
    -   **自定义** 全局系统提示词和自定义规则。
    -   **使用游乐场** 向任何已配置的服务发送测试提示。

### 服务配置详解

每个AI服务配置包含以下参数：

```json
{
  "name": "服务名称（唯一标识）",
  "model_name": "模型名称（如gpt-4o）",
  "base_url": "API基础URL（支持OpenAI兼容接口）",
  "key": "API密钥",
  "temperature": "采样温度（0.0-2.0）",
  "max_tokens": "最大生成token数",
  "max_context_size": "最大上下文token数（用于智能上下文裁剪）",
  "timeout_seconds": "API请求超时时间（秒）",
  "price_1M_input": "每百万输入token价格（美元）",
  "price_1M_output": "每百万输出token价格（美元）",
  "supports_json_output": "是否支持JSON模式输出",
  "is_thinking": "内部状态，无需手动设置"
}
```

### 手动 `settings.json` 配置

您也可以直接在您的 `settings.json` 文件中配置本插件。

-   **`treehouseCodeCompleter.services`**: 一个服务对象的数组。您可以在此存储不同 AI 提供商的凭据。
    ```json
    "treehouseCodeCompleter.services": [
        {
            "name": "OpenAI-GPT4o",
            "base_url": "https://api.openai.com/v1",
            "model_name": "gpt-4o",
            "key": "sk-...",
            "temperature": 0.1,
            "max_tokens": 8192,
            "max_context_size": 128000,
            "timeout_seconds": 60,
            "price_1M_input": 5.00,
            "price_1M_output": 15.00,
            "supports_json_output": true
        }
    ]
    ```

-   **`treehouseCodeCompleter.activeService`**: 要用于代码生成的服务 `name` (来自上面的列表)。
    ```json
    "treehouseCodeCompleter.activeService": "OpenAI-GPT4o"
    ```

-   **`treehouseCodeCompleter.prompt.systemMessage`**: 指导 AI 行为的主系统提示词。

-   **`treehouseCodeCompleter.prompt.rule`**: 附加到每个提示的自定义规则 (例如, "所有函数必须包含 JSDoc 块。")。

-   **`treehouseCodeCompleter.output.streamingResults`**: 是否启用流式结果输出（默认为true）

-   **`treehouseCodeCompleter.output.prefixCompletionMode`**: 前缀完成模式开关。启用时，选中的代码将被视为完成的前缀而非替换目标（默认为false）

-   **`treehouseCodeCompleter.debug.debugStreamingChunks`**: 调试选项，启用后将记录原始流式响应数据到输出通道（默认为false）

## 工作原理

本插件使用一套复杂的机制来为 AI 提供相关上下文：

1.  **上下文检测**：
    *   **目标代码**：如果您有活动的选区，则使用该代码。否则，插件会解析文档的抽象语法树（AST）以找到光标所在的符号（函数、类、方法）。
    *   **导入块**：插件会自动扫描文件头部，提取出所有 `import` 或 `require` 语句作为一个独立的上下文块。
    *   **多语言支持**：智能识别各种编程语言的导入语句，包括多行导入和带括号/大括号的导入块。
    *   **特殊处理**：自动跳过 shebang 行和文档注释，确保准确提取导入语句。

2.  **大文件的智能上下文**：对于大于 32KB 的文件，插件不会发送整个文件，而是仅发送**导入块**、目标代码块以及其之前和之后的符号代码，从而在不超出 token 限制的情况下提供专注且相关的上下文。

3.  **提示词工程**：插件会构建一个详细的提示，包括文件路径、**导入块**、待修改的代码、您的指令、文件的完整或智能上下文，以及您定义的任何自定义规则。

4.  **结构化响应**：AI被指示返回一个包含两部分的响应，使用XML风格标签进行标记：
    *   `<UPDATED_IMPORTS>` - 包含更新后的导入语句
    *   `<UPDATED_CODE>` - 包含更新后的目标代码
    插件解析这个结构化响应，以确保两部分更改都能被正确应用。

5.  **流式处理**：使用StreamingAccumulator类实时处理流式响应：
    *   管理流式会话状态
    *   实时显示生成的代码
    *   处理中断和取消操作
    *   提供调试日志功能

6.  **会话管理**：
    *   跟踪活跃的差异视图会话
    *   使用上下文键（`treehouseCodeCompleter.diffViewActive`）管理UI状态
    *   处理标签页切换和手动关闭
    *   自动清理临时文件和会话状态

7.  **面板管理**：
    *   Webview面板的生命周期控制
    *   与差异视图同步显示
    *   传递国际化配置
    *   处理用户交互事件

8.  **成本计算**：基于用户配置的定价信息，精确计算每次调用的成本，包括输入和输出token的分别计价。

## 开发者指南

想要贡献代码或自行构建此插件？

### 环境设置

1.  **克隆仓库**:
    ```sh
    git clone <repository-url>
    cd treehouse-code-completer
    ```
2.  **安装依赖**:
    ```sh
    pnpm install
    ```

### 开发与测试

1.  **编译并监视文件变化**:
    ```sh
    pnpm run watch
    ```
2.  **在 VS Code 中运行**:
    -   在 VS Code 中打开项目文件夹。
    -   按 `F5` 打开一个新的"扩展开发宿主"窗口。
    -   插件将在此新窗口中激活以供测试。

3.  **运行测试**:
    ```sh
    pnpm test
    ```
    或者
    ```sh
    pnpm test:watch
    ```
    测试使用Jest框架，覆盖了核心功能和边缘情况。

4.  **构建生产版本**:
    ```sh
    pnpm run package
    ```

### 项目架构

```
src/
├── api/                # LLM API客户端和通信逻辑
│   └── llmClient.ts    # LLM API调用实现
├── commands/           # VS Code命令实现
│   ├── generateCode.ts # 主要的代码生成命令
│   └── ...
├── config/             # 配置管理
│   └── configuration.ts # 配置读取和验证
├── extension.ts        # 插件入口点
├── state/              # 会话和状态管理
│   ├── sessionManager.ts # 差异视图会话管理
│   └── undoManager.ts   # 撤销操作管理
├── types.ts            # 全局类型定义
├── ui/                 # 用户界面组件
│   ├── interactions.ts  # 用户交互处理
│   ├── panelManager.ts  # Webview面板管理
│   └── settingsView.ts  # 设置界面
├── util/               # 工具函数
│   └── i18n.ts         # 国际化支持
├── utils/              # 工具函数和辅助类
│   ├── document.ts     # 文档操作工具
│   ├── logger.ts       # 日志记录
│   ├── streamingAccumulator.ts # 流式响应处理
│   └── tempFileManager.ts     # 临时文件管理
├── webview/            # Webview界面资源
│   ├── index.html      # 主页面
│   ├── main.ts         # 前端逻辑
│   └── styles.css      # 样式文件
├── history/            # 历史记录（预留）
├── locales/            # 本地化文件
│   ├── en/             # 英文
│   └── zh/             # 中文
└── __tests__/          # 测试用例
    ├── api/            # API测试
    ├── commands/       # 命令测试
    ├── config/         # 配置测试
    ├── state/          # 状态管理测试
    ├── ui/             # UI测试
    └── utils/          # 工具函数测试
```

### 关键设计决策

- **流式响应处理**：使用StreamingAccumulator类提供实时反馈，提升用户体验
- **智能上下文管理**：针对大文件优化上下文提取，避免token超限
- **结构化响应解析**：通过XML风格标签确保代码和导入语句的正确分离
- **健壮的错误处理**：详细的错误分类和用户友好的错误消息
- **类型安全**：严格的TypeScript类型定义，确保代码质量和可维护性
- **可测试性**：模块化设计，便于单元测试和集成测试
- **国际化架构**：基于VS Code语言设置的动态本地化系统
- **会话状态管理**：使用上下文键和事件监听实现精细的状态控制
- **资源生命周期**：自动化的临时文件和会话清理机制

## 错误处理与日志

- **详细的错误分类**：区分API错误、网络错误、配置错误等
- **用户友好的错误消息**：提供明确的操作建议
- **详细的日志记录**：所有操作和错误都会记录到"Treehouse Code Completer"输出通道
- **错误详情查看**：在错误消息中提供"Show Details"选项，可查看完整错误日志

## 许可证

本项目基于 [MIT 许可证](LICENSE) 发布。