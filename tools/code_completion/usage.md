# AI Code Completer - User Guide

This document provides a comprehensive guide to using, configuring, and developing the "AI Code Completer" VS Code extension.

## Overview

AI Code Completer empowers you to leverage Large Language Models (LLMs) like those from OpenAI or DeepSeek to refactor, complete, or generate code directly within your editor. It is designed to be a seamless and interactive part of your development workflow.

## Features

-   **Instruction-Based Code Generation**: Select a block of code, press a keybinding, and provide a natural language instruction (e.g., "Add error handling" or "Convert this to an async function").
-   **Context-Aware Selection**: If you don't select any code, the extension automatically identifies the enclosing function or class at your cursor's position to use as context.
-   **Interactive Diff View**: AI suggestions are not applied automatically. A clean side-by-side diff view is presented, allowing you to review every change before accepting.
-   **Configurable Backend**: Easily configure the API endpoint, API key, and model name to work with any OpenAI-compatible service.
-   **Customizable Prompts**: Tailor the system prompt to fit your specific needs or coding standards.
-   **Safe Undo**: A dedicated command to revert the last AI-driven change, ensuring you can always go back.

## How to Use

The primary workflow is simple and designed to be non-intrusive.

1.  **Select Code (Optional)**: Highlight a piece of code in your editor you wish to modify. If you don't make a selection, the extension will automatically detect the function or class your cursor is in.
2.  **Trigger Command**: Press `Cmd+Alt+I` (on macOS) or `Ctrl+Alt+I` (on Windows/Linux).
3.  **Provide Instruction**: An input box will appear at the top of your screen. Type your instruction (e.g., "Add comprehensive JSDoc comments") and press `Enter`.
4.  **Review Diff**: The extension will communicate with the AI. Once a suggestion is ready, a new tab will open showing a diff between your original code and the AI's suggestion.
5.  **Accept or Reject**: A notification will appear with "Accept" and "Reject" buttons.
    -   Clicking **Accept** applies the changes to your source file.
    -   Clicking **Reject** discards the suggestion and closes the diff view.

## Commands and Keybindings

The extension contributes the following commands to the command palette (`Cmd/Ctrl+Shift+P`):

| Command Title                 | Command ID                             | Default Keybinding     |
| ----------------------------- | -------------------------------------- | ---------------------- |
| AI: Generate/Refactor Code    | `ai-code-completer.generateCode`       | `Cmd/Ctrl+Alt+I`       |
| AI: Undo Last Generation      | `ai-code-completer.undoLastGeneration` | (none)                 |

## Configuration

You can configure the extension by navigating to `Code > Settings > Settings` and searching for "AI Code Completer".

---

#### `aiCodeCompleter.api.baseUrl`

-   **Description**: The base URL of the OpenAI-compatible API.
-   **Type**: `string`
-   **Default**: `"https://api.openai.com/v1"`
-   **Examples**:
    -   For OpenAI: `https://api.openai.com/v1`
    -   For DeepSeek: `https://api.deepseek.com`

---

#### `aiCodeCompleter.api.apiKey`

-   **Description**: Your secret API key for the service. It is highly recommended to let VS Code handle this via its secret storage for security. You will be prompted to enter it securely the first time.
-   **Type**: `string`
-   **Default**: `""`

---

#### `aiCodeCompleter.api.model`

-   **Description**: The specific model you want to use for code generation.
-   **Type**: `string`
-   **Default**: `"gpt-4o"`
-   **Examples**: `"deepseek-coder"`, `"gpt-4-turbo"`, `"gpt-3.5-turbo"`

---

#### `aiCodeCompleter.prompt.systemMessage`

-   **Description**: The master system prompt that guides the AI's behavior. You can customize this to enforce specific coding styles or architectural principles.
-   **Type**: `string`
-   **Default**: `"You are an expert software architect and programmer. The user will provide a block of code and an instruction. Your task is to rewrite the code according to the instruction. Only output the raw, modified code block. Do not include any explanations, markdown, or language specifiers like \`\`\`python."`

---

#### `aiCodeCompleter.prompt.usePrefixCompletion`

-   **Description**: Enable this for models that use a specific prefix-based completion format (e.g., some versions of DeepSeek Coder Instruct). If true, the prompt is sent in a special `<｜fim begin｜>...<｜fim hole｜>...<｜fim end｜>` format, where the model is expected to fill in the "hole". For most standard chat models (like GPT series), this should be `false`.
-   **Type**: `boolean`
-   **Default**: `false`

## Building from Source

If you want to contribute to the development or build the extension yourself, follow these steps:

1.  **Clone the Repository**:
    ```sh
    git clone <repository-url>
    cd ai-code-completer
    ```
2.  **Install Dependencies**:
    ```sh
    # Using npm
    npm install

    # Or using pnpm
    pnpm install
    ```
3.  **Compile the Code**:
    ```sh
    # For a single build
    npm run compile

    # To watch for changes and recompile automatically
    npm run watch
    ```
4.  **Run in VS Code**:
    -   Open the project folder in VS Code.
    -   Press `F5` to open a new Extension Development Host window.
    -   The extension will be active in this new window, and you can test your changes.
