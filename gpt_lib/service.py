import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from tree import GLOBAL_PROJECT_CONFIG, LLM_PROJECT_CONFIG


class SymbolService:
    """符号服务实例管理器

    功能:
    1. 加载项目配置(.llm_project)
    2. 管理tree.py进程(端口分配、PID记录)
    3. 提供符号服务API(http://127.0.0.1:port)
    """

    CONFIG_FILE = LLM_PROJECT_CONFIG
    PID_FILE = ".tree/pid"
    LOG_FILE = ".tree/log"
    RC_FILE = ".tree/rc.sh" if os.name != "nt" else ".tree/rc.ps1"
    DEFAULT_PORT = 9050
    DEFAULT_LSP = "pylsp"

    def __init__(
        self,
        project_root: str = None,
        port: int = None,
        lsp: str = None,
        force_restart: bool = False,
    ):
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.port = port or self._find_available_port()
        self.lsp = lsp or self.DEFAULT_LSP
        self.force_restart = force_restart
        self.tree_dir = self.project_root / ".tree"
        self.pid_file = self.tree_dir / "pid"
        self.log_file = self.tree_dir / "log"
        self.rc_file = self.tree_dir / ("rc.ps1" if os.name == "nt" else "rc.sh")
        self._validate_project_root()

    def _validate_project_root(self):
        """验证项目根目录是否包含配置文件"""
        config_path = self.project_root / self.CONFIG_FILE
        if not config_path.exists():
            GLOBAL_PROJECT_CONFIG.set_config_file_path(config_path)
            GLOBAL_PROJECT_CONFIG.save_config()

    def _find_available_port(self) -> int:
        """查找可用端口"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def _read_pid_file(self) -> Optional[dict]:
        """读取PID文件内容"""
        if not self.pid_file.exists():
            return None
        try:
            with open(self.pid_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _write_pid_file(self, pid: int):
        """写入PID文件"""
        with open(self.pid_file, "w") as f:
            json.dump({"pid": pid, "port": self.port}, f)

    def _write_rc_file(self, api_url: str):
        """写入环境变量配置文件"""
        if os.name == "nt":
            # Windows下使用UTF-8 with BOM编码
            with open(self.rc_file, "w", encoding="utf-8-sig") as f:
                f.write(f'$env:GPT_SYMBOL_API_URL="{api_url}"\n')
        else:
            with open(self.rc_file, "w") as f:
                f.write(f"export GPT_SYMBOL_API_URL={api_url}\n")

    def _kill_existing_process(self, pid: int):
        """终止现有进程"""
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)  # 等待进程退出
            if self._is_process_running(pid):
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # 进程已不存在
        finally:
            self.pid_file.unlink(missing_ok=True)

    def _is_process_running(self, pid: int) -> bool:
        """检查进程是否在运行"""
        if os.name == "nt":  # Windows系统
            psutil = __import__("psutil")
            return psutil.pid_exists(pid)
        else:  # Unix-like系统
            try:
                # 使用/proc文件系统检查
                proc_path = Path(f"/proc/{pid}")
                if proc_path.exists():
                    try:
                        # 检查进程状态
                        status = (proc_path / "status").read_text()
                        return "running" in status.lower()
                    except IOError:
                        return False
                return False
            except Exception:
                # 回退方案
                try:
                    os.kill(pid, 0)
                    return True
                except ProcessLookupError:
                    return False

    def _check_service_ready(self, timeout: int = 10) -> bool:
        """检查服务是否就绪"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return True
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(0.5)
        return False

    def start(self) -> str:
        """启动符号服务

        返回:
            API服务URL (http://127.0.0.1:port)
        """
        # 确保.tree目录存在
        self.tree_dir.mkdir(parents=True, exist_ok=True)

        # 检查现有进程
        pid_info = self._read_pid_file()
        if pid_info:
            if self._is_process_running(pid_info["pid"]):
                if not self.force_restart:
                    return f"http://127.0.0.1:{pid_info['port']}"
                self._kill_existing_process(pid_info["pid"])
            else:
                # 清理无效的pid文件
                self.pid_file.unlink(missing_ok=True)

        python_bin = os.environ.get("GPT_PYTHON_BIN", "python")
        package_path = Path(__file__).parent.parent
        # 启动新进程
        cmd = [
            python_bin,
            str(package_path / "tree.py"),
            "--project",
            str(self.project_root),
            "--port",
            str(self.port),
            "--lsp",
            self.lsp,
        ]

        if os.name == "nt":
            # Windows下不重定向日志，直接显示在终端
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )
            process = subprocess.Popen(
                cmd, creationflags=creationflags, close_fds=True, cwd=str(package_path)
            )
        else:
            # Unix-like系统仍然重定向输出到日志文件
            # preexec_fn=os.setsid,
            with open(self.log_file, "w") as log_file:
                process = subprocess.Popen(
                    cmd,
                    stdout=log_file,
                    stderr=log_file,
                    start_new_session=True,
                    close_fds=True,
                    cwd=str(package_path),
                )

        self._write_pid_file(process.pid)

        if not self._check_service_ready():
            if os.name != "nt":
                # 读取并输出日志内容(仅非Windows系统)
                log_content = ""
                try:
                    with open(self.log_file, "r") as f:
                        log_content = f.read()
                except IOError:
                    log_content = "无法读取日志文件"
                raise RuntimeError(
                    f"符号服务启动失败，端口 {self.port} 不可用\n"
                    f"日志内容:\n{log_content}"
                )
            else:
                raise RuntimeError(f"符号服务启动失败，端口 {self.port} 不可用")

        api_url = f"http://127.0.0.1:{self.port}/"
        self._write_rc_file(api_url)
        return api_url


def start_symbol_service(force=False):
    """
    use config in global object
    GLOBAL_PROJECT_CONFIG
    start symbol service
    """
    if not hasattr(GLOBAL_PROJECT_CONFIG, "project_root_dir"):
        raise ValueError("GLOBAL_PROJECT_CONFIG缺少project_root_dir配置")

    try:
        # 从配置中读取LSP设置，默认为pylsp
        lsp_config = getattr(GLOBAL_PROJECT_CONFIG, "lsp", {})
        default_lsp = (
            lsp_config.get("default", "py") if isinstance(lsp_config, dict) else "py"
        )

        # 尝试从配置中获取symbol_service端口
        port = 0
        if hasattr(GLOBAL_PROJECT_CONFIG, "symbol_service_url"):
            try:
                parsed_url = urlparse(GLOBAL_PROJECT_CONFIG.symbol_service_url)
                if parsed_url.port:
                    port = parsed_url.port
            except (AttributeError, ValueError):
                pass

        service = SymbolService(
            project_root=GLOBAL_PROJECT_CONFIG.project_root_dir,
            port=port,
            lsp=default_lsp,
            force_restart=force,
        )

        # 如果使用了随机端口，更新global config
        if port is None or port != service.port:
            GLOBAL_PROJECT_CONFIG.update_symbol_service_url(
                f"http://127.0.0.1:{service.port}"
            )

        api_url = service.start()
        print(f"符号服务已启动: {api_url}")
        print(f"环境变量已写入: {service.rc_file}")
        print(
            f"使用命令加载环境变量: {'source' if os.name != 'nt' else '.'} {service.rc_file}"
        )
        return api_url
    except Exception as e:
        print(f"启动符号服务失败: {str(e)}")
        raise
