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
    settings = Settings(db_path=tmp_path / "t.db", static_dir=None, api_token=None, autostart_live=False)

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
    settings = Settings(db_path=tmp_path / "t.db", static_dir=None, api_token="s3cret")
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
    settings = Settings(db_path=tmp_path / "t.db", static_dir=dist, api_token=None)
    with TestClient(create_app(settings, config={})) as c:
        assert "app" in c.get("/backtest").text
        assert "nope" not in c.get("/..%2Fsecret.txt").text
        assert c.get("/api/unknown").status_code == 404
