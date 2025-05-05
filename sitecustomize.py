from logging import error
from gpt_workflow import auto_exception
from gpt_workflow.auto_exception import ExceptionHandler
from pathlib import Path
import json
import atexit
import os
import sys
from colorama import init, Fore, Style


def install_auto_exception():
    """全局安装异常处理器"""
    handler = ExceptionHandler()
    handler.install()


def print_trace_banner():
    """打印TRACE模式的启动横幅"""
    init(autoreset=True)
    banner = f"""
{Fore.GREEN}╔════════════════════════════════════════════════════════════╗
{Fore.GREEN}║{Fore.YELLOW}                    TRACE MODE ACTIVATED                    {Fore.GREEN}║
{Fore.GREEN}╚════════════════════════════════════════════════════════════╝
{Style.RESET_ALL}
{Fore.CYAN}• Tracing exception from:{Style.RESET_ALL} {Fore.WHITE}{exception["call_stack"][0]["filename"]}{Style.RESET_ALL}
{Fore.CYAN}• Line number:{Style.RESET_ALL} {Fore.WHITE}{exception["call_stack"][-1]["lineno"]}{Style.RESET_ALL}
{Fore.CYAN}• Function:{Style.RESET_ALL} {Fore.WHITE}{exception["call_stack"][0]["function"]}{Style.RESET_ALL}
{Fore.CYAN}• Exception type:{Style.RESET_ALL} {Fore.RED}{exception["exception_type"]}{Style.RESET_ALL}
"""
    print(banner, file=sys.stderr)


TRACE = os.environ.get("TRACE", "")

if TRACE:
    path = Path(__file__).parent / "gpt_workflow/auto_exception/logs/auto_exception.json"
    if path.exists():
        exception_str = path.read_text()
        exception = json.loads(exception_str)
        print_trace_banner()
        error_frame = exception["call_stack"][-1]
        filename = error_frame["filename"]
        lineno = error_frame["lineno"]
        function = error_frame["function"]
        from debugger.tracer import start_trace, TraceConfig

        g = {"t": None}

        def close(*args):
            g["t"].stop()
            print(
                f"\n{Fore.GREEN}✓ Trace report saved to: {Fore.WHITE}{t.config.report_name}{Style.RESET_ALL}",
                file=sys.stderr,
            )

        atexit.register(close)
        t = start_trace(
            TraceConfig(
                target_files=["*.py"],
                ignore_system_paths=False,
                ignore_self=True,
                start_function=(filename, lineno),
                report_name=f"auto_exception_{function}.html",
            )
        )
        g["t"] = t
else:
    install_auto_exception()
