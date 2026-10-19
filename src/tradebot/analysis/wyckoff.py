"""Wyckoff helpers: trading ranges, springs and upthrusts.

These are deliberately simple, objective approximations of discretionary
Wyckoff events so they can be backtested:

- Trading range: rolling support/resistance over `lookback` bars whose width
  is small relative to ATR-normalized price movement.
- Spring: price undercuts range support, then closes back inside the range,
  ideally on above-average volume (shakeout / absorption).
- Upthrust (UTAD): mirror image at resistance.
"""

from __future__ import annotations

import pandas as pd

from ..indicators import atr, volume_ratio


def trading_range(df: pd.DataFrame, lookback: int = 40, max_width_atr: float = 6.0) -> pd.DataFrame:
    # Range is measured on bars *before* the current one so a break is detectable.
    support = df["low"].rolling(lookback).min().shift()
    resistance = df["high"].rolling(lookback).max().shift()
    width = (resistance - support) / atr(df).shift()
    return pd.DataFrame({
        "support": support,
        "resistance": resistance,
        "in_range": width <= max_width_atr,
    }, index=df.index)


def springs(df: pd.DataFrame, lookback: int = 40, max_width_atr: float = 6.0,
            min_volume_ratio: float = 1.0) -> pd.Series:
    tr = trading_range(df, lookback, max_width_atr)
    vol_ok = volume_ratio(df) >= min_volume_ratio
    sig = tr["in_range"] & (df["low"] < tr["support"]) & (df["close"] > tr["support"]) & vol_ok
    return sig.fillna(False)


def upthrusts(df: pd.DataFrame, lookback: int = 40, max_width_atr: float = 6.0,
              min_volume_ratio: float = 1.0) -> pd.Series:
    tr = trading_range(df, lookback, max_width_atr)
    vol_ok = volume_ratio(df) >= min_volume_ratio
    sig = tr["in_range"] & (df["high"] > tr["resistance"]) & (df["close"] < tr["resistance"]) & vol_ok
    return sig.fillna(False)
