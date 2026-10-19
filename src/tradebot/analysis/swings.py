"""Swing (pivot) detection without look-ahead bias.

A pivot high at bar i is only *confirmed* `right` bars later. The returned
frames carry both the pivot time and the confirmation time so strategies can
use pivots exactly when they would have been known in real time.
"""

from __future__ import annotations

import pandas as pd


def pivots(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.DataFrame:
    h, l = df["high"], df["low"]
    win = left + right + 1
    is_high = h.rolling(win, center=True).max() == h
    is_low = l.rolling(win, center=True).min() == l
    rows = []
    idx = df.index
    for i in range(left, len(df) - right):
        if is_high.iloc[i]:
            rows.append((idx[i], idx[i + right], "H", h.iloc[i]))
        if is_low.iloc[i]:
            rows.append((idx[i], idx[i + right], "L", l.iloc[i]))
    return pd.DataFrame(rows, columns=["time", "confirmed_at", "kind", "price"])


def zigzag(df: pd.DataFrame, pct: float = 0.05) -> pd.DataFrame:
    """Alternating swing points where price reverses by at least `pct`.

    Note: the last point is provisional (the leg can still extend), which is
    fine for analysis but must not be used for signals without confirmation.
    """
    highs, lows, idx = df["high"].values, df["low"].values, df.index
    points: list[tuple] = []
    trend = 0
    hi_i, hi_p = 0, highs[0]
    lo_i, lo_p = 0, lows[0]
    for i in range(1, len(df)):
        h, l = highs[i], lows[i]
        if trend == 0:
            if h > hi_p:
                hi_i, hi_p = i, h
            if l < lo_p:
                lo_i, lo_p = i, l
            if hi_i > lo_i and hi_p >= lo_p * (1 + pct):
                points.append((idx[lo_i], "L", lo_p))
                trend = 1
            elif lo_i > hi_i and lo_p <= hi_p * (1 - pct):
                points.append((idx[hi_i], "H", hi_p))
                trend = -1
        elif trend == 1:
            if h > hi_p:
                hi_i, hi_p = i, h
            elif l <= hi_p * (1 - pct):
                points.append((idx[hi_i], "H", hi_p))
                trend, lo_i, lo_p = -1, i, l
        else:
            if l < lo_p:
                lo_i, lo_p = i, l
            elif h >= lo_p * (1 + pct):
                points.append((idx[lo_i], "L", lo_p))
                trend, hi_i, hi_p = 1, i, h
    if trend == 1:
        points.append((idx[hi_i], "H", hi_p))
    elif trend == -1:
        points.append((idx[lo_i], "L", lo_p))
    return pd.DataFrame(points, columns=["time", "kind", "price"])
