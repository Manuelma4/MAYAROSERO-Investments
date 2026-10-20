"""Probabilistic price forecasts and volume analysis.

Monte Carlo ("filtered historical simulation", a standard risk-desk method):
1. Estimate today's volatility with an EWMA / GARCH-type recursion (RiskMetrics, lambda = 0.94),
   so calm and stormy periods are reflected (volatility clustering).
2. Standardize past daily returns by the volatility of their day -> a library of realistic "shocks"
   (keeps fat tails and skew that a normal distribution misses).
3. Simulate thousands of future paths: each day draw a past shock, scale it by the current simulated
   volatility, and update the volatility with the same recursion.
Result: a fan of likely price ranges, P(up) / P(down) at the horizon, and the 5-95% range.
Drift is set to the long-run average daily return (close to zero), so the simulation describes risk
and range, not a directional bet; the direction view comes from the cross-sectional ranker.

Volume analysis: volume profile (where most shares changed hands: point of control and the 70% value
area), VWAP with standard-deviation bands, relative volume and on-balance volume.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LAMBDA = 0.94


def ewma_vol(r: np.ndarray, lam: float = LAMBDA) -> np.ndarray:
    v = np.empty_like(r)
    v[0] = np.var(r[: min(30, len(r))]) or 1e-6
    for t in range(1, len(r)):
        v[t] = lam * v[t - 1] + (1 - lam) * r[t - 1] ** 2
    return np.sqrt(v)


def monte_carlo(close: pd.Series, horizon: int = 5, n_paths: int = 5000, lookback: int = 750,
                seed: int | None = 7, drift: str = "historical") -> dict:
    c = close.dropna().iloc[-(lookback + 1):]
    r = np.log(c).diff().dropna().to_numpy()
    if len(r) < 120:
        raise ValueError("Need at least ~120 days of history for a forecast")
    sig = ewma_vol(r)
    z = r / sig                                     # standardized shocks
    z = (z - z.mean()) / z.std()
    mu = float(r.mean()) if drift == "historical" else 0.0
    mu = float(np.clip(mu, -0.001, 0.001))          # cap extrapolated drift at +/-0.1%/day
    rng = np.random.default_rng(seed)
    var = np.full(n_paths, LAMBDA * sig[-1] ** 2 + (1 - LAMBDA) * r[-1] ** 2)
    logp = np.zeros((horizon + 1, n_paths))
    for t in range(1, horizon + 1):
        shock = rng.choice(z, size=n_paths) * np.sqrt(var)
        step = mu - 0.5 * var + shock
        logp[t] = logp[t - 1] + step
        var = LAMBDA * var + (1 - LAMBDA) * shock ** 2
    paths = float(c.iloc[-1]) * np.exp(logp)
    q = np.percentile(paths, [5, 25, 50, 75, 95], axis=1)
    end = paths[-1]
    p0 = float(c.iloc[-1])
    return {
        "horizon": horizon, "paths": n_paths, "last_price": p0,
        "daily_vol_%": float(np.sqrt(var.mean()) * 100), "annual_vol_%": float(sig[-1] * np.sqrt(252) * 100),
        "p_up": float((end > p0).mean()), "p_down": float((end < p0).mean()),
        "range_5_95": [float(np.percentile(end, 5)), float(np.percentile(end, 95))],
        "median": float(np.median(end)),
        "p_move_up_5%": float((end >= p0 * 1.05).mean()), "p_move_down_5%": float((end <= p0 * 0.95).mean()),
        "fan": {name: [float(x) for x in q[i]] for i, name in enumerate(["p5", "p25", "p50", "p75", "p95"])},
    }


def volume_profile(df: pd.DataFrame, bins: int = 24, value_area: float = 0.70) -> dict:
    """Volume traded at each price level (typical price of each bar, weighted by its volume)."""
    d = df.dropna(subset=["close", "volume"])
    tp = ((d["high"] + d["low"] + d["close"]) / 3).to_numpy()
    vol = d["volume"].to_numpy()
    lo, hi = float(d["low"].min()), float(d["high"].max())
    if hi <= lo or vol.sum() <= 0:
        return {"bins": [], "poc": None, "value_area": [None, None]}
    edges = np.linspace(lo, hi, bins + 1)
    hist, _ = np.histogram(tp, bins=edges, weights=vol)
    poc_i = int(hist.argmax())
    # Value area: expand from the POC until 70% of volume is covered.
    total, covered, lo_i, hi_i = hist.sum(), hist[poc_i], poc_i, poc_i
    while covered < value_area * total and (lo_i > 0 or hi_i < bins - 1):
        down = hist[lo_i - 1] if lo_i > 0 else -1
        up = hist[hi_i + 1] if hi_i < bins - 1 else -1
        if up >= down:
            hi_i += 1
            covered += hist[hi_i]
        else:
            lo_i -= 1
            covered += hist[lo_i]
    mid = (edges[:-1] + edges[1:]) / 2
    return {
        "bins": [{"price": float(p), "volume": float(v), "share": float(v / total)} for p, v in zip(mid, hist)],
        "poc": float(mid[poc_i]), "value_area": [float(edges[lo_i]), float(edges[hi_i + 1])],
    }


def vwap_bands(df: pd.DataFrame, k: tuple[float, ...] = (1.0, 2.0)) -> pd.DataFrame:
    """Session-anchored VWAP (resets each day) with volume-weighted standard-deviation bands."""
    d = df.copy()
    tp = (d["high"] + d["low"] + d["close"]) / 3
    day = d.index.normalize()
    pv = (tp * d["volume"]).groupby(day).cumsum()
    vv = d["volume"].groupby(day).cumsum().replace(0, np.nan)
    vwap = pv / vv
    var = ((tp - vwap) ** 2 * d["volume"]).groupby(day).cumsum() / vv
    out = pd.DataFrame({"vwap": vwap}, index=d.index)
    for x in k:
        out[f"upper_{x:g}"] = vwap + x * np.sqrt(var)
        out[f"lower_{x:g}"] = vwap - x * np.sqrt(var)
    return out


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()
