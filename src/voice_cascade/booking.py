"""SQLite appointment book for the fictional Clínica Aurora. Scheduling only."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected an integer column")
    return value


class BookingStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS slots (
                slot_id TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                service TEXT NOT NULL,
                free INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bookings (
                booking_id TEXT PRIMARY KEY,
                slot_id TEXT NOT NULL,
                patient_ref TEXT NOT NULL,
                active INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_slot
                ON bookings(slot_id) WHERE active = 1;
            CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> BookingStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def ensure_slot(self, slot_id: str, day: str, service: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO slots (slot_id, day, service, free) VALUES (?, ?, ?, 1)",
            (slot_id, day, service),
        )
        self._conn.commit()

    def seed_booking(
        self, slot_id: str, day: str, service: str, patient_ref: str, booking_id: str
    ) -> None:
        self.ensure_slot(slot_id, day, service)
        self._conn.execute("UPDATE slots SET free = 0 WHERE slot_id = ?", (slot_id,))
        self._conn.execute(
            """
            INSERT OR IGNORE INTO bookings (booking_id, slot_id, patient_ref, active)
            VALUES (?, ?, ?, 1)
            """,
            (booking_id, slot_id, patient_ref),
        )
        self._conn.commit()

    def find_slots(self, day: str, service: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT slot_id, day, service FROM slots
            WHERE day = ? AND service = ? AND free = 1
            ORDER BY slot_id
            LIMIT 3
            """,
            (day, service),
        ).fetchall()
        found: list[dict[str, object]] = []
        for row in rows:
            slot_id, slot_day, slot_service = cast(tuple[object, object, object], tuple(row))
            found.append({"slot_id": slot_id, "day": slot_day, "service": slot_service})
        return found

    def book(self, slot_id: str, patient_ref: str, key: str) -> dict[str, object]:
        cached = self._cached(key)
        if cached is not None:
            cached["idempotent_replay"] = True
            return cached
        row = self._conn.execute("SELECT free FROM slots WHERE slot_id = ?", (slot_id,)).fetchone()
        if row is None:
            result: dict[str, object] = {"ok": False, "error": "unknown_slot", "slot_id": slot_id}
        else:
            free = _as_int(cast(tuple[object, ...], tuple(row))[0])
            if free == 0:
                result = {"ok": False, "error": "slot_unavailable", "slot_id": slot_id}
            else:
                booking_id = f"bk-{slot_id}"
                self._conn.execute("UPDATE slots SET free = 0 WHERE slot_id = ?", (slot_id,))
                self._conn.execute(
                    """
                    INSERT INTO bookings (booking_id, slot_id, patient_ref, active)
                    VALUES (?, ?, ?, 1)
                    """,
                    (booking_id, slot_id, patient_ref),
                )
                result = {
                    "ok": True,
                    "booking_id": booking_id,
                    "slot_id": slot_id,
                    "patient_ref": patient_ref,
                }
        self._store(key, result)
        return result

    def cancel(self, booking_id: str, key: str) -> dict[str, object]:
        cached = self._cached(key)
        if cached is not None:
            cached["idempotent_replay"] = True
            return cached
        row = self._conn.execute(
            "SELECT slot_id, active FROM bookings WHERE booking_id = ?",
            (booking_id,),
        ).fetchone()
        if row is None:
            result: dict[str, object] = {
                "ok": False,
                "error": "not_found",
                "booking_id": booking_id,
            }
        else:
            slot_id, active = cast(tuple[object, object], tuple(row))
            if _as_int(active) == 0:
                result = {"ok": False, "error": "not_found", "booking_id": booking_id}
            else:
                self._conn.execute(
                    "UPDATE bookings SET active = 0 WHERE booking_id = ?",
                    (booking_id,),
                )
                self._conn.execute("UPDATE slots SET free = 1 WHERE slot_id = ?", (str(slot_id),))
                result = {"ok": True, "booking_id": booking_id, "slot_id": slot_id}
        self._store(key, result)
        return result

    def active_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT slot_id, COUNT(*) FROM bookings WHERE active = 1 GROUP BY slot_id"
        ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            slot_id, count = cast(tuple[object, object], tuple(row))
            counts[str(slot_id)] = _as_int(count)
        return counts

    def _cached(self, key: str) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT response_json FROM idempotency WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        raw = cast(tuple[object, ...], tuple(row))[0]
        parsed: object = json.loads(str(raw))
        if not isinstance(parsed, dict):
            return None
        return {str(item_key): value for item_key, value in parsed.items()}

    def _store(self, key: str, result: dict[str, object]) -> None:
        self._conn.execute(
            "INSERT INTO idempotency (key, response_json) VALUES (?, ?)",
            (key, json.dumps(result, sort_keys=True)),
        )
        self._conn.commit()
