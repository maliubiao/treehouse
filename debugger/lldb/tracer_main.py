#!/usr/bin/env python3
"""LLDB Tracer 主入口模块"""

import argparse
import atexit
import logging
import sys

from tracer import Tracer


def parse_args():
    parser = argparse.ArgumentParser(description="LLDB Tracer Tool")
    parser.add_argument("-e", "--program-path", required=True, help="Path to the debugged program")
    parser.add_argument(
        "-a",
        "--program-args",
        action="append",
        default=[],
        help="Program arguments (repeatable, deprecated - use '--' separator instead)",
    )
    parser.add_argument("-l", "--logfile", help="Path to log output")
    parser.add_argument("-c", "--config-file", help="Path to config file")
    parser.add_argument("--condition", help="Breakpoint condition expression")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "--attach-pid", type=int, help="Attach to an existing process by PID instead of launching a new one"
    )
    parser.add_argument(
        "--dump-modules-for-skip", action="store_true", help="Dump module information and generate skip modules config"
    )
    parser.add_argument(
        "--dump_source_files_for_skip",
        action="store_true",
        help="dump source files information and generate skip source files config",
    )

    # 使用parse_known_args来处理--分隔符
    args, remaining = parser.parse_known_args()

    # 检查是否使用了--分隔符
    if "--" in sys.argv:
        separator_pos = sys.argv.index("--")
        program_args = sys.argv[separator_pos + 1 :]

        # 验证是否同时使用了--program-args和--分隔符
        if args.program_args:
            parser.error("Cannot use both --program-args and '--' separator")

        args.program_args = program_args

    return args


from debugger.presets import generate_for_project


@generate_for_project(
    project_glob="*/tracer/*py",
    model_name="deepseek-r1",
    checker_model_name="gemini-2.5-flash",
    num_workers=10,
    trace_llm=True,
    verbose_trace=True,
)
def main():
    args = parse_args()
    tracer = Tracer(
        program_path=args.program_path,
        program_args=args.program_args,
        logfile=args.logfile,
        config_file=args.config_file,
        attach_pid=args.attach_pid,
    )
    if args.verbose:
        tracer.logger.setLevel(logging.DEBUG)
        tracer.config_manager.config.update(
            {
                "log_target_info": True,
                "log_module_info": True,
                "log_breakpoint_details": True,
            }
        )
    if args.dump_modules_for_skip:
        tracer.config_manager.config["dump_modules_for_skip"] = True
    if args.dump_source_files_for_skip:
        tracer.config_manager.config["dump_source_files_for_skip"] = True
    tracer.start()


if __name__ == "__main__":
    # 注册全局退出处理函数
    atexit.register(lambda: logging.shutdown())

    main()
