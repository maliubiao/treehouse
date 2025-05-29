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
        }
        self.config_file = config_file
        if config_file:
            self._load_config(config_file)
            self.config_watcher = threading.Thread(target=self._watch_config, daemon=True)
            self.config_watcher.start()
        else:
            self.config_file = "tracer_config.yaml"

    def _load_config(self, filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                config = yaml.safe_load(f)
                self.config.update(config)
                self.logger.info("Loaded config from %s: %s", filepath, config)
        except (yaml.YAMLError, OSError) as e:
            self.logger.error("Error loading config file %s: %s", filepath, str(e))

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
