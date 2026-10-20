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
Options: keep a share in the benchmark itself (`core_spy`, core-satellite: the default "core_momentum" preset
holds 60% S&P 500), shrink the picks when they swing more than the benchmark (`vol_scale`, the rest in the
index), a turnover buffer (`buffer_n`) and a per-sector cap (`sector_max`). `robustness()` summarizes how
consistent the edge is (rolling 3-year windows, calendar years, halves, block-bootstrap odds).

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
    "core_momentum": {"momentum_12_1": 0.5, "momentum_6_1": 0.3, "rel_strength": 0.2},
    "momentum": {"momentum_12_1": 0.5, "momentum_6_1": 0.3, "rel_strength": 0.2},
    "quality_momentum": {"momentum_12_1": 0.35, "rel_strength": 0.25, "trend": 0.15, "low_vol": 0.25},
    "low_volatility": {"low_vol": 0.6, "trend": 0.2, "momentum_12_1": 0.2},
    "trend_following": {"trend": 0.4, "momentum_6_1": 0.3, "rel_strength": 0.3},
}
# Share held in the S&P 500 itself by default (core-satellite presets).
PRESET_CORE_SPY = {"core_momentum": 0.6}
# The app's main strategy (Beat-the-S&P page, Today board, alerts, plans' ranking), from the 2026-10 study.
# Honest history: the pre-registered 60% SPY + 40% pure 12-1 momentum (top 25) failed the 2015-2020 gate and
# gave only +1.6%/yr over the full period; this variant (40% in the momentum preset's top 10) came from the
# robustness runs made after the confirmation results existed, so its 2021-2026 result is not a clean
# out-of-sample test. An adversarial review (no look-ahead found) puts the believable edge at about +1-2%/yr
# with ~2-3 points deeper drawdowns: much of the backtest gain is 2026 and a few chip/storage stocks, and it
# fades with 50 bps costs or a survivorship drag of ~5%/yr on the momentum part. Not statistically proven.
DEFAULT_PRESET = "core_momentum"

PRESET_INFO = {
    "core_momentum": "60% in the S&P 500 itself + 40% in the 10 strongest momentum stocks. The S&P 500 part "
                     "keeps the swings close to the market's; the momentum part tries to add a little (realistically about "
                     "+1-2% a year, not proven).",
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
    buffer_n: int | None = None       # keep a holding while it still ranks in the top `buffer_n` (cuts turnover)
    sector_max: int | None = None     # at most this many picks per sector (None: no cap)
    core_spy: float | None = None     # share held in the benchmark itself (None: the preset's, usually 0)
    vol_scale: bool = False           # risk-managed: hold less of the picks when they swing more than the benchmark
    vol_lookback: int = 126           # days of returns used by vol_scale; what is not in the picks sits in the index
    sectors: dict[str, str | None] | None = None   # symbol -> sector for `sector_max` (default: the universe)

    def factor_weights(self) -> dict[str, float]:
        return self.weights or PRESETS[self.preset]

    def spy_share(self) -> float:
        return float(self.core_spy if self.core_spy is not None else PRESET_CORE_SPY.get(self.preset, 0.0))


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


def select(eligible: list[str], held: set[str], top_n: int, buffer_n: int | None = None,
           sector_max: int | None = None, sectors: dict[str, str | None] | None = None) -> list[str]:
    """Pick `top_n` names from `eligible` (best first). With `buffer_n`, current holdings that still rank in
    the top `buffer_n` are kept first (fewer trades); with `sector_max`, no sector gets more than that many."""
    order = list(eligible)
    if buffer_n:
        keep = [s for s in order[:buffer_n] if s in held]
        order = keep + [s for s in order if s not in keep]
    out: list[str] = []
    count: dict[str, int] = {}
    for s in order:
        if len(out) >= top_n:
            break
        sec = (sectors or {}).get(s) or "Other"
        if sector_max and count.get(sec, 0) >= sector_max:
            continue
        out.append(s)
        count[sec] = count.get(sec, 0) + 1
    return out


BENCH = "__benchmark__"   # internal column name of the benchmark when it is held


def vol_scale_factor(stock_rets: pd.DataFrame, bench_rets: pd.Series, lookback: int = 126) -> float:
    """Risk-managed momentum (Barroso & Santa-Clara 2015), long-only and without leverage: the share of the
    equal-weight basket to hold so its recent volatility is no higher than the benchmark's, min(1, vol_b / vol_p).
    Uses the last `lookback` daily returns given (pass data up to the decision date only)."""
    r = stock_rets.iloc[-lookback:].fillna(0.0).mean(axis=1)
    b = bench_rets.iloc[-lookback:]
    vp, vb = float(r.std()), float(b.std())
    if not np.isfinite(vp) or vp <= 0 or not np.isfinite(vb):
        return 1.0
    return float(min(1.0, vb / vp))


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
    sectors = cfg.sectors
    if cfg.sector_max and sectors is None:
        from .universe import by_symbol
        info = by_symbol()
        sectors = {s: (info[s].sector if s in info else None) for s in px.columns}

    # The benchmark itself can be held (core-satellite, risk-managed): column BENCH, next-open fills too.
    stock_rets = px.pct_change(fill_method=None)
    bopen = benchmark["open"].copy() if "open" in benchmark else benchmark["close"].copy()
    bopen.index = bopen.index.normalize()
    bopen = bopen[~bopen.index.duplicated(keep="last")].reindex(bench.index)
    b_ret = bench.pct_change().fillna(0.0)
    b_gap = (bopen / bench.shift(1) - 1).where(bopen.notna() & bench.shift(1).notna())
    b_intra = (bench / bopen - 1).where(b_gap.notna())
    rets[BENCH], gap[BENCH], intra[BENCH] = b_ret, b_gap.fillna(0.0), b_intra.fillna(b_ret)

    first = px.index[min(len(px) - 1, 260)]
    if start:
        first = max(first, pd.Timestamp(start, tz=px.index.tz))
    dates = px.loc[first:].index
    if len(dates) < 2:
        raise ValueError("Not enough history: need at least ~1 year before the start date")
    rebal = set(pd.Series(dates, index=dates).resample(cfg.rebalance).last().dropna())

    spy_share = cfg.spy_share()
    cols = list(px.columns) + [BENCH]
    weights = pd.Series(0.0, index=cols)          # fraction of equity per holding; the rest is cash
    equity, holdings = [1.0], []
    pending: pd.Series | None = None              # target decided at a close, filled at the next open
    last_picks: set[str] = set()

    def decide(t: pd.Timestamp) -> pd.Series:
        nonlocal last_picks
        ranked = rank(px, bench, t, cfg, members)
        target = pd.Series(0.0, index=cols)
        risk_off = bool(cfg.regime_filter and bench.loc[t] < bench_ma200.loc[t])
        picks: list[str] = []
        if not ranked.empty and not risk_off:
            picks = select(list(ranked.index[ranked["eligible"]]), last_picks, cfg.top_n, cfg.buffer_n,
                           cfg.sector_max, sectors)
            if picks:
                scale = vol_scale_factor(stock_rets[picks].loc[:t], b_ret.loc[:t], cfg.vol_lookback) \
                    if cfg.vol_scale else 1.0
                target[picks] = (1.0 - spy_share) * scale / len(picks)
        if not risk_off and (spy_share > 0 or cfg.vol_scale):
            target[BENCH] = max(0.0, 1.0 - float(target.sum()))   # fully invested: the rest is in the index
        last_picks = set(picks)
        holdings.append({"date": t.date().isoformat(), "symbols": picks,
                         "turnover": float((target - weights).abs().sum()), "risk_off": risk_off,
                         "benchmark_weight": float(target[BENCH])})
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
    res.stats["benchmark_weight_%"] = float(holdings[-1].get("benchmark_weight", 0.0) * 100) if holdings else 0.0
    # A review decided on the last bar of a running period has not filled yet: leave it out of turnover.
    filled = holdings[1:-1] if pending is not None else holdings[1:]
    res.stats["turnover_per_year_%"] = float(sum(h.get("turnover", 0.0) for h in filled) /
                                             max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9) * 100)
    return res


def robustness(eq: pd.Series, bench: pd.Series, window_months: int = 36, block: int = 12,
               sims: int = 2000, seed: int = 0) -> dict:
    """How consistent the edge over the benchmark is (plain numbers for the UI):
    - rolling `window_months` windows (monthly steps): share where the strategy's yearly return beat the benchmark's,
      and the worst / median gap in %/yr,
    - calendar years beating the benchmark,
    - the two halves of the period (did it win in both, or only in one?),
    - the chance of beating the benchmark over 5 and 10 years, from a circular block bootstrap of monthly
      returns (blocks of `block` months keep streaks and crashes together). It re-shuffles THIS history, so it
      assumes the future looks like the past: an upper bound on confidence, not a promise."""
    m = eq.resample("ME").last()
    mb = bench.resample("ME").last()
    m, mb = m.align(mb, join="inner")
    out: dict = {}
    if len(m) > window_months:
        k = window_months / 12
        gap = (((m / m.shift(window_months)) ** (1 / k) - (mb / mb.shift(window_months)) ** (1 / k)) * 100).dropna()
        out.update({"window_years": int(k), "windows": int(len(gap)), "windows_beating_%": float((gap > 0).mean() * 100),
                    "worst_window_gap_%": float(gap.min()), "median_window_gap_%": float(gap.median())})
    ye, yb = eq.groupby(eq.index.year).last(), bench.groupby(bench.index.year).last()
    ry = ye / ye.shift(1).fillna(eq.iloc[0]) - 1
    rby = yb / yb.shift(1).fillna(bench.iloc[0]) - 1
    out["years"] = [{"year": int(y), "return_%": float(ry[y] * 100), "benchmark_%": float(rby[y] * 100)} for y in ry.index]
    out["years_beating"] = int((ry > rby).sum())
    out["years_total"] = int(len(ry))
    mid = eq.index[0] + (eq.index[-1] - eq.index[0]) / 2
    halves = []
    for a, b in ((eq.index[0], mid), (mid, eq.index[-1])):
        s, sb = eq.loc[a:b], bench.loc[a:b]
        yrs = max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
        halves.append({"start": s.index[0].date().isoformat(), "end": s.index[-1].date().isoformat(),
                       "cagr_%": float(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100),
                       "benchmark_cagr_%": float(((sb.iloc[-1] / sb.iloc[0]) ** (1 / yrs) - 1) * 100)})
    out["halves"] = halves
    out["both_halves_beating"] = all(h["cagr_%"] > h["benchmark_cagr_%"] for h in halves)
    r = np.log1p(np.c_[m.pct_change().dropna().values, mb.pct_change().dropna().values])
    if len(r) >= 24:
        rng = np.random.default_rng(seed)
        for years in (5, 10):
            h = years * 12
            nb = int(np.ceil(h / block))
            idx = (rng.integers(0, len(r), size=(sims, nb))[:, :, None] + np.arange(block)).reshape(sims, -1)[:, :h]
            s = r[idx % len(r)].sum(axis=1)
            out[f"p_beat_{years}y_%"] = float((s[:, 0] > s[:, 1]).mean() * 100)
    return out
