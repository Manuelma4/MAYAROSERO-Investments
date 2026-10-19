import numpy as np

from conftest import make_ohlcv
from tradebot.ml import Predictor, build_features, make_labels


def test_features_are_backward_looking():
    df = make_ohlcv(800)
    full = build_features(df)
    cut = build_features(df.iloc[:500])
    a, b = full.iloc[:500], cut
    assert np.allclose(a.fillna(-9).values, b.fillna(-9).values)


def test_labels_last_horizon_is_nan():
    y = make_labels(make_ohlcv(300), horizon=5)
    assert y.iloc[-5:].isna().all() and y.iloc[:-5].notna().all()


def test_no_edge_on_random_walk():
    # If features or validation leaked future data, the model would "find" an edge here.
    for seed in (0, 1):
        res = Predictor().walk_forward({"RW": make_ohlcv(1500, seed, drift=0, cycle=0)})
        assert not res["has_edge"]
        assert res["accuracy"] < res["baseline_accuracy"] + 0.05


def test_finds_real_pattern_and_predicts():
    df = make_ohlcv(2000, cycle=0.01)  # contains a genuine, learnable cycle
    p = Predictor()
    res = p.walk_forward({"CYC": df})
    assert res["has_edge"]
    pred = p.fit({"CYC": df}).predict_latest("CYC", df, res)
    assert pred.action in {"BUY", "SELL", "HOLD"}
    assert abs(sum(pred.probabilities.values()) - 1) < 1e-6


def test_multi_symbol_training():
    frames = {"A": make_ohlcv(900, 1), "B": make_ohlcv(900, 2)}
    res = Predictor(n_splits=3).walk_forward(frames)
    assert res["samples"] > 500
