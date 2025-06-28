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

import yaml

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
    # 将目标脚本所在目录添加到 sys.path
    sys.path.insert(0, os.path.dirname(str(target)))
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
    finally:
        # 恢复 sys.path
        if sys.path[0] == os.path.dirname(str(target)):
            sys.path.pop(0)


def create_parser() -> ArgumentParser:
    """创建命令行参数解析器"""
    epilog = (
        "示例:\n"
        "  python -m debugger.tracer_main script.py\n"
        "  python -m debugger.tracer_main --config my_config.yaml script.py\n"
        "  python -m debugger.tracer_main --watch-files='src/*.py' script.py\n"
        "  python -m debugger.tracer_main --capture-vars='x' --capture-vars='y.z' script.py\n"
        "  python -m debugger.tracer_main --line-ranges='test.py:10-20' script.py\n"
        "  python -m debugger.tracer_main --start-function='main.py:5' script.py arg1 --arg2"
    )
    parser = ArgumentParser(
        description="Python脚本调试跟踪工具",
        usage="python -m debugger.tracer_main [选项] <脚本> [脚本参数]",
        formatter_class=RawDescriptionHelpFormatter,
        epilog=epilog,
        add_help=False,  # We add our own help argument for custom text
    )
    # Redefine help argument to provide custom help text in Chinese
    parser.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    parser.add_argument(
        "--config",
        type=Path,
        help="从YAML文件加载配置",
    )
    parser.add_argument(
        "--watch-files",
        action="append",
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
        help="要捕获的变量表达式(可多次指定)",
    )
    parser.add_argument(
        "--exclude-functions",
        action="append",
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
        help="启用变量操作跟踪 (可能影响性能)",
    )
    parser.add_argument(
        "--disable-html",
        action="store_true",
        help="禁用HTML报告生成",
    )
    parser.add_argument(
        "--report-name",
        type=str,
        help="自定义报告文件名 (例如: my_report.html)",
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="包含系统路径和第三方库的跟踪",
    )
    parser.add_argument(
        "--trace-self",
        action="store_true",
        help="包含跟踪器自身的代码执行 (用于调试跟踪器)",
    )
    parser.add_argument(
        "--start-function",
        type=str,
        help="指定开始跟踪的函数，格式为'文件路径:行号'",
    )
    parser.add_argument(
        "--source-base-dir",
        type=Path,
        help="源代码的根目录，用于在报告中显示相对路径",
    )
    return parser


def parse_cli_args(argv: List[str]) -> Dict[str, Any]:
    """
    解析命令行参数，支持配置文件，并稳健地分离目标脚本及其参数。

    处理顺序:
    1. 查找 --config 参数并加载配置文件作为默认值。
    2. 解析调试器自身的参数。
    3. 将剩余的参数视为目标脚本及其参数。
    """
    parser = create_parser()

    # 早期解析，只为获取配置文件路径
    config_parser = ArgumentParser(add_help=False)
    config_parser.add_argument("--config", type=Path)
    config_args, remaining_argv = config_parser.parse_known_args(argv)

    # 加载配置文件
    config_from_file = {}
    if config_args.config:
        if not config_args.config.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_args.config}")
        with open(config_args.config, "r", encoding="utf-8") as f:
            try:
                config_from_file = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                raise ValueError(f"配置文件解析失败: {e}") from e

    # 将配置文件中的值设置为默认值
    # 命令行参数将覆盖配置文件中的值
    parser.set_defaults(**config_from_file)

    # 解析剩余的参数
    # parse_known_args will exit if -h or --help is present
    args, script_argv = parser.parse_known_args(remaining_argv)

    if not script_argv:
        raise ValueError("未指定目标Python脚本。请在选项后提供脚本路径。")

    target_script = Path(script_argv[0])
    script_args = script_argv[1:]

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
        "target": target_script,
        "watch_files": args.watch_files or [],
        "open_report": args.open_report,
        "verbose": args.verbose,
        "capture_vars": args.capture_vars or [],
        "exclude_functions": args.exclude_functions or [],
        "line_ranges": line_ranges,
        "enable_var_trace": args.enable_var_trace,
        "disable_html": args.disable_html,
        "report_name": args.report_name,
        "ignore_system_paths": not args.include_system,
        "ignore_self": not args.trace_self,
        "start_function": start_function,
        "source_base_dir": args.source_base_dir,
        "script_args": script_args,
    }


def open_trace_report(report_path: Path) -> None:
    """打开指定的跟踪报告HTML文件"""
    if not report_path.exists():
        print(color_wrap(f"❌ 跟踪报告文件 {report_path} 不存在", "error"))
        return

    report_uri = f"file://{report_path.resolve()}"
    try:
        webbrowser.open(report_uri)
    except (OSError, webbrowser.Error) as e:
        print(color_wrap(f"❌ 无法打开跟踪报告: {str(e)}", "error"))


def debug_main(argv: Optional[List[str]] = None) -> int:
    """调试器主入口，可被其他模块调用"""
    if argv is None:
        argv = sys.argv[1:]

    # 如果没有提供任何参数，则显示帮助信息并退出。
    # argparse将在解析时自动处理 -h/--help。
    if not argv:
        create_parser().print_help()
        return 0

    try:
        # parse_cli_args 会在内部调用 create_parser()
        # 如果用户提供了 -h 或 --help，argparse 会自动处理并退出，不会执行到这里。
        args = parse_cli_args(argv)
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
        if args["source_base_dir"]:
            print(color_wrap(f"📝 源码根目录: {args['source_base_dir'].resolve()}", "var"))

        # 创建 TraceConfig 实例
        config = TraceConfig(
            target_files=args["watch_files"] + [f"*{target.stem}.py"],
            capture_vars=args["capture_vars"],
            line_ranges=args["line_ranges"],
            exclude_functions=args["exclude_functions"],
            enable_var_trace=args["enable_var_trace"],
            disable_html=args["disable_html"],
            report_name=args["report_name"],
            ignore_system_paths=args["ignore_system_paths"],
            ignore_self=args["ignore_self"],
            start_function=args["start_function"],
            source_base_dir=args["source_base_dir"],
        )

        log_dir = Path(__file__).parent / "logs"
        report_path = log_dir / config.report_name

        print(color_wrap("\n📝 调试功能:", "line"))
        print(color_wrap("  ✓ 仅追踪目标模块内的代码执行", "call"))
        print(color_wrap(f"  ✓ {'包含' if not config.ignore_system_paths else '跳过'}标准库和第三方库", "call"))
        print(color_wrap(f"  ✓ {'包含' if not config.ignore_self else '跳过'}跟踪器自身的代码", "call"))
        if config.enable_var_trace:
            print(color_wrap("  ✓ 变量变化检测", "var"))
        print(color_wrap("  ✓ 彩色终端输出 (日志文件无颜色)", "return"))
        print(color_wrap(f"\n📂 调试日志路径: {log_dir / 'debug.log'}", "line"))
        print(color_wrap(f"📂 报告文件路径: {report_path}\n", "line"))

        original_argv = sys.argv.copy()
        exit_code = 0
        tracer = None

        try:
            tracer = start_trace(target, config=config)
            execute_script(target, args["script_args"])
        except KeyboardInterrupt:
            print(color_wrap("\n🛑 用户中断调试过程", "error"))
            exit_code = 130
        except Exception as e:
            print(color_wrap(f"❌ 执行错误: {str(e)}", "error"))
            logging.error("执行错误: %s\n%s", str(e), traceback.format_exc())
            exit_code = 3
        finally:
            if tracer:
                tracer.stop()
            sys.argv = original_argv
            print_debug_summary(report_path)
            if args["open_report"] and not config.disable_html:
                open_trace_report(report_path)

        return exit_code
    except (ValueError, FileNotFoundError) as e:
        print(color_wrap(f"❌ 参数错误: {str(e)}", "error"))
        # Show help for value errors like missing script
        if "未指定目标Python脚本" in str(e):
            print("-" * 20)
            create_parser().print_help()
        return 1
    except Exception as e:
        logging.error("调试器崩溃: %s\n%s", str(e), traceback.format_exc())
        print(color_wrap(f"💥 调试器内部错误: {str(e)}", "error"))
        return 4


def print_debug_summary(report_path: Path) -> None:
    """打印调试会话摘要"""
    print(color_wrap("\n调试日志包含以下信息类型：", "line"))
    print(color_wrap("  ↘ CALL     - 函数调用及参数", "call"))
    print(color_wrap("  ↗ RETURN   - 函数返回值及耗时", "return"))
    print(color_wrap("  Δ VARIABLES - 变量创建/修改/删除", "var"))
    print(color_wrap("  ▷ LINE     - 执行的源代码行", "line"))
    print(color_wrap("  ⚠ WARNING  - 异常或限制提示", "error"))
    print(color_wrap("\n调试功能说明:", "line"))
    print(color_wrap(f"{Path(__file__).parent}/logs/debug.log 查看日志", "line"))
    print(color_wrap(f"{report_path} 查看网页报告", "line"))


if __name__ == "__main__":
    sys.exit(debug_main())
