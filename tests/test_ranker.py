import numpy as np
import pandas as pd

from conftest import make_ohlcv
from tradebot.ml.ranker import rank_universe


def _frames(n_stocks=40, n=700, reversal=0.0, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n, tz="UTC")
    out = {}
    for i in range(n_stocks):
        eps = rng.normal(0, 0.015, n)
        r = eps.copy()
        r[1:] -= reversal * eps[:-1]        # short-term reversal: yesterday's move partly undone today
        close = 50 * np.exp(np.cumsum(r))
        open_ = np.concatenate([[close[0]], close[:-1]])
        out[f"S{i:02d}"] = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.004,
                                         "low": np.minimum(open_, close) * 0.996, "close": close,
                                         "volume": rng.lognormal(10, 0.3, n)}, index=idx)
    return out


def test_ranker_finds_planted_cross_sectional_signal():
    res = rank_universe(_frames(reversal=0.5), horizon=1, point_in_time=False, train_every=5)
    v = res.validation
    assert v["ic_mean"] > 0.1 and v["has_edge"] and v["train_every_days"] == 5
    assert len(res.scores) == 40 and set(res.scores["decile"]) == set(range(1, 11))


def test_ranker_has_no_edge_on_random_walks():
    # If labels leaked into features or training overlapped the test period, IC would be > 0 here.
    for seed in (1, 2):
        v = rank_universe(_frames(seed=seed), horizon=5, point_in_time=False).validation
        assert not v["has_edge"] and abs(v["ic_mean"]) < 0.03


def test_ranker_latest_scores_ignore_future_bars():
    # Scoring as of a past date with the data cut there must not need (or see) anything later.
    frames = {f"S{i}": make_ohlcv(700, i) for i in range(25)}
    t = frames["S0"].index[600]
    res = rank_universe({s: f.loc[:t] for s, f in frames.items()}, horizon=5, point_in_time=False)
    assert res.as_of == str(t.date())


def test_ranker_point_in_time_drops_non_members():
    frames = _frames(n_stocks=30, seed=3)
    last = frames["S00"].index[-1]
    spells = {"S00": [(None, (last - pd.Timedelta(days=30)).date().isoformat())],     # left the index
              "S01": [(last.date().isoformat(), None)]}                               # joined on the last day
    res = rank_universe(frames, horizon=5, spells=spells)
    assert "S00" not in res.scores.index and "S01" in res.scores.index
    assert res.validation["point_in_time"]
