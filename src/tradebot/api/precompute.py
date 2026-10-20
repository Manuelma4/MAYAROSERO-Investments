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
from .services import compute_picks, compute_predictions, market_mood

log = logging.getLogger(__name__)


class Precomputer:
    def __init__(self, market: MarketData, interval: int = 1800, opportunities_interval: int = 300,
                 on_opportunity=None, paper=None, paper_lock=None):
        self.market = market
        self.interval = interval
        self.opportunities_interval = opportunities_interval
        self.on_opportunity = on_opportunity   # callback(dict) for each NEW qualified opportunity
        self.paper = paper                     # PaperBroker for automatic exits of "Invest" positions
        self.paper_lock = paper_lock or threading.Lock()
        self._seen: set[tuple] = set()
        self._scanner = None
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

    def run_once(self, predictions: bool = True) -> None:
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
        today = datetime.now(timezone.utc).date().isoformat()
        for h in ((5, 1, 21) if predictions else ()):   # heavy: recomputed once per day
            key = f"predictions:{h}"
            cur = self.get(key)
            if cur is not None and cur.get("_computed") == today:
                continue
            try:
                data = compute_predictions(self.market, h)
                data["_computed"] = today
                self.put(key, data)
            except Exception as exc:
                errors.append(f"predictions {h}: {exc}")
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

    # ---- live opportunities ---------------------------------------------------------
    def scan_opportunities(self) -> dict:
        import pandas as pd

        from ..live.opportunities import OpportunityScanner, session_fraction

        if self._scanner is None:
            self._scanner = OpportunityScanner(self.market)
        now = pd.Timestamp.now(tz="UTC")
        items = [o.to_dict() for o in self._scanner.scan(now)]
        data = ser.clean({"as_of": now.isoformat(), "us_market_open": session_fraction(now, False) < 1.0,
                          "items": items})
        self.put("opportunities", data)
        for o in items:
            key = (o["symbol"], o["direction"], o["as_of"][:10])
            if o["qualified"] and key not in self._seen:
                self._seen.add(key)
                if self.on_opportunity:
                    try:
                        self.on_opportunity(o)
                    except Exception as exc:
                        log.warning("opportunity callback failed: %s", exc)
        return data

    def manage_paper_exits(self) -> list[dict]:
        """Close paper 'Invest' positions at their stop, target or time limit."""
        import pandas as pd

        if self.paper is None:
            return []
        closed = []
        pos = [p for p in self.paper.positions.values() if p.strategy == "opportunity"]
        if not pos:
            return closed
        quotes = {q["symbol"]: q for q in self.market.quotes([p.symbol for p in pos])}
        now = pd.Timestamp.now(tz="UTC")
        for p in pos:
            price = quotes.get(p.symbol, {}).get("price")
            if price is None:
                if now - pd.Timestamp(p.entry_time) > pd.Timedelta(days=7):
                    log.warning("time limit reached for %s but no price available; will retry", p.symbol)
                continue
            long = p.side == "long"
            reason = None
            if (price <= p.stop) if long else (price >= p.stop):
                reason = "stop"
            elif p.target is not None and ((price >= p.target) if long else (price <= p.target)):
                reason = "target"
            elif now - pd.Timestamp(p.entry_time) > pd.Timedelta(days=7):  # ~5 trading days
                reason = "time limit"
            if reason:
                with self.paper_lock:
                    rec = self.paper.close(p.symbol, p.strategy, price, now.isoformat(), reason)
                if rec:
                    closed.append(rec)
        return closed

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            self.run_once()
            self._stop.wait(max(60.0, self.interval - (time.time() - started)))

    def _opp_loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            try:
                self.scan_opportunities()
            except Exception as exc:
                log.warning("opportunity scan failed: %s", exc)
            try:
                self.manage_paper_exits()   # stops must fire even if the scan failed
            except Exception as exc:
                log.warning("paper exits failed: %s", exc)
            self._stop.wait(max(60.0, self.opportunities_interval - (time.time() - started)))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="precompute", daemon=True)
        self._thread.start()
        threading.Thread(target=self._opp_loop, name="opportunities", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
