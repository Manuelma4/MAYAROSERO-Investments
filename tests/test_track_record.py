"""Live forward track record: picks portfolio vs SPY and Invest-now idea outcomes (offline, synthetic)."""

import pandas as pd
import pytest

from conftest import make_ohlcv
from tradebot.api.store import EventStore
from tradebot.live.track_record import (idea_outcome, ideas_summary, line_return, picks_forward,
                                        session_close_known)


def bars(rows, start="2024-03-04"):
    idx = pd.bdate_range(start, periods=len(rows), tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=1.0)


def flat(n, px=100.0, start="2024-03-04"):
    return bars([(px, px, px, px)] * n, start)


def test_session_close_known_waits_for_the_close():
    # 2024-03-04 is a Monday; New York is UTC-5 in early March: close 21:00 UTC (+20 min delay buffer).
    assert not session_close_known("2024-03-04", "2024-03-04T20:59:00Z")
    assert not session_close_known("2024-03-04", "2024-03-04T21:10:00Z")
    assert session_close_known("2024-03-04", "2024-03-04T21:21:00Z")
    assert session_close_known("2024-03-04", "2024-03-07T12:00:00Z")


def test_picks_bought_at_next_open_with_costs_vs_spy():
    spy = bars([(100, 100, 100, 100), (100, 101, 99, 101), (101, 103, 100, 102)])
    a = bars([(50, 50, 50, 50), (52, 55, 51, 55), (55, 60, 54, 60)])
    snap = {"date": "2024-03-04", "weights": {"A": 1.0}}   # decided at Monday's close
    r = picks_forward([snap], {"A": a}, spy, cost_bps=10)
    assert r["first_trade"] == "2024-03-05" and r["days"] == 2   # Monday's close is not tradable
    # Bought at Tuesday's open (52) after 10 bps; Wednesday close 60.
    assert r["return_%"] == pytest.approx((0.999 * 60 / 52 - 1) * 100)
    assert r["spy_%"] == pytest.approx(2.0)           # 100 open -> 102 close
    assert r["turnover_%"] == pytest.approx(100) and r["rebalances"] == 1
    assert r["holdings"] == {"A": pytest.approx(100)}


def test_late_recording_is_never_backdated():
    spy = flat(4)
    a = bars([(10, 10, 10, 10), (10, 10, 10, 10), (20, 20, 20, 20), (20, 20, 20, 20)])
    # Monday's picks only saved on Tuesday afternoon: they count from Wednesday's open (20), not Tuesday's (10).
    late = {"date": "2024-03-04", "recorded_at": "2024-03-05T18:00:00Z", "weights": {"A": 1.0}}
    r = picks_forward([late], {"A": a}, spy, cost_bps=0)
    assert r["first_trade"] == "2024-03-06" and r["return_%"] == pytest.approx(0.0)


def test_rebalance_only_when_picks_change_and_cash_when_empty():
    spy = flat(5)
    a, b = flat(5, 10), flat(5, 20)
    snaps = [{"date": "2024-03-04", "weights": {"A": 0.5, "B": 0.5}},
             {"date": "2024-03-05", "weights": {"A": 0.5, "B": 0.5}},   # same list: no trade
             {"date": "2024-03-06", "weights": {}}]                     # risk-off: all cash
    r = picks_forward(snaps, {"A": a, "B": b}, spy, cost_bps=10)
    assert r["rebalances"] == 2 and r["turnover_%"] == pytest.approx(200, rel=1e-3)
    assert r["holdings"] == {}
    assert r["return_%"] == pytest.approx((0.999 * 0.999 - 1) * 100, rel=1e-6)


def test_picks_forward_has_no_lookahead():
    syms = ["A", "B", "C", "D"]
    data = {s: make_ohlcv(300, seed=i + 1, freq="B") for i, s in enumerate(syms)}
    spy = make_ohlcv(300, seed=99, freq="B")
    days = [d.strftime("%Y-%m-%d") for d in spy.index]
    snaps = [{"date": days[i], "weights": {s: 0.5 for s in syms[(i // 20) % 3:(i // 20) % 3 + 2]}}
             for i in range(10, 290, 7)]
    full = picks_forward(snaps, data, spy)
    cut = 200
    part = picks_forward(snaps, {s: df.iloc[:cut] for s, df in data.items()}, spy.iloc[:cut])
    assert part["days"] < full["days"]
    assert part["curve"] == full["curve"][: part["days"]]


def test_line_return_from_snapshot_close():
    line = [{"time": int(pd.Timestamp(d, tz="UTC").timestamp()), "value": v}
            for d, v in [("2024-03-01", 100), ("2024-03-04", 110), ("2024-03-05", 121)]]
    assert line_return(line, "2024-03-04") == pytest.approx(10.0)
    assert line_return(line, "2024-03-04", "2024-03-04") == pytest.approx(0.0)
    assert line_return([], "2024-03-04") is None


IDEA = {"symbol": "AAA", "direction": "long", "entry": 100.0, "stop": 95.0, "target": 110.0,
        "as_of": "2024-03-04T17:00:00+00:00", "valid_until": "2024-03-04T20:00:00+00:00"}


def test_idea_fills_next_open_and_stop_is_checked_before_target():
    df = bars([(99, 101, 98, 100), (100, 100, 100, 100), (100, 111, 94, 105)])
    o = idea_outcome(IDEA, df, cost_bps=0)
    assert o["fill_date"] == "2024-03-05" and o["fill"] == 100          # not the bar it was issued on
    assert o["status"] == "closed" and o["reason"] == "stop" and o["r"] == pytest.approx(-1.0)


def test_idea_target_gap_and_costs():
    df = bars([(99, 101, 98, 100), (100, 104, 99, 103), (112, 113, 111, 112)])
    o = idea_outcome(IDEA, df, cost_bps=10)
    assert o["reason"] == "target" and o["exit"] == 112                 # gapped above the target: exit at the open
    assert o["r"] == pytest.approx(12 / 5 - 2 * 0.001 * 100 / 5)
    gap_down = bars([(99, 101, 98, 100), (100, 101, 99, 100), (90, 92, 89, 91)])
    assert idea_outcome(IDEA, gap_down, cost_bps=0)["r"] == pytest.approx(-2.0)   # gap through the stop costs more than 1R


def test_idea_time_limit_open_pending_and_short():
    calm = bars([(100, 101, 99, 100)] + [(100, 103, 98, 102)] * 6)
    o = idea_outcome(IDEA, calm, cost_bps=0)
    assert o["reason"] == "time limit" and o["days_held"] == 5 and o["exit_date"] == "2024-03-11"
    assert o["r"] == pytest.approx(0.4)
    part = idea_outcome(IDEA, calm.iloc[:6], cost_bps=0, last_bar_complete=False)   # 5th bar still trading
    assert part["status"] == "open" and part["r"] == pytest.approx(0.4)
    assert idea_outcome(IDEA, calm.iloc[:1])["status"] == "pending"
    short = dict(IDEA, direction="short", stop=105.0, target=90.0)
    s = idea_outcome(short, bars([(99, 101, 98, 100), (100, 101, 89, 92)]), cost_bps=0)
    assert s["reason"] == "target" and s["r"] == pytest.approx(2.0)


def test_idea_outcome_has_no_lookahead():
    df = make_ohlcv(120, seed=7, freq="B")
    ideas = []
    for i in range(5, 100, 4):
        px = float(df["close"].iloc[i])
        d = "long" if i % 8 else "short"
        k = 1 if d == "long" else -1
        ideas.append({"symbol": "X", "direction": d, "entry": px, "stop": px * (1 - 0.02 * k),
                      "target": px * (1 + 0.04 * k), "as_of": (df.index[i] + pd.Timedelta(hours=20)).isoformat()})
    cut = 70
    for idea in ideas:
        full, part = idea_outcome(idea, df), idea_outcome(idea, df.iloc[:cut])
        if part["status"] == "closed":
            assert part == full
        elif part["status"] == "open":
            assert full["fill"] == part["fill"]


def test_ideas_summary():
    outs = [{"status": "closed", "r": 2.0, "exit_date": "2024-03-06", "as_of": "a"},
            {"status": "closed", "r": -1.0, "exit_date": "2024-03-07", "as_of": "b"},
            {"status": "open", "r": 0.3, "as_of": "c"}, {"status": "pending", "r": None, "as_of": "d"}]
    s = ideas_summary(outs)
    assert s["count"] == 4 and s["closed_count"] == 2 and s["open_count"] == 1 and s["pending_count"] == 1
    assert s["win_rate"] == 50 and s["avg_r"] == pytest.approx(0.5) and s["total_r_%"] == pytest.approx(100)
    assert s["closed"][0]["exit_date"] == "2024-03-07"
    assert ideas_summary([])["win_rate"] is None


def test_store_records_once_per_day(tmp_path):
    st = EventStore(tmp_path / "t.db")
    picks = [{"symbol": "A", "weight": 0.5, "price": 10}, {"symbol": "B", "weight": 0.5, "price": 20}]
    assert st.record_picks_snapshot("qm", "2024-03-04", picks, False, "2024-03-04T21:30:00Z")
    assert not st.record_picks_snapshot("qm", "2024-03-04", [], True, "2024-03-04T22:00:00Z")
    assert st.record_picks_snapshot("qm", "2024-03-05", picks, False, "2024-03-05T21:30:00Z")
    snaps = st.picks_snapshots("qm")
    assert [s["date"] for s in snaps] == ["2024-03-04", "2024-03-05"] and snaps[0]["weights"] == {"A": 0.5, "B": 0.5}
    idea = dict(IDEA, hold_days=5, expires_at="2024-03-04T20:00:00+00:00")
    assert st.record_idea(idea, "2024-03-04T17:00:05Z")
    assert not st.record_idea(dict(idea, as_of="2024-03-04T18:00:00+00:00", entry=101), "x")   # same day
    assert st.record_idea(dict(idea, direction="short", stop=105.0, target=90.0), "x")
    rows = st.track_ideas()
    assert len(rows) == 2 and rows[0]["entry"] == 100 and rows[0]["valid_until"] == idea["expires_at"]


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient

    from test_api import FakeProvider
    from tradebot.api import create_app
    from tradebot.api.settings import Settings

    prov = FakeProvider()
    settings = Settings(db_path=tmp_path / "t.db", static_dir=None, api_token=None, autostart_live=False,
                        precompute=False)
    with TestClient(create_app(settings, provider_factory=lambda n, e: prov, config={})) as c:
        yield c


def test_track_record_api_just_started_then_with_history(client):
    empty = client.get("/api/track-record").json()
    assert empty["started"] is None and empty["days"] == 0 and empty["too_early"] and empty["message"]
    assert empty["ideas"]["count"] == 0 and empty["ideas"]["win_rate"] is None

    pre, store = client.app.state.precompute, client.app.state.store
    pre.run_once(predictions=False)
    pre.run_once(predictions=False)                     # idempotent: still one snapshot per preset and day
    snaps = store.picks_snapshots("quality_momentum")
    assert len(snaps) == 1
    tr = client.get("/api/track-record").json()
    # The synthetic data ended long before the snapshot was saved: nothing is back-dated.
    assert tr["started"] == snaps[0]["date"] and tr["days"] == 0 and "Just started" in tr["message"]

    # A record that has been running for a while (saved at the time, as the live loop does).
    store.record_picks_snapshot("quality_momentum", "2021-06-01",
                                [{"symbol": "AAA", "weight": 0.5, "price": 1}, {"symbol": "BBB", "weight": 0.5, "price": 1}],
                                False, "2021-06-01T21:00:00+00:00")
    store.record_picks_snapshot("quality_momentum", "2021-06-15", [], True, "2021-06-15T21:00:00+00:00")
    px = float(client.app.state.market.history("yahoo", "AAA", "1d").loc["2021-06-02", "close"])
    store.record_idea({"symbol": "AAA", "direction": "long", "entry": px, "stop": px * 0.97, "target": px * 1.06,
                       "as_of": "2021-06-02T18:00:00+00:00", "expires_at": "2021-06-02T21:00:00+00:00",
                       "hold_days": 5}, "2021-06-02T18:00:00+00:00")
    pre.put("track:quality_momentum", None)            # drop the 2-minute cache
    tr = client.get("/api/track-record", params={"preset": "quality_momentum"}).json()
    assert tr["started"] == "2021-06-01" and tr["days"] > 20 and not tr["too_early"]
    p = tr["picks"]
    assert p["first_trade"] == "2021-06-02" and p["rebalances"] == 2 and p["holdings"] == {}
    assert len(p["curve"]) == tr["days"] and {"picks", "spy", "date", "time"} <= set(p["curve"][0])
    assert p["return_%"] is not None and p["spy_%"] is not None and p["universe_%"] is not None
    ideas = tr["ideas"]
    assert ideas["count"] == 1 and ideas["closed_count"] == 1 and ideas["closed"][0]["fill_date"] == "2021-06-03"
    assert ideas["win_rate"] in (0, 100) and ideas["avg_r"] is not None
    assert client.get("/api/track-record", params={"preset": "nope"}).status_code == 404


def test_scan_records_qualified_ideas(client):
    pre = client.app.state.precompute
    item = {"symbol": "AAA", "name": "Aaa", "direction": "long", "as_of": "2026-10-20T15:00:00+00:00",
            "price": 100.0, "change_pct": 5.0, "sigma": 3.0, "rel_volume": 3.0, "trend": "uptrend",
            "pct_from_extreme": 1.0, "entry": 100.0, "stop": 95.0, "target": 110.0, "risk_pct": 5.0,
            "hold_days": 5, "expires_at": "2026-10-20T18:00:00+00:00", "score": 80.0, "catalyst": "earnings",
            "headline": "h", "headline_url": "u", "headline_publisher": "X", "qualified": True, "reasons": []}
    watch = dict(item, symbol="BBB", qualified=False)
    pre._scanner = type("S", (), {"scan": lambda self, now=None: [
        type("O", (), {"to_dict": lambda s2, d=d: dict(d)})() for d in (item, watch)]})()
    pre.scan_opportunities()
    pre.scan_opportunities()
    rows = client.app.state.store.track_ideas()
    assert [r["symbol"] for r in rows] == ["AAA"]      # qualified only, once per day
    tr = pre.track_record(max_age=0)
    assert tr["ideas"]["pending_count"] == 1 and tr["started"] == "2026-10-20"


def test_restart_does_not_repeat_an_opportunity_alert(client):
    """The idea is already in SQLite: a restarted Precomputer (empty memory) must not announce it again."""
    from tradebot.api.precompute import Precomputer

    item = {"symbol": "AAA", "name": "Aaa", "direction": "long", "as_of": "2026-10-20T15:00:00+00:00",
            "entry": 100.0, "stop": 95.0, "target": 110.0, "hold_days": 5, "qualified": True}
    scanner = type("S", (), {"scan": lambda self, now=None: [type("O", (), {"to_dict": lambda s2: dict(item)})()]})()
    sent = []
    first = Precomputer(client.app.state.market, store=client.app.state.store, on_opportunity=sent.append)
    first._scanner = scanner
    first.scan_opportunities()
    restarted = Precomputer(client.app.state.market, store=client.app.state.store, on_opportunity=sent.append)
    restarted._scanner = scanner
    restarted.scan_opportunities()
    assert [o["symbol"] for o in sent] == ["AAA"]
