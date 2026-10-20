"""Cross-sectional ranker: which stocks are likely to do better or worse than the others.

This is how quantitative funds frame short-term prediction: not "will NVDA go up?" (close to a coin
flip) but "will NVDA beat the typical stock over the next N days?". Quality is measured with the
information coefficient (IC): the rank correlation between the predicted score and the realized
forward returns across stocks on each date. Professional signals often have IC of 0.02-0.05;
anything consistently above 0 with a t-stat > 2 is a real, if small, edge.

- Target: each stock's percentile rank of its forward `horizon`-day return among all stocks that day.
- Model: gradient-boosted trees on backward-looking features (same as Predictor).
- Training rows: one date every `train_every` trading days (default min(horizon, 5): daily for the
  1-day ranker, weekly for 5 and 21 days). Neighbouring days carry overlapping labels, so weekly
  training lost no IC at 5/21 days on the real S&P 500 (2017-2026), but it did at 1 day, which keeps
  daily rows. Fits use float32 features and at most TRADEBOT_ML_THREADS (default 2) OpenMP threads:
  unlimited threads on a busy shared box oversubscribe the cores (the cause of ~20-minute runs).
- Validation: walk-forward by date with a purge gap of `horizon` days, scored on EVERY test date.
- Point-in-time universe (`point_in_time=True`): a stock only enters training and validation while
  it was an S&P 500 member (approximate join dates in `universe.membership_spells`), so the model is
  not trained or graded on future index joiners during the run-up that got them in.
- Probabilities: calibrated from validation (share of past cases in the same score decile that beat
  the median), so "62%" means "62 of 100 similar past cases outperformed".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .features import build_features


@dataclass
class RankerResult:
    horizon: int
    as_of: str
    scores: pd.DataFrame                     # per symbol: score, decile, p_outperform, p_underperform
    validation: dict = field(default_factory=dict)


def _panel(frames: dict[str, pd.DataFrame], horizon: int) -> tuple[pd.DataFrame, pd.Series]:
    """Features (float32) and forward returns, indexed by (date, symbol)."""
    xs, fwd = [], []
    for sym, df in frames.items():
        X = build_features(df).astype(np.float32)
        X["symbol"] = sym
        r = df["close"].shift(-horizon) / df["close"] - 1   # label only: never used as a feature
        xs.append(X)
        fwd.append(r.rename(sym))
    X = pd.concat(xs)
    X.index.name = "date"
    X = X.reset_index().set_index(["date", "symbol"]).sort_index()
    fwd_df = pd.concat(fwd, axis=1)
    fwd_df.index.name = "date"
    f = fwd_df.stack(future_stack=True)
    f.index.names = ["date", "symbol"]
    return X, f.reindex(X.index)


def _members(index: pd.MultiIndex, spells: dict | None) -> np.ndarray:
    from ..picker import membership_mask

    dates = pd.DatetimeIndex(index.get_level_values("date").unique().sort_values())
    mask = membership_mask(dates, sorted(set(index.get_level_values("symbol"))), spells)
    s = mask.stack()
    s.index.names = ["date", "symbol"]
    return s.reindex(index).fillna(True).to_numpy(bool)


def _model(max_iter: int = 150):
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(max_iter=max_iter, learning_rate=0.05, max_depth=4, min_samples_leaf=200,
                                         l2_regularization=1.0, random_state=0)


def _threads() -> int:
    """OpenMP threads for the tree fits. Unlimited OpenMP on a busy shared box oversubscribes the
    cores and was the main cause of 20-minute fits; 2 threads is the measured sweet spot."""
    try:
        return max(1, int(os.environ.get("TRADEBOT_ML_THREADS", "2")))
    except ValueError:
        return 2


def rank_universe(frames: dict[str, pd.DataFrame], horizon: int = 5, n_splits: int = 3,
                  min_names: int = 20, train_every: int | None = None, point_in_time: bool = True,
                  spells: dict | None = None) -> RankerResult:
    from threadpoolctl import threadpool_limits

    train_every = max(1, min(horizon, 5)) if train_every is None else max(1, int(train_every))
    with threadpool_limits(limits=_threads(), user_api="openmp"):
        return _rank_universe(frames, horizon, n_splits, min_names, train_every, point_in_time, spells)


def _rank_universe(frames, horizon, n_splits, min_names, train_every, point_in_time, spells) -> RankerResult:
    X, fwd = _panel(frames, horizon)
    good = (X.notna().sum(axis=1) > X.shape[1] * 0.8).to_numpy()
    if point_in_time:
        good = good & _members(X.index, spells)
    X, fwd = X[good], fwd[good]
    # Rank among the stocks that are actually in the universe that day.
    target = fwd.groupby(level="date").rank(pct=True)
    dates = X.index.get_level_values("date").unique().sort_values()
    if len(dates) < 400:
        raise ValueError("Need at least ~400 trading days of history")
    d = X.index.get_level_values("date")
    Xv = X.to_numpy(np.float32)
    yv = target.to_numpy(np.float64)
    labeled = np.isfinite(yv)
    sampled = d.isin(dates[::-1][::train_every])              # training dates: every `train_every` days

    # Walk-forward validation
    edges = np.linspace(len(dates) * 0.5, len(dates) - horizon, n_splits + 1).astype(int)
    ics, spreads, calib_rows = [], [], []
    for k in range(n_splits):
        train_end = dates[edges[k] - 1 - horizon]               # purge: labels end before the test starts
        test = (dates[edges[k]], dates[edges[k + 1] - 1])
        tr = (d <= train_end) & labeled & sampled
        te = (d >= test[0]) & (d <= test[1]) & labeled
        if tr.sum() < 1000 or te.sum() == 0:
            continue
        m = _model().fit(Xv[tr], yv[tr])
        df = pd.DataFrame({"pred": m.predict(Xv[te]), "target": yv[te], "fwd": fwd.to_numpy()[te]},
                          index=X.index[te])
        for _, g in df.groupby(level="date"):
            if len(g) < min_names:
                continue
            ics.append(g["pred"].rank().corr(g["target"].rank()))
            dec = pd.qcut(g["pred"].rank(method="first"), 10, labels=False)
            spreads.append(g["fwd"][dec == 9].mean() - g["fwd"][dec == 0].mean())
            calib_rows.append(pd.DataFrame({"decile": dec, "beat": g["target"] > 0.5}))
    ic = np.array([x for x in ics if np.isfinite(x)])
    calib = pd.concat(calib_rows).groupby("decile")["beat"].mean() if calib_rows else pd.Series(dtype=float)
    spread = np.array([x for x in spreads if np.isfinite(x)])
    ic_mean = float(ic.mean()) if len(ic) else 0.0
    ic_t = float(ic_mean / (ic.std(ddof=1) / np.sqrt(len(ic)))) if len(ic) > 2 and ic.std() > 0 else 0.0
    # Overlapping horizons inflate t-stats; scale by sqrt(horizon) to stay honest.
    ic_t_adj = ic_t / np.sqrt(horizon)
    validation = {
        "dates_tested": int(len(ic)), "ic_mean": ic_mean, "ic_t_stat": float(ic_t_adj),
        "ic_positive_share": float((ic > 0).mean()) if len(ic) else 0.0,
        "top_minus_bottom_per_period_%": float(spread.mean() * 100) if len(spread) else 0.0,
        "calibration": {int(k): float(v) for k, v in calib.items()},
        "has_edge": bool(ic_mean > 0.01 and ic_t_adj > 2.0),
        "point_in_time": point_in_time, "train_every_days": int(train_every),
    }

    # Fit on every sampled labeled date, score the latest date
    model = _model().fit(Xv[labeled & sampled], yv[labeled & sampled])
    last = dates.max()
    latest = X.xs(last, level="date")
    scores = pd.Series(model.predict(latest.to_numpy(np.float32)), index=latest.index, name="score")
    dec = pd.qcut(scores.rank(method="first"), 10, labels=False)
    p_out = dec.map(lambda d: validation["calibration"].get(int(d), 0.5))
    out = pd.DataFrame({"score": scores, "decile": dec + 1, "p_outperform": p_out, "p_underperform": 1 - p_out})
    return RankerResult(horizon, str(pd.Timestamp(last).date()), out.sort_values("score", ascending=False), validation)
