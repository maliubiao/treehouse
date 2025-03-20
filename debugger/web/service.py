import bdb
import json
import logging
import os
import sys
import threading
from pdb import Pdb

import tornado.ioloop
import tornado.web
import tornado.websocket
from tornado.options import define

define("port", default=5555, help="run on the given port", type=int)

# Configure logging
logging.basicConfig(level=0, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def null_breakpoint():
    pass


class DebugWebSocket(tornado.websocket.WebSocketHandler):
    clients = set()

    def open(self):
        self.clients.add(self)
        logger.debug("WebSocket连接已打开")

    def on_close(self):
        self.clients.remove(self)
        logger.debug("WebSocket连接已关闭")

    def on_message(self, message):
        """处理客户端消息"""
        logger.debug("收到客户端消息: %s", message)

    def data_received(self, chunk):
        """处理数据流"""
        super().data_received(chunk)

    def check_origin(self, origin):
        return True

    @classmethod
    def broadcast(cls, message):
        for client in cls.clients:
            try:
                client.write_message(json.dumps(message))
            except tornado.websocket.WebSocketClosedError as e:
                logger.warning("客户端连接已关闭: %s", e)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("广播消息失败: %s", e)


class BreakpointHandler(tornado.web.RequestHandler):
    def data_received(self, chunk):
        """处理数据流"""
        super().data_received(chunk)

    async def post(self):
        try:
            data = json.loads(self.request.body)
            variables = data.get("variables", [])
            filename = os.path.abspath(data["file"])

            if not os.path.isfile(filename):
                logger.error("文件不存在: %s", filename)
                self.set_status(400)
                self.write({"status": "error", "message": "文件不存在"})
                return

            line = data.get("line")
            function_name = data.get("function")
            condition = data.get("condition")
            bp_args = []

            if function_name:
                bp_args.append(f"{function_name}")
            elif line is not None:
                bp_args.append(f"{filename}:{line}")

            if condition:
                bp_args.append(f", {condition}")

            debugger = self.application.settings["debugger"]
            debugger.message("")  # 初始化last_msg
            debugger.do_break(" ".join(bp_args))
            result = debugger.last_msg

            if "Breakpoint" in result:
                bp_id = int(result.split(" ")[1])
                debugger.breakpoints[bp_id] = {
                    "file": filename,
                    "line": line or debugger.get_breaks(filename, function_name)[0].lineno,
                    "condition": condition,
                    "variables": variables,
                    "function": function_name,
                }
                logger.info("成功设置断点: %s", result.strip())
                self.write({"status": "ok", "id": bp_id})
            else:
                logger.error("设置断点失败: %s", result)
                self.set_status(400)
                self.write({"status": "error", "message": result})

        except (KeyError, ValueError, IndexError) as e:
            logger.error("请求参数错误: %s", e)
            self.set_status(400)
            self.write({"status": "error", "message": f"无效的请求参数: {str(e)}"})
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("设置断点时出错: %s", e)
            self.set_status(500)
            self.write({"status": "error", "message": str(e)})

    async def get(self):
        debugger = self.application.settings["debugger"]
        breakpoints = [
            {"id": bp.number, "file": bp.file, "line": bp.line, "function": bp.funcname, "condition": bp.cond}
            for bp in debugger.get_all_breaks()
            if bp
        ]
        logger.debug("获取到的断点列表: %s", breakpoints)
        self.write({"breakpoints": breakpoints})

    async def delete(self, bp_id):
        try:
            debugger = self.application.settings["debugger"]
            debugger.message("")  # 初始化last_msg
            debugger.do_clear(f" {bp_id}")
            result = debugger.last_msg
            if "Deleted" in result:
                debugger.breakpoints.pop(int(bp_id), None)
                logger.info("成功删除断点 %s", bp_id)
                self.write({"status": "ok"})
            else:
                logger.error("删除断点失败: %s", result)
                self.set_status(400)
                self.write({"status": "error", "message": result})
        except (ValueError, KeyError) as e:
            logger.error("无效的断点ID: %s", e)
            self.set_status(400)
            self.write({"status": "error", "message": "无效的断点ID"})
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("删除断点时出错: %s", e)
            self.set_status(500)
            self.write({"status": "error", "message": str(e)})


class VariableHandler(tornado.web.RequestHandler):
    def data_received(self, chunk):
        """处理数据流"""
        super().data_received(chunk)

    async def post(self):
        data = json.loads(self.request.body)
        self.application.settings["debugger"].var_watch_list.update(data["variables"])
        logger.debug("更新监视列表，添加变量: %s", data["variables"])
        self.write({"status": "ok"})


class DebuggerWebUI(Pdb):
    def __init__(self, port=5555, start_loop=True):
        super().__init__()
        self.port = port
        self.breakpoints = {}
        self.var_watch_list = set()
        self.watched_files = set()
        self.last_msg = ""
        self.curframe = None  # 初始化curframe属性
        self._setup_tornado(start_loop)
        self._server = None
        self._ioloop = None

    def _setup_tornado(self, start_loop):
        current_dir = os.path.dirname(__file__)
        template_path = os.path.join(current_dir, "templates")
        static_path = os.path.join(current_dir, "static")

        self.app = tornado.web.Application(
            [
                (r"/", self.MainHandler),
                (r"/ws", DebugWebSocket),
                (r"/breakpoints", BreakpointHandler),
                (r"/breakpoints/(\d+)", BreakpointHandler),
                (r"/variables", VariableHandler),
                (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": static_path}),
            ],
            template_path=template_path,
            debugger=self,
        )
        if start_loop:
            self._server = self.app.listen(self.port)
            self._ioloop = tornado.ioloop.IOLoop.current()
            threading.Thread(target=self._ioloop.start, daemon=True).start()
            logger.info("调试器Web UI已启动，端口为 %s", self.port)

    def close(self):
        if self._server:
            self._server.stop()
        if self._ioloop:
            self._ioloop.add_callback(self._ioloop.stop)
        logger.info("调试器Web UI已停止")

    class MainHandler(tornado.web.RequestHandler):
        def data_received(self, chunk):
            """处理数据流"""
            super().data_received(chunk)

        async def get(self):
            self.render("debugger.html")

    def message(self, msg):
        print(msg)
        self.last_msg = msg

    def _evaluate_variable(self, frame, var_name):
        try:
            # pylint: disable=eval-used
            value = eval(var_name, frame.f_globals, frame.f_locals)
            type_name = type(value).__name__
            if isinstance(value, (list, dict, tuple, set)):
                return {"value": value, "type": type_name, "complex": True}
            return {"value": value, "type": type_name, "complex": False}
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("评估变量 %s 时出错: %s", var_name, e)
            return {"value": f"评估错误: {str(e)}", "type": "error", "complex": False}

    def _collect_and_send_data(self, frame, variables):
        var_data = {}
        for var in variables:
            evaluated = self._evaluate_variable(frame, var)
            var_data[var] = self._safe_serialize(evaluated)

        DebugWebSocket.broadcast(
            {"type": "variables", "data": var_data, "location": f"{frame.f_code.co_filename}:{frame.f_lineno}"}
        )
        logger.info("收集并发送的变量数据: %s", var_data)

    def get_all_breaks(self):
        """获取所有pdb管理的断点"""
        return bdb.Breakpoint.bpbynumber

    def _update_watched_files(self, filename):
        """更新关注文件集合"""
        if filename not in self.watched_files:
            self.watched_files.add(filename)
            logger.info("新增关注文件: %s", filename)

    def _cleanup_watched_files(self, filename):
        """清理不再需要关注的文件"""
        remaining = any(bp.file == filename for bp in self.get_all_breaks())
        if not remaining:
            self.watched_files.discard(filename)
            logger.info("移除不再关注的文件: %s", filename)

    def _should_stop_at_breakpoint(self, frame):
        current_file = os.path.abspath(frame.f_code.co_filename)
        current_line = frame.f_lineno

        if current_file not in self.watched_files:
            return False

        return super().break_here(frame)

    def user_line(self, frame):
        breaks = self.get_all_breaks()
        target_bp = None
        for bp in breaks:
            if not bp:
                continue
            if os.path.abspath(bp.file) == frame.f_code.co_filename and bp.line == frame.f_lineno:
                target_bp = self.breakpoints[bp.number]
                break
        logger.info("在 %s:%s 处触发断点", frame.f_code.co_filename, frame.f_lineno)
        if target_bp:
            self._collect_and_send_data(frame, target_bp["variables"])
            self._send_stack_trace(frame)
            self._send_breakpoint_variables(frame)

    def _send_stack_trace(self, frame):
        stack_trace = self._get_stack_trace(frame)
        DebugWebSocket.broadcast({"type": "stack_trace", "data": stack_trace})
        logger.info("发送的堆栈跟踪: %s", stack_trace)

    def _send_breakpoint_variables(self, frame):
        current_file = os.path.abspath(frame.f_code.co_filename)

        for bp in self.get_all_breaks():
            if not bp:
                continue
            if os.path.abspath(bp.file) == current_file and bp.line == frame.f_lineno:
                var_data = {}
                for var in self.breakpoints.get(bp.number, {}).get("variables", []):
                    if var in frame.f_locals:
                        evaluated = self._evaluate_variable(frame, var)
                        var_data[var] = self._safe_serialize(evaluated)

                DebugWebSocket.broadcast(
                    {"type": "breakpoint_variables", "data": var_data, "location": f"{current_file}:{frame.f_lineno}"}
                )
                logger.info("发送的断点变量数据: %s", var_data)

    def _get_stack_trace(self, frame):
        stack = []
        while frame:
            stack.append(
                {"filename": frame.f_code.co_filename, "lineno": frame.f_lineno, "function": frame.f_code.co_name}
            )
            frame = frame.f_back
        return stack

    def _safe_serialize(self, obj):
        try:
            if isinstance(obj, dict) and "value" in obj and "type" in obj:
                serialized_value = json.dumps(obj["value"], default=repr)
                return {"value": serialized_value, "type": obj["type"], "complex": obj.get("complex", False)}
            return {"value": json.dumps(obj, default=repr), "type": "unknown", "complex": False}
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("序列化对象时出错: %s", e)
            return {"value": f"序列化错误: {str(e)}", "type": "error", "complex": False}


def start_debugger(port=5555):
    debugger = DebuggerWebUI(port=port)
    # pylint: disable=protected-access
    debugger.curframe = sys._getframe()
    debugger.do_break("null_breakpoint")
    debugger.set_trace(sys._getframe().f_back)
    logger.info("调试器已启动")
