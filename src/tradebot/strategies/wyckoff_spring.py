from __future__ import annotations

import numpy as np

from .. import indicators as ta
from ..analysis import wyckoff
from .base import Strategy


class WyckoffSpring(Strategy):
    """Wyckoff spring / upthrust inside a trading range.

    Long:  spring (false break below range support that closes back inside,
           on above-average volume). Stop below the spring low; target at
           range resistance.
    Short: upthrust at resistance; target at range support.
    """

    name = "wyckoff_spring"
    description = "Wyckoff spring (long) / upthrust (short) in a trading range"
    defaults = {"lookback": 40, "max_width_atr": 6.0, "min_volume_ratio": 1.2,
                "buffer_atr": 0.25, "min_rr": 1.5}

    def signals(self, df):
        kw = dict(lookback=self.p("lookback"), max_width_atr=self.p("max_width_atr"))
        tr = wyckoff.trading_range(df, **kw)
        spring = wyckoff.springs(df, min_volume_ratio=self.p("min_volume_ratio"), **kw)
        upthrust = wyckoff.upthrusts(df, min_volume_ratio=self.p("min_volume_ratio"), **kw)
        a = ta.atr(df)
        c = df["close"]
        buf = self.p("buffer_atr") * a

        long_stop = df["low"] - buf
        short_stop = df["high"] + buf
        long_rr = (tr["resistance"] - c) / (c - long_stop)
        short_rr = (c - tr["support"]) / (short_stop - c)

        long_ok = spring & (long_rr >= self.p("min_rr"))
        short_ok = upthrust & (short_rr >= self.p("min_rr"))

        df["entry_long"] = long_ok
        df["entry_short"] = short_ok
        df["stop"] = np.where(long_ok, long_stop, np.where(short_ok, short_stop, np.nan))
        df["target"] = np.where(long_ok, tr["resistance"], np.where(short_ok, tr["support"], np.nan))
        return df
