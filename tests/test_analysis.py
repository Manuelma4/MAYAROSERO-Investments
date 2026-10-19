import pandas as pd

from tradebot.analysis import candlesticks as cs
from tradebot.analysis import dow, elliott
from tradebot.analysis.swings import pivots, zigzag


def frame(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1D", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=1.0)


def test_bullish_engulfing():
    df = frame([(10, 10.2, 9.4, 9.5), (9.4, 10.5, 9.3, 10.4)])
    assert cs.bullish_engulfing(df).tolist() == [False, True]
    assert not cs.bearish_engulfing(df).any()


def test_hammer_and_star():
    df = frame([(10, 10.4, 8.0, 10.3), (10, 12.0, 9.6, 9.7)])
    assert cs.hammer(df).tolist() == [True, False]
    assert cs.shooting_star(df).tolist() == [False, True]


def test_pivots_confirmed_later(ohlcv):
    p = pivots(ohlcv, 5, 5)
    assert (p["confirmed_at"] > p["time"]).all()


def test_dow_trend_no_lookahead(ohlcv):
    full = dow.trend(ohlcv)
    partial = dow.trend(ohlcv.iloc[:800])
    assert (full.iloc[:800] == partial).all()


def test_zigzag_alternates(ohlcv):
    zz = zigzag(ohlcv, 0.05)
    assert len(zz) > 5
    assert (zz["kind"] != zz["kind"].shift()).iloc[1:].all()


def test_elliott_rules():
    good = elliott.check_impulse([100, 120, 110, 150, 135, 160])
    assert good["valid"] and good["direction"] == "bull"
    overlap = elliott.check_impulse([100, 120, 110, 150, 115, 160])
    assert not overlap["rules"]["wave4_no_overlap"]
    short3 = elliott.check_impulse([100, 130, 120, 130, 125, 160])
    assert not short3["rules"]["wave3_not_shortest"]
    bear = elliott.check_impulse([160, 135, 150, 110, 120, 100])
    assert bear["valid"] and bear["direction"] == "bear"
