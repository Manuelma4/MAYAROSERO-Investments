"""Cross-sectional ranker: which stocks are likely to do better or worse than the others.

This is how quantitative funds frame short-term prediction: not "will NVDA go up?" (close to a coin
flip) but "will NVDA beat the typical stock over the next N days?". Quality is measured with the
information coefficient (IC): the rank correlation between the predicted score and the realized
forward returns across stocks on each date. Professional signals often have IC of 0.02-0.05;
anything consistently above 0 with a t-stat > 2 is a real, if small, edge.

- Target: each stock's percentile rank of its forward `horizon`-day return among all stocks that day.
- Model: gradient-boosted trees on backward-looking features (same as Predictor).
- Validation: walk-forward by date with a purge gap of `horizon` days.
- Probabilities: calibrated from validation (share of past cases in the same score decile that beat
  the median), so "62%" means "62 of 100 similar past cases outperformed".
"""

from __future__ import annotations

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


def _panel(frames: dict[str, pd.DataFrame], horizon: int) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    xs, fwd = [], []
    for sym, df in frames.items():
        X = build_features(df)
        X["symbol"] = sym
        r = df["close"].shift(-horizon) / df["close"] - 1
        xs.append(X)
        fwd.append(r.rename(sym))
    X = pd.concat(xs)
    X.index.name = "date"
    X = X.reset_index().set_index(["date", "symbol"]).sort_index()
    fwd_df = pd.concat(fwd, axis=1)
    fwd_df.index.name = "date"
    f = fwd_df.stack(future_stack=True)
    f.index.names = ["date", "symbol"]
    f = f.reindex(X.index)
    target = f.groupby(level="date").rank(pct=True)
    return X, target, f


def _model():
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(max_iter=150, learning_rate=0.05, max_depth=4, min_samples_leaf=200,
                                         l2_regularization=1.0, random_state=0)


def rank_universe(frames: dict[str, pd.DataFrame], horizon: int = 5, n_splits: int = 3,
                  min_names: int = 20) -> RankerResult:
    X, target, fwd = _panel(frames, horizon)
    good = X.notna().sum(axis=1) > X.shape[1] * 0.8
    X = X[good]
    target, fwd = target[good], fwd[good]
    dates = X.index.get_level_values("date").unique().sort_values()
    if len(dates) < 400:
        raise ValueError("Need at least ~400 trading days of history")
    labeled = target.notna()

    # Walk-forward validation
    edges = np.linspace(len(dates) * 0.5, len(dates) - horizon, n_splits + 1).astype(int)
    ics, spreads, calib_rows = [], [], []
    for k in range(n_splits):
        train_end = dates[edges[k] - 1 - horizon]
        test = (dates[edges[k]], dates[edges[k + 1] - 1])
        d = X.index.get_level_values("date")
        tr = (d <= train_end) & labeled
        te = (d >= test[0]) & (d <= test[1]) & labeled
        if tr.sum() < 1000 or te.sum() == 0:
            continue
        m = _model().fit(X[tr], target[tr])
        pred = pd.Series(m.predict(X[te]), index=X.index[te])
        df = pd.DataFrame({"pred": pred, "target": target[te], "fwd": fwd[te]})
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
    }

    # Fit on everything labeled, score the latest date
    model = _model().fit(X[labeled], target[labeled])
    last = X.index.get_level_values("date").max()
    latest = X.xs(last, level="date")
    scores = pd.Series(model.predict(latest), index=latest.index, name="score")
    dec = pd.qcut(scores.rank(method="first"), 10, labels=False)
    p_out = dec.map(lambda d: validation["calibration"].get(int(d), 0.5))
    out = pd.DataFrame({"score": scores, "decile": dec + 1, "p_outperform": p_out, "p_underperform": 1 - p_out})
    return RankerResult(horizon, str(pd.Timestamp(last).date()), out.sort_values("score", ascending=False), validation)
