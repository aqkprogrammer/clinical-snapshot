"""Structured logging.

One rule governs this module: **no protected health information reaches a log
line.** Logs record which patient *id* was requested and how many resources
were classified, never a name, an identifier value, a date of birth, or a
clinical code. Resource bodies are never logged at any level.

Output is line-delimited JSON so it is greppable in development and ingestible
by a log pipeline in production without a second format.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

LOGGER_NAME = "clinical_snapshot"

# Keys that must never appear in a log record's extra fields, as a backstop
# against a future caller passing something careless.
_FORBIDDEN_KEYS = frozenset(
    {"name", "birthdate", "birth_date", "ssn", "identifier", "address", "telecom", "resource"}
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "context", {}).items():
            if key.lower() in _FORBIDDEN_KEYS:
                continue
            payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level.upper())
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_event(level: int, message: str, **context: Any) -> None:
    """Emit a structured event. Context keys are filtered by the formatter."""
    get_logger().log(level, message, extra={"context": context})
