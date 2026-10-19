"""Features for the predictive model.

Every feature is computed from data available at the bar's close (strictly
backward looking). Prices are expressed as ratios / returns so a model can be
trained across symbols with different price levels.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ta
from ..analysis import candlesticks as cs
from ..analysis import dow


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    c, v = df["close"], df["volume"]
    logret = np.log(c).diff()
    a = ta.atr(df)
    f = pd.DataFrame(index=df.index)

    for n in (1, 3, 5, 10, 20, 60):
        f[f"ret_{n}"] = c.pct_change(n)
    for n in (10, 20, 60):
        f[f"vol_{n}"] = logret.rolling(n).std()
    f["vol_ratio_10_60"] = f["vol_10"] / f["vol_60"]
    for n in (20, 50, 200):
        f[f"dist_ema{n}"] = c / ta.ema(c, n) - 1
    f["ema20_slope"] = ta.ema(c, 20).pct_change(5)
    f["rsi14"] = ta.rsi(c, 14) / 100
    f["rsi_change"] = f["rsi14"].diff(3)
    m = ta.macd(c)
    f["macd_hist"] = m["hist"] / c
    bb = ta.bollinger(c)
    f["bb_pos"] = (c - bb["lower"]) / (bb["upper"] - bb["lower"])
    f["atr_pct"] = a / c
    f["volume_ratio"] = ta.volume_ratio(df).replace([np.inf, -np.inf], np.nan)
    f["volume_trend"] = v.rolling(5).mean() / v.rolling(50).mean()
    f["range_pct"] = (df["high"] - df["low"]) / c
    f["close_pos"] = (c - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)
    f["high_20_dist"] = c / df["high"].rolling(20).max() - 1
    f["low_20_dist"] = c / df["low"].rolling(20).min() - 1
    f["high_250_dist"] = c / df["high"].rolling(250, min_periods=50).max() - 1
    f["dow_trend"] = dow.trend(df)
    pats = cs.scan(df)
    bull = pats[["hammer", "bullish_engulfing", "morning_star"]].any(axis=1)
    bear = pats[["shooting_star", "bearish_engulfing", "evening_star"]].any(axis=1)
    f["candle_bias"] = bull.astype(int) - bear.astype(int)
    f["candle_bias_5"] = f["candle_bias"].rolling(5).sum()
    if isinstance(df.index, pd.DatetimeIndex):
        f["dow_week"] = df.index.dayofweek
        if (df.index.hour != 0).any():
            f["hour"] = df.index.hour
    return f.replace([np.inf, -np.inf], np.nan)


def make_labels(df: pd.DataFrame, horizon: int = 5, threshold_atr: float = 0.5) -> pd.Series:
    """Target: what happened over the next `horizon` bars.

    +1 (BUY)  if the forward return exceeds threshold_atr * ATR%,
    -1 (SELL) if it falls below the negative threshold,
     0 (HOLD) otherwise. The last `horizon` bars have no label (NaN).
    """
    c = df["close"]
    fwd = c.shift(-horizon) / c - 1
    thr = threshold_atr * ta.atr(df) / c * np.sqrt(horizon)
    y = pd.Series(np.where(fwd > thr, 1, np.where(fwd < -thr, -1, 0)), index=df.index, dtype=float)
    y[fwd.isna()] = np.nan
    return y
