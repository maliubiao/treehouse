"""
用大模型批量修改源代码, 在控制流语句前后插入trace代码
然后重新编译，跑代码，看看程序是怎么运行的
只靠LSP无法解决实际代码运行时序的问题，比如队列,callback, 异步等
"""

import os
import sys
from pathlib import Path

from debugger.tracer import TraceConfig, start_trace
from llm_query import ModelSwitch, process_patch_response
from tree import ParserLoader as PL
from tree import ParserUtil as PU

parser_loader_s = PL()
parser_util = PU(parser_loader_s)
file_path = sys.argv[1]
results, code_map = parser_util.get_symbol_paths(file_path)

prompt_text_path = Path(os.path.dirname(__file__)).parent / "prompts/code-trace"
dump_example_path = Path(os.path.dirname(__file__)).parent / "prompts/dumb-example"
# symbol_rule_path = Path(os.path.dirname(__file__)).parent / "prompts/symbol-path-rule-v2"
prompt = prompt_text_path.read_text(encoding="utf-8")
prompt += "\n\n"
tag = "symbol"
modified_type = "symbol"
prompt += """
# 响应格式
[modified whole {modified_type}]: 符号路径
[{tag} start]
完整文件内容
[{tag} end]

或（无修改时）:
[modified whole {modified_type}]: 符号路径
[{tag} start]
完整原始内容
[{tag} end]
"""
# prompt += symbol_rule_path.read_text(encoding="utf-8") + "\n\n"
prompt += dump_example_path.read_text(encoding="utf-8") + "\n\n"


fixed_part = prompt
text_list = []
total_length = 0
max_length = 65535
current_length = max_length - len(fixed_part)
batch = []
batch_length = 0

ms = ModelSwitch()
ms.select("coder")
symbol_detail_map = {}
responses = []


def process_batch(batch):
    """处理当前批次的数据"""
    if not batch:
        return
    batch_prompt = fixed_part + "\n".join(batch)
    print(batch_prompt)
    print(f"Processing batch with {len(batch)} symbols, length: {len(batch_prompt)}")
    response = ms.query_for_text("coder", batch_prompt)
    responses.append(response)
    print(f"Received response for batch")
    # 这里可以添加对响应的处理逻辑


for symbol_name, symbol in code_map.items():
    symbol["file_path"] = file_path
    if symbol["type"] not in ("function", "class", "namespace"):
        continue
    symbol_detail_map[f"{file_path}/{symbol_name}"] = {
        "file_path": file_path,
        "block_range": symbol["block_range"],
        "block_content": symbol["code"].encode("utf-8"),
    }
    one_symbol = f"""
[SYMBOL START]
符号路径: {file_path}/{symbol_name}

[source code start]
{symbol["code"] if isinstance(symbol["code"], str) else symbol["code"].decode("utf-8")}
[source code end]

[SYMBOL END]
"""
    symbol_length = len(one_symbol)

    if batch_length + symbol_length > current_length:
        process_batch(batch)
        batch = []
        batch_length = 0

    batch.append(one_symbol)
    batch_length += symbol_length

# 处理最后一批
process_batch(batch)

process_patch_response("\n".join(responses), symbol_detail_map)

print("All symbols processed successfully")
