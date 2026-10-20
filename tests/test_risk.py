import pandas as pd
import pytest

from tradebot.trading.risk import OrderRejected, RiskLimits, plan_order

NOW = pd.Timestamp("2026-10-20 15:00", tz="UTC")


def test_size_from_risk_and_cap():
    p = plan_order("ACME", "long", 100.0, 95.0, 110.0, 10_000, [], 0, now=NOW)
    # 1% of 10k = 100 risk / 5 per share = 20 shares, but capped at 10% of equity = 10 shares
    assert p.qty == 10 and p.value == 1000 and p.max_loss == 50
    wide = plan_order("ACME", "long", 100.0, 80.0, 140.0, 100_000, [], 0, now=NOW)
    assert wide.qty == 50 and wide.max_loss == pytest.approx(1000)  # risk-based (1%)


@pytest.mark.parametrize("kwargs,msg", [
    ({"stop": 105.0}, "stop-loss"),
    ({"expires_at": "2026-10-20T14:00:00+00:00"}, "expired"),
    ({"open_positions": [{"symbol": "ACME", "side": "long", "qty": 1, "entry": 1}]}, "already hold"),
    ({"open_positions": [{"symbol": f"S{i}", "side": "long", "qty": 1, "entry": 1} for i in range(5)]}, "at most 5"),
    ({"realized_today": -300.0}, "Daily loss"),
])
def test_rejections(kwargs, msg):
    args = dict(symbol="ACME", side="long", entry=100.0, stop=95.0, target=110.0, equity=10_000,
                open_positions=[], realized_today=0.0, now=NOW)
    args.update(kwargs)
    with pytest.raises(OrderRejected, match=msg):
        plan_order(**args)


def test_short_exposure_cap():
    shorts = [{"symbol": "X", "side": "short", "qty": 20, "entry": 100.0}]  # 2,000 = 20% of 10k
    with pytest.raises(OrderRejected, match="Short limit"):
        plan_order("ACME", "short", 50.0, 55.0, 40.0, 10_000, shorts, 0, now=NOW)
    ok = plan_order("ACME", "short", 50.0, 55.0, 40.0, 10_000, [], 0, now=NOW)
    assert ok.qty * ok.entry <= 2_000 + 1e-9 and ok.stop > ok.entry
