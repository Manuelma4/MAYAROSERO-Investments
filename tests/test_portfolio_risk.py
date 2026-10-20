import numpy as np
import pandas as pd
import pytest

from tradebot.portfolio_risk import (daily_returns, diversification, risk_view, simulate_month, worst_drop)


def market(n=900, k=6, seed=0, beta=1.2, idio=0.012):
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(seed)
    m = rng.normal(0.0004, 0.011, n)
    cols = {"SPY": 100 * np.cumprod(1 + m)}
    for i in range(k):
        cols[f"S{i}"] = 50 * np.cumprod(1 + beta * m + rng.normal(0, idio, n))
    return pd.DataFrame(cols, index=idx)


W = {**{f"S{i}": 0.1 for i in range(6)}, "SPY": 0.1}
SECTORS = {f"S{i}": ("Tech" if i < 3 else "Health") for i in range(6)}


def test_monte_carlo_is_reproducible_with_a_seed():
    c = market()
    a = risk_view(c, W, 10_000, sectors=SECTORS, seed=11)
    b = risk_view(c, W, 10_000, sectors=SECTORS, seed=11)
    other = risk_view(c, W, 10_000, sectors=SECTORS, seed=12)
    assert a["month"] == b["month"] and a["histogram"] == b["histogram"]
    assert a["month"]["plan"]["loss_95"] != other["month"]["plan"]["loss_95"]


def test_var_ordering_and_money_scale():
    r = risk_view(market(), W, 10_000, sectors=SECTORS)
    for side in ("plan", "spy"):
        m = r["month"][side]
        assert m["loss_99_%"] > m["loss_95_%"] > 0
        assert m["avg_worst_5_%"] >= m["loss_95_%"]
        assert m["loss_95"] == pytest.approx(m["loss_95_%"] * 100)   # 10,000 x % / 100
    assert sum(r["histogram"]["plan"]) == pytest.approx(1.0)
    assert len(r["histogram"]["plan"]) == len(r["histogram"]["edges_%"]) - 1
    assert len(r["summary"]) >= 4 and "1 in 20" in r["summary"][0] and "S&P 500" in r["summary"][0]


def test_monthly_loss_matches_theory_for_normal_returns():
    """iid normal 1%/day, no volatility clustering: 1-month 5% quantile ~ -1.645 x sqrt(21) x 1%."""
    idx = pd.bdate_range("2020-01-01", periods=2000)
    rng = np.random.default_rng(3)
    spy = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 2000)), index=idx)
    sims = simulate_month({"x": spy.pct_change().dropna()}, n_paths=20_000, seed=1)
    q5 = -np.percentile(sims["x"], 5)
    assert q5 == pytest.approx(1.645 * np.sqrt(21) * 0.01, rel=0.2)


def test_spy_against_itself_has_beta_one_and_identical_risk():
    c = market()
    r = risk_view(c, {"SPY": 1.0}, 10_000)
    assert r["beta"] == pytest.approx(1.0)
    assert r["month"]["plan"] == r["month"]["spy"]
    assert r["volatility_%"] == pytest.approx(r["spy_volatility_%"])
    # same in euros: currency risk hits both sides equally
    fx = pd.Series(1.1 * np.cumprod(1 + np.random.default_rng(5).normal(0, 0.005, len(c))), index=c.index)
    e = risk_view(c, {"SPY": 1.0}, 10_000, "EUR", fx=fx)
    assert e["beta"] == pytest.approx(1.0) and e["currency_risk"]
    assert e["volatility_%"] != pytest.approx(r["volatility_%"])


def test_cash_scales_risk_down():
    c = market()
    full = risk_view(c, {"SPY": 1.0}, 10_000)
    half = risk_view(c, {"SPY": 0.5}, 10_000, ideas_share=0.2)
    assert half["beta"] == pytest.approx(0.5)
    assert half["volatility_%"] == pytest.approx(full["volatility_%"] / 2)
    assert half["cash_share"] == pytest.approx(0.3)
    assert half["month"]["plan"]["loss_95"] < full["month"]["plan"]["loss_95"]
    assert any("live ideas" in s.lower() for s in half["summary"])


def test_correlation_and_independent_bets_on_constructed_cases():
    idx = pd.bdate_range("2020-01-01", periods=5000)
    rng = np.random.default_rng(1)
    indep = pd.DataFrame(rng.normal(0, 0.01, (5000, 4)), index=idx, columns=list("ABCD"))
    w = {s: 0.25 for s in "ABCD"}
    d = diversification(indep, w, {})
    assert d["avg_correlation"] == pytest.approx(0.0, abs=0.05)
    assert d["independent_bets"] == pytest.approx(4.0, rel=0.05)
    assert d["equal_size_count"] == pytest.approx(4.0)
    assert sum(x["risk_share_%"] for x in d["contributors"]) == pytest.approx(100.0)

    one = indep["A"]
    same = pd.DataFrame({s: one for s in "ABCD"})
    d1 = diversification(same, w, {})
    assert d1["avg_correlation"] == pytest.approx(1.0)
    assert d1["independent_bets"] == pytest.approx(1.0)

    # a stock twice as volatile with the same weight is the biggest risk contributor
    loud = indep.assign(D=indep["D"] * 3)
    d2 = diversification(loud, w, {"A": "Tech", "B": "Tech", "C": "Health", "D": "Energy"})
    assert d2["top_contributor"]["symbol"] == "D" and d2["top_contributor"]["risk_share_%"] > 50
    assert d2["sectors"][0]["sector"] == "Energy"
    assert d2["top_sector"]["sector"] == "Tech" and d2["top_sector"]["weight_%"] == pytest.approx(50.0)


def test_worst_drop_and_recovery():
    idx = pd.bdate_range("2024-01-01", periods=7)
    eq = pd.Series([100, 110, 55, 80, 110, 120, 118], index=idx, dtype=float)
    d = worst_drop(eq.pct_change().fillna(0.0))
    assert d["drop_%"] == pytest.approx(-50.0)
    assert d["peak"] == idx[1] and d["trough"] == idx[2] and d["recovered"] == idx[4]
    assert d["fall_days"] == 1 and d["recovery_days"] == 2
    never = worst_drop(pd.Series([0.0, -0.2, 0.05], index=idx[:3]))
    assert never["recovered"] is None and never["recovery_days"] is None


def test_no_future_data_truncation():
    c = market()
    t = c.index[700]
    cut = risk_view(c.loc[:t], W, 10_000, sectors=SECTORS)
    full = risk_view(c, W, 10_000, sectors=SECTORS, as_of=t)
    assert cut == full
    # wild future prices change nothing as of t
    future = c.copy()
    future.loc[c.index > t] *= np.linspace(0.1, 5, (c.index > t).sum())[:, None]
    assert risk_view(future, W, 10_000, sectors=SECTORS, as_of=t) == cut
    assert cut["as_of"] == t.date().isoformat()


def test_missing_history_uses_spy_and_says_so():
    c = market()
    c.loc[c.index[:500], "S0"] = np.nan          # listed recently
    r, notes = daily_returns(c, list(W))
    assert not r.isna().any().any() and notes and notes[0].startswith("S0")
    assert risk_view(c, W, 10_000)["notes"]


def test_empty_and_short_inputs():
    c = market()
    assert risk_view(c, {}, 10_000)["status"] == "empty"
    assert risk_view(c.iloc[:60], W, 10_000)["status"] == "short"
