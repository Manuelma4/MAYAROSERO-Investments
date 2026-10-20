"""Computations shared by the API routes and the background precompute job."""

from __future__ import annotations

import math

import pandas as pd

from ..picker import PRESET_INFO, PickerConfig, run_picker
from ..universe import by_symbol, sp500_symbols
from . import serialize as ser
from .market import DataUnavailable, MarketData
from .schemas import PicksRequest


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def pick_reason(r: dict) -> str:
    """One plain-English line explaining why a stock ranks well."""
    parts = []
    m12 = r.get("momentum_12_1_%")
    if m12 is not None:
        parts.append(f"{'up' if m12 >= 0 else 'down'} {abs(m12):.0f}% over the past year")
    rs = r.get("rel_strength_%")
    if rs is not None:
        parts.append(f"{'beating' if rs >= 0 else 'lagging'} the S&P 500 by {abs(rs):.0f}% over 6 months")
    tr = r.get("trend_%")
    if tr is not None:
        parts.append(f"{abs(tr):.0f}% {'above' if tr >= 0 else 'below'} its 200-day average")
    vol = r.get("volatility_%")
    if vol is not None:
        parts.append("calm price action" if vol < 25 else "volatile" if vol > 45 else "average volatility")
    text = ", ".join(parts)
    return text[:1].upper() + text[1:] + "." if text else ""


_PERIOD_END = {"ME": pd.offsets.MonthEnd(0), "QE": pd.offsets.QuarterEnd(0), "W-FRI": pd.offsets.Week(weekday=4)}


def completed_changes(holdings: list[dict], rebalance: str, as_of: pd.Timestamp) -> dict:
    """Buy/sell/keep at the last COMPLETED review. A review dated in the still-running period
    (e.g. today, mid-month) is provisional, so it is skipped and reported separately."""
    hs = list(holdings)
    provisional = False
    if hs:
        last = pd.Timestamp(hs[-1]["date"])
        period_end = (last + _PERIOD_END.get(rebalance, pd.offsets.MonthEnd(0))).normalize()
        if last.normalize() < period_end and last.date() >= as_of.date():
            hs = hs[:-1]
            provisional = True
    if not hs:
        return {"date": None, "buy": [], "sell": [], "keep": [], "provisional_skipped": provisional}
    cur = set(hs[-1]["symbols"])
    prev = set(hs[-2]["symbols"]) if len(hs) > 1 else set()
    return {"date": hs[-1]["date"], "buy": sorted(cur - prev), "sell": sorted(prev - cur),
            "keep": sorted(cur & prev), "provisional_skipped": provisional}


def compute_picks(market: MarketData, body: PicksRequest, ew_cache: dict | None = None) -> dict:
    symbols = body.symbols or sp500_symbols()
    # One extra year before `start` so 12-month factors exist on day one.
    fetch_start = (pd.Timestamp(body.start) - pd.Timedelta(days=400)).date().isoformat()
    frames = market.history_many("yahoo", symbols, "1d", start=fetch_start)
    try:
        bench = market.history("yahoo", body.benchmark, "1d", start=fetch_start)
    except DataUnavailable as exc:
        raise ServiceError(502, str(exc)) from exc
    if len(frames) < body.top_n:
        raise ServiceError(502, f"Only {len(frames)} of {len(symbols)} stocks could be loaded")
    cfg = PickerConfig(preset=body.preset, top_n=body.top_n, rebalance=body.rebalance,
                       trend_filter=body.trend_filter, regime_filter=body.regime_filter, cost_bps=body.cost_bps)
    try:
        res = run_picker(frames, bench, cfg, start=body.start)
        # Honest yardstick: the same stocks, equal weight, no selection. It shares the
        # survivorship bias, so the gap to it measures the selection skill itself.
        ew_key = (tuple(sorted(frames)), body.rebalance, body.cost_bps, body.start, body.benchmark)
        ew = ew_cache.get(ew_key) if ew_cache is not None else None
        if ew is None:
            ew = run_picker(frames, bench, PickerConfig(top_n=len(frames), trend_filter=False,
                                                        rebalance=body.rebalance, cost_bps=body.cost_bps),
                            start=body.start)
            if ew_cache is not None:
                ew_cache[ew_key] = ew
    except ValueError as exc:
        raise ServiceError(400, str(exc)) from exc
    res.stats["universe_cagr_%"] = ew.stats["cagr_%"]
    res.stats["skill_vs_universe_%"] = res.stats["cagr_%"] - ew.stats["cagr_%"]

    info = by_symbol()

    def row(sym: str, r) -> dict:
        s = info.get(sym)
        out = {"symbol": sym, "name": s.name if s else sym, "sector": s.sector if s else None,
               "score": r.score, "eligible": bool(r.eligible), "price": r.price,
               "return_1m_%": r.return_1m * 100, "momentum_12_1_%": r.momentum_12_1 * 100,
               "momentum_6_1_%": r.momentum_6_1 * 100, "rel_strength_%": r.rel_strength * 100,
               "trend_%": r.trend * 100, "volatility_%": -r.low_vol * 100}
        out["reason"] = pick_reason(out)
        return out

    ranking = [row(sym, r) for sym, r in res.current.iterrows()]
    current = [x for x in ranking if x["eligible"]][: body.top_n]
    risk_off = bool(res.holdings and res.holdings[-1]["risk_off"])

    # What changed at the last completed review (buy / sell / keep).
    changes = completed_changes(res.holdings, body.rebalance, res.equity.index[-1])

    return ser.clean({
        "preset": body.preset, "preset_info": PRESET_INFO,
        "as_of": res.equity.index[-1].isoformat(),
        "risk_off": risk_off,
        "picks": [] if risk_off else current,
        "ranking": ranking[:60],
        "changes": changes,
        "stats": res.stats,
        "equity": ser.line(res.equity),
        "benchmark": ser.line(res.benchmark),
        "universe": ser.line(ew.equity),
        "holdings": res.holdings[-36:][::-1],
        "universe_size": len(frames),
        "missing": sorted(set(symbols) - set(frames)),
        "breadth_%": float(sum(1 for x in ranking if (x["trend_%"] or 0) > 0) / max(1, len(ranking)) * 100),
    })


def market_mood(market: MarketData, breadth_pct: float | None) -> dict:
    """S&P 500 trend + breadth + volatility (VIX) summarized as one label with a plain explanation."""
    spy = market.history("yahoo", "SPY", "1d", limit=260)
    close = spy["close"]
    ma200 = close.rolling(200).mean().iloc[-1]
    dist = (close.iloc[-1] / ma200 - 1) * 100
    ret_1m = (close.iloc[-1] / close.iloc[-22] - 1) * 100
    vix = None
    try:
        vix = float(market.history("yahoo", "^VIX", "1d", limit=5)["close"].iloc[-1])
    except DataUnavailable:
        pass

    if not math.isfinite(dist):
        raise DataUnavailable("S&P 500 trend unavailable")
    if vix is not None and not math.isfinite(vix):
        vix = None
    breadth = 50.0 if breadth_pct is None else breadth_pct
    score = (1 if dist > 0 else -1) + (1 if breadth >= 55 else -1 if breadth < 45 else 0) \
        + (0 if vix is None else 1 if vix < 18 else -1 if vix > 25 else 0)
    label = "Risk-on" if score >= 2 else "Risk-off" if score <= -1 else "Neutral"
    parts = [f"The S&P 500 is {abs(dist):.1f}% {'above' if dist >= 0 else 'below'} its 200-day average "
             f"({'uptrend' if dist >= 0 else 'downtrend'})"]
    if breadth_pct is not None:
        parts.append(f"{breadth_pct:.0f}% of the leading stocks are in an uptrend")
    if vix is not None:
        parts.append(f"fear index (VIX) at {vix:.0f} ({'calm' if vix < 18 else 'nervous' if vix > 25 else 'normal'})")
    advice = {"Risk-on": "Conditions favor staying fully invested in the picks.",
              "Neutral": "Mixed signals: stay invested but respect stop-losses.",
              "Risk-off": "Weak market: consider holding more cash until the trend recovers."}[label]
    return {"label": label, "explanation": "; ".join(parts) + ".", "advice": advice,
            "spy_vs_200d_%": float(dist), "spy_1m_%": float(ret_1m), "breadth_%": breadth_pct, "vix": vix}
