"""Market data providers.

Every provider returns a DataFrame indexed by UTC timestamp with the columns
``open, high, low, close, volume``. Strategies, the backtester and the live
scanner only ever see this normalized format.

- Stocks / indices / ETFs / forex: Yahoo Finance (free, intraday data is
  delayed ~15 min for many exchanges; fine for analysis and swing trading).
- Crypto: any exchange supported by ccxt (real-time, public endpoints, no
  API key needed for market data).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]

# yfinance keeps shared module state during downloads; concurrent calls can mix results.
_YF_LOCK = threading.Lock()


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    df = df[OHLCV].astype(float)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.index.name = "time"
    return df[~df.index.duplicated(keep="last")].sort_index().dropna()


class DataProvider(ABC):
    @abstractmethod
    def history(self, symbol: str, timeframe: str, start: str | None = None,
                end: str | None = None, limit: int | None = None) -> pd.DataFrame:
        """Historical candles."""

    def latest(self, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
        """Most recent candles (used by the live scanner)."""
        return self.history(symbol, timeframe, limit=limit)


class YahooProvider(DataProvider):
    # yfinance intervals; intraday history is limited (1m: 7 days, <1h: 60 days, 1h: 730 days)
    _PERIOD_FOR = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
                   "1h": "730d", "4h": "730d", "1d": "max", "1wk": "max"}

    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        import yfinance as yf

        interval = "1h" if timeframe == "4h" else timeframe
        kwargs = {"interval": interval, "auto_adjust": True, "progress": False,
                  "multi_level_index": False}
        if start:
            kwargs.update(start=start, end=end)
        elif limit and timeframe in ("1d", "1wk"):
            # Only download what's needed (~1.5 calendar days per trading day).
            days = int(limit * (7 if timeframe == "1wk" else 1) * 1.5) + 10
            kwargs["period"] = f"{days}d"
        else:
            kwargs["period"] = self._PERIOD_FOR.get(timeframe, "max")
        with _YF_LOCK:
            raw = yf.download(symbol, **kwargs)
        if raw.empty:
            raise ValueError(f"No data from Yahoo for {symbol} {timeframe}")
        df = normalize(raw)
        if timeframe == "4h":
            df = resample(df, "4h")
        return df.tail(limit) if limit else df


    def history_many(self, symbols: list[str], timeframe: str = "1d", start: str | None = None,
                     limit: int | None = None) -> dict[str, pd.DataFrame]:
        """One batched Yahoo request for many symbols (much faster than one call each)."""
        import yfinance as yf

        kwargs = {"interval": timeframe, "auto_adjust": True, "progress": False, "group_by": "ticker",
                  "threads": True}
        if start:
            kwargs["start"] = start
        else:
            days = int((limit or 300) * (7 if timeframe == "1wk" else 1) * 1.5) + 10
            kwargs["period"] = f"{days}d"
        with _YF_LOCK:
            raw = yf.download(symbols, **kwargs)
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                sub = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = normalize(sub)
            except (KeyError, ValueError):
                continue
            if len(df):
                out[sym] = df.tail(limit) if limit else df
        return out


class CCXTProvider(DataProvider):
    def __init__(self, exchange: str = "binance"):
        import ccxt

        opts: dict = {"enableRateLimit": True}
        if exchange == "binance":
            # Spot market data only, via Binance's public data mirror: it serves the same
            # candles but isn't geo-blocked like api.binance.com (HTTP 451 from US servers).
            opts["options"] = {"defaultType": "spot", "fetchMarkets": ["spot"]}
        self.exchange = getattr(ccxt, exchange)(opts)
        # ccxt ignores the standard proxy environment variables; honor them explicitly.
        import os

        if proxy := os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
            self.exchange.httpsProxy = proxy
        if exchange == "binance":
            self.exchange.urls["api"]["public"] = "https://data-api.binance.vision/api/v3"

    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        since = self.exchange.parse8601(pd.Timestamp(start, tz="UTC").isoformat()) if start else None
        until = pd.Timestamp(end, tz="UTC") if end else None
        rows: list[list] = []
        page = 1000
        while True:
            want = page if limit is None else min(page, limit - len(rows))
            batch = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=want)
            if not batch:
                break
            rows.extend(batch)
            if since is None or len(batch) < want or (limit and len(rows) >= limit):
                break
            since = batch[-1][0] + 1
            if until is not None and pd.Timestamp(since, unit="ms", tz="UTC") >= until:
                break
        if not rows:
            raise ValueError(f"No data from {self.exchange.id} for {symbol} {timeframe}")
        df = pd.DataFrame(rows, columns=["ts", *OHLCV])
        df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
        df = normalize(df)
        if until is not None:
            df = df[df.index < until]
        return df.tail(limit) if limit else df


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample(rule).agg(agg).dropna()


def provider_for(symbol: str) -> str:
    """Guess the provider from the symbol: crypto pairs look like BASE/QUOTE."""
    return "ccxt" if "/" in symbol else "yahoo"


def get_provider(name: str, **kwargs) -> DataProvider:
    name = name.lower()
    if name in ("yahoo", "yfinance", "stocks"):
        return YahooProvider()
    if name in ("ccxt", "crypto"):
        return CCXTProvider(kwargs.get("exchange", "binance"))
    raise ValueError(f"Unknown provider: {name}")
