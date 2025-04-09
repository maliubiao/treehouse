#!/usr/bin/env python3
import logging
import os
import sys
import traceback
import webbrowser
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from debugger.tracer import TraceConfig, color_wrap, start_trace


def execute_script(target: Path, args: List[str]) -> None:
    """执行目标脚本并保持正确的模块上下文"""
    sys.argv = [str(target)] + args
    code = target.read_text(encoding="utf-8")

    # 创建模拟的__main__模块
    main_module = ModuleType("__main__")
    main_module.__file__ = str(target)
    main_module.__name__ = "__main__"
    main_module.__package__ = None
    sys.modules["__main__"] = main_module

    # 准备执行环境
    globals_dict = main_module.__dict__
    globals_dict.update({"__name__": "__main__", "__file__": str(target), "__package__": None})
    sys.path.append(os.path.dirname(str(target)))
    try:
        compiled_code = compile(code, str(target), "exec")
        # 使用更安全的执行方式
        exec(compiled_code, globals_dict)  # pylint: disable=exec-used
    except SystemExit as sys_exit:
        if sys_exit.code != 0:
            print(color_wrap(f"⚠ 脚本以退出码 {sys_exit.code} 终止", "error"))
    except Exception:
        traceback.print_exc()
        raise


def parse_args(argv: List[str]) -> Dict[str, Any]:
    """解析命令行参数"""
    parser = ArgumentParser(
        prog="python -m debugger.tracer_main",
        description="Python脚本调试跟踪工具",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""示例:
  # 基本用法
  python -m debugger.tracer_main script.py
  
  # 监控特定文件模式
  python -m debugger.tracer_main --watch-files='src/*.py' --watch-files='tests/*.py' script.py
  
  # 自动打开报告
  python -m debugger.tracer_main --open-report script.py
  
  # 传递脚本参数
  python -m debugger.tracer_main script.py --script-arg1 --script-arg2
""",
    )
    parser.add_argument(
        "target",
        type=Path,
        help="要调试的Python脚本路径",
    )
    parser.add_argument(
        "script_args",
        nargs="*",
        help="传递给目标脚本的参数",
    )
    parser.add_argument(
        "--watch-files",
        action="append",
        default=[],
        help="要监控的文件模式(支持通配符), 可多次指定",
    )
    parser.add_argument(
        "--open-report",
        action="store_true",
        help="调试完成后自动打开HTML报告",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示详细调试信息",
    )

    # 找到第一个存在的.py文件作为分界点
    split_index = 0
    for i, arg in enumerate(argv):
        if arg.endswith(".py") and Path(arg).exists():
            split_index = i
            break

    if split_index == 0 and not argv:
        return parser.parse_args([])

    try:
        args = parser.parse_args(argv[: split_index + 1])
        # 将剩余参数作为脚本参数
        args.script_args = argv[split_index + 1 :]
        return {
            "target": args.target,
            "script_args": args.script_args,
            "watch_files": args.watch_files,
            "open_report": args.open_report,
            "verbose": args.verbose,
        }
    except SystemExit:
        print(color_wrap("\n错误: 参数解析失败, 请检查输入参数", "error"))
        raise


def open_trace_report() -> None:
    """打开跟踪报告HTML文件"""
    report_path = Path(__file__).parent / "logs" / "trace_report.html"
    if not report_path.exists():
        print(color_wrap(f"❌ 跟踪报告文件 {report_path} 不存在", "error"))
        return

    try:
        if sys.platform == "win32":
            os.startfile(report_path)
        elif sys.platform == "darwin":
            webbrowser.open(f"file://{report_path}")
        else:
            webbrowser.open(f"file://{report_path}")
    except Exception as e:
        print(color_wrap(f"❌ 无法打开跟踪报告: {str(e)}", "error"))


def debug_main(argv: Optional[List[str]] = None) -> int:
    """调试器主入口，可被其他模块调用"""
    try:
        if argv is None:
            argv = sys.argv[1:]

        if not argv:
            print(
                color_wrap(
                    "Python脚本调试跟踪工具\n\n"
                    "用法: python -m debugger.tracer_main [选项] <脚本> [脚本参数]\n\n"
                    "选项:\n"
                    "  --watch-files=PATTERN   监控匹配的文件模式(可多次指定)\n"
                    "  --open-report          调试完成后自动打开HTML报告\n"
                    "  --verbose              显示详细调试信息\n\n"
                    "示例:\n"
                    "  python -m debugger.tracer_main script.py\n"
                    "  python -m debugger.tracer_main --watch-files='src/*.py' script.py\n"
                    "  python -m debugger.tracer_main --open-report script.py\n",
                    "call",
                )
            )
            return 1

        args = parse_args(argv)
        target = args["target"].resolve()
        if not target.exists():
            print(color_wrap(f"❌ 目标文件 {target} 不存在", "error"))
            return 2
        if target.suffix != ".py":
            print(color_wrap(f"❌ 目标文件 {target} 不是Python脚本(.py)", "error"))
            return 2

        print(color_wrap(f"\n🔍 启动调试会话 - 目标: {target}", "call"))
        if args["watch_files"]:
            print(color_wrap(f"📝 监控文件模式: {', '.join(args['watch_files'])}", "var"))

        print(color_wrap("\n📝 调试功能:", "line"))
        print(color_wrap("  ✓ 仅追踪目标模块内的代码执行", "call"))
        print(color_wrap("  ✓ 自动跳过标准库和第三方库", "call"))
        print(color_wrap("  ✓ 变量变化检测", "var"))
        print(color_wrap("  ✓ 彩色终端输出 (日志文件无颜色)", "return"))
        print(color_wrap(f"\n📂 调试日志路径: {Path(__file__).parent/'logs/debug.log'}", "line"))
        print(color_wrap(f"📂 报告文件路径: {Path(__file__).parent/'logs/trace_report.html'}\n", "line"))

        original_argv = sys.argv.copy()
        exit_code = 0

        tracer = None
        try:
            # 创建匹配当前调试目标的TraceConfig
            target_patterns = args["watch_files"] + [f"*{target.stem}.py"]
            config = TraceConfig(
                target_files=target_patterns,
                capture_vars=[],
            )
            tracer = start_trace(target, config=config)
            execute_script(target, args["script_args"])
        except KeyboardInterrupt:
            print(color_wrap("\n🛑 用户中断调试过程", "error"))
            exit_code = 130
        except (SystemExit, RuntimeError) as e:
            print(color_wrap(f"❌ 执行错误: {str(e)}", "error"))
            logging.error("执行错误: %s\n%s", str(e), traceback.format_exc())
            exit_code = 3
        finally:
            if tracer:
                tracer.stop()
            sys.argv = original_argv
            print_debug_summary()
            if args["open_report"]:
                open_trace_report()

        return exit_code
    except (SystemExit, RuntimeError) as e:
        logging.error("调试器崩溃: %s\n%s", str(e), traceback.format_exc())
        print(color_wrap(f"💥 调试器内部错误: {str(e)}", "error"))
        return 4


def print_debug_summary() -> None:
    """打印调试会话摘要"""
    print(color_wrap("\n调试日志包含以下信息类型：", "line"))
    print(color_wrap("  ↘ CALL     - 函数调用及参数", "call"))
    print(color_wrap("  ↗ RETURN   - 函数返回值及耗时", "return"))
    print(color_wrap("  Δ VARIABLES - 变量创建/修改/删除", "var"))
    print(color_wrap("  ▷ LINE     - 执行的源代码行", "line"))
    print(color_wrap("  ⚠ WARNING  - 异常或限制提示", "error"))
    print(color_wrap("\n调试功能说明:", "line"))
    print(color_wrap(f"{Path(__file__).parent}/logs/debug.log 查看日志", "line"))
    print(color_wrap(f"{Path(__file__).parent}/logs/trace_report.html 查看网页报告", "line"))


if __name__ == "__main__":
    sys.exit(debug_main())
