"""Computations shared by the API routes and the background precompute job."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
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
    def equal_weight(point_in_time: bool):
        # Honest yardstick: the same stocks (index members at each date), equal weight, no
        # selection. The gap to it measures the selection skill itself.
        key = (tuple(sorted(frames)), body.rebalance, body.cost_bps, body.start, body.benchmark, point_in_time)
        ew = ew_cache.get(key) if ew_cache is not None else None
        if ew is None:
            ew = run_picker(frames, bench, PickerConfig(top_n=len(frames), trend_filter=False, rebalance=body.rebalance,
                                                        cost_bps=body.cost_bps, point_in_time=point_in_time),
                            start=body.start)
            if ew_cache is not None:
                ew_cache[key] = ew
        return ew

    try:
        # Point-in-time membership (default): a stock counts only from the day it joined the S&P 500.
        res = run_picker(frames, bench, cfg, start=body.start)
        ew = equal_weight(True)
        # Same test on today's members throughout, shown only to explain how much that bias inflates results.
        naive = run_picker(frames, bench, replace(cfg, point_in_time=False), start=body.start)
        ew_naive = equal_weight(False)
    except ValueError as exc:
        raise ServiceError(400, str(exc)) from exc
    res.stats["universe_cagr_%"] = ew.stats["cagr_%"]
    res.stats["skill_vs_universe_%"] = res.stats["cagr_%"] - ew.stats["cagr_%"]
    res.stats["todays_members_cagr_%"] = naive.stats["cagr_%"]
    res.stats["todays_members_skill_%"] = naive.stats["cagr_%"] - ew_naive.stats["cagr_%"]

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
        "ranking": ranking,
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
        parts.append(f"{breadth_pct:.0f}% of S&P 500 stocks are in an uptrend")
    if vix is not None:
        parts.append(f"fear index (VIX) at {vix:.0f} ({'calm' if vix < 18 else 'nervous' if vix > 25 else 'normal'})")
    advice = {"Risk-on": "Conditions favor staying fully invested in the picks.",
              "Neutral": "Mixed signals: stay invested but respect stop-losses.",
              "Risk-off": "Weak market: consider holding more cash until the trend recovers."}[label]
    return {"label": label, "explanation": "; ".join(parts) + ".", "advice": advice,
            "spy_vs_200d_%": float(dist), "spy_1m_%": float(ret_1m), "breadth_%": breadth_pct, "vix": vix}


HORIZONS = {1: "tomorrow", 5: "the next week", 21: "the next month"}


def prediction_reason(f: pd.Series) -> str:
    """Plain-English summary of the main inputs behind a ranking (not a causal claim)."""
    parts = []
    r20 = f.get("ret_20")
    if r20 is not None and np.isfinite(r20):
        parts.append(f"{'up' if r20 >= 0 else 'down'} {abs(r20) * 100:.0f}% in a month")
    rsi = f.get("rsi14")
    if rsi is not None and np.isfinite(rsi):
        parts.append("overbought" if rsi > 0.7 else "oversold" if rsi < 0.3 else f"RSI {rsi * 100:.0f}")
    vr = f.get("volume_ratio")
    if vr is not None and np.isfinite(vr) and vr > 1.5:
        parts.append(f"volume {vr:.1f}x normal")
    d200 = f.get("dist_ema200")
    if d200 is not None and np.isfinite(d200):
        parts.append(f"{abs(d200) * 100:.0f}% {'above' if d200 >= 0 else 'below'} its long-term trend")
    text = ", ".join(parts)
    return text[:1].upper() + text[1:] + "." if text else ""


def default_prediction_symbols() -> list[str]:
    """The full S&P 500 plus the curated US-listed names (~510). With capped OpenMP threads, float32
    features and weekly training dates (5/21 days) this takes ~1.5 min per horizon instead of ~20."""
    from ..universe import CURATED

    return list(dict.fromkeys(sp500_symbols() + [s.symbol for s in CURATED if "." not in s.symbol]))


def compute_predictions(market: MarketData, horizon: int = 5, symbols: list[str] | None = None) -> dict:
    from ..ml.features import build_features
    from ..ml.ranker import rank_universe
    from ..universe import by_symbol

    symbols = symbols or default_prediction_symbols()
    frames = market.history_many("yahoo", symbols, "1d", start="2017-01-01")
    if len(frames) < 20:
        raise ServiceError(502, f"Only {len(frames)} stocks could be loaded; need at least 20 to rank them.")
    try:
        res = rank_universe(frames, horizon=horizon)
    except ValueError as exc:
        raise ServiceError(400, str(exc)) from exc
    info = by_symbol()
    items = []
    for sym, r in res.scores.iterrows():
        df = frames[sym]
        feats = build_features(df.iloc[-260:]).iloc[-1]
        st = info.get(sym)
        items.append({
            "symbol": sym, "name": st.name if st else sym, "sector": st.sector if st else None,
            "score": float(r.score), "decile": int(r.decile), "p_outperform": float(r.p_outperform),
            "p_underperform": float(r.p_underperform), "price": float(df["close"].iloc[-1]),
            "change_1d_%": float((df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100),
            "reason": prediction_reason(feats),
        })
    v = res.validation
    quality = (f"On unseen past data, its top-ranked stocks beat its bottom-ranked ones by "
               f"{v['top_minus_bottom_per_period_%']:.2f}% per period on average, and its ranking was right more "
               f"often than wrong on {v['ic_positive_share'] * 100:.0f}% of days.")
    return ser.clean({"horizon": horizon, "horizon_label": HORIZONS.get(horizon, f"{horizon} days"),
                      "as_of": res.as_of, "validation": v, "quality_sentence": quality,
                      "edge_sentence": ("Small but statistically real edge." if v["has_edge"] else
                                        "No reliable edge at this horizon: treat the ranking as weak information."),
                      "items": items, "universe_size": len(frames)})


def _day(iso: str) -> str:
    d = pd.Timestamp(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def compute_track_record(market: MarketData, store, preset: str = "quality_momentum",
                         universe_line: list[dict] | None = None, now=None) -> dict:
    """The live forward record: recorded picks vs SPY, and the outcome of every recorded Invest-now idea."""
    from ..data import provider_for
    from ..live.track_record import (idea_outcome, ideas_summary, line_return, picks_forward,
                                     session_close_known)

    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    snaps = store.picks_snapshots(preset)
    ideas = store.track_ideas()
    firsts = [x for x in (snaps[0]["date"] if snaps else None, ideas[0]["day"] if ideas else None) if x]
    started = min(firsts) if firsts else None

    # ---- picks vs SPY
    fw: dict = {"days": 0, "curve": []}
    if snaps:
        fetch_start = (pd.Timestamp(snaps[0]["date"]) - pd.Timedelta(days=10)).date().isoformat()
        syms = sorted({s for snap in snaps for s in snap["weights"]})
        frames = market.history_many("yahoo", syms, "1d", start=fetch_start) if syms else {}
        try:
            spy = market.history("yahoo", "SPY", "1d", start=fetch_start)
        except DataUnavailable:
            spy = None
        fw = picks_forward(snaps, frames, spy)
        last_day = fw["curve"][-1]["date"] if fw["curve"] else None
        fw["universe_%"] = line_return(universe_line or [], snaps[0]["date"], last_day) if last_day else None
        fw["missing"] = sorted(set(syms) - set(frames))
    latest = snaps[-1] if snaps else None
    fw.update(snapshots=len(snaps), latest_date=latest["date"] if latest else None,
              current=latest["picks"] if latest else [], risk_off=bool(latest and latest["risk_off"]))

    # ---- Invest-now ideas
    outcomes = []
    if ideas:
        fetch_start = (pd.Timestamp(ideas[0]["day"]) - pd.Timedelta(days=5)).date().isoformat()
        by_provider: dict[str, list[str]] = {}
        for i in ideas:
            by_provider.setdefault(provider_for(i["symbol"]), []).append(i["symbol"])
        bars: dict[str, pd.DataFrame] = {}
        for prov, syms in by_provider.items():
            try:
                bars.update(market.history_many(prov, sorted(set(syms)), "1d", start=fetch_start))
            except Exception:   # an unreachable provider leaves its ideas pending
                pass
        today_ny = now.tz_convert("America/New_York").date().isoformat()
        today_utc = now.tz_convert("UTC").date().isoformat()
        for i in ideas:
            df = bars.get(i["symbol"])
            complete = True
            if df is not None and len(df):
                last = pd.Timestamp(df.index[-1])
                last = (last.tz_convert("UTC") if last.tzinfo else last).date().isoformat()
                complete = (last < today_utc) if "/" in i["symbol"] else (
                    last < today_ny or session_close_known(today_ny, now))
            outcomes.append(idea_outcome(i, df, max_days=int(i.get("hold_days") or 5), last_bar_complete=complete))
    summary = ideas_summary(outcomes)
    summary["closed"] = summary["closed"][:50]

    days = int(fw.get("days") or 0)
    if not started:
        message = ("The live record starts at the next US market close: from then on, the picks and every "
                   "Invest-now idea are saved each day and followed with real prices.")
    elif not snaps:
        message = (f"Just started on {_day(started)} with the first Invest-now ideas. The picks are saved after the "
                   "next US market close and count from the open after that.")
    elif days == 0:
        message = (f"Just started: first picks saved for {_day(snaps[0]['date'])}. They count from the next market "
                   "open, so there is no result yet.")
    elif days < 20:
        message = (f"Just started: {days} trading day{'s' if days != 1 else ''} so far. Far too early to judge; "
                   "a few weeks can be pure luck either way, it takes many months to tell skill from luck.")
    else:
        message = (f"{days} trading days of real, forward results (no hindsight). Still short: judge the "
                   "engine on a year or more.")
    return ser.clean({
        "preset": preset, "as_of": now.isoformat(), "started": started, "days": days,
        "too_early": days < 20, "message": message, "picks": fw, "ideas": summary,
    })
