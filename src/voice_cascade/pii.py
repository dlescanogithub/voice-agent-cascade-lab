"""Redact synthetic phones and names before anything is logged."""

from __future__ import annotations

import contextvars
import re
from collections.abc import Mapping

PHONE_RE = re.compile(r"(?<!\w)(?:\+\d{10,15}|\d{2,4}[\s-]\d{3,4}[\s-]\d{3,4})(?!\w)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SENSITIVE_KEYS = frozenset(
    {"phone", "patient_name", "name", "caller_name", "email", "patient_phone"}
)

_denylist: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "pii_denylist",
    default=(),
)


def reset_denylist() -> None:
    _denylist.set(())


def add_sensitive(terms: list[str]) -> None:
    current = list(_denylist.get())
    for term in terms:
        cleaned = term.strip()
        if len(cleaned) >= 3 and cleaned not in current:
            current.append(cleaned)
        for part in cleaned.split():
            if len(part) >= 3 and part not in current:
                current.append(part)
    _denylist.set(tuple(current))


def redact_text(text: str) -> str:
    text = PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    for term in sorted(_denylist.get(), key=len, reverse=True):
        text = re.sub(
            rf"\b{re.escape(term)}\b",
            "[REDACTED_NAME]",
            text,
            flags=re.IGNORECASE,
        )
    return text


def redact_obj(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            if str(key) in SENSITIVE_KEYS:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_obj(item)
        return redacted
    return value


def contains_raw_pii(text: str, names: list[str], phones: list[str]) -> str | None:
    for phone in phones:
        if phone and phone in text:
            return phone
    for name in names:
        for part in [name, *name.split()]:
            if len(part) >= 3 and re.search(rf"\b{re.escape(part)}\b", text, flags=re.IGNORECASE):
                return part
    return None


def mapping_text(payload: Mapping[str, object]) -> str:
    return redact_text(repr(dict(payload)))
