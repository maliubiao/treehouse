from __future__ import annotations

import pydantic_settings


class Settings(pydantic_settings.BaseSettings):
    """Manages application settings using environment variables."""

    model_config = pydantic_settings.SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    OPENAI_API_BASE: str = "https://api.openai.com/v1"
    OPENAI_API_KEY: str = "your_api_key_here"

    # Logging configuration
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    LOG_REQUEST_BODY: bool = True
    LOG_RESPONSE_BODY: bool = True
    LOG_SENSITIVE_DATA: bool = False  # Set to True to log API keys, etc.


settings = Settings()
