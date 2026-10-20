"""Server-side state that protects broker orders, whatever the broker:

- ConfirmTokens: a preview issues a short-lived, single-use token bound to the exact plan; placing needs it.
- OrderJournal: orders placed through the app (for the time limit and target watch, and the UI).
- DayBaseline: start-of-day equity for brokers that do not report today's P&L (daily loss limit).
- Halt: after the kill switch, new orders stay blocked until the owner resumes. Paper: also lifted at the next
  UTC day. Live (real money): only a manual resume lifts it.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path

import pandas as pd

CONFIRM_TTL_SECONDS = 90


class ConfirmTokens:
    def __init__(self, ttl: float = CONFIRM_TTL_SECONDS, clock=time.monotonic):
        self.ttl, self.clock = ttl, clock
        self._items: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def issue(self, bound: dict) -> str:
        tok = secrets.token_urlsafe(18)
        with self._lock:
            now = self.clock()
            self._items = {k: v for k, v in self._items.items() if v[0] > now}
            self._items[tok] = (now + self.ttl, dict(bound))
        return tok

    def consume(self, token: str | None) -> dict | None:
        """The bound plan, once. None if missing, unknown, used or expired."""
        if not token:
            return None
        with self._lock:
            item = self._items.pop(token, None)
        if item is None or item[0] < self.clock():
            return None
        return item[1]


class _JsonFile:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self, default):
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return default

    def _write(self, data) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(self.path)


class OrderJournal(_JsonFile):
    def add(self, rec: dict) -> None:
        with self._lock:
            data = self._read([])
            data.append(rec)
            self._write(data[-500:])

    def all(self) -> list[dict]:
        with self._lock:
            return self._read([])

    def open_entries(self, broker: str, mode: str) -> list[dict]:
        return [r for r in self.all() if r.get("status") == "open" and r.get("broker") == broker and r.get("mode") == mode]

    def mark(self, order_id: str, **fields) -> None:
        with self._lock:
            data = self._read([])
            for r in data:
                if r.get("id") == order_id:
                    r.update(fields)
            self._write(data)


class DayBaseline(_JsonFile):
    def day_pnl(self, key: str, equity: float, now: pd.Timestamp | None = None) -> float:
        day = str((now or pd.Timestamp.now(tz="UTC")).date())
        with self._lock:
            data = self._read({})
            rec = data.get(key)
            if not rec or rec.get("day") != day:
                rec = data[key] = {"day": day, "equity": equity}
                self._write(data)
        return equity - float(rec["equity"])


class Halt(_JsonFile):
    def set(self, reason: str, now: pd.Timestamp | None = None, persistent: bool = False) -> None:
        """``persistent`` (real money): stays until clear(), whatever the date."""
        now = now or pd.Timestamp.now(tz="UTC")
        with self._lock:
            self._write({"day": str(now.date()), "at": now.isoformat(), "reason": reason, "persistent": persistent})

    def active(self, now: pd.Timestamp | None = None) -> dict | None:
        now = now or pd.Timestamp.now(tz="UTC")
        with self._lock:
            d = self._read(None)
        if not d:
            return None
        return d if d.get("persistent") or d.get("day") == str(now.date()) else None

    def clear(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)
