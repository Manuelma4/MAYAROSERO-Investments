"""Stock picker: rank stocks by factors, hold the top N, and measure it against the S&P 500.

How it works, at each rebalance date (e.g. every month end):
1. Compute factors for every stock using ONLY prices up to that date:
   - momentum_12_1: 12-month return excluding the last month (the most
     documented equity factor; skipping the last month avoids short-term reversal)
   - momentum_6_1:  6-month return excluding the last month
   - rel_strength:  6-month return minus the benchmark's 6-month return
   - trend:         distance above the 200-day average
   - low_vol:       minus the 3-month daily volatility (calmer stocks score higher)
2. Standardize each factor across stocks (z-scores, clipped) and combine with
   the weights of the chosen preset into one score.
3. Buy the top N equally weighted (optionally only stocks above their 200-day
   average, and optionally go to cash when the benchmark itself is in a downtrend).
   The decision uses the close of the review day; trades fill at the NEXT day's open.
4. Hold until the next rebalance; trading costs are charged on turnover.

Point-in-time membership (`point_in_time=True`, the default): a stock can only be
picked, and only counts in the equal-weight yardstick, from the date it actually
joined the S&P 500 (`universe.membership_spells`). Without this, today's members
that joined after a huge run (PLTR, SMCI, APP, CVNA, ...) get "bought" during the
run-up, which no investor following the index could have done.

Honesty notes shown in the UI:
- Companies that LEFT the index are still missing (residual survivorship bias), and
  the join-date list is approximate, so backtests remain somewhat flattering.
- Factor premiums are real on average but can underperform for years.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

PRESETS: dict[str, dict[str, float]] = {
    "momentum": {"momentum_12_1": 0.5, "momentum_6_1": 0.3, "rel_strength": 0.2},
    "quality_momentum": {"momentum_12_1": 0.35, "rel_strength": 0.25, "trend": 0.15, "low_vol": 0.25},
    "low_volatility": {"low_vol": 0.6, "trend": 0.2, "momentum_12_1": 0.2},
    "trend_following": {"trend": 0.4, "momentum_6_1": 0.3, "rel_strength": 0.3},
}

PRESET_INFO = {
    "momentum": "Winners keep winning: strongest 6-12 month performers.",
    "quality_momentum": "Strong performers with calmer price action (smoother ride).",
    "low_volatility": "Calm, defensive stocks still in an uptrend.",
    "trend_following": "Stocks in the strongest established uptrends vs the market.",
}


@dataclass
class PickerConfig:
    preset: str = "quality_momentum"
    top_n: int = 10
    rebalance: str = "ME"             # pandas offset: ME month-end, QE quarter-end, W-FRI weekly
    trend_filter: bool = True         # only buy stocks above their 200-day average
    regime_filter: bool = False       # hold cash when the benchmark is below its 200-day average
    cost_bps: float = 10.0            # cost per unit of turnover (10 bps = 0.10%)
    point_in_time: bool = True        # only pick S&P 500 stocks from the date they joined the index
    weights: dict[str, float] | None = None

    def factor_weights(self) -> dict[str, float]:
        return self.weights or PRESETS[self.preset]


def _closes(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    px = pd.DataFrame({s: df["close"] for s, df in frames.items()})
    px.index = px.index.normalize()
    return px[~px.index.duplicated(keep="last")].sort_index()


def _opens(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    op = pd.DataFrame({s: df["open"] if "open" in df else df["close"] for s, df in frames.items()})
    op.index = op.index.normalize()
    return op[~op.index.duplicated(keep="last")].sort_index()


def membership_mask(index: pd.DatetimeIndex, symbols, spells: dict | None = None) -> pd.DataFrame:
    """True where a symbol was an S&P 500 member on that date (point-in-time approximation).

    Symbols without recorded spells (long-time members, or stocks outside the S&P 500 such as
    a custom list) are allowed on every date."""
    if spells is None:
        from .universe import membership_spells
        spells = membership_spells()
    tz = index.tz
    mask = pd.DataFrame(True, index=index, columns=list(symbols))
    for sym in mask.columns:
        if sym not in spells:
            continue
        inside = np.zeros(len(index), dtype=bool)
        for added, removed in spells[sym]:
            lo = pd.Timestamp(added, tz=tz) if added else index.min()
            hi = pd.Timestamp(removed, tz=tz) if removed else index.max() + pd.Timedelta(days=1)
            inside |= (index >= lo) & (index < hi)
        mask[sym] = inside
    return mask


def factors_at(px: pd.DataFrame, bench: pd.Series, t: pd.Timestamp) -> pd.DataFrame:
    """Factor table for all symbols using data up to and including date t."""
    hist = px.loc[:t]
    b = bench.loc[:t]
    if len(hist) < 260:
        return pd.DataFrame()

    def ret(series_or_frame, start, end):
        a = series_or_frame.iloc[-start - 1] if start else None
        z = series_or_frame.iloc[-end - 1]
        return z / a - 1

    last = hist.iloc[-1]
    f = pd.DataFrame(index=px.columns)
    f["momentum_12_1"] = ret(hist, 252, 21)
    f["momentum_6_1"] = ret(hist, 126, 21)
    f["rel_strength"] = (last / hist.iloc[-127] - 1) - (b.iloc[-1] / b.iloc[-127] - 1)
    f["trend"] = last / hist.iloc[-200:].mean() - 1
    f["low_vol"] = -hist.iloc[-63:].pct_change(fill_method=None).std() * np.sqrt(252)
    f["return_1m"] = last / hist.iloc[-22] - 1
    f["price"] = last
    # Need a full year of history and a current price.
    ok = hist.iloc[-253:].notna().all() & last.notna()
    return f[ok]


def score(f: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    total = pd.Series(0.0, index=f.index)
    for col, w in weights.items():
        x = f[col]
        z = ((x - x.mean()) / x.std(ddof=0)).clip(-3, 3) if x.std(ddof=0) > 0 else x * 0
        total += w * z.fillna(0)
    return total / sum(abs(w) for w in weights.values())


def rank(px: pd.DataFrame, bench: pd.Series, t: pd.Timestamp, cfg: PickerConfig,
         members: pd.DataFrame | None = None) -> pd.DataFrame:
    """Ranked factor table at date t. `members` (dates x symbols, bool) drops stocks that were
    not index members at t; membership at t is a historical fact known at t (no look-ahead)."""
    f = factors_at(px, bench, t)
    if members is not None and not f.empty:
        known = members.loc[:t]
        if len(known):
            f = f[known.iloc[-1].reindex(f.index).fillna(True).astype(bool)]
    if f.empty:
        return f
    f["score"] = score(f, cfg.factor_weights())
    f["eligible"] = f["trend"] > 0 if cfg.trend_filter else True
    return f.sort_values("score", ascending=False)


@dataclass
class PickerResult:
    equity: pd.Series
    benchmark: pd.Series
    holdings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    current: pd.DataFrame = field(default_factory=pd.DataFrame)


def _stats(eq: pd.Series, bench: pd.Series, holdings: list[dict]) -> dict:
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    r, rb = eq.pct_change().dropna(), bench.pct_change().dropna()

    def cagr(s):
        return (s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1

    def mdd(s):
        return float((s / s.cummax() - 1).min())

    cov = np.cov(r, rb.reindex(r.index).fillna(0))
    beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 0 else 0.0
    m, mb = eq.resample("ME").last().pct_change().dropna(), bench.resample("ME").last().pct_change().dropna()
    m, mb = m.align(mb, join="inner")
    turnover = np.mean([h["turnover"] for h in holdings[1:]]) if len(holdings) > 1 else 0.0
    return {
        "start": eq.index[0].date().isoformat(), "end": eq.index[-1].date().isoformat(),
        "total_return_%": (eq.iloc[-1] / eq.iloc[0] - 1) * 100,
        "benchmark_return_%": (bench.iloc[-1] / bench.iloc[0] - 1) * 100,
        "cagr_%": cagr(eq) * 100, "benchmark_cagr_%": cagr(bench) * 100,
        "excess_cagr_%": (cagr(eq) - cagr(bench)) * 100,
        "volatility_%": float(r.std() * np.sqrt(252) * 100),
        "benchmark_volatility_%": float(rb.std() * np.sqrt(252) * 100),
        "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0,
        "benchmark_sharpe": float(rb.mean() / rb.std() * np.sqrt(252)) if rb.std() > 0 else 0.0,
        "max_drawdown_%": mdd(eq) * 100, "benchmark_max_drawdown_%": mdd(bench) * 100,
        "beta": float(beta),
        "months_beating_benchmark_%": float((m > mb).mean() * 100) if len(m) else 0.0,
        "avg_turnover_%": float(turnover * 100),
        "rebalances": len(holdings),
    }


def run_picker(frames: dict[str, pd.DataFrame], benchmark: pd.DataFrame, cfg: PickerConfig | None = None,
               start: str | None = None, members: pd.DataFrame | None = None) -> PickerResult:
    """Backtest the picker. `members` overrides the point-in-time membership mask (tests)."""
    cfg = cfg or PickerConfig()
    px = _closes(frames)
    bench = benchmark["close"].copy()
    bench.index = bench.index.normalize()
    bench = bench[~bench.index.duplicated(keep="last")]
    raw = px.reindex(bench.index)
    px = raw.ffill(limit=5)                       # align to benchmark trading days
    rets = px.pct_change(fill_method=None).fillna(0.0)
    # Next-open fills: split each day into overnight (prev close -> open) and intraday (open -> close).
    opn = _opens(frames).reindex(bench.index).where(raw.notna())
    gap = (opn / px.shift(1) - 1).where(opn.notna() & px.shift(1).notna())
    intra = (px / opn - 1).where(gap.notna())
    gap, intra = gap.fillna(0.0), intra.fillna(rets)
    if members is None and cfg.point_in_time:
        members = membership_mask(px.index, px.columns)
    elif members is not None:
        members = members.reindex(index=px.index, columns=px.columns).ffill().fillna(True).astype(bool)
    bench_ma200 = bench.rolling(200).mean()

    first = px.index[min(len(px) - 1, 260)]
    if start:
        first = max(first, pd.Timestamp(start, tz=px.index.tz))
    dates = px.loc[first:].index
    if len(dates) < 2:
        raise ValueError("Not enough history: need at least ~1 year before the start date")
    rebal = set(pd.Series(dates, index=dates).resample(cfg.rebalance).last().dropna())

    weights = pd.Series(0.0, index=px.columns)   # fraction of equity per stock; the rest is cash
    equity, holdings = [1.0], []
    pending: pd.Series | None = None              # target decided at a close, filled at the next open

    def decide(t: pd.Timestamp) -> pd.Series:
        ranked = rank(px, bench, t, cfg, members)
        target = pd.Series(0.0, index=px.columns)
        risk_off = bool(cfg.regime_filter and bench.loc[t] < bench_ma200.loc[t])
        if not ranked.empty and not risk_off:
            picks = ranked[ranked["eligible"]].head(cfg.top_n).index
            if len(picks):
                target[picks] = 1.0 / len(picks)
        holdings.append({"date": t.date().isoformat(), "symbols": list(target[target > 0].index),
                         "turnover": float((target - weights).abs().sum()), "risk_off": risk_off})
        return target

    def grow(value: float, r: pd.Series) -> float:
        nonlocal weights
        day = float((weights * r).sum())
        weights = weights * (1 + r) / (1 + day)   # weights drift with prices; the rest is cash
        return value * (1 + day)

    pending = decide(dates[0])                    # decided at the first close, bought at the next open
    for t in dates[1:]:
        if pending is not None:
            value = grow(equity[-1], gap.loc[t])  # overnight move still on the old portfolio
            turnover = float((pending - weights).abs().sum())
            holdings[-1]["turnover"] = turnover
            value *= 1 - turnover * cfg.cost_bps / 10_000
            weights, pending = pending, None
            equity.append(grow(value, intra.loc[t]))
        else:
            equity.append(grow(equity[-1], rets.loc[t]))
        if t in rebal:
            pending = decide(t)                   # decided at today's close with data up to today

    eq = pd.Series(equity, index=dates, name="portfolio") * 100
    b = bench.loc[dates] / bench.loc[dates].iloc[0] * 100
    res = PickerResult(eq, b, holdings)
    res.stats = _stats(eq, b, holdings)
    res.stats["point_in_time"] = members is not None
    res.current = rank(px, bench, px.index[-1], cfg, members)
    return res
