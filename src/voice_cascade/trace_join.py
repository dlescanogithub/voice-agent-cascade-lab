"""Join log lines for one turn. Used by ``python -m voice_cascade trace``."""

from __future__ import annotations

import json
from pathlib import Path


def _rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    found: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed: object = json.loads(line)
        if isinstance(parsed, dict):
            found.append({str(key): value for key, value in parsed.items()})
    return found


def _turn_of(row: dict[str, object]) -> str:
    direct = row.get("turn_id")
    if isinstance(direct, str):
        return direct
    fields = row.get("fields")
    if isinstance(fields, dict):
        nested = fields.get("turn_id")
        if isinstance(nested, str):
            return nested
    return ""


def format_turn(turn_id: str, log_path: Path, trace_path: Path | None = None) -> str:
    rows: list[dict[str, object]] = []
    for row in _rows(log_path):
        if _turn_of(row) == turn_id:
            rows.append(row)
    if trace_path is not None:
        for row in _rows(trace_path):
            if _turn_of(row) == turn_id or row.get("scenario_id") == turn_id:
                rows.append(row)
    if not rows:
        return f"no events for turn {turn_id}\n"
    lines = [f"turn {turn_id} events={len(rows)} provenance=SIMULATED"]
    for row in rows:
        event = row.get("event", "")
        error_class = row.get("error_class", "")
        fields = row.get("fields")
        if not error_class and isinstance(fields, dict):
            error_class = str(fields.get("error_class", ""))
            if not event:
                event = str(fields.get("event", ""))
        attempt = row.get("attempt", "")
        lines.append(
            f"event={event} error_class={error_class} attempt={attempt} call_id={row.get('call_id', '')}"
        )
    return "\n".join(lines) + "\n"
