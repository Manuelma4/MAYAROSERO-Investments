from __future__ import annotations

import numpy as np

from .. import indicators as ta
from .base import Strategy


class EmaCrossRsi(Strategy):
    """Trend following: fast/slow EMA cross, filtered by RSI and the 200 EMA.

    Long:  fast EMA crosses above slow EMA, RSI > 50, close > trend EMA.
    Short: mirror image.
    Stop:  ATR multiple from the close. Target: reward/risk multiple.
    Exit:  opposite cross.
    """

    name = "ema_cross_rsi"
    description = "EMA crossover with RSI and 200-EMA trend filter"
    defaults = {"fast": 20, "slow": 50, "trend": 200, "rsi": 14,
                "atr": 14, "atr_stop": 2.0, "rr": 2.0}

    def signals(self, df):
        c = df["close"]
        fast, slow, trend = ta.ema(c, self.p("fast")), ta.ema(c, self.p("slow")), ta.ema(c, self.p("trend"))
        rsi = ta.rsi(c, self.p("rsi"))
        a = ta.atr(df, self.p("atr"))
        up = (fast > slow) & (fast.shift() <= slow.shift())
        down = (fast < slow) & (fast.shift() >= slow.shift())

        df["entry_long"] = up & (rsi > 50) & (c > trend)
        df["entry_short"] = down & (rsi < 50) & (c < trend)
        df["exit_long"] = down
        df["exit_short"] = up
        risk = self.p("atr_stop") * a
        df["stop"] = np.where(df["entry_long"], c - risk, np.where(df["entry_short"], c + risk, np.nan))
        df["target"] = np.where(df["entry_long"], c + self.p("rr") * risk,
                                np.where(df["entry_short"], c - self.p("rr") * risk, np.nan))
        return df
