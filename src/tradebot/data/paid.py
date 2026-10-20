"""Paid real-time stock data: Polygon.io, Alpaca Market Data and Finnhub.

Selected with ``MARKET_DATA_PROVIDER`` (yahoo | polygon | alpaca | finnhub) plus that
provider's key in ``.env``. Without a key (or with ``yahoo``) nothing changes: stocks keep
coming from Yahoo. With a key, stock requests go to the paid feed and fall back to Yahoo for
that call whenever the feed fails (HTTP error, rate limit, bad key, symbol it does not cover).

Every adapter returns the same normalized OHLCV frame as :class:`YahooProvider` and shapes
the bars the same way Yahoo does, so strategies cannot tell the sources apart:

- intraday bars are limited to the regular US session (09:30-16:00 New York) unless
  ``MARKET_DATA_EXTENDED_HOURS=1``; hourly bars start at :30 like Yahoo's;
- daily bars are indexed by the session date at 00:00 UTC, weekly bars by the Monday;
- prices are split-adjusted (Alpaca: split + dividend adjusted, like Yahoo's auto_adjust).

Only plain US tickers (``AAPL``, ``BRK-B``) go to the paid feed. Indices (``^GSPC``), foreign
listings (``MC.PA``), forex and Yahoo crypto pairs always use Yahoo.

Check a key from a shell: ``python -m tradebot.data.paid AAPL``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from .providers import OHLCV, DataProvider, YahooProvider, normalize, resample

log = logging.getLogger(__name__)

NY = "America/New_York"
TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk")
PAID_PROVIDERS = ("polygon", "alpaca", "finnhub")

# What each requested timeframe is built from (fetched natively, then reshaped like Yahoo).
_NATIVE = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "30m", "4h": "30m",
           "1d": "1d", "1wk": "1d"}
# Regular-session bars per trading day, used to size the request window from ``limit``.
_BARS_PER_DAY = {"1m": 390, "5m": 78, "15m": 26, "30m": 13, "1h": 7, "4h": 2, "1d": 1, "1wk": 0.2}
# Window when neither start nor limit is given (mirrors Yahoo's intraday limits).
_DEFAULT_DAYS = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 730, "4h": 730,
                 "1d": 365 * 20, "1wk": 365 * 20}

# Plain US tickers, with an optional share class written Yahoo style (BRK-B).
_US_TICKER = re.compile(r"^[A-Z]{1,5}(?:-[A-Z])?$")


class ProviderError(RuntimeError):
    """The paid provider failed for this request."""


class MissingCredentials(ProviderError):
    """No API key configured for the selected provider."""


class AuthError(ProviderError):
    """Key rejected or the plan does not include this data (HTTP 401/403)."""


class RateLimited(ProviderError):
    """HTTP 429 even after backing off."""


_warned: set[str] = set()
_warn_lock = threading.Lock()


def _warn_once(key: str, msg: str, *args) -> None:
    with _warn_lock:
        first = key not in _warned
        _warned.add(key)
    (log.warning if first else log.debug)(msg, *args)


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def supports(symbol: str) -> bool:
    """True for symbols the paid US stock feeds cover (not indices, foreign listings, forex, crypto)."""
    return bool(_US_TICKER.match(symbol or ""))


def vendor_symbol(symbol: str) -> str:
    """Yahoo style -> vendor style: BRK-B -> BRK.B (same for all three providers)."""
    return symbol.upper().replace("-", ".")


def _frame(rows: list[tuple]) -> pd.DataFrame:
    """Rows of (timestamp, open, high, low, close, volume) -> normalized OHLCV frame."""
    if not rows:
        return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([], tz="UTC", name="time"), dtype=float)
    df = pd.DataFrame(rows, columns=["time", *OHLCV]).set_index("time")
    df.index = pd.DatetimeIndex(df.index)
    return normalize(df)


def _session_dates(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Daily bar timestamps -> session date at 00:00 UTC (Yahoo's daily index)."""
    if len(idx) and (idx == idx.normalize()).all():
        return idx  # already midnight UTC (Finnhub)
    local = idx.tz_convert(NY)
    return pd.DatetimeIndex(local.tz_localize(None).normalize()).tz_localize("UTC")


def _regular_session(df: pd.DataFrame) -> pd.DataFrame:
    local = df.index.tz_convert(NY)
    minutes = local.hour * 60 + local.minute
    keep = (minutes >= 9 * 60 + 30) & (minutes < 16 * 60) & (local.dayofweek < 5)
    return df[keep]


def _agg(df: pd.DataFrame, rule: str, **kw) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample(rule, **kw).agg(agg).dropna()


class PaidProvider(DataProvider):
    """Shared HTTP plumbing (auth, retries on 429, throttle) and Yahoo-compatible bar shaping."""

    name = "paid"
    base_url = ""

    def __init__(self, *, session: requests.Session | None = None, timeout: float = 10.0,
                 max_retries: int = 3, backoff: float = 0.5, max_rpm: int | None = None,
                 extended_hours: bool = False, live_daily: bool = True, max_workers: int = 8,
                 base_url: str | None = None):
        # requests honors HTTPS_PROXY / REQUESTS_CA_BUNDLE from the environment by default.
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.extended_hours = extended_hours
        self.live_daily = live_daily
        self.max_workers = max_workers
        if base_url:
            self.base_url = base_url.rstrip("/")
        self._min_interval = 60.0 / max_rpm if max_rpm else 0.0
        self._next_slot = 0.0
        self._throttle_lock = threading.Lock()

    # --- HTTP -----------------------------------------------------------------------------
    def _auth(self) -> tuple[dict, dict]:
        """(headers, query params) carrying the credentials."""
        return {}, {}

    def _throttle(self) -> None:
        if not self._min_interval:
            return
        with self._throttle_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._min_interval
        if wait > 0:
            time.sleep(wait)

    def _get(self, url: str, params: Mapping | None = None) -> dict | list:
        if not url.startswith("http"):
            url = self.base_url + url
        headers, auth_params = self._auth()
        params = {**(params or {}), **auth_params}
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                raise ProviderError(f"{self.name}: network error: {exc}") from exc
            code = resp.status_code
            if code == 429:
                if attempt < self.max_retries:
                    try:
                        wait = float(resp.headers.get("Retry-After", ""))
                    except ValueError:
                        wait = self.backoff * 2 ** attempt
                    time.sleep(min(max(wait, 0.0), 10.0))
                    continue
                raise RateLimited(f"{self.name}: rate limited (HTTP 429)")
            if code in (401, 403):
                raise AuthError(f"{self.name}: HTTP {code} (key rejected or not in your plan): "
                                f"{resp.text[:200]}")
            if code >= 400:
                raise ProviderError(f"{self.name}: HTTP {code}: {resp.text[:200]}")
            try:
                return resp.json()
            except ValueError as exc:
                raise ProviderError(f"{self.name}: invalid JSON response") from exc
        raise RateLimited(f"{self.name}: rate limited (HTTP 429)")  # pragma: no cover

    # --- vendor hooks ---------------------------------------------------------------------
    def _fetch(self, ticker: str, native: str, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.DataFrame:
        raise NotImplementedError

    def _fetch_many(self, tickers: list[str], native: str, t0: pd.Timestamp,
                    t1: pd.Timestamp) -> dict[str, pd.DataFrame]:
        """Default batch: parallel single requests; stop early on bad key / rate limit."""
        stop = threading.Event()
        fatal: list[Exception] = []

        def one(t):
            if stop.is_set():
                return t, None
            try:
                return t, self._fetch(t, native, t0, t1)
            except (AuthError, RateLimited) as exc:
                stop.set()
                fatal.append(exc)
            except Exception as exc:  # one bad symbol must not sink the batch
                log.debug("%s: %s failed: %s", self.name, t, exc)
            return t, None

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            out = {t: df for t, df in pool.map(one, tickers) if df is not None}
        if fatal and not out:
            raise fatal[0]
        return out

    def _today_bars(self, tickers: list[str]) -> dict[str, tuple]:
        """Live daily bar per ticker from a snapshot: {ticker: (session date UTC, o, h, l, c, v)}."""
        return {}

    def last_trade(self, symbol: str) -> dict:
        """Most recent trade: {"symbol", "price", "size", "time"}."""
        raise NotImplementedError

    # --- shaping --------------------------------------------------------------------------
    def _window(self, timeframe, start, end, limit) -> tuple[pd.Timestamp, pd.Timestamp]:
        t1 = _ts(end) if end else pd.Timestamp.now(tz="UTC")
        if start:
            return _ts(start), t1
        if limit:
            trading_days = limit / _BARS_PER_DAY[timeframe]
            days = int(trading_days * 7 / 5 * 1.1) + 7
        else:
            days = _DEFAULT_DAYS[timeframe]
        return t1 - pd.Timedelta(days=days), t1

    def _shape(self, df: pd.DataFrame, timeframe: str, today: tuple | None = None) -> pd.DataFrame:
        native = _NATIVE[timeframe]
        if df.empty:
            return df
        if native == "1d":
            df = df.copy()
            df.index = _session_dates(df.index)
            df.index.name = "time"
            df = df[~df.index.duplicated(keep="last")]
            if today is not None:
                df = self._patch_today(df, today)
            if timeframe == "1wk":
                df = _agg(df, "W-MON", label="left", closed="left")
            return df
        if not self.extended_hours:
            df = _regular_session(df)
        if timeframe in ("1h", "4h"):
            df = _agg(df, "1h", offset="30min")  # Yahoo's hourly bars start at :30
        if timeframe == "4h":
            df = resample(df, "4h")  # same as YahooProvider
        return df

    @staticmethod
    def _patch_today(df: pd.DataFrame, today: tuple) -> pd.DataFrame:
        day, o, h, l, c, v = today
        if not c or not o:
            return df
        if len(df) and day < df.index[-1]:
            return df
        df = df.copy()
        df.loc[day, OHLCV] = [float(o), float(h), float(l), float(c), float(v)]
        return df.sort_index()

    @staticmethod
    def _clip(df: pd.DataFrame, start, end, limit) -> pd.DataFrame:
        if start:
            df = df[df.index >= _ts(start)]
        if end:
            df = df[df.index < _ts(end)]
        return df.tail(limit) if limit else df

    def _live_today(self, tickers: list[str], timeframe: str, end) -> dict[str, tuple]:
        if end or not self.live_daily or _NATIVE[timeframe] != "1d":
            return {}
        try:
            return self._today_bars(tickers)
        except Exception as exc:  # the snapshot is a bonus; history is still valid without it
            log.debug("%s: snapshot failed: %s", self.name, exc)
            return {}

    # --- DataProvider ---------------------------------------------------------------------
    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        if timeframe not in _NATIVE:
            raise ValueError(f"{self.name} does not support timeframe {timeframe}")
        if not supports(symbol):
            raise ValueError(f"{self.name} does not cover {symbol}")
        ticker = vendor_symbol(symbol)
        t0, t1 = self._window(timeframe, start, end, limit)
        raw = self._fetch(ticker, _NATIVE[timeframe], t0, t1)
        today = self._live_today([ticker], timeframe, end).get(ticker)
        df = self._clip(self._shape(raw, timeframe, today), start, end, limit)
        if df.empty:
            raise ValueError(f"No data from {self.name} for {symbol} {timeframe}")
        return df

    def history_many(self, symbols: list[str], timeframe: str = "1d", start: str | None = None,
                     limit: int | None = None, end: str | None = None, **_) -> dict[str, pd.DataFrame]:
        if timeframe not in _NATIVE:
            raise ValueError(f"{self.name} does not support timeframe {timeframe}")
        by_ticker = {vendor_symbol(s): s for s in symbols if supports(s)}
        if not by_ticker:
            return {}
        t0, t1 = self._window(timeframe, start, end, limit)
        raw = self._fetch_many(list(by_ticker), _NATIVE[timeframe], t0, t1)
        today = self._live_today(list(raw), timeframe, end)
        out: dict[str, pd.DataFrame] = {}
        for ticker, df in raw.items():
            df = self._clip(self._shape(df, timeframe, today.get(ticker)), start, end, limit)
            if len(df) and ticker in by_ticker:
                out[by_ticker[ticker]] = df
        return out


# --- Polygon.io --------------------------------------------------------------------------------

class PolygonProvider(PaidProvider):
    """Polygon.io stocks REST: /v2/aggs (bars), /v2/snapshot (live day bar), /v2/last/trade."""

    name = "polygon"
    base_url = "https://api.polygon.io"
    _SPAN = {"1m": (1, "minute"), "5m": (5, "minute"), "15m": (15, "minute"), "30m": (30, "minute"),
             "1d": (1, "day")}

    def __init__(self, api_key: str | None, **kw):
        if not api_key:
            raise MissingCredentials("POLYGON_API_KEY is not set")
        self.api_key = api_key
        super().__init__(**kw)

    def _auth(self):
        return {"Authorization": f"Bearer {self.api_key}"}, {}

    def _fetch(self, ticker, native, t0, t1):
        mult, span = self._SPAN[native]
        url = (f"/v2/aggs/ticker/{ticker}/range/{mult}/{span}/"
               f"{int(t0.timestamp() * 1000)}/{int(t1.timestamp() * 1000)}")
        params: dict | None = {"adjusted": "true", "sort": "asc", "limit": 50000}
        rows: list[tuple] = []
        for _ in range(50):  # pagination guard
            data = self._get(url, params)
            if data.get("status") == "ERROR":
                raise ProviderError(f"polygon: {data.get('error') or data.get('message')}")
            for b in data.get("results") or []:
                rows.append((pd.Timestamp(b["t"], unit="ms", tz="UTC"),
                             b["o"], b["h"], b["l"], b["c"], b.get("v", 0.0)))
            url, params = data.get("next_url"), None
            if not url:
                break
        return _frame(rows)

    def _today_bars(self, tickers):
        out: dict[str, tuple] = {}
        for i in range(0, len(tickers), 250):
            chunk = tickers[i:i + 250]
            data = self._get("/v2/snapshot/locale/us/markets/stocks/tickers",
                             {"tickers": ",".join(chunk)})
            for snap in data.get("tickers") or []:
                bar = _polygon_day(snap)
                if bar:
                    out[snap["ticker"]] = bar
        return out

    def last_trade(self, symbol):
        data = self._get(f"/v2/last/trade/{vendor_symbol(symbol)}")
        r = data.get("results") or {}
        if "p" not in r:
            raise ValueError(f"No last trade from polygon for {symbol}")
        return {"symbol": symbol, "price": float(r["p"]), "size": float(r.get("s") or 0),
                "time": pd.Timestamp(r["t"], unit="ns", tz="UTC").isoformat()}


def _polygon_day(snap: dict) -> tuple | None:
    day = snap.get("day") or {}
    if not day.get("c") or not day.get("o"):
        return None
    stamp = snap.get("updated") or (snap.get("lastTrade") or {}).get("t")
    if not stamp:
        return None
    date = _session_dates(pd.DatetimeIndex([pd.Timestamp(stamp, unit="ns", tz="UTC")]))[0]
    o, h, l, c, v = day["o"], day["h"], day["l"], day["c"], day.get("v", 0.0)
    last = (snap.get("lastTrade") or {}).get("p")
    if last:
        c, h, l = last, max(h, last), min(l, last)
    return date, o, h, l, c, v


# --- Alpaca Market Data ------------------------------------------------------------------------

class AlpacaProvider(PaidProvider):
    """Alpaca Market Data v2: /v2/stocks/bars (multi-symbol), /snapshots, /trades/latest."""

    name = "alpaca"
    base_url = "https://data.alpaca.markets"
    _TF = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1d": "1Day"}

    def __init__(self, key_id: str | None, secret: str | None, feed: str = "iex", **kw):
        if not key_id or not secret:
            raise MissingCredentials("ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not set")
        self.key_id, self.secret = key_id, secret
        self.feed = (feed or "iex").lower()
        if self.feed not in ("iex", "sip", "delayed_sip"):
            raise ValueError(f"ALPACA_DATA_FEED must be iex or sip, not {feed!r}")
        super().__init__(**kw)

    def _auth(self):
        return {"APCA-API-KEY-ID": self.key_id, "APCA-API-SECRET-KEY": self.secret}, {}

    @staticmethod
    def _rfc3339(t: pd.Timestamp) -> str:
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _fetch(self, ticker, native, t0, t1):
        df = self._fetch_many([ticker], native, t0, t1).get(ticker)
        return df if df is not None else _frame([])

    def _fetch_many(self, tickers, native, t0, t1):
        rows: dict[str, list[tuple]] = {}
        for i in range(0, len(tickers), 100):
            params = {"symbols": ",".join(tickers[i:i + 100]), "timeframe": self._TF[native],
                      "start": self._rfc3339(t0), "end": self._rfc3339(t1), "limit": 10000,
                      "adjustment": "all", "feed": self.feed, "sort": "asc"}
            for _ in range(500):  # pagination guard
                data = self._get("/v2/stocks/bars", params)
                for sym, bars in (data.get("bars") or {}).items():
                    dest = rows.setdefault(sym, [])
                    for b in bars or []:
                        dest.append((pd.Timestamp(b["t"]), b["o"], b["h"], b["l"], b["c"], b.get("v", 0.0)))
                token = data.get("next_page_token")
                if not token:
                    break
                params = {**params, "page_token": token}
        return {sym: _frame(r) for sym, r in rows.items() if r}

    def _today_bars(self, tickers):
        out: dict[str, tuple] = {}
        for i in range(0, len(tickers), 100):
            data = self._get("/v2/stocks/snapshots",
                             {"symbols": ",".join(tickers[i:i + 100]), "feed": self.feed})
            for sym, snap in (data or {}).items():
                bar = (snap or {}).get("dailyBar") or {}
                if not bar.get("c"):
                    continue
                date = _session_dates(pd.DatetimeIndex([pd.Timestamp(bar["t"])]))[0]
                o, h, l, c, v = bar["o"], bar["h"], bar["l"], bar["c"], bar.get("v", 0.0)
                trade = snap.get("latestTrade") or {}
                if trade.get("p") and trade.get("t") and pd.Timestamp(trade["t"]) >= pd.Timestamp(bar["t"]):
                    c = trade["p"]
                    h, l = max(h, c), min(l, c)
                out[sym] = (date, o, h, l, c, v)
        return out

    def last_trade(self, symbol):
        ticker = vendor_symbol(symbol)
        data = self._get("/v2/stocks/trades/latest", {"symbols": ticker, "feed": self.feed})
        t = (data.get("trades") or {}).get(ticker)
        if not t:
            raise ValueError(f"No last trade from alpaca for {symbol}")
        return {"symbol": symbol, "price": float(t["p"]), "size": float(t.get("s") or 0),
                "time": pd.Timestamp(t["t"]).tz_convert("UTC").isoformat()}


# --- Finnhub -----------------------------------------------------------------------------------

class FinnhubProvider(PaidProvider):
    """Finnhub: /stock/candle (bars, paid plans) and /quote (real-time last price)."""

    name = "finnhub"
    base_url = "https://finnhub.io/api/v1"
    _RES = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1d": "D"}

    def __init__(self, api_key: str | None, **kw):
        if not api_key:
            raise MissingCredentials("FINNHUB_API_KEY is not set")
        self.api_key = api_key
        super().__init__(**kw)

    def _auth(self):
        return {"X-Finnhub-Token": self.api_key}, {}

    def _fetch(self, ticker, native, t0, t1):
        data = self._get("/stock/candle", {"symbol": ticker, "resolution": self._RES[native],
                                           "from": int(t0.timestamp()), "to": int(t1.timestamp())})
        if data.get("s") == "no_data":
            return _frame([])
        if data.get("s") != "ok":
            raise ProviderError(f"finnhub: {data.get('error') or data.get('s')}")
        ts = pd.to_datetime(data["t"], unit="s", utc=True)
        vols = data.get("v") or [0.0] * len(ts)
        return _frame(list(zip(ts, data["o"], data["h"], data["l"], data["c"], vols)))

    def quote(self, symbol: str) -> dict:
        data = self._get("/quote", {"symbol": vendor_symbol(symbol)})
        if not data.get("c") or not data.get("t"):
            raise ValueError(f"No quote from finnhub for {symbol}")
        return data

    def _today_bars(self, tickers):
        # One request per symbol; only worth it for single-symbol calls.
        if len(tickers) != 1:
            return {}
        q = self.quote(tickers[0])
        date = _session_dates(pd.DatetimeIndex([pd.Timestamp(q["t"], unit="s", tz="UTC")]))[0]
        # Finnhub's daily candles are stamped 00:00 UTC; the quote time is intraday, so align by NY date.
        return {tickers[0]: (date, q["o"], q["h"], q["l"], q["c"], 0.0)}

    def _patch_today(self, df, today):  # the quote has no volume: keep the candle's if present
        day = today[0]
        if day in df.index:
            today = (*today[:5], float(df.at[day, "volume"]))
        return super()._patch_today(df, today)

    def last_trade(self, symbol):
        q = self.quote(symbol)
        return {"symbol": symbol, "price": float(q["c"]), "size": None,
                "time": pd.Timestamp(q["t"], unit="s", tz="UTC").isoformat()}


# --- fallback + selection ----------------------------------------------------------------------

class FallbackProvider(DataProvider):
    """Paid feed first, Yahoo for anything it can't serve. Never raises because of the paid feed."""

    AUTH_COOLDOWN = 15 * 60  # bad key / plan: stop asking for a while
    RATE_COOLDOWN = 60

    def __init__(self, primary: PaidProvider, fallback: DataProvider | None = None):
        self.primary = primary
        self.fallback = fallback or YahooProvider()
        self._paused_until = 0.0
        self.last_error: str | None = None

    @property
    def name(self) -> str:
        return self.primary.name

    def _active(self) -> bool:
        return time.time() >= self._paused_until

    def _failed(self, exc: Exception, what: str) -> None:
        self.last_error = str(exc)
        if isinstance(exc, (AuthError, MissingCredentials)):
            self._paused_until = time.time() + self.AUTH_COOLDOWN
        elif isinstance(exc, RateLimited):
            self._paused_until = time.time() + self.RATE_COOLDOWN
        _warn_once(f"{self.primary.name}:{type(exc).__name__}",
                   "%s failed for %s, using Yahoo instead: %s", self.primary.name, what, exc)

    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        if supports(symbol) and timeframe in _NATIVE and self._active():
            try:
                return self.primary.history(symbol, timeframe, start=start, end=end, limit=limit)
            except Exception as exc:
                self._failed(exc, f"{symbol} {timeframe}")
        return self.fallback.history(symbol, timeframe, start=start, end=end, limit=limit)

    def history_many(self, symbols: list[str], timeframe: str = "1d", start: str | None = None,
                     limit: int | None = None, **kw) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        paid = [s for s in symbols if supports(s)]
        if paid and timeframe in _NATIVE and self._active():
            try:
                out = self.primary.history_many(paid, timeframe, start=start, limit=limit, **kw)
            except Exception as exc:
                self._failed(exc, f"{len(paid)} symbols {timeframe}")
                out = {}
        rest = [s for s in symbols if s not in out]
        if rest:
            if hasattr(self.fallback, "history_many"):
                out.update(self.fallback.history_many(rest, timeframe, start=start, limit=limit, **kw))
            else:  # pragma: no cover - YahooProvider has history_many
                for s in rest:
                    try:
                        out[s] = self.fallback.history(s, timeframe, start=start, limit=limit)
                    except Exception:
                        pass
        return out

    def last_trade(self, symbol: str) -> dict:
        if supports(symbol) and self._active():
            try:
                return self.primary.last_trade(symbol)
            except Exception as exc:
                self._failed(exc, f"{symbol} last trade")
        df = self.fallback.history(symbol, "1m", limit=1)
        return {"symbol": symbol, "price": float(df["close"].iloc[-1]), "size": None,
                "time": df.index[-1].isoformat()}


def _flag(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def build_paid_provider(name: str, env: Mapping[str, str] | None = None, **kw) -> PaidProvider:
    """One paid adapter from environment variables. Raises MissingCredentials without a key."""
    env = os.environ if env is None else env
    name = name.strip().lower()
    opts = {"extended_hours": _flag(env.get("MARKET_DATA_EXTENDED_HOURS"))}
    if rpm := (env.get("MARKET_DATA_MAX_RPM") or "").strip():
        opts["max_rpm"] = int(rpm)
    opts.update(kw)
    if name == "polygon":
        return PolygonProvider(env.get("POLYGON_API_KEY"), base_url=env.get("POLYGON_BASE_URL"), **opts)
    if name == "alpaca":
        return AlpacaProvider(env.get("ALPACA_API_KEY_ID"), env.get("ALPACA_API_SECRET_KEY"),
                              feed=env.get("ALPACA_DATA_FEED") or "iex", **opts)
    if name == "finnhub":
        return FinnhubProvider(env.get("FINNHUB_API_KEY"), **opts)
    raise ValueError(f"Unknown paid provider: {name}")


def stock_provider_from_env(env: Mapping[str, str] | None = None,
                            yahoo_factory: Callable[[], DataProvider] = YahooProvider) -> DataProvider:
    """The stock data source for the app: Yahoo, or the configured paid feed with Yahoo fallback."""
    env = os.environ if env is None else env
    choice = (env.get("MARKET_DATA_PROVIDER") or "yahoo").strip().lower()
    if choice in ("", "yahoo", "yfinance", "free"):
        return yahoo_factory()
    if choice not in PAID_PROVIDERS:
        _warn_once(f"unknown:{choice}", "MARKET_DATA_PROVIDER=%r is not one of yahoo/%s; using Yahoo",
                   choice, "/".join(PAID_PROVIDERS))
        return yahoo_factory()
    try:
        primary = build_paid_provider(choice, env)
    except (MissingCredentials, ValueError) as exc:
        _warn_once(f"config:{choice}", "MARKET_DATA_PROVIDER=%s but %s; using Yahoo", choice, exc)
        return yahoo_factory()
    log.info("Stock market data: %s (Yahoo as fallback)", choice)
    return FallbackProvider(primary, yahoo_factory())


def describe_stock_source(env: Mapping[str, str] | None = None) -> dict:
    """Plain summary for a status screen: which feed is configured and whether it has a key."""
    env = os.environ if env is None else env
    choice = (env.get("MARKET_DATA_PROVIDER") or "yahoo").strip().lower()
    if choice not in PAID_PROVIDERS:
        return {"provider": "yahoo", "realtime": False, "note": "Free Yahoo data, about 15 minutes delayed"}
    try:
        build_paid_provider(choice, env)
    except (MissingCredentials, ValueError) as exc:
        return {"provider": "yahoo", "realtime": False, "note": f"{choice} selected but {exc}"}
    return {"provider": choice, "realtime": True, "note": f"{choice} real-time feed, Yahoo as fallback"}


def main(argv: list[str] | None = None) -> int:
    """``python -m tradebot.data.paid AAPL``: call the configured paid feed directly (no fallback)."""
    import sys

    args = sys.argv[1:] if argv is None else argv
    symbol = args[0] if args else "AAPL"
    choice = (os.environ.get("MARKET_DATA_PROVIDER") or "yahoo").strip().lower()
    if choice not in PAID_PROVIDERS:
        print(f"MARKET_DATA_PROVIDER={choice!r}: no paid feed selected, the app uses Yahoo.")
        return 1
    try:
        prov = build_paid_provider(choice)
        bars = prov.history(symbol, "5m", limit=3)
        trade = prov.last_trade(symbol)
    except Exception as exc:
        print(f"FAILED: {choice} could not serve {symbol}: {exc}")
        return 2
    print(f"OK: {choice} works. Last 3 five-minute bars for {symbol}:")
    print(bars.to_string())
    print(f"Last trade: {trade['price']} at {trade['time']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
