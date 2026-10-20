import numpy as np
import pandas as pd
import pytest

from tradebot.rotation import CASH_COL, RotationConfig, cash_returns, rotation_target, run_rotation


def etfs(drifts: dict[str, float], n=800, seed=0, vol=0.01):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2001-01-02", periods=n, tz="UTC")
    out = {}
    for s, d in drifts.items():
        close = 100 * np.exp(np.cumsum(rng.normal(d, vol, n)))
        out[s] = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0}, index=idx)
    return out


def closes(frames):
    return pd.DataFrame({s: f["close"] for s, f in frames.items()})


def test_holds_the_strongest_sectors():
    fr = etfs({"XLK": 0.002, "XLE": 0.0015, "XLF": 0.001, "XLU": -0.001, "XLP": -0.0015, "SPY": 0.0003})
    px = closes(fr)
    w, info = rotation_target(px, px.index[-1], RotationConfig(top_k=3))
    assert {s for s in w.index if w[s] > 0} == {"XLK", "XLE", "XLF"}
    assert w.sum() == pytest.approx(1.0) and w[CASH_COL] == 0
    assert set(list(info["momentum"])[:3]) == {"XLK", "XLE", "XLF"}


def test_trend_filter_sends_a_falling_slot_to_cash():
    # Only two sectors rise: the third-best slot is below its 200-day average and goes to cash.
    fr = etfs({"XLK": 0.002, "XLE": 0.0015, "XLF": -0.002, "XLU": -0.003, "SPY": 0.0003}, vol=0.002)
    px = closes(fr)
    w, _ = rotation_target(px, px.index[-1], RotationConfig(top_k=3))
    assert w[CASH_COL] == pytest.approx(1 / 3) and w["XLF"] == 0
    w2, _ = rotation_target(px, px.index[-1], RotationConfig(top_k=3, trend_filter=False))
    assert w2[CASH_COL] == 0 and w2["XLF"] == pytest.approx(1 / 3)


def test_vol_target_and_core_spy_never_leverage():
    fr = etfs({"XLK": 0.002, "XLE": 0.0015, "XLF": 0.001, "SPY": 0.0003}, vol=0.03)   # ~48% vol each
    px = closes(fr)
    w, info = rotation_target(px, px.index[-1], RotationConfig(vol_target=0.15))
    assert 0 < info["scale"] < 1 and w.sum() == pytest.approx(1.0) and w[CASH_COL] > 0.4
    w, _ = rotation_target(px, px.index[-1], RotationConfig(core_spy=0.5))
    assert w["SPY"] == pytest.approx(0.5) and w.sum() == pytest.approx(1.0)


def test_only_existing_funds_are_used_and_young_funds_wait_a_year():
    fr = etfs({"XLK": 0.001, "XLE": 0.0005, "XLF": 0.0002, "SPY": 0.0003})
    late = etfs({"XLC": 0.01}, n=200, seed=3)["XLC"]                  # 200 days of history only
    late.index = fr["XLK"].index[-200:]
    fr["XLC"] = late
    px = closes(fr)
    w, info = rotation_target(px, px.index[-1], RotationConfig())
    assert "XLC" not in info["momentum"] and w.get("XLC", 0) == 0


def test_cash_uses_tbills_before_shy_exists():
    idx = pd.bdate_range("2002-01-01", periods=300, tz="UTC")
    irx = pd.Series(2.52, index=idx)                                   # 2.52%/yr
    shy = pd.Series(np.linspace(100, 101, 100), index=idx[200:])
    r = cash_returns(idx, shy, irx)
    assert r.iloc[50] == pytest.approx(0.0252 / 252)
    assert r.iloc[250] == pytest.approx(shy.pct_change().iloc[50])
    assert cash_returns(idx, None, None).sum() == 0


def test_run_rotation_costs_and_fills():
    fr = etfs({"XLK": 0.001, "XLE": 0.0008, "XLF": 0.0002, "XLU": 0.0, "SPY": 0.0003}, n=900, seed=5)
    cheap = run_rotation(fr, RotationConfig(cost_bps=0))
    pricey = run_rotation(fr, RotationConfig(cost_bps=100))
    assert pricey.equity.iloc[-1] < cheap.equity.iloc[-1]
    assert cheap.stats["rebalances"] > 20 and cheap.current["weights"]
    with pytest.raises(ValueError):
        run_rotation({k: v for k, v in fr.items() if k != "SPY"})
