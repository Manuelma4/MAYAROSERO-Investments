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
