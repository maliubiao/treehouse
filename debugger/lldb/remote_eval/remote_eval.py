import builtins
import io
import os
import sys
import time
import traceback
from contextlib import redirect_stdout
from threading import Thread

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server


class DebugContext:
    def __init__(self):
        self.globals = {"__builtins__": builtins}
        self.locals = {}
        self.history = []

    def execute(self, code: str) -> dict:
        stdout = io.StringIO()
        result = {"status": "success", "output": "", "error": ""}

        try:
            with redirect_stdout(stdout):
                exec(code, self.globals, self.locals)
        except Exception as e:
            result["status"] = "error"
            result["error"] = traceback.format_exc()
        finally:
            result["output"] = stdout.getvalue()
            self.history.append({"code": code, "result": result, "timestamp": time.time()})
            if len(self.history) > 20:
                self.history.pop(0)
            return result

    def get_safe_context(self):
        return {
            "globals": [k for k in self.globals if not k.startswith("__")],
            "locals": list(self.locals.keys()),
            "history": [{"code": h["code"], "timestamp": h["timestamp"]} for h in self.history],
        }


class DebugServer:
    def __init__(self, port=5678):
        self.app = Flask(__name__)
        self.port = port
        self.context = DebugContext()
        self.server = None
        self.thread = None
        self.setup_routes()

    def setup_routes(self):
        @self.app.route("/")
        def index():
            return send_from_directory("static", "index.html")

        @self.app.route("/<path:path>")
        def static_files(path):
            return send_from_directory("static", path)

        @self.app.route("/execute", methods=["POST"])
        def execute_code():
            code = request.json.get("code", "")
            result = self.context.execute(code)
            return jsonify(result)

        @self.app.route("/context", methods=["GET"])
        def get_context():
            return jsonify(self.context.get_safe_context())

        @self.app.route("/health")
        def health_check():
            return jsonify({"status": "ok", "timestamp": time.time()})

    def start(self, daemon=True):
        if not os.path.exists("static"):
            os.makedirs("static")

        self.server = make_server("0.0.0.0", self.port, self.app)
        self.thread = Thread(target=self.server.serve_forever)
        self.thread.daemon = daemon
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.thread.join()


def start_server(port=5678):
    server = DebugServer(port)
    server.start()
    return server


if __name__ == "__main__":
    server = start_server()
    print(f"Debug server running on http://localhost:5678")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("\nServer stopped")
