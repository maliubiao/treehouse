import builtins
import io
import os
import sys
import time
import traceback
from contextlib import redirect_stdout
from threading import Thread
from types import FrameType

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server


class DebugUtils:
    """调试工具类，提供自定义函数供调试环境使用"""

    def __init__(self):
        """初始化工具类"""
        self.counter = 0  # 示例计数器

    def askgpt(self, context: str) -> str:
        """
        向LLM提问的示例函数（实际应用中需替换为真正的LLM调用）

        Args:
            context: 提供给LLM的上下文信息

        Returns:
            LLM生成的回答（当前为示例实现）
        """
        self.counter += 1
        return f"这是askgpt函数的示例响应 #{self.counter}。你提供的上下文是: {context[:50]}{'...' if len(context) > 50 else ''}"

    def save_file(self, content: str, filename: str = "debug_output.txt") -> str:
        """
        将内容保存到文件

        Args:
            content: 要保存的内容
            filename: 文件名（默认为debug_output.txt）

        Returns:
            操作结果信息
        """
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            return f"✅ 内容已保存到: {os.path.abspath(filename)}"
        except Exception as e:
            return f"❌ 保存文件失败: {str(e)}"

    def get_timestamp(self) -> str:
        """获取当前时间戳"""
        return time.strftime("%Y-%m-%d %H:%M:%S")


class DebugContext:
    """调试上下文管理类，提供代码执行和上下文管理功能"""

    def __init__(self, frame: FrameType = None):
        """
        初始化调试上下文

        Args:
            frame: 要绑定的堆栈帧（可选），默认为创建新的上下文环境
        """
        # 创建工具类实例
        self.utils = DebugUtils()

        if frame:
            # 绑定到指定帧的上下文
            self.globals = frame.f_globals
            self.locals = frame.f_locals
            # 注入工具类实例
            self.locals["utils"] = self.utils
        else:
            # 创建新的上下文环境
            self.globals = {"__builtins__": builtins}
            self.locals = {"utils": self.utils}

        self.history = []

    def execute(self, code: str) -> dict:
        """
        执行代码片段并返回结果

        Args:
            code: 要执行的Python代码字符串

        Returns:
            包含执行结果的字典:
            {
                "status": "success" | "error",
                "output": 标准输出内容,
                "error": 错误信息（如果有）
            }
        """
        stdout = io.StringIO()
        result = {"status": "success", "output": "", "error": ""}

        try:
            with redirect_stdout(stdout):
                # pylint: disable=exec-used
                exec(code, self.globals, self.locals)
        except Exception as exc:  # 捕获所有非系统退出异常，因为调试需要
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
        finally:
            # 获取输出内容
            result["output"] = stdout.getvalue()

            # 记录执行历史
            self.history.append(
                {
                    "code": code,
                    "result": result.copy(),  # 避免后续修改影响历史记录
                    "timestamp": time.time(),
                }
            )

            # 限制历史记录长度
            if len(self.history) > 20:
                self.history.pop(0)

        return result

    def get_safe_context(self) -> dict:
        """
        获取安全的上下文信息（过滤掉内置变量和敏感信息）

        Returns:
            包含安全上下文信息的字典:
            {
                "globals": [全局变量名列表],
                "locals": [局部变量名列表],
                "history": [执行历史摘要]
            }
        """
        # 过滤掉内置变量和私有变量
        safe_globals = [k for k in self.globals if not k.startswith("__") and not callable(self.globals[k])]

        safe_locals = [k for k in self.locals if not k.startswith("__") and not callable(self.locals[k])]

        # 历史记录摘要（不含完整结果）
        history_summary = [
            {"code": h["code"][:100] + "..." if len(h["code"]) > 100 else h["code"], "timestamp": h["timestamp"]}
            for h in self.history
        ]

        return {
            "globals": safe_globals,
            "locals": safe_locals,
            "history": history_summary,
        }


class DebugServer:
    """调试服务器类，提供基于HTTP的远程代码执行接口"""

    def __init__(self, port: int = 5678, context: DebugContext = None):
        """
        初始化调试服务器

        Args:
            port: 服务器端口号，默认为5678
            context: 调试上下文对象，默认为新建的上下文
        """
        self.app = Flask(__name__)
        self.port = port
        self.context = context if context else DebugContext()
        self.server = None
        self.thread = None
        self.setup_routes()

    def setup_routes(self):
        """设置Flask路由"""

        @self.app.route("/")
        def index():
            """主页面路由，返回调试器UI"""
            return send_from_directory("static", "index.html")

        @self.app.route("/<path:path>")
        def static_files(path: str):
            """静态文件路由"""
            return send_from_directory("static", path)

        @self.app.route("/execute", methods=["POST"])
        def execute_code():
            """代码执行接口"""
            code = request.json.get("code", "")
            result = self.context.execute(code)
            return jsonify(result)

        @self.app.route("/context", methods=["GET"])
        def get_context():
            """获取上下文信息接口"""
            return jsonify(self.context.get_safe_context())

        @self.app.route("/health")
        def health_check():
            """健康检查接口"""
            return jsonify({"status": "ok", "timestamp": time.time()})

    def start(self, daemon: bool = True):
        """启动调试服务器"""
        if not os.path.exists("static"):
            os.makedirs("static")

        self.server = make_server("0.0.0.0", self.port, self.app)
        self.thread = Thread(target=self.server.serve_forever)
        self.thread.daemon = daemon
        self.thread.start()
        return self

    def stop(self):
        """停止调试服务器"""
        if self.server:
            self.server.shutdown()
            self.thread.join()


def run(port: int = 5678):
    """
    启动调试服务器并绑定到当前帧上下文

    使用示例:
        import remote_eval
        remote_eval.run()  # 默认端口5678

    这将启动HTTP服务器并打印访问地址

    🆕 调试环境中已注入自定义工具类:
        - utils.askgpt(context): 向LLM提问的示例函数
        - utils.save_file(content, filename): 保存内容到文件
        - utils.get_timestamp(): 获取当前时间戳

    Args:
        port: 服务器端口号，默认为5678
    """
    # 获取调用者帧作为执行上下文
    frame = sys._getframe(1) if hasattr(sys, "_getframe") else None

    # 创建带上下文的调试服务器
    server = DebugServer(port=port, context=DebugContext(frame))
    server.start(daemon=False)

    print(f"🚀 调试服务器已启动: http://localhost:{port}")
    print("🛑 按 Ctrl+C 停止服务器")
    print("💡 提示: 在浏览器中打开上述地址使用交互式调试器")
    print("🆕 调试环境中已注入自定义工具类 `utils`:")
    print("    - utils.askgpt(context): 向LLM提问的示例函数")
    print("    - utils.save_file(content, filename): 保存内容到文件")
    print("    - utils.get_timestamp(): 获取当前时间戳")

    try:
        # 保持主线程运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 正在停止调试服务器...")
        server.stop()
        print("✅ 服务器已停止")


def sample_function(param1: str = "默认值", param2: int = 42):
    """
    示例函数，用于展示调试上下文绑定效果

    当直接运行 remote_eval.py 时，将在此函数的上下文中启动调试服务器
    在调试器中可以访问以下变量：
    - param1: 字符串参数
    - param2: 整数参数
    - sample_list: 示例列表
    - sample_dict: 示例字典
    - sample_value: 示例变量

    🆕 调试环境中已注入自定义工具类 `utils`:
        - utils.askgpt(context): 向LLM提问的示例函数
        - utils.save_file(content, filename): 保存内容到文件
        - utils.get_timestamp(): 获取当前时间戳

    示例代码:
        print(f"参数1: {param1}, 参数2: {param2}")
        print(f"示例列表: {sample_list}")
        print(f"示例字典: {sample_dict}")
        sample_value += 10
        print(f"修改后的值: {sample_value}")

        # 使用自定义工具函数
        response = utils.askgpt("请解释这个函数")
        print(f"LLM响应: {response}")

        utils.save_file("测试内容", "test.txt")
    """
    # 创建一些变量用于调试
    sample_list = [1, 2, 3, 4, 5]
    sample_dict = {"key1": "value1", "key2": 100}
    sample_value = 42

    print("=" * 60)
    print("进入示例调试上下文...")
    print(f"局部变量: param1={param1}, param2={param2}")
    print(f"示例变量: sample_list={sample_list}, sample_dict={sample_dict}, sample_value={sample_value}")
    print("=" * 60)
    print("💡 提示: 在调试器中可以操作这些变量")
    print("🆕 提示: 可以使用 `utils` 对象调用自定义函数:")
    print("    - utils.askgpt(context): 向LLM提问")
    print("    - utils.save_file(content, filename): 保存内容")
    print("    - utils.get_timestamp(): 获取时间戳")

    # 启动调试服务器，绑定到当前帧
    run()


if __name__ == "__main__":
    # 调用示例函数，传入测试参数
    sample_function("测试参数", 100)
