
# Treehouse  
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/maliubiao/treehouse)  
[English users please view README.en.md](README.en.md)  

A code assistance tool based on OpenAI-compatible APIs, offering convenient command-line interaction and context-aware functionality. It aims to be the command-line version of Cursor and Windsurf, with Deepseek R1 and V3 recommended for use.
## Usage Scenarios

Multiple @ symbols can be used after askgpt to mix and form context. URLs can be used while simultaneously incorporating file content without requiring quotation marks, but special shell characters like > should be noted.

```bash

# Analyze clipboard content
askgpt Explain this code: @clipboard @tree

# Command suggestion
askgpt @cmd Find all files modified 2 hours ago and delete them

# Attach current directory structure
askgpt "@tree, analyze the main modules"

# Attach current directory structure, including subdirectories
askgpt "@treefull, analyze the main modules"

# Embed file content
askgpt "Optimize this config file: @config/settings.yaml"

# Access webpage
askgpt @https://tree-sitter.github.io/tree-sitter/using-parsers/1-getting-started.html Summarize this document

# Read news (uses readability tool to extract main text; requires browser forwarding setup; tutorial below)  
askgpt @readhttps://www.guancha.cn/internation/2025_02_08_764448.shtml Summarize the news

# Embed common prompts (files stored in prompts/ directory)
askgpt @advice #This prompt asks GPT to provide modification suggestions

# Flexibly introduce prompt blocks, provide files, complete directory modifications, while incorporating clipboard snippets. @ references must end with a space to distinguish from other content.  
askgpt @advice @llm_query.py @clipboard Fix potential bugs  

# Use custom context (written in prompts/ directory, supports autocompletion)
# Functionality: Copy a long passage from a webpage, use r1 to "Organize this person's viewpoints and provide commentary"
askgpt @clipboard @comment

# Directory reference
askgpt @src Explain the structure of this React project
# Directory references support wildcards
askgpt "@src/*tsx" Explain the purpose of these components
# File references support wildcards
askgpt "@*json" What is the purpose of JSON files in the current directory?

# Project reference (supports all @ functionalities here). Some file components and config files reference complex contexts for convenience.
askgpt @projects/lldb_ai.yml Write an LLDB AI extension
patchgpt @projects/context.yaml Improve test suite based on README and code implementation

# Recent conversations
recentconversation
# Recent conversation history:
# 1) 2025-02-09 18:35:27 EB6E6ED0-CAFE-488F-B247-11C1CE549B12 What did I say earlier?
# 2) 2025-02-09 18:34:37 C63CA6F6-CB89-42D2-B108-A551F8E55F75 hello
# 3) 2025-02-09 18:23:13 27CDA712-9CD9-4C6A-98BD-FACA02844C25 hello
# Select conversation (1-4, press Enter to cancel): 2
# Switched to conversation: C63CA6F6-CB89-42D2-B108-A551F8E55F75

# New conversation (opens by default in new terminal or can be manually reset)
newconversation

# After git add, generate commit message for staged changes (PowerShell not supported yet)
commitgpt

# Ask a question outside current context without interfering with existing conversation
naskgpt hello

# Clipboard listener function: subsequent copies will be added to context. Useful for gathering fragments from different document locations when writing materials.
askgpt @listen What trends do these user comments reflect?

# Reuse the last sent prompt (useful for network issues or modifying questions)
askgpt @last

# Chatbot for casual conversation 
# New conversation
chatbot

# Continue chatting (affected by newconversation)
chatagain

# Multi-line input (normally \ can be used for line breaks)
naskgpt \
> hello \
> world

# File line number selection (workaround for large files: first 100, or 100-, or 20-50)
naskgpt @large-file:-100

# Execute prompt file as script. If executable permissions are set or it starts with #!, its stdout will be included in context (prompt extension feature)
naskgpt @script.sh

# The following features involve symbols and are core functionalities requiring symbolgpt to start a symbol server (defined in env.sh)
# Start symbol service (tree.py). When switching between multiple projects in terminal, if tree.py is already running in that directory, directly source .tree/rc.sh to use its service 
symbolgpt
symbolgptrestart

# @patch indicates the response contains symbols to be patched
askgpt @patch @symbol_tree.py/ParserUtil When traverse encounters nodes like function_definition, additional consideration is needed: check if its parent node is decorated_definition. If yes, use the full text of the parent node to include the decorator.

# Symbol autocompletion (supports bash, zsh, PowerShell when typing @symbol_ to complete current file symbols. Requires tree.py language support)
askgpt @symbol_file/symbol 

# Specify symbol by line number (functions may be anonymous; directly use line number)
askgpt @symbol_llm_query.py/at_4204

# Specify symbol by line number but search includes parent nodes containing this line (no need to know parent node names)
askgpt @symbol_llm_query.py/near_4215

# Fix code bugs (generates a diff for optional patching). @edit indicates response contains patchable content; @edit-file specifies output.
askgpt @edit @edit-file @main.py Find and fix potential bugs

# Same functionality as above
codegpt @main.py Find and fix potential bugs

# Modify a symbol (patchgpt is shorthand for naskgpt @patch; see command set defined in env.sh)
patchgpt @symbol_file/symbol Fix bugs in it

# Uses LSP to find symbols called by this symbol and include them in context
patchgpt @context @symbol_file/symbol Fix bugs in it

# Re-execute last command to diagnose failure
fixgpt 

# Use ripgrep for project search and automatically locate found symbols (requires installed tool). ..search.. can be mixed with other contexts.
# .llm_project.yml configures search scope
patchgpt ..LintFix.. ..main.. Add unit test suite

# Class/function location and completion (write a placeholder like class MyClass: pass in a file)
patchgpt ..MyClass.. Complete this test suite based on specifications

```

## Features

- **Code Generation**: Implements code generation functionality for cursor and windsurf, based on AST and LSP for precise context acquisition
- **Conversation Saving & Switching**: Follow up on questions, restore past conversations, and continue questioning
- **Powerful Symbol Reference Functionality**: Uses symbols like classes and functions as units for LLM modifications, then diffs and patches local code, significantly reducing response time and token consumption
- **Comprehensive Context Integration**:
  - Automatic clipboard content reading (`@clipboard`)
  - Directory structure viewing (`@tree`/`@treefull`)
  - File content embedding (`@filepath`)
  - Web content embedding (`@http://example.com`)
  - Common prompt referencing (`@advice`...)
  - Command line suggestions (`@cmd`)
  - Code editing (`@edit`)
- **Web Content Conversion**: Built-in web service for HTML-to-Markdown conversion
  - Browser extension integration support, bypassing Cloudflare interference
  - Automatic content extraction and format conversion
- **Obsidian Support**: Saves historical queries in Markdown format to specified directories
- **Multiple Model Switching**: Uses configuration files to switch between local ollama 14b/32b small models and remote r1 full-scale models
- **Advanced Debugging Features**: Supports line-level tracing for Python code, outputting local variable changes to tracing logs

## Code Generation  
Patches can be generated for files or specific code symbols. To enable precise symbol lookup, tree.py must be launched. The language server can automatically retrieve the context of a function. After a query is made, the system will output code based on the large model's response and autonomously decide whether to apply the patch based on the diff results. Refer to the configuration instructions provided later.

## Installation and Configuration

1. **Clone the repository**
```bash
git clone https://github.com/maliubiao/treehouse
cd treehouse
```

2. **Set up virtual environment**
```bash
#Install uv on Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
#Install uv on Mac or Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync #uv python list; uv python install a specific Python version, 3.12 or higher
source .venv/bin/activate
```

3. **Environment variable configuration**
```bash
# Add to shell configuration file (~/.bashrc or ~/.zshrc). If model.json is configured, only GPT_PATH needs to be set to the project directory, source /your/path/to/env.sh
export GPT_PATH="/path/to/treehouse"
export GPT_KEY="your-api-key"
export GPT_MODEL="your-model"
export GPT_BASE_URL="https://api.example.com/v1"  # OpenAI-compatible API address
source $GPT_PATH/env.sh #Supports @ autocompletion in zsh/bash
```

4. **Usage on Windows PowerShell**  
Note that @ has special meaning in PowerShell and cannot be directly used for autocompletion - use \@ instead (adding one extra character). Quotes may also be needed to prevent escaping.
```powershell
#On Windows, packages can be installed via choco install ripgrep git, then add their bin directories to PATH. Will use git's built-in diff.exe, patch.exe, and locate them via git.exe
#C:\\Program Files\\Git\\bin;C:\\ProgramData\\chocolatey\\bin;$HOME\\.local\\bin
#naskgpt "@cmd" or '@cmd' or \@cmd
$env:GPT_PATH="C:\Users\richard\treehouse"
#Add to user environment variables so it persists
[Environment]::SetEnvironmentVariable('GPT_PATH', $env:GPT_PATH, 'User')
notepad $PROFILE
#Add these two lines to the config file (modify treehouse directory as needed)
#$env:GPT_PATH=C:\Users\richard\treehouse
#Convert env.ps1 to UTF8-BOM format to prevent encoding issues on Windows. Use Vs Code's "Save with Encoding" or python tools/utf8_bom.py env.ps1
#. C:\Users\richard\treehouse\env.ps1 
```

### R1 API Providers  
[ByteDance Volcano ARK](https://www.volcengine.com/experience/ark?utm_term=202502dsinvite&ac=DSASUQY5&rc=FNTDEYLA) currently offers the fastest API response, lowest fees at half price, and provides 30 million tokens upon registration.  
[SiliconFlow](https://cloud.siliconflow.cn/i/BofVjNGq) delivers high-performance API services, but with limited resources due to its smaller scale, congestion may occur. Registration grants 20 million tokens, and the platform runs on Huawei Ascend, a fully domestic infrastructure, ensuring security and reliability.  
Tutorial included: [SiliconCloud API Usage Guide](https://docs.siliconflow.cn/usercases/use-siliconcloud-in-chatbox)

## User Guide

### Basic Commands

**Conversation Management**

```bash
# List historical conversations
➜  treehouse git:(main) ✗ allconversation #allconversation 2 shows the last two, recentconversation is equivalent to allconversation 10
All conversation records:
 1) 2025-02-09 19:07:34 E8737837-AD37-46B0-ACEA-8A7F93BE25E8 File /Users/richard/code/termi...
 2) 2025-02-09 18:34:37 C63CA6F6-CB89-42D2-B108-A551F8E55F75 hello
 3) 2025-02-09 18:48:47 5EC8AF87-8E00-4BCB-9588-1F131D6BC9FE recentconversation() {     # U...
 4) 2025-02-09 18:35:27 EB6E6ED0-CAFE-488F-B247-11C1CE549B12 What did I say earlier
 5) 2025-02-09 18:23:13 27CDA712-9CD9-4C6A-98BD-FACA02844C25 hello
Select conversation (1-       5, press Enter to cancel):
# After selection, the conversation can be restored, or press Enter to exit
➜  treehouse git:(main) ✗ newconversation #Start an empty conversation
New conversation ID:  D84E64CF-F337-4B8B-AD2D-C58FD2AE713C
```

**Direct Queries**

```bash
askgpt "How to implement the quicksort algorithm?"
naskgpt "How to implement the quicksort algorithm?"
```

**Complex Context Combinations**
```yaml
# YAML configurations under projects are combination configurations, must be in this directory and end with .yml
# Can freely use @supported features and define which files to reference
# lldb_ai.yml
files:
  - debugger/lldb/ai/*py  #Files to use
dirs: [] #Directories to use
context:
  - treefull #@commands to use

# Another example of using context separately in context.yml
context:
  - symbol_tests/test_llm_query.py/TestGPTContextProcessor #Direct symbol reference
  - symbol_llm_query.py/_handle_local_file,_process_directory,_handle_project,under_projects,__import__ #Combined symbol references
  - ..read_context_config.. #Symbol search
  - env.sh #File
```

## Coding Project Configuration
```yaml
# Example LLM project search configuration file, filename .llm_project.yml
# Exclusion configuration (supports glob patterns)
#
# Project root directory, must contain .llm_project.yml to locate symbols, @symbol_src/file.py/main refers to the main function in src/file.py under this directory
project_root_dir: /path/to/your/project
lsp: #lsp configuration
  commands: #lsp startup commands for this project
    py: pylsp
    clangd: clangd
  subproject: #lsp for subdirectories
    debugger/cpp/: clangd 
  default: py #default lsp when no match
  suffix:
    cpp: clangd #match which lsp to query based on file extension
#..main.. ripgrep search scope control, search for main string in which files
exclude:
  dirs:
    - .git          # Version control directory
    - .venv         # Python virtual environment
    - node_modules  # Node.js dependency directory
    - build         # Build directory
    - dist          # Distribution directory
    - __pycache__   # Python cache directory
    - conversation
    - obsidian
    - web
  files:
    - "*.min.js"    # Minified JS files
    - "*.bundle.css" # Bundled CSS files
    - "*.log"       # Log files
    - "*.tmp"       # Temporary files

# Include configuration (empty means using default file types)
include:
  dirs: []  # Specify directories to include (overrides exclusion rules)
  files:
    - "*.py"  # Python source files
    - "*.cpp" # CPP
    - "*.js"  # JavaScript files
    - "*.md"  # Markdown documents
    - "*.txt" # Text files

# File types to search (extensions or predefined types)
file_types:
  - .py    # Python
  - .js    # JavaScript
  - .md    # Markdown
  - .txt   # Text files
  - .cpp   #cpp

```

**Model Switching**

```bash
# Create model.json in the same directory, use listgpt to check. After configuring model.json, GPT_* environment variables are not needed, will use "default" provider or the first one
➜  treehouse git:(main) ✗ listgpt 
14b: deepseek-r1:14b
➜  treehouse :(main) ✗ usegpt 14b
Successfully set GPT environment variables:
  GPT_KEY: olla****
  GPT_BASE_URL: http://192.168.40.116:11434/v1
  GPT_MODEL: deepseek-r1:14b
```
```
//Different models have vastly different max_context_size, some only support 8192, or even smaller like 4k, setting too high will cause errors
//max_context_size is context size, max_tokens is output size, different API providers have different parameters
//Temperature significantly affects response tendencies, set to 0.0 for programming questions, 0.6 for literary tasks, official recommendation
//is_thinking marks whether this is a thinking model, thinking models don't need complex prompts as they can deduce themselves, e.g. r1 is, v3 isn't
```
```json
{
    "14b": {
        "key": "ollama",
        "base_url": "http://192.168.40.116:11434/v1",
        "model_name": "r1-qwen-14b:latest",
        "max_context_size": 131072,
        "temperature": 0.6,
        "max_tokens": 8096,
        "is_thinking": false,
        "temperature": 0.0
    }

}
```

**Document Management**

It is recommended to use professional tools like Obsidian for managing large volumes of Markdown documents. This program automatically generates daily indexes.  

Each prompt and response is saved by default in the obsidian/ directory for easy access via Obsidian.  
Historical conversations are stored by default in the conversation/ directory, organized by date and not deleted as they occupy minimal space.  

### Advanced Features  

**Web Content Conversion Service**  
```bash  
# Start the conversion server (default port 8000), implemented using https://github.com/microsoft/markitdown  
# Supports --addr, --port, which also need to be updated in the plugin options  
python server/server.py  
# Call the conversion API (requires browser extension integration). Load server/plugin into the browser  
curl "http://localhost:8000/convert?url=current_page_URL"  

# Firefox Readability news extraction. When the server receives the is_news=True parameter, it queries this (port 3000, modifiable in package.json)  
cd node; npm install; npm start  
```  

**Element Filter for Web Conversion Service**  
Web pages may contain numerous irrelevant elements, such as external links, which waste context. Many APIs also impose 8k context limits, making it impossible to include everything.  
In such cases, custom CSS or XPath selectors are needed to instruct the conversion service on which areas to focus on.  
XPath selectors are more powerful and effective for handling obfuscated webpage structures.  
The web conversion service includes a built-in element filter, configured in server/config.yaml.  
Additionally, after selecting elements with the built-in selector, they can be saved directly, and the plugin will update server/config.yaml.  
```yaml  
# Supports glob patterns like . * for URL matching  
filters:  
    - pattern: https://www.guancha.cn/*/*.shtml  
      cache_seconds: 600 # Cache results for 10 minutes, allowing repeated queries to explore different angles  
      selectors:  
        - "div.content > div > ul" # Focus only on the main webpage content  

    - pattern: https://x.com/*/status/*  
      selectors:  
        - "//article/ancestor::div[4]" # XPath, must start with //. This selects the fourth-level parent div of the article  
```
Plugin configuration
Click the plugin icon to access a pop-up menu, where you can load an element selector on the current page. This tool helps locate the CSS selector of desired content, which can then be copied to config.yaml.  
If you are familiar with DevTools' inspector, you can use its "Copy selector" feature.  

### Symbol Query  

tree.py is a Tree-sitter-based abstract syntax tree parsing library that provides multi-language AST and LSP symbol lookup support.  

```bash  
# A typical output  
(treehouse) ➜  treehouse git:(main) ✗ python tree.py --project /Volumes/外置2T/android-kernel-preprocess/aosp/ --port 9050  

INFO:     Started server process [74500]  
INFO:     Waiting for application startup.  
INFO:     Application startup complete.  
INFO:     Uvicorn running on http://127.0.0.1:9050 (Press CTRL+C to quit)  
INFO:     127.0.0.1:57943 - "GET /symbols/show_tty_driver/context?max_depth=5 HTTP/1.1" 200 OK  
INFO:     127.0.0.1:57957 - "GET /symbols/show_tty_driver/context?max_depth=5 HTTP/1.1" 200 OK  
```  

### Starting a Tree Service for a New Project  
In the project's root directory, execute the following. If `.llm_project` is not configured, a default one will be generated. The configuration specifies how to use the language server and ripgrep search settings.  
```bash  
symbolgpt  
symbolgptrestart # Force restart  
# When using @symbol_* ..symbol.. services later, remember that tree.py must be started with the above command. On Linux and Mac, source .tree/rc.sh to load environment variables; on Windows, use . .tree\rc.ps1  
```  
Alternatively, start it manually:  
```bash  
# Create a new .llm_project.yml to configure LSP  
$GPT_PYTHON_BIN $GPT_PATH/tree.py --port 9060;  
# GPT_PYTHON_BIN and GPT_PATH are environment variables set in env.sh, pointing to the treehouse directory  
export GPT_SYMBOL_API_URL=http://127.0.0.1:9060/;  
# In askgpt, use @symbol_file.xx/main to retrieve symbol context. Bash and Zsh shells support autocompletion for convenience.  
```

# Advanced Debugger
Supports line-by-line bytecode tracing for Python programs, outputs which line is executed and variable changes, with sufficiently good performance to avoid freezing.

#### Compilation
```bash
#python 3.11.11 uv python pin {version}, preferably 3.11.11 because cpp accesses Python VM internal data - wrong version will crash
cd treehouse; source .venv/bin/activate;
cd debugger/cpp
#If compilation fails, join the QQ group below for discussion. If documentation steps don't work, provide feedback in the group
cmake ../ -DCMAKE_BUILD_TYPE=Debug -DENABLE_ASAN=ON #or
cmake ../ -DCMAKE_BUILD_TYPE=Release
#Output at treehouse/debugger/tracer_core.so
```

#### Compiling on Windows

1. **Environment Setup**:
  - Install Visual Studio 2022, ensure "Desktop development with C++" workload is selected
  - Install CMake (via Visual Studio installer or official website)
  - Ensure using compatible Python version

2. **Python Environment Configuration**:
```powershell
# Execute in PowerShell
# Install and pin Python 3.11.12 version
PS C:\Users\richard\treehouse> uv python install cpython-3.11.12-windows-x86_64-none
PS C:\Users\richard\treehouse> uv python pin cpython-3.11.12-windows-x86_64-none
PS C:\Users\richard\treehouse> uv sync
```

3. **Building with Developer PowerShell**:
```powershell
# Open "Developer PowerShell for VS 2022" from Start Menu
cd C:\Users\richard\treehouse\debugger
mkdir build
cd build
# Generate Visual Studio solution
cmake ../ -A x64 -DCMAKE_BUILD_TYPE=Release
```

4. **Building the Project**:
  - Method 1: Using Visual Studio
    ```powershell
    # Open generated solution
    start .\treehouse-tracer.sln
    # Select Release configuration in Visual Studio and build solution
    ```
  - Method 2: Command line build
    ```powershell
    cmake --build . --config Release
    #Verify correct version of python dll is linked
    dumpbin /dependents ../tracer_core.pyd
    ```

5. **Output Verification**:
  - After successful compilation, the generated DLL file should be at `treehouse\debugger\tracer_core.pyd`
  - If issues occur, check Visual Studio output window for detailed error messages

Note: Windows version uses `.pyd` extension instead of Linux's `.so`, but they function identically.

#### Usage
```bash
#Modify path before use, --watch-files= uses glob matching with wildcards, --open-report opens webpage after completion. Not recommended for tracing hundreds of thousands of lines - browser load would be too heavy.
python -m debugger.tracer_main --watch-files="*path.py"  --watch-files="*query.py" --open-report test_llm_query.py -v TestDiffBlockFilter
```

<img src="doc/debugger-preview.png" width = "600" alt="line tracer" align=center />

# Custom Prompt Library

Create custom templates in the `prompts/` directory. You can place scripts or executable files in this directory to dynamically generate prompts. Please copy and reference existing files:
```py
#! /usr/bin/env python
# Write shell scripts under prompts directory. The script will be executed and its output will be used as part of the prompt. Add executable permissions.
print("You are a friendly assistant")
```

## Environment Variables

| Variable Name  | Description                    |
| -------------- | ------------------------------ |
| `GPT_PATH`     | Project root directory path    |
| `GPT_KEY`      | OpenAI API key                 |
| `GPT_BASE_URL` | API base URL (default Groq official endpoint) |
| `GPT_KEY`      | API KEY                        |

```bash
env |grep GPT_
```
# Precautions  

**Note**
1. **Optional Tools**:
   - Install the `tree` command to view directory structures
   - Install `diff` and `patch` tools for source code operations (may not be available by default on Windows)

2. **Proxy Configuration**:
   Automatically detects `http_proxy`/`https_proxy` environment variables

3. **Web Conversion Service Dependencies**:
   - Requires Chrome browser extension for coordinated use
   - Ensure port 8000 is not occupied, or modify the address in the plugin configuration options page
   - Conversion service only accepts local connections

## Treehouse Group
<img src="doc/qrcode_1739088418032.jpg" width = "200" alt="QQ Group" align=center />

## License

MIT License © 2024 maliubiao
