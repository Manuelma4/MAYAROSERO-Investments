"""Market data access for the API, with a small TTL cache to avoid hammering providers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from ..data import DataProvider, get_provider, provider_for

ProviderFactory = Callable[[str, str], DataProvider]


class DataUnavailable(RuntimeError):
    """Raised when a provider can't be reached or returns nothing."""


class MarketData:
    def __init__(self, provider_factory: ProviderFactory | None = None, ttl: int = 60):
        self._factory = provider_factory or (lambda name, exchange: get_provider(name, exchange=exchange))
        self._providers: dict[tuple[str, str], DataProvider] = {}
        self._cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
        self._lock = threading.Lock()
        self.ttl = ttl

    def provider(self, name: str, exchange: str = "binance") -> DataProvider:
        key = (name, exchange)
        with self._lock:
            if key not in self._providers:
                self._providers[key] = self._factory(name, exchange)
            return self._providers[key]

    def _ttl(self, timeframe: str) -> int:
        # Daily history barely changes intraday except the last bar: cache it longer.
        return self.ttl if timeframe not in ("1d", "1wk") else max(self.ttl, 300)

    def _cached(self, key) -> pd.DataFrame | None:
        with self._lock:
            hit = self._cache.get(key)
        return hit[1] if hit and time.time() - hit[0] < self._ttl(key[3]) else None

    def history(self, provider: str, symbol: str, timeframe: str, *, exchange: str = "binance",
                start: str | None = None, end: str | None = None, limit: int | None = None) -> pd.DataFrame:
        key = (provider, exchange, symbol, timeframe, start, end, limit)
        now = time.time()
        if (hit := self._cached(key)) is not None:
            return hit
        try:
            df = self.provider(provider, exchange).history(symbol, timeframe, start=start, end=end, limit=limit)
        except ValueError as exc:
            raise DataUnavailable(str(exc)) from exc
        except Exception as exc:  # network / exchange errors
            raise DataUnavailable(f"{provider} could not load {symbol} {timeframe}: {exc}") from exc
        if df.empty:
            raise DataUnavailable(f"No data for {symbol} {timeframe}")
        with self._lock:
            self._cache[key] = (now, df)
        return df

    def history_many(self, provider: str, symbols: list[str], timeframe: str = "1d", *,
                     exchange: str = "binance", start: str | None = None,
                     limit: int | None = None) -> dict[str, pd.DataFrame]:
        """Many symbols at once: batched when the provider supports it, else in parallel threads."""
        out: dict[str, pd.DataFrame] = {}
        missing = []
        for s in symbols:
            hit = self._cached((provider, exchange, s, timeframe, start, None, limit))
            if hit is not None:
                out[s] = hit
            else:
                missing.append(s)
        if not missing:
            return out
        prov = self.provider(provider, exchange)
        fetched: dict[str, pd.DataFrame] = {}
        if hasattr(prov, "history_many") and len(missing) > 1:
            try:
                fetched = prov.history_many(missing, timeframe, start=start, limit=limit)
            except Exception:
                fetched = {}
        rest = [s for s in missing if s not in fetched]

        def one(s):
            try:
                return s, prov.history(s, timeframe, start=start, limit=limit)
            except Exception:
                return s, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            for s, df in pool.map(one, rest):
                if df is not None and len(df):
                    fetched[s] = df
        now = time.time()
        with self._lock:
            for s, df in fetched.items():
                self._cache[(provider, exchange, s, timeframe, start, None, limit)] = (now, df)
        out.update(fetched)
        return out

    @staticmethod
    def _quote_from(symbol: str, provider: str, df: pd.DataFrame | None, spark_bars: int) -> dict:
        if df is None or df.empty:
            return {"symbol": symbol, "provider": provider, "error": f"No data for {symbol}"}
        close = df["close"]
        last = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else last
        return {
            "symbol": symbol, "provider": provider, "price": last,
            "change": last - prev, "change_pct": (last / prev - 1) * 100 if prev else 0.0,
            "time": df.index[-1].isoformat(),
            "spark": [float(x) for x in close.iloc[-spark_bars:]],
        }

    def quote(self, symbol: str, exchange: str = "binance", spark_bars: int = 30) -> dict:
        return self.quotes([symbol], exchange, spark_bars)[0]

    def quotes(self, symbols: list[str], exchange: str = "binance", spark_bars: int = 30) -> list[dict]:
        """Last price, daily change and sparkline per symbol (provider auto-detected from the symbol)."""
        groups: dict[str, list[str]] = {}
        for s in symbols:
            groups.setdefault(provider_for(s), []).append(s)
        data: dict[str, pd.DataFrame] = {}
        for provider, syms in groups.items():
            try:
                data.update(self.history_many(provider, syms, "1d", exchange=exchange, limit=spark_bars + 1))
            except Exception:
                pass
        return [self._quote_from(s, provider_for(s), data.get(s), spark_bars) for s in symbols]
