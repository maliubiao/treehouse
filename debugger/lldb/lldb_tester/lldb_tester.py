#!/usr/bin/env python3

import argparse
import glob
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

import colorama
import lldb


class TestStatus(Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class TestResult:
    name: str
    status: TestStatus
    duration: float
    message: str = ""


class TestReporter:
    def __init__(self):
        self.results: List[TestResult] = []
        colorama.init()

    def add_result(self, result: TestResult):
        self.results.append(result)

    def print_summary(self):
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)
        error = sum(1 for r in self.results if r.status == TestStatus.ERROR)

        print("\n=== Test Summary ===")
        print(f"Total: {len(self.results)}, Passed: {passed}, Failed: {failed}, Error: {error}, Skipped: {skipped}")

        if failed > 0 or error > 0:
            print("\n=== Failed/Error Tests ===")
            for result in self.results:
                if result.status in (TestStatus.FAILED, TestStatus.ERROR):
                    print(f"{result.name}: {result.message}")


class TestLoader:
    @staticmethod
    def discover_tests(test_dir: str, pattern: str = "test_*.py") -> List[str]:
        if not os.path.exists(test_dir):
            return []
        return glob.glob(os.path.join(test_dir, pattern))

    @staticmethod
    def map_tests_to_programs(test_files: List[str], programs_dir: str) -> Dict[str, str]:
        """映射测试脚本到对应的测试程序"""
        test_map = {}
        for test_file in test_files:
            # 提取程序名: test_<program>.py -> <program>
            base_name = os.path.basename(test_file)
            if base_name.startswith("test_") and base_name.endswith(".py"):
                program_name = base_name[5:-3]

                # 尝试多种命名格式和扩展名
                possible_files = []
                # 不带前缀的.c/.cpp文件
                possible_files.append(os.path.join(programs_dir, f"{program_name}.c"))
                possible_files.append(os.path.join(programs_dir, f"{program_name}.cpp"))
                # 带test_前缀的.c/.cpp文件
                possible_files.append(os.path.join(programs_dir, f"test_{program_name}.c"))
                possible_files.append(os.path.join(programs_dir, f"test_{program_name}.cpp"))
                # 与测试脚本同名的.c/.cpp文件
                possible_files.append(os.path.join(programs_dir, f"{base_name[:-3]}.c"))
                possible_files.append(os.path.join(programs_dir, f"{base_name[:-3]}.cpp"))

                # 查找存在的源文件
                source_file = None
                for file_path in possible_files:
                    if os.path.exists(file_path):
                        source_file = file_path
                        break

                if source_file:
                    test_map[test_file] = source_file
                else:
                    logging.warning("No matching source file for test: %s", test_file)
            else:
                logging.warning("Test file doesn't follow naming convention: %s", test_file)
        return test_map


class TestContext:
    """为测试函数提供调试环境上下文"""

    def __init__(self, debugger, target, process):
        self.debugger = debugger
        self.target = target
        self.process = process

    def run_command(self, command: str) -> lldb.SBCommandReturnObject:
        """执行LLDB命令（可选，推荐直接使用LLDB API）"""
        ret = lldb.SBCommandReturnObject()
        self.debugger.GetCommandInterpreter().HandleCommand(command, ret)
        return ret.GetOutput()

    def wait_for_stop(self, timeout_sec: float = 5.0) -> bool:
        """等待进程进入停止状态"""
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            state = self.process.GetState()
            if state == lldb.eStateStopped:
                return True
            time.sleep(0.1)
        return False


class LLDBTester:
    def __init__(self, config_file=None):
        self.config = self._load_config(config_file) if config_file else {}
        self.debugger = lldb.SBDebugger.Create()
        self.debugger.SetAsync(False)
        self.reporter = TestReporter()
        logging.basicConfig(level=logging.INFO)

        # 添加项目根目录到Python路径
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        self.test_programs_dir = os.path.join(os.path.dirname(__file__), "test_programs")
        self.test_scripts_dir = os.path.join(os.path.dirname(__file__), "test_scripts")
        self.temp_files = []

    def _load_config(self, config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logging.error("Failed to load config file: %s", e)
            raise RuntimeError(f"Config file error: {e}") from e

    def _create_target(self, test_program: str) -> lldb.SBTarget:
        """为测试创建全新的target"""
        target = self.debugger.CreateTarget(test_program)
        if not target:
            raise RuntimeError(f"Failed to create target for {test_program}")

        # 在main函数设置断点
        main_bp = target.BreakpointCreateByName("main", target.GetExecutable().GetFilename())
        if not main_bp:
            logging.warning("Failed to set breakpoint at main. Program may not stop at entry point.")
        else:
            logging.info("Set breakpoint at main: %s", main_bp)

        return target

    def _execute_test_function(self, test_func, context, full_test_name):
        """执行单个测试函数并处理结果"""
        result = TestResult(name=full_test_name, status=TestStatus.PASSED, duration=0)
        start_time = time.time()

        try:
            test_func(context)
        except Exception as e:
            result.status = TestStatus.FAILED
            result.message = f"{type(e).__name__}: {str(e)}"
            logging.error("Test %s failed: %s", full_test_name, e, exc_info=True)

        result.duration = time.time() - start_time
        return result

    def _run_test_script(self, test_script: str, test_program: str) -> List[TestResult]:
        """运行测试脚本并返回测试结果列表"""
        test_name = os.path.basename(test_script)
        results = []

        try:
            # 动态导入测试模块
            module_name = os.path.splitext(test_name)[0]
            spec = importlib.util.spec_from_file_location(module_name, test_script)
            if spec is None:
                raise ImportError(f"Could not import test module: {test_script}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # 查找并执行所有测试函数
            test_functions = []
            for name, func in module.__dict__.items():
                if callable(func) and (name.startswith("test_") or name == "run_test"):
                    test_functions.append((name, func))

            if not test_functions:
                raise RuntimeError(f"No test functions found in {test_script}")

            for name, test_func in test_functions:
                full_test_name = f"{test_name}::{name}"
                target = None
                process = None

                try:
                    # 为每个测试函数创建全新的target
                    target = self._create_target(test_program)

                    # 启动新进程
                    logging.info("Launching program for test: %s", full_test_name)
                    process = target.LaunchSimple(None, None, os.getcwd())
                    if not process:
                        raise RuntimeError(f"Failed to launch process for {test_program}")

                    # 确保程序已停止
                    if not process.GetState() == lldb.eStateStopped:
                        logging.warning("Program not stopped after launch. Waiting for stop...")
                        if not TestContext(self.debugger, target, process).wait_for_stop():
                            raise RuntimeError("Program did not stop after launch")

                    # 创建测试上下文
                    context = TestContext(debugger=self.debugger, target=target, process=process)

                    # 执行测试函数
                    result = self._execute_test_function(test_func, context, full_test_name)
                    results.append(result)

                except Exception as e:
                    error_result = TestResult(
                        name=full_test_name,
                        status=TestStatus.ERROR,
                        duration=0,
                        message=f"Setup failed: {type(e).__name__}: {str(e)}",
                    )
                    results.append(error_result)
                    logging.error("Test %s setup failed: %s", full_test_name, e, exc_info=True)

                finally:
                    # 清理当前测试的进程和target
                    if process and process.IsValid() and process.GetState() != lldb.eStateExited:
                        process.Destroy()
                    if target and target.IsValid():
                        self.debugger.DeleteTarget(target)

        except Exception as e:
            error_result = TestResult(
                name=test_name,
                status=TestStatus.ERROR,
                duration=0,
                message=f"Setup failed: {type(e).__name__}: {str(e)}",
            )
            results.append(error_result)
            logging.error("Test %s setup failed: %s", test_name, e, exc_info=True)

        return results

    def compile_test_program(self, source_path):
        """编译C/C++测试程序并返回可执行文件路径"""
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Test program not found: {source_path}")

        executable = source_path.rsplit(".", 1)[0]
        dsym_dir = executable + ".dSYM"

        # 检查是否需要重新编译
        need_compile = False
        if not os.path.exists(executable):
            need_compile = True
        else:
            # 检查源文件是否比可执行文件新
            src_mtime = os.path.getmtime(source_path)
            exe_mtime = os.path.getmtime(executable)
            if src_mtime > exe_mtime:
                need_compile = True

        if need_compile:
            # 删除旧的可执行文件和dSYM目录
            if os.path.exists(executable):
                os.remove(executable)
            if os.path.exists(dsym_dir):
                shutil.rmtree(dsym_dir)

            # 根据文件扩展名选择编译器
            compiler = "gcc"
            if source_path.endswith(".cpp"):
                compiler = "g++"

            # 编译程序
            cmd = [compiler, "-g", "-O0", source_path, "-o", executable]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if result.returncode != 0:
                raise RuntimeError(f"Compilation failed for {source_path}:\n{result.stderr}")
            print(f"Compiled: {source_path} -> {executable}")
        else:
            print(f"Using existing executable: {executable}")

        return executable

    def run_tests(self, test_map: Dict[str, str], continue_on_failure: bool = False) -> int:
        """运行测试，test_map映射测试脚本到对应的源文件"""
        for test_file, source_file in test_map.items():
            try:
                # 编译测试程序
                executable = self.compile_test_program(source_file)

                # 运行测试脚本
                results = self._run_test_script(test_file, executable)
                for result in results:
                    self.reporter.add_result(result)

                    if result.status == TestStatus.PASSED:
                        status_color = colorama.Fore.GREEN
                    elif result.status == TestStatus.FAILED:
                        status_color = colorama.Fore.RED
                    else:
                        status_color = colorama.Fore.YELLOW

                    status_msg = f"{status_color}[{result.status.value}]{colorama.Style.RESET_ALL}"
                    print(f"{status_msg} {result.name} ({result.duration:.2f}s)")

                    # 检查是否需要中断
                    if result.status in (TestStatus.FAILED, TestStatus.ERROR) and not continue_on_failure:
                        logging.error("Aborting tests due to failure in %s", test_file)
                        return 1

            except Exception as e:
                error_result = TestResult(
                    name=os.path.basename(test_file),
                    status=TestStatus.ERROR,
                    duration=0,
                    message=f"Setup failed: {str(e)}",
                )
                self.reporter.add_result(error_result)
                logging.error("Failed to run test %s: %s", test_file, e)
                if not continue_on_failure:
                    return 1

        self.reporter.print_summary()
        return 0

    def build_all_programs(self):
        """编译所有测试程序"""
        # 同时查找.c和.cpp文件
        test_programs = glob.glob(os.path.join(self.test_programs_dir, "*.c")) + glob.glob(
            os.path.join(self.test_programs_dir, "*.cpp")
        )
        if not test_programs:
            print("No test programs found to build", file=sys.stderr)
            return 1

        for program in test_programs:
            try:
                self.compile_test_program(program)
            except Exception as e:
                print(f"Failed to build {program}: {e}", file=sys.stderr)
                return 1
        return 0

    def cleanup(self):
        """清理临时文件和编译产物，保留源代码"""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                if os.path.isdir(temp_file):
                    shutil.rmtree(temp_file)
                else:
                    os.remove(temp_file)

        # 清理编译产物
        for root, dirs, files in os.walk(self.test_programs_dir):
            # 删除可执行文件
            for file in files:
                if not (file.endswith(".c") or file.endswith(".cpp")):
                    file_path = os.path.join(root, file)
                    if os.access(file_path, os.X_OK):  # 检查是否是可执行文件
                        os.remove(file_path)
                        print(f"Removed executable: {file_path}")

            # 删除dSYM目录
            for dir_name in dirs:
                if dir_name.endswith(".dSYM"):
                    dir_path = os.path.join(root, dir_name)
                    shutil.rmtree(dir_path)
                    print(f"Removed dSYM directory: {dir_path}")

        self.temp_files = []


def main():
    parser = argparse.ArgumentParser(description="LLDB API Test Framework")
    parser.add_argument("-c", "--config", help="Path to config file")
    parser.add_argument("-t", "--test", help="Run specific test file")
    parser.add_argument("-p", "--pattern", default="test_*.py", help="Test file pattern")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continue on test failure")
    parser.add_argument("--list-tests", action="store_true", help="List available tests")
    parser.add_argument("--build", action="store_true", help="Automatically build all test programs")
    parser.add_argument("--clean", action="store_true", help="Clean up after tests")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # 设置日志级别
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    tester = LLDBTester(args.config)

    # 获取测试脚本
    if args.test:
        test_files = [args.test]
    else:
        test_files = TestLoader.discover_tests(tester.test_scripts_dir, args.pattern)

    if args.list_tests:
        print("Available tests:")
        for test in test_files:
            print(f"  {test}")
        return 0

    if not test_files:
        print("No tests found", file=sys.stderr)
        return 1

    # 构建所有测试程序（如果指定）
    if args.build:
        if tester.build_all_programs() != 0:
            return 1
        # 如果只构建不运行测试
        if not any([args.test, args.pattern != "test_*.py"]):
            print("All test programs built successfully")
            return 0

    # 映射测试脚本到测试程序
    test_map = TestLoader.map_tests_to_programs(test_files, tester.test_programs_dir)
    if not test_map:
        print("No valid test mappings found", file=sys.stderr)
        return 1

    # 运行测试
    exit_code = tester.run_tests(test_map, args.continue_on_failure)

    # 清理
    if args.clean:
        tester.cleanup()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
