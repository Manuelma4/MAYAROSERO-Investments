"""Predict the next move (BUY / SELL / HOLD) from historical patterns.

Honest by design:
- Walk-forward validation only: the model is always trained on the past and
  tested on the following, never-seen period, with a purge gap of `horizon`
  bars so labels cannot leak across the split.
- Every report compares the model with naive baselines. If it does not beat
  them out of sample, the prediction is flagged as having NO EDGE, and you
  should not trade it.
- Markets are noisy: accuracy of 52-56% with good risk management is already
  considered useful by professional quant funds. Anything near 90% is a bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .features import build_features, make_labels

ACTIONS = {1: "BUY", -1: "SELL", 0: "HOLD"}


@dataclass
class Prediction:
    symbol: str
    time: pd.Timestamp
    action: str
    probabilities: dict
    confidence: float
    validation: dict
    has_edge: bool

    def __str__(self) -> str:
        p = self.probabilities
        v = self.validation
        edge = "YES" if self.has_edge else "NO (do not trade this signal)"
        return (
            f"{self.symbol} @ {self.time:%Y-%m-%d %H:%M} -> {self.action} "
            f"(confidence {self.confidence:.0%})\n"
            f"  P(BUY) {p.get('BUY', 0):.0%}  P(HOLD) {p.get('HOLD', 0):.0%}  P(SELL) {p.get('SELL', 0):.0%}\n"
            f"  walk-forward: accuracy {v['accuracy']:.1%} vs baseline {v['baseline_accuracy']:.1%}, "
            f"precision on confident calls {v['confident_precision']:.1%} ({v['confident_calls']} calls)\n"
            f"  strategy return {v['strategy_return_%']:+.1f}% vs buy & hold {v['buy_hold_return_%']:+.1f}% "
            f"| statistical edge: {edge}"
        )


@dataclass
class Predictor:
    horizon: int = 5                 # bars ahead to predict
    threshold_atr: float = 0.5       # size of move that counts as BUY / SELL
    min_confidence: float = 0.45     # probability needed to act instead of HOLD
    n_splits: int = 5
    params: dict = field(default_factory=lambda: {
        "max_iter": 200, "learning_rate": 0.05, "max_depth": 4,
        "min_samples_leaf": 40, "l2_regularization": 1.0})
    model: object = None
    feature_names: list = field(default_factory=list)

    def _new_model(self):
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(random_state=0, **self.params)

    def dataset(self, frames: dict[str, pd.DataFrame]):
        """Stack features, labels and forward returns for one or many symbols."""
        xs, ys, fs = [], [], []
        for df in frames.values():
            X, y = build_features(df), make_labels(df, self.horizon, self.threshold_atr)
            fwd = df["close"].shift(-self.horizon) / df["close"] - 1
            ok = y.notna() & X.notna().sum(axis=1).gt(len(X.columns) * 0.8)
            xs.append(X[ok]), ys.append(y[ok]), fs.append(fwd[ok])
        order = np.argsort(np.concatenate([x.index.values for x in xs]), kind="stable")
        X = pd.concat(xs).iloc[order]
        y = pd.concat(ys).iloc[order].astype(int)
        fwd = pd.concat(fs).iloc[order]
        return X, y, fwd

    def _decide(self, proba: np.ndarray, classes: np.ndarray) -> np.ndarray:
        act = classes[proba.argmax(axis=1)].copy()
        act[proba.max(axis=1) < self.min_confidence] = 0
        return act

    def walk_forward(self, frames: dict[str, pd.DataFrame]) -> dict:
        X, y, fwd = self.dataset(frames)
        times = X.index.unique().sort_values()
        if len(times) < 300:
            raise ValueError("Need at least ~300 bars of history for walk-forward validation")
        edges = np.linspace(len(times) * 0.4, len(times), self.n_splits + 1).astype(int)
        preds, truth, acts, rets, tidx = [], [], [], [], []
        for k in range(self.n_splits):
            train_end = times[edges[k] - 1 - self.horizon]       # purge gap: no label overlap
            test_start, test_end = times[edges[k]], times[edges[k + 1] - 1]
            tr = X.index <= train_end
            te = (X.index >= test_start) & (X.index <= test_end)
            if te.sum() == 0 or y[tr].nunique() < 2:
                continue
            m = self._new_model().fit(X[tr], y[tr])
            proba = m.predict_proba(X[te])
            preds.append(m.classes_[proba.argmax(axis=1)])
            acts.append(self._decide(proba, m.classes_))
            truth.append(y[te].values)
            rets.append(fwd[te].values)
            tidx.append(X.index[te])
        p, t, act = np.concatenate(preds), np.concatenate(truth), np.concatenate(acts)
        r = np.concatenate(rets)
        when = np.concatenate([i.values for i in tidx])

        # P&L proxy: equal-weight across symbols per bar, then non-overlapping
        # holding periods (every `horizon`-th bar) so returns are not double counted.
        pnl = pd.DataFrame({"t": when, "s": act * r, "b": r}).groupby("t").mean()
        pnl = pnl.iloc[:: self.horizon]
        conf = act != 0
        majority = float(pd.Series(t).value_counts(normalize=True).iloc[0])
        res = {
            "samples": int(len(t)),
            "accuracy": float((p == t).mean()),
            "baseline_accuracy": majority,
            "confident_calls": int(conf.sum()),
            "confident_precision": float((act[conf] == t[conf]).mean()) if conf.any() else 0.0,
            "strategy_return_%": float((np.prod(1 + pnl["s"]) - 1) * 100),
            "buy_hold_return_%": float((np.prod(1 + pnl["b"]) - 1) * 100),
        }
        directional_base = max((t == 1).mean(), (t == -1).mean())
        res["has_edge"] = bool(res["accuracy"] > majority + 0.01 and res["confident_calls"] >= 20
                               and res["confident_precision"] > directional_base + 0.03)
        return res

    def fit(self, frames: dict[str, pd.DataFrame]) -> "Predictor":
        X, y, _ = self.dataset(frames)
        self.feature_names = list(X.columns)
        self.model = self._new_model().fit(X, y)
        return self

    def predict_latest(self, symbol: str, df: pd.DataFrame, validation: dict | None = None) -> Prediction:
        if self.model is None:
            raise RuntimeError("call fit() first")
        X = build_features(df)[self.feature_names].iloc[[-1]]
        proba = self.model.predict_proba(X)[0]
        classes = self.model.classes_
        action = int(self._decide(proba[None, :], classes)[0])
        probs = {ACTIONS[int(c)]: float(p) for c, p in zip(classes, proba)}
        validation = validation or {}
        return Prediction(symbol, df.index[-1], ACTIONS[action], probs, float(proba.max()),
                          validation, bool(validation.get("has_edge", False)))

    def save(self, path: str) -> None:
        import joblib

        joblib.dump(self, path)

    @staticmethod
    def load(path: str) -> "Predictor":
        import joblib

        return joblib.load(path)
