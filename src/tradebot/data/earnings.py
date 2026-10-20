"""Earnings calendar: next and last quarterly results per stock, from Yahoo Finance (free, via yfinance).

"Earnings" = the day a company publishes its quarterly results. Prices often jump or drop sharply the next
session, so the app shows the date on stock pages and Today, and can warn the day before.

- `fetch_earnings(symbol)` reads `Ticker.get_earnings_dates()` (dates with time of day, EPS estimate, reported
  EPS and surprise), falling back to `Ticker.calendar` (next date only). Every yfinance call holds the shared
  `_YF_LOCK`. Any failure returns status "unknown"; it never raises.
- `EarningsCalendar` caches results for 12 h (failures for 1 h) in memory and, when given the app's
  `EventStore`, in SQLite so a restart doesn't hit Yahoo again. Refreshes are sequential with a short pause
  between symbols (polite to Yahoo's rate limits).
- `average_move()` is the average absolute price move on the session that reacted to each past report
  (descriptive statistic over past data, used in the alert text).
- `alert_phase()` / `alert_text()` decide when the "earnings tomorrow" alert is due in the owner's time zone.

Timing ("before the open" / "after the close") is read from the report's time in New York for US stocks.
Yahoo stores unconfirmed future reports at a fixed UTC hour, so a 15:00 New York time after a daylight-saving
change still means "after the close" (16:00). Non-US listings get "time not announced".
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .providers import _YF_LOCK

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
TTL = 12 * 3600          # successful lookups
FAIL_TTL = 3600          # failed lookups are retried after an hour
PAUSE = 0.25             # seconds between two Yahoo requests during a refresh
MAX_PAST = 8             # past reports kept per symbol

TIMING_TEXT = {
    "before_open": "before the market opens",
    "after_close": "after the market closes",
    "during": "during market hours",
    "unknown": "time not announced yet",
}
HINT = ("Earnings: the company publishes its quarterly results. Prices often jump or drop sharply right after, "
        "in either direction.")


def applicable(symbol: str) -> bool:
    """Only single stocks report earnings (not crypto, indices, FX, futures)."""
    return bool(symbol) and "/" not in symbol and not symbol.startswith("^") and "=" not in symbol


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def classify_timing(ts: pd.Timestamp | None, symbol: str) -> str:
    if ts is None or ts.tzinfo is None or "." in symbol:
        return "unknown"
    t = ts.tz_convert(NY)
    h = t.hour + t.minute / 60
    if h == 0:
        return "unknown"            # date only
    if h < 9.5:
        return "before_open"
    if h >= 15:                     # 16:00 (or 15:00 for an unconfirmed date across a DST change)
        return "after_close"
    return "during"


def _event(ts: pd.Timestamp, symbol: str, row: dict | None = None) -> dict:
    row = row or {}
    timing = classify_timing(ts, symbol)
    local = ts.tz_convert(NY) if ts.tzinfo is not None and "." not in symbol else ts
    return {"date": local.date().isoformat(),
            "time": ts.tz_convert("UTC").isoformat() if ts.tzinfo is not None and timing != "unknown" else None,
            "timing": timing,
            "eps_estimate": _num(row.get("EPS Estimate")), "eps_actual": _num(row.get("Reported EPS")),
            "surprise_pct": _num(row.get("Surprise(%)"))}


def parse_earnings_dates(df: pd.DataFrame | None, symbol: str, now: datetime | None = None) -> dict:
    """`Ticker.get_earnings_dates()` frame -> {"next": event | None, "last": event | None, "history": [...]}.

    A report counts as past once it has a reported EPS or its time is more than 12 hours ago."""
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    now = now.tz_localize("UTC") if now.tzinfo is None else now
    out = {"next": None, "last": None, "history": []}
    if df is None or len(df) == 0:
        return out
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize(NY)
    rows = df.to_dict("records")
    events = sorted(zip(idx, rows), key=lambda e: e[0])
    future, past = [], []
    for ts, row in events:
        reported = _num(row.get("Reported EPS")) is not None
        (past if reported or ts < now - pd.Timedelta(hours=12) else future).append(_event(ts, symbol, row))
    out["next"] = future[0] if future else None
    if out["next"]:
        for k in ("eps_actual", "surprise_pct"):
            out["next"].pop(k, None)
    out["history"] = past[::-1][:MAX_PAST]        # most recent first
    out["last"] = out["history"][0] if out["history"] else None
    return out


def parse_calendar(cal, symbol: str, now: datetime | None = None) -> dict | None:
    """`Ticker.calendar` (dict in yfinance >= 0.2.3x) -> next event (date only) or None."""
    if not isinstance(cal, dict):
        return None
    dates = cal.get("Earnings Date") or []
    dates = dates if isinstance(dates, (list, tuple)) else [dates]
    today = (now or datetime.now(timezone.utc)).astimezone(NY).date()
    upcoming = sorted(d for d in (pd.Timestamp(x).date() for x in dates if x is not None) if d >= today)
    if not upcoming:
        return None
    return {"date": upcoming[0].isoformat(), "time": None, "timing": "unknown",
            "eps_estimate": _num(cal.get("Earnings Average"))}


def unknown(symbol: str, reason: str = "") -> dict:
    return {"symbol": symbol, "status": "unknown", "next": None, "last": None, "history": [], "reason": reason}


def fetch_earnings(symbol: str, now: datetime | None = None) -> dict:
    """Next / last earnings for one stock from Yahoo. Never raises: problems give status "unknown"."""
    if not applicable(symbol):
        return {**unknown(symbol), "status": "none", "reason": "Only single stocks report earnings."}
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        df = None
        try:
            with _YF_LOCK:
                df = t.get_earnings_dates(limit=12)
        except Exception as exc:   # rate limit, no data, parsing change in yfinance
            log.info("earnings dates %s: %s", symbol, exc)
        data = parse_earnings_dates(df, symbol, now)
        if data["next"] is None:
            try:
                with _YF_LOCK:
                    cal = t.calendar
                data["next"] = parse_calendar(cal, symbol, now)
            except Exception as exc:
                log.info("earnings calendar %s: %s", symbol, exc)
        if data["next"] is None and data["last"] is None:
            return unknown(symbol, "No earnings dates from Yahoo.")
        return {"symbol": symbol, "status": "ok", **data}
    except Exception as exc:  # never crash the caller
        log.warning("earnings %s failed: %s", symbol, exc)
        return unknown(symbol, str(exc))


# Looked up at call time so tests can swap in an offline fetcher.
FETCH: Callable[[str], dict] = fetch_earnings


# ---- average reaction to past reports --------------------------------------------------------------
def report_move(ev: dict, bars: pd.DataFrame) -> float | None:
    """% move of the session that reacted to one past report (close to close).

    before the open / during the day: close of that day vs the previous close; after the close: next day's
    close vs that day's close; time unknown: next day's close vs the close before the report day (both)."""
    if bars is None or len(bars) < 3:
        return None
    days = pd.DatetimeIndex(bars.index).tz_localize(None).normalize() if bars.index.tz is not None \
        else pd.DatetimeIndex(bars.index).normalize()
    close = bars["close"].to_numpy(dtype=float)
    d = pd.Timestamp(ev["date"])
    pos = int(days.searchsorted(d))        # first session on or after the report date
    if pos >= len(days) or pos == 0:
        return None
    on_day = days[pos] == d
    timing = ev.get("timing") or "unknown"
    if not on_day or timing in ("before_open", "during"):   # a weekend report reacts on the next session
        a, b = pos - 1, pos
    elif timing == "after_close":
        a, b = pos, pos + 1
    else:
        a, b = pos - 1, pos + 1
    if b >= len(close) or close[a] <= 0:
        return None
    return (close[b] / close[a] - 1) * 100


def average_move(history: list[dict], bars: pd.DataFrame | None, n: int = 4) -> dict | None:
    """Average absolute move over the last `n` reports that have price data."""
    moves = []
    for ev in history or []:
        m = report_move(ev, bars) if bars is not None else None
        if m is not None:
            moves.append({"date": ev["date"], "move_%": round(m, 2)})
        if len(moves) >= n:
            break
    if not moves:
        return None
    return {"avg_abs_move_%": round(sum(abs(m["move_%"]) for m in moves) / len(moves), 2), "moves": moves}


# ---- cache -----------------------------------------------------------------------------------------
class EarningsCalendar:
    """Earnings per symbol, cached 12 h (1 h for failures) in memory and optionally in SQLite."""

    def __init__(self, store=None, ttl: int = TTL, fail_ttl: int = FAIL_TTL, pause: float | None = None,
                 fetcher: Callable[[str], dict] | None = None, clock: Callable[[], float] = time.time):
        self.store = store
        self.ttl, self.fail_ttl, self.pause = ttl, fail_ttl, pause
        self._fetcher = fetcher
        self._clock = clock
        self._mem: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._fetching = threading.Lock()   # one refresh at a time
        self.last_refresh: str | None = None

    def _fetch(self, symbol: str) -> dict:
        fn = self._fetcher or FETCH
        try:
            rec = fn(symbol)
        except Exception as exc:   # an injected fetcher may raise; the calendar never does
            rec = unknown(symbol, str(exc))
        return {**rec, "symbol": symbol}

    def _fresh(self, rec: dict | None, max_age: float | None = None) -> bool:
        if not rec:
            return False
        ttl = self.ttl if rec.get("status") in ("ok", "none") else self.fail_ttl
        if max_age is not None:
            ttl = min(ttl, max_age)
        return self._clock() - float(rec.get("_at", 0)) < ttl

    def cached(self, symbols: list[str]) -> dict[str, dict]:
        """Whatever is cached (fresh or not), memory first, then SQLite."""
        with self._lock:
            out = {s: self._mem[s] for s in symbols if s in self._mem}
        missing = [s for s in symbols if s not in out]
        if missing and self.store is not None:
            try:
                rows = self.store.earnings_get(missing)
            except Exception as exc:
                log.warning("earnings cache read failed: %s", exc)
                rows = {}
            with self._lock:
                for s, rec in rows.items():
                    self._mem.setdefault(s, rec)
                    out[s] = self._mem[s]
        return out

    def put(self, rec: dict) -> dict:
        rec = {**rec, "_at": rec.get("_at", self._clock()),
               "fetched_at": datetime.fromtimestamp(rec.get("_at", self._clock()), timezone.utc).isoformat()}
        with self._lock:
            self._mem[rec["symbol"]] = rec
        if self.store is not None:
            try:
                self.store.earnings_put(rec["symbol"], rec)
            except Exception as exc:
                log.warning("earnings cache write failed: %s", exc)
        return rec

    def get(self, symbols: list[str], fetch: bool = True, max_fetch: int = 20) -> dict[str, dict]:
        """Records for `symbols`; stale or missing ones are fetched (at most `max_fetch`), others "unknown"."""
        symbols = list(dict.fromkeys(symbols))
        have = self.cached(symbols)
        todo = [s for s in symbols if not self._fresh(have.get(s))]
        if fetch and todo:   # never waits behind a running background refresh: serves the cache instead
            self.refresh(todo[:max_fetch], max_age=None, wait=False)
            have = self.cached(symbols)
        return {s: have.get(s) or unknown(s, "Not loaded yet.") for s in symbols}

    def refresh(self, symbols: list[str], max_age: float | None = None, limit: int = 200,
                enrich: Callable[[list[dict]], None] | None = None, wait: bool = True) -> dict:
        """Fetch symbols whose cache is missing or older than min(ttl, max_age). `enrich(records)` may add
        fields (the average move) before they are saved. With wait=False, returns at once (nothing fetched)
        when another refresh is running. Returns counts."""
        symbols = list(dict.fromkeys(s for s in symbols if s))
        have = self.cached(symbols)
        todo = [s for s in symbols if not self._fresh(have.get(s), max_age)][:limit]
        fetched: list[dict] = []
        if todo:
            if not self._fetching.acquire(blocking=wait):
                return {"requested": len(symbols), "fetched": 0, "ok": 0, "busy": True}
            try:
                pause = PAUSE if self.pause is None else self.pause
                for i, s in enumerate(todo):
                    if i and pause:
                        time.sleep(pause)
                    fetched.append(self._fetch(s))
            finally:
                self._fetching.release()
        if enrich and fetched:
            try:
                enrich(fetched)
            except Exception as exc:
                log.warning("earnings enrich failed: %s", exc)
        for rec in fetched:
            self.put(rec)
        self.last_refresh = datetime.now(timezone.utc).isoformat()
        ok = sum(r.get("status") == "ok" for r in fetched)
        return {"requested": len(symbols), "fetched": len(fetched), "ok": ok}


# ---- views and alert -------------------------------------------------------------------------------
def public(rec: dict) -> dict:
    """API view of a cached record (no internal fields), with plain-English timing."""
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    for k in ("next", "last"):
        if out.get(k):
            out[k] = {**out[k], "timing_text": TIMING_TEXT.get(out[k].get("timing") or "unknown")}
    return out


def upcoming(records: dict[str, dict], today: date, days: int, flags: dict[str, dict] | None = None,
             names: dict[str, str] | None = None) -> list[dict]:
    """Reports from `today` to `today + days` (inclusive), soonest first."""
    flags, names = flags or {}, names or {}
    end = today + timedelta(days=days)
    out = []
    for s, rec in records.items():
        nxt = (rec or {}).get("next")
        if not nxt or not nxt.get("date"):
            continue
        d = date.fromisoformat(nxt["date"])
        if not today <= d <= end:
            continue
        f = flags.get(s, {})
        move = rec.get("avg_move") or {}
        out.append({"symbol": s, "name": names.get(s, s), "date": nxt["date"], "time": nxt.get("time"),
                    "timing": nxt.get("timing", "unknown"), "timing_text": TIMING_TEXT.get(nxt.get("timing") or "unknown"),
                    "days_until": (d - today).days, "eps_estimate": nxt.get("eps_estimate"),
                    "avg_move_%": move.get("avg_abs_move_%"), "reports_measured": len(move.get("moves") or []),
                    "pick": bool(f.get("pick")), "watchlist": bool(f.get("watchlist")), "held": bool(f.get("held"))})
    out.sort(key=lambda r: (r["date"], {"before_open": 0, "during": 1, "after_close": 2}.get(r["timing"], 3), r["symbol"]))
    return out


def alert_phase(nxt: dict | None, now: datetime, tz: str = "Europe/Paris", start_hour: int = 8) -> str | None:
    """"tomorrow" when it is the day before the report in the owner's time zone (from `start_hour`, so nobody
    is woken at midnight); "today" as a catch-up on the report day, only while the report is still more than an
    hour away (its time known). None otherwise.

    The report date is the exchange's (New York) date. Paris is 6 h ahead: a report before the US open at 07:00
    New York is at 13:00 in Paris on the same date, and one after the close (16:00) is at 22:00 Paris."""
    if not nxt or not nxt.get("date"):
        return None
    d = date.fromisoformat(nxt["date"])
    local = now.astimezone(ZoneInfo(tz))
    if local.date() == d - timedelta(days=1) and local.hour >= start_hour:
        return "tomorrow"
    if local.date() == d and nxt.get("time"):
        at = pd.Timestamp(nxt["time"]).to_pydatetime()
        if now < at - timedelta(hours=1):
            return "today"
    return None


def alert_text(symbol: str, name: str, nxt: dict, phase: str, reasons: list[str],
               move: dict | None = None) -> str:
    when = {"before_open": "before the open", "after_close": "after the close",
            "during": "during market hours"}.get(nxt.get("timing") or "", "")
    head = f"[EARNINGS {phase.upper()}] {symbol}" + (f" ({name})" if name and name != symbol else "")
    head += f" reports {when}." if when else f" reports {'tomorrow' if phase == 'tomorrow' else 'today'} (time not announced)."
    lines = [head]
    if move and move.get("moves"):
        n = len(move["moves"])
        avg, last = move["avg_abs_move_%"], f"last {n} report{'s' if n > 1 else ''}"
        lines.append(f"  Big moves are common ({last}: avg ±{avg:.1f}%)." if avg >= 4
                     else f"  Typical move after its results: ±{avg:.1f}% ({last}), and it can be bigger.")
    else:
        lines.append("  Prices often jump or drop sharply right after results.")
    if nxt.get("eps_estimate") is not None:
        lines.append(f"  Analysts expect earnings of {nxt['eps_estimate']:.2f} per share.")
    if reasons:
        lines.append(f"  Why you get this: {', '.join(reasons)}.")
    return "\n".join(lines)
