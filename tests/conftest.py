import os

# One OpenMP thread per test process: the ML models otherwise oversubscribe the CPU and slow to a crawl
# when several processes share a small machine. Must be set before numpy / scikit-learn load.
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import pytest


def make_ohlcv(n=1500, seed=0, drift=0.0003, vol=0.015, freq="1D", cycle=0.01):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n) + cycle * np.sin(np.arange(n) / 40)
    close = 100 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol_ = rng.lognormal(10, 0.4, n)
    idx = pd.date_range("2018-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol_}, index=idx)


@pytest.fixture
def ohlcv():
    return make_ohlcv()


def fake_earnings(symbol: str) -> dict:
    """Deterministic offline stand-in for Yahoo's earnings calendar (no network in tests): the next report
    within ~3 weeks, alternating before the open / after the close, and six past quarterly reports."""
    import zlib
    from datetime import datetime, timedelta, timezone

    from tradebot.data import earnings as er

    if not er.applicable(symbol):
        return {**er.unknown(symbol), "status": "none"}
    seed = zlib.crc32(symbol.encode())
    today = datetime.now(timezone.utc).astimezone(er.NY).date()
    timing = "before_open" if seed % 2 else "after_close"
    hour = "07:00:00" if timing == "before_open" else "16:00:00"

    def ev(d, past):
        ts = pd.Timestamp(f"{d.isoformat()} {hour}", tz=er.NY)
        e = {"date": d.isoformat(), "time": ts.tz_convert("UTC").isoformat(), "timing": timing, "eps_estimate": 1.2}
        if past:
            e.update(eps_actual=1.3, surprise_pct=8.3)
        return e

    nxt = today + timedelta(days=int(seed % 21))
    history = [ev(nxt - timedelta(days=91 * k), True) for k in range(1, 7)]
    return {"symbol": symbol, "status": "ok", "next": ev(nxt, False), "last": history[0], "history": history}


@pytest.fixture(autouse=True, scope="session")
def _offline_earnings():
    """The earnings calendar must never call Yahoo from the test suite (precompute runs refresh it)."""
    from tradebot.data import earnings as er

    mp = pytest.MonkeyPatch()
    mp.setattr(er, "FETCH", fake_earnings)
    mp.setattr(er, "PAUSE", 0.0)
    yield
    mp.undo()


def fake_fundamentals(symbol: str) -> dict | None:
    """Deterministic offline stand-in for Yahoo's `Ticker.info` (parsed): market values from 5bn to 3tn,
    P/E from losses (None) to 60, about two thirds paying a dividend."""
    import zlib

    seed = zlib.crc32(symbol.encode())
    pe = None if seed % 9 == 0 else 6.0 + seed % 55
    return {"name": symbol, "market_cap": float(5e9 * (1.0 + seed % 600)), "currency": "USD", "pe": pe,
            "forward_pe": None if pe is None else pe * 0.9, "eps": -1.0 if pe is None else 3.0,
            "dividend_yield": 0.0 if seed % 3 == 0 else round((seed % 50) / 10, 2), "beta": 0.5 + (seed % 15) / 10,
            "sector_yahoo": None, "industry_yahoo": None}


@pytest.fixture(autouse=True, scope="session")
def _offline_fundamentals():
    """The screener's daily fundamentals must never call Yahoo from the test suite."""
    from tradebot.data import fundamentals as fd

    mp = pytest.MonkeyPatch()
    mp.setattr(fd, "FETCH", fake_fundamentals)
    mp.setattr(fd, "PAUSE", 0.0)
    mp.setattr(fd, "BACKOFF", 0.0)
    yield
    mp.undo()
