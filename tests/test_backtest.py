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
