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
    """解析命令行参数并返回配置字典"""
    parser = ArgumentParser(description="Python调试跟踪工具")
    parser.add_argument("target", type=Path, help="要调试的Python脚本路径")
    parser.add_argument(
        "--watch-files",
        action="append",
        default=[],
        help="监控匹配的文件模式(支持通配符，可多次指定)",
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
    parser.add_argument(
        "--capture-vars",
        action="append",
        default=[],
        help="要捕获的变量表达式(可多次指定)",
    )
    parser.add_argument(
        "--exclude-functions",
        action="append",
        default=[],
        help="要排除的函数名(可多次指定)",
    )
    parser.add_argument(
        "--line-ranges",
        type=str,
        help="要跟踪的行号范围，格式为'文件路径:起始行-结束行'，多个范围用逗号分隔",
    )
    parser.add_argument(
        "--enable-var-trace",
        action="store_true",
        help="启用变量操作跟踪",
    )
    parser.add_argument(
        "--disable-html",
        action="store_true",
        help="禁用HTML报告生成",
    )
    parser.add_argument(
        "--report-name",
        type=str,
        help="自定义报告文件名(不含扩展名)",
        default="trace_report.html",
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="包含系统路径和第三方库的跟踪",
    )
    parser.add_argument(
        "--start-function",
        type=str,
        help="指定开始跟踪的函数，格式为'文件名:行号'",
    )
    parser.add_argument(
        "script_args",
        nargs="*",
        help="传递给目标脚本的参数",
    )

    split_index = 0
    for i, arg in enumerate(argv):
        if arg.endswith(".py") and Path(arg).exists():
            split_index = i
            break

    if split_index == 0 and not argv:
        return parser.parse_args([])

    args = parser.parse_args(argv[: split_index + 1])

    # 解析行号范围
    line_ranges = {}
    if args.line_ranges:
        for range_str in args.line_ranges.split(","):
            file_path, ranges = range_str.split(":")
            start, end = map(int, ranges.split("-"))
            if file_path not in line_ranges:
                line_ranges[file_path] = []
            line_ranges[file_path].append((start, end))

    # 解析起始函数
    start_function = None
    if args.start_function:
        filename, lineno = args.start_function.split(":")
        start_function = (filename, int(lineno))

    return {
        "target": args.target,
        "watch_files": args.watch_files,
        "open_report": args.open_report,
        "verbose": args.verbose,
        "capture_vars": args.capture_vars,
        "exclude_functions": args.exclude_functions,
        "line_ranges": line_ranges,
        "enable_var_trace": args.enable_var_trace,
        "disable_html": args.disable_html,
        "report_name": args.report_name,
        "ignore_system_paths": not args.include_system,
        "start_function": start_function,
        "script_args": argv[split_index + 1 :],
    }


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
    except (OSError, webbrowser.Error) as e:
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
                    "  --capture-vars=EXPR     要捕获的变量表达式(可多次指定)\n"
                    "  --exclude-functions=NAME 要排除的函数名(可多次指定)\n"
                    "  --line-ranges=FILE:START-END 要跟踪的行号范围(可逗号分隔多个)\n"
                    "  --enable-var-trace      启用变量操作跟踪\n"
                    "  --disable-html         禁用HTML报告生成\n"
                    "  --report-name=NAME     自定义报告文件名(不含扩展名)\n"
                    "  --include-system       包含系统路径和第三方库的跟踪\n"
                    "  --start-function=FILE:LINE 指定开始跟踪的函数\n"
                    "  --open-report          调试完成后自动打开HTML报告\n"
                    "  --verbose              显示详细调试信息\n\n"
                    "示例:\n"
                    "  python -m debugger.tracer_main script.py\n"
                    "  python -m debugger.tracer_main --watch-files='src/*.py' script.py\n"
                    "  python -m debugger.tracer_main --capture-vars='x' --capture-vars='y.z' script.py\n"
                    "  python -m debugger.tracer_main --line-ranges='test.py:10-20,test.py:30-40' script.py\n"
                    "  python -m debugger.tracer_main --start-function='main.py:5' script.py\n",
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
        if args["capture_vars"]:
            print(color_wrap(f"📝 捕获变量: {', '.join(args['capture_vars'])}", "var"))
        if args["exclude_functions"]:
            print(color_wrap(f"📝 排除函数: {', '.join(args['exclude_functions'])}", "var"))
        if args["line_ranges"]:
            print(color_wrap(f"📝 行号范围: {args['line_ranges']}", "var"))
        if args["start_function"]:
            print(color_wrap(f"📝 起始函数: {args['start_function'][0]}:{args['start_function'][1]}", "var"))

        print(color_wrap("\n📝 调试功能:", "line"))
        print(color_wrap("  ✓ 仅追踪目标模块内的代码执行", "call"))
        print(color_wrap(f"  ✓ {'包含' if not args['ignore_system_paths'] else '跳过'}标准库和第三方库", "call"))
        print(color_wrap("  ✓ 变量变化检测", "var") if args["enable_var_trace"] else None)
        print(color_wrap("  ✓ 彩色终端输出 (日志文件无颜色)", "return"))
        print(color_wrap(f"\n📂 调试日志路径: {Path(__file__).parent / 'logs/debug.log'}", "line"))
        report_name = args.get("report_name", "trace_report") + ".html"
        print(
            color_wrap(
                f"📂 报告文件路径: {Path(__file__).parent / 'logs' / report_name}\n",
                "line",
            )
        )

        original_argv = sys.argv.copy()
        exit_code = 0

        tracer = None
        try:
            # 创建匹配当前调试目标的TraceConfig
            target_patterns = args["watch_files"] + [f"*{target.stem}.py"]
            config = TraceConfig(
                target_files=target_patterns,
                capture_vars=args["capture_vars"],
                line_ranges=args["line_ranges"],
                exclude_functions=args["exclude_functions"],
                enable_var_trace=args["enable_var_trace"],
                disable_html=args["disable_html"],
                report_name=args.get("report_name", "trace_report.html"),
                ignore_system_paths=args["ignore_system_paths"],
                start_function=args["start_function"],
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
