# Anthropic to OpenAI API Proxy

This project provides a highly flexible and robust proxy server that translates API requests from Anthropic's Messages API format to any OpenAI-compatible Chat Completions API. It's designed for production environments with a focus on configuration-driven routing, multi-provider support, and detailed logging.

## ✨ Key Features

-   **Seamless Translation:** Accurately translates Anthropic requests (including streaming, tool use, and batching) to the OpenAI format, and translates responses back.
-   **Full Client Compatibility:** Works out-of-the-box with the official `anthropic` Python client.
-   **Configuration-Driven Routing:** Use a single `config.yml` file to manage all behavior. No code changes needed to add new providers or change routing rules.
-   **Multi-Provider Support:** Route requests to various backends like OpenAI, OpenRouter, SiliconFlow, or local models (like Ollama) simultaneously.
-   **Reasoning-Aware Routing:** Intelligently routes requests with Anthropic's `thinking` parameter to providers that explicitly support reasoning/thinking features. The proxy correctly translates streaming `reasoning_content` into Anthropic `thinking_delta` events.
-   **Dynamic Model Mapping:** Map a single Anthropic model alias (e.g., `claude-3-5-sonnet`) to different target models on different providers (e.g., `openai/gpt-4o` on one, `deepseek/deepseek-r1` on another).
-   **Robustness Features:** Includes a `max_tokens_override` setting to prevent requests from failing on providers with strict token limits.
-   **Structured Logging:** Generates detailed JSON logs for the entire request lifecycle, making it easy to debug routing decisions and provider errors.

## 🧠 How It Works: The Routing Logic

The proxy's core strength is its routing engine. When a request for a model (e.g., `claude-3-5-sonnet-20241022`) arrives, the router follows these steps:

1.  **Check for Reasoning:** The router first checks if the incoming request has `thinking={"type": "enabled"}`.
2.  **Reasoning-First Routing:** If `thinking` is requested, the router will *only* consider providers with `supports_reasoning: true` in their configuration. It checks in this order:
    a. A specific provider defined in `anthropic.model_providers` for the requested model.
    b. The `anthropic.default_provider`.
    If no reasoning-capable provider is found, it logs a warning and proceeds to standard routing.
3.  **Standard Routing:** If `thinking` is not requested (or if no reasoning provider was found), it selects a provider in this order:
    a.  **Specific Model Mapping:** An entry for the model in `anthropic.model_providers`.
    b.  **Default Provider:** The `anthropic.default_provider`.
4.  **Translate and Forward:** The request is translated to the OpenAI format, using the target model name defined in the selected provider's `default_models` map, and sent to the provider's `base_url`.

This entire process is logged with a unique request ID, so you can trace exactly why a certain provider was chosen.

## ⚙️ Configuration (`config.yml`)

All proxy behavior is controlled by a single YAML file. Here is an annotated example based on the project's default `config.yml`:

```yaml
# Server host and port settings
server:
  host: "127.0.0.1"
  port: 8083

# Logging settings
logging:
  level: "INFO" # Can be DEBUG, INFO, WARNING, ERROR
  dir: "logs"

# Main provider configuration block
providers:
  # This section defines the routing rules for incoming Anthropic requests
  anthropic:
    name: "Anthropic"
    # The key of the provider to use if no specific model rule matches below.
    default_provider: "openai_provider1"
    # Maps specific Anthropic model names to a provider key from openai_providers.
    # This has higher priority than the default_provider.
    model_providers:
      # Example: "claude-sonnet-4-20250514": "openai_provider3"

  # This section defines all available downstream OpenAI-compatible providers
  openai_providers:
    # Key used for reference in the 'anthropic' section above
    openai_provider1:
      name: "OpenRouter" # Human-readable name for logs
      type: "openai"
      base_url: "https://openrouter.ai/api/v1"
      api_key: "sk-or-v1-..." # Your provider API key
      timeout: 600.0
      # Maps the incoming Anthropic model name to the actual model on this provider
      default_models:
        "claude-sonnet-4-20250514": "moonshotai/kimi-k2"
      # Does this provider support a reasoning/thinking feature?
      supports_reasoning: false
      # If the user requests more tokens than this, the value will be capped.
      # This prevents errors from providers with hard limits.
      max_tokens_override: 4096

    # A second provider, this one supporting reasoning
    openai_provider3:
      name: "siliconflow-r1"
      type: "openai"
      base_url: "https://api.siliconflow.cn/v1"
      api_key: "sk-..."
      supports_reasoning: true
      default_models:
        "claude-sonnet-4-20250514": "Pro/deepseek-ai/DeepSeek-R1"
      # Provider-specific config for enabling reasoning
      reasoning_config:
        thinking_budget_param: "thinking_budget"
        include_reasoning: true
      max_tokens_override: 8192
```

## 🚀 Getting Started

1.  **Install Dependencies:**
    From the project root (`terminal-llm/`), install the required packages.
    ```bash
    pip install -r tools/claude_code_proxy/requirements.txt
    ```

2.  **Create Configuration File:**
    The project includes `config.yml` as a template. It is recommended to copy it and modify it for your needs.
    ```bash
    cp tools/claude_code_proxy/config.yml my_config.yml
    ```
    Now, edit `my_config.yml` to:
    -   Add your provider `api_key` values.
    -   Adjust `base_url`s and `default_models` mappings.
    -   Set up your `anthropic` routing rules.
    -   Add `max_tokens_override` for providers that need token limits.

3.  **Run the Server:**
    From the project root, run the `main` module, pointing it to your configuration file.
    ```bash
    python -m tools.claude_code_proxy.main --config my_config.yml
    ```
    The server will start and print a summary of the loaded providers and routing rules.

## 👨‍💻 Usage with the Anthropic Client

Point the official `anthropic` Python client to your running proxy server.

1.  **Install the client:**
    ```bash
    pip install anthropic
    ```

2.  **Configure Environment:**
    Set the base URL to point to your proxy. The API key can be a dummy value as the proxy uses the keys from your `config.yml`.
    ```bash
    export ANTHROPIC_BASE_URL="http://127.0.0.1:8083/v1"
    export ANTHROPIC_API_KEY="dummy_key"
    ```

3.  **Example Python Script:**

    ```python
    import anthropic

    # The client automatically uses the environment variables
    client = anthropic.Anthropic()

    # --- Test 1: Standard request ---
    # This will use the routing rules in your config for this model.
    print("--- Testing Standard Request ---")
    message = client.messages.create(
        model="claude-sonnet-4-20250514", # Use a model name from your config
        max_tokens=100,
        messages=[{"role": "user", "content": "Hello, world!"}],
    )
    print(f"Response from model: {message.model}")
    print(message.content[0].text)

    # --- Test 2: Request with "thinking" ---
    # The proxy will prioritize a provider with `supports_reasoning: true`.
    # You will see 'thinking_delta' events in the stream if your provider yields them.
    print("\n--- Testing Reasoning Request ---")
    try:
        with client.messages.stream(
            model="claude-sonnet-4-20250514", # This model must be mapped to a reasoning provider
            max_tokens=1024,
            messages=[{"role": "user", "content": "Explain black holes step-by-step."}],
            thinking={"type": "enabled"},
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "thinking_delta":
                    print(f"[THINKING]: {event.delta.thinking}", end="", flush=True)
                elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                    print(event.delta.text, end="", flush=True)
        print()
    except Exception as e:
        print(f"\nAn error occurred: {e}")

    ```

## ✅ Testing

The project includes a comprehensive test suite.

1.  **Set `PYTHONPATH`:**
    To ensure tests can import the application modules, set your `PYTHONPATH` from the project root.
    ```bash
    # From terminal-llm/
    export PYTHONPATH=.
    ```

2.  **Run Tests:**
    From the project root, use `unittest` to discover and run all tests.
    ```bash
    # From terminal-llm/
    python -m unittest discover tests/claude_code_proxy_tests/ -v
    ```