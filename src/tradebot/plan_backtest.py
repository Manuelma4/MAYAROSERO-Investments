"""Walk-forward backtest of the portfolio plan's lasting part (picks + S&P 500 index) for one risk level.

At every month end t, using ONLY data up to t's close:
1. rank the stocks with the picker (point-in-time S&P 500 membership by default),
2. build the plan's weights with portfolio.plan_weights (the same code the app uses), either the
   original way (inverse volatility, fixed mix) or risk-aware (equal risk contribution + risk budget),
3. trade at the NEXT day's open, paying `cost_bps` per unit of turnover, and hold until the next review.

Live ideas (the satellite part) cannot be replayed (they come from live news scans), so their share earns
nothing here, exactly like the risk card counts them as cash. Both variants share that handicap, so
before/after comparisons are fair; absolute returns are understated for Balanced and Bold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .picker import PickerConfig, _closes, _opens, membership_mask, rank
from .portfolio import SHORT_LOOKBACK, SPY, plan_weights


def _ranked_items(ranked: pd.DataFrame, sectors: dict[str, str | None]) -> list[dict]:
    el = ranked[ranked["eligible"]]
    return [{"symbol": s, "sector": sectors.get(s), "price": float(r.price), "volatility_%": float(-r.low_vol * 100)}
            for s, r in el.iterrows()]


def run_plan_backtest(frames: dict[str, pd.DataFrame], benchmark: pd.DataFrame, risk: str, risk_aware: bool = True,
                      start: str | None = "2015-01-01", end: str | None = None, cfg: PickerConfig | None = None,
                      members: pd.DataFrame | None = None, sectors: dict[str, str | None] | None = None,
                      cost_bps: float = 10.0, core_n: int = 10, short_lookback: int | None = SHORT_LOOKBACK) -> dict:
    """Returns {"equity": Series (starts at 100), "benchmark": SPY Series, "weights": [...], "stats": {...}}.
    `members` overrides point-in-time membership (tests); `sectors` maps symbol -> sector (default: universe)."""
    cfg = cfg or PickerConfig(top_n=core_n)
    if sectors is None:
        from .universe import by_symbol
        info = by_symbol()
        sectors = {s: (info[s].sector if s in info else None) for s in frames}
    stocks = {s: f for s, f in frames.items() if s != SPY}
    px = _closes(stocks)
    bench = benchmark["close"].copy()
    bench.index = bench.index.normalize()
    bench = bench[~bench.index.duplicated(keep="last")]
    if end:
        bench = bench.loc[:pd.Timestamp(end, tz=bench.index.tz)]
    raw = px.reindex(bench.index)
    px = raw.ffill(limit=5)
    allc = px.copy()
    allc[SPY] = bench
    opn = _opens(stocks).reindex(bench.index).where(raw.notna())
    bopen = benchmark["open"].copy() if "open" in benchmark else benchmark["close"].copy()
    bopen.index = bopen.index.normalize()
    opn[SPY] = bopen[~bopen.index.duplicated(keep="last")].reindex(bench.index)
    rets = allc.pct_change(fill_method=None).fillna(0.0)
    gap = (opn / allc.shift(1) - 1).where(opn.notna() & allc.shift(1).notna())
    intra = (allc / opn - 1).where(gap.notna())
    gap, intra = gap.fillna(0.0), intra.fillna(rets)
    if members is None and cfg.point_in_time:
        members = membership_mask(px.index, px.columns)
    elif members is not None:
        members = members.reindex(index=px.index, columns=px.columns).ffill().fillna(True).astype(bool)

    first = px.index[min(len(px) - 1, 260)]
    if start:
        first = max(first, pd.Timestamp(start, tz=px.index.tz))
    dates = px.loc[first:].index
    if len(dates) < 2:
        raise ValueError("Not enough history: need at least ~1 year before the start date")
    rebal = set(pd.Series(dates, index=dates).resample(cfg.rebalance).last().dropna())
    cols = allc.columns
    weights = pd.Series(0.0, index=cols)
    equity, log = [1.0], []

    def decide(t):
        ranked = rank(px, bench, t, cfg, members)
        target = pd.Series(0.0, index=cols)
        items = _ranked_items(ranked, sectors) if not ranked.empty else []
        _, w, anchor, info = plan_weights(risk, items, False, allc if risk_aware else None, as_of=t, core_n=core_n,
                                          risk_budget=risk_aware, short_lookback=short_lookback)
        for s, v in w.items():
            target[s] = v
        target[SPY] += anchor
        log.append({"date": t.date().isoformat(), "core": float(sum(w.values())), "anchor": float(anchor),
                    "holdings": int((target > 0).sum()), "vol_est_%": info.get("vol_%"), "x_spy_est": info.get("x_spy"),
                    "spy_vol_est_%": info.get("spy_vol_%")})
        return target

    def grow(value, r):
        nonlocal weights
        day = float((weights * r).sum())
        weights = weights * (1 + r) / (1 + day)
        return value * (1 + day)

    pending = decide(dates[0])
    for t in dates[1:]:
        if pending is not None:
            value = grow(equity[-1], gap.loc[t])
            turnover = float((pending - weights).abs().sum())
            log[-1]["turnover"] = turnover
            value *= 1 - turnover * cost_bps / 10_000
            weights, pending = pending, None
            equity.append(grow(value, intra.loc[t]))
        else:
            equity.append(grow(equity[-1], rets.loc[t]))
        if t in rebal:
            pending = decide(t)

    eq = pd.Series(equity, index=dates) * 100
    b = bench.loc[dates] / bench.loc[dates].iloc[0] * 100
    return {"equity": eq, "benchmark": b, "log": log, "stats": level_stats(eq, b, log)}


def level_stats(eq: pd.Series, bench: pd.Series, log: list[dict] | None = None) -> dict:
    """CAGR, volatility, worst drop, Sharpe (cash = 0%), realized 1-in-20 month, months beating SPY, turnover."""
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    r = eq.pct_change().dropna()
    rb = bench.pct_change().dropna().reindex(r.index).fillna(0.0)
    m = eq.resample("ME").last().pct_change().dropna()
    mb = bench.resample("ME").last().pct_change().dropna()
    m, mb = m.align(mb, join="inner")
    vol = float(r.std() * np.sqrt(252))
    bvol = float(rb.std() * np.sqrt(252))
    yearly = pd.DataFrame({"p": r, "b": rb}).groupby(r.index.year).std()
    ratio = (yearly["p"] / yearly["b"]).replace([np.inf, -np.inf], np.nan).dropna()
    turns = [x.get("turnover", 0.0) for x in (log or [])[1:]]
    return {
        "cagr_%": ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100,
        "volatility_%": vol * 100,
        "vol_x_spy": vol / bvol if bvol > 0 else None,
        "vol_x_spy_by_year": {int(k): float(v) for k, v in ratio.items()},
        "max_drawdown_%": float((eq / eq.cummax() - 1).min() * 100),
        "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0,
        "month_1in20_%": float(np.percentile(m, 5) * 100) if len(m) else None,
        "worst_month_%": float(m.min() * 100) if len(m) else None,
        "months_beating_spy_%": float((m > mb).mean() * 100) if len(m) else None,
        "turnover_per_year_%": float(np.mean(turns) * 12 * 100) if turns else 0.0,
        "beta": float(np.cov(r, rb)[0, 1] / rb.var()) if rb.var() > 0 else None,
    }
