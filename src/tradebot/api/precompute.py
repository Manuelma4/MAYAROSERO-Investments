"""Background precomputation: pages show results instantly instead of computing on click.

Jobs run at startup and then every `interval` seconds in a daemon thread:
- picks for every preset with default settings
- the "Today" board: market mood, what to hold, buy/sell/keep changes, today's biggest movers
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone

from ..picker import PRESETS
from ..universe import by_symbol, sp500_symbols
from . import serialize as ser
from .market import MarketData
from .schemas import PicksRequest
from .services import compute_picks, market_mood

log = logging.getLogger(__name__)


class Precomputer:
    def __init__(self, market: MarketData, interval: int = 1800):
        self.market = market
        self.interval = interval
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run: str | None = None
        self.last_error: str | None = None

    def get(self, key: str) -> dict | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._data[key] = value

    def run_once(self) -> None:
        errors = []
        ew_cache: dict = {}  # the equal-weight yardstick is identical for every preset
        for preset in PRESETS:
            try:
                self.put(f"picks:{preset}", compute_picks(self.market, PicksRequest(preset=preset), ew_cache))
            except Exception as exc:  # keep the previous result if a refresh fails
                errors.append(f"picks {preset}: {exc}")
        try:
            self.put("today", self.build_today())
        except Exception as exc:
            errors.append(f"today: {exc}")
        self.last_run = datetime.now(timezone.utc).isoformat()
        self.last_error = "; ".join(errors) or None
        if errors:
            log.warning("precompute errors: %s", self.last_error)

    def build_today(self) -> dict:
        core = self.get("picks:quality_momentum")
        try:
            mood = market_mood(self.market, core.get("breadth_%") if core else None)
        except Exception as exc:  # the board still shows picks and movers without the mood
            log.warning("market mood unavailable: %s", exc)
            mood = None
        quotes = [q for q in self.market.quotes(sp500_symbols())
                  if isinstance(q.get("change_pct"), (int, float)) and math.isfinite(q["change_pct"])]
        quotes.sort(key=lambda q: q["change_pct"], reverse=True)
        names = {k: v.name for k, v in by_symbol().items()}
        for q in quotes:
            q["name"] = names.get(q["symbol"], q["symbol"])
        return ser.clean({
            "as_of": datetime.now(timezone.utc).isoformat(),
            "mood": mood,
            "core": None if core is None else {
                "preset": core["preset"], "risk_off": core["risk_off"], "picks": core["picks"],
                "changes": core["changes"], "as_of": core["as_of"],
                "edge": {k: core["stats"].get(k) for k in ("cagr_%", "benchmark_cagr_%", "skill_vs_universe_%", "start")},
                "settings": "10 stocks, monthly review, uptrends only (Quality momentum)",
            },
            "gainers": [{k: q[k] for k in ("symbol", "name", "price", "change_pct")} for q in quotes[:6]],
            "losers": [{k: q[k] for k in ("symbol", "name", "price", "change_pct")} for q in quotes[::-1][:6]],
        })

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            self.run_once()
            self._stop.wait(max(60.0, self.interval - (time.time() - started)))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="precompute", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
