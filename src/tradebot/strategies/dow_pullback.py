from __future__ import annotations

import numpy as np

from .. import indicators as ta
from ..analysis import candlesticks as cs
from ..analysis import dow
from ..analysis.swings import pivots
from .base import Strategy


class DowPullback(Strategy):
    """Dow theory trend + pullback + candlestick confirmation.

    Long:  Dow uptrend (HH + HL), price pulled back to the EMA zone, and a
           bullish reversal candle (hammer / bullish engulfing / morning star).
    Stop:  below the last confirmed swing low (minus an ATR buffer).
    Target: reward/risk multiple of the stop distance.
    Short: mirror image in a Dow downtrend.
    """

    name = "dow_pullback"
    description = "Dow trend (HH/HL) + EMA pullback + reversal candlestick"
    defaults = {"swing": 5, "ema": 20, "atr": 14, "buffer_atr": 0.5, "rr": 2.0, "max_risk_atr": 4.0}

    def signals(self, df):
        n = self.p("swing")
        t = dow.trend(df, n, n)
        e = ta.ema(df["close"], self.p("ema"))
        a = ta.atr(df, self.p("atr"))

        bull_candle = cs.hammer(df) | cs.bullish_engulfing(df) | cs.morning_star(df)
        bear_candle = cs.shooting_star(df) | cs.bearish_engulfing(df) | cs.evening_star(df)
        touched_low = df["low"] <= e
        touched_high = df["high"] >= e

        # Last confirmed swing low/high known at each bar.
        piv = pivots(df, n, n)
        last_low = (piv[piv.kind == "L"].set_index("confirmed_at")["price"]
                    .groupby(level=0).last().reindex(df.index, method="ffill"))
        last_high = (piv[piv.kind == "H"].set_index("confirmed_at")["price"]
                     .groupby(level=0).last().reindex(df.index, method="ffill"))

        buf = self.p("buffer_atr") * a
        long_stop = last_low - buf
        short_stop = last_high + buf
        c = df["close"]
        max_risk = self.p("max_risk_atr") * a

        long_ok = (t == 1) & touched_low & (c > e) & bull_candle & (long_stop < c) & (c - long_stop <= max_risk)
        short_ok = (t == -1) & touched_high & (c < e) & bear_candle & (short_stop > c) & (short_stop - c <= max_risk)

        df["entry_long"] = long_ok
        df["entry_short"] = short_ok
        df["exit_long"] = t == -1
        df["exit_short"] = t == 1
        rr = self.p("rr")
        df["stop"] = np.where(long_ok, long_stop, np.where(short_ok, short_stop, np.nan))
        df["target"] = np.where(long_ok, c + rr * (c - long_stop),
                                np.where(short_ok, c - rr * (short_stop - c), np.nan))
        return df
