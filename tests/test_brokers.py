"""Broker layer, offline: mocked HTTP for Alpaca, a fake ccxt exchange, a fake ib_insync client.

No network, no real order: every adapter gets a fake transport.
"""

import json
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from test_api import FakeProvider
from tradebot.api import create_app
from tradebot.api.settings import Settings
from tradebot.trading.brokers import ALPACA_URLS, BrokerError, make_broker, resolve_endpoint, trading_mode
from tradebot.trading.brokers.alpaca import AlpacaBroker
from tradebot.trading.brokers.ccxt_broker import CCXTBroker
from tradebot.trading.brokers.ibkr import IBKRBroker
from tradebot.trading.guard import ConfirmTokens
from tradebot.trading.risk import RiskLimits

KEYS = {"ALPACA_API_KEY_ID": "k", "ALPACA_API_SECRET_KEY": "s"}
LIVE = {"TRADING_MODE": "live"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("BROKER", "TRADING_MODE", "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "MAX_ORDER_VALUE", "RISK_PER_TRADE_PCT"):
        monkeypatch.delenv(k, raising=False)


# -- fakes -------------------------------------------------------------------------------------------------
class Resp:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data
        self.content = b"" if data is None else json.dumps(data).encode()
        self.text = self.content.decode()

    def json(self):
        return self._data


class FakeAlpacaSession:
    def __init__(self, price=100.0, equity=10_000.0, last_equity=10_000.0, positions=None):
        self.headers, self.calls = {}, []
        self.price, self.equity, self.last_equity = price, equity, last_equity
        self.pos = positions or []

    def request(self, method, url, timeout=None, **kw):
        self.calls.append((method, url, kw))
        path = url.split(".markets", 1)[1]
        if path == "/v2/account":
            return Resp({"equity": str(self.equity), "last_equity": str(self.last_equity), "cash": str(self.equity),
                         "buying_power": str(self.equity * 2), "currency": "USD", "status": "ACTIVE"})
        if path == "/v2/positions" and method == "GET":
            return Resp(self.pos)
        if path.endswith("/trades/latest"):
            return Resp({"trade": {"p": self.price}})
        if path == "/v2/orders" and method == "POST":
            return Resp({"id": "o-1", "status": "accepted"})
        if path == "/v2/orders" and method == "GET":
            return Resp([{"id": "leg-1"}])
        if method == "DELETE" and path == "/v2/orders":
            return Resp([{"id": "a", "status": 200}])
        if method == "DELETE" and path == "/v2/positions":
            return Resp([{"symbol": p["symbol"], "status": 200} for p in self.pos])
        if method == "DELETE":
            return Resp(None, 204)
        return Resp({"message": "not found"}, 404)

    def orders_sent(self):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith("/v2/orders")]


class FakeExchange:
    def __init__(self, sandbox=True, price=100.0, usdt=10_000.0, holdings=None, stop_ok=True):
        self.has = {"createStopLossOrder": stop_ok, "sandbox": sandbox}
        self._sandbox_ok, self.isSandboxModeEnabled = sandbox, False
        self.price, self.usdt, self.holdings = price, usdt, dict(holdings or {})
        self.orders, self.cancelled, self.stop_ok = [], [], True

    def set_sandbox_mode(self, on):
        if not self._sandbox_ok:
            raise TypeError("'NoneType' object is not iterable")   # what ccxt.kraken really raises
        self.isSandboxModeEnabled = on

    def fetch_balance(self):
        total = {"USDT": self.usdt, **self.holdings}
        return {"total": total, "free": total}

    def fetch_tickers(self, pairs):
        return {p: {"last": self.price} for p in pairs}

    def fetch_ticker(self, pair):
        return {"last": self.price}

    def load_markets(self):
        return {}

    def amount_to_precision(self, sym, qty):
        return f"{qty:.4f}"

    def create_order(self, sym, type, side, amount, price=None, params=None):
        params = params or {}
        if "stopLossPrice" in params and not self.stop_ok:
            raise RuntimeError("stop refused")
        self.orders.append((sym, type, side, amount, price, params))
        return {"id": f"x{len(self.orders)}", "filled": amount, "status": "closed", "average": self.price}

    def fetch_open_orders(self, symbol=None):
        return [{"id": "open-1", "symbol": "BTC/USDT"}]

    def cancel_order(self, oid, symbol=None):
        self.cancelled.append(oid)


# -- the single endpoint decision -------------------------------------------------------------------------
@pytest.mark.parametrize("value,mode", [(None, "paper"), ("", "paper"), ("paper", "paper"), ("true", "paper"),
                                        ("1", "paper"), ("livee", "paper"), ("real", "paper"),
                                        ("live", "live"), (" LIVE ", "live"), ("Live", "live")])
def test_trading_mode_is_live_only_with_trading_mode_live(value, mode):
    env = {} if value is None else {"TRADING_MODE": value}
    assert trading_mode(env) == mode
    ep = resolve_endpoint("alpaca", env)
    assert ep.mode == mode and ep.url == ALPACA_URLS[mode] and ep.sandbox == (mode == "paper")
    assert resolve_endpoint("ccxt", env).sandbox == (mode == "paper")


def test_paper_broker_never_live_and_unknown_broker_refused():
    assert resolve_endpoint("paper", LIVE).mode == "paper"
    with pytest.raises(BrokerError, match="Unknown BROKER"):
        resolve_endpoint("robinhood", {})
    with pytest.raises(BrokerError, match="Unknown BROKER"):
        make_broker({"BROKER": "nope"})
    assert make_broker({}).name == "paper"   # default


def test_ibkr_ports_follow_the_mode():
    assert resolve_endpoint("ibkr", {}).port == 7497
    assert resolve_endpoint("ibkr", {"IBKR_PORT": "4002"}).mode == "paper"
    with pytest.raises(BrokerError, match="not a paper-trading port"):
        resolve_endpoint("ibkr", {"IBKR_PORT": "7496"})          # live port without TRADING_MODE=live
    assert resolve_endpoint("ibkr", LIVE).port == 7496
    with pytest.raises(BrokerError, match="paper port"):
        resolve_endpoint("ibkr", {**LIVE, "IBKR_PORT": "7497"})


# -- Alpaca -----------------------------------------------------------------------------------------------
def test_alpaca_uses_paper_endpoint_unless_live():
    s = FakeAlpacaSession()
    paper = AlpacaBroker({**KEYS, "BROKER": "alpaca"}, session=s)
    paper.account()
    assert paper.mode == "paper" and s.calls[-1][1] == "https://paper-api.alpaca.markets/v2/account"
    s2 = FakeAlpacaSession()
    live = AlpacaBroker({**KEYS, **LIVE}, session=s2)
    live.account()
    assert live.mode == "live" and s2.calls[-1][1] == "https://api.alpaca.markets/v2/account"
    with pytest.raises(BrokerError, match="keys missing"):
        AlpacaBroker({})


def test_alpaca_bracket_order_and_refusals():
    s = FakeAlpacaSession()
    b = AlpacaBroker(KEYS, session=s)
    o = b.place_order("AAPL", "buy", 3, type="limit", limit_price=100.5, stop_loss=95.123, take_profit=110)
    body = s.orders_sent()[0][2]["json"]
    assert o["id"] == "o-1" and body["order_class"] == "bracket" and body["qty"] == "3"
    assert body["stop_loss"] == {"stop_price": 95.12} and body["take_profit"] == {"limit_price": 110}
    assert body["type"] == "limit" and body["limit_price"] == 100.5 and body["time_in_force"] == "day"
    with pytest.raises(BrokerError, match="stop-loss"):
        b.place_order("AAPL", "buy", 3)
    with pytest.raises(BrokerError, match="whole"):
        b.place_order("AAPL", "buy", 2.5, stop_loss=90)
    with pytest.raises(BrokerError, match="ccxt"):
        b.normalize_qty("BTC/USDT", 1)
    assert b.normalize_qty("AAPL", 7.9) == 7 and len(s.orders_sent()) == 1


def test_alpaca_kill_switch_cancels_and_closes():
    s = FakeAlpacaSession(positions=[{"symbol": "AAPL", "qty": "3", "avg_entry_price": "100", "side": "long"}])
    res = AlpacaBroker(KEYS, session=s).close_all()
    deletes = [(m, u.split(".markets")[1]) for m, u, _ in s.calls if m == "DELETE"]
    assert ("DELETE", "/v2/orders") in deletes and ("DELETE", "/v2/positions") in deletes
    assert res["closed"] == ["AAPL"] and res["errors"] == []


# -- ccxt -------------------------------------------------------------------------------------------------
def test_ccxt_sandbox_unless_live_and_refuses_exchanges_without_testnet():
    ex = FakeExchange()
    assert CCXTBroker({}, exchange=ex).mode == "paper" and ex.isSandboxModeEnabled is True
    ex_live = FakeExchange()
    assert CCXTBroker(LIVE, exchange=ex_live).mode == "live" and ex_live.isSandboxModeEnabled is False
    with pytest.raises(BrokerError, match="no test network"):
        CCXTBroker({}, exchange=FakeExchange(sandbox=False))
    CCXTBroker(LIVE, exchange=FakeExchange(sandbox=False))   # live needs no sandbox


def test_ccxt_entry_then_exchange_stop_and_refusals():
    ex = FakeExchange()
    b = CCXTBroker({}, exchange=ex)
    o = b.place_order("BTC-USD", "buy", 0.5, type="limit", limit_price=100.5, stop_loss=95, take_profit=110)
    assert o["status"] == "filled" and o["symbol"] == "BTC/USDT"
    assert ex.orders[0][:3] == ("BTC/USDT", "limit", "buy") and ex.orders[0][5] == {"timeInForce": "IOC"}
    assert ex.orders[1][2] == "sell" and ex.orders[1][5] == {"stopLossPrice": 95.0}
    with pytest.raises(BrokerError, match="Short selling"):
        b.place_order("BTC/USDT", "sell", 1, stop_loss=110)
    with pytest.raises(BrokerError, match="stop-loss"):
        b.place_order("BTC/USDT", "buy", 1)
    with pytest.raises(BrokerError, match="not a crypto pair"):
        b.quote("AAPL")
    nostop = FakeExchange(stop_ok=False)
    with pytest.raises(BrokerError, match="cannot hold a stop-loss"):
        CCXTBroker({}, exchange=nostop).place_order("BTC/USDT", "buy", 1, stop_loss=95)
    assert nostop.orders == []   # refused before buying


def test_ccxt_stop_refused_sells_back_immediately():
    ex = FakeExchange()
    ex.stop_ok = False
    with pytest.raises(BrokerError, match="sold again"):
        CCXTBroker({}, exchange=ex).place_order("BTC/USDT", "buy", 1, stop_loss=95)
    assert [o[2] for o in ex.orders] == ["buy", "sell"]


def test_ccxt_kill_switch():
    ex = FakeExchange(holdings={"BTC": 2.0})
    res = CCXTBroker({}, exchange=ex).close_all()
    assert ex.cancelled == ["open-1"] and res["closed"] == ["BTC/USDT"] and ex.orders[-1][:4] == ("BTC/USDT", "market", "sell", 2.0)


# -- IBKR -------------------------------------------------------------------------------------------------
def test_ibkr_needs_ib_insync(monkeypatch):
    monkeypatch.setitem(sys.modules, "ib_insync", None)   # import fails
    with pytest.raises(BrokerError, match="ib_insync"):
        IBKRBroker({})


def test_ibkr_paper_session_on_real_account_disconnects():
    class FakeIB:
        disconnected = False

        def __init__(self, accounts):
            self.accounts = accounts

        def managedAccounts(self):
            return self.accounts

        def disconnect(self):
            self.disconnected = True

    real = FakeIB(["U1234567"])
    with pytest.raises(BrokerError, match="REAL-money"):
        IBKRBroker({}, ib=real)
    assert real.disconnected
    assert IBKRBroker({}, ib=FakeIB(["DU1234567"])).mode == "paper"


# -- limits and tokens ------------------------------------------------------------------------------------
def test_risk_limits_from_env_only_tighten():
    lim = RiskLimits.from_env({"RISK_PER_TRADE_PCT": "5", "MAX_POSITION_PCT": "4", "MAX_OPEN_POSITIONS": "50",
                               "MAX_DAILY_LOSS_PCT": "2", "MAX_ORDER_VALUE": "500", "MAX_DAILY_LOSS_VALUE": "abc"})
    assert lim.risk_per_trade_pct == 1.0 and lim.max_position_pct == 4 and lim.max_open_positions == 5
    assert lim.max_daily_loss_pct == 2 and lim.max_order_value == 500 and lim.max_daily_loss_value is None


def test_confirm_tokens_single_use_and_expire():
    t = [0.0]
    c = ConfirmTokens(ttl=60, clock=lambda: t[0])
    tok = c.issue({"symbol": "A"})
    assert c.consume(tok) == {"symbol": "A"} and c.consume(tok) is None and c.consume(None) is None
    tok = c.issue({"symbol": "A"})
    t[0] = 61
    assert c.consume(tok) is None


# -- API: one risk path for every broker ---------------------------------------------------------------------
def _opp(symbol, price, **kw):
    return {"symbol": symbol, "name": symbol, "direction": "long", "qualified": True, "entry": price, "price": price,
            "stop": price * 0.95, "target": price * 1.10, "hold_days": 5,
            "expires_at": "2099-01-01T00:00:00+00:00", **kw}


def _app(tmp_path, broker_factory=None, token=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    settings = Settings(db_path=tmp_path / "t.db", static_dir=None, api_token=token, autostart_live=False,
                        precompute=False)
    prov = FakeProvider()
    return create_app(settings, provider_factory=lambda n, e: prov, config={}, broker_factory=broker_factory)


def _with_broker(kind, tmp_path, live=False, n_positions=0, day_loss=0.0):
    """(client, symbol, sent_orders) for a real adapter on a fake transport."""
    env = {**KEYS, **(LIVE if live else {})}
    if kind == "alpaca":
        pos = [{"symbol": f"P{i}", "qty": "1", "avg_entry_price": "10", "current_price": "10", "side": "long",
                "unrealized_pl": "0"} for i in range(n_positions)]
        s = FakeAlpacaSession(positions=pos, last_equity=10_000 - day_loss)
        app = _app(tmp_path, lambda: AlpacaBroker(env, session=s), token="t" if live else None)
        return app, "AAA", s.orders_sent
    if kind == "ccxt":
        ex = FakeExchange(holdings={f"C{i}": 1.0 for i in range(n_positions)})
        if day_loss:
            day = str(pd.Timestamp.now(tz="UTC").date())
            (tmp_path / "broker_day.json").write_text(json.dumps({"ccxt:paper": {"day": day, "equity": 10_000 + n_positions * 100 - day_loss}}))
        app = _app(tmp_path, lambda: CCXTBroker(env, exchange=ex))
        return app, "BTC/USDT", lambda: ex.orders
    app = _app(tmp_path)   # default: BROKER unset -> paper
    st = app.state
    for i in range(n_positions):
        st.paper.open(f"P{i}", "opportunity", "long", 10.0, 9.0, None, "2026-10-20T00:00:00+00:00", qty=1)
    if day_loss:
        st.paper.history.append({"exit_time": pd.Timestamp.now(tz="UTC").isoformat(), "pnl": day_loss})
    return app, "AAA", lambda: [p for p in st.paper.positions.values() if p.symbol in ("AAA", "BTC/USDT")]


def _set_idea(client, symbol, **kw):
    st = client.app.state
    b = st.broker
    price = b.quote(symbol) or st.market.quote(symbol)["price"]
    st.precompute.put("opportunities", {"items": [_opp(symbol, price, **kw)]})
    return price


@pytest.mark.parametrize("kind", ["paper", "alpaca", "ccxt"])
def test_full_flow_preview_place_close(kind, tmp_path):
    app, sym, sent = _with_broker(kind, tmp_path)
    with TestClient(app) as c:
        status = c.get("/api/broker/status").json()
        assert status["broker"] == kind and status["mode"] == "paper" and status["connected"] is True
        _set_idea(c, sym)
        prev = c.post("/api/orders/preview", json={"symbol": sym, "side": "long"}).json()
        assert prev["mode"] == "paper" and prev["confirm_token"] and prev["plan"]["risk_pct_of_equity"] <= 1.0001
        assert c.post("/api/orders", json={"symbol": sym, "side": "long"}).status_code == 400   # token required
        r = c.post("/api/orders", json={"symbol": sym, "side": "long", "confirm_token": prev["confirm_token"]})
        assert r.status_code == 200 and r.json()["placed"] is True and len(sent()) >= 1
        again = c.post("/api/orders", json={"symbol": sym, "side": "long", "confirm_token": prev["confirm_token"]})
        assert again.status_code == 400 and "expired" in again.json()["detail"]   # single use
        killed = c.post("/api/orders/close-all").json()
        assert killed["halted"] is True
        paused = c.post("/api/orders/preview", json={"symbol": sym, "side": "long"})
        assert paused.status_code == 400 and "paused" in paused.json()["detail"]
        assert c.post("/api/paper/orders", json={"symbol": sym, "side": "long", "preview": True}).status_code == 400
        c.post("/api/orders/resume")
        assert c.get("/api/broker/status").json()["halted"] is None


@pytest.mark.parametrize("kind", ["paper", "alpaca", "ccxt"])
@pytest.mark.parametrize("scenario,msg", [("expired", "expired"), ("drift", "moved"), ("positions", "at most 5"),
                                          ("daily_loss", "Daily loss"), ("past_stop", "past the stop")])
def test_risk_rejections_apply_to_every_broker(kind, scenario, msg, tmp_path):
    app, sym, sent = _with_broker(kind, tmp_path, n_positions=5 if scenario == "positions" else 0,
                                  day_loss=-400.0 if scenario == "daily_loss" else 0.0)
    with TestClient(app) as c:
        price = _set_idea(c, sym)
        if scenario == "expired":
            _set_idea(c, sym, expires_at="2020-01-01T00:00:00+00:00")
        elif scenario == "drift":
            _set_idea(c, sym, entry=price * 1.05)
        elif scenario == "past_stop":
            _set_idea(c, sym, stop=price * 1.001, entry=price)
        r = c.post("/api/orders/preview", json={"symbol": sym, "side": "long"})
        assert r.status_code == 400 and msg in r.json()["detail"], r.json()
        assert c.post("/api/orders", json={"symbol": sym, "side": "long", "confirm_token": "forged-token"}).status_code == 400
        assert len(sent()) == 0   # nothing reached the broker


def test_live_requires_api_token_and_confirm_token(tmp_path):
    # Live without TRADEBOT_API_TOKEN: preview allowed, placing refused.
    s = FakeAlpacaSession()
    app = _app(tmp_path, lambda: AlpacaBroker({**KEYS, **LIVE}, session=s), token=None)
    with TestClient(app) as c:
        _set_idea(c, "AAA")
        prev = c.post("/api/orders/preview", json={"symbol": "AAA", "side": "long"}).json()
        assert prev["mode"] == "live" and prev["can_place"] is False
        r = c.post("/api/orders", json={"symbol": "AAA", "side": "long", "confirm_token": prev["confirm_token"]})
        assert r.status_code == 403 and s.orders_sent() == []

    app, sym, sent = _with_broker("alpaca", tmp_path / "live", live=True)
    h = {"Authorization": "Bearer t"}
    with TestClient(app) as c:
        assert c.get("/api/broker/status", headers=h).json()["mode"] == "live"
        _set_idea(c, sym)
        assert c.post("/api/orders", json={"symbol": sym, "side": "long"}, headers=h).status_code == 400
        prev = c.post("/api/orders/preview", json={"symbol": sym, "side": "long"}, headers=h).json()
        wrong = c.post("/api/orders", json={"symbol": "BBB", "side": "long", "confirm_token": prev["confirm_token"]}, headers=h)
        assert wrong.status_code == 400 and sent() == []   # token bound to the previewed order, and now used up
        prev = c.post("/api/orders/preview", json={"symbol": sym, "side": "long"}, headers=h).json()
        ok = c.post("/api/orders", json={"symbol": sym, "side": "long", "confirm_token": prev["confirm_token"]}, headers=h)
        assert ok.status_code == 200 and len(sent()) == 1
        assert sent()[0][1] == "https://api.alpaca.markets/v2/orders"
        body = sent()[0][2]["json"]
        assert body["order_class"] == "bracket" and float(body["stop_loss"]["stop_price"]) < float(body["limit_price"])
        # The order the user confirmed: whole shares, at most 1% risk and 10% of the account.
        assert int(body["qty"]) == prev["plan"]["qty"] and prev["plan"]["value"] <= 1000.01
        # Sized on the worst-case fill (the limit), so the max loss shown is an upper bound and stays <= 1%.
        assert body["limit_price"] == pytest.approx(prev["plan"]["entry"], abs=0.01) and prev["plan"]["entry"] > 100
        worst = int(body["qty"]) * (body["limit_price"] - body["stop_loss"]["stop_price"])
        assert worst == pytest.approx(prev["plan"]["max_loss"], rel=1e-3) and worst <= 100.5


def test_paper_routes_stay_on_practice_account_whatever_the_broker(tmp_path):
    s = FakeAlpacaSession()
    app = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s))
    with TestClient(app) as c:
        px = c.app.state.market.quote("AAA")["price"]
        c.app.state.precompute.put("opportunities", {"items": [_opp("AAA", px)]})
        assert c.post("/api/paper/orders", json={"symbol": "AAA", "side": "long"}).json()["placed"] is True
        assert s.orders_sent() == [] and c.get("/api/paper").json()["positions"][0]["symbol"] == "AAA"


def test_broken_broker_config_reports_error_not_paper_fallback(tmp_path):
    def bad():
        raise BrokerError("Alpaca keys missing: add ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY to .env.")
    with TestClient(_app(tmp_path, bad)) as c:
        st = c.get("/api/broker/status").json()
        assert st["connected"] is False and "keys missing" in st["error"]
        assert c.post("/api/orders/preview", json={"symbol": "AAA", "side": "long"}).status_code == 503
        assert c.post("/api/orders/close-all").status_code == 503


def test_time_limit_closes_broker_positions(tmp_path):
    from tradebot.api.orders import manage_broker_exits

    s = FakeAlpacaSession(positions=[{"symbol": "AAA", "qty": "3", "avg_entry_price": "100", "current_price": "101",
                                      "side": "long", "unrealized_pl": "3"}])
    app = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s))
    with TestClient(app):
        st = app.state
        old = pd.Timestamp("2026-01-01", tz="UTC")
        st.journal.add({"id": "o-1", "broker": "alpaca", "mode": "paper", "symbol": "AAA", "side": "long", "qty": 3,
                        "entry": 100, "stop": 95, "target": 110, "opened_at": old.isoformat(),
                        "close_by": (old + pd.Timedelta(days=7)).isoformat(), "status": "open"})
        done = manage_broker_exits(st)
        assert [d["reason"] for d in done] == ["time limit"]
        assert ("DELETE", "https://paper-api.alpaca.markets/v2/positions/AAA") in [(m, u) for m, u, _ in s.calls]
        assert st.journal.all()[0]["status"] == "closed"
