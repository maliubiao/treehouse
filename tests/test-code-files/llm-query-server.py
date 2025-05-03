# pylint: skip-file
"""
虚构的LLM API服务，用于测试query_gpt_api函数
当收到特定prompt时返回预设响应
"""

import json
import threading

import requests
from flask import Flask, Response, request


class MockLLMServer:
    def __init__(self, port=8000):
        self.port = port
        self.app = Flask(__name__)
        self.server = None
        self.setup_routes()

    def setup_routes(self):
        @self.app.route("/v1/chat/completions", methods=["POST"])
        def handle_chat():
            data = request.json
            # 预定义响应规则
            response_content = self._get_mock_response(data)

            # 流式响应格式
            def generate():
                for chunk in self._build_streaming_response(response_content):
                    yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return Response(generate(), mimetype="text/event-stream")

        @self.app.route("/shutdown", methods=["GET"])
        def shutdown():
            func = request.environ.get("werkzeug.server.shutdown")
            if func is None:
                raise RuntimeError("Not running with the Werkzeug Server")
            func()
            return "Server shutting down..."

    def _get_mock_response(self, request_data):
        # 定义测试用例与响应的映射
        test_case = request_data.get("test_case")
        if test_case:
            responses = {
                "thinking_test": "\n[内部推理]\n\n\nFinal answer",
                "normal_test": "standard response content",
                "error_test": {"error": "simulated API error"},
                "multi_chunk_test": "first_chunk second_chunk third_chunk",
            }
            return responses.get(test_case, "default_test_response")

        # 兼容旧的prompt匹配方式
        prompt = request_data["messages"][-1]["content"].lower()
        legacy_responses = {
            "test": "test response",
            "hello": "hello! how can I help you?",
            "error": {"error": "mock error response"},
        }
        return legacy_responses.get(prompt, "default mock response")

    def _build_streaming_response(self, content):
        # 处理特殊格式的思维响应
        if isinstance(content, str) and content.startswith("") and "\n\n" in content:
            reasoning_part, final_part = content.split("\n\n", 1)
            reasoning_part += "\n\n"

            # 先发送完整思维部分
            yield {
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "delta": {"content": reasoning_part, "role": "assistant"},
                        "index": 0,
                        "finish_reason": None,
                    }
                ],
            }

            # 分割最终答案部分
            words = final_part.split()
            for i, word in enumerate(words):
                yield {
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "delta": {
                                "content": word + (" " if i < len(words) - 1 else ""),
                                "role": "assistant",
                            },
                            "index": 0,
                            "finish_reason": None,
                        }
                    ],
                }
        else:
            # 处理普通文本或JSON错误
            if isinstance(content, dict):
                content = json.dumps(content)

            words = content.split() if isinstance(content, str) else [content]
            for i, word in enumerate(words):
                yield {
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "delta": {
                                "content": (str(word) + " ")
                                if i < len(words) - 1
                                else str(word),
                                "role": "assistant",
                            },
                            "index": 0,
                            "finish_reason": None,
                        }
                    ],
                }

        # 结束块
        yield {
            "object": "chat.completion.chunk",
            "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
        }

    def start(self):
        self.server = threading.Thread(target=self.app.run, kwargs={"port": self.port})
        self.server.start()

    def stop(self):
        requests.get(f"http://localhost:{self.port}/shutdown", timeout=5)


if __name__ == "__main__":
    # 示例用法
    server = MockLLMServer(port=8000)
    server.start()

    # 测试请求
    response = requests.post(
        "http://localhost:8000/v1/chat/completions",
        json={
            "test_case": "thinking_test",  # 使用新的测试用例标识
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "dummy"}],
            "stream": True,
        },
        timeout=5,
    )

    # 打印流式响应
    for line in response.iter_lines():
        if line:
            print(line.decode("utf-8"))

    server.stop()
