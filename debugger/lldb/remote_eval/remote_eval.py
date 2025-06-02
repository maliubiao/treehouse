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


class DebugContext:
    """调试上下文管理类，提供代码执行和上下文管理功能"""

    def __init__(self, frame: FrameType = None):
        """
        初始化调试上下文

        Args:
            frame: 要绑定的堆栈帧（可选），默认为创建新的上下文环境
        """
        if frame:
            # 绑定到指定帧的上下文
            self.globals = frame.f_globals
            self.locals = frame.f_locals
        else:
            # 创建新的上下文环境
            self.globals = {"__builtins__": builtins}
            self.locals = {}
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

    try:
        # 保持主线程运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 正在停止调试服务器...")
        server.stop()
        print("✅ 服务器已停止")


if __name__ == "__main__":
    run()
