from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

from .logger import get_logger

logger = get_logger("config_manager")


class ProviderConfig(BaseModel):
    """Configuration for a single OpenAI-compatible provider."""

    name: str
    type: str = "openai"
    base_url: str
    api_key: str = ""
    timeout: float = 600.0
    default_models: Dict[str, str] = Field(default_factory=dict)
    default_model: Optional[str] = Field(
        default=None, description="Fallback model to use when no specific mapping exists"
    )
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    supports_reasoning: bool = False
    reasoning_config: Dict[str, Any] = Field(default_factory=dict)
    max_tokens_override: Optional[int] = Field(
        default=None, description="Override max_tokens if request value exceeds this limit"
    )


class AnthropicConfig(BaseModel):
    """Configuration for routing Anthropic models."""

    name: str = "Anthropic"
    default_provider: str
    model_providers: Dict[str, str] = Field(default_factory=dict)


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    dir: str = "logs"
    sse_debug: bool = False
    sse_debug_dir: str = "logs/sse_debug"


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = "127.0.0.1"
    port: int = 8083
    reload: bool = False


class AppConfig(BaseModel):
    """Main application configuration model."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    providers: Dict[str, Any] = Field(default_factory=dict)

    @property
    def anthropic_config(self) -> Optional[AnthropicConfig]:
        """Get the parsed Anthropic routing configuration."""
        if "anthropic" in self.providers:
            try:
                return AnthropicConfig(**self.providers["anthropic"])
            except ValidationError as e:
                logger.error("Invalid 'anthropic' provider config: %s", e)
                return None
        return None

    @property
    def openai_providers(self) -> Dict[str, ProviderConfig]:
        """Get all parsed OpenAI-compatible provider configurations."""
        providers: Dict[str, ProviderConfig] = {}
        if "openai_providers" in self.providers:
            for name, config in self.providers["openai_providers"].items():
                try:
                    providers[name] = ProviderConfig(**config)
                except ValidationError as e:
                    logger.error("Invalid config for provider '%s': %s", name, e)
        return providers

    def get_model_mapping(self, provider_key: str, anthropic_model: str) -> str:
        """获取目标模型名，强制映射且必须有结果"""
        provider = self.openai_providers.get(provider_key)
        if not provider:
            raise ValueError(f"Provider '{provider_key}' not found")

        # 优先使用特定模型映射
        if anthropic_model in provider.default_models:
            return provider.default_models[anthropic_model]

        if provider.default_model:
            return provider.default_model

        raise ValueError(
            f"No model mapping for '{anthropic_model}' on provider '{provider.name}' and no default_model configured"
        )


class ConfigManager:
    """Manages loading, parsing, and accessing application configuration."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._find_config_file()
        self._config: Optional[AppConfig] = None
        if self.config_path:
            logger.info("Using configuration file: %s", self.config_path)
        else:
            logger.warning("No config.yml found, using default settings.")

    def _find_config_file(self) -> Optional[str]:
        """Search for the config file in standard locations."""
        search_paths = [
            "config.yml",
            "claude_code_proxy/config.yml",
            os.path.expanduser("~/.config/claude_proxy/config.yml"),
        ]
        for path in search_paths:
            if os.path.exists(path):
                return path
        return None

    def load_config(self, reload: bool = False) -> AppConfig:
        """Load configuration from the YAML file."""
        if self._config is not None and not reload:
            return self._config

        config_data = {}
        if self.config_path and os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config_data = yaml.safe_load(f) or {}
            except (yaml.YAMLError, IOError) as e:
                logger.error("Failed to load or parse %s: %s", self.config_path, e)

        try:
            self._config = AppConfig(**config_data)
        except ValidationError as e:
            logger.error("Configuration validation failed: %s", e)
            # Fallback to a default config to prevent crashing
            self._config = AppConfig()

        return self._config


# Global instance of the config manager
config_manager = ConfigManager()
