import numpy as np
import pandas as pd
import pytest

from conftest import make_ohlcv
from tradebot.forecast import ewma_vol, monte_carlo, obv, volume_profile, vwap_bands


def test_monte_carlo_shape_and_probabilities():
    df = make_ohlcv(900, seed=1)
    mc = monte_carlo(df["close"], horizon=5, n_paths=3000)
    assert len(mc["fan"]["p50"]) == 6 and mc["fan"]["p5"][0] == pytest.approx(mc["last_price"])
    assert mc["p_up"] + mc["p_down"] == pytest.approx(1.0, abs=0.01)
    lo, hi = mc["range_5_95"]
    assert lo < mc["last_price"] < hi
    assert all(mc["fan"]["p5"][i] <= mc["fan"]["p50"][i] <= mc["fan"]["p95"][i] for i in range(6))


def test_monte_carlo_range_scales_with_volatility():
    calm = make_ohlcv(900, seed=2, vol=0.005)
    wild = make_ohlcv(900, seed=2, vol=0.03)
    a = monte_carlo(calm["close"], 21, 3000)
    b = monte_carlo(wild["close"], 21, 3000)
    width = lambda m: (m["range_5_95"][1] - m["range_5_95"][0]) / m["last_price"]
    assert width(b) > 3 * width(a)


def test_monte_carlo_no_lookahead():
    df = make_ohlcv(900, seed=3)
    a = monte_carlo(df["close"].iloc[:700], 5, 2000)
    b = monte_carlo(df["close"].iloc[:700].copy(), 5, 2000)
    assert a == b  # deterministic given the same past


def test_ewma_vol_reacts_to_shock():
    r = np.r_[np.full(100, 0.001), 0.1, np.full(20, 0.001)]
    v = ewma_vol(r)
    assert v[101] > 5 * v[99]


def test_volume_profile_poc_and_value_area():
    idx = pd.date_range("2026-01-01", periods=100, freq="D", tz="UTC")
    price = np.r_[np.full(80, 100.0), np.linspace(100, 120, 20)]
    df = pd.DataFrame({"open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "volume": 1000.0}, index=idx)
    vp = volume_profile(df, bins=20)
    assert 99 <= vp["poc"] <= 101.5
    assert vp["value_area"][0] <= vp["poc"] <= vp["value_area"][1]
    assert sum(b["share"] for b in vp["bins"]) == pytest.approx(1.0)


def test_vwap_resets_each_day_and_obv():
    idx = pd.date_range("2026-01-05 14:30", periods=26, freq="15min", tz="UTC").append(
        pd.date_range("2026-01-06 14:30", periods=26, freq="15min", tz="UTC"))
    p = np.r_[np.linspace(100, 110, 26), np.linspace(50, 55, 26)]
    df = pd.DataFrame({"open": p, "high": p + 0.1, "low": p - 0.1, "close": p, "volume": 100.0}, index=idx)
    vb = vwap_bands(df)
    assert vb["vwap"].iloc[26] == pytest.approx(50, abs=0.2)  # new day starts fresh
    assert (vb["upper_1"] >= vb["vwap"] - 1e-9).all()
    assert obv(df).iloc[25] > 0
