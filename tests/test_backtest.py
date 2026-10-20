import numpy as np
import pandas as pd
import pytest

from tradebot.backtest import BacktestConfig, run_backtest
from tradebot.strategies import REGISTRY, get_strategy
from tradebot.strategies.base import Strategy


@pytest.mark.parametrize("name", list(REGISTRY))
def test_strategies_run(ohlcv, name):
    res = run_backtest(ohlcv, get_strategy(name))
    assert len(res.equity) == len(ohlcv)
    assert res.stats["final_equity"] > 0
    for t in res.trades:
        assert t.exit_time >= t.entry_time


@pytest.mark.parametrize("name", list(REGISTRY))
def test_signals_have_no_lookahead(ohlcv, name):
    s = get_strategy(name)
    full = s.prepare(ohlcv)
    cut = s.prepare(ohlcv.iloc[:1000])
    cols = ["entry_long", "entry_short"]
    assert (full[cols].iloc[:1000] == cut[cols]).all().all()


class OneShot(Strategy):
    name = "oneshot"

    def signals(self, df):
        df["entry_long"] = False
        df.iloc[1, df.columns.get_loc("entry_long")] = True
        df["stop"] = np.where(df["entry_long"], 90.0, np.nan)
        df["target"] = np.where(df["entry_long"], 120.0, np.nan)
        return df


def bars(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1D", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=1.0)


def test_fill_next_open_and_target():
    df = bars([(100, 101, 99, 100), (100, 101, 99, 100), (100, 105, 98, 104), (104, 125, 103, 121)])
    res = run_backtest(df, OneShot(), BacktestConfig(fee=0, slippage=0, risk_per_trade=0.01))
    t = res.trades[0]
    assert t.entry_time == df.index[2] and t.entry_price == 100
    assert t.exit_reason == "target" and t.exit_price == 120
    assert t.qty == pytest.approx(10)  # 1% of 10k = 100 risk / 10 per unit
    assert t.r_multiple == pytest.approx(2.0)


def test_stop_first_when_both_hit_and_gap():
    df = bars([(100, 101, 99, 100), (100, 101, 99, 100), (100, 125, 85, 100)])
    t = run_backtest(df, OneShot(), BacktestConfig(fee=0, slippage=0)).trades[0]
    assert t.exit_reason == "stop" and t.exit_price == 90

    gap = bars([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100), (80, 82, 79, 81)])
    t = run_backtest(gap, OneShot(), BacktestConfig(fee=0, slippage=0)).trades[0]
    assert t.exit_reason == "stop" and t.exit_price == 80


# ---- portfolio strategies (stock picker presets and ETF rotation): truncation tests -------------------------

def _ohlc_universe(names, n_days=1400, seed=0, start="2016-01-04"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n_days, tz="UTC")
    out = {}
    for i, s in enumerate(names):
        close = 50 * np.exp(np.cumsum(rng.normal(0.0001 * (i % 5), 0.012 + 0.002 * (i % 4), n_days)))
        open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, n_days))
        out[s] = pd.DataFrame({"open": open_, "high": np.maximum(open_, close), "low": np.minimum(open_, close),
                               "close": close, "volume": 1e6}, index=idx)
    return out


PORTFOLIO_STRATEGIES = {
    "core_momentum": {"preset": "core_momentum"},
    "momentum_vol_scaled": {"preset": "momentum", "vol_scale": True},
    "momentum_buffer_sector_cap": {"preset": "momentum", "top_n": 6, "buffer_n": 12, "sector_max": 2,
                                   "rebalance": "QE"},
}


@pytest.mark.parametrize("name", list(PORTFOLIO_STRATEGIES))
def test_picker_strategies_have_no_lookahead(name):
    from tradebot.picker import PickerConfig, run_picker

    frames = _ohlc_universe([f"S{i:02d}" for i in range(24)], seed=11)
    bench = _ohlc_universe(["B"], seed=12)["B"]
    sectors = {s: f"sec{i % 4}" for i, s in enumerate(frames)}
    cfg = PickerConfig(**PORTFOLIO_STRATEGIES[name], sectors=sectors, point_in_time=False)
    t = bench.index[1000]
    full = run_picker(frames, bench, cfg)
    cut = run_picker({s: f.loc[:t] for s, f in frames.items()}, bench.loc[:t], cfg)
    pd.testing.assert_series_equal(full.equity.loc[:t], cut.equity, check_freq=False)
    assert [h["symbols"] for h in full.holdings[:len(cut.holdings) - 1]] == [h["symbols"] for h in cut.holdings[:-1]]


@pytest.mark.parametrize("cfg", [{}, {"trend_filter": False}, {"vol_target": 0.12}, {"core_spy": 0.5}])
def test_rotation_has_no_lookahead(cfg):
    from tradebot.rotation import RotationConfig, run_rotation

    names = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "SPY", "SHY"]
    frames = _ohlc_universe(names, seed=13)
    irx = pd.Series(2.0, index=frames["SPY"].index)
    t = frames["SPY"].index[1000]
    full = run_rotation(frames, RotationConfig(**cfg), irx=irx)
    cut = run_rotation({s: f.loc[:t] for s, f in frames.items()}, RotationConfig(**cfg), irx=irx.loc[:t])
    pd.testing.assert_series_equal(full.equity.loc[:t], cut.equity, check_freq=False)
