import numpy as np
import pandas as pd
import pytest

from tradebot.picker import PickerConfig, _closes, membership_mask, rank, run_picker


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
    # One stock, one rebalance: decided at the first close, bought at the next open, then the
    # portfolio must track the stock exactly (no costs).
    frames, bench = universe(n_stocks=1, seed=4)
    frames["S00"]["open"] = frames["S00"]["close"].shift(1).fillna(frames["S00"]["close"]) * 1.003
    res = run_picker(frames, bench, PickerConfig(top_n=1, trend_filter=False, cost_bps=0, rebalance="10YE"))
    px = frames["S00"]["close"].loc[res.equity.index]
    fill = frames["S00"]["open"].loc[res.equity.index[1]]
    assert res.equity.iloc[-1] / res.equity.iloc[0] == pytest.approx(px.iloc[-1] / fill, rel=1e-9)


def test_point_in_time_membership_blocks_future_joiners():
    # S03 is a huge winner but only "joins the index" on day 1200: before that it must never be
    # picked nor counted in the equal-weight yardstick.
    frames, bench = universe(seed=5, winners={3})
    join = frames["S03"].index[1200]
    spells = {"S03": [(join.date().isoformat(), None)]}
    members = membership_mask(_closes(frames).index, list(frames), spells)
    cfg = PickerConfig(preset="momentum", top_n=5)
    free = run_picker(frames, bench, cfg)
    pit = run_picker(frames, bench, cfg, members=members)

    def before(res):
        return [h for h in res.holdings if pd.Timestamp(h["date"], tz="UTC") < join]

    assert before(pit) and all("S03" not in h["symbols"] for h in before(pit))
    assert any("S03" in h["symbols"] for h in before(free))
    assert any("S03" in h["symbols"] for h in pit.holdings)          # allowed once it is a member
    ew = run_picker(frames, bench, PickerConfig(top_n=30, trend_filter=False), members=members)
    assert all("S03" not in h["symbols"] for h in before(ew))


def test_membership_mask_spells_and_unknown_symbols():
    idx = pd.bdate_range("2015-01-01", "2024-12-31", tz="UTC")
    m = membership_mask(idx, ["A", "B", "C"], {"A": [("2020-06-22", None)],
                                                "B": [(None, "2017-03-20"), ("2022-12-19", None)]})
    assert not m.loc[:"2020-06-19", "A"].any() and m.loc["2020-06-22":, "A"].all()
    assert m.loc[:"2017-03-17", "B"].all() and not m.loc["2017-03-20":"2022-12-16", "B"].any()
    assert m.loc["2022-12-19":, "B"].all() and m["C"].all()       # no spells: member throughout


def test_bundled_join_dates_cover_the_obvious_late_joiners():
    from tradebot.universe import membership_spells, sp500_symbols

    spells = membership_spells()
    assert set(spells) <= set(sp500_symbols())
    for sym, year in {"PLTR": 2024, "SMCI": 2024, "DELL": 2024, "TSLA": 2020, "APP": 2025, "CVNA": 2025,
                      "VST": 2024, "AXON": 2023, "COIN": 2025, "HOOD": 2025, "UBER": 2023, "CEG": 2022}.items():
        assert int(spells[sym][-1][0][:4]) == year, sym
    for sym, rows in spells.items():
        for added, removed in rows:
            assert added or removed, sym
            if added and removed:
                assert added < removed, sym


def test_default_config_applies_bundled_membership():
    # A real ticker that joined late (PLTR, 2024-09-23) is filtered out by default before joining.
    frames, bench = universe(n_stocks=12, seed=8, winners={0})
    frames = {("PLTR" if k == "S00" else k): v for k, v in frames.items()}
    res = run_picker(frames, bench, PickerConfig(preset="momentum", top_n=3))
    assert res.stats["point_in_time"] and all("PLTR" not in h["symbols"] for h in res.holdings)
    naive = run_picker(frames, bench, PickerConfig(preset="momentum", top_n=3, point_in_time=False))
    assert any("PLTR" in h["symbols"] for h in naive.holdings)


def test_no_lookahead_in_ranking_with_membership():
    frames, bench = universe(seed=6)
    px = _closes(frames)
    members = membership_mask(px.index, list(frames), {"S01": [(px.index[700].date().isoformat(), None)],
                                                       "S02": [(None, px.index[650].date().isoformat())]})
    t = px.index[800]
    full = rank(px, bench["close"], t, PickerConfig(), members)
    truncated = rank(px.loc[:t], bench["close"].loc[:t], t, PickerConfig(), members.loc[:t])
    pd.testing.assert_frame_equal(full, truncated)
    assert "S02" not in full.index


def test_backtest_is_unchanged_by_future_data():
    # Truncation test for the whole backtest: equity up to t must not depend on bars after t.
    frames, bench = universe(seed=9)
    t = bench.index[1100]
    full = run_picker(frames, bench, PickerConfig())
    cut = run_picker({s: f.loc[:t] for s, f in frames.items()}, bench.loc[:t], PickerConfig())
    pd.testing.assert_series_equal(full.equity.loc[:t], cut.equity, check_freq=False)


def test_trades_fill_at_next_open():
    # Decided at the close of day 261 at 100; the stock opens at 110 the next day and stays there,
    # so a next-open fill buys at 110 and gains nothing.
    frames, bench = universe(n_stocks=1, n_days=300, seed=7)
    df = frames["S00"]
    df[["open", "high", "low", "close"]] = 100.0
    df.iloc[262:, :4] = 110.0
    start = df.index[261].date().isoformat()
    res = run_picker({"S00": df}, bench, PickerConfig(top_n=1, trend_filter=False, cost_bps=0, rebalance="10YE"),
                     start=start)
    assert res.holdings[0]["symbols"] == ["S00"]
    assert res.equity.iloc[-1] == pytest.approx(100.0)
