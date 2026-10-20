"""ETF rotation: hold the strongest US sectors (or asset classes) with a trend filter, tested back to 1999.

Why ETFs: our stock universe only has reliable point-in-time S&P 500 membership from 2015, while the sector
SPDRs exist since December 1998, so a rotation among them can be tested over 2000-02, 2008, 2011, 2015-16,
2018, 2020 and 2022 without survivorship bias (the funds existed and could be bought at the time).

Rule, at every review date t (month end by default), using ONLY closes up to t:
1. Momentum of each ETF = return from `lookback` to `skip` trading days ago (12-1 by default: the last month
   is skipped, as in the academic momentum literature).
2. Hold the `top_k` strongest, equal weight. With `trend_filter`, a slot whose ETF is below its 200-day average
   goes to cash instead (absolute momentum, Antonacci 2014 / Faber 2007).
3. Optional `vol_target`: if the book swung more than this (annualized, last `vol_lookback` days), hold less of it
   and the rest in cash (Barroso & Santa-Clara 2015, Moreira & Muir 2017). Never leverages.
4. Optional `core_spy`: that share always sits in SPY (core-satellite).
Trades fill at the NEXT day's open, `cost_bps` per unit of turnover. Cash = SHY (1-3y Treasuries) when it has
data, else the 13-week T-bill yield (^IRX) accrued daily, else 0%.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SECTOR_ETFS = ("XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC")
MULTI_ASSET = ("SPY", "QQQ", "IWM", "EFA", "TLT", "IEF", "GLD")
CASH = "SHY"
SPY = "SPY"
CASH_COL = "__cash__"

ETF_NAMES = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care",
    "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLI": "Industrials", "XLB": "Materials",
    "XLU": "Utilities", "XLRE": "Real Estate", "XLC": "Communication Services", "SPY": "S&P 500",
    "QQQ": "Nasdaq 100", "IWM": "US small caps", "EFA": "International developed", "TLT": "Long US Treasuries",
    "IEF": "7-10y US Treasuries", "GLD": "Gold", "SHY": "Cash (1-3y US Treasuries)",
}


@dataclass
class RotationConfig:
    universe: tuple[str, ...] = SECTOR_ETFS
    top_k: int = 3
    lookback: int = 252          # momentum window start (trading days ago)
    skip: int = 21               # momentum window end: skip the most recent month
    trend_filter: bool = True    # a slot below its 200-day average goes to cash
    vol_target: float | None = None
    vol_lookback: int = 126
    core_spy: float = 0.0
    rebalance: str = "ME"
    cost_bps: float = 10.0


@dataclass
class RotationResult:
    equity: pd.Series
    benchmark: pd.Series
    holdings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    current: dict = field(default_factory=dict)


def _frame(frames: dict[str, pd.DataFrame], col: str) -> pd.DataFrame:
    out = pd.DataFrame({s: (df[col] if col in df else df["close"]) for s, df in frames.items()})
    out.index = out.index.normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


def cash_returns(index: pd.DatetimeIndex, shy_close: pd.Series | None, irx: pd.Series | None) -> pd.Series:
    """Daily return of cash: SHY where it trades, else yesterday's T-bill yield / 252, else 0."""
    r = pd.Series(0.0, index=index)
    if irx is not None and len(irx):
        y = irx.copy()
        y.index = y.index.normalize()
        y = y[~y.index.duplicated(keep="last")].reindex(index).ffill()
        r = (y.shift(1) / 100 / 252).fillna(0.0)
    if shy_close is not None and len(shy_close):
        s = shy_close.copy()
        s.index = s.index.normalize()
        s = s[~s.index.duplicated(keep="last")].reindex(index)
        sr = s.pct_change(fill_method=None)
        r = sr.where(sr.notna() & s.shift(1).notna(), r)
    return r


def rotation_target(closes: pd.DataFrame, t: pd.Timestamp, cfg: RotationConfig) -> tuple[pd.Series, dict]:
    """Target weights at date t from closes up to t only. Columns of `closes`: ETFs (+ SPY). Cash = the rest."""
    hist = closes.loc[:t]
    uni = [s for s in cfg.universe if s in hist.columns]
    w = pd.Series(0.0, index=list(closes.columns) + [CASH_COL])
    info: dict = {"momentum": {}, "above_trend": {}, "scale": 1.0}
    if len(hist) <= cfg.lookback:
        w[CASH_COL] = 1.0
        return w, info
    a, z, last = hist.iloc[-cfg.lookback - 1], hist.iloc[-cfg.skip - 1], hist.iloc[-1]
    ma200 = hist.iloc[-200:].mean()
    full = hist.iloc[-cfg.lookback - 1:].notna().all()
    mom = (z / a - 1)[uni]
    mom = mom[full[uni] & last[uni].notna()].dropna().sort_values(ascending=False)
    info["momentum"] = {s: float(v) for s, v in mom.items()}
    info["above_trend"] = {s: bool(last[s] > ma200[s]) for s in mom.index}
    chosen = list(mom.index[: cfg.top_k])
    if not chosen:
        w[CASH_COL] = 1.0
        return w, info
    slot = 1.0 / cfg.top_k if len(mom) >= cfg.top_k else 1.0 / len(chosen)
    for s in chosen:
        if cfg.trend_filter and not info["above_trend"][s]:
            w[CASH_COL] += slot
        else:
            w[s] += slot
    risky = [s for s in chosen if w[s] > 0]
    if cfg.vol_target and risky:
        r = hist[risky].iloc[-cfg.vol_lookback - 1:].pct_change(fill_method=None).iloc[1:].fillna(0.0)
        vol = float((r * w[risky]).sum(axis=1).std() * np.sqrt(252))
        if vol > 0:
            scale = min(1.0, cfg.vol_target / vol)
            info["scale"] = scale
            moved = w[risky] * (1 - scale)
            w[risky] -= moved
            w[CASH_COL] += float(moved.sum())
    if cfg.core_spy > 0:
        w *= 1 - cfg.core_spy
        w[SPY] += cfg.core_spy
    return w, info


def run_rotation(frames: dict[str, pd.DataFrame], cfg: RotationConfig | None = None, start: str | None = None,
                 end: str | None = None, irx: pd.Series | None = None) -> RotationResult:
    """Backtest. `frames` holds daily OHLC for the ETFs, SPY (benchmark, required) and SHY (cash) if available.
    `irx`: 13-week T-bill yield in % (Yahoo ^IRX close) for cash before SHY existed (optional)."""
    from .picker import _stats

    cfg = cfg or RotationConfig()
    if SPY not in frames:
        raise ValueError("SPY is required (benchmark)")
    tradable = [s for s in dict.fromkeys(list(cfg.universe) + [SPY]) if s in frames]
    closes = _frame({s: frames[s] for s in tradable}, "close")
    opens = _frame({s: frames[s] for s in tradable}, "open")
    if end:
        closes = closes.loc[:pd.Timestamp(end, tz=closes.index.tz)]
    idx = closes.index[closes[SPY].notna()]
    closes, opens = closes.reindex(idx), opens.reindex(idx).where(closes.reindex(idx).notna())
    held_px = closes.ffill(limit=5)
    rets = held_px.pct_change(fill_method=None)
    gap = (opens / held_px.shift(1) - 1).where(opens.notna() & held_px.shift(1).notna())
    intra = (held_px / opens - 1).where(gap.notna())
    rets, gap, intra = rets.fillna(0.0), gap.fillna(0.0), intra.fillna(rets.fillna(0.0))
    cr = cash_returns(idx, frames[CASH]["close"] if CASH in frames else None, irx)
    rets[CASH_COL], gap[CASH_COL], intra[CASH_COL] = cr, 0.0, cr   # cash accrues over the day, no overnight gap

    first = idx[min(len(idx) - 1, cfg.lookback + 1)]
    if start:
        first = max(first, pd.Timestamp(start, tz=idx.tz))
    dates = idx[idx >= first]
    if len(dates) < 2:
        raise ValueError("Not enough history: need at least ~1 year before the start date")
    rebal = set(pd.Series(dates, index=dates).resample(cfg.rebalance).last().dropna())
    weights = pd.Series(0.0, index=rets.columns)
    weights[CASH_COL] = 1.0
    equity, holdings = [1.0], []
    last_info: dict = {}

    def decide(t):
        nonlocal last_info
        target, info = rotation_target(closes, t, cfg)
        target = target.reindex(rets.columns).fillna(0.0)
        last_info = info
        holdings.append({"date": t.date().isoformat(),
                         "symbols": [s for s in target.index if target[s] > 1e-9 and s != CASH_COL],
                         "weights": {("CASH" if s == CASH_COL else s): float(v) for s, v in target.items() if v > 1e-9},
                         "turnover": float((target - weights).abs().sum()), "risk_off": False})
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
            holdings[-1]["turnover"] = turnover
            value *= 1 - turnover * cfg.cost_bps / 10_000
            weights, pending = pending, None
            equity.append(grow(value, intra.loc[t]))
        else:
            equity.append(grow(equity[-1], rets.loc[t]))
        if t in rebal:
            pending = decide(t)

    eq = pd.Series(equity, index=dates, name="portfolio") * 100
    b = closes[SPY].loc[dates] / closes[SPY].loc[dates].iloc[0] * 100
    res = RotationResult(eq, b, holdings)
    res.stats = _stats(eq, b, holdings)
    target, info = rotation_target(closes, idx[-1], cfg)
    res.current = {"date": idx[-1].date().isoformat(),
                   "weights": {("CASH" if s == CASH_COL else s): float(v) for s, v in target.items() if v > 1e-9},
                   **info}
    return res
