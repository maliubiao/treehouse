import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class SymbolTracePattern:
    """Represents a configuration for tracing symbols matching a pattern."""

    module: str
    regex: str


class ConfigManager:
    """
    Manages loading, validation, and access to the tracer's configuration.
    """

    def __init__(self, config_file: Optional[str] = None, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.config_file = config_file or "tracer_config.yaml"

        # Default configuration values
        self.config = {
            "max_steps": 100,
            "log_mode": "instruction",  # "instruction" or "source"
            "log_target_info": True,
            "log_module_info": True,
            "log_breakpoint_details": True,
            "source_base_dir": "",
            "skip_modules": [],
            "skip_source_files": [],
            "source_search_paths": [],
            "dump_modules_for_skip": False,
            "dump_source_files_for_skip": False,
            "skip_symbols_file": "skip_symbols.yaml",
            "attach_pid": None,
            "forward_stdin": True,
            "expression_hooks": [],
            "libc_functions": [],
            "show_console": False,
            # Symbol Tracing
            "symbol_trace_enabled": False,
            "symbol_trace_patterns": [],
            "symbol_trace_cache_file": "symbol_trace_cache.json",
        }

        self._load_config()
        self._load_skip_symbols()

    def _load_config(self):
        """Loads the main YAML configuration file."""
        if not os.path.exists(self.config_file):
            self.logger.warning("Config file '%s' not found. Using default settings.", self.config_file)
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                loaded_config = yaml.safe_load(f)
            if loaded_config:
                self.config.update(loaded_config)
                self.logger.info("Loaded config from '%s'.", self.config_file)

            # Validate and normalize loaded configuration values
            self._validate_config()

        except (yaml.YAMLError, OSError) as e:
            self.logger.error("Error loading config file '%s': %s", self.config_file, e)

    def _load_skip_symbols(self):
        """Loads additional skip patterns from a separate symbols file."""
        skip_file = self.get_skip_symbols_file()
        if not skip_file or not os.path.exists(skip_file):
            return

        try:
            with open(skip_file, "r", encoding="utf-8") as f:
                skip_config = yaml.safe_load(f) or {}

            # Merge skip lists, avoiding duplicates
            if "skip_source_files" in skip_config:
                existing = set(self.get_skip_source_files())
                new = set(skip_config["skip_source_files"])
                self.config["skip_source_files"] = sorted(list(existing.union(new)))

            self.logger.info("Loaded and merged skip patterns from '%s'.", skip_file)
        except (yaml.YAMLError, OSError) as e:
            self.logger.error("Error loading skip symbols file '%s': %s", skip_file, e)

    def _validate_config(self):
        """Validates and normalizes the configuration dictionary."""
        self.config["symbol_trace_patterns"] = self._validate_symbol_trace_patterns(
            self.config.get("symbol_trace_patterns", [])
        )
        self.config["source_base_dir"] = self._validate_source_base_dir(self.config.get("source_base_dir", ""))
        self.config["expression_hooks"] = self._validate_expression_hooks(self.config.get("expression_hooks", []))

    def _validate_symbol_trace_patterns(self, patterns_config) -> List[SymbolTracePattern]:
        """Validates the structure of symbol trace patterns."""
        if not isinstance(patterns_config, list):
            self.logger.error("'symbol_trace_patterns' must be a list. Ignoring.")
            return []

        valid_patterns = []
        for item in patterns_config:
            if isinstance(item, dict) and "module" in item and "regex" in item:
                valid_patterns.append(SymbolTracePattern(module=item["module"], regex=item["regex"]))
            else:
                self.logger.warning("Skipping invalid symbol_trace_pattern item: %s", item)
        return valid_patterns

    def _validate_source_base_dir(self, path: str) -> str:
        """Ensures the source_base_dir is an absolute path."""
        if path and not os.path.isabs(path):
            abs_path = os.path.abspath(path)
            self.logger.info("Converted relative source_base_dir '%s' to absolute path '%s'.", path, abs_path)
            return abs_path
        return path

    def _validate_expression_hooks(self, hooks_config: List[Any]) -> List[Dict[str, Any]]:
        """Validates and normalizes the expression_hooks configuration."""
        if not isinstance(hooks_config, list):
            self.logger.error("'expression_hooks' must be a list. Ignoring.")
            return []

        valid_hooks = []
        for item in hooks_config:
            if not isinstance(item, dict):
                self.logger.error("Skipping invalid expression_hook item (not a dict): %s", item)
                continue

            # Check for required keys
            if not all(k in item for k in ["path", "line", "expr"]):
                self.logger.error("Skipping invalid expression_hook (missing 'path', 'line', or 'expr'): %s", item)
                continue

            # Check path type
            if not isinstance(item["path"], str):
                self.logger.error("Skipping invalid expression_hook ('path' must be a string): %s", item)
                continue

            # Create a copy to avoid modifying the original config dict in place
            hook = item.copy()

            # Normalize path to be absolute
            if not os.path.isabs(hook["path"]):
                abs_path = os.path.abspath(hook["path"])
                self.logger.debug("Converted relative hook path '%s' to absolute path '%s'.", hook["path"], abs_path)
                hook["path"] = abs_path

            valid_hooks.append(hook)
        return valid_hooks

    # --- Public Getters for Configuration Values ---

    def get_log_mode(self) -> str:
        return self.config.get("log_mode", "instruction")

    def get_step_action(self) -> Dict[str, Any]:
        return self.config.get("step_action", {})

    def get_source_base_dir(self) -> str:
        return self.config.get("source_base_dir", "")

    def get_skip_modules(self) -> List[str]:
        return self.config.get("skip_modules", [])

    def get_skip_source_files(self) -> List[str]:
        return self.config.get("skip_source_files", [])

    def get_skip_symbols_file(self) -> str:
        return self.config.get("skip_symbols_file", "")

    def get_source_search_paths(self) -> List[str]:
        return self.config.get("source_search_paths", [])

    def get_attach_pid(self) -> Optional[int]:
        return self.config.get("attach_pid")

    def get_libc_functions(self) -> List[str]:
        return self.config.get("libc_functions", [])

    def should_show_console(self) -> bool:
        return self.config.get("show_console", False)

    # --- Symbol Trace Getters ---

    def is_symbol_trace_enabled(self) -> bool:
        return self.config.get("symbol_trace_enabled", False)

    def get_symbol_trace_patterns(self) -> List[SymbolTracePattern]:
        return self.config.get("symbol_trace_patterns", [])

    def get_symbol_trace_cache_file(self) -> Optional[str]:
        return self.config.get("symbol_trace_cache_file")

    def get_environment_list(self) -> List[str]:
        """Gets environment variables as a list of 'KEY=VALUE' strings."""
        env_dict = self.config.get("environment", {})
        if not isinstance(env_dict, dict):
            return []
        return [f"{key}={value}" for key, value in env_dict.items()]

    # --- Methods to Save Configuration ---

    def save_skip_modules(self, modules_to_skip: List[str]):
        """Saves a list of modules to skip to the main config file."""
        if not self.config_file:
            self.logger.error("Cannot save skip modules: no config file path specified.")
            return

        try:
            config = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}

            # Merge new modules with existing ones, avoiding duplicates
            existing_modules = set(config.get("skip_modules", []))
            new_modules = set(modules_to_skip)
            config["skip_modules"] = sorted(list(existing_modules.union(new_modules)))

            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.dump(config, f, indent=2, sort_keys=False)

            # Update in-memory config
            self.config["skip_modules"] = config["skip_modules"]
            self.logger.info("Saved %d skip module patterns to '%s'.", len(config["skip_modules"]), self.config_file)

        except (yaml.YAMLError, OSError) as e:
            self.logger.error("Error saving skip modules to '%s': %s", self.config_file, e)
