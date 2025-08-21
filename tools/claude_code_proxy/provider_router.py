from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import httpx

from .client import create_http_client
from .config_manager import AppConfig, ProviderConfig, config_manager
from .logger import get_logger
from .models_anthropic import AnthropicRequest

logger = get_logger("provider_router")


def estimate_context_length(request: AnthropicRequest) -> int:
    """
    Estimate the context length (in tokens) required for a request.
    Uses a simple approximation: string length divided by 4.
    """
    total_length = 0

    # Count messages content
    if request.messages:
        for message in request.messages:
            if hasattr(message, "content") and message.content:
                if isinstance(message.content, str):
                    total_length += len(message.content)
                elif isinstance(message.content, list):
                    for content_item in message.content:
                        if hasattr(content_item, "text") and content_item.text:
                            total_length += len(content_item.text)

    # Count system prompt if present
    if request.system:
        total_length += len(request.system)

    # Simple approximation: divide by 4 to estimate tokens
    return total_length // 4


class ProviderRouter:
    """
    Manages multiple provider clients and routing logic based on configuration.
    This class is a singleton managed by the application's lifespan.
    """

    def __init__(self) -> None:
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._config: Optional[AppConfig] = None
        self._name_to_key_map: Dict[str, str] = {}

    async def initialize(self, config: Optional[AppConfig] = None) -> None:
        """
        Initializes the router by loading configuration and creating HTTP clients
        for all configured providers.

        Args:
            config: Optional AppConfig to use instead of loading from config manager.
                   This is useful for testing with mock configurations.
        """
        if config is not None:
            self._config = config
        else:
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

    def _find_providers_with_sufficient_context(
        self, required_context: int, model_name: str
    ) -> List[Tuple[str, ProviderConfig]]:
        """
        Find all providers that support the required context length and model.
        Returns list of (provider_key, provider_config) tuples sorted by context capacity.
        """
        if not self._config:
            return []

        suitable_providers = []
        all_providers = self._config.openai_providers

        for key, provider in all_providers.items():
            # Check if provider supports the model
            if model_name not in provider.default_models and not provider.default_model:
                continue

            # Check if provider has sufficient context capacity
            if provider.max_context is None or provider.max_context >= required_context:
                suitable_providers.append((key, provider))

        # Sort by context capacity (ascending - smallest sufficient capacity first)
        suitable_providers.sort(key=lambda x: x[1].max_context or float("inf"))
        return suitable_providers

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
                # Check if reasoning provider has sufficient context capacity
                reasoning_provider_config = all_providers.get(reasoning_provider)
                if reasoning_provider_config:
                    required_context = estimate_context_length(request)
                    if (
                        reasoning_provider_config.max_context is None
                        or reasoning_provider_config.max_context >= required_context
                    ):
                        logger.info(
                            "Selected reasoning provider '%s' with sufficient context",
                            reasoning_provider_config.name,
                            extra=log_extra,
                        )
                        return reasoning_provider
                    else:
                        logger.warning(
                            "Reasoning provider '%s' lacks sufficient context (%d < %d tokens). Falling back to standard routing.",
                            reasoning_provider_config.name,
                            reasoning_provider_config.max_context or 0,
                            required_context,
                            extra=log_extra,
                        )

            logger.warning("No reasoning-capable provider found. Falling back to standard routing.", extra=log_extra)

        # --- Step 2: Standard routing ---
        # Priority 1: Specific model mapping
        specific_key = anthropic_cfg.model_providers.get(model_name)
        if specific_key and specific_key in all_providers:
            specific_provider = all_providers[specific_key]
            required_context = estimate_context_length(request)

            if specific_provider.max_context is None or specific_provider.max_context >= required_context:
                logger.info(
                    "Selected provider '%s' via specific model mapping", specific_provider.name, extra=log_extra
                )
                return specific_key
            else:
                logger.warning(
                    "Specific provider '%s' lacks sufficient context (%d < %d tokens). Continuing search...",
                    specific_provider.name,
                    specific_provider.max_context or 0,
                    required_context,
                    extra=log_extra,
                )

        # Priority 2: Default provider
        default_key = anthropic_cfg.default_provider
        if default_key in all_providers:
            # Check if default provider has sufficient context capacity
            default_provider = all_providers[default_key]
            required_context = estimate_context_length(request)

            if default_provider.max_context is None or default_provider.max_context >= required_context:
                logger.info("Selected provider '%s' via default setting", default_provider.name, extra=log_extra)
                return default_key
            else:
                logger.warning(
                    "Default provider '%s' lacks sufficient context (%d < %d tokens). Searching alternatives...",
                    default_provider.name,
                    default_provider.max_context or 0,
                    required_context,
                    extra=log_extra,
                )

        # --- Step 3: Context-aware routing ---
        required_context = estimate_context_length(request)
        suitable_providers = self._find_providers_with_sufficient_context(required_context, model_name)

        if suitable_providers:
            # Select the provider with the smallest sufficient context capacity
            selected_key, selected_provider = suitable_providers[0]
            logger.info(
                "Selected provider '%s' with sufficient context (%s >= %d tokens)",
                selected_provider.name,
                "unlimited" if selected_provider.max_context is None else str(selected_provider.max_context),
                required_context,
                extra=log_extra,
            )
            return selected_key

        logger.error(
            "Could not determine a provider. Neither a specific mapping nor a default provider "
            "is configured correctly or found, or no provider has sufficient context capacity.",
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
