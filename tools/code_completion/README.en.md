# Treehouse Code Completer

[![VS Code Extension Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://marketplace.visualstudio.com/items?itemName=local-dev.treehouse-code-completer)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Treehouse Code Completer** is a powerful and intuitive VS Code extension that seamlessly integrates Large Language Models (LLMs) into your daily coding workflow. It allows you to refactor, enhance, or generate code snippets by simply providing natural language instructions.

## Overview

Tired of repetitive coding tasks? Need to add documentation, write tests, or convert a function to a different paradigm? Treehouse Code Completer is your AI engineering partner. Select a block of code (or let the extension intelligently select the context for you), provide an instruction, and review the AI-generated suggestions in a clean, interactive diff view before applying them.

## Core Features

-   **Instruction-Based Code Generation**: Select any code, press a keybinding, and tell the AI what to do (e.g., "Add error handling" or "Convert this to an async function").
-   **Context-Aware Selection**: If you don't select any code, the extension automatically identifies the enclosing function or class at your cursor's position to use as context.
-   **Interactive Diff View**: AI suggestions are never applied blindly. A clear side-by-side diff view is presented, allowing you to review every change before accepting.
-   **Graphical Settings UI**: A user-friendly webview interface to manage multiple AI service configurations, test API connections, customize prompts, and even experiment in a playground.
-   **Highly Configurable**: Easily configure API endpoints, keys, and models to work with any OpenAI-compatible service (like DeepSeek, Groq, etc.).
-   **Customizable Prompts**: Tailor the master system prompt and add custom rules to enforce specific coding styles or architectural principles.
-   **Safe Undo**: A dedicated command to instantly revert the last AI-driven change, ensuring you're always in control.

## Workflow in Action

The primary workflow is designed to be simple and non-intrusive.

1.  **Select Code (Optional)**: Highlight a piece of code. If you don't, the extension will find the function/class your cursor is in.
2.  **Trigger Command**: Press `Cmd+Alt+I` (macOS) or `Ctrl+Alt+I` (Windows/Linux).
3.  **Provide Instruction**: An input box appears. Type your instruction (e.g., "Add comprehensive JSDoc comments") and press `Enter`.
4.  **Review Diff**: The extension communicates with the AI. A new tab opens showing a diff between your original code and the AI's suggestion.
5.  **Accept or Reject**: A notification appears with "Accept" and "Reject" buttons.
    -   Clicking **Accept** applies the changes to your source file.
    -   Clicking **Reject** discards the suggestion and closes the diff view.

## Commands and Keybindings

| Command Title                        | Command ID                                    | Default Keybinding |
| ------------------------------------ | --------------------------------------------- | ------------------ |
| Treehouse: Generate/Refactor Code    | `treehouse-code-completer.generateCode`       | `Cmd/Ctrl+Alt+I`   |
| Treehouse: Open Settings             | `treehouse-code-completer.openSettings`       | (none)             |
| Treehouse: Undo Last Generation      | `treehouse-code-completer.undoLastGeneration` | (none)             |
| Treehouse: Open Webview Developer Tools | `treehouse-code-completer.openWebviewDeveloperTools` | (none)             |

## Configuration Guide

The recommended way to configure the extension is through the **Graphical Settings UI**.

### Graphical Settings UI (Recommended)

1.  Open the Command Palette (`Cmd/Ctrl+Shift+P`).
2.  Run the command `Treehouse: Open Settings`.
3.  In the webview, you can:
    -   **Add, Edit, and Delete** multiple AI service configurations.
    -   **Set an Active Service** for code generation.
    -   **Test API Connection** for any service to ensure your credentials are correct.
    -   **Import/Export** all your service configurations as a single JSON file.
    -   **Customize** the global System Prompt and a custom Rule.
    -   **Use the Playground** to send test prompts to any configured service.

### Manual `settings.json` Configuration

You can also configure the extension directly in your `settings.json` file.

-   **`treehouseCodeCompleter.services`**: An array of service objects. This is where you store credentials for different AI providers.
    ```json
    "treehouseCodeCompleter.services": [
        {
            "name": "OpenAI-GPT4o",
            "base_url": "https://api.openai.com/v1",
            "model_name": "gpt-4o",
            "key": "sk-...",
            "temperature": 0.1,
            "max_tokens": 8192,
            // ... other properties
        }
    ]
    ```

-   **`treehouseCodeCompleter.activeService`**: The `name` of the service from the list above to use for generations.
    ```json
    "treehouseCodeCompleter.activeService": "OpenAI-GPT4o"
    ```

-   **`treehouseCodeCompleter.prompt.systemMessage`**: The master system prompt that guides the AI's behavior.

-   **`treehouseCodeCompleter.prompt.rule`**: A custom rule appended to every prompt (e.g., "All functions must include a JSDoc block.").

## How It Works

The extension uses a sophisticated approach to provide relevant context to the AI:

1.  **Context Detection**: If you have an active selection, that code is used. If not, the extension parses the document's Abstract Syntax Tree (AST) to find the symbol (function, class, method) your cursor is inside.
2.  **Smart Context for Large Files**: For files larger than 32KB, instead of sending the entire file, the extension sends only the code of the symbols immediately preceding and succeeding the target block, providing focused and relevant context without exceeding token limits.
3.  **Prompt Engineering**: A detailed prompt is constructed including the file path, the code to modify, your instruction, the file's full or smart context, and any custom rules you've defined.

## For Developers

Want to contribute or build the extension yourself?

1.  **Clone the Repository**:
    ```sh
    git clone <repository-url>
    cd treehouse-code-completer
    ```
2.  **Install Dependencies**:
    ```sh
    pnpm install
    ```
3.  **Compile and Watch**:
    ```sh
    pnpm run watch
    ```
4.  **Run in VS Code**:
    -   Open the project folder in VS Code.
    -   Press `F5` to open a new Extension Development Host window.
    -   The extension will be active in this new window for testing.

## License

This project is licensed under the [MIT License](LICENSE).