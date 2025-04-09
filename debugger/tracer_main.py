#!/usr/bin/env python3
import logging
import os
import sys
import traceback
import webbrowser
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from debugger.tracer import TraceConfig, _color_wrap, start_trace


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
            print(_color_wrap(f"⚠ 脚本以退出码 {sys_exit.code} 终止", "error"))
    except Exception:
        traceback.print_exc()
        raise


def parse_args(argv: List[str]) -> Dict[str, Any]:
    """解析命令行参数"""
    if len(argv) < 1:
        print(_color_wrap("错误：需要指定目标脚本", "error"))
        sys.exit(1)

    result = {"target": None, "script_args": [], "watch_files": []}

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            # 遇到--后剩余参数都作为脚本参数
            result["script_args"] = argv[i + 1 :]
            break
        elif arg.startswith("--watch-files="):
            # 处理--watch-files参数
            file_patterns = arg.split("=", 1)[1].split(",")
            result["watch_files"] = [p.strip() for p in file_patterns if p.strip()]
            i += 1
        elif arg.startswith("--"):
            # 忽略其他未知调试参数
            i += 1
        else:
            # 第一个非--参数作为目标脚本，剩余作为脚本参数
            result["target"] = Path(arg)
            result["script_args"] = argv[i + 1 :]
            break

    if not result["target"]:
        print(_color_wrap("错误：需要指定目标脚本", "error"))
        sys.exit(1)

    return result


def open_trace_report() -> None:
    """打开跟踪报告HTML文件"""
    report_path = Path(__file__).parent / "logs" / "trace_report.html"
    if not report_path.exists():
        print(_color_wrap(f"❌ 跟踪报告文件 {report_path} 不存在", "error"))
        return

    try:
        if sys.platform == "win32":
            os.startfile(report_path)
        elif sys.platform == "darwin":
            webbrowser.open(f"file://{report_path}")
        else:
            webbrowser.open(f"file://{report_path}")
    except Exception as e:
        print(_color_wrap(f"❌ 无法打开跟踪报告: {str(e)}", "error"))


def debug_main(argv: Optional[List[str]] = None) -> int:
    """调试器主入口，可被其他模块调用"""
    try:
        if argv is None:
            argv = sys.argv[1:]

        if not argv:
            print(
                _color_wrap(
                    "用法: python -m debugger.tracer_main [调试选项] <目标脚本> [脚本参数]\n"
                    "调试选项:\n"
                    "  --watch-files=PATTERNS  可以使用多次这个选项\n"
                    "  --open-report          调试完成后自动打开HTML报告\n"
                    "示例: python -m debugger.tracer_main --watch-files='src/*.py' --watch-files='*main.py' --verbose --open-report",
                    "error",
                )
            )
            return 1

        open_report = "--open-report" in argv
        if open_report:
            argv.remove("--open-report")

        args = parse_args(argv)
        target = args["target"].resolve()
        if not target.exists():
            print(_color_wrap(f"❌ 目标文件 {target} 不存在", "error"))
            return 2

        print(_color_wrap(f"\n🔍 启动调试会话 - 目标: {target}", "call"))
        if args["watch_files"]:
            print(_color_wrap(f"📝 监控文件模式: {', '.join(args['watch_files'])}", "var"))
        print(_color_wrap("📝 调试功能说明:", "line"))
        print(_color_wrap("  ✓ 仅追踪目标模块内的代码执行", "call"))
        print(_color_wrap("  ✓ 自动跳过标准库和第三方库", "call"))
        print(_color_wrap("  ✓ 变量变化检测", "var"))
        print(_color_wrap("  ✓ 彩色终端输出 (日志文件无颜色)", "return"))
        print(_color_wrap(f"\n📂 调试日志路径: {Path(__file__).parent/'logs/debug.log'}\n", "line"))

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
            print(_color_wrap(f"  ✓ 监控文件模式: {', '.join(target_patterns)}", "call"))
            tracer = start_trace(target, config=config)
            execute_script(target, args["script_args"])
        except KeyboardInterrupt:
            print(_color_wrap("\n🛑 用户中断调试过程", "error"))
            exit_code = 130
        except (SystemExit, RuntimeError) as e:
            print(_color_wrap(f"❌ 执行错误: {str(e)}", "error"))
            logging.error("执行错误: %s\n%s", str(e), traceback.format_exc())
            exit_code = 3
        finally:
            tracer.stop()
            sys.argv = original_argv
            print_debug_summary()
            if open_report:
                open_trace_report()

        return exit_code
    except (SystemExit, RuntimeError) as e:
        logging.error("调试器崩溃: %s\n%s", str(e), traceback.format_exc())
        print(_color_wrap(f"💥 调试器内部错误: {str(e)}", "error"))
        return 4


def print_debug_summary() -> None:
    """打印调试会话摘要"""
    print(_color_wrap("\n调试日志包含以下信息类型：", "line"))
    print(_color_wrap("  ↘ CALL     - 函数调用及参数", "call"))
    print(_color_wrap("  ↗ RETURN   - 函数返回值及耗时", "return"))
    print(_color_wrap("  Δ VARIABLES - 变量创建/修改/删除", "var"))
    print(_color_wrap("  ▷ LINE     - 执行的源代码行", "line"))
    print(_color_wrap("  ⚠ WARNING  - 异常或限制提示", "error"))
    print(_color_wrap("\n调试功能说明:", "line"))
    print(_color_wrap(f"{Path(__file__).parent}/logs/debug.log 查看日志", "line"))
    print(_color_wrap(f"{Path(__file__).parent}/logs/trace_report.html 查看网页报告", "line"))


if __name__ == "__main__":
    sys.exit(debug_main())
