"""Dow theory: trend from the sequence of confirmed swing highs and lows.

Uptrend   = higher highs and higher lows.
Downtrend = lower highs and lower lows.
Otherwise = range / transition (0).
"""

from __future__ import annotations

import pandas as pd

from .swings import pivots


def trend(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """+1 / -1 / 0 per bar, using only pivots confirmed by that bar."""
    piv = pivots(df, left, right)
    out = pd.Series(0, index=df.index, dtype=int)
    highs: list[float] = []
    lows: list[float] = []
    state = 0
    events = piv.sort_values("confirmed_at").itertuples()
    ev = next(events, None)
    for t in df.index:
        while ev is not None and ev.confirmed_at <= t:
            (highs if ev.kind == "H" else lows).append(ev.price)
            if len(highs) >= 2 and len(lows) >= 2:
                hh, hl = highs[-1] > highs[-2], lows[-1] > lows[-2]
                lh, ll = highs[-1] < highs[-2], lows[-1] < lows[-2]
                state = 1 if (hh and hl) else -1 if (lh and ll) else 0
            ev = next(events, None)
        out[t] = state
    return out


def last_swings(df: pd.DataFrame, at=None, left: int = 5, right: int = 5) -> dict:
    """Most recent confirmed swing high / low as of `at` (default: last bar)."""
    at = at if at is not None else df.index[-1]
    piv = pivots(df, left, right)
    piv = piv[piv["confirmed_at"] <= at]
    hi = piv[piv.kind == "H"].tail(1)
    lo = piv[piv.kind == "L"].tail(1)
    return {
        "swing_high": float(hi.price.iloc[0]) if len(hi) else None,
        "swing_low": float(lo.price.iloc[0]) if len(lo) else None,
    }
