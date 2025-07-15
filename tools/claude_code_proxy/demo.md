### 1. 环境准备

```bash
# 1. 切到项目根目录
cd /Users/richard/code/terminal-llm

# 2. 安装依赖
pip install -r tools/claude_code_proxy/requirements.txt
pip install anthropic  # 官方客户端，仅用于测试

# 3. 配置 OpenAI Key
cp tools/claude_code_proxy/.env.example tools/claude_code_proxy/.env
# 编辑 .env，填入 OPENAI_API_KEY
```

---

### 2. 一键启动 & 冒烟测试

```bash
# 启动代理（终端 1）
python -m tools.claude_code_proxy.main
# 看到 Uvicorn running on http://127.0.0.1:8000 即成功

# 冒烟测试（终端 2）
python tools/claude_code_proxy/run_demo.py
```
`run_demo.py` 会：
1. 自动拉起服务器子进程
2. 运行 `demo_client.py` 里的 4 组场景
3. 断言所有请求返回 200 且内容非空
4. 异常时打印 stderr 并退出码非 0

> ✅ 若终端 2 输出 `=== All tests completed ===` 即通过冒烟测试。

---

### 3. 手动验证清单（逐项对照）

| 验证点 | 命令/脚本 | 期望结果 |
|---|---|---|
| **非流式文本** | `demo_client.py` → `test_non_streaming_simple` | 返回 `Message` 对象，`content[0].type == "text"` |
| **流式文本** | `demo_client.py` → `test_streaming_simple` | 终端逐字输出，最后收到 `message_stop` 事件 |
| **非流式工具调用** | `demo_client.py` → `test_tool_use` | `stop_reason == "tool_use"`，且 `content` 含 `tool_use` block |
| **流式工具调用** | `demo_client.py` → `test_streaming_tool_use` | 事件序列包含 `content_block_start(tool_use)` → `input_json_delta` → `content_block_stop` |
| **Batch 接口** | 见下方「4. Batch 验证」 | 返回 `message_batch` 对象，可轮询状态并拉取 JSONL 结果 |

---

### 4. Batch 接口验证（可选）

```bash
# 1. 创建 batch
curl -X POST http://127.0.0.1:8000/v1/messages/batches \
  -H "Content-Type: application/json" \
  -d '{
    "requests": [
      {"custom_id":"req1","params":{"model":"claude-3-5-sonnet-20241022","max_tokens":10,"messages":[{"role":"user","content":"Hi"}]}},
      {"custom_id":"req2","params":{"model":"claude-3-5-sonnet-20241022","max_tokens":10,"messages":[{"role":"user","content":"Bye"}]}}
    ]
  }'

# 2. 记录返回的 batch_id
BATCH_ID=msgbatch_xxxxxxxx

# 3. 查询状态
curl http://127.0.0.1:8000/v1/messages/batches/$BATCH_ID

# 4. 拉取结果
curl http://127.0.0.1:8000/v1/messages/batches/$BATCH_ID/results
```
结果应为 **JSON Lines**，每行对应 `custom_id` 的 `succeeded` 或 `errored`。

---

### 5. 协议级断言（自动化测试）

```bash
# 运行单元 + 集成测试
export PYTHONPATH=/Users/richard/code/terminal-llm:$PYTHONPATH
python -m unittest discover tests/claude_code_proxy_tests/ -v
```

测试覆盖：
- `test_translator.py`
  - 请求翻译：Anthropic → OpenAI 字段映射正确
  - 响应翻译：OpenAI → Anthropic 字段映射正确
- `test_server.py`
  - 使用 `respx` Mock OpenAI，断言 HTTP 往返 & SSE 事件序列
  - 断言状态码、Header、事件类型、JSON Schema

> 所有测试通过即代表协议转换在语法与语义层面均正确。

---

### 6. 常见错误排查

| 现象 | 可能原因 | 解决 |
|---|---|---|
| `401 Authentication Error` | `.env` 中 `OPENAI_API_KEY` 无效 | 检查 key 是否以 `sk-` 开头 |
| `404 model not found` | 模型映射表未命中 | 在 `request_translator.py` 的 `MODEL_MAPPING` 里添加对应条目 |
| 流式输出乱码/中断 | 客户端未正确处理 SSE | 使用官方 `anthropic.Anthropic` 并设置 `ANTHROPIC_BASE_URL=http://127.0.0.1:8000/v1` |
| Batch 结果为空 | OpenAI Batch API 异步，需等待 | 轮询 `/v1/messages/batches/{id}` 直到 `processing_status=ended` |

---

### 7. 结论

完成以上 1-5 步后，即可**高置信度**地认定：

- 代理服务器已正确实现 Anthropic ↔ OpenAI 的双向协议转换
- 支持流式/非流式文本与工具调用
- 支持 Batch 作业
- 与官方 `anthropic` Python SDK 100% 兼容
