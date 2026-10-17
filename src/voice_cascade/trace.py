"""Append-only JSONL traces. Values are redacted before they hit disk."""

from __future__ import annotations

import json
from pathlib import Path

from voice_cascade.pii import redact_obj


def append_trace(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    redacted = redact_obj(record)
    line = json.dumps(redacted, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_traces(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed: object = json.loads(line)
        if isinstance(parsed, dict):
            rows.append({str(key): value for key, value in parsed.items()})
    return rows
