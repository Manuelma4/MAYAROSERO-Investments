from tradebot.live.alerts import due, message

from test_api import client  # noqa: F401  (fixture)


def test_due_rules():
    q = {"price": 105.0, "change_pct": -6.0}
    assert due({"kind": "above", "value": 100}, q)
    assert not due({"kind": "above", "value": 110}, q)
    assert due({"kind": "below", "value": 110}, q)
    assert due({"kind": "move", "value": 5}, q)          # a 6% drop counts as a 5% move
    assert not due({"kind": "move", "value": 7}, q)
    assert not due({"kind": "above", "value": 100, "active": False}, q)
    assert not due({"kind": "above", "value": 100}, {})   # no quote, no alert
    stale = {"kind": "move", "value": 5, "last_bar": "2026-10-16T00:00:00"}
    assert not due(stale, {**q, "time": "2026-10-16T00:00:00"})   # same daily bar after re-arm
    assert due(stale, {**q, "time": "2026-10-19T00:00:00"})       # a new day's move
    assert "AAA" in message({"symbol": "AAA", "kind": "below", "value": 110, "note": "buy zone"}, q)


def test_watchlists_crud(client):  # noqa: F811
    w = client.post("/api/watchlists", json={"name": "Tech", "symbols": ["aapl", "MSFT", "AAPL", "BTC/USDT"]}).json()
    assert w["symbols"] == ["AAPL", "MSFT", "BTC/USDT"]
    w2 = client.put(f"/api/watchlists/{w['id']}", json={"name": "Big tech", "symbols": ["NVDA"]}).json()
    assert w2 == {"id": w["id"], "name": "Big tech", "symbols": ["NVDA"]}
    assert client.get("/api/watchlists").json() == [w2]
    assert client.post("/api/watchlists", json={"name": "x", "symbols": ["DROP TABLE;"]}).status_code == 422
    assert client.put("/api/watchlists/999", json={"name": "x", "symbols": []}).status_code == 404
    assert client.delete(f"/api/watchlists/{w['id']}").json() == {"ok": True}
    assert client.get("/api/watchlists").json() == []


def test_alert_fires_once_and_rearms(client):  # noqa: F811
    pre = client.app.state.precompute
    price = client.get("/api/quotes", params={"symbols": "AAA"}).json()[0]["price"]
    r = client.post("/api/alerts", json={"symbol": "AAA", "kind": "above", "value": price * 0.5})
    assert r.status_code == 422 and "already above" in r.json()["detail"]   # level already passed
    miss = client.post("/api/alerts", json={"symbol": "aaa", "kind": "below", "value": price * 0.5,
                                           "note": "buy\nzone"}).json()
    assert miss["symbol"] == "AAA" and miss["note"] == "buy zone"
    for bad in ({"kind": "sideways", "value": 1}, {"kind": "above", "value": 0}, {"kind": "move", "value": 500}):
        assert client.post("/api/alerts", json={"symbol": "AAA", **bad}).status_code == 422
    assert client.post("/api/alerts", content='{"symbol":"AAA","kind":"above","value":1e999}',
                       headers={"content-type": "application/json"}).status_code == 422
    # the price moved past the level after the alert was set (simulated by storing it directly)
    hit = client.app.state.store.add_alert("AAA", "above", price * 0.5)
    fired = pre.check_alerts()
    assert [a["id"] for a in fired] == [hit["id"]]
    assert pre.check_alerts() == []                         # fires once, then deactivates
    listed = {a["id"]: a for a in client.get("/api/alerts").json()["alerts"]}
    assert not listed[hit["id"]]["active"] and listed[hit["id"]]["triggered_price"] == price
    assert listed[miss["id"]]["active"]
    events = client.get("/api/events", params={"type": "alert"}).json()
    assert events and events[0]["symbol"] == "AAA"
    assert client.post(f"/api/alerts/{hit['id']}/rearm").status_code == 422   # still above: would re-fire
    assert client.get("/api/alerts").status_code == 200
    assert client.delete(f"/api/alerts/{miss['id']}").json() == {"ok": True}


def test_picks_change_alert_once_per_review(client):  # noqa: F811
    pre = client.app.state.precompute
    sent = []
    pre.on_picks_change = sent.append
    pre.put("picks:core_momentum", {"changes": {"date": "2026-09-30", "buy": ["NVDA"], "sell": ["KO"], "keep": ["AAPL"]}})
    ev = pre.record_picks_change()
    assert ev["buy"] == ["NVDA"] and ev["sell"] == ["KO"] and sent == [ev]
    assert pre.record_picks_change() is None                       # same review: no repeat
    pre.put("picks:core_momentum", {"changes": {"date": "2026-10-31", "buy": [], "sell": [], "keep": ["AAPL"]}})
    assert pre.record_picks_change() is None                       # nothing changed: no alert
    pre.put("picks:core_momentum", {"changes": {"date": "2026-11-30", "buy": ["MSFT"], "sell": [], "keep": []}})
    assert pre.record_picks_change()["date"] == "2026-11-30" and len(sent) == 2
    assert [e["date"] for e in client.get("/api/events", params={"type": "picks"}).json()] == ["2026-11-30", "2026-09-30"]
    pre.put("picks:core_momentum", {"changes": {"date": "2025-01-31", "buy": ["X"], "sell": [], "keep": []}})
    assert pre.record_picks_change() and len(sent) == 2               # old review: recorded, not announced
