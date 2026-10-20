"""Daily fundamentals for the screener: market cap, P/E (last and next 12 months), dividend yield, beta, sector.

Source: Yahoo Finance via yfinance (`Ticker.info`, free). Every call holds the shared `_YF_LOCK`, one symbol at a
time with a pause in between, so a full pass over the ~520-stock universe takes several minutes and never holds
the lock for long (price downloads for the other jobs slip in between two symbols).

- `parse_info(info)` turns Yahoo's dict into the screener record (numbers or None; never raises).
- `dividend_yield_pct(info)` returns the yield in percent (2.3 = 2.3% a year). yfinance changed the unit of
  `dividendYield` (a fraction like 0.023 before 0.2.54, a percent like 2.3 since Yahoo's Feb 2025 change); the app
  once showed yields 100x too small because of it. The unit is decided against unit-free references from the same
  response (`trailingAnnualDividendYield`, always a fraction, and `dividendRate / price`), then the version.
- `Fundamentals` caches records in memory and, given the app's `EventStore`, in SQLite (restarts don't refetch).
  A record is due again once a day (when it was fetched before the latest 06:00 New York, before the US open)
  or 2 h after a failure. `refresh()` fetches
  due symbols one by one and saves each at once, so partial results are usable while a pass is running.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .providers import _YF_LOCK

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
SLOT_HOUR = 6           # daily refresh from 06:00 New York (after yesterday's close and overnight reports)
FAIL_TTL = 2 * 3600     # failed lookups are retried after 2 h
FRESH = 36 * 3600       # "up to date" in the coverage figures
PAUSE = 0.35            # seconds between two Yahoo requests (~1-2 symbols per second with the request itself)
BACKOFF = 60.0          # pause after MAX_FAILS failures in a row (rate limit), doubled each time
MAX_FAILS = 4           # consecutive failures before backing off
MAX_BACKOFFS = 3        # give up this pass after this many back-offs; the next pass retries
MAX_YIELD = 25.0        # a dividend yield above this is a data error (special dividends, unit mix-ups)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _yf_reports_percent() -> bool:
    """yfinance >= 0.2.54 reports `dividendYield` in percent (Yahoo changed the field in Feb 2025)."""
    try:
        import yfinance as yf

        parts = tuple(int(p) for p in yf.__version__.split(".")[:3])
    except Exception:
        return True
    return parts >= (0, 2, 54)


def dividend_yield_pct(info: dict, percent_default: bool | None = None) -> float | None:
    """Yearly dividend as a percent of the price (2.3 means 2.3%), whatever unit Yahoo/yfinance used. None when
    unknown; 0.0 when the company pays no dividend."""
    dy = _num(info.get("dividendYield"))
    trailing = _num(info.get("trailingAnnualDividendYield"))   # always a fraction (0.022)
    rate, price = _num(info.get("dividendRate")), _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    refs = [r for r in ((trailing * 100) if trailing else None,
                        (rate / price * 100) if rate and price and rate > 0 and price > 0 else None) if r]
    if dy is None:
        out = refs[0] if refs else (0.0 if trailing == 0 or rate == 0 else None)
    elif dy <= 0:
        out = 0.0
    elif refs:   # pick the unit that lands closest to the unit-free reference
        ref = refs[0]
        out = min((dy, dy * 100), key=lambda v: abs(math.log(v / ref)))
    else:
        pct = _yf_reports_percent() if percent_default is None else percent_default
        out = dy if pct else dy * 100
    if out is None or out < 0 or out > MAX_YIELD:
        return None
    return round(out, 3)


def parse_info(info: dict | None) -> dict | None:
    """Screener fields from `Ticker.info`; None when Yahoo returned nothing usable (rate limit, unknown symbol)."""
    if not info:
        return None
    cap = _num(info.get("marketCap"))
    pe, fpe = _num(info.get("trailingPE")), _num(info.get("forwardPE"))
    if cap is None and pe is None and _num(info.get("regularMarketPrice") or info.get("currentPrice")) is None:
        return None
    ccy = info.get("currency") or info.get("financialCurrency")
    return {
        "name": info.get("longName") or info.get("shortName"),
        "market_cap": cap if cap and cap > 0 else None,
        "currency": str(ccy) if ccy else None,
        "pe": pe if pe and pe > 0 else None,                 # Yahoo leaves it out when profits are negative
        "forward_pe": fpe if fpe and fpe > 0 else None,
        "eps": _num(info.get("trailingEps")),
        "dividend_yield": dividend_yield_pct(info),
        "beta": _num(info.get("beta")),
        "sector_yahoo": info.get("sector"),
        "industry_yahoo": info.get("industry"),
    }


def fetch_fundamentals(symbol: str) -> dict | None:
    """One Yahoo request under the shared lock. Never raises: returns None on any failure."""
    try:
        import yfinance as yf

        with _YF_LOCK:
            info = yf.Ticker(symbol).info
        return parse_info(info)
    except Exception as exc:
        log.info("fundamentals %s failed: %s", symbol, exc)
        return None


# Looked up at call time so tests can swap in an offline fetcher.
FETCH: Callable[[str], dict | None] = fetch_fundamentals


class Fundamentals:
    """Fundamentals per symbol, cached in memory and (optionally) SQLite, refreshed once a day."""

    def __init__(self, store=None, slot_hour: int = SLOT_HOUR, fail_ttl: float = FAIL_TTL, pause: float | None = None,
                 fetcher: Callable[[str], dict | None] | None = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] | None = None):
        self.store = store
        self.slot_hour, self.fail_ttl, self.pause = slot_hour, fail_ttl, pause
        self._fetcher = fetcher
        self._clock = clock
        self._sleep = sleep
        self._mem: dict[str, dict] = {}
        self._loaded = False
        self._lock = threading.Lock()
        self._running = threading.Lock()      # one refresh pass at a time
        self.last_pass: dict | None = None   # counts of the last finished pass
        self.progress: dict | None = None    # live counts while a pass runs

    # ---- cache ------------------------------------------------------------------------------
    def _load(self) -> None:
        if self._loaded:
            return
        rows = {}
        if self.store is not None:
            try:
                rows = self.store.fundamentals_all()
            except Exception as exc:
                log.warning("fundamentals cache read failed: %s", exc)
        with self._lock:
            for s, rec in rows.items():
                self._mem.setdefault(s, rec)
            self._loaded = True

    def cached(self, symbols: list[str] | None = None) -> dict[str, dict]:
        """Every stored record (fresh or not)."""
        self._load()
        with self._lock:
            if symbols is None:
                return dict(self._mem)
            return {s: self._mem[s] for s in symbols if s in self._mem}

    def put(self, symbol: str, data: dict | None) -> dict:
        """Save one attempt. A failure keeps the last good figures (marked as not refreshed)."""
        now = self._clock()
        self._load()
        with self._lock:
            old = self._mem.get(symbol)
        if data is not None:
            rec = {**data, "symbol": symbol, "ok": True, "_tried": now, "_ok_at": now,
                   "fetched_at": datetime.fromtimestamp(now, timezone.utc).isoformat()}
        else:
            rec = {**(old or {"symbol": symbol, "_ok_at": None, "fetched_at": None}), "ok": False, "_tried": now}
        with self._lock:
            self._mem[symbol] = rec
        if self.store is not None:
            try:
                self.store.fundamentals_put(symbol, rec)
            except Exception as exc:
                log.warning("fundamentals cache write failed: %s", exc)
        return rec

    def last_slot(self, now: float) -> float:
        """The most recent daily refresh time (06:00 New York) at or before `now`, as a Unix time."""
        t = datetime.fromtimestamp(now, timezone.utc).astimezone(NY)
        slot = t.replace(hour=self.slot_hour, minute=0, second=0, microsecond=0)
        if slot > t:
            slot = (t - timedelta(days=1)).replace(hour=self.slot_hour, minute=0, second=0, microsecond=0)
        return slot.timestamp()

    def is_due(self, rec: dict | None, now: float | None = None) -> bool:
        """Never fetched; fetched before today's refresh time; or failed more than `fail_ttl` ago."""
        if not rec:
            return True
        now = self._clock() if now is None else now
        tried = float(rec.get("_tried") or 0)
        if rec.get("ok"):
            return tried < self.last_slot(now)
        return now - tried >= self.fail_ttl

    def due(self, symbols: list[str]) -> list[str]:
        """Symbols to fetch, most useful first: never fetched, then failed, then the oldest."""
        have = self.cached(symbols)
        now = self._clock()
        todo = [s for s in dict.fromkeys(symbols) if self.is_due(have.get(s), now)]
        return sorted(todo, key=lambda s: (s in have, bool(have.get(s, {}).get("_ok_at")),
                                           float(have.get(s, {}).get("_tried") or 0)))

    @property
    def refreshing(self) -> bool:
        return self._running.locked()

    def coverage(self, symbols: list[str]) -> dict:
        have = self.cached(symbols)
        now = self._clock()
        with_data = [r for r in have.values() if r.get("_ok_at")]
        fresh = [r for r in with_data if now - float(r["_ok_at"]) < FRESH]
        last = max((float(r["_ok_at"]) for r in with_data), default=None)
        return {"total": len(symbols), "with_fundamentals": len(with_data), "fresh": len(fresh),
                "last_update": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
                "refreshing": self.refreshing, "progress": self.progress}

    # ---- refresh ----------------------------------------------------------------------------
    def refresh(self, symbols: list[str], stop: threading.Event | None = None, wait: bool = False) -> dict:
        """Fetch the due symbols one by one (each saved at once). Backs off when Yahoo keeps failing (rate limit)
        and gives up the pass after a few back-offs. Returns at once with busy=True when a pass is running."""
        if not self._running.acquire(blocking=wait):
            return {"busy": True, "fetched": 0, "ok": 0}
        try:
            todo = self.due(symbols)
            fn = self._fetcher or FETCH
            pause = PAUSE if self.pause is None else self.pause
            sleep = self._sleep or (stop.wait if stop is not None else time.sleep)
            fetched = ok = fails = backoffs = 0
            self.progress = {"done": 0, "todo": len(todo)}
            for s in todo:
                if stop is not None and stop.is_set():
                    break
                if fetched and pause:
                    sleep(pause)
                try:
                    data = fn(s)
                except Exception as exc:   # an injected fetcher may raise; the cache never does
                    log.info("fundamentals %s failed: %s", s, exc)
                    data = None
                self.put(s, data)
                fetched += 1
                self.progress = {"done": fetched, "todo": len(todo)}
                if data is not None:
                    ok, fails = ok + 1, 0
                    continue
                fails += 1
                if fails >= MAX_FAILS:
                    if backoffs >= MAX_BACKOFFS:
                        log.warning("fundamentals: Yahoo keeps failing, pausing the refresh until the next pass")
                        break
                    sleep(BACKOFF * 2 ** backoffs)
                    backoffs, fails = backoffs + 1, 0
            res = {"busy": False, "due": len(todo), "fetched": fetched, "ok": ok, "backoffs": backoffs,
                   "finished_at": datetime.fromtimestamp(self._clock(), timezone.utc).isoformat()}
            if fetched:
                self.last_pass = res
                log.info("fundamentals: %d fetched, %d ok", fetched, ok)
            return res
        finally:
            self.progress = None
            self._running.release()
