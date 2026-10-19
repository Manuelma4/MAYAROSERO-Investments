import numpy as np
import pandas as pd

from tradebot import indicators as ta


def test_rsi_bounds(ohlcv):
    r = ta.rsi(ohlcv["close"]).dropna()
    assert r.between(0, 100).all()


def test_rsi_extremes():
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert ta.rsi(up).iloc[-1] == 100


def test_atr_positive(ohlcv):
    assert (ta.atr(ohlcv) > 0).all()


def test_macd_hist(ohlcv):
    m = ta.macd(ohlcv["close"])
    assert np.allclose(m["hist"], m["macd"] - m["signal"])
