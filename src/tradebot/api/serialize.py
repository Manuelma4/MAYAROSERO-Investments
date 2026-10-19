"""Conversions from pandas objects to JSON-friendly structures for the frontend."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def ts(t) -> int:
    """Unix seconds (the time format used by lightweight-charts)."""
    return int(pd.Timestamp(t).timestamp())


def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (pd.Timestamp,)):
        return x.isoformat()
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if math.isnan(x) or math.isinf(x) else float(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def candles(df: pd.DataFrame) -> list[dict]:
    return [{"time": ts(t), "open": r.open, "high": r.high, "low": r.low, "close": r.close,
             "volume": r.volume} for t, r in zip(df.index, df.itertuples())]


def line(s: pd.Series) -> list[dict]:
    s = s.dropna()
    return [{"time": ts(t), "value": float(v)} for t, v in s.items()]
