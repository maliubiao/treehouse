import inspect
import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class ExceptionHandler:
    def __init__(self):
        self.logger = logging.getLogger("ExceptionHandler")
        self.original_excepthook = sys.excepthook
        self.installed = False

    def install(self):
        """安装全局异常处理器"""
        if not self.installed:
            sys.excepthook = self._handle_exception
            self.logger.info("全局异常处理器已安装")
            self.installed = True

    def _handle_exception(self, exc_type, exc_value, exc_traceback):
        """处理未捕获的异常"""
        # 调用原始异常钩子
        self.original_excepthook(exc_type, exc_value, exc_traceback)
        # 收集异常信息
        exception_info = self._collect_exception_info(exc_type, exc_value, exc_traceback)

        path = Path(__file__).parent / "logs/auto_exception.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(exception_info, indent=2, default=str),
            encoding="utf-8",
        )
        self.logger.info(f"异常信息已写入临时文件: {path}")
        # 输出相对路径如果文件在当前目录下
        print("加TRACE=1运行脚本以trace出错的函数")

    def _collect_exception_info(self, exc_type, exc_value, exc_traceback) -> Dict[str, Any]:
        """收集完整的异常信息"""
        tb_list = traceback.extract_tb(exc_traceback)
        frame = exc_traceback.tb_frame
        module = inspect.getmodule(frame)

        # 获取模块信息
        module_info = {}
        if module:
            try:
                module_info = {
                    "module_name": module.__name__,
                    "module_path": inspect.getsourcefile(module),
                    "module_loader": str(getattr(module, "__loader__", None)),
                }
            except Exception as e:
                self.logger.warning(f"获取模块信息失败: {str(e)}")

        # 构建调用栈数据
        call_stack = []
        for i, frame in enumerate(tb_list):
            try:
                code_context = frame.line.strip() if frame.line else ""
                call_stack.append(
                    {
                        "filename": frame.filename,
                        "lineno": frame.lineno,
                        "function": frame.name,
                        "code": code_context,
                        "depth": i,
                    }
                )
            except AttributeError:
                continue

        return {
            "exception_type": exc_type.__name__,
            "exception_value": str(exc_value),
            "timestamp": datetime.now().isoformat(),
            "python_path": sys.executable,
            "original_argv": sys.argv.copy(),
            "sys_path": sys.path.copy(),
            "call_stack": call_stack,
            **module_info,
        }
