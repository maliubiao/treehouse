
## 持续验证与追踪 (Continuous Verification & Tracing)
**验证优先：** 在每次完成有意义的代码修改后，你必须主动考虑使用 `trace_python` 工具来验证你的修改是否符合预期。这是一个强制性的反馈环节。
**制定追踪策略：** 由于 `trace_python` 工具作用于文件或模块入口，你需要根据情况制定策略：

**直接追踪：** 如果你的修改可以直接通过运行一个脚本或模块来触发（例如，修改了一个命令行工具），则直接追踪该入口。
**临时验证脚本：** 如果你修改的是一个库中的特定函数或方法，你应该创建一个临时的Python文件（如 `temp_trace_verifier.py`），在其中导入你修改的模块，调用相关函数，然后使用 `trace_python` 追踪这个临时脚本, 这个临时脚本验证过后，需要写成unittest文件, test_开头，固定下来
**通过测试追踪：** 编写一个针对性的单元测试，然后使用 `trace_python` 追踪该测试文件的执行，也是一种非常好的验证方法。
**分析追踪日志：** 仔细检查生成的 `.log` 追踪日志，确认函数调用顺序、参数、变量变化和返回值与你的设计意图完全一致。
**注意事项：** 被追踪的程序路径应避免出现死循环、长时间的阻塞操作（如网络请求或大型文件读写）以及复杂的异步代码，以确保追踪可以在合理时间内完成。此工具仅适用于追踪Python代码, 

## 编写临时脚本 
写临时脚本要注意，临时脚本不属于任何包，不可以使用. ..相对导入, 你必须避免直接导入同级目录下的文件,因为它们里边很可能使用了相对导入
需要在sys.path中insert临时脚本的parent.parent，通过它的父目录,作为包名，导致它同目录下的文件的函数 
这需要你先list一下当前目录，获取fullpath, 找到parent的名，作为包名，再用包名.submodule 访问里边的函数

## HTTP MCP 服务器使用指南

### 启动 HTTP 服务器
```bash
# 从项目根目录启动
python -m claude_code_proxy.src.http_mcp_server

# 自定义端口和主机
python -m claude_code_proxy.src.http_mcp_server --host 0.0.0.0 --port 8000

# 启用调试模式
python -m claude_code_proxy.src.http_mcp_server --log-level DEBUG
```

### 测试 HTTP 服务器
```bash
# 运行综合测试
python tools/claude_code_proxy/src/test_http_mcp_client.py

# 测试特定服务器
python tools/claude_code_proxy/src/test_http_mcp_client.py http://localhost:8000
```

### Claude Code 集成配置
claude mcp add --transport http tracer http://xxxxx


### 验证追踪功能

创建测试脚本验证追踪功能：

```python
# test_trace_validation.py
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from claude_code_proxy.src.http_mcp_server import HTTPMCPServer

async def test_trace_functionality():
    server = HTTPMCPServer()
    
    # 测试初始化
    init_result = await server.handle_initialize({})
    print("Initialize result:", init_result)
    
    # 测试工具列表
    tools_result = await server.handle_tools_list()
    print("Available tools:", [t['name'] for t in tools_result['tools']])

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_trace_functionality())
``` 

