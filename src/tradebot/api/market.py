"""Market data access for the API, with a small TTL cache to avoid hammering providers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pandas as pd

from ..data import DataProvider, get_provider

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

    def history(self, provider: str, symbol: str, timeframe: str, *, exchange: str = "binance",
                start: str | None = None, end: str | None = None, limit: int | None = None) -> pd.DataFrame:
        key = (provider, exchange, symbol, timeframe, start, end, limit)
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
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
