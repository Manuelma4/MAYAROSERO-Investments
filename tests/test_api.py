import time

import pytest
from fastapi.testclient import TestClient

from conftest import make_ohlcv
from tradebot.api import create_app
from tradebot.api.settings import Settings
from tradebot.data import DataProvider
from tradebot.live import PaperBroker, Scanner
from tradebot.live.scanner import WatchItem


class FakeProvider(DataProvider):
    """Offline provider for tests: deterministic synthetic candles per symbol."""

    def __init__(self):
        self.calls = 0

    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        self.calls += 1
        if symbol == "MISSING":
            raise ValueError("No data for MISSING")
        df = make_ohlcv(1500, seed=sum(map(ord, symbol)) % 100)
        return df.tail(limit) if limit else df


@pytest.fixture
def client(tmp_path):
    prov = FakeProvider()
    settings = Settings(db_path=tmp_path / "t.db", static_dir=None, api_token=None, autostart_live=False, precompute=False)

    def scanner_factory(cfg):
        item = WatchItem("yahoo", "AAA", "1d", [{"name": "ema_cross_rsi"}])
        sc = Scanner([item], [], PaperBroker(tmp_path / "paper.json"))
        sc._providers[("yahoo", "binance")] = prov
        return sc

    app = create_app(settings, provider_factory=lambda n, e: prov, config={"poll_seconds": 60},
                     scanner_factory=scanner_factory)
    with TestClient(app) as c:
        c.provider = prov
        yield c


def test_health_and_strategies(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    names = {s["name"] for s in client.get("/api/strategies").json()}
    assert {"ema_cross_rsi", "dow_pullback", "wyckoff_spring"} <= names


def test_chart(client):
    r = client.get("/api/chart", params={"symbol": "AAPL", "limit": 300})
    assert r.status_code == 200
    d = r.json()
    assert len(d["candles"]) == 300
    assert {"ema20", "ema50", "ema200"} <= set(d["overlays"])
    assert d["analysis"]["trend"] in (-1, 0, 1)
    assert d["candles"][0]["time"] < d["candles"][-1]["time"]


def test_chart_cache(client):
    client.get("/api/chart", params={"symbol": "AAPL"})
    n = client.provider.calls
    client.get("/api/chart", params={"symbol": "AAPL"})
    assert client.provider.calls == n


def test_data_error_is_502(client):
    r = client.get("/api/chart", params={"symbol": "MISSING"})
    assert r.status_code == 502 and "MISSING" in r.json()["detail"]


def test_backtest(client):
    r = client.post("/api/backtest", json={"symbol": "AAPL", "strategy": "dow_pullback"})
    assert r.status_code == 200
    d = r.json()
    assert d["stats"]["trades"] == len(d["trades"])
    assert len(d["equity"]) == len(d["candles"])


def test_backtest_bad_input(client):
    assert client.post("/api/backtest", json={"strategy": "nope"}).status_code == 400
    assert client.post("/api/backtest", json={"risk_per_trade": 5}).status_code == 422


def test_predict(client):
    r = client.post("/api/predict", json={"symbols": ["AAA", "BBB"], "horizon": 5})
    assert r.status_code == 200
    d = r.json()
    assert {p["symbol"] for p in d["predictions"]} == {"AAA", "BBB"}
    assert all(p["action"] in ("BUY", "SELL", "HOLD") for p in d["predictions"])
    assert "has_edge" in d["validation"]


def test_live_scan_and_events_ws(client):
    status = client.get("/api/live/status").json()
    assert status["running"] is False
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "status"
        r = client.post("/api/live/scan").json()
        assert r["status"]["scans"] == 1
        msg = ws.receive_json()
        while msg["type"] != "status":
            assert msg["type"] == "signal"
            msg = ws.receive_json()
    events = client.get("/api/events").json()
    assert len(events) == len(r["events"])
    assert client.get("/api/paper").json()["enabled"] is True


def test_live_start_stop(client):
    assert client.post("/api/live/start").json()["running"] is True
    time.sleep(0.2)
    assert client.post("/api/live/stop").json()["running"] is False


def test_token_auth(tmp_path):
    settings = Settings(db_path=tmp_path / "t.db", static_dir=None, api_token="s3cret", precompute=False)
    app = create_app(settings, provider_factory=lambda n, e: FakeProvider(), config={})
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/strategies").status_code == 401
        assert c.get("/api/strategies", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_spa_fallback_and_traversal(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (tmp_path / "secret.txt").write_text("nope")
    settings = Settings(db_path=tmp_path / "t.db", static_dir=dist, api_token=None, precompute=False)
    with TestClient(create_app(settings, config={})) as c:
        assert "app" in c.get("/backtest").text
        assert "nope" not in c.get("/..%2Fsecret.txt").text
        assert c.get("/api/unknown").status_code == 404


def test_quotes(client):
    r = client.get("/api/quotes", params={"symbols": "AAPL,BTC/USDT,MISSING,AAPL"})
    assert r.status_code == 200
    q = {x["symbol"]: x for x in r.json()}
    assert set(q) == {"AAPL", "BTC/USDT", "MISSING"}  # de-duplicated
    assert q["BTC/USDT"]["provider"] == "ccxt" and q["AAPL"]["provider"] == "yahoo"
    assert len(q["AAPL"]["spark"]) == 30 and q["AAPL"]["price"] == q["AAPL"]["spark"][-1]
    assert "error" in q["MISSING"]


def test_chart_auto_provider(client):
    d = client.get("/api/chart", params={"symbol": "ETH/USDT", "provider": "auto", "limit": 100}).json()
    assert len(d["candles"]) == 100


def test_universe(client):
    d = client.get("/api/universe").json()
    assert len(d["sectors"]) == 11 and "Magnificent 7" in d["themes"]
    m7 = [s["symbol"] for s in d["stocks"] if "Magnificent 7" in s["themes"]]
    assert set(m7) == {"AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA"}
    assert any(c["symbol"] == "BTC/USDT" for c in d["crypto"])


def test_picks(client):
    r = client.post("/api/picks", json={"symbols": [f"S{i}" for i in range(15)], "top_n": 5,
                                         "start": "2020-01-01", "benchmark": "SPY"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["picks"]) <= 5 and d["universe_size"] == 15
    assert len(d["equity"]) == len(d["benchmark"]) > 100
    assert {"cagr_%", "benchmark_cagr_%", "excess_cagr_%", "max_drawdown_%", "skill_vs_universe_%"} <= set(d["stats"])
    assert len(d["universe"]) == len(d["equity"])
    assert d["holdings"][0]["date"] >= d["holdings"][-1]["date"]  # newest first


def test_precompute_today_and_latest_picks(client):
    pre = client.app.state.precompute
    assert client.get("/api/today").status_code == 503  # not computed yet: clear message, no crash
    pre.run_once()
    assert pre.last_error is None, pre.last_error
    t = client.get("/api/today").json()
    assert t["mood"]["label"] in {"Risk-on", "Neutral", "Risk-off"} and t["mood"]["explanation"]
    assert isinstance(t["core"]["picks"], list)  # may be empty if nothing is in an uptrend
    latest = client.get("/api/picks/latest").json()
    assert latest["ranking"] and all(r["reason"] for r in latest["ranking"])
    assert {"buy", "sell", "keep"} <= set(t["core"]["changes"])
    assert len(t["gainers"]) == 6 and t["gainers"][0]["change_pct"] >= t["losers"][0]["change_pct"]
    for preset in ("quality_momentum", "momentum", "trend_following", "low_volatility"):
        assert client.get("/api/picks/latest", params={"preset": preset}).json()["preset"] == preset


def test_pick_reason_plain_english():
    from tradebot.api.services import pick_reason

    r = pick_reason({"momentum_12_1_%": 45.2, "rel_strength_%": -3.1, "trend_%": 12.0, "volatility_%": 21})
    assert r == ("Up 45% over the past year, lagging the S&P 500 by 3% over 6 months, "
                 "12% above its 200-day average, calm price action.")


def test_completed_changes_skips_provisional_review():
    import pandas as pd

    from tradebot.api.services import completed_changes

    h = [{"date": "2026-08-31", "symbols": ["A", "B"]},
         {"date": "2026-09-30", "symbols": ["B", "C"]},
         {"date": "2026-10-20", "symbols": ["C", "D"]}]  # mid-month: still provisional
    c = completed_changes(h, "ME", pd.Timestamp("2026-10-20"))
    assert c["date"] == "2026-09-30" and c["buy"] == ["C"] and c["sell"] == ["A"] and c["keep"] == ["B"]
    assert c["provisional_skipped"] is True
    done = completed_changes(h[:2], "ME", pd.Timestamp("2026-09-30"))
    assert done["date"] == "2026-09-30" and done["provisional_skipped"] is False


def test_unknown_preset_is_404(client):
    assert client.get("/api/picks/latest", params={"preset": "nope"}).status_code == 404


def test_opportunities_and_paper_invest(client, monkeypatch):
    import pandas as pd

    pre = client.app.state.precompute
    assert client.get("/api/opportunities").status_code == 503
    fake = {"symbol": "AAA", "name": "Aaa", "direction": "long", "as_of": "2026-10-20T15:00:00+00:00",
            "price": 100.0, "change_pct": 5.0, "sigma": 3.0, "rel_volume": 3.0, "trend": "uptrend",
            "pct_from_extreme": 1.0, "entry": 100.0, "stop": 95.0, "target": 110.0, "risk_pct": 5.0,
            "hold_days": 5, "expires_at": "2099-01-01T00:00:00+00:00", "score": 80.0, "catalyst": "earnings",
            "headline": "Aaa beats earnings", "headline_url": "u", "headline_publisher": "X", "qualified": True,
            "reasons": ["r"]}

    class FakeScanner:
        def scan(self, now=None):
            class O:
                def to_dict(self_inner):
                    return dict(fake)
            return [O()]

    pre._scanner = FakeScanner()
    sent = []
    pre.on_opportunity = lambda o: sent.append(o["symbol"])
    data = client.post("/api/opportunities/scan").json()
    assert data["items"][0]["symbol"] == "AAA" and sent == ["AAA"]
    pre.scan_opportunities()
    assert sent == ["AAA"]  # notified once per day

    # The fake provider's last close for AAA becomes the fresh fill price; align the idea with it.
    px = client.app.state.market.quote("AAA")["price"]
    fake.update(entry=px, price=px, stop=px * 0.95, target=px * 1.1)
    pre.scan_opportunities()
    order = {"symbol": "AAA", "side": "long"}
    prev = client.post("/api/paper/orders", json={**order, "preview": True}).json()
    assert prev["mode"] == "paper" and prev["plan"]["stop"] == pytest.approx(px * 0.95) and "placed" not in prev
    placed = client.post("/api/paper/orders", json=order).json()
    assert placed["placed"] is True
    again = client.post("/api/paper/orders", json=order)
    assert again.status_code == 400 and "already hold" in again.json()["detail"]
    paper = client.get("/api/paper").json()
    assert paper["positions"][0]["symbol"] == "AAA" and paper["positions"][0]["strategy"] == "opportunity"
    gone = client.post("/api/paper/orders", json={"symbol": "BBB", "side": "long"})
    assert gone.status_code == 400 and "no longer active" in gone.json()["detail"]
    moved = dict(fake, symbol="AAA", entry=px * 1.05)  # signal far from the current price
    pre._scanner = type("S", (), {"scan": lambda self, now=None: [type("O", (), {"to_dict": lambda s2: dict(moved)})()]})()
    pre.scan_opportunities()
    client.post("/api/paper/close-all")
    r = client.post("/api/paper/orders", json=order)
    assert r.status_code == 400 and "moved" in r.json()["detail"]
    assert client.get("/api/paper").json()["positions"] == []


def test_ai_analyst_off_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client.app.state.analyst._client = None
    assert client.get("/api/ai/status").json()["enabled"] is False
    r = client.post("/api/ai/analyze", params={"symbol": "AAA"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_ai_analyst_with_fake_client(client):
    import json as _json
    from types import SimpleNamespace

    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            out = {"technical": "Uptrend.", "news": "No news.", "fundamentals": "Missing.", "bull_case": "Momentum.",
                   "bear_case": "Extended.", "verdict": "neutral", "confidence": 140, "summary": "Mixed.",
                   "main_risk": "Pullback.", "invalidation": "Close below the 200-day average."}
            return SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                                   content=[SimpleNamespace(type="text", text=_json.dumps(out))])

    an = client.app.state.analyst
    an._client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    an.news, an.fundamentals_fn = None, lambda s: {"sector": "Tech"}  # offline
    d = client.post("/api/ai/analyze", params={"symbol": "AAA"}).json()
    assert d["verdict"] == "neutral" and d["confidence"] == 100 and d["symbol"] == "AAA"
    sent = calls[0]
    assert sent["model"] == "claude-opus-5-5" and sent["output_config"]["format"]["type"] == "json_schema"
    assert "technical" in sent["messages"][0]["content"]
    client.post("/api/ai/analyze", params={"symbol": "AAA"})
    assert len(calls) == 1  # cached for the day


def test_portfolio_endpoint(client):
    pre = client.app.state.precompute
    assert client.post("/api/portfolio", json={}).status_code == 503
    pre.run_once()
    d = client.post("/api/portfolio", json={"amount": 10000, "currency": "USD", "risk": "balanced"}).json()
    invested = sum(l["invested"] for l in d["lines"])
    assert abs(invested + d["cash"] - 10000) < 1e-6
    assert all(v <= 0.25 + 1e-6 for v in d["by_sector"].values())
    assert {"cagr_%", "spy_cagr_%"} <= set(d["track_record"])
    eur = client.post("/api/portfolio", json={"amount": 10000, "currency": "EUR", "risk": "cautious"}).json()
    assert eur["currency"] == "EUR" and eur["fx_usd_per_unit"] > 0
    assert client.post("/api/portfolio", json={"risk": "yolo"}).status_code == 422
