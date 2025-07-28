#!/usr/bin/env python3
import importlib.util
import logging
import os
import runpy
import sys
import traceback
import webbrowser
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from debugger.tracer import TraceConfig, color_wrap, start_trace, stop_trace


def execute_target(target_script: Optional[Path], target_module: Optional[str], args: List[str]) -> None:
    """
    使用runpy执行目标脚本或模块，以确保正确的执行上下文。

    Args:
        target_script: 要执行的脚本的路径。
        target_module: 要执行的模块的名称。
        args: 传递给目标脚本或模块的参数列表。
    """
    try:
        if target_script:
            # 对于run_path，我们必须手动设置sys.argv
            sys.argv = [str(target_script)] + args
            runpy.run_path(str(target_script), run_name="__main__")
        elif target_module:
            # run_module如果alter_sys为True，则会处理sys.argv，
            # 但为了一致性，我们提前设置它。程序的'name' (argv[0])是模块文件的路径。
            spec = importlib.util.find_spec(target_module)
            if spec is None or spec.origin is None:
                raise ImportError(f"无法找到模块: {target_module}")
            sys.argv = [spec.origin] + args
            # alter_sys=True 还会处理 sys.modules['__main__']
            runpy.run_module(target_module, run_name="__main__", alter_sys=True)
        else:
            # 从debug_main的逻辑来看，不应到达此分支
            raise ValueError("未提供执行目标（脚本或模块）")

    except SystemExit as sys_exit:
        if sys_exit.code is not None and sys_exit.code != 0:
            print(color_wrap(f"⚠ 目标以退出码 {sys_exit.code} 终止", "error"))
    except (Exception, ImportError):
        traceback.print_exc()
        raise


def create_parser() -> ArgumentParser:
    """创建命令行参数解析器"""
    epilog = (
        "示例:\n"
        "  # 跟踪脚本\n"
        "  python -m debugger.tracer_main script.py arg1\n\n"
        "  # 跟踪模块 (注意用 -- 分隔模块参数)\n"
        "  python -m debugger.tracer_main -m my_package.main -- --user=test\n\n"
        "  # 使用配置文件\n"
        "  python -m debugger.tracer_main --config my_config.yaml script.py\n\n"
        "  # 其他常用选项\n"
        "  python -m debugger.tracer_main --watch-files='src/*.py' script.py\n"
        "  python -m debugger.tracer_main --capture-vars='x' --capture-vars='y.z' script.py\n"
        "  python -m debugger.tracer_main --line-ranges='test.py:10-20' script.py\n"
        "  python -m debugger.tracer_main --start-function='main.py:5' script.py arg1 --arg2\n"
        "  python -m debugger.tracer_main --include-stdlibs=json --include-stdlibs=re script.py\n"
        "  python -m debugger.tracer_main --trace-c-calls script.py"
    )
    parser = ArgumentParser(
        description="Python脚本/模块调试跟踪工具",
        usage="python -m debugger.tracer_main [选项] (<脚本> | -m <模块>) [参数]",
        formatter_class=RawDescriptionHelpFormatter,
        epilog=epilog,
        add_help=False,  # We add our own help argument for custom text
    )
    # Redefine help argument to provide custom help text in Chinese
    parser.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    parser.add_argument(
        "-m",
        "--module",
        type=str,
        help="以模块方式执行和跟踪 (例如: my_package.main)",
    )
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
        "--include-stdlibs",
        action="append",
        help="即使默认忽略系统路径，也强制追踪指定的标准库模块 (可多次指定，例如: --include-stdlibs json)",
    )
    parser.add_argument(
        "--trace-self",
        action="store_true",
        help="包含跟踪器自身的代码执行 (用于调试跟踪器)",
    )
    parser.add_argument(
        "--trace-c-calls",
        action="store_true",
        help="启用对C函数的调用跟踪 (可能显著影响性能和输出量)",
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
    解析命令行参数，支持配置文件，并稳健地分离目标及其参数。

    处理顺序:
    1. 查找 --config 参数并加载配置文件作为默认值。
    2. 解析调试器自身的参数。
    3. 将剩余的参数视为目标（脚本或模块）及其参数。
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
            import yaml

            try:
                config_from_file = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                raise ValueError(f"配置文件解析失败: {e}") from e

    parser.set_defaults(**config_from_file)

    # 解析剩余的参数
    # parse_known_args 如果存在 -h 或 --help，将会退出
    args, target_argv = parser.parse_known_args(remaining_argv)

    target_script: Optional[Path] = None
    target_module: Optional[str] = None
    script_args: List[str] = []

    if args.module:
        target_module = args.module
        script_args = target_argv
    else:
        if not target_argv:
            raise ValueError("未指定目标。请提供脚本路径或使用 -m <模块>。")
        target_script = Path(target_argv[0])
        script_args = target_argv[1:]

    # 解析行号范围
    line_ranges = {}
    if args.line_ranges:
        for range_str in args.line_ranges.split(","):
            try:
                file_path, ranges = range_str.split(":", 1)
                file_path = os.path.abspath(file_path)  # 转换为绝对路径
                start_str, end_str = ranges.split("-", 1)
                start, end = int(start_str), int(end_str)
                if start > end:
                    raise ValueError(f"起始行号 {start} 大于结束行号 {end}")
                if file_path not in line_ranges:
                    line_ranges[file_path] = []
                line_ranges[file_path].append((start, end))
            except ValueError as e:
                raise ValueError(f"行号范围格式错误 '{range_str}': {e}") from e
            except Exception as e:
                raise ValueError(f"解析行号范围时发生未知错误 '{range_str}': {e}") from e

    return {
        "target_script": target_script,
        "target_module": target_module,
        "script_args": script_args,
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
        "start_function": args.start_function,
        "source_base_dir": args.source_base_dir,
        "include_stdlibs": args.include_stdlibs or [],
        "trace_c_calls": args.trace_c_calls,
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
    if not argv:
        create_parser().print_help()
        return 0

    try:
        args = parse_cli_args(argv)
        target_script = args["target_script"]
        target_module = args["target_module"]
        target_path_for_config: Path

        if target_script:
            target_path_for_config = target_script.resolve()
            if not target_path_for_config.exists():
                print(color_wrap(f"❌ 目标文件 {target_path_for_config} 不存在", "error"))
                return 2
            if target_path_for_config.suffix != ".py":
                print(color_wrap(f"❌ 目标文件 {target_path_for_config} 不是Python脚本(.py)", "error"))
                return 2
            print(color_wrap(f"\n🔍 启动调试会话 - 目标脚本: {target_path_for_config}", "call"))

        elif target_module:
            try:
                spec = importlib.util.find_spec(target_module)
                if spec is None:
                    raise ImportError(f"无法找到模块 '{target_module}' 的规范。")
                if spec.origin is None or spec.origin == "built-in":
                    raise ImportError(f"不支持跟踪内置或命名空间模块: {target_module}")

                # 如果是包，入口点是 `__main__.py`
                if spec.submodule_search_locations:
                    main_py_path = Path(spec.origin).parent / "__main__.py"
                    if main_py_path.exists():
                        target_path_for_config = main_py_path
                    else:
                        msg = f"⚠ 模块 '{target_module}' 是一个包但缺少 '__main__.py'。执行可能会因缺少入口点而失败。"
                        print(color_wrap(msg, "error"))
                        # 跟踪将从 __init__.py 开始
                        target_path_for_config = Path(spec.origin)
                else:
                    target_path_for_config = Path(spec.origin)

                target_path_for_config = target_path_for_config.resolve()
                print(
                    color_wrap(
                        f"\n🔍 启动调试会话 - 目标模块: {target_module} ({target_path_for_config})",
                        "call",
                    )
                )

            except ImportError as e:
                print(color_wrap(f"❌ 无法定位模块: {e}", "error"))
                return 2
        else:
            # 此分支不应被 parse_cli_args 的逻辑命中
            create_parser().print_help()
            return 1

        if args["watch_files"]:
            print(color_wrap(f"📝 监控文件模式: {', '.join(args['watch_files'])}", "var"))
        if args["capture_vars"]:
            print(color_wrap(f"📝 捕获变量: {', '.join(args['capture_vars'])}", "var"))
        if args["exclude_functions"]:
            print(color_wrap(f"📝 排除函数: {', '.join(args['exclude_functions'])}", "var"))
        if args["line_ranges"]:
            print(color_wrap(f"📝 行号范围: {args['line_ranges']}", "var"))
        if args["start_function"]:
            print(color_wrap(f"📝 起始函数: {args['start_function']}", "var"))
        if args["source_base_dir"]:
            print(color_wrap(f"📝 源码根目录: {args['source_base_dir'].resolve()}", "var"))
        if args["include_stdlibs"]:
            print(color_wrap(f"📝 包含标准库: {', '.join(args['include_stdlibs'])}", "var"))

        # 创建 TraceConfig 实例
        config = TraceConfig(
            target_files=args["watch_files"] + [f"*{target_path_for_config.stem}.py"],
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
            include_stdlibs=args["include_stdlibs"],
            trace_c_calls=args["trace_c_calls"],
        )

        log_dir = Path(__file__).parent / "logs"
        # 报告路径将在 `tracer.stop()` 后确定
        report_path = log_dir / config.report_name

        print(color_wrap("\n📝 调试功能:", "line"))
        print(color_wrap("  ✓ 仅追踪目标模块内的代码执行", "call"))
        print(color_wrap(f"  ✓ {'包含' if not config.ignore_system_paths else '跳过'}标准库和第三方库", "call"))
        print(color_wrap(f"  ✓ {'包含' if not config.ignore_self else '跳过'}跟踪器自身的代码", "call"))
        if config.enable_var_trace:
            print(color_wrap("  ✓ 变量变化检测", "var"))
        if config.trace_c_calls and sys.version_info >= (3, 12):
            print(color_wrap("  ✓ C函数调用跟踪 (sys.monitoring)", "var"))
        print(color_wrap("  ✓ 彩色终端输出 (日志文件无颜色)", "return"))
        print(color_wrap("  ✓ 多线程跟踪支持", "return"))
        print(color_wrap(f"\n📂 调试日志路径: {log_dir / 'debug.log'}", "line"))
        print(color_wrap(f"📂 报告文件路径: {report_path.parent / Path(report_path.stem + '.log')}\n", "line"))

        original_argv = sys.argv.copy()
        exit_code = 0
        tracer = None
        report_path = None

        try:
            tracer = start_trace(target_path_for_config, config=config)

            execute_target(target_script, target_module, args["script_args"])
        except KeyboardInterrupt:
            print(color_wrap("\n🛑 用户中断调试过程", "error"))
            exit_code = 130
        except Exception as e:
            print(color_wrap(f"❌ 执行错误: {str(e)}", "error"))
            logging.error("执行错误: %s\n%s", str(e), traceback.format_exc())
            exit_code = 3
        finally:
            if tracer:
                report_path = stop_trace(tracer)
            sys.argv = original_argv
            if report_path:
                print_debug_summary(report_path)
                if args["open_report"] and not config.disable_html:
                    open_trace_report(report_path)

        return exit_code
    except (ValueError, FileNotFoundError) as e:
        print(color_wrap(f"❌ 参数错误: {str(e)}", "error"))
        # Show help for value errors like missing script/module
        if "未指定目标" in str(e):
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
    print(color_wrap("  ↘ C-CALL   - C函数调用", "trace"))
    print(color_wrap("  ↗ C-RETURN - C函数返回", "trace"))
    print(color_wrap("  Δ VARIABLES - 变量创建/修改/删除", "var"))
    print(color_wrap("  ▷ LINE     - 执行的源代码行", "line"))
    print(color_wrap("  ⚠ WARNING  - 异常或限制提示", "error"))
    print(color_wrap("\n调试功能说明:", "line"))
    print(color_wrap(f"{Path(__file__).parent}/logs/debug.log 查看日志", "line"))
    print(color_wrap(f"{report_path} 查看网页报告", "line"))


if __name__ == "__main__":
    sys.exit(debug_main())
