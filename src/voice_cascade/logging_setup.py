"""One JSON object per log line, with PII redaction applied first."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

from voice_cascade.pii import redact_obj, redact_text

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "fields", None)
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "event": getattr(record, "event", ""),
        }
        if isinstance(fields, Mapping):
            redacted = redact_obj(dict(fields))
            if isinstance(redacted, dict):
                clean = {str(key): value for key, value in redacted.items()}
                payload["fields"] = clean
                for key in (
                    "call_id",
                    "turn_id",
                    "span_id",
                    "provenance",
                    "tool",
                    "attempt",
                    "error_class",
                    "idempotency_key_hash",
                ):
                    if key in clean:
                        payload[key] = clean[key]
        payload["ts"] = payload["timestamp"]
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("voice_cascade")
    logger.setLevel(level.upper())
    if not _CONFIGURED:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        _CONFIGURED = True
    return logger


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def log_event(
    logger: logging.Logger,
    event: str,
    message: str,
    fields: Mapping[str, object] | None = None,
    level: int = logging.INFO,
) -> None:
    logger.log(level, message, extra={"event": event, "fields": dict(fields or {})})
