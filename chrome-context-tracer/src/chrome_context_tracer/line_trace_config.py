#!/usr/bin/env python3
"""
Configuration loader for the line-by-line tracing feature.
"""

import dataclasses
from typing import List

import yaml

from .i18n import _


@dataclasses.dataclass
class LineTraceConfig:
    """
    Configuration for the line-by-line tracing feature.

    Attributes:
        blacklist_patterns: A list of URL regex patterns. Scripts whose URL matches
                            one of these patterns will be "blackboxed", and the
                            debugger will not step into them.
    """

    blacklist_patterns: List[str] = dataclasses.field(default_factory=list)


def load_config(path: str) -> LineTraceConfig:
    """
    Loads and parses the line trace configuration from a YAML file.

    Args:
        path: The path to the YAML configuration file.

    Returns:
        A LineTraceConfig object.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config file is not in the expected format.
        yaml.YAMLError: If the YAML file is malformed.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        if config_data is None:
            config_data = {}

        if not isinstance(config_data, dict):
            raise ValueError(_("Config file content must be a dictionary (key-value mapping)."))

        patterns = config_data.get("blacklist_patterns", [])
        if not isinstance(patterns, list):
            raise ValueError(_("'blacklist_patterns' must be a list of strings."))

        return LineTraceConfig(blacklist_patterns=patterns)
    except FileNotFoundError:
        print(_("❌ Error: Line trace config file not found at {path}", path=path))
        raise
    except yaml.YAMLError as e:
        print(_("❌ Error parsing YAML config file {path}: {e}", path=path, e=e))
        raise
    except ValueError as e:
        print(_("❌ Error in config file format: {e}", e=e))
        raise
