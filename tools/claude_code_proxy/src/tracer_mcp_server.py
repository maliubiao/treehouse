#!/usr/bin/env python3
"""
A MCP server that provides Python code tracing capabilities.
This server implements the Model Context Protocol over stdio and exposes
a tracer tool that can execute Python scripts/modules with full tracing.
"""

import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("tracer_mcp_server.log"), logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Add parent directory to path for tracer imports
sys.path.insert(0, str(Path(__file__).parent.parent))


import shutil
from typing import Any, Dict, List, Optional, Tuple


class TracerMCPServer:
    """MCP server implementation with tracing capabilities."""

    def __init__(self) -> None:
        self.server_info = {"name": "tracer-mcp-server", "version": "2.0.0"}
        self.tools = [
            {
                "name": "trace_python",
                "description": "Execute and trace Python scripts or modules with detailed execution analysis",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "目标脚本路径或模块名称。例如：'src/main.py' 或 'my_package.module'",
                        },
                        "target_type": {
                            "type": "string",
                            "enum": ["script", "module"],
                            "description": "目标类型：'script' 表示脚本文件，'module' 表示Python模块",
                        },
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "传递给目标脚本/模块的参数列表。例如：['--verbose', 'input.txt']",
                        },
                        "watch_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要监控的文件模式列表，支持通配符。例如：['src/*.py', 'tests/**/*.py']",
                        },
                        "exclude_functions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要排除跟踪的函数名称列表。例如：['print', 'logging.debug']",
                        },
                        "line_ranges": {
                            "type": "string",
                            "description": "指定要跟踪的行号范围，格式为'文件路径:起始行-结束行'，多个范围用逗号分隔。例如：'main.py:10-50,utils.py:5-20'",
                        },
                        "enable_var_trace": {
                            "type": "boolean",
                            "description": "启用详细的变量变化跟踪（可能影响性能）",
                        },
                        "report_name": {
                            "type": "string",
                            "description": "自定义报告文件名，默认为'trace_report'。例如：'my_analysis' 将生成 my_analysis.log",
                            "default": "trace_report",
                        },
                        "include_system": {
                            "type": "boolean",
                            "description": "是否包含系统路径和第三方库的跟踪，默认为false",
                        },
                        "include_stdlibs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "即使忽略系统路径，也强制跟踪指定的标准库模块。例如：['json', 're', 'os.path']",
                        },
                        "timeout": {"type": "number", "description": "最大执行时间（秒），超时将终止跟踪，默认为30秒"},
                    },
                    "required": ["target", "target_type"],
                },
            },
            {
                "name": "import_path_finder",
                "description": "分析当前目录和父目录的文件结构，帮助确定Python import语句的写法",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_patterns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要包含的文件模式列表，支持通配符。例如：['*.py', '*.pyi']，默认包含所有Python文件",
                            "default": ["*.py", "*.pyi"],
                        },
                        "exclude_patterns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要排除的文件模式列表，支持通配符。例如：['__pycache__/*', '*.pyc']",
                            "default": ["__pycache__/*", "*.pyc", "*.pyo", ".git/*", ".pytest_cache/*"],
                        },
                        "max_depth": {"type": "number", "description": "扫描的最大目录深度，默认为3层", "default": 3},
                    },
                    "required": [],
                },
            },
        ]

    def handle_initialize(self, _params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialize request."""
        logger.info("MCP server initialized")
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": self.server_info}

    def handle_tools_list(self) -> Dict[str, List[Dict[str, Any]]]:
        """Handle tools/list request."""
        logger.info("Listing available tools")
        return {"tools": self.tools}

    def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        tool_params = params.get("arguments", {})

        if tool_name == "trace_python":
            return self._handle_trace_python(tool_params)
        elif tool_name == "import_path_finder":
            return self._handle_import_path_finder(tool_params)

        raise ValueError(f"Unknown tool: {tool_name}")

    def _validate_script_target(self, target: str) -> None:
        """Validate that target is an existing .py file."""
        path = Path(target)
        if not path.exists():
            raise ValueError(f"Script file does not exist: {target}")
        if not path.is_file():
            raise ValueError(f"Script path is not a file: {target}")
        if path.suffix != ".py":
            raise ValueError(f"Script file must have .py extension: {target}")

    def _validate_module_target(self, target: str) -> None:
        """Validate that target is an importable module name."""
        spec = importlib.util.find_spec(target)
        if spec is None:
            raise ValueError(f"Module not found: {target}")

    def _extract_log_path_from_stdout(self, stdout: str) -> Optional[str]:
        """从stdout中提取日志文件路径"""
        # 匹配格式：📂 报告文件路径: /path/to/trace_report.log
        pattern = r"📂 报告文件路径:\s*([^\n]+)"
        match = re.search(pattern, stdout)
        if match:
            return match.group(1).strip()
        return None

    def _read_log_content(self, log_path: str) -> str:
        """读取日志文件内容"""
        try:
            path = Path(log_path)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            else:
                return f"日志文件不存在: {log_path}"
        except OSError as e:
            return f"读取日志文件失败: {str(e)}"

    def _build_tracer_command_args(self, params: Dict[str, Any], target: str, target_type: str) -> List[str]:
        """Builds the command line arguments for the tracer process."""
        argv = []

        if params.get("watch_files"):
            for pattern in params["watch_files"]:
                argv.extend(["--watch-files", pattern])

        if params.get("exclude_functions"):
            for func in params["exclude_functions"]:
                argv.extend(["--exclude-functions", func])

        if params.get("line_ranges"):
            argv.extend(["--line-ranges", params["line_ranges"]])

        if params.get("enable_var_trace"):
            argv.append("--enable-var-trace")

        # Always disable HTML report
        argv.append("--disable-html")

        report_name = params.get("report_name", "trace_report")
        argv.extend(["--report-name", report_name])

        if params.get("include_system"):
            argv.append("--include-system")

        if params.get("include_stdlibs"):
            for lib in params["include_stdlibs"]:
                argv.extend(["--include-stdlibs", lib])

        if target_type == "module":
            argv.extend(["-m", target])
        else:
            argv.append(target)

        argv.extend(params.get("args", []))
        return [sys.executable, "-m", "debugger.tracer_main"] + argv

    def _execute_tracer_process(self, command_args: List[str], cwd: str, timeout: int) -> Tuple[int, str, str, bool]:
        """Executes the tracer process and handles timeouts.
        Returns (exit_code, stdout, stderr, killed_by_timeout).
        """
        old_cwd = os.getcwd()
        os.chdir(cwd)
        stdout, stderr = "", ""
        exit_code = -1
        killed = False

        try:
            logger.info("Starting trace with timeout %ss", timeout)

            result = subprocess.run(
                command_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                timeout=timeout,
                check=False,  # Do not raise CalledProcessError for non-zero exit codes
            )
            stdout = result.stdout
            stderr = result.stderr
            exit_code = result.returncode
            killed = False
        except subprocess.TimeoutExpired as e:
            logger.warning("Trace timed out after %ss", timeout)
            stdout = e.stdout if e.stdout else ""  # Capture any output before timeout
            stderr = e.stderr if e.stderr else ""
            exit_code = -1  # Indicate timeout by -1 exit code
            killed = True
        except OSError as e:
            logger.error("Failed to execute tracer process: %s", e)
            stderr = f"Failed to execute tracer process: {e}"
            exit_code = -1
            killed = False
        finally:
            os.chdir(old_cwd)
        return exit_code, stdout, stderr, killed

    def _cleanup_temp_dir(self, temp_dir: str) -> None:
        """Cleans up the temporary directory."""
        # C0415: import shutil was moved to the top of the file as per Pylint recommendation.
        try:
            shutil.rmtree(temp_dir)
        except OSError as e:
            logger.warning("Failed to clean up temp directory %s: %s", temp_dir, e)

    def _compose_trace_result_text(
        self, exit_code: int, killed: bool, stdout: str, stderr: str, trace_log_content: str
    ) -> str:
        """Composes the final result text for the trace."""
        result_text = "Trace completed\n"
        result_text += f"Exit code: {exit_code}\n"
        if killed:
            result_text += "Process was killed due to timeout\n"

        if stdout:
            result_text += f"STDOUT:\n{stdout}\n"
        if stderr:
            result_text += f"STDERR:\n{stderr}\n"
        if trace_log_content:
            result_text += f"TRACE LOG:\n{trace_log_content}\n"
        return result_text

    def _scan_directory(
        self,
        directory: Path,
        include_patterns: List[str],
        exclude_patterns: List[str],
        max_depth: int,
        current_depth: int = 0,
    ) -> Dict[str, Any]:
        """扫描目录并返回文件结构"""
        if current_depth >= max_depth:
            return {}

        result = {"path": str(directory), "files": [], "subdirectories": {}}

        try:
            for item in directory.iterdir():
                if item.is_file():
                    # 检查是否匹配包含模式
                    include_file = False
                    for pattern in include_patterns:
                        if item.match(pattern):
                            include_file = True
                            break

                    # 检查是否匹配排除模式
                    exclude_file = False
                    for pattern in exclude_patterns:
                        if item.match(pattern):
                            exclude_file = True
                            break

                    if include_file and not exclude_file:
                        result["files"].append(
                            {
                                "name": item.name,
                                "path": str(item.relative_to(directory)),
                                "full_path": str(item.absolute()),
                            }
                        )

                elif item.is_dir() and not any(item.match(pattern) for pattern in exclude_patterns):
                    subdir_result = self._scan_directory(
                        item, include_patterns, exclude_patterns, max_depth, current_depth + 1
                    )
                    if subdir_result:
                        result["subdirectories"][item.name] = subdir_result

        except PermissionError:
            logger.warning(f"Permission denied accessing directory: {directory}")

        return result

    def _handle_import_path_finder(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理import_path_finder工具调用"""
        try:
            # 获取参数
            include_patterns = params.get("include_patterns", ["*.py", "*.pyi"])
            exclude_patterns = params.get(
                "exclude_patterns", ["__pycache__/*", "*.pyc", "*.pyo", ".git/*", ".pytest_cache/*"]
            )
            max_depth = params.get("max_depth", 3)

            # 获取当前目录和父目录
            current_dir = Path.cwd()
            parent_dir = current_dir.parent

            # 扫描当前目录
            current_structure = self._scan_directory(current_dir, include_patterns, exclude_patterns, max_depth)

            # 扫描父目录
            parent_structure = self._scan_directory(parent_dir, include_patterns, exclude_patterns, max_depth)

            # 构建结果
            result = {
                "current_directory": {
                    "path": str(current_dir),
                    "name": current_dir.name,
                    "structure": current_structure,
                },
                "parent_directory": {"path": str(parent_dir), "name": parent_dir.name, "structure": parent_structure},
                "import_suggestions": self._generate_import_suggestions(
                    current_dir, parent_dir, current_structure, parent_structure
                ),
            }

            return {"content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]}

        except Exception as e:
            logger.error("Error in import_path_finder: %s", e)
            return {"content": [{"type": "text", "text": f"Error analyzing directory structure: {str(e)}"}]}

    def _generate_import_suggestions(
        self, current_dir: Path, parent_dir: Path, current_structure: Dict, parent_structure: Dict
    ) -> List[str]:
        """生成import语句建议"""
        suggestions = []

        # 检查当前目录下的Python文件
        has_init = any(f["name"] == "__init__.py" for f in current_structure.get("files", []))
        if current_structure.get("files"):
            for file_info in current_structure["files"]:
                if file_info["name"].endswith(".py") and file_info["name"] != "__init__.py":
                    module_name = file_info["name"][:-3]  # 去掉.py
                    if not has_init:
                        suggestions.append(f"import {module_name}")

        # 检查父目录下的Python包
        if parent_structure.get("subdirectories"):
            for dir_name, dir_info in parent_structure["subdirectories"].items():
                if dir_info.get("files"):
                    # 检查是否有__init__.py来判断是否是Python包
                    has_init = any(f["name"] == "__init__.py" for f in dir_info.get("files", []))
                    if has_init:
                        suggestions.append(f"import {dir_name}")
                        # 检查包内的模块
                        for file_info in dir_info.get("files", []):
                            if file_info["name"].endswith(".py") and file_info["name"] != "__init__.py":
                                module_name = file_info["name"][:-3]
                                suggestions.append(f"from {dir_name} import {module_name}")

        # 去重并保持顺序
        seen = set()
        unique_suggestions = []
        for suggestion in suggestions:
            if suggestion not in seen:
                seen.add(suggestion)
                unique_suggestions.append(suggestion)

        return unique_suggestions

    def _handle_trace_python(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle trace_python tool synchronously."""
        try:
            # Validate parameters
            target = params.get("target")
            target_type = params.get("target_type")

            if not target or not target_type:
                raise ValueError("target and target_type are required")

            # Strict validation based on target_type
            if target_type == "script":
                self._validate_script_target(target)
            elif target_type == "module":
                self._validate_module_target(target)
            else:
                raise ValueError("target_type must be either 'script' or 'module'")

            timeout = params.get("timeout", 30)

            # Create temporary directory for this trace
            temp_dir = tempfile.mkdtemp(prefix="trace_")

            try:
                # Build command line arguments for tracer
                command_args = self._build_tracer_command_args(params, target, target_type)

                # Run tracer process with timeout
                exit_code, stdout, stderr, killed = self._execute_tracer_process(command_args, temp_dir, timeout)

                # Extract log path from stdout
                log_path = self._extract_log_path_from_stdout(stdout)
                trace_log_content = self._read_log_content(log_path) if log_path else ""
                if log_path:
                    logger.info("Extracted trace log from: %s", log_path)
                else:
                    logger.warning("Could not extract trace log path from stdout")

                # Prepare response
                result_text = self._compose_trace_result_text(exit_code, killed, stdout, stderr, trace_log_content)
                return {"content": [{"type": "text", "text": result_text}]}

            finally:
                self._cleanup_temp_dir(temp_dir)

        except ValueError as e:  # Specific catch for validation errors
            logger.error("Trace validation error: %s", e)
            return {"content": [{"type": "text", "text": f"Error during trace validation: {str(e)}"}]}
        # Catch specific execution errors
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("Error during trace execution: %s", e)
            return {"content": [{"type": "text", "text": f"Error during trace execution: {str(e)}"}]}
        # Catching common unexpected errors to ensure a response is always returned.
        except (
            TypeError,
            AttributeError,
            RuntimeError,
        ) as e:
            logger.error("Unexpected error during trace handling: %s", e)
            return {"content": [{"type": "text", "text": f"An unexpected error occurred: {str(e)}"}]}

    def run(self) -> None:
        """Run the MCP server over stdio synchronously."""
        logger.info("Starting tracer MCP server...")

        try:
            while True:
                line = sys.stdin.readline()

                if not line:
                    break

                try:
                    message = json.loads(line.strip())
                    request_id = message.get("id")
                    method = message.get("method")
                    params = message.get("params", {})

                    logger.debug("Received request: %s", method)

                    if method == "initialize":
                        result = self.handle_initialize(params)
                    elif method == "tools/list":
                        result = self.handle_tools_list()
                    elif method == "tools/call":
                        result = self.handle_tools_call(params)
                    else:
                        result = {"error": f"Unknown method: {method}"}

                    response = {"jsonrpc": "2.0", "id": request_id, "result": result}

                    print(json.dumps(response), flush=True)

                # Catching specific application errors for server robustness per request.
                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    AttributeError,
                    OSError,
                    subprocess.SubprocessError,
                ) as e:
                    logger.error("Error handling request: %s", e)
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id if "request_id" in locals() else None,
                        "error": {"code": -32603, "message": str(e)},
                    }
                    print(json.dumps(error_response), flush=True)

        except KeyboardInterrupt:
            logger.info("Server shutting down...")
        # Catching specific system-level errors for top-level server robustness and graceful handling.
        except (
            RuntimeError,
            SystemError,
            OSError,
        ) as e:
            logger.error("Server error: %s", e)


def main() -> None:
    """Main entry point."""
    server = TracerMCPServer()
    server.run()


if __name__ == "__main__":
    main()
