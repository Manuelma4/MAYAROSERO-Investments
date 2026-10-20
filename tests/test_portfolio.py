import numpy as np
import pandas as pd
import pytest

from tradebot.portfolio import build_plan, capped_weights, plan_risk

CORE = [{"symbol": f"T{i}", "name": f"Tech {i}", "sector": "Tech", "price": 100.0, "volatility_%": 30} for i in range(6)] + \
       [{"symbol": f"H{i}", "name": f"Health {i}", "sector": "Health", "price": 50.0, "volatility_%": 20} for i in range(4)]
IDEA = {"symbol": "LLY", "name": "Eli Lilly", "direction": "long", "qualified": True, "entry": 1000.0, "stop": 950.0,
        "headline": "Upgrade"}


def test_caps_respected():
    w = capped_weights(CORE, 0.70, stock_cap=0.10, sector_cap=0.25)
    assert all(v <= 0.10 + 1e-9 for v in w.values())
    tech = sum(v for s, v in w.items() if s.startswith("T"))
    health = sum(v for s, v in w.items() if s.startswith("H"))
    assert tech <= 0.25 + 1e-9 and health <= 0.25 + 1e-9
    assert sum(w.values()) == pytest.approx(0.50, abs=1e-6)  # only 2 sectors -> 2 x 25% placeable


def test_plan_balanced_sums_and_roles():
    p = build_plan(10_000, "balanced", CORE, False, [IDEA], spy_price=500.0)
    roles = p.by_role()
    assert sum(l.invested for l in p.lines) + p.cash == pytest.approx(10_000)
    assert roles["anchor"] == pytest.approx(0.10)
    sat = [l for l in p.lines if l.role == "satellite"]
    # 1% risk = 100 / 50 per share = 2 shares = 2,000 > budget 2,000? capped by stock cap 10% = 1,000
    assert sat and sat[0].invested <= 1_000 + 1e-6 and sat[0].stop == 950.0
    assert all(s <= 0.25 + 1e-9 for s in p.by_sector().values())


def test_risk_off_core_goes_to_cash_and_whole_shares():
    p = build_plan(10_000, "cautious", CORE, True, [], spy_price=500.0, fractional=False)
    assert not [l for l in p.lines if l.role == "core"]
    anchor = [l for l in p.lines if l.role == "anchor"][0]
    assert anchor.shares == 9 and p.cash == pytest.approx(10_000 - 9 * 500)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        build_plan(10_000, "yolo", CORE, False, [], 500.0)
    with pytest.raises(ValueError):
        build_plan(0, "balanced", CORE, False, [], 500.0)


def test_plan_risk_metrics():
    idx = pd.bdate_range("2025-01-01", periods=300)
    rng = np.random.default_rng(0)
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 300))), index=idx)
    closes = pd.DataFrame({"SPY": spy, **{c["symbol"]: spy * (1 + rng.normal(0, 0.001, 300)) for c in CORE}})
    p = build_plan(10_000, "balanced", CORE, False, [], spy_price=float(spy.iloc[-1]))
    r = plan_risk(p, closes, spy)
    assert 0.3 < r["beta"] < 1.2 and r["volatility_%"] > 0 and r["max_drawdown_1y_%"] <= 0


def test_diversifies_beyond_concentrated_top_picks():
    ranked = CORE[:6] + [{"symbol": f"E{i}", "name": f"Energy {i}", "sector": "Energy", "price": 80.0, "volatility_%": 25} for i in range(3)] + \
             [{"symbol": f"F{i}", "name": f"Fin {i}", "sector": "Financials", "price": 60.0, "volatility_%": 22} for i in range(3)]
    p = build_plan(10_000, "balanced", ranked, False, [], 500.0, core_n=6)  # top 6 are all Tech
    core = [l for l in p.lines if l.role == "core"]
    assert {l.sector for l in core} >= {"Tech", "Energy", "Financials"}
    assert sum(l.weight for l in core) == pytest.approx(0.70, abs=0.01)  # fully invested despite caps


def test_live_idea_already_in_core_is_not_doubled():
    core = [{"symbol": "LLY", "name": "Eli Lilly", "sector": "Health", "price": 1000.0, "volatility_%": 30}] + CORE
    p = build_plan(10_000, "balanced", core, False, [IDEA], 500.0)
    lly = [l for l in p.lines if l.symbol == "LLY"]
    assert len(lly) == 1 and lly[0].role == "core" and lly[0].weight <= 0.10 + 1e-9
