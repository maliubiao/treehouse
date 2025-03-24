#!/usr/bin/env python3
import logging
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from debugger.tracer import TraceConfig, TraceCore, _color_wrap, start_trace, stop_trace


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

    return {"target": Path(argv[0]), "script_args": argv[1:]}


def debug_main(argv: Optional[List[str]] = None) -> int:
    """调试器主入口，可被其他模块调用"""
    try:
        if argv is None:
            argv = sys.argv[1:]

        if not argv:
            print(
                _color_wrap(
                    "用法: python -m debugger.pdb_debugger <目标脚本> [脚本参数]\n"
                    "示例: python -m debugger.pdb_debugger src/main.py --verbose",
                    "error",
                )
            )
            return 1

        args = parse_args(argv)
        target = args["target"].resolve()
        if not target.exists():
            print(_color_wrap(f"❌ 目标文件 {target} 不存在", "error"))
            return 2

        print(_color_wrap(f"\n🔍 启动调试会话 - 目标: {target}", "call"))
        print(_color_wrap("📝 调试功能说明:", "line"))
        print(_color_wrap("  ✓ 仅追踪目标模块内的代码执行", "call"))
        print(_color_wrap("  ✓ 自动跳过标准库和第三方库", "call"))
        print(_color_wrap("  ✓ 变量变化检测 (截断长度: 100字符)", "var"))
        print(_color_wrap("  ✓ 循环控制: 同一行最多记录3次", "line"))
        print(_color_wrap("  ✓ 彩色终端输出 (日志文件无颜色)", "return"))
        print(_color_wrap("  ✓ 自动在主程序入口设置断点 (if __name__ == '__main__')", "call"))
        print(_color_wrap(f"\n📂 调试日志路径: {Path(__file__).parent/'logs/debug.log'}\n", "line"))

        original_argv = sys.argv.copy()
        exit_code = 0

        try:
            # 创建匹配当前调试目标的TraceConfig
            config = TraceConfig(
                target_files=[f"*{target.stem}.py"],  # 匹配当前脚本相关的文件
                capture_vars=[],
            )
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
    print(_color_wrap(f"\n输入 'tail -f {Path(__file__).parent}/logs/debug.log' 实时查看日志\n", "line"))


if __name__ == "__main__":
    sys.exit(debug_main())
