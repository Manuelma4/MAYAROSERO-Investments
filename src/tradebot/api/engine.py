"""Live engine: runs the scanner in a background thread and broadcasts events.

Events are persisted in SQLite and pushed to every connected WebSocket
client. Email / WhatsApp alerts are sent by the scanner's notifiers.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone

from ..live import Scanner
from .serialize import clean
from .store import EventStore

log = logging.getLogger(__name__)


class Broadcaster:
    """Fan-out of events from the engine thread to asyncio WebSocket queues."""

    def __init__(self):
        self._queues: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def publish(self, event: dict) -> None:
        if self._loop is None:
            return
        for q in list(self._queues):
            self._loop.call_soon_threadsafe(self._put, q, event)

    @staticmethod
    def _put(q: asyncio.Queue, event: dict) -> None:
        if q.full():
            q.get_nowait()
        q.put_nowait(event)


class LiveEngine:
    def __init__(self, config: dict, store: EventStore, broadcaster: Broadcaster,
                 scanner_factory=Scanner.from_config):
        self.config = config
        self.store = store
        self.broadcaster = broadcaster
        self._scanner_factory = scanner_factory
        self.scanner: Scanner | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._scan_lock = threading.Lock()
        self.last_scan: str | None = None
        self.last_error: str | None = None
        self.scans = 0

    @property
    def poll_seconds(self) -> int:
        return int(self.config.get("poll_seconds", 60))

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _ensure_scanner(self) -> Scanner:
        if self.scanner is None:
            self.scanner = self._scanner_factory(self.config)
        return self.scanner

    def status(self) -> dict:
        try:
            sc = self._ensure_scanner()
        except Exception as exc:  # bad config should be visible, not crash the API
            self.last_error = f"Invalid config: {exc}"
            sc = None
        return {
            "running": self.running,
            "poll_seconds": self.poll_seconds,
            "scans": self.scans,
            "last_scan": self.last_scan,
            "last_error": self.last_error,
            "watchlist": [{"provider": w.provider, "symbol": w.symbol, "timeframe": w.timeframe,
                           "strategies": [s["name"] for s in w.strategies]} for w in (sc.watchlist if sc else [])],
            "movers_enabled": bool(sc and sc.movers),
            "paper_trading": bool(sc and sc.broker),
            "notifiers": [type(n).__name__.replace("Notifier", "").lower() for n in (sc.notifiers if sc else [])],
        }

    def scan_once(self) -> list[dict]:
        with self._scan_lock:
            sc = self._ensure_scanner()
            try:
                alerts = sc.run_once()
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                log.exception("scan failed")
                alerts = []
            self.scans += 1
            self.last_scan = datetime.now(timezone.utc).isoformat()
        events = []
        for a in alerts:
            a = clean(dict(a))
            type_ = a.pop("type", "signal")
            symbol = a.pop("symbol")
            ev = self.store.add(type_, symbol, a)
            self.broadcaster.publish(ev)
            events.append(ev)
        self.broadcaster.publish({"type": "status", **self.status()})
        return events

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            self.scan_once()
            self._stop.wait(max(1.0, self.poll_seconds - (time.time() - started)))

    def start(self) -> None:
        if self.running:
            return
        self._ensure_scanner()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tradebot-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
