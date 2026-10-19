"""Market structure snapshot, as data (for the API) and as text (for the CLI)."""

from __future__ import annotations

import math

import pandas as pd

from . import indicators as ta
from .analysis import candlesticks, dow, elliott, wyckoff

TREND_TEXT = {1: "UPTREND (higher highs + higher lows)",
              -1: "DOWNTREND (lower highs + lower lows)", 0: "RANGE / TRANSITION"}


def _f(x) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def analyze_structure(df: pd.DataFrame) -> dict:
    c = df["close"]
    last = df.iloc[-1]
    a = ta.atr(df).iloc[-1]
    m = ta.macd(c).iloc[-1]
    tr = wyckoff.trading_range(df).iloc[-1]
    pats = candlesticks.scan(df.tail(3))
    impulses = elliott.find_impulses(df.tail(500), pct=max(0.02, 3 * a / last.close))
    imp = impulses[-1] if impulses else None
    return {
        "time": df.index[-1].isoformat(),
        "close": float(last.close),
        "atr": float(a),
        "atr_pct": float(a / last.close * 100),
        "trend": int(dow.trend(df).iloc[-1]),
        "swings": dow.last_swings(df),
        "ema": {str(n): float(ta.ema(c, n).iloc[-1]) for n in (20, 50, 200)},
        "rsi": float(ta.rsi(c).iloc[-1]),
        "macd_hist": float(m["hist"]),
        "wyckoff_range": {"support": _f(tr.support), "resistance": _f(tr.resistance),
                          "tight": bool(tr.in_range)},
        "recent_patterns": [{"time": ts.isoformat(), "pattern": name}
                            for ts, row in pats.iterrows() for name, hit in row.items() if hit],
        "elliott": None if imp is None else {
            "direction": imp["direction"], "start": imp["start"].isoformat(),
            "end": imp["end"].isoformat(), "points": imp["points"],
            "wave3_extension": _f(imp["guidelines"]["wave3_extension"])},
    }


def market_report(df: pd.DataFrame, symbol: str, timeframe: str) -> str:
    s = analyze_structure(df)
    e, w, sw = s["ema"], s["wyckoff_range"], s["swings"]
    pats = ", ".join(f"{p['pattern']} ({p['time'][:16]})" for p in s["recent_patterns"]) or "none"
    lines = [
        f"=== {symbol} {timeframe} | last bar {df.index[-1]:%Y-%m-%d %H:%M} UTC ===",
        f"Close {s['close']:.4f}   ATR(14) {s['atr']:.4f} ({s['atr_pct']:.2f}%)",
        f"Dow trend: {TREND_TEXT[s['trend']]}",
        f"  last swing high {sw['swing_high']}  last swing low {sw['swing_low']}",
        f"EMA20 {e['20']:.4f}  EMA50 {e['50']:.4f}  EMA200 {e['200']:.4f}  -> price "
        f"{'above' if s['close'] > e['200'] else 'below'} EMA200",
        f"RSI(14) {s['rsi']:.1f}   MACD hist {s['macd_hist']:+.4f}",
        f"Wyckoff range (40 bars): support {w['support']:.4f} resistance {w['resistance']:.4f} "
        f"{'-> tight range' if w['tight'] else '-> trending / wide'}",
        f"Candles (last 3 bars): {pats}",
    ]
    el = s["elliott"]
    lines.append(f"Elliott: last rule-valid {el['direction']} impulse {el['start'][:10]} -> {el['end'][:10]} "
                 f"(w3/w1 {el['wave3_extension']:.2f})" if el else
                 "Elliott: no rule-valid 5-wave impulse in recent swings")
    return "\n".join(lines)
