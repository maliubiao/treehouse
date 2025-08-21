# 🔄 Anthropic 转 OpenAI API 代理服务器

这是一个高度灵活且健壮的代理服务器，将 Anthropic 消息 API 格式的请求转换为任意兼容 OpenAI 的聊天补全 API。专为生产环境设计，专注于配置驱动的路由、多提供商支持和详细日志记录。

## ✨ 核心特性

- **无缝转换**：精确转换 Anthropic 请求（包括流式传输、工具使用和批处理）为 OpenAI 格式，并将响应转换回来
- **完整客户端兼容**：可与官方 `anthropic` Python 客户端开箱即用
- **配置驱动路由**：使用单个 `config.yml` 文件管理所有行为。无需更改代码即可添加新提供商或更改路由规则
- **多提供商支持**：同时将请求路由到不同的后端，如 OpenAI、OpenRouter、SiliconFlow 或本地模型（如 Ollama）
- **推理感知路由**：智能地将带有 Anthropic `thinking` 参数的请求路由到明确支持推理/思维功能的提供商。代理正确地将流式 `reasoning_content` 转换为 Anthropic `thinking_delta` 事件
- **动态模型映射**：将单个 Anthropic 模型别名（如 `claude-3-5-sonnet`）映射到不同提供商上的不同目标模型（如一个在 `openai/gpt-4o` 上，另一个在 `deepseek/deepseek-r1` 上）
- **健壮性特性**：包含 `max_tokens_override` 设置，防止在有严格令牌限制的提供商上出现请求失败
- **上下文感知路由**：自动检测请求的上下文长度要求，并智能路由到具有足够容量的提供商
- **结构化日志**：为整个请求生命周期生成详细的 JSON 日志，便于调试路由决策和提供商错误


### 高级调试与追踪
- **Python 代码追踪**：内置 MCP 服务器，支持详细的 Python 代码分析
- **导入路径分析**：自动发现模块结构和导入语句
- **执行流跟踪**：API 转换过程的完全可见性
- **请求/响应调试**：路由决策和提供商交互的实时监控

### 增强型提供商支持
- **推理提供商处理**：增强对启用推理功能的提供商（如 DeepSeek R1）支持
- **流式响应转换**：实时转换推理内容和流式响应
- **批处理支持**：对 Anthropic 批处理 API 请求的翻译支持

## 🧠 工作原理：路由逻辑

代理的核心优势在于其路由引擎。当对某模型（如 `claude-3-5-sonnet-20241022`）的请求到达时，路由器按以下步骤执行：

1. **检查推理**：路由器首先检查传入请求是否包含 `thinking={"type": "enabled"}`
2. **优先推理路由**：如果请求了推理功能，路由器将**仅**考虑配置中 `supports_reasoning: true` 的提供商。按以下顺序检查：
   a. 为请求模型定义的具体提供商（在 `anthropic.model_providers` 中）
   b. 默认提供商 `anthropic.default_provider`
   如果未找到支持推理的提供商，将记录警告并继续标准路由
3. **标准路由**：如果未请求推理功能（或未找到推理提供商），按以下顺序选择提供商：
   a. **特定模型映射**：`anthropic.model_providers` 中的模型条目
   b. **默认提供商**：`anthropic.default_provider`
4. **上下文感知路由**：如果请求需要超过提供商定义容量的上下文长度，路由器会自动寻找具有足够容量的其他提供商
5. **转换并转发**：使用所选提供商的 `default_models` 映射中定义的目标模型名将请求转换为 OpenAI 格式，并发送到提供商的 `base_url`

整个过程通过唯一请求 ID 记录，因此您可以准确追踪为什么选择特定提供商

### 🧠 上下文感知路由

代理现在支持智能的上下文长度感知路由，自动检测请求的令牌需求并选择最合适的提供商：

1. **自动令牌估算**：使用字符串长度 ÷ 4 的近似方法估算请求的上下文长度需求
2. **容量检查**：在每个路由优先级级别检查提供商的 `max_context` 容量
3. **智能降级**：如果首选提供商容量不足，自动寻找具有足够容量的其他提供商
4. **最优选择**：选择具有最小足够容量的提供商，以节约资源

**示例场景**：
- 小请求（<4K tokens）→ 路由到标准容量提供商
- 中等请求（4K-16K tokens）→ 路由到中等容量提供商  
- 大请求（16K-32K tokens）→ 路由到大容量提供商
- 超大请求（>32K tokens）→ 路由到无限制容量提供商

## ⚙️ 配置 (`config.yml`)

所有代理行为都由单个 YAML 文件控制。以下是基于项目默认 `config.yml` 的注释示例：

```yaml
# 服务器主机和端口设置
server:
  host: "127.0.0.1"
  port: 8083

# 日志设置
logging:
  level: "INFO"  # 可为 DEBUG, INFO, WARNING, ERROR
  dir: "logs"

# 主提供商配置模块
providers:
  # 此部分定义传入 Anthropic 请求的路由规则
  anthropic:
    name: "Anthropic"
    # 如果没有匹配以下特定模型规则，使用的提供商密钥
    default_provider: "openai_provider1"
    # 将特定 Anthropic 模型名称映射到 openai_providers 中的提供商密钥
    # 此优先级高于 default_provider
    model_providers:
      # 示例: "claude-sonnet-4-20250514": "openai_provider3"

  # 此部分定义所有可用的下游 OpenAI 兼容提供商
  openai_providers:
    # 以上 anthropic 部分中引用的密钥
    openai_provider1:
      name: "OpenRouter"  # 日志中的人类可读名称
      type: "openai"
      base_url: "https://openrouter.ai/api/v1"
      api_key: "sk-or-v1-..."  # 您的提供商 API 密钥
      timeout: 600.0
      # 将传入的 Anthropic 模型名称映射到该提供商上的实际模型
      default_models:
        "claude-sonnet-4-20250514": "moonshotai/kimi-k2"
      # 该提供商是否支持推理/思维功能？
      supports_reasoning: false
      # 如果用户请求的令牌多于上述值，则值将被限制
      # 这可防止具有严格限制的提供商出现错误
      max_tokens_override: 4096
      # 该提供商支持的最大上下文长度（令牌数）
      # 如果为 None，表示无限制容量
      max_context: 16000

    # 第二个提供商，支持推理
    openai_provider3:
      name: "siliconflow-r1"
      type: "openai"
      base_url: "https://api.siliconflow.cn/v1"
      api_key: "sk-..."
      supports_reasoning: true
      default_models:
        "claude-sonnet-4-20250514": "Pro/deepseek-ai/DeepSeek-R1"
      # 启用推理的提供商特定配置
      reasoning_config:
        thinking_budget_param: "thinking_budget"
        include_reasoning: true
      max_tokens_override: 8192
      # 这个提供商支持更大的上下文容量
      max_context: 32000
```

**上下文长度配置说明**：
- `max_context`：该提供商支持的最大上下文长度（令牌数）
- 设置为 `null` 或省略表示无限制容量
- 建议为每个提供商设置合适的容量限制，以启用智能路由功能

## 🔍 追踪与调试功能

### 内置追踪工具
代理包括用于 Python 追踪的原生 MCP（模型上下文协议）服务器：

- **Python 执行追踪**：Python 脚本和模块执行的详细分析
- **导入路径查找器**：模块结构和导入路径的自动发现
- **实时调试**：代理操作和 API 转换的实时监控
- **增强响应转换调试**：支持推理内容和自定义工具调用格式追踪

### 可用诊断命令

```bash
# 以最详细级别运行调试日志记录
python -m claude_code_proxy.main --config my_config.yml --log-level DEBUG

# 启用请求/响应追踪
export TRACE_REQUESTS=true
python -m claude_code_proxy.main --config my_config.yml

# 用于性能分析的追踪
python -m claude_code_proxy.src.tracer_mcp_server

# 测试响应转换器（新的v2版本）
python -m tests.claude_code_proxy_tests.test_response_translator_v2 -v
```

### 配置验证
- **自动验证**：启动时的 YAML 配置验证
- **提供商健康检查**：配置时的提供商连接测试
- **模型映射检查**：模型名称转换验证

## 🚀 快速开始

1. **安装依赖**：
   从项目根目录（`treehouse/`），安装所需包。
   ```bash
   pip install -r tools/claude_code_proxy/requirements.txt
   ```

2. **创建配置文件**：
   项目包含 `config.yml` 作为模板。建议复制并根据需要进行修改。
   ```bash
   cd tools/claude_code_proxy
   cp config.yml my_config.yml
   ```
   现在，编辑 `my_config.yml`：
   - 添加您的提供商 `api_key` 值
   - 调整 `base_url` 和 `default_models` 映射
   - 设置 `anthropic` 路由规则
   - 为需要令牌限制的提供商添加 `max_tokens_override`
   - 为提供商设置合适的 `max_context` 上下文容量限制

3. **运行服务器**：
   从项目根目录运行 `main` 模块，指向您的配置文件。
   ```bash
   python -m claude_code_proxy.main --config my_config.yml
   ```
   服务器将启动并打印已加载提供商和路由规则的摘要。

4. **高级调试（可选）**：
   用于开发和调试：
   ```bash
   # 开发期间运行自动重载
   python -m claude_code_proxy.main --config my_config.yml --reload
   
   # 启用综合追踪
   export TRACE_PYTHON=true
   python -m claude_code_proxy.main --config my_config.yml
   ```

## 👨‍💻 与 Anthropic 客户端一起使用

将官方 `anthropic` Python 客户端指向您的运行代理服务器。

1. **安装客户端**：
   ```bash
   pip install anthropic
   ```

2. **配置环境**：
   设置基本 URL 指向您的代理。API 密钥可以是虚拟值，因为代理使用 `config.yml` 中的密钥。
   ```bash
   export ANTHROPIC_BASE_URL="http://127.0.0.1:8083/v1"
   export ANTHROPIC_API_KEY="dummy_key"
   ```

3. **示例 Python 脚本**：

```python
import anthropic

# 客户端自动使用环境变量
client = anthropic.Anthropic()

# --- 测试 1：标准请求 ---
# 这将为您的配置中的该模型使用路由规则。
print("--- 测试标准请求 ---")
message = client.messages.create(
    model="claude-sonnet-4-20250514",  # 使用配置中的模型名称
    max_tokens=100,
    messages=[{"role": "user", "content": "你好，世界！"}],
)
print(f"来自模型的响应：{message.model}")
print(message.content[0].text)

# --- 测试 2：带"推理"的请求 ---
# 代理将优先考虑 `supports_reasoning: true` 的提供商。
# 如果您的提供商产生它们，您将在流中看到 'thinking_delta' 事件。
print("\n--- 测试推理请求 ---")
try:
    with client.messages.stream(
        model="claude-sonnet-4-20250514",  # 此模型必须映射到可推理提供商
        max_tokens=1024,
        messages=[{"role": "user", "content": "请逐步解释黑洞"}],
        thinking={"type": "enabled"},
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "thinking_delta":
                print(f"[推理中]：{event.delta.thinking}", end="", flush=True)
            elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                print(event.delta.text, end="", flush=True)
    print()
except Exception as e:
    print(f"\n发生错误：{e}")
```

## ✅ 测试

项目包括具有追踪功能的综合测试套件。

1. **设置 `PYTHONPATH`**：
   为确保测试可导入应用程序模块，从项目根目录设置您的 `PYTHONPATH`。
   ```bash
   # 来自 treehouse/
   export PYTHONPATH=.
   ```

2. **运行测试**：
   从项目根目录使用 `unittest` 发现并运行所有测试。
   ```bash
   # 来自 treehouse/
   python -m unittest discover tests/claude_code_proxy_tests/ -v
   ```

3. **高级测试**：
   ```bash
   # 使用追踪分析运行
   python -c "
   import claude_code_proxy.main as main_module
   print('测试导入结构...')
   print('可用模块：', main_module)
   "
   ```

## 📊 架构概览

```
客户端 (Anthropic 格式) → 代理 → 提供商 A (OpenAI 格式)
                                      ↗
                                   提供商 B
                                      ↘
                                   提供商 C
```

### 核心组件
- **提供商路由器**：基于模型和推理要求智能路由
- **请求转换器**：Anthropic → OpenAI 格式转换
- **响应转换器**：OpenAI → Anthropic 格式转换
- **身份验证管理器**：多个提供商 API 密钥管理
- **速率限制**：每个提供商的可配置节流
- **日志系统**：用于调试和审计的结构化日志，包括上下文路由决策的详细记录

## 🔧 开发与调试

### 热重载开发
```bash
# 运行自动重载以供主动开发
python -m claude_code_proxy.main --config my_config.yml --reload
```

### 调试模式
```bash
# 启用全面调试功能
export DEBUG_PROXY=true
python -m claude_code_proxy.main --config my_config.yml --log-level DEBUG
```

### 上下文路由日志示例
当启用详细日志时，你会看到如下的上下文路由决策记录：

```json
{
  "level": "WARNING",
  "message": "Specific provider 'Provider 1' lacks sufficient context (4000 < 7000 tokens). Continuing search...",
  "timestamp": "2024-01-15T10:30:45.123Z",
  "model": "claude-3-opus-20240229",
  "required_context": 7000,
  "provider_capacity": 4000
}

{
  "level": "INFO", 
  "message": "Selected provider 'Provider 2' with sufficient context (16000 >= 7000 tokens)",
  "timestamp": "2024-01-15T10:30:45.125Z",
  "model": "claude-3-opus-20240229",
  "selected_provider": "provider2",
  "provider_capacity": 16000,
  "required_context": 7000
}
```

### 自定义提供商集成
通过扩展基础配置添加新提供商：

```yaml
providers:
  openai_providers:
    new_provider:
      name: "CustomProvider"
      type: "openai"
      base_url: "https://api.custom-provider.com/v1"
      api_key: "sk-..."
      supports_reasoning: true
      default_models:
        "claude-sonnet-4-20250514": "gpt-4o"
```

## 📄 许可证

MIT 许可证 - 有关详情，请参阅 LICENSE 文件

## 🤝 贡献

欢迎贡献！请阅读贡献指南并确保在提交 PR 之前通过所有测试。

## 📈 性能监控

代理包括内置性能示例：
- 请求延迟跟踪
- 提供商响应时间
- 令牌使用统计
- 错误率监控

在调试模式下运行时通过调试端点访问指标。

## 🔬 增强响应转换（V2版）

代理现在包括一个完全重写的响应转换系统，支持高级功能：

### 🧠 推理内容处理
自动将提供商的推理/思维内容转换为Anthropic格式：
- 支持OpenAI风格的`reasoning_content`字段
- 自动转换为`thinking_delta`和`thinking`内容块
- 为每个思考块生成SHA-256签名校验
- 保持流传输的实时解析

```json
// 输入（OpenAI格式）
{
  "delta": {
    "content": "",
    "reasoning_content": "让我逐步思考这个问题..."
  }
}

// 输出（Anthropic格式）
{
  "type": "content_block_start",
  "index": 0,
  "content_block": {
    "type": "thinking",
    "thinking": ""
  }
}
```

### 🔧 自定义工具调用解析
支持新的自定义工具调用格式，即使提供商不直接支持标准工具调用：

```
|tool_call_begin|>工具名称:唯一ID参数|<{tool_argument_begin}>JSON参数字符串<|tool_call_end|>
```

示例：
```
|tool_call_begin|>functions.calculate:123<|tool_call_argument_begin>{"expression": "2+2"}<|tool_call_end|>
```

### 📊 内容块管理
- **动态类型转换**：文本、思考内容、工具调用之间的无缝转换
- **缓冲处理**：正确处理部分和不完整的工具调用标签
- **错误恢复**：格式错误的工具调用会优雅地降级为文本内容
- **并行支持**：并发处理多个工具调用

### 🧪 测试能力
代理包括增强的测试功能：

```bash
# 运行全面的响应转换测试
python -m unittest tests.claude_code_proxy_tests.test_response_translator_v2 -v

# 运行带实时跟踪的调试测试
python -c "
from unittest import main
from tests.claude_code_proxy_tests.test_response_translator_v2 import *
main(module='__main__')
"
```

### 📈 性能特征
新的V2转换器：
- **状态管理**：每请求独立状态隔离
- **内存效率**：流式处理，无缓冲累积
- **时间复杂度**：O(n)，其中n是输出令牌数量
- **空间复杂度**：O(1)，恒定内存使用