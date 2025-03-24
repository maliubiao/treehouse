# terminal LLM

A terminal assistant tool based on OpenAI-compatible APIs, providing convenient CLI interaction and context-aware capabilities. Designed as a command-line version of Cursor/Windsurf, optimized for Deepseek R1.

## Use Cases

Mix multiple `@` contexts in a single `askgpt` command. Supports combining URLs, file contents, and special syntax without quotes (note shell special characters like `>`):

```bash
# Fix code bugs and generate diff/patch
askgpt @edit @main.py Find potential bugs and fix them

# Analyze clipboard content
askgpt Explain this code: @clipboard @tree

# Command suggestion
askgpt @cmd Find all files modified 2 hours ago and delete them

# Attach directory structure
askgpt "@tree, analyze main modules"

# Attach full directory structure
askgpt "@treefull, analyze main modules"

# Embed file content
askgpt "Optimize this config: @config/settings.yaml"

# Webpage analysis
askgpt @https://tree-sitter.github.io/tree-sitter/using-parsers/1-getting-started.html Summarize this doc

# News parsing (requires readability & browser setup)
askgpt @readhttps://www.guancha.cn/internation/2025_02_08_764448.shtml Summarize news

# Use prompt templates
askgpt @advice # Uses advice.txt in prompts/ directory

# Combine multiple contexts
askgpt @advice @llm_query.py @clipboard Fix potential bugs

# Recent conversations
recentconversation
# Output:
# 1) 2025-02-09 18:35:27 EB6E6ED0-CAFE-488F-B247-11C1CE549B12 What I said earlier
# 2) 2025-02-09 18:34:37 C63CA6F6-CB89-42D2-B108-A551F8E55F75 hello
# Select conversation (1-4, Enter to cancel): 2
# Switched to: C63CA6F6-CB89-42D2-B108-A551F8E55F75

# Start new conversation
newconversation

# Generate commit message after git add (not supported in PowerShell)
commitgpt

# Temporary query without affecting current conversation
naskgpt hello

# Clipboard listening, add multiple copies to context
askgpt @listen What trends do these user comments reflect?

# Repeat last prompt
askgpt @last

# Symbol context query, lists multi-level symbol calls across files
askgpt @symbol:show_tty_driver

# Chatbot for casual conversation
chatbot

# Continue chatting, affected by newconversation
chatagain
```

## Features

- **Code Analysis**: Replace view/vim with LLM-powered local code analysis
- **Conversation Management**: Resume past conversations or start new ones
- **Context Integration**:
  - Clipboard content (`@clipboard`)
  - Directory structure (`@tree`/`@treefull`)
  - File embedding (`@filepath`)
  - Web content (`@http://...`)
  - Prompt templates (`@advice`)
  - Command suggestions (`@cmd`)
  - Code editing (`@edit`)
- **Web Content Conversion**:
  - Built-in HTML-to-Markdown service
  - Browser extension integration bypassing Cloudflare
  - Automatic content extraction and format conversion
- **Obsidian Integration**: Auto-save queries to Obsidian vault
- **Proxy Support**: Automatic HTTP proxy detection
- **Multi-model Switching**: Configure local/remote models via `model.json`
- **Streaming Responses**: Real-time API output with thinking process

## Installation

1. **Clone Repo**
```bash
git clone https://github.com/maliubiao/terminal-llm
cd terminal-llm
```

2. **Setup Virtual Env**
```bash
#install uv
# Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Mac/Linux curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
source .venv/bin/activate
```

3. **Environment Variables**
```bash
# Add to shell config (~/.bashrc/zshrc), only last line required if you has a model.json config
export GPT_PATH="/path/to/terminal-llm"
export GPT_KEY="your-api-key"
export GPT_MODEL="your-model"
export GPT_BASE_URL="https://api.example.com/v1"
source $GPT_PATH/env.sh  # Enables @ autocomplete
```

4. **Windows PowerShell**
```powershell
# Add to $PROFILE
[Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. \path\to\env.ps1  # Use \@ for autocomplete
```

### Recommended API Providers
[ByteDance Volcano Ark](https://www.volcengine.com/experience/ark?utm_term=202502dsinvite&ac=DSASUQY5&rc=FNTDEYLA) - Fastest API response, lowest cost, 30M free tokens.  
[SiliconFlow Cloud](https://cloud.siliconflow.cn/i/BofVjNGq) - 20M free tokens, runs on Huawei Ascend NPUs.  
[Tutorial](https://docs.siliconflow.cn/usercases/use-siliconcloud-in-chatbox)

## Usage

### Basic Commands

**Conversation Management**
```bash
# List conversations
allconversation  # recentconversation = allconversation 10

# Start new session
newconversation
```

**Code Analysis**
```bash
explaingpt path/to/file.py
explaingpt file.py prompts/custom-prompt.txt
```

**Direct Query**
```bash
askgpt "Implement quicksort in Python"
```

**Model Switching**
```bash
listgpt  # Show configured models
usegpt 14b  # Switch model
```
```json
// model.json
{
    "14b": {
        "key": "ollama",
        "base_url": "http://192.168.40.116:11434/v1",
        "model_name": "deepseek-r1:14b",
        "max_context_size": 131072
    }
}
```

### Advanced

**Web Conversion Service**
```bash
python server/server.py  # Start converter (port 8000)

# Browser extension setup: Load server/plugin/
curl "http://localhost:8000/convert?url=CURRENT_PAGE_URL"

# Readability news extraction (Node.js)
cd node; npm install; npm start  # Port 3000
```

**Element Filters for Web Conversion**
```yaml
# Supports glob patterns
filters:
    - pattern: https://www.guancha.cn/*/*.shtml
      cache_seconds: 600 # Cache results for 10 minutes
      selectors:
        - "div.content > div > ul" # Focus on main content

    - pattern: https://x.com/*/status/*
      selectors:
        - "//article/ancestor::div[4]" # XPath selector
```

**Plugin Configuration**
Click the plugin icon to load an element selector, which helps locate CSS selectors for desired content.

### Symbol Query

tree.py is a tree-sitter based AST parser that generates a SQLite index for source code. Set `GPT_SYMBOL_API_URL` to the API server location.

```bash
python tree.py --project /path/to/project/ --port 9050
```

### Prompt Templates

Create templates in `prompts/`:
```txt
Analyze this Python code:

Tasks:
1. Explain core functionality
2. Identify potential bugs
3. Suggest optimizations

File: {path}
{pager}
\```
{code}
\```
```

## Environment Variables

| Variable       | Description                  |
|----------------|------------------------------|
| `GPT_PATH`     | Project root path            |
| `GPT_KEY`      | API key                      |
| `GPT_BASE_URL` | API endpoint (OpenAI-compatible) |
| `GPT_MODEL`    | Default model name           |

## Directory Structure

```
terminal-llm/
├── bin/              # Utility scripts
├── server/           # Web conversion
│   └── server.py     # Converter server
├── prompts/          # Prompt templates
├── logs/             # Logs
├── llm_query.py      # Core logic
├── env.sh            # Environment config
└── pyproject.toml    # Dependencies
```

## Notes

1. **Dependencies**:
   - [glow](https://github.com/charmbracelet/glow) for Markdown rendering
   - `tree` command for directory visualization

2. **Proxy**: Auto-detects `http_proxy`/`https_proxy`

3. **Large Files**: Auto-chunking (32k chars/chunk)

4. **Web Converter**:
   - Requires Chrome extension
   - Port 8000 must be available
   - Only accepts local connections

## Community

<img src="doc/qrcode_1739088418032.jpg" width="200" alt="QQ Group" />

## License

MIT License © 2024 maliubiao
