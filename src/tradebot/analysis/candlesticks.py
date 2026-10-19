"""Japanese candlestick pattern detection.

Each function returns a boolean Series aligned with the input frame: True on
the bar that *completes* the pattern (so it is known at that bar's close and
never looks into the future).
"""

from __future__ import annotations

import pandas as pd


def _parts(df: pd.DataFrame):
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, float("nan"))
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    lower = pd.concat([o, c], axis=1).min(axis=1) - l
    return o, h, l, c, body, rng, upper, lower


def doji(df, max_body_ratio: float = 0.1) -> pd.Series:
    *_, body, rng, _, _ = _parts(df)
    return (body / rng <= max_body_ratio).fillna(False)


def hammer(df, wick_mult: float = 2.0) -> pd.Series:
    """Small body at the top, long lower wick (bullish if after a decline)."""
    *_, body, rng, upper, lower = _parts(df)
    return ((lower >= wick_mult * body) & (upper <= body) & (body / rng > 0.05)).fillna(False)


def shooting_star(df, wick_mult: float = 2.0) -> pd.Series:
    """Small body at the bottom, long upper wick (bearish if after a rally)."""
    *_, body, rng, upper, lower = _parts(df)
    return ((upper >= wick_mult * body) & (lower <= body) & (body / rng > 0.05)).fillna(False)


def bullish_engulfing(df) -> pd.Series:
    o, _, _, c, *_ = _parts(df)
    po, pc = o.shift(), c.shift()
    return ((pc < po) & (c > o) & (c >= po) & (o <= pc)).fillna(False)


def bearish_engulfing(df) -> pd.Series:
    o, _, _, c, *_ = _parts(df)
    po, pc = o.shift(), c.shift()
    return ((pc > po) & (c < o) & (c <= po) & (o >= pc)).fillna(False)


def morning_star(df) -> pd.Series:
    o, _, _, c, body, rng, *_ = _parts(df)
    first_bear = (c.shift(2) < o.shift(2)) & (body.shift(2) / rng.shift(2) > 0.5)
    small_mid = body.shift(1) / rng.shift(1) < 0.3
    strong_close = (c > o) & (c > (o.shift(2) + c.shift(2)) / 2)
    return (first_bear & small_mid & strong_close).fillna(False)


def evening_star(df) -> pd.Series:
    o, _, _, c, body, rng, *_ = _parts(df)
    first_bull = (c.shift(2) > o.shift(2)) & (body.shift(2) / rng.shift(2) > 0.5)
    small_mid = body.shift(1) / rng.shift(1) < 0.3
    weak_close = (c < o) & (c < (o.shift(2) + c.shift(2)) / 2)
    return (first_bull & small_mid & weak_close).fillna(False)


PATTERNS = {
    "doji": doji,
    "hammer": hammer,
    "shooting_star": shooting_star,
    "bullish_engulfing": bullish_engulfing,
    "bearish_engulfing": bearish_engulfing,
    "morning_star": morning_star,
    "evening_star": evening_star,
}


def scan(df: pd.DataFrame) -> pd.DataFrame:
    """All patterns as boolean columns."""
    return pd.DataFrame({name: fn(df) for name, fn in PATTERNS.items()}, index=df.index)
