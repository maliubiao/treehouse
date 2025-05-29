#!/usr/bin/env python3
"""LLDB Tracer 主入口模块"""

import argparse
import logging

from tracer import Tracer


def parse_args():
    parser = argparse.ArgumentParser(description="LLDB Tracer Tool")
    parser.add_argument("-e", "--program-path", required=True, help="Path to the debugged program")
    parser.add_argument("-a", "--program-args", action="append", default=[], help="Program arguments (repeatable)")
    parser.add_argument("-l", "--logfile", help="Path to log output")
    parser.add_argument("-c", "--config-file", help="Path to config file")
    parser.add_argument("--condition", help="Breakpoint condition expression")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "--dump-modules-for-skip", action="store_true", help="Dump module information and generate skip modules config"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    tracer = Tracer(
        program_path=args.program_path,
        program_args=args.program_args,
        logfile=args.logfile,
        config_file=args.config_file,
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
    tracer.start()


if __name__ == "__main__":
    main()
