"""Paid real-time data adapters (Polygon, Alpaca, Finnhub): offline, with mocked HTTP payloads
shaped like each vendor's documented responses."""

import json

import pandas as pd
import pytest

from tradebot.api.market import MarketData
from tradebot.data import get_provider
from tradebot.data import paid
from tradebot.data.paid import (AlpacaProvider, FallbackProvider, FinnhubProvider, MissingCredentials,
                                PolygonProvider, RateLimited, build_paid_provider,
                                describe_stock_source, stock_provider_from_env, supports,
                                vendor_symbol)
from tradebot.data.providers import OHLCV, YahooProvider
from tradebot.data.streaming import (AlpacaStream, FinnhubStream, PolygonStream,
                                     stream_from_env)


# --- fakes ---------------------------------------------------------------------------------

class FakeResp:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self.payload is None:
            raise ValueError("no json")
        return self.payload


class FakeSession:
    """Routes by URL substring; a list value is consumed one response per call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        for key, resp in self.routes.items():
            if key in url:
                if isinstance(resp, list):
                    return resp.pop(0) if len(resp) > 1 else resp[0]
                return resp
        return FakeResp({"error": "not found"}, status=404)


class FakeYahoo(YahooProvider):
    def __init__(self):
        self.calls = []

    def _df(self, symbol, n=5):
        idx = pd.date_range("2024-03-04", periods=n, freq="D", tz="UTC", name="time")
        return pd.DataFrame({c: [1.0] * n for c in OHLCV}, index=idx)

    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        self.calls.append(("history", symbol, timeframe))
        return self._df(symbol)

    def history_many(self, symbols, timeframe="1d", start=None, limit=None):
        self.calls.append(("history_many", tuple(symbols), timeframe))
        return {s: self._df(s) for s in symbols}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(paid.time, "sleep", lambda s: None)


def ms(ts):
    return int(pd.Timestamp(ts).timestamp() * 1000)


def ny(ts):
    return pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC")


# --- symbols -------------------------------------------------------------------------------

def test_symbol_coverage_and_mapping():
    assert supports("AAPL") and supports("BRK-B")
    for s in ("^GSPC", "MC.PA", "VOD.L", "BTC-USD", "EURUSD=X", "BTC/USDT", ""):
        assert not supports(s)
    assert vendor_symbol("BRK-B") == "BRK.B"


# --- Polygon -------------------------------------------------------------------------------

def polygon_bar(ts, o, c, v=1000):
    return {"v": v, "vw": (o + c) / 2, "o": o, "c": c, "h": max(o, c) + 1, "l": min(o, c) - 1,
            "t": ms(ts), "n": 12}


def test_polygon_intraday_parsing_session_filter_and_pagination():
    page1 = {"ticker": "AAPL", "queryCount": 2, "resultsCount": 2, "adjusted": True, "status": "OK",
             "request_id": "a1", "count": 2,
             "results": [polygon_bar(ny("2024-03-12 08:00"), 170, 171),     # pre-market: dropped
                         polygon_bar(ny("2024-03-12 09:30"), 172, 173)],
             "next_url": "https://api.polygon.io/v2/aggs/ticker/AAPL/range/5/minute/x/y?cursor=abc"}
    page2 = {"ticker": "AAPL", "status": "OK", "request_id": "a2", "resultsCount": 2,
             "results": [polygon_bar(ny("2024-03-12 09:35"), 173, 174),
                         polygon_bar(ny("2024-03-12 16:00"), 174, 175)]}       # after-hours: dropped
    sess = FakeSession({"cursor=abc": FakeResp(page2), "/v2/aggs/ticker/AAPL/range/5/minute/": FakeResp(page1)})
    prov = PolygonProvider("pk", session=sess)
    df = prov.history("AAPL", "5m", start="2024-03-12", end="2024-03-13")
    assert list(df.columns) == OHLCV and str(df.index.tz) == "UTC"
    assert list(df.index) == [ny("2024-03-12 09:30"), ny("2024-03-12 09:35")]
    assert df["close"].tolist() == [173.0, 174.0] and df["volume"].iloc[0] == 1000.0
    assert sess.calls[0]["headers"]["Authorization"] == "Bearer pk"
    assert sess.calls[0]["params"]["adjusted"] == "true"
    assert len(sess.calls) == 2  # followed next_url


def test_polygon_daily_alignment_and_live_snapshot():
    aggs = {"ticker": "AAPL", "status": "OK", "resultsCount": 2,
            "results": [polygon_bar(ny("2024-03-11"), 170, 171, 5e7), polygon_bar(ny("2024-03-12"), 171, 172, 6e7)]}
    snap = {"status": "OK", "count": 1, "tickers": [{
        "ticker": "AAPL", "todaysChange": 1.5, "todaysChangePerc": 0.87,
        "updated": int(ny("2024-03-13 11:00").value),
        "day": {"o": 172.5, "h": 174, "l": 172, "c": 173.5, "v": 2.1e7, "vw": 173.1},
        "lastTrade": {"p": 174.5, "s": 100, "t": int(ny("2024-03-13 11:00").value), "x": 4},
        "prevDay": {"o": 171, "h": 173, "l": 170, "c": 172, "v": 6e7}}]}
    sess = FakeSession({"/v2/aggs/": FakeResp(aggs), "/v2/snapshot/": FakeResp(snap)})
    df = PolygonProvider("pk", session=sess).history("AAPL", "1d", limit=10)
    assert [d.strftime("%Y-%m-%d %H:%M") for d in df.index] == ["2024-03-11 00:00", "2024-03-12 00:00",
                                                                "2024-03-13 00:00"]
    today = df.iloc[-1]
    assert today["open"] == 172.5 and today["close"] == 174.5 and today["high"] == 174.5
    assert today["volume"] == 2.1e7


def test_polygon_hourly_bars_start_at_half_past_like_yahoo():
    bars = [polygon_bar(ny("2024-03-12 09:30") + pd.Timedelta(minutes=30 * i), 100 + i, 101 + i)
            for i in range(13)]
    sess = FakeSession({"/range/30/minute/": FakeResp({"status": "OK", "results": bars})})
    df = PolygonProvider("pk", session=sess, live_daily=False).history("AAPL", "1h", start="2024-03-12")
    local = df.index.tz_convert("America/New_York")
    assert [t.strftime("%H:%M") for t in local] == ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
    assert df["open"].iloc[0] == 100 and df["close"].iloc[0] == 102  # two 30m bars merged
    assert df["volume"].iloc[0] == 2000 and df["volume"].iloc[-1] == 1000


def test_polygon_last_trade():
    payload = {"request_id": "x", "status": "OK", "results": {
        "T": "AAPL", "p": 174.25, "s": 50, "t": int(ny("2024-03-13 11:00").value), "x": 4, "c": [14, 41]}}
    sess = FakeSession({"/v2/last/trade/AAPL": FakeResp(payload)})
    t = PolygonProvider("pk", session=sess).last_trade("AAPL")
    assert t["price"] == 174.25 and t["size"] == 50 and t["time"].startswith("2024-03-13T15:00")


@pytest.mark.parametrize("tf,path", [("1m", "/1/minute/"), ("5m", "/5/minute/"), ("15m", "/15/minute/"),
                                     ("1h", "/30/minute/"), ("1d", "/1/day/"), ("1wk", "/1/day/")])
def test_polygon_timeframe_mapping(tf, path):
    sess = FakeSession({"/v2/aggs/": FakeResp({"status": "OK", "resultsCount": 0})})
    with pytest.raises(ValueError):  # no data -> ValueError, URL still checked
        PolygonProvider("pk", session=sess, live_daily=False).history("AAPL", tf, limit=10)
    assert path in sess.calls[0]["url"]


# --- Alpaca --------------------------------------------------------------------------------

def alpaca_bar(t, o, c, v=500):
    return {"t": t, "o": o, "h": max(o, c) + 1, "l": min(o, c) - 1, "c": c, "v": v, "n": 10, "vw": o}


def test_alpaca_batch_daily_with_pagination_and_feed():
    p1 = {"bars": {"AAPL": [alpaca_bar("2024-03-11T04:00:00Z", 170, 171)],
                   "BRK.B": [alpaca_bar("2024-03-11T04:00:00Z", 400, 401)]},
          "next_page_token": "tok"}
    p2 = {"bars": {"AAPL": [alpaca_bar("2024-03-12T04:00:00Z", 171, 172)]}, "next_page_token": None}
    sess = FakeSession({"/v2/stocks/bars": [FakeResp(p1), FakeResp(p2)]})
    prov = AlpacaProvider("kid", "sec", feed="sip", session=sess, live_daily=False)
    out = prov.history_many(["AAPL", "BRK-B", "^GSPC"], "1d", limit=5)
    assert set(out) == {"AAPL", "BRK-B"}  # index left for Yahoo, class share mapped back
    assert [d.strftime("%Y-%m-%d") for d in out["AAPL"].index] == ["2024-03-11", "2024-03-12"]
    assert out["AAPL"].index[0].hour == 0
    first = sess.calls[0]
    assert first["params"]["symbols"] == "AAPL,BRK.B" and first["params"]["feed"] == "sip"
    assert first["params"]["timeframe"] == "1Day" and first["params"]["adjustment"] == "all"
    assert first["headers"] == {"APCA-API-KEY-ID": "kid", "APCA-API-SECRET-KEY": "sec"}
    assert sess.calls[1]["params"]["page_token"] == "tok"


@pytest.mark.parametrize("tf,code", [("1m", "1Min"), ("5m", "5Min"), ("15m", "15Min"), ("1h", "30Min"),
                                     ("4h", "30Min"), ("1d", "1Day")])
def test_alpaca_timeframe_mapping(tf, code):
    sess = FakeSession({"/v2/stocks/bars": FakeResp({"bars": {}, "next_page_token": None})})
    with pytest.raises(ValueError):
        AlpacaProvider("k", "s", session=sess, live_daily=False).history("AAPL", tf, limit=10)
    assert sess.calls[0]["params"]["timeframe"] == code


def test_alpaca_intraday_and_snapshot_and_latest_trade():
    bars = {"bars": {"AAPL": [alpaca_bar("2024-03-12T13:30:00Z", 172, 173),
                              alpaca_bar("2024-03-12T13:35:00Z", 173, 174)]}, "next_page_token": None}
    snaps = {"AAPL": {"dailyBar": alpaca_bar("2024-03-12T04:00:00Z", 171, 172.8, 9e6),
                      "latestTrade": {"t": "2024-03-12T15:01:02.123Z", "p": 173.9, "s": 10, "x": "V"},
                      "prevDailyBar": alpaca_bar("2024-03-11T04:00:00Z", 170, 171)}}
    trade = {"trades": {"AAPL": {"t": "2024-03-12T15:01:02.123456Z", "x": "V", "p": 173.9, "s": 10,
                                 "c": ["@"], "i": 52983525029461, "z": "C"}}}
    daily = {"bars": {"AAPL": [alpaca_bar("2024-03-11T04:00:00Z", 170, 171)]}, "next_page_token": None}
    sess = FakeSession({"/v2/stocks/bars": [FakeResp(bars), FakeResp(daily)],
                        "/v2/stocks/snapshots": FakeResp(snaps), "/v2/stocks/trades/latest": FakeResp(trade)})
    prov = AlpacaProvider("k", "s", session=sess)
    df = prov.history("AAPL", "5m", start="2024-03-12")
    assert df["close"].tolist() == [173.0, 174.0]
    d = prov.history("AAPL", "1d", limit=5)
    assert d.index[-1] == pd.Timestamp("2024-03-12", tz="UTC") and d["close"].iloc[-1] == 173.9
    t = prov.last_trade("AAPL")
    assert t["price"] == 173.9 and t["time"].startswith("2024-03-12T15:01:02")


def test_alpaca_rejects_unknown_feed():
    with pytest.raises(ValueError):
        AlpacaProvider("k", "s", feed="nasdaq")


# --- Finnhub -------------------------------------------------------------------------------

def test_finnhub_candles_daily_and_quote():
    t = [int(pd.Timestamp("2024-03-11", tz="UTC").timestamp()), int(pd.Timestamp("2024-03-12", tz="UTC").timestamp())]
    candles = {"c": [171.0, 172.0], "h": [172.0, 173.0], "l": [169.0, 170.0], "o": [170.0, 171.0],
               "s": "ok", "t": t, "v": [5e7, 6e7]}
    quote = {"c": 173.2, "d": 1.2, "dp": 0.7, "h": 174.0, "l": 171.5, "o": 172.1, "pc": 172.0,
             "t": int(ny("2024-03-12 15:59").timestamp())}
    sess = FakeSession({"/stock/candle": FakeResp(candles), "/quote": FakeResp(quote)})
    prov = FinnhubProvider("fk", session=sess)
    df = prov.history("AAPL", "1d", limit=10)
    assert [d.strftime("%Y-%m-%d") for d in df.index] == ["2024-03-11", "2024-03-12"]
    assert df["close"].iloc[-1] == 173.2 and df["volume"].iloc[-1] == 6e7  # live quote, candle volume
    call = sess.calls[0]
    assert call["params"]["resolution"] == "D" and call["headers"]["X-Finnhub-Token"] == "fk"
    assert prov.last_trade("AAPL")["price"] == 173.2


@pytest.mark.parametrize("tf,res", [("1m", "1"), ("5m", "5"), ("15m", "15"), ("1h", "30"), ("1d", "D")])
def test_finnhub_resolution_mapping_and_no_data(tf, res):
    sess = FakeSession({"/stock/candle": FakeResp({"s": "no_data"})})
    with pytest.raises(ValueError):
        FinnhubProvider("fk", session=sess, live_daily=False).history("AAPL", tf, limit=10)
    assert sess.calls[0]["params"]["resolution"] == res


def test_weekly_bars_are_monday_labelled():
    days = pd.bdate_range("2024-03-04", "2024-03-15", tz="UTC")
    candles = {"s": "ok", "t": [int(d.timestamp()) for d in days], "o": [1.0] * 10, "h": [2.0] * 10,
               "l": [0.5] * 10, "c": [1.5] * 10, "v": [10] * 10}
    sess = FakeSession({"/stock/candle": FakeResp(candles)})
    df = FinnhubProvider("fk", session=sess, live_daily=False).history("AAPL", "1wk", start="2024-03-04")
    assert list(df.index) == [pd.Timestamp("2024-03-04", tz="UTC"), pd.Timestamp("2024-03-11", tz="UTC")]
    assert df["volume"].tolist() == [50.0, 50.0]


# --- HTTP errors, retries, fallback --------------------------------------------------------

def test_backoff_on_429_then_success():
    ok = {"status": "OK", "results": [polygon_bar(ny("2024-03-12 09:30"), 1, 2)]}
    sess = FakeSession({"/v2/aggs/": [FakeResp({"status": "ERROR"}, 429, {"Retry-After": "1"}), FakeResp(ok)]})
    df = PolygonProvider("pk", session=sess, live_daily=False).history("AAPL", "5m", start="2024-03-12")
    assert len(df) == 1 and len(sess.calls) == 2


def test_persistent_429_raises_rate_limited():
    sess = FakeSession({"/v2/aggs/": FakeResp({"status": "ERROR"}, 429)})
    with pytest.raises(RateLimited):
        PolygonProvider("pk", session=sess, max_retries=2).history("AAPL", "5m", limit=5)
    assert len(sess.calls) == 3


def test_fallback_to_yahoo_on_auth_error_then_cooldown():
    sess = FakeSession({"/v2/aggs/": FakeResp({"status": "NOT_AUTHORIZED"}, 403)})
    yahoo = FakeYahoo()
    prov = FallbackProvider(PolygonProvider("bad", session=sess), yahoo)
    df = prov.history("AAPL", "1d", limit=5)
    assert len(df) == 5 and yahoo.calls == [("history", "AAPL", "1d")]
    assert "403" in prov.last_error
    prov.history("MSFT", "1d", limit=5)
    assert len(sess.calls) == 1  # paused after a rejected key: no hammering


def test_fallback_on_rate_limit_and_network_error():
    sess = FakeSession({"/stock/candle": FakeResp({}, 429)})
    yahoo = FakeYahoo()
    prov = FallbackProvider(FinnhubProvider("fk", session=sess, max_retries=1), yahoo)
    assert len(prov.history("AAPL", "5m", limit=5)) == 5

    class Boom:
        def get(self, *a, **k):
            import requests
            raise requests.ConnectionError("down")
    prov2 = FallbackProvider(FinnhubProvider("fk", session=Boom()), yahoo)
    assert len(prov2.history("AAPL", "5m", limit=5)) == 5
    assert prov2._active()  # transient errors don't pause the feed


def test_unsupported_symbols_go_straight_to_yahoo():
    sess = FakeSession({})
    yahoo = FakeYahoo()
    prov = FallbackProvider(PolygonProvider("pk", session=sess), yahoo)
    prov.history("^GSPC", "1d", limit=5)
    prov.history("MC.PA", "1d", limit=5)
    assert sess.calls == [] and len(yahoo.calls) == 2


def test_history_many_mixes_paid_and_yahoo():
    payload = {"bars": {"AAPL": [alpaca_bar("2024-03-11T04:00:00Z", 1, 2)]}, "next_page_token": None}
    sess = FakeSession({"/v2/stocks/bars": FakeResp(payload)})
    yahoo = FakeYahoo()
    prov = FallbackProvider(AlpacaProvider("k", "s", session=sess, live_daily=False), yahoo)
    out = prov.history_many(["AAPL", "MSFT", "^GSPC"], "1d", limit=5)
    assert set(out) == {"AAPL", "MSFT", "^GSPC"} and len(out["AAPL"]) == 1
    assert yahoo.calls == [("history_many", ("MSFT", "^GSPC"), "1d")]


def test_history_many_falls_back_entirely_on_error():
    sess = FakeSession({"/v2/stocks/bars": FakeResp({"message": "forbidden"}, 403)})
    yahoo = FakeYahoo()
    prov = FallbackProvider(AlpacaProvider("k", "s", session=sess), yahoo)
    out = prov.history_many(["AAPL", "MSFT"], "1d", limit=5)
    assert set(out) == {"AAPL", "MSFT"}


def test_market_data_never_crashes_with_failing_paid_feed():
    sess = FakeSession({"/v2/aggs/": FakeResp({}, 500)})
    prov = FallbackProvider(PolygonProvider("pk", session=sess), FakeYahoo())
    md = MarketData(provider_factory=lambda n, e: prov)
    assert len(md.history("yahoo", "AAPL", "1d", limit=5)) == 5
    q = md.quotes(["AAPL", "MSFT"])
    assert all("price" in x for x in q)


# --- selection by environment --------------------------------------------------------------

def test_selection_defaults_to_yahoo(monkeypatch):
    monkeypatch.delenv("MARKET_DATA_PROVIDER", raising=False)
    assert type(get_provider("yahoo")) is YahooProvider
    assert describe_stock_source({})["provider"] == "yahoo"


@pytest.mark.parametrize("name,env,cls", [
    ("polygon", {"POLYGON_API_KEY": "pk"}, PolygonProvider),
    ("alpaca", {"ALPACA_API_KEY_ID": "k", "ALPACA_API_SECRET_KEY": "s", "ALPACA_DATA_FEED": "sip"}, AlpacaProvider),
    ("finnhub", {"FINNHUB_API_KEY": "fk"}, FinnhubProvider),
])
def test_selection_by_env(monkeypatch, name, env, cls):
    for k in ("POLYGON_API_KEY", "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "FINNHUB_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", name.upper())
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    prov = get_provider("yahoo")
    assert isinstance(prov, FallbackProvider) and isinstance(prov.primary, cls)
    assert isinstance(prov.fallback, YahooProvider)
    assert describe_stock_source()["realtime"] is True


def test_selection_without_key_or_unknown_uses_yahoo():
    assert type(stock_provider_from_env({"MARKET_DATA_PROVIDER": "polygon"})) is YahooProvider
    assert type(stock_provider_from_env({"MARKET_DATA_PROVIDER": "alpaca", "ALPACA_API_KEY_ID": "k"})) is YahooProvider
    assert type(stock_provider_from_env({"MARKET_DATA_PROVIDER": "bloomberg"})) is YahooProvider
    assert describe_stock_source({"MARKET_DATA_PROVIDER": "finnhub"})["realtime"] is False


def test_build_options_from_env():
    p = build_paid_provider("polygon", {"POLYGON_API_KEY": "k", "MARKET_DATA_MAX_RPM": "120",
                                        "MARKET_DATA_EXTENDED_HOURS": "1",
                                        "POLYGON_BASE_URL": "https://api.massive.com/"})
    assert p.extended_hours and p._min_interval == 0.5 and p.base_url == "https://api.massive.com"
    with pytest.raises(MissingCredentials):
        build_paid_provider("finnhub", {})


def test_verify_command_reports_missing_selection(monkeypatch, capsys):
    monkeypatch.delenv("MARKET_DATA_PROVIDER", raising=False)
    assert paid.main(["AAPL"]) == 1
    assert "Yahoo" in capsys.readouterr().out


# --- streaming parsers ---------------------------------------------------------------------

def test_polygon_stream_parse():
    s = PolygonStream("pk")
    raw = json.dumps([{"ev": "T", "sym": "BRK.B", "p": 410.5, "s": 20, "t": ms(ny("2024-03-12 10:00")), "x": 4},
                      {"ev": "AM", "sym": "AAPL", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 900,
                       "s": ms(ny("2024-03-12 10:00")), "e": ms(ny("2024-03-12 10:01"))}])
    trade, bar = s.parse(raw)
    assert trade == {"type": "trade", "symbol": "BRK-B", "price": 410.5, "size": 20.0,
                     "time": "2024-03-12T14:00:00+00:00"}
    assert bar["type"] == "bar" and bar["close"] == 1.5 and bar["volume"] == 900
    assert s.authenticated(json.dumps([{"ev": "status", "status": "auth_success", "message": "ok"}]))
    with pytest.raises(PermissionError):
        s.parse(json.dumps([{"ev": "status", "status": "auth_failed", "message": "bad key"}]))
    assert s.subscribe_messages(["AAPL"]) == [{"action": "subscribe", "params": "T.AAPL,AM.AAPL"}]


def test_alpaca_stream_parse():
    s = AlpacaStream("k", "s", feed="sip")
    assert s.url.endswith("/v2/sip")
    raw = json.dumps([{"T": "t", "S": "AAPL", "i": 1, "x": "V", "p": 173.9, "s": 5, "t": "2024-03-12T14:00:00.5Z",
                       "c": ["@"], "z": "C"},
                      {"T": "b", "S": "AAPL", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "t": "2024-03-12T14:00:00Z"}])
    trade, bar = s.parse(raw)
    assert trade["price"] == 173.9 and bar["open"] == 1.0
    assert s.authenticated(json.dumps([{"T": "success", "msg": "authenticated"}]))
    with pytest.raises(PermissionError):
        s.parse(json.dumps([{"T": "error", "code": 402, "msg": "auth failed"}]))


def test_finnhub_stream_parse_and_selection():
    s = FinnhubStream("fk")
    raw = json.dumps({"type": "trade", "data": [{"s": "AAPL", "p": 173.9, "t": ms(ny("2024-03-12 10:00")), "v": 3,
                                                 "c": None}]})
    assert s.parse(raw)[0]["symbol"] == "AAPL"
    assert s.parse(json.dumps({"type": "ping"})) == [{"type": "pong"}]
    assert stream_from_env({}) is None
    assert stream_from_env({"MARKET_DATA_PROVIDER": "polygon"}) is None
    assert isinstance(stream_from_env({"MARKET_DATA_PROVIDER": "finnhub", "FINNHUB_API_KEY": "x"}), FinnhubStream)
