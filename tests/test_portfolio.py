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


# ---------------------------------------------------------------- risk-aware construction

from tradebot.portfolio import (CORE_FLOOR, RISK_LEVELS, TARGET_VOL, equal_risk_weights, fit_risk_budget,  # noqa: E402
                                past_returns, plan_weights, risk_shares)


def market(n=600, seed=1, idio=None, beta=None, mvol=0.010):
    """SPY + 10 stocks driven by one market factor. idio/beta: per-stock daily idiosyncratic vol and beta."""
    idx = pd.bdate_range("2021-01-04", periods=n)
    rng = np.random.default_rng(seed)
    m = rng.normal(0.0004, mvol, n)
    idio = idio or [0.012] * 10
    beta = beta or [1.0] * 10
    cols = {"SPY": 400 * np.cumprod(1 + m)}
    for i, (e, b) in enumerate(zip(idio, beta)):
        cols[f"S{i}"] = 50 * np.cumprod(1 + b * m + rng.normal(0, e, n))
    closes = pd.DataFrame(cols, index=idx)
    sectors = ["Tech", "Tech", "Tech", "Health", "Health", "Energy", "Energy", "Fin", "Fin", "Util"]
    cands = [{"symbol": f"S{i}", "name": f"S{i}", "sector": sectors[i], "price": float(closes[f"S{i}"].iloc[-1]),
              "volatility_%": 30.0} for i in range(10)]
    return closes, cands


def test_equal_risk_weights_equalize_contributions():
    rng = np.random.default_rng(0)
    a = rng.normal(size=(500, 5)) @ np.diag([0.5, 1, 2, 3, 4]) + rng.normal(size=(500, 1))
    cov = np.cov(a.T)
    w = equal_risk_weights(cov)
    assert w.sum() == pytest.approx(1.0) and (w > 0).all()
    assert risk_shares(cov, w) == pytest.approx(np.full(5, 0.2), abs=1e-6)
    # uncorrelated assets: equal risk = inverse volatility
    w2 = equal_risk_weights(np.diag([0.01, 0.04, 0.09]))
    assert w2 == pytest.approx(np.array([1, 1 / 2, 1 / 3]) / (1 + 1 / 2 + 1 / 3), rel=1e-5)


def test_risk_aware_plan_sums_and_respects_caps():
    closes, cands = market()
    for risk in RISK_LEVELS:
        p = build_plan(10_000, risk, cands, False, [IDEA], spy_price=float(closes["SPY"].iloc[-1]), closes=closes)
        assert sum(l.invested for l in p.lines) + p.cash == pytest.approx(10_000)
        assert p.cash >= -1e-6
        assert all(l.weight <= 0.10 + 1e-9 for l in p.lines if l.role in ("core", "satellite"))
        assert all(v <= 0.25 + 1e-9 for v in p.by_sector().values())
        assert sum(p.mix.values()) <= 1 + 1e-9 and p.mix["core"] <= RISK_LEVELS[risk][0] + 1e-9
        assert p.weighting["method"] == "equal_risk" and len(p.weighting["summary"]) == 2
        assert len({l.symbol for l in p.lines}) == len(p.lines)          # never doubles a holding


def test_very_volatile_holding_gets_a_smaller_weight():
    closes, cands = market(idio=[0.012] * 9 + [0.05])
    _, free, _, _ = plan_weights("balanced", cands, False, closes, risk_budget=False, stock_cap=1, sector_cap=1)
    assert free["S9"] < 0.7 * min(free[f"S{i}"] for i in range(9))
    _, w, _, _ = plan_weights("balanced", cands, False, closes, risk_budget=False)   # with the money caps
    assert w["S9"] < min(w[f"S{i}"] for i in range(9))
    # its share of the picks' risk is about 1 in 10, not dominant
    syms = list(w)
    cov = past_returns(closes, syms)[syms].cov().to_numpy()
    assert risk_shares(cov, np.array([w[s] for s in syms]))[syms.index("S9")] < 0.2


def test_risk_budget_hits_the_target_on_jumpy_picks():
    closes, cands = market(idio=[0.03] * 10, beta=[1.6] * 10)        # picks about 2x as jumpy as SPY
    rets = past_returns(closes, [c["symbol"] for c in cands])
    for risk in RISK_LEVELS:
        _, w, anchor, info = plan_weights(risk, cands, False, closes)
        assert info["x_spy_start"] > TARGET_VOL[risk]
        assert info["x_spy"] == pytest.approx(TARGET_VOL[risk], rel=1e-3)
        assert sum(w.values()) >= CORE_FLOOR * RISK_LEVELS[risk][0] * min(1.0, info["x_spy"] / info["x_spy_start"]) - 1e-9
        # recomputed from scratch on the past year: plan vol / SPY vol <= the level's target
        wt = pd.Series({**w, "SPY": anchor})
        port = rets[wt.index].mul(wt).sum(axis=1)
        assert port.std() / rets["SPY"].std() <= TARGET_VOL[risk] + 1e-6
    # money moves to the index before any goes to cash
    _, _, anchor, info = plan_weights("bold", cands, False, closes)
    assert anchor > 0 and info["moved_to_index"] > 0


def test_cautious_needs_cash_and_calm_picks_keep_the_standard_mix():
    closes, cands = market()
    _, _, _, info = plan_weights("cautious", cands, False, closes)
    assert info["to_cash"] > 0.05 and info["x_spy"] == pytest.approx(0.8, rel=1e-3)   # 95% in stocks is ~0.95x+
    calm, cands2 = market(idio=[0.006] * 10, beta=[0.6] * 10)
    _, w2, anchor2, info2 = plan_weights("balanced", cands2, False, calm)
    assert info2["x_spy_start"] <= 1.0 and info2["to_cash"] == 0
    assert anchor2 == pytest.approx(RISK_LEVELS["balanced"][2])
    assert sum(w2.values()) == pytest.approx(RISK_LEVELS["balanced"][0], abs=0.01)


def test_short_window_makes_the_budget_stricter_when_picks_got_jumpier():
    closes, _ = market()
    stocks = [f"S{i}" for i in range(10)]
    r = closes[stocks].pct_change().fillna(0.0).to_numpy().copy()
    r[-40:] += np.random.default_rng(9).normal(0, 0.05, (40, 10))
    late = closes.copy()
    late[stocks] = 50 * np.cumprod(1 + r, axis=0)
    rets = past_returns(late, stocks)
    w = {s: 0.07 for s in stocks}
    assert fit_risk_budget(w, 0.10, rets, 1.0)["core"] < fit_risk_budget(w, 0.10, rets, 1.0, short=None)["core"]


def test_plan_uses_no_future_data():
    closes, cands = market(n=700)
    t = closes.index[550]
    full = plan_weights("balanced", cands, False, closes, as_of=t)
    cut = plan_weights("balanced", cands, False, closes.loc[:t])
    assert full[1] == pytest.approx(cut[1]) and full[2] == pytest.approx(cut[2])
    shocked = closes.copy()
    shocked.loc[shocked.index > t, "S0"] *= 3                          # wild moves after t change nothing
    assert plan_weights("balanced", cands, False, shocked, as_of=t)[1] == pytest.approx(full[1])


def test_plan_backtest_truncation_costs_and_levels():
    from conftest import make_ohlcv
    from tradebot.plan_backtest import run_plan_backtest

    frames = {f"S{i}": make_ohlcv(900, seed=i, drift=0.0002 + i * 0.0001, vol=0.01 + 0.002 * i) for i in range(12)}
    bench = make_ohlcv(900, seed=99, drift=0.0003, vol=0.01)
    members = pd.DataFrame(True, index=bench.index, columns=list(frames))
    sectors = {s: "ABC"[i % 3] for i, s in enumerate(frames)}
    kw = dict(members=members, sectors=sectors, start=None)
    full = run_plan_backtest(frames, bench, "balanced", **kw)
    cut_at = full["equity"].index[400]
    cut = run_plan_backtest(frames, bench, "balanced", end=str(cut_at.date()), **kw)
    pd.testing.assert_series_equal(full["equity"].loc[:cut_at], cut["equity"], check_freq=False, check_names=False)
    assert {"cagr_%", "volatility_%", "max_drawdown_%", "sharpe", "month_1in20_%", "months_beating_spy_%",
            "turnover_per_year_%"} <= set(full["stats"])
    free = run_plan_backtest(frames, bench, "balanced", cost_bps=0, **kw)
    assert free["equity"].iloc[-1] > full["equity"].iloc[-1]
    before = run_plan_backtest(frames, bench, "balanced", risk_aware=False, **kw)
    assert all(x["core"] <= 0.70 + 1e-9 and x["anchor"] == pytest.approx(0.10) for x in before["log"])
    cautious = run_plan_backtest(frames, bench, "cautious", **kw)
    assert all(x["x_spy_est"] <= TARGET_VOL["cautious"] + 1e-6 for x in cautious["log"] if x["x_spy_est"] is not None)
