import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class SymbolTracePattern:
    """Represents a symbol trace pattern configuration.

    Attributes:
        module: The module name to trace symbols in
        regex: Regular expression pattern to match symbol names
    """

    module: str
    regex: str


class ConfigManager:
    def __init__(self, config_file=None, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.config = {
            "max_steps": 100,
            "log_target_info": True,
            "log_module_info": True,
            "log_breakpoint_details": True,
            "skip_modules": [],
            "dump_modules_for_skip": False,
            "skip_source_files": [],
            "dump_source_files_for_skip": False,
            "skip_symbols_file": "skip_symbols.yaml",
            "use_source_cache": True,
            "cache_dir": "cache",
            "environment": {},
            "enable_symbol_trace": False,
            "symbol_trace_patterns": [],
            "attach_pid": None,
            "forward_stdin": True,
            "expression_hooks": [],
            "libc_functions": [],
            "source_search_paths": [],
            "symbol_trace_cache_file": None,
            "source_base_dir": "",  # New option for shortening source paths
            "symbol_trace_enabled": False,  # Added: global enable/disable flag
            "show_console": False,  # 新增：是否显示LLDB控制台
        }
        self.config_file = config_file
        if config_file:
            self._load_config(config_file)
        else:
            self.config_file = "tracer_config.yaml"
        # 加载符号配置文件
        self._load_skip_symbols()

    def _load_config(self, filepath):
        with open(filepath, encoding="utf-8") as f:
            loaded_config = yaml.safe_load(f)
            self.config.update(loaded_config)
            self.logger.info("Loaded config from %s: %s", filepath, loaded_config)

            self.config["expression_hooks"] = self._validate_expression_hooks(self.config.get("expression_hooks"))
            self.config["libc_functions"] = self._validate_libc_functions(self.config.get("libc_functions"))
            self.config["source_search_paths"] = self._validate_source_search_paths(
                self.config.get("source_search_paths")
            )
            self.config["symbol_trace_patterns"] = self._validate_symbol_trace_patterns(
                self.config.get("symbol_trace_patterns")
            )
            self.config["source_base_dir"] = self._validate_source_base_dir(self.config.get("source_base_dir"))
            self.config["symbol_trace_cache_file"] = self._validate_symbol_trace_cache_file(
                self.config.get("symbol_trace_cache_file")
            )

    def _load_skip_symbols(self):
        """加载符号配置文件"""
        skip_symbols_file = self.config.get("skip_symbols_file")
        if not skip_symbols_file:
            return

        try:
            if os.path.exists(skip_symbols_file):
                with open(skip_symbols_file, "r", encoding="utf-8") as f:
                    skip_symbols = yaml.safe_load(f) or {}
                # 合并到主配置
                if "skip_source_files" in skip_symbols:
                    self.config["skip_source_files"] = list(
                        set(self.config.get("skip_source_files", []) + skip_symbols["skip_source_files"])
                    )
                self.logger.info("Loaded skip symbols from %s", skip_symbols_file)
        except (yaml.YAMLError, OSError) as e:
            self.logger.error("Error loading skip symbols file: %s", str(e))

    def _watch_config(self):
        last_mtime = 0
        while True:
            try:
                current_mtime = os.path.getmtime(self.config_file)
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    self._load_config(self.config_file)
                    self.logger.info("Config file reloaded")
            except FileNotFoundError:
                self.logger.error("Config file %s not found, stop watching.", self.config_file)
                break  # 退出监控循环
            except OSError as e:
                self.logger.error("Error watching config file: %s", str(e))
            time.sleep(1)

    def save_skip_modules(self, modules):
        """保存skip modules到配置文件，合并现有配置"""
        if not self.config_file:
            self.logger.warning("No config file specified, skip modules not saved")
            return
        try:
            # 读取现有配置或创建空配置
            config = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}

            # 合并skip_modules列表并去重
            existing_modules = set(config.get("skip_modules", []))
            new_modules = set(modules)
            merged_modules = list(existing_modules.union(new_modules))

            # 更新配置并写入
            config["skip_modules"] = merged_modules
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.dump(config, f, indent=4, sort_keys=False)

            # 更新内存中的配置
            self.config["skip_modules"] = merged_modules
            self.logger.info(
                "Saved skip modules to %s (merged %d existing with %d new)",
                self.config_file,
                len(existing_modules),
                len(new_modules),
            )
        except (yaml.YAMLError, OSError) as e:
            self.logger.error("Error saving skip modules: %s", str(e))

    def save_skip_source_files(self, source_files):
        """保存skip source files到符号配置文件"""
        skip_symbols_file = self.config.get("skip_symbols_file")
        if not skip_symbols_file:
            self.logger.warning("No skip symbols file specified")
            return

        try:
            # 创建或更新配置文件
            config = {"skip_source_files": source_files}
            with open(skip_symbols_file, "w", encoding="utf-8") as f:
                yaml.dump(config, f, indent=4, sort_keys=False)

            # 更新内存中的配置
            self.config["skip_source_files"] = source_files
            self.logger.info("Saved skip source files to %s: %d files", skip_symbols_file, len(source_files))
        except (yaml.YAMLError, OSError) as e:
            self.logger.error("Error saving skip source files: %s", str(e))

    def _validate_expression_hooks(self, hooks_config):
        """验证并清理 expression_hooks 配置"""
        if not isinstance(hooks_config, list):
            self.logger.error("Invalid expression_hooks config: must be a list")
            return []

        valid_hooks = []
        invalid_count = 0
        for i, hook in enumerate(hooks_config):
            if not isinstance(hook, dict):
                self.logger.error("Invalid expression_hooks[%d]: must be dict, got %s", i, type(hook))
                invalid_count += 1
                continue

            if "path" not in hook or not isinstance(hook["path"], str):
                self.logger.error("Invalid expression_hooks[%d]: missing or invalid 'path' field (must be string)", i)
                invalid_count += 1
                continue

            original_path = hook["path"]
            if not os.path.isabs(original_path):
                hook["path"] = os.path.abspath(original_path)
                self.logger.info(
                    "Converted expression_hooks[%d] path to absolute: %s -> %s", i, original_path, hook["path"]
                )

            if "line" not in hook or not isinstance(hook["line"], int):
                self.logger.error("Invalid expression_hooks[%d]: missing or invalid 'line' field (must be integer)", i)
                invalid_count += 1
                continue

            if "expr" not in hook or not isinstance(hook["expr"], str) or not hook["expr"].strip():
                self.logger.error(
                    "Invalid expression_hooks[%d]: missing or empty 'expr' field (must be non-empty string)", i
                )
                invalid_count += 1
                continue

            valid_hooks.append(hook)

        if invalid_count > 0:
            self.logger.warning(
                "Discarded %d invalid expression hooks, using %d valid entries", invalid_count, len(valid_hooks)
            )
        return valid_hooks

    def _validate_libc_functions(self, libc_funcs_config):
        """验证并清理 libc_functions 配置"""
        if not isinstance(libc_funcs_config, list):
            self.logger.error("Invalid libc_functions config: must be a list")
            return []
        # 确保所有条目都是字符串
        return [str(func) for func in libc_funcs_config if isinstance(func, (str, int, float))]

    def _validate_source_search_paths(self, paths_config):
        """验证并清理 source_search_paths 配置"""
        if not isinstance(paths_config, list):
            self.logger.error("Invalid source_search_paths config: must be a list")
            return []

        resolved_paths = []
        for path in paths_config:
            if not isinstance(path, str):
                self.logger.warning("Skipping invalid path in source_search_paths: %s", path)
                continue
            if not os.path.isabs(path):
                abs_path = os.path.abspath(path)
                self.logger.info("Converted source search path to absolute: %s -> %s", path, abs_path)
                resolved_paths.append(abs_path)
            else:
                resolved_paths.append(path)
        return resolved_paths

    def _validate_symbol_trace_patterns(self, patterns_config) -> List[SymbolTracePattern]:
        """验证并清理 symbol_trace_patterns 配置

        返回:
            SymbolTracePattern 对象列表
        """
        if not isinstance(patterns_config, list):
            self.logger.error("Invalid symbol_trace_patterns config: must be a list")
            return []

        valid_patterns = []
        for i, pattern in enumerate(patterns_config):
            if not isinstance(pattern, dict):
                self.logger.error("Invalid symbol_trace_patterns[%d]: must be dict, got %s", i, type(pattern))
                continue
            if "module" not in pattern or not isinstance(pattern["module"], str):
                self.logger.error(
                    "Invalid symbol_trace_patterns[%d]: missing or invalid 'module' field (must be string)", i
                )
                continue
            if "regex" not in pattern or not isinstance(pattern["regex"], str):
                self.logger.error(
                    "Invalid symbol_trace_patterns[%d]: missing or invalid 'regex' field (must be string)", i
                )
                continue
            # 创建强类型对象
            valid_patterns.append(SymbolTracePattern(module=pattern["module"], regex=pattern["regex"]))
        return valid_patterns

    def _validate_symbol_trace_cache_file(self, cache_file_config):
        """验证并清理 symbol_trace_cache_file 配置"""
        if cache_file_config is not None and not isinstance(cache_file_config, str):
            self.logger.error("Invalid symbol_trace_cache_file config: must be a string or None")
            return None
        return cache_file_config

    def _validate_source_base_dir(self, base_dir_config):
        """验证并清理 source_base_dir 配置"""
        if not isinstance(base_dir_config, str):
            self.logger.error("Invalid source_base_dir config: must be a string")
            return ""
        if base_dir_config and not os.path.isabs(base_dir_config):
            abs_path = os.path.abspath(base_dir_config)
            self.logger.info("Converted source_base_dir to absolute: %s -> %s", base_dir_config, abs_path)
            return abs_path
        return base_dir_config

    # ====== Symbol Trace Configuration Getters ======
    def is_symbol_trace_enabled(self) -> bool:
        """检查符号追踪是否启用"""
        return self.config.get("symbol_trace_enabled", False)

    def get_symbol_trace_patterns(self) -> List[SymbolTracePattern]:
        """获取符号追踪模式配置

        返回:
            SymbolTracePattern 对象列表
        """
        return self.config.get("symbol_trace_patterns", [])

    def get_symbol_trace_cache_file(self) -> Optional[str]:
        """获取符号追踪缓存文件路径"""
        return self.config.get("symbol_trace_cache_file")

    # ====== Other Configuration Getters ======
    def get_environment(self) -> Dict[str, str]:
        """获取环境变量字典"""
        return self.config.get("environment", {})

    def get_environment_list(self) -> List[str]:
        """获取环境变量列表（格式：["KEY=value", ...]）"""
        env_dict = self.get_environment()
        return [f"{key}={value}" for key, value in env_dict.items()]

    def get_attach_pid(self) -> Optional[int]:
        """获取附加PID配置"""
        return self.config.get("attach_pid")

    def get_expression_hooks(self) -> List[Dict[str, Any]]:
        """获取表达式钩子配置"""
        return self.config.get("expression_hooks", [])

    def get_libc_functions(self) -> List[str]:
        """获取要跟踪的libc函数列表"""
        return self.config.get("libc_functions", [])

    def get_source_search_paths(self) -> List[str]:
        """获取源代码搜索路径列表"""
        return self.config.get("source_search_paths", [])

    def get_call_trace_file(self) -> str:
        """获取调用跟踪文件路径"""
        return self.config.get("call_trace_file", "call_trace.txt")

    def get_log_mode(self) -> str:
        """获取日志模式配置"""
        value = self.config.get("log_mode", "instruction")
        assert value in ["source", "instruction"]
        return value

    def get_step_action(self) -> Dict[str, Any]:
        """获取步过操作配置"""
        value = self.config.get("step_action", {})
        for path, number_range in value.items():
            [a, b], action = number_range
            assert isinstance(a, int) and isinstance(b, int), f"Invalid step_over_action range: {number_range}"
            assert a <= b, f"Step over range start must be less than or equal to end: {number_range}"
            assert os.path.isabs(path), f"Path must be absolute: {path}"
        return value

    def get_source_base_dir(self) -> str:
        """获取源代码基础目录配置"""
        return self.config.get("source_base_dir", "")

    def should_show_console(self) -> bool:
        """检查是否应显示控制台"""
        return self.config.get("show_console", False)
