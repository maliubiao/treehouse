import atexit
import json
import os
import sys
from pathlib import Path


def install_auto_exception():
    """全局安装异常处理器"""
    from gpt_workflow.auto_exception import ExceptionHandler

    handler = ExceptionHandler()
    handler.install()


def print_trace_banner(error_frame, exception_data):
    """打印TRACE模式的启动横幅"""
    init(autoreset=True)
    banner = f"""
{Fore.GREEN}╔════════════════════════════════════════════════════════════╗
{Fore.GREEN}║{Fore.YELLOW}                    TRACE MODE ACTIVATED                    {Fore.GREEN}║
{Fore.GREEN}╚════════════════════════════════════════════════════════════╝
{Style.RESET_ALL}
{Fore.CYAN}• Tracing exception from:{Style.RESET_ALL} {Fore.WHITE}{error_frame["filename"]}{Style.RESET_ALL}
{Fore.CYAN}• Line number:{Style.RESET_ALL} {Fore.WHITE}{error_frame["lineno"]}{Style.RESET_ALL}
{Fore.CYAN}• Function:{Style.RESET_ALL} {Fore.WHITE}{error_frame["function"]}{Style.RESET_ALL}
{Fore.CYAN}• Exception type:{Style.RESET_ALL} {Fore.RED}{exception_data["exception_type"]}{Style.RESET_ALL}
"""
    print(banner, file=sys.stderr)


TRACE = os.environ.get("TRACE", "")

if TRACE:
    from debugger.tracer import TraceConfig, start_trace
    from colorama import Fore, Style, init

    path = Path(__file__).parent / "gpt_workflow/auto_exception/logs/auto_exception.json"
    if path.exists():
        exception_str = path.read_text()
        exception = json.loads(exception_str)

        config = TraceConfig(
            target_files=["*.py"],
            ignore_system_paths=True,
            ignore_self=True,
            report_name="auto_exception.html",
        )
        ERROR_FRAME = None
        for v in reversed(exception["call_stack"]):
            if config.match_filename(v["filename"]):
                print("trace last frame match tracer config: ", v["function"])
                ERROR_FRAME = v
                break
        if ERROR_FRAME:
            print_trace_banner(ERROR_FRAME, exception)
            filename = ERROR_FRAME["filename"]
            lineno = ERROR_FRAME["lineno"]
            function = ERROR_FRAME["function"]

            start_function = ((filename, lineno),)
            config.start_function = start_function

            TRACER = None

            def close():
                TRACER.stop()
                print(
                    f"\n{Fore.GREEN}✓ Trace report saved to: {Fore.WHITE}{TRACER.config.report_name}{Style.RESET_ALL}",
                    file=sys.stderr,
                )

            atexit.register(close)
            TRACER = start_trace(config)
else:
    try:
        install_auto_exception()
    except Exception:
        pass
