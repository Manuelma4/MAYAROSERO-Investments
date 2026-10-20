"""Broker layer, offline: mocked HTTP for Alpaca, a fake ccxt exchange, a fake ib_insync client.

No network, no real order: every adapter gets a fake transport.
"""

import json
import math
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
TOKEN = "a" * 40   # a good-enough TRADEBOT_API_TOKEN


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("BROKER", "TRADING_MODE", "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "MAX_ORDER_VALUE", "RISK_PER_TRADE_PCT",
              "ALPACA_DATA_FEED", "TRADEBOT_ENV_FILE"):
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
    """Alpaca REST v2 in memory. ``close_fails``: DELETE /v2/positions/{sym} refused (e.g. market closed).
    ``stuck``: order ids whose cancel is never confirmed (stay pending_cancel)."""

    def __init__(self, price=100.0, equity=10_000.0, last_equity=10_000.0, positions=None, trade_age_s=1,
                 close_fails=False, stuck=(), protect_fails=False, close_all_errors=()):
        self.headers, self.calls = {}, []
        self.price, self.equity, self.last_equity = price, equity, last_equity
        self.pos = positions or []
        self.trade_age_s, self.close_fails, self.stuck, self.protect_fails = trade_age_s, close_fails, set(stuck), protect_fails
        self.close_all_errors = set(close_all_errors)
        self.n_posts = 0

    def request(self, method, url, timeout=None, **kw):
        self.calls.append((method, url, kw))
        path = url.split(".markets", 1)[1]
        if path == "/v2/account":
            return Resp({"equity": str(self.equity), "last_equity": str(self.last_equity), "cash": str(self.equity),
                         "buying_power": str(self.equity * 2), "currency": "USD", "status": "ACTIVE"})
        if path == "/v2/positions" and method == "GET":
            return Resp(self.pos)
        if path.startswith("/v2/positions/") and method == "GET":
            sym = path.rsplit("/", 1)[1]
            p = next((p for p in self.pos if p["symbol"] == sym), None)
            return Resp(p) if p else Resp({"message": "position does not exist"}, 404)
        if path.endswith("/trades/latest"):
            t = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=self.trade_age_s)).isoformat()
            return Resp({"trade": {"p": self.price, "t": t}})
        if path == "/v2/orders" and method == "POST":
            self.n_posts += 1
            body = kw.get("json") or {}
            if body.get("type") == "stop":
                return Resp({"message": "insufficient qty"}, 403) if self.protect_fails else Resp({"id": f"stop-{self.n_posts}", "status": "new"})
            return Resp({"id": "o-1", "status": "accepted", "legs": [{"id": "tp-1", "type": "limit"},
                                                                       {"id": "sl-1", "type": "stop"}]})
        if path.startswith("/v2/orders/") and method == "GET":
            oid = path.rsplit("/", 1)[1]
            return Resp({"id": oid, "status": "pending_cancel" if oid in self.stuck else "canceled",
                         "legs": [{"id": "tp-1"}, {"id": "sl-1"}] if oid == "o-1" else []})
        if path == "/v2/orders" and method == "GET":
            return Resp([{"id": "leg-1"}])
        if method == "DELETE" and path == "/v2/orders":
            return Resp([{"id": "a", "status": 200}])
        if method == "DELETE" and path == "/v2/positions":
            return Resp([{"symbol": p["symbol"], "status": 403 if p["symbol"] in self.close_all_errors else 200,
                          **({"body": {"message": "market closed"}} if p["symbol"] in self.close_all_errors else {})}
                         for p in self.pos])
        if method == "DELETE" and path.startswith("/v2/positions/"):
            if self.close_fails:
                return Resp({"message": "market is closed"}, 403)
            return Resp({"id": "close-1", "status": "accepted"})
        if method == "DELETE":
            return Resp(None, 204)
        return Resp({"message": "not found"}, 404)

    def orders_sent(self):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith("/v2/orders")]

    def paths(self, method):
        return [u.split(".markets")[1] for m, u, _ in self.calls if m == method]


class NetworkError(Exception):   # same name as ccxt's
    pass


class OrderNotFound(Exception):
    pass


class FakeExchange:
    """Spot exchange in memory: buys add (amount - fee) coins, market sells remove them, stop orders rest.
    ``buy_error``: raised by the buy (``buy_happens``: after it really filled). ``fetch_error``: fetch_order raises.
    ``sell_fails``: plain market sells refused."""

    def __init__(self, sandbox=True, price=100.0, usdt=10_000.0, holdings=None, stop_ok=True, fee=0.0,
                 buy_error=None, buy_happens=False, fetch_error=None, open_status=None, sell_fails=False):
        self.has = {"createStopLossOrder": stop_ok, "sandbox": sandbox}
        self._sandbox_ok, self.isSandboxModeEnabled = sandbox, False
        self.price, self.usdt, self.holdings = price, usdt, dict(holdings or {})
        self.orders, self.cancelled, self.stop_ok = [], [], True
        self.fee, self.buy_error, self.buy_happens, self.fetch_error = fee, buy_error, buy_happens, fetch_error
        self.open_status, self.sell_fails = open_status, sell_fails

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
        return f"{math.floor(qty * 1e4) / 1e4:.4f}"   # truncates, like ccxt's default

    def create_order(self, sym, type, side, amount, price=None, params=None):
        params = params or {}
        base = sym.split("/")[0]
        if "stopLossPrice" in params and not self.stop_ok:
            raise RuntimeError("stop refused")
        if side == "sell" and "stopLossPrice" not in params and self.sell_fails:
            raise RuntimeError("market closed")
        if side == "buy" and self.buy_error and not self.buy_happens:
            raise self.buy_error
        self.orders.append((sym, type, side, amount, price, params))
        if "stopLossPrice" not in params:
            self.holdings[base] = self.holdings.get(base, 0.0) + (amount - self.fee if side == "buy" else -amount)
        if side == "buy" and self.buy_error:
            raise self.buy_error
        if side == "buy" and self.open_status:
            return {"id": f"x{len(self.orders)}", "filled": 0, "status": self.open_status}
        return {"id": f"x{len(self.orders)}", "filled": amount, "status": "closed", "average": self.price}

    def fetch_order(self, oid, sym=None):
        if self.fetch_error:
            raise self.fetch_error
        return {"id": oid, "status": "closed", "filled": 0}

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
        app = _app(tmp_path, lambda: AlpacaBroker(env, session=s), token=TOKEN if live else None)
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
        killed = c.post("/api/orders/close-all", json={"confirm": True}).json()
        assert killed["halted"] is True
        paused = c.post("/api/orders/preview", json={"symbol": sym, "side": "long"})
        assert paused.status_code == 400 and "paused" in paused.json()["detail"]
        assert c.post("/api/paper/orders", json={"symbol": sym, "side": "long", "preview": True}).status_code == 400
        c.post("/api/orders/resume", json={"confirm": True})
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
    h = {"Authorization": f"Bearer {TOKEN}"}
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
        r = c.post("/api/orders/close-all", json={"confirm": True})
        assert r.status_code == 503 and "close your positions at the broker manually" in r.json()["detail"].lower()
        assert c.get("/api/broker/status").json()["halted"] is not None   # paused even though nothing could be closed


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


# == Broker safety fixes (review items 1-14) ===============================================================
def _pos(sym, qty, price=100.0, side="long"):
    return {"symbol": sym, "qty": str(qty), "avg_entry_price": str(price), "current_price": str(price), "side": side,
            "unrealized_pl": "0"}


def _entry(id_, sym, qty, legs=None, close_by="2026-01-08", **kw):
    old = pd.Timestamp("2026-01-01", tz="UTC")
    return {"id": id_, "broker": kw.pop("broker", "alpaca"), "mode": "paper", "symbol": sym, "side": "long", "qty": qty,
            "entry": 100, "stop": 95, "target": 110, "opened_at": old.isoformat(),
            "close_by": pd.Timestamp(close_by, tz="UTC").isoformat(), "status": "open", "legs": legs or [], **kw}


# 1. live token: no placeholder, no short token, constant-time comparison
@pytest.mark.parametrize("token,ok", [(None, False), ("change-me-to-a-long-random-string", False),
                                      ("short-token", False), ("x" * 31, False), (TOKEN, True)])
def test_live_needs_a_real_api_token(token, ok, tmp_path):
    from tradebot.api.settings import api_token_problem

    assert (api_token_problem(token) is None) is ok
    s = FakeAlpacaSession()
    app = _app(tmp_path, lambda: AlpacaBroker({**KEYS, **LIVE}, session=s), token=token)
    h = {"Authorization": f"Bearer {token}"} if token else {}
    with TestClient(app) as c:
        _set_idea(c, "AAA")
        prev = c.post("/api/orders/preview", json={"symbol": "AAA", "side": "long"}, headers=h).json()
        assert prev["can_place"] is ok
        r = c.post("/api/orders", json={"symbol": "AAA", "side": "long", "confirm_token": prev["confirm_token"]}, headers=h)
        assert (r.status_code == 200) is ok and len(s.orders_sent()) == (1 if ok else 0)
        if not ok:
            assert r.status_code == 403


def test_api_token_checked_on_http_and_websocket(tmp_path):
    from starlette.websockets import WebSocketDisconnect

    with TestClient(_app(tmp_path, token=TOKEN)) as c:
        assert c.get("/api/broker/status").status_code == 401
        assert c.get("/api/broker/status", headers={"Authorization": "Bearer " + "b" * 40}).status_code == 401
        assert c.get("/api/broker/status", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/events?token=wrong") as ws:
                ws.receive_json()


# 2. close only what the app opened, cancel only its own legs; no idea on a symbol already held
def test_alpaca_exit_closes_only_the_journaled_qty_and_own_legs(tmp_path):
    from tradebot.api.orders import manage_broker_exits

    s = FakeAlpacaSession(positions=[_pos("AAA", 10, 101)])   # 7 shares were bought outside the app
    app = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s, sleep=lambda _: None))
    with TestClient(app):
        st = app.state
        st.journal.add(_entry("o-1", "AAA", 3, legs=["o-1", "tp-1", "sl-1"]))
        assert [d["reason"] for d in manage_broker_exits(st)] == ["time limit"]
        close = [(u, kw) for m, u, kw in s.calls if m == "DELETE" and "/v2/positions/AAA" in u]
        assert close and close[0][1]["params"] == {"qty": "3"}
        assert sorted(s.paths("DELETE")) == ["/v2/orders/o-1", "/v2/orders/sl-1", "/v2/orders/tp-1", "/v2/positions/AAA"]
        assert not any(u.endswith("/v2/orders") for m, u, _ in s.calls if m == "GET")   # no "all orders of AAA"
        assert st.journal.all()[0]["status"] == "closed"


def test_place_journals_the_bracket_legs(tmp_path):
    app, sym, sent = _with_broker("alpaca", tmp_path)
    with TestClient(app) as c:
        _set_idea(c, sym)
        prev = c.post("/api/orders/preview", json={"symbol": sym, "side": "long"}).json()
        c.post("/api/orders", json={"symbol": sym, "side": "long", "confirm_token": prev["confirm_token"]})
        e = c.app.state.journal.all()[0]
        assert e["legs"] == ["o-1", "tp-1", "sl-1"] and e["stop_order_id"] == "sl-1"


def test_ccxt_exit_sells_only_the_journaled_qty():
    ex = FakeExchange(holdings={"BTC": 5.0})
    CCXTBroker({}, exchange=ex).close_position("BTC/USDT", qty=1.0, order_ids=["s1"], stop=95)
    assert ex.cancelled == ["s1"] and ex.orders[-1][:4] == ("BTC/USDT", "market", "sell", 1.0)
    assert ex.holdings["BTC"] == 4.0


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeIB:
    """ib_insync.IB stand-in: records the thread of every call."""

    def __init__(self, accounts=("DU1234567",), positions=(), trades=()):
        self.accounts, self.disconnected, self.threads = list(accounts), False, []
        self._positions, self._trades, self.cancelled, self.placed = list(positions), list(trades), [], []

    def _t(self):
        import threading

        self.threads.append(threading.current_thread().name)

    def managedAccounts(self):
        self._t()
        return self.accounts

    def disconnect(self):
        self.disconnected = True

    def positions(self):
        self._t()
        return self._positions

    def openTrades(self):
        self._t()
        return self._trades

    def cancelOrder(self, order):
        self.cancelled.append(order.orderId)

    def placeOrder(self, contract, order):
        self._t()
        self.placed.append(order)
        return _Obj(order=_Obj(orderId=100 + len(self.placed)), orderStatus=_Obj(status="Submitted"))


@pytest.fixture
def fake_ib_insync(monkeypatch):
    import types

    mod = types.ModuleType("ib_insync")
    mod.MarketOrder = lambda action, qty: _Obj(kind="MKT", action=action, totalQuantity=qty)
    mod.StopOrder = lambda action, qty, stop: _Obj(kind="STP", action=action, totalQuantity=qty, auxPrice=stop)
    mod.Stock = lambda *a: _Obj(symbol=a[0])
    monkeypatch.setitem(sys.modules, "ib_insync", mod)
    return mod


def test_ibkr_exit_closes_only_journaled_qty_and_own_legs_on_one_thread(fake_ib_insync):
    aaa = _Obj(symbol="AAA")
    trades = [_Obj(contract=aaa, order=_Obj(orderId=i)) for i in (1, 2, 3, 9)]   # 9: the owner's own order
    ib = FakeIB(positions=[_Obj(contract=aaa, position=10, avgCost=100.0)], trades=trades)
    b = IBKRBroker({}, ib=ib)
    out = b.close_position("AAA", qty=3, order_ids=["1", "2", "3"], stop=95)
    assert ib.cancelled == [1, 2, 3] and ib.placed[-1].totalQuantity == 3 and ib.placed[-1].action == "SELL"
    assert out["qty"] == 3
    assert ib.threads and all(t.startswith("ibkr") for t in ib.threads)   # ib_insync only ever on its own thread


@pytest.mark.parametrize("kind,held,idea", [("alpaca", "AAA", "AAA"), ("ccxt", "BTC", "BTC-USD")])
def test_new_idea_refused_on_a_symbol_already_held(kind, held, idea, tmp_path):
    if kind == "alpaca":
        s = FakeAlpacaSession(positions=[_pos("AAA", 2, 100, side="short")])
        app, sent = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s)), s.orders_sent
    else:
        ex = FakeExchange(holdings={"BTC": 0.5})
        app, sent = _app(tmp_path, lambda: CCXTBroker({}, exchange=ex)), lambda: ex.orders
    with TestClient(app) as c:
        _set_idea(c, idea)
        r = c.post("/api/orders/preview", json={"symbol": idea, "side": "long"})
        assert r.status_code == 400 and "already holds" in r.json()["detail"] and sent() == []


# 3. a failed close never leaves the position without a stop
def test_alpaca_failed_close_replaces_the_stop(tmp_path):
    from tradebot.api.orders import manage_broker_exits

    s = FakeAlpacaSession(positions=[_pos("AAA", 3, 101)], close_fails=True)
    app = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s, sleep=lambda _: None))
    with TestClient(app):
        st = app.state
        st.journal.add(_entry("o-1", "AAA", 3, legs=["o-1", "tp-1", "sl-1"]))
        assert manage_broker_exits(st) == []
        stop = s.orders_sent()[-1][2]["json"]
        assert stop["type"] == "stop" and stop["side"] == "sell" and stop["qty"] == "3" and stop["stop_price"] == 95
        assert stop["time_in_force"] == "gtc"
        e = st.journal.all()[0]
        assert e["status"] == "open" and e["legs"] == ["stop-1"] and "placed again" in e["last_error"]


def test_alpaca_unconfirmed_cancel_does_not_close():
    s = FakeAlpacaSession(positions=[_pos("AAA", 3)], stuck={"sl-1"}, protect_fails=True)
    b = AlpacaBroker(KEYS, session=s, cancel_wait=0, sleep=lambda _: None)
    with pytest.raises(BrokerError, match="not confirmed") as ei:
        b.close_position("AAA", qty=3, order_ids=["o-1", "tp-1", "sl-1"], stop=95)
    assert "/v2/positions/AAA" not in s.paths("DELETE") and ei.value.legs == ["o-1", "tp-1", "sl-1"]


def test_ccxt_failed_sale_replaces_the_stop():
    ex = FakeExchange(holdings={"BTC": 1.0}, sell_fails=True)
    with pytest.raises(BrokerError, match="placed again") as ei:
        CCXTBroker({}, exchange=ex).close_position("BTC/USDT", qty=1.0, order_ids=["s1"], stop=95)
    assert ex.cancelled == ["s1"] and ex.orders[-1][5] == {"stopLossPrice": 95.0} and ei.value.legs == ["x1"]


# 4. ccxt entry: fee in the coin, network errors, unknown order status, journal whatever happens
def test_ccxt_stop_sized_on_coins_really_received():
    ex = FakeExchange(fee=0.001)
    o = CCXTBroker({}, exchange=ex).place_order("BTC/USDT", "buy", 1.0, type="limit", limit_price=100, stop_loss=95)
    assert ex.orders[1][3] == pytest.approx(0.999) and o["qty"] == pytest.approx(0.999) and o["legs"] == ["x2"]


def test_ccxt_network_error_after_fill_is_protected_and_journaled(tmp_path):
    ex = FakeExchange(buy_error=NetworkError("timeout"), buy_happens=True)
    app = _app(tmp_path, lambda: CCXTBroker({}, exchange=ex))
    with TestClient(app) as c:
        _set_idea(c, "BTC/USDT")
        prev = c.post("/api/orders/preview", json={"symbol": "BTC/USDT", "side": "long"}).json()
        r = c.post("/api/orders", json={"symbol": "BTC/USDT", "side": "long", "confirm_token": prev["confirm_token"]})
        assert r.status_code == 200 and "balance" in r.json()["order"]["status"]
        assert ex.orders[-1][5] == {"stopLossPrice": pytest.approx(prev["plan"]["stop"])}   # stop placed on what arrived
        assert c.app.state.journal.all()[0]["qty"] == pytest.approx(ex.orders[-1][3])


def test_ccxt_network_error_without_fill_is_a_clear_400(tmp_path):
    ex = FakeExchange(buy_error=NetworkError("timeout"))
    app = _app(tmp_path, lambda: CCXTBroker({}, exchange=ex))
    with TestClient(app) as c:
        _set_idea(c, "BTC/USDT")
        prev = c.post("/api/orders/preview", json={"symbol": "BTC/USDT", "side": "long"}).json()
        r = c.post("/api/orders", json={"symbol": "BTC/USDT", "side": "long", "confirm_token": prev["confirm_token"]})
        assert r.status_code == 400 and "Nothing was bought" in r.json()["detail"] and ex.orders == []
        assert c.app.state.journal.all() == []


def test_ccxt_unknown_order_status_checks_the_balance():
    ex = FakeExchange(open_status="open", fetch_error=NetworkError("timeout"))   # the buy did fill
    o = CCXTBroker({}, exchange=ex).place_order("BTC/USDT", "buy", 0.5, type="limit", limit_price=100, stop_loss=95)
    assert o["qty"] == 0.5 and ex.orders[-1][5] == {"stopLossPrice": 95.0}


def test_ccxt_raw_exceptions_become_broker_errors():
    ex = FakeExchange()
    ex.fetch_balance = lambda: (_ for _ in ()).throw(NetworkError("down"))
    b = CCXTBroker({}, exchange=ex)
    for call in (b.account, b.positions, b.close_all, lambda: b.place_order("BTC/USDT", "buy", 1, stop_loss=95)):
        with pytest.raises(BrokerError):
            call()
    assert ex.orders == []


def test_unprotected_fill_is_journaled_and_sold_by_the_app(tmp_path):
    from tradebot.api.orders import manage_broker_exits

    ex = FakeExchange(sell_fails=True)
    ex.stop_ok = False   # stop refused AND emergency sale refused
    app = _app(tmp_path, lambda: CCXTBroker({}, exchange=ex))
    with TestClient(app) as c:
        _set_idea(c, "BTC/USDT")
        prev = c.post("/api/orders/preview", json={"symbol": "BTC/USDT", "side": "long"}).json()
        r = c.post("/api/orders", json={"symbol": "BTC/USDT", "side": "long", "confirm_token": prev["confirm_token"]})
        assert r.status_code == 502 and "DANGER" in r.json()["detail"]
        e = c.app.state.journal.all()[0]
        assert e["status"] == "open" and e["unprotected"] is True and e["qty"] > 0
        ex.sell_fails = False   # the exchange accepts sales again: the background loop sells it
        assert [d["reason"] for d in manage_broker_exits(c.app.state)] == ["no stop-loss at the broker"]
        assert ex.orders[-1][2] == "sell" and c.app.state.journal.all()[0]["status"] == "closed"


def test_stop_refused_sold_back_is_journaled_closed(tmp_path):
    ex = FakeExchange()
    ex.stop_ok = False
    app = _app(tmp_path, lambda: CCXTBroker({}, exchange=ex))
    with TestClient(app) as c:
        _set_idea(c, "BTC/USDT")
        prev = c.post("/api/orders/preview", json={"symbol": "BTC/USDT", "side": "long"}).json()
        r = c.post("/api/orders", json={"symbol": "BTC/USDT", "side": "long", "confirm_token": prev["confirm_token"]})
        assert r.status_code == 400 and "sold again" in r.json()["detail"]
        assert c.app.state.journal.all()[0]["status"] == "closed"


def test_unexpected_adapter_error_is_502_not_500(tmp_path):
    s = FakeAlpacaSession()
    b = AlpacaBroker(KEYS, session=s)
    b.place_order = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
    app = _app(tmp_path, lambda: b)
    with TestClient(app) as c:
        _set_idea(c, "AAA")
        prev = c.post("/api/orders/preview", json={"symbol": "AAA", "side": "long"}).json()
        r = c.post("/api/orders", json={"symbol": "AAA", "side": "long", "confirm_token": prev["confirm_token"]})
        assert r.status_code == 502 and "check your account" in r.json()["detail"]


# 5 + 12. kill switch: pause first (even disconnected); live pause survives midnight
def test_halt_persists_overnight_only_in_live(tmp_path):
    from tradebot.trading.guard import Halt

    h = Halt(tmp_path / "h.json")
    today, tomorrow = pd.Timestamp("2026-10-20 23:00", tz="UTC"), pd.Timestamp("2026-10-21 09:00", tz="UTC")
    h.set("x", now=today)
    assert h.active(today) and h.active(tomorrow) is None
    h.set("x", now=today, persistent=True)
    assert h.active(tomorrow)["persistent"] is True
    h.clear()
    assert h.active(tomorrow) is None


def test_live_kill_switch_pause_is_persistent(tmp_path):
    app, _sym, _ = _with_broker("alpaca", tmp_path, live=True)
    h = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as c:
        assert c.post("/api/orders/close-all", json={"confirm": True}, headers=h).json()["halted"] is True
        assert c.app.state.halt.active(pd.Timestamp("2099-01-01", tz="UTC"))["persistent"] is True


# 6. close-all only marks what was really closed
def test_close_all_marks_only_closed_entries(tmp_path):
    s = FakeAlpacaSession(positions=[_pos("AAA", 3), _pos("BBB", 2)], close_all_errors={"BBB"})
    app = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s))
    with TestClient(app) as c:
        st = c.app.state
        st.journal.add(_entry("a", "AAA", 3))
        st.journal.add(_entry("b", "BBB", 2))
        res = c.post("/api/orders/close-all", json={"confirm": True}).json()
        assert res["closed"] == ["AAA"] and "BBB" in res["errors"][0]
        assert {e["symbol"]: e["status"] for e in st.journal.all()} == {"AAA": "closed", "BBB": "open"}


# 7. no real order on a stale price; Alpaca quotes use the configured feed
def test_stale_price_refused_for_real_brokers(tmp_path):
    s = FakeAlpacaSession(trade_age_s=3600)   # last trade an hour old (market closed)
    app = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s))
    with TestClient(app) as c:
        px = c.app.state.market.quote("AAA")["price"]   # the app's daily-bar price: not fresh
        c.app.state.precompute.put("opportunities", {"items": [_opp("AAA", px)]})
        r = c.post("/api/orders/preview", json={"symbol": "AAA", "side": "long"})
        assert r.status_code == 400 and "less than a minute old" in r.json()["detail"]
        # the practice account keeps using the app's market data
        assert c.post("/api/paper/orders", json={"symbol": "AAA", "side": "long", "preview": True}).status_code == 200


def test_alpaca_quote_uses_data_feed():
    s = FakeAlpacaSession()
    AlpacaBroker(KEYS, session=s).quote("AAA")
    assert s.calls[-1][2]["params"] == {"feed": "iex"}
    s2 = FakeAlpacaSession()
    assert AlpacaBroker({**KEYS, "ALPACA_DATA_FEED": "sip"}, session=s2).quote("AAA") == 100.0
    assert s2.calls[-1][2]["params"] == {"feed": "sip"}


def test_market_quote_age_rule(tmp_path):
    from tradebot.api.orders import _quote_age

    now = pd.Timestamp.now(tz="UTC")
    assert _quote_age({"time": (now - pd.Timedelta(seconds=5)).isoformat()}) < pd.Timedelta(seconds=60)
    assert _quote_age({"time": "2026-01-01"}) > pd.Timedelta(seconds=60) and _quote_age({}) is None


# 8. daily-loss baseline recorded by the background loop
def test_day_baseline_recorded_by_background_loop(tmp_path):
    from tradebot.api.orders import manage_broker_exits

    ex = FakeExchange(usdt=5_000)
    app = _app(tmp_path, lambda: CCXTBroker({}, exchange=ex))
    with TestClient(app):
        manage_broker_exits(app.state)
        rec = json.loads((tmp_path / "broker_day.json").read_text())["ccxt:paper"]
        assert rec["equity"] == 5_000 and rec["day"] == str(pd.Timestamp.now(tz="UTC").date())


# 9. IBKR: real money refused until the adapter is proven
def test_ibkr_live_refused():
    ib = FakeIB(accounts=["U1234567"])
    with pytest.raises(BrokerError, match="switched off"):
        IBKRBroker(LIVE, ib=ib)
    assert ib.threads == []   # refused before any call


# 10. one bad entry does not stop the others
def test_exit_pass_survives_a_bad_entry(tmp_path):
    from tradebot.api.orders import manage_broker_exits

    s = FakeAlpacaSession(positions=[_pos("AAA", 3), _pos("BBB", 2)])
    app = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s, sleep=lambda _: None))
    with TestClient(app):
        st = app.state
        st.journal.add({**_entry("a", "AAA", 3), "close_by": "not a date"})
        st.journal.add(_entry("b", "BBB", 2, legs=["b"]))
        assert [d["symbol"] for d in manage_broker_exits(st)] == ["BBB"]


# 11. .env loading
def test_dotenv_parsing_and_location(tmp_path, monkeypatch):
    from tradebot import cli

    for k in ("A1", "A2", "A3", "A4", "TRADING_MODE"):
        monkeypatch.delenv(k, raising=False)
    f = tmp_path / "x.env"
    f.write_text('A1="abc#def"  # comment\nA2=plain   # comment\nexport A3=\'q # in quotes\'\nA4=#nothing\n# c\n')
    assert cli.load_dotenv(f) == 4
    import os

    assert (os.environ["A1"], os.environ["A2"], os.environ["A3"], os.environ["A4"]) == ("abc#def", "plain", "q # in quotes", "")
    monkeypatch.chdir(tmp_path)   # the working directory does not matter
    root = cli.repo_root()
    assert root and (root / "pyproject.toml").is_file() and cli.default_env_file() == root / ".env"
    monkeypatch.setenv("TRADEBOT_ENV_FILE", str(f))
    assert cli.default_env_file() == f


def test_trading_mode_origin_is_logged(tmp_path, monkeypatch):
    from tradebot import cli

    monkeypatch.delenv("TRADING_MODE", raising=False)
    assert "not set anywhere, so paper" in cli.trading_mode_origin(None, set())
    monkeypatch.setenv("TRADING_MODE", "live")
    assert cli.trading_mode_origin(tmp_path / ".env", set()) == f"TRADING_MODE=LIVE ({tmp_path / '.env'}); BROKER=paper"
    assert "the shell environment" in cli.trading_mode_origin(None, {"TRADING_MODE"})
    with pytest.raises(SystemExit, match="does not exist"):
        cli.main(["serve", "--env-file", str(tmp_path / "missing.env")])


# 13. no euro-named caps applied in dollars
def test_eur_aliases_no_longer_read():
    lim = RiskLimits.from_env({"MAX_ORDER_EUR": "500", "MAX_DAILY_LOSS_EUR": "100"})
    assert lim.max_order_value is None and lim.max_daily_loss_value is None


# 14. kill switch / resume need a JSON {"confirm": true}
def test_close_all_and_resume_need_json_confirm(tmp_path):
    s = FakeAlpacaSession()
    app = _app(tmp_path, lambda: AlpacaBroker(KEYS, session=s))
    with TestClient(app) as c:
        for path in ("/api/orders/close-all", "/api/orders/resume"):
            assert c.post(path).status_code == 422
            assert c.post(path, data={"confirm": "true"}).status_code in (415, 422)   # an HTML form
            assert c.post(path, content='{"confirm": true}', headers={"content-type": "text/plain"}).status_code in (415, 422)
            assert c.post(path, json={"confirm": False}).status_code == 400
        assert c.app.state.halt.active() is None and "DELETE" not in [m for m, _, _ in s.calls]
        assert c.post("/api/orders/close-all", json={"confirm": True}).json()["halted"] is True
