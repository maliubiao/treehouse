import logging
import os
import threading
import time

import yaml


class ConfigManager:
    def __init__(self, config_file=None, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.config = {
            "max_steps": 100,
            "enable_jit": False,
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
            "attach_pid": None,
            "forward_stdin": True,
        }
        self.config_file = config_file
        if config_file:
            self._load_config(config_file)
            self.config_watcher = threading.Thread(target=self._watch_config, daemon=True)
            self.config_watcher.start()
        else:
            self.config_file = "tracer_config.yaml"
        # 加载符号配置文件
        self._load_skip_symbols()

    def _load_config(self, filepath):
        with open(filepath, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            self.config.update(config)
            self.logger.info("Loaded config from %s: %s", filepath, config)

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

    def get_environment(self):
        """获取环境变量字典"""
        return self.config.get("environment", {})

    def get_environment_list(self):
        """获取环境变量列表（格式：["KEY=value", ...]）"""
        env_dict = self.get_environment()
        return [f"{key}={value}" for key, value in env_dict.items()]

    def get_attach_pid(self):
        """获取附加PID配置"""
        return self.config.get("attach_pid")
