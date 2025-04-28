import json
import unittest

import tornado.testing
import tornado.websocket
from service import DebuggerWebUI
from tornado.testing import gen_test


class DebuggerWebSocketTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.debugger = DebuggerWebUI(port=5555, start_loop=False)
        return self.debugger.app

    @gen_test
    async def test_websocket_connection(self):
        ws_url = f"ws://localhost:{self.get_http_port()}/ws"
        try:
            ws_client = await tornado.websocket.websocket_connect(ws_url, connect_timeout=5)
            # 测试连接状态
            self.assertIsNotNone(ws_client)
            ws_client.close()
            # 等待连接关闭
            with self.assertRaises(tornado.websocket.WebSocketClosedError):
                await ws_client.write_message("test")
        except tornado.websocket.WebSocketError as e:
            self.fail(f"WebSocket connection failed: {str(e)}")

    @gen_test
    async def test_breakpoint_lifecycle(self):
        # 使用测试文件实际存在的行号（选择有代码的行）
        valid_line = 30  # 更改为当前测试方法内的有效行号
        bp_data = {"file": __file__, "line": valid_line, "variables": ["var1", "var2"], "condition": "1 == 1"}

        # 创建断点
        response = await self.http_client.fetch(self.get_url("/breakpoints"), method="POST", body=json.dumps(bp_data))
        self.assertEqual(response.code, 200)
        result = json.loads(response.body)
        self.assertIn("id", result)
        bp_id = result["id"]

        # 获取断点列表
        response = await self.http_client.fetch(self.get_url("/breakpoints"))
        self.assertEqual(response.code, 200)
        breakpoints = json.loads(response.body)["breakpoints"]
        self.assertTrue(any(bp["id"] == bp_id for bp in breakpoints))

        # 删除断点
        response = await self.http_client.fetch(self.get_url(f"/breakpoints/{bp_id}"), method="DELETE")
        self.assertEqual(response.code, 200)

        # 验证删除结果
        response = await self.http_client.fetch(self.get_url("/breakpoints"))
        self.assertEqual(response.code, 200)
        updated_breakpoints = json.loads(response.body)["breakpoints"]
        self.assertFalse(any(bp["id"] == bp_id for bp in updated_breakpoints))

    @gen_test
    async def test_variable_monitoring(self):
        # 设置监控变量
        var_data = {"variables": ["test_var"]}
        response = await self.http_client.fetch(self.get_url("/variables"), method="POST", body=json.dumps(var_data))
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body)["status"], "ok")
        self.assertIn("test_var", self.debugger.var_watch_list)

    def test_debugger_initialization(self):
        debugger = DebuggerWebUI(start_loop=False)
        try:
            self.assertIsInstance(debugger, DebuggerWebUI)
            self.assertEqual(debugger.port, 5555)
        finally:
            debugger.close()


if __name__ == "__main__":
    unittest.main()
