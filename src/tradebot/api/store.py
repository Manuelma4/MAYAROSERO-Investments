"""SQLite store for live events (signals, abnormal moves), watchlists, price alerts and the live
track record (daily picks snapshots and Invest-now ideas, recorded as they happen), the saved portfolio target
and the "already sent" marks of the weekly digest and drift alerts (so a restart never repeats them)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
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
CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    symbols TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    value REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    triggered_at TEXT,
    triggered_price REAL,
    last_bar TEXT
);
CREATE TABLE IF NOT EXISTS track_picks (
    preset TEXT NOT NULL,
    date TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    risk_off INTEGER NOT NULL DEFAULT 0,
    picks TEXT NOT NULL,
    PRIMARY KEY (preset, date)
);
CREATE TABLE IF NOT EXISTS track_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL,
    valid_until TEXT,
    as_of TEXT NOT NULL,
    hold_days INTEGER NOT NULL DEFAULT 5,
    recorded_at TEXT NOT NULL,
    UNIQUE (symbol, direction, day)
);
CREATE TABLE IF NOT EXISTS notices (
    kind TEXT NOT NULL,
    period TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (kind, period)
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
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
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(alerts)")}
            if "last_bar" not in cols:   # databases created before this column existed
                self._conn.execute("ALTER TABLE alerts ADD COLUMN last_bar TEXT")

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

    # --- watchlists -------------------------------------------------------------------------
    def watchlists(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM watchlists ORDER BY id").fetchall()
        return [{"id": r["id"], "name": r["name"], "symbols": json.loads(r["symbols"])} for r in rows]

    def save_watchlist(self, name: str, symbols: list[str], id_: int | None = None) -> dict | None:
        syms = json.dumps(list(dict.fromkeys(symbols)))
        with self._lock:
            if id_ is None:
                id_ = self._conn.execute("INSERT INTO watchlists(name, symbols) VALUES (?, ?)", (name, syms)).lastrowid
            elif not self._conn.execute("UPDATE watchlists SET name = ?, symbols = ? WHERE id = ?",
                                        (name, syms, id_)).rowcount:
                return None
            self._conn.commit()
        return next(w for w in self.watchlists() if w["id"] == id_)

    def delete_watchlist(self, id_: int) -> bool:
        with self._lock:
            n = self._conn.execute("DELETE FROM watchlists WHERE id = ?", (id_,)).rowcount
            self._conn.commit()
        return bool(n)

    # --- price alerts -----------------------------------------------------------------------
    def alerts(self, active_only: bool = False) -> list[dict]:
        q = "SELECT * FROM alerts" + (" WHERE active = 1" if active_only else "") + " ORDER BY id DESC"
        with self._lock:
            rows = self._conn.execute(q).fetchall()
        return [{**dict(r), "active": bool(r["active"])} for r in rows]

    def add_alert(self, symbol: str, kind: str, value: float, note: str = "") -> dict:
        with self._lock:
            id_ = self._conn.execute("INSERT INTO alerts(symbol, kind, value, note) VALUES (?, ?, ?, ?)",
                                     (symbol, kind, value, note)).lastrowid
            self._conn.commit()
        return next(a for a in self.alerts() if a["id"] == id_)

    def set_alert_active(self, id_: int, active: bool, price: float | None = None, bar: str | None = None) -> bool:
        """Deactivate (fired: records time, price and the quote's bar so a re-armed daily-move alert
        waits for a NEW day) or re-arm an alert."""
        with self._lock:
            if active:
                n = self._conn.execute("UPDATE alerts SET active = 1, triggered_at = NULL, triggered_price = NULL "
                                       "WHERE id = ?", (id_,)).rowcount
            else:
                n = self._conn.execute("UPDATE alerts SET active = 0, triggered_price = ?, last_bar = ?, triggered_at = "
                                       "strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (price, bar, id_)).rowcount
            self._conn.commit()
        return bool(n)

    def delete_alert(self, id_: int) -> bool:
        with self._lock:
            n = self._conn.execute("DELETE FROM alerts WHERE id = ?", (id_,)).rowcount
            self._conn.commit()
        return bool(n)

    # --- live track record ------------------------------------------------------------------
    def record_picks_snapshot(self, preset: str, date: str, picks: list[dict], risk_off: bool,
                              recorded_at: str) -> bool:
        """One snapshot per preset and session date; later calls for the same day are ignored."""
        with self._lock:
            n = self._conn.execute("INSERT OR IGNORE INTO track_picks(preset, date, recorded_at, risk_off, picks) "
                                   "VALUES (?, ?, ?, ?, ?)",
                                   (preset, date, recorded_at, int(risk_off), json.dumps(picks))).rowcount
            self._conn.commit()
        return bool(n)

    def picks_snapshots(self, preset: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM track_picks WHERE preset = ? ORDER BY date", (preset,)).fetchall()
        out = []
        for r in rows:
            picks = json.loads(r["picks"])
            out.append({"preset": r["preset"], "date": r["date"], "recorded_at": r["recorded_at"],
                        "risk_off": bool(r["risk_off"]), "picks": picks,
                        "weights": {p["symbol"]: p["weight"] for p in picks}})
        return out

    def record_idea(self, idea: dict, recorded_at: str) -> bool:
        """One row per symbol, direction and day (the first qualified version of the idea is kept)."""
        with self._lock:
            n = self._conn.execute(
                "INSERT OR IGNORE INTO track_ideas(day, symbol, direction, entry, stop, target, valid_until, as_of, "
                "hold_days, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(idea["as_of"])[:10], idea["symbol"], idea["direction"], float(idea["entry"]), float(idea["stop"]),
                 None if idea.get("target") is None else float(idea["target"]), idea.get("expires_at"),
                 str(idea["as_of"]), int(idea.get("hold_days") or 5), recorded_at)).rowcount
            self._conn.commit()
        return bool(n)

    def track_ideas(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM track_ideas ORDER BY as_of").fetchall()
        return [dict(r) for r in rows]

    # --- once-only notices (weekly digest, drift alert) ---------------------------------------
    def claim_notice(self, kind: str, period: str, now: datetime, min_gap: timedelta | None = None) -> bool:
        """Atomically mark `kind` as sent for `period`. False if it was already sent for that period, or
        (with `min_gap`) if the last one of this kind went out less than `min_gap` ago."""
        with self._lock:
            if min_gap is not None:
                last = self._conn.execute("SELECT MAX(sent_at) FROM notices WHERE kind = ?", (kind,)).fetchone()[0]
                if last and now - datetime.fromisoformat(last) < min_gap:
                    return False
            n = self._conn.execute("INSERT OR IGNORE INTO notices(kind, period, sent_at) VALUES (?, ?, ?)",
                                   (kind, period, now.isoformat())).rowcount
            self._conn.commit()
        return bool(n)

    def last_notice(self, kind: str) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM notices WHERE kind = ? ORDER BY sent_at DESC LIMIT 1",
                                   (kind,)).fetchone()
        return dict(r) if r else None

    # --- small saved settings (portfolio target) ------------------------------------------------
    def get_value(self, key: str):
        with self._lock:
            r = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(r["value"]) if r else None

    def set_value(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET "
                               "value = excluded.value, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                               (key, json.dumps(value, default=str)))
            self._conn.commit()

    def delete_value(self, key: str) -> bool:
        with self._lock:
            n = self._conn.execute("DELETE FROM kv WHERE key = ?", (key,)).rowcount
            self._conn.commit()
        return bool(n)
