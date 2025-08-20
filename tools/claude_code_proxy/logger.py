from __future__ import annotations

import json
import logging
import logging.config
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Dict

from fastapi import Request


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging in files."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # Add any extra fields from the log record
        extra_fields = {
            key: val
            for key, val in record.__dict__.items()
            if key not in logging.LogRecord.__dict__ and key not in log_entry
        }
        if extra_fields:
            log_entry["extra"] = extra_fields

        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    """Configure logging for the application using dictConfig."""
    from .config_manager import config_manager

    config = config_manager.load_config()

    log_dir = config.logging.dir
    log_level = config.logging.level.upper()
    log_file = os.path.join(log_dir, "anthropic_proxy.log")

    os.makedirs(log_dir, exist_ok=True)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": JSONFormatter},
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "standard",
                "stream": sys.stdout,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",
                "formatter": "json",
                "filename": log_file,
                "maxBytes": 10 * 1024 * 1024,  # 10MB
                "backupCount": 5,
                "encoding": "utf8",
            },
        },
        "loggers": {
            "anthropic_proxy": {
                "level": "DEBUG",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn": {"handlers": ["console"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False},
        },
        "root": {"level": "INFO", "handlers": ["console"]},
    }

    logging.config.dictConfig(logging_config)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module."""
    return logging.getLogger(f"anthropic_proxy.{name}")


class RequestLogger:
    """Helper class for consistent, structured logging of request lifecycles."""

    def __init__(self, logger: logging.Logger):
        self.log = logger
        # Determine from config if bodies should be logged
        self.log_bodies = os.getenv("LOG_REQUEST_BODY", "true").lower() == "true"

    def log_request_received(self, request_id: str, request: Request, body: Dict[str, Any]) -> None:
        extra = {
            "request_id": request_id,
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "anthropic_request": body if self.log_bodies else {"model": body.get("model")},
        }
        self.log.info(f"Request {request_id} received", extra=extra)

    def log_request_translated(self, request_id: str, translation_info: str, openai_body: Dict[str, Any]) -> None:
        extra = {
            "request_id": request_id,
            "translation_info": translation_info,
            "openai_request": openai_body if self.log_bodies else {"model": openai_body.get("model")},
        }
        self.log.info(f"Request {request_id} translated", extra=extra)

    def log_response_received(self, request_id: str, provider: str, response: Dict[str, Any]) -> None:
        extra = {
            "request_id": request_id,
            "provider": provider,
            "openai_response": response if self.log_bodies else {"id": response.get("id")},
        }
        self.log.debug(f"Request {request_id} received response from {provider}", extra=extra)

    def log_response_translated(self, request_id: str, anthropic_response: Dict[str, Any]) -> None:
        extra = {
            "request_id": request_id,
            "anthropic_response": anthropic_response if self.log_bodies else {"id": anthropic_response.get("id")},
        }
        self.log.info(f"Request {request_id} response translated", extra=extra)

    def log_error(self, request_id: str, error: Exception, context: Dict[str, Any]) -> None:
        import traceback

        # 获取完整的堆栈跟踪信息
        stack_trace = traceback.format_exc()
        if not stack_trace or stack_trace == "None\n":
            # 如果没有异常堆栈，获取当前调用堆栈
            stack_trace = "".join(traceback.format_stack())

        extra = {
            "request_id": request_id,
            "error": str(error),
            "error_type": error.__class__.__name__,
            "stack_trace": stack_trace,
            "context": context,
        }
        self.log.error(f"Error processing request {request_id}: {error}\nStack trace: {stack_trace}", extra=extra)

    def log_model_mapping(
        self, request_id: str, anthropic_model: str, target_model: str, provider_key: str, provider_name: str
    ) -> None:
        """Log model mapping information."""
        extra = {
            "request_id": request_id,
            "anthropic_model": anthropic_model,
            "target_model": target_model,
            "provider_key": provider_key,
            "provider_name": provider_name,
        }
        self.log.info(
            f"Model mapping for request {request_id}: "
            f"'{anthropic_model}' → '{target_model}' via '{provider_name}' ({provider_key})",
            extra=extra,
        )


class SSEDebugLogger:
    """Debug logger for SSE events - stores original and translated events in pairs."""

    def __init__(self, debug_dir: str = "logs/sse_debug", enabled: bool = True):
        self.enabled = enabled
        self.debug_dir = Path(debug_dir)
        if self.enabled:
            self.debug_dir.mkdir(parents=True, exist_ok=True)

    def _get_request_dir(self, request_id: str) -> Path:
        """Get the directory for a specific request."""
        date_dir = datetime.now().strftime("%Y-%m-%d")
        request_dir = self.debug_dir / date_dir / request_id
        if self.enabled:
            request_dir.mkdir(parents=True, exist_ok=True)
        return request_dir

    def log_raw_sse(self, request_id: str, event_type: str, data: str):
        """Log raw SSE events from provider."""
        if not self.enabled:
            return

        request_dir = self._get_request_dir(request_id)
        raw_file = request_dir / "raw_events.log"

        with open(raw_file, "a", encoding="utf-8") as f:
            entry = {"timestamp": datetime.utcnow().isoformat(), "event_type": event_type, "data": data}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_translated_sse(self, request_id: str, event_type: str, data: dict):
        """Log translated SSE events (anthropic format)."""
        if not self.enabled:
            return

        request_dir = self._get_request_dir(request_id)
        translated_file = request_dir / "translated_events.log"

        with open(translated_file, "a", encoding="utf-8") as f:
            entry = {"timestamp": datetime.utcnow().isoformat(), "event_type": event_type, "data": data}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def start_batch(self, request_id: str, metadata: dict):
        """Start recording a new SSE batch with metadata."""
        if not self.enabled:
            return

        request_dir = self._get_request_dir(request_id)
        metadata_file = request_dir / "metadata.json"

        with open(metadata_file, "w", encoding="utf-8") as f:
            metadata.update({"request_id": request_id, "started_at": datetime.utcnow().isoformat(), "status": "active"})
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def finish_batch(self, request_id: str, summary: dict):
        """Mark batch as complete with summary."""
        if not self.enabled:
            return

        request_dir = self._get_request_dir(request_id)
        metadata_file = request_dir / "metadata.json"

        if metadata_file.exists():
            with open(metadata_file, "r+", encoding="utf-8") as f:
                metadata = json.load(f)
                metadata.update(
                    {"finished_at": datetime.utcnow().isoformat(), "status": "complete", "summary": summary}
                )
                f.seek(0)
                json.dump(metadata, f, indent=2, ensure_ascii=False)
                f.truncate()

    def get_debug_dirs(self, date_str: str = None) -> list[Path]:
        """Get list of debug directories for a given date."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        date_dir = self.debug_dir / date_str
        if not date_dir.exists():
            return []

        return [d for d in date_dir.iterdir() if d.is_dir()]
