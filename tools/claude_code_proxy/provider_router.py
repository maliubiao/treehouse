from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import httpx

from .client import create_http_client
from .config_manager import AppConfig, ProviderConfig, config_manager
from .logger import get_logger
from .models_anthropic import AnthropicRequest

logger = get_logger("provider_router")


class ProviderRouter:
    """
    Manages multiple provider clients and routing logic based on configuration.
    This class is a singleton managed by the application's lifespan.
    """

    def __init__(self) -> None:
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._config: Optional[AppConfig] = None
        self._name_to_key_map: Dict[str, str] = {}

    async def initialize(self) -> None:
        """
        Initializes the router by loading configuration and creating HTTP clients
        for all configured providers.
        """
        self._config = config_manager.load_config(reload=True)
        if not self._config:
            logger.critical("Failed to load application configuration. Router is disabled.")
            return

        self._name_to_key_map.clear()
        for key, provider in self._config.openai_providers.items():
            logger.info("Initializing client for provider: %s (%s)", provider.name, key)
            self._clients[key] = create_http_client(provider)
            self._name_to_key_map[provider.name] = key

        logger.info("Initialized %s provider clients.", len(self._clients))

    def _find_reasoning_provider(self, model_name: str) -> Optional[str]:
        """Finds the best reasoning-capable provider for the given model."""
        if not self._config or not self._config.anthropic_config:
            return None

        anthropic_cfg = self._config.anthropic_config
        all_providers = self._config.openai_providers
        log_extra = {"model": model_name, "context": "reasoning_provider_search"}

        # 1. Check specific model mapping for reasoning provider
        specific_provider_key = anthropic_cfg.model_providers.get(model_name)
        if specific_provider_key:
            provider = all_providers.get(specific_provider_key)
            if provider and provider.supports_reasoning:
                logger.info(
                    "Selected reasoning provider '%s' via specific model mapping", provider.name, extra=log_extra
                )
                return specific_provider_key

        # 2. Check default provider for reasoning support
        default_provider_key = anthropic_cfg.default_provider
        provider = all_providers.get(default_provider_key)
        if provider and provider.supports_reasoning:
            logger.info("Selected reasoning provider '%s' via default setting", provider.name, extra=log_extra)
            return default_provider_key

        # 3. Search all providers for reasoning support
        reasoning_providers = [(key, prov) for key, prov in all_providers.items() if prov.supports_reasoning]

        if reasoning_providers:
            # Prioritize providers that have the model in their mapping
            for key, provider in reasoning_providers:
                if model_name in provider.default_models:
                    logger.info("Selected reasoning provider '%s' with model mapping", provider.name, extra=log_extra)
                    return key

            # Fallback to first reasoning provider
            key, provider = reasoning_providers[0]
            logger.info("Selected reasoning provider '%s' (first available)", provider.name, extra=log_extra)
            return key

        return None

    def route_request(self, request: AnthropicRequest) -> Optional[str]:
        """
        Determines the correct provider key for a given Anthropic request,
        prioritizing providers that support reasoning if requested.
        """
        if not self._config or not self._config.anthropic_config:
            logger.error("Router not initialized or Anthropic config missing.")
            return None

        model_name = request.model
        thinking_requested = request.thinking and request.thinking.type == "enabled"
        anthropic_cfg = self._config.anthropic_config
        all_providers = self._config.openai_providers
        log_extra = {"model": model_name, "thinking_requested": thinking_requested}

        # --- Step 1: Prioritize reasoning-capable providers if thinking is requested ---
        if thinking_requested:
            logger.info("Reasoning requested. Searching for reasoning-capable providers...", extra=log_extra)

            reasoning_provider = self._find_reasoning_provider(model_name)
            if reasoning_provider:
                return reasoning_provider

            logger.warning("No reasoning-capable provider found. Falling back to standard routing.", extra=log_extra)

        # --- Step 2: Standard routing ---
        # Priority 1: Specific model mapping
        specific_key = anthropic_cfg.model_providers.get(model_name)
        if specific_key and specific_key in all_providers:
            logger.info(
                "Selected provider '%s' via specific model mapping", all_providers[specific_key].name, extra=log_extra
            )
            return specific_key

        # Priority 2: Default provider
        default_key = anthropic_cfg.default_provider
        if default_key in all_providers:
            logger.info("Selected provider '%s' via default setting", all_providers[default_key].name, extra=log_extra)
            return default_key

        logger.error(
            "Could not determine a provider. Neither a specific mapping nor a default provider "
            "is configured correctly or found.",
            extra=log_extra,
        )
        return None

    def get_target_model(self, anthropic_model: str, provider_key: str) -> str:
        """获取目标模型名，禁止使用原始Anthropic模型名"""
        if not self._config:
            return "INVALID_CONFIG_ERROR"
        try:
            target_model = self._config.get_model_mapping(provider_key, anthropic_model)
            return target_model
        except ValueError as e:
            logger.error("Model mapping error for provider '%s': %s", provider_key, str(e))
            return "INVALID_MODEL_MAPPING_ERROR"

    def get_client(self, provider_key: str) -> Optional[httpx.AsyncClient]:
        """Retrieves the pre-configured HTTP client for a given provider key."""
        return self._clients.get(provider_key)

    def get_provider_by_name(self, provider_name: str) -> Optional[str]:
        """Retrieves provider key by provider name."""
        return self._name_to_key_map.get(provider_name)

    def get_provider_by_key(self, provider_key: str) -> Optional[ProviderConfig]:
        """Retrieves provider configuration by its key."""
        if not self._config:
            return None
        return self._config.openai_providers.get(provider_key)

    async def cleanup(self) -> None:
        """Closes all active HTTP clients gracefully."""
        logger.info("Closing %s provider clients...", len(self._clients))
        for client in self._clients.values():
            if not client.is_closed:
                await client.aclose()
        self._clients.clear()
        logger.info("All provider clients closed.")

    def get_all_providers(self) -> Dict[str, ProviderConfig]:
        """Returns all configured OpenAI providers."""
        if not self._config:
            return {}
        return self._config.openai_providers


# Global instance of the provider router
provider_router = ProviderRouter()
