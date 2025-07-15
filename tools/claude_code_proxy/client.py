from __future__ import annotations

import httpx

from .config_manager import ProviderConfig


def create_http_client(provider: ProviderConfig) -> httpx.AsyncClient:
    """
    Creates an asynchronous HTTP client for a given provider configuration.

    Args:
        provider: The provider configuration object.

    Returns:
        An configured httpx.AsyncClient instance.
    """
    headers = provider.extra_headers.copy()

    # Set Authorization header if an API key is provided.
    # Some providers might not require it (e.g., local Ollama).
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"

    return httpx.AsyncClient(
        base_url=provider.base_url,
        headers=headers,
        timeout=provider.timeout,
    )
