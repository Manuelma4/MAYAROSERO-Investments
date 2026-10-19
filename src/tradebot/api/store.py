"""SQLite store for live events (signals, abnormal moves)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, id DESC);
"""


class EventStore:
    def __init__(self, path: str | Path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def add(self, type_: str, symbol: str, payload: dict) -> dict:
        with self._lock:
            cur = self._conn.execute("INSERT INTO events(type, symbol, payload) VALUES (?, ?, ?)",
                                     (type_, symbol, json.dumps(payload, default=str)))
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._row(row)

    def list(self, type_: str | None = None, limit: int = 100, before_id: int | None = None) -> list[dict]:
        q, args = "SELECT * FROM events WHERE 1=1", []
        if type_:
            q += " AND type = ?"
            args.append(type_)
        if before_id:
            q += " AND id < ?"
            args.append(before_id)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "created_at": r["created_at"], "type": r["type"],
                "symbol": r["symbol"], **json.loads(r["payload"])}
