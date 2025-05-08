import subprocess
import re
import os


class DebugEnvironment:
    def __init__(self, debugger):
        self.debugger = debugger

    def get_compiler_info(self) -> dict:
        """获取clang/gcc版本"""
        compiler_info = {}
        try:
            # 尝试获取clang版本
            clang_output = subprocess.check_output(["clang", "--version"], stderr=subprocess.STDOUT, timeout=5).decode()
            if "clang version" in clang_output:
                version_match = re.search(r"clang version (\d+\.\d+\.\d+)", clang_output)
                if version_match:
                    compiler_info["clang"] = version_match.group(1)

            # 尝试获取gcc版本
            gcc_output = subprocess.check_output(["gcc", "--version"], stderr=subprocess.STDOUT, timeout=5).decode()
            if "gcc (GCC)" in gcc_output:
                version_match = re.search(r"gcc \(GCC\) (\d+\.\d+\.\d+)", gcc_output)
                if version_match:
                    compiler_info["gcc"] = version_match.group(1)
        except subprocess.TimeoutExpired:
            compiler_info["error"] = "compiler version check timeout"
        except Exception as e:
            compiler_info["error"] = str(e)
        return compiler_info

    def get_loaded_images(self) -> list:
        """获取加载的共享库列表"""
        target = self.debugger.GetSelectedTarget()
        modules = []
        for module in target.modules:
            modules.append(
                {
                    "path": os.path.join(module.GetFileSpec().GetDirectory(), module.GetFileSpec().GetFilename()),
                    "symbols_loaded": module.GetNumSymbols() > 0,
                }
            )
        return modules

    def get_runtime_stats(self) -> dict:
        """获取内存/线程使用情况"""
        process = self.debugger.GetSelectedTarget().GetProcess()
        return {
            "memory_usage": process.GetMemoryUsage(),
            "thread_count": process.GetNumThreads(),
            "state": str(process.GetState()),
        }
