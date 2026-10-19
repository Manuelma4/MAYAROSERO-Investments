"""Human-readable snapshot of a market's current structure."""

from __future__ import annotations

import pandas as pd

from . import indicators as ta
from .analysis import candlesticks, dow, elliott, wyckoff


def market_report(df: pd.DataFrame, symbol: str, timeframe: str) -> str:
    c = df["close"]
    last = df.iloc[-1]
    t = dow.trend(df).iloc[-1]
    sw = dow.last_swings(df)
    rsi = ta.rsi(c).iloc[-1]
    m = ta.macd(c).iloc[-1]
    a = ta.atr(df).iloc[-1]
    e20, e50, e200 = (ta.ema(c, n).iloc[-1] for n in (20, 50, 200))
    tr = wyckoff.trading_range(df).iloc[-1]
    pats = candlesticks.scan(df.tail(3))
    recent = [f"{name} ({ts:%Y-%m-%d %H:%M})" for ts, row in pats.iterrows()
              for name, hit in row.items() if hit]
    imp = elliott.find_impulses(df.tail(500), pct=max(0.02, 3 * a / last.close))

    trend_txt = {1: "UPTREND (higher highs + higher lows)",
                 -1: "DOWNTREND (lower highs + lower lows)", 0: "RANGE / TRANSITION"}[int(t)]
    lines = [
        f"=== {symbol} {timeframe} | last bar {df.index[-1]:%Y-%m-%d %H:%M} UTC ===",
        f"Close {last.close:.4f}   ATR(14) {a:.4f} ({a / last.close * 100:.2f}%)",
        f"Dow trend: {trend_txt}",
        f"  last swing high {sw['swing_high']}  last swing low {sw['swing_low']}",
        f"EMA20 {e20:.4f}  EMA50 {e50:.4f}  EMA200 {e200:.4f}  -> price "
        f"{'above' if last.close > e200 else 'below'} EMA200",
        f"RSI(14) {rsi:.1f}   MACD hist {m['hist']:+.4f}",
        f"Wyckoff range (40 bars): support {tr.support:.4f} resistance {tr.resistance:.4f} "
        f"{'-> tight range' if tr.in_range else '-> trending / wide'}",
        f"Candles (last 3 bars): {', '.join(recent) if recent else 'none'}",
    ]
    if imp:
        x = imp[-1]
        lines.append(f"Elliott: last rule-valid {x['direction']} impulse {x['start']:%Y-%m-%d} -> "
                     f"{x['end']:%Y-%m-%d} (w3/w1 {x['guidelines']['wave3_extension']:.2f})")
    else:
        lines.append("Elliott: no rule-valid 5-wave impulse in recent swings")
    return "\n".join(lines)
