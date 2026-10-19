import numpy as np
import pandas as pd
import pytest

from tradebot.picker import PickerConfig, rank, run_picker, _closes


def universe(n_stocks=30, n_days=1500, seed=0, winners=()):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2017-01-02", periods=n_days, tz="UTC")
    frames = {}
    for i in range(n_stocks):
        drift = 0.0012 if i in winners else 0.0002
        close = 50 * np.exp(np.cumsum(rng.normal(drift, 0.015, n_days)))
        frames[f"S{i:02d}"] = pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                                            "volume": 1e6}, index=idx)
    bench_close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n_days)))
    bench = pd.DataFrame({"open": bench_close, "high": bench_close, "low": bench_close,
                          "close": bench_close, "volume": 1e6}, index=idx)
    return frames, bench


def test_picks_persistent_winners_and_beats_benchmark():
    winners = {3, 7, 11, 19}
    frames, bench = universe(winners=winners)
    res = run_picker(frames, bench, PickerConfig(preset="momentum", top_n=5))
    names = {f"S{i:02d}" for i in winners}
    slots = [s for h in res.holdings for s in h["symbols"]]
    hit_rate = sum(s in names for s in slots) / len(slots)
    assert hit_rate > 0.25  # ~2x random picking (4/30 = 13%)
    assert res.stats["excess_cagr_%"] > 0
    assert res.stats["rebalances"] > 30


def test_no_lookahead_in_ranking():
    frames, bench = universe(seed=1)
    cfg = PickerConfig()
    px = _closes(frames)
    t = px.index[800]
    full = rank(px, bench["close"], t, cfg)
    truncated = rank(px.loc[:t], bench["close"].loc[:t], t, cfg)
    pd.testing.assert_frame_equal(full, truncated)


def test_costs_reduce_returns():
    frames, bench = universe(seed=2)
    cheap = run_picker(frames, bench, PickerConfig(cost_bps=0))
    pricey = run_picker(frames, bench, PickerConfig(cost_bps=100))
    assert pricey.equity.iloc[-1] < cheap.equity.iloc[-1]


def test_regime_filter_can_go_to_cash():
    frames, bench = universe(seed=3)
    crash = bench.copy()
    crash.loc[crash.index[1000]:, "close"] *= np.linspace(1, 0.5, len(crash) - 1000)
    res = run_picker(frames, crash, PickerConfig(regime_filter=True))
    assert any(h["risk_off"] for h in res.holdings)
    assert all(not h["symbols"] for h in res.holdings if h["risk_off"])


def test_equity_without_rebalancing_drift_matches_buy_and_hold():
    # One stock, one rebalance: portfolio must track the stock exactly (no costs).
    frames, bench = universe(n_stocks=1, seed=4)
    res = run_picker(frames, bench, PickerConfig(top_n=1, trend_filter=False, cost_bps=0, rebalance="10YE"))
    px = frames["S00"]["close"].loc[res.equity.index]
    assert res.equity.iloc[-1] / res.equity.iloc[0] == pytest.approx(px.iloc[-1] / px.iloc[0], rel=1e-9)
