"""Screener: fundamentals parsing (dividend units), daily refresh scheduling, technicals, filters, sorting, API."""

import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import fake_fundamentals, make_ohlcv
from tradebot import screener as sc
from tradebot.api import create_app
from tradebot.api.settings import Settings
from tradebot.api.store import EventStore
from tradebot.data import DataProvider
from tradebot.data import fundamentals as fd
from tradebot.universe import STOCKS

NY = ZoneInfo("America/New_York")


# ---- dividend units and parsing -------------------------------------------------------------
KO_NEW = {"marketCap": 400007987200, "trailingPE": 27.92, "forwardPE": 26.39, "dividendYield": 2.27,
          "trailingAnnualDividendYield": 0.02226504, "dividendRate": 2.12, "currentPrice": 92.97, "beta": 0.318,
          "sector": "Consumer Defensive", "currency": "USD", "longName": "The Coca-Cola Company"}


def test_dividend_yield_percent_style_current_yfinance():
    assert fd.dividend_yield_pct(KO_NEW) == pytest.approx(2.27)


def test_dividend_yield_fraction_style_old_yfinance():
    old = {**KO_NEW, "dividendYield": 0.0227}
    assert fd.dividend_yield_pct(old) == pytest.approx(2.27)


def test_dividend_yield_unit_from_rate_and_price_when_trailing_missing():
    info = {"dividendYield": 0.031, "dividendRate": 3.1, "currentPrice": 100.0}
    assert fd.dividend_yield_pct(info) == pytest.approx(3.1)
    info = {"dividendYield": 3.1, "dividendRate": 3.1, "currentPrice": 100.0}
    assert fd.dividend_yield_pct(info) == pytest.approx(3.1)


def test_dividend_yield_without_references_uses_version_rule():
    assert fd.dividend_yield_pct({"dividendYield": 0.5}, percent_default=True) == pytest.approx(0.5)
    assert fd.dividend_yield_pct({"dividendYield": 0.005}, percent_default=False) == pytest.approx(0.5)


def test_dividend_yield_edge_cases():
    assert fd.dividend_yield_pct({"dividendYield": 0.0, "trailingAnnualDividendYield": 0.0}) == 0.0
    assert fd.dividend_yield_pct({"trailingAnnualDividendYield": 0.0}) == 0.0        # pays none
    assert fd.dividend_yield_pct({}) is None                                           # unknown
    assert fd.dividend_yield_pct({"trailingAnnualDividendYield": 0.031}) == pytest.approx(3.1)
    assert fd.dividend_yield_pct({"dividendYield": 45.0, "trailingAnnualDividendYield": 0.45}) is None  # data error
    assert fd.dividend_yield_pct({"dividendYield": float("nan")}) is None


def test_parse_info():
    rec = fd.parse_info(KO_NEW)
    assert rec["market_cap"] == 400007987200 and rec["pe"] == 27.92 and rec["forward_pe"] == 26.39
    assert rec["dividend_yield"] == pytest.approx(2.27) and rec["beta"] == 0.318 and rec["currency"] == "USD"
    assert rec["name"] == "The Coca-Cola Company" and rec["sector_yahoo"] == "Consumer Defensive"
    # A rate-limited answer (no figures at all) is a failure, not a company without data.
    assert fd.parse_info({}) is None and fd.parse_info(None) is None
    assert fd.parse_info({"trailingPegRatio": None, "quoteType": "EQUITY"}) is None
    loss = fd.parse_info({"marketCap": 5e9, "trailingPE": -3.0, "trailingEps": -1.2, "currency": "USD"})
    assert loss["pe"] is None and loss["eps"] == -1.2


def test_fetch_fundamentals_holds_the_yahoo_lock_only_during_the_request(monkeypatch):
    import yfinance as yf

    from tradebot.data.providers import _YF_LOCK

    seen = []

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            seen.append(_YF_LOCK.locked())
            return KO_NEW

    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    assert fd.fetch_fundamentals("KO")["pe"] == 27.92
    assert seen == [True] and not _YF_LOCK.locked()

    class Broken(FakeTicker):
        @property
        def info(self):
            raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(yf, "Ticker", Broken)
    assert fd.fetch_fundamentals("KO") is None and not _YF_LOCK.locked()


# ---- the daily cache ------------------------------------------------------------------------
class Clock:
    def __init__(self, t: datetime):
        self.t = t.timestamp()

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def ny(*args) -> datetime:
    return datetime(*args, tzinfo=NY)


def test_daily_refresh_schedule_and_persistence(tmp_path):
    store = EventStore(tmp_path / "f.db")
    clock = Clock(ny(2026, 10, 20, 9, 0))
    calls = []

    def fetch(s):
        calls.append(s)
        return fake_fundamentals(s)

    f = fd.Fundamentals(store, fetcher=fetch, clock=clock, pause=0)
    syms = ["AAA", "BBB", "CCC"]
    assert f.due(syms) == syms
    res = f.refresh(syms)
    assert res["fetched"] == 3 and res["ok"] == 3 and calls == syms
    assert f.due(syms) == []
    clock.advance(20 * 3600)                    # 05:00 the next day: before the daily slot
    assert f.due(syms) == []
    clock.advance(3600)                         # 06:00 New York: due again, once
    assert f.due(syms) == syms
    # A restart reads SQLite instead of asking Yahoo again.
    clock2 = Clock(ny(2026, 10, 20, 15, 0))
    f2 = fd.Fundamentals(EventStore(tmp_path / "f.db"), fetcher=fetch, clock=clock2, pause=0)
    assert f2.due(syms) == [] and f2.cached(syms)["BBB"]["market_cap"] == fake_fundamentals("BBB")["market_cap"]
    cov = f2.coverage(syms + ["DDD"])
    assert cov["total"] == 4 and cov["with_fundamentals"] == 3 and cov["fresh"] == 3 and not cov["refreshing"]


def test_last_slot_handles_time_zones():
    f = fd.Fundamentals(clock=lambda: 0)
    assert datetime.fromtimestamp(f.last_slot(ny(2026, 10, 20, 5, 59).timestamp()), NY) == ny(2026, 10, 19, 6, 0)
    assert datetime.fromtimestamp(f.last_slot(ny(2026, 10, 20, 6, 0).timestamp()), NY) == ny(2026, 10, 20, 6, 0)
    # 03:00 UTC = 23:00 New York the previous evening
    utc = datetime(2026, 10, 21, 3, 0, tzinfo=timezone.utc).timestamp()
    assert datetime.fromtimestamp(f.last_slot(utc), NY) == ny(2026, 10, 20, 6, 0)


def test_failure_keeps_last_figures_and_retries_after_two_hours():
    clock = Clock(ny(2026, 10, 20, 9, 0))
    ok = {"v": True}
    f = fd.Fundamentals(fetcher=lambda s: fake_fundamentals(s) if ok["v"] else None, clock=clock, pause=0)
    f.refresh(["AAA"])
    clock.advance(24 * 3600)
    ok["v"] = False
    f.refresh(["AAA"])
    rec = f.cached(["AAA"])["AAA"]
    assert rec["ok"] is False and rec["market_cap"] == fake_fundamentals("AAA")["market_cap"]   # old figures kept
    assert f.due(["AAA"]) == []
    clock.advance(2 * 3600)
    assert f.due(["AAA"]) == ["AAA"]
    assert f.coverage(["AAA"])["with_fundamentals"] == 1


def test_due_order_new_first_then_failed_then_oldest():
    clock = Clock(ny(2026, 10, 20, 9, 0))
    f = fd.Fundamentals(fetcher=fake_fundamentals, clock=clock, pause=0)
    f.refresh(["OLD"])
    clock.advance(60)
    f.refresh(["NEWER"])
    f.put("FAILED", None)
    clock.advance(26 * 3600)
    assert f.due(["NEWER", "OLD", "FAILED", "NEVER"]) == ["NEVER", "FAILED", "OLD", "NEWER"]


def test_refresh_is_polite_and_backs_off_on_repeated_failures():
    sleeps = []
    f = fd.Fundamentals(fetcher=lambda s: None, pause=0.3, sleep=sleeps.append)
    syms = [f"S{i}" for i in range(40)]
    res = f.refresh(syms)
    # pause between symbols, then exponential back-offs after every MAX_FAILS failures, then give up the pass
    backoffs = [s for s in sleeps if s != 0.3]
    assert backoffs == [fd.BACKOFF * 2 ** i for i in range(fd.MAX_BACKOFFS)]
    assert res["fetched"] == fd.MAX_FAILS * (fd.MAX_BACKOFFS + 1) < len(syms) and res["ok"] == 0
    assert sleeps.count(0.3) == res["fetched"] - 1


def test_partial_results_are_usable_and_refresh_never_blocks_readers():
    gate, started = threading.Event(), threading.Event()
    stop = threading.Event()

    def slow(s):
        if s == "S3":
            started.set()
            gate.wait(5)
        return fake_fundamentals(s)

    f = fd.Fundamentals(fetcher=slow, pause=0)
    syms = [f"S{i}" for i in range(6)]
    t = threading.Thread(target=f.refresh, args=(syms,), kwargs={"stop": stop})
    t.start()
    assert started.wait(5)
    t0 = time.time()
    cov = f.coverage(syms)
    assert time.time() - t0 < 0.5
    assert cov["with_fundamentals"] == 3 and cov["refreshing"] and cov["progress"]["todo"] == 6
    assert f.refresh(syms)["busy"] is True                       # a second pass doesn't wait behind the first
    stop.set()
    gate.set()
    t.join(5)
    assert not t.is_alive() and f.coverage(syms)["with_fundamentals"] == 4   # stopped after the running symbol


def test_yahoo_lock_is_free_between_symbols(monkeypatch):
    from tradebot.data.providers import _YF_LOCK

    states = []

    def fetch(s):
        with _YF_LOCK:
            return fake_fundamentals(s)

    f = fd.Fundamentals(fetcher=fetch, pause=0.01, sleep=lambda x: states.append(_YF_LOCK.locked()))
    f.refresh(["A", "B", "C"])
    assert states == [False, False]


# ---- technicals -----------------------------------------------------------------------------
def test_technicals_from_daily_bars():
    df = make_ohlcv(300, seed=3)
    t = sc.technicals(df)
    c = df["close"].to_numpy()
    assert t["price"] == pytest.approx(c[-1])
    assert t["change_pct"] == pytest.approx((c[-1] / c[-2] - 1) * 100)
    assert t["ret_1m"] == pytest.approx((c[-1] / c[-22] - 1) * 100)
    assert t["ret_6m"] == pytest.approx((c[-1] / c[-127] - 1) * 100)
    assert t["ret_12m"] == pytest.approx((c[-1] / c[-253] - 1) * 100)
    sma = c[-200:].mean()
    assert t["above_200d"] == (c[-1] > sma) and t["vs_200d_pct"] == pytest.approx((c[-1] / sma - 1) * 100)
    hi = df["high"].to_numpy()[-252:].max()
    assert t["from_high_pct"] == pytest.approx(min(0.0, (c[-1] / hi - 1) * 100))
    vol = np.diff(np.log(c[-64:])).std(ddof=1) * np.sqrt(252) * 100
    assert t["volatility"] == pytest.approx(vol)


def test_technicals_only_use_past_bars():
    df = make_ohlcv(300, seed=4)
    a = sc.technicals(df.iloc[:280])
    b = sc.technicals(df.iloc[:280].copy())
    assert a == b
    assert a["as_of"] == df.index[279].isoformat()


def test_technicals_short_history():
    assert sc.technicals(make_ohlcv(20)) is None and sc.technicals(None) is None
    t = sc.technicals(make_ohlcv(100))
    assert t["ret_6m"] is None and t["ret_12m"] is None and t["above_200d"] is None and t["ret_1m"] is not None


# ---- rows, filters, sorting -----------------------------------------------------------------
class S:
    def __init__(self, symbol, sector="Information Technology", region="US"):
        self.symbol, self.name, self.sector, self.industry, self.region, self.sp500 = (
            symbol, f"{symbol} Inc", sector, "Software", region, True)


def frow(cap, pe, dy, ccy="USD"):
    return {"market_cap": cap, "pe": pe, "forward_pe": pe, "dividend_yield": dy, "beta": 1.0, "currency": ccy,
            "_ok_at": 1.0, "fetched_at": "2026-10-20T10:00:00+00:00"}


def trow(ret6, above, price=100.0):
    return {"price": price, "change_pct": 0.5, "ret_1m": 1.0, "ret_6m": ret6, "ret_12m": ret6 * 2,
            "above_200d": above, "vs_200d_pct": 5.0 if above else -5.0, "from_high_pct": -3.0, "volatility": 25.0}


@pytest.fixture
def rows():
    stocks = [S("MEGA"), S("BIG", "Financials"), S("MIDC", "Utilities"), S("SMAL", "Energy"), S("LOSS"),
              S("NOFUND"), S("EURO", "Industrials", "Europe")]
    fund = {"MEGA": frow(3e12, 35.0, 0.5), "BIG": frow(80e9, 11.0, 3.2), "MIDC": frow(20e9, 18.0, 4.5),
            "SMAL": frow(8e9, 9.0, 0.0), "LOSS": frow(30e9, None, None), "EURO": frow(100e9, 14.0, 2.5, "EUR")}
    tech = {"MEGA": trow(40.0, True), "BIG": trow(10.0, True), "MIDC": trow(-5.0, False), "SMAL": trow(25.0, True),
            "LOSS": trow(-30.0, False), "EURO": trow(5.0, True)}
    return sc.build_rows(stocks, fund, tech, {"EUR": 1.10})


def by(rows, sym):
    return next(r for r in rows if r["symbol"] == sym)


def test_rows_bands_fx_and_momentum_percentile(rows):
    assert by(rows, "MEGA")["size"] == "mega" and by(rows, "BIG")["size"] == "large"
    assert by(rows, "MIDC")["size"] == "mid" and by(rows, "SMAL")["size"] == "small"
    assert by(rows, "EURO")["market_cap"] == pytest.approx(110e9) and by(rows, "EURO")["size"] == "large"
    assert by(rows, "BIG")["valuation"] == "cheap" and by(rows, "MIDC")["valuation"] == "fair"
    assert by(rows, "MEGA")["valuation"] == "expensive" and by(rows, "LOSS")["valuation"] == "no_profit"
    nf = by(rows, "NOFUND")
    assert nf["valuation"] is None and nf["size"] is None and not nf["has_fundamentals"] and not nf["has_technicals"]
    assert by(rows, "MEGA")["momentum_pct"] == 100.0 and by(rows, "LOSS")["momentum_pct"] == 0.0
    assert nf["momentum_pct"] is None


def syms(rs):
    return [r["symbol"] for r in rs]


def test_filters(rows):
    F = sc.Filters
    assert syms(sc.apply(rows, F(sector="Financials,Utilities"))) == ["BIG", "MIDC"]
    assert set(syms(sc.apply(rows, F(size=("large", "mega"))))) == {"MEGA", "BIG", "EURO"}
    assert set(syms(sc.apply(rows, F(valuation="cheap")))) == {"BIG", "SMAL", "EURO"}
    assert syms(sc.apply(rows, F(valuation="no_profit"))) == ["LOSS"]
    assert set(syms(sc.apply(rows, F(min_cap=50e9)))) == {"MEGA", "BIG", "EURO"}
    assert set(syms(sc.apply(rows, F(max_cap=25e9)))) == {"MIDC", "SMAL"}
    assert set(syms(sc.apply(rows, F(max_pe=15)))) == {"BIG", "SMAL", "EURO"}   # no P/E (losses) excluded
    assert set(syms(sc.apply(rows, F(min_div=3)))) == {"BIG", "MIDC"}
    assert set(syms(sc.apply(rows, F(dividends=True)))) == {"MEGA", "BIG", "MIDC", "EURO"}
    assert set(syms(sc.apply(rows, F(dividends=False)))) == {"SMAL"}             # unknown is not "pays none"
    assert set(syms(sc.apply(rows, F(trend="up")))) == {"MEGA", "BIG", "SMAL", "EURO"}
    assert set(syms(sc.apply(rows, F(trend="down")))) == {"MIDC", "LOSS"}
    assert set(syms(sc.apply(rows, F(momentum="positive")))) == {"MEGA", "BIG", "SMAL", "EURO"}
    assert syms(sc.apply(rows, F(momentum="strong"))) == ["MEGA"]               # top 20% of 6
    assert syms(sc.apply(rows, F(q="smal"))) == ["SMAL"]
    combo = F(dividends=True, trend="up", min_div=2)
    assert set(syms(sc.apply(rows, combo))) == {"BIG", "EURO"}
    assert len(sc.apply(rows, F())) == len(rows)


def test_sorting_puts_missing_values_last(rows):
    assert syms(sc.sort_rows(rows, "market_cap"))[:3] == ["MEGA", "EURO", "BIG"]
    assert syms(sc.sort_rows(rows, "market_cap"))[-1] == "NOFUND"
    asc = syms(sc.sort_rows(rows, "pe", desc=False))
    assert asc[:2] == ["SMAL", "BIG"] and asc[-2:] == ["LOSS", "NOFUND"]
    assert syms(sc.sort_rows(rows, "pe", desc=True))[-2:] == ["LOSS", "NOFUND"]
    assert syms(sc.sort_rows(rows, "name", desc=False))[0] == "BIG"
    with pytest.raises(ValueError):
        sc.sort_rows(rows, "drop table")


def test_bands_are_json_safe():
    b = sc.bands()
    assert [x["id"] for x in b["size"]] == ["small", "mid", "large", "mega"] and b["size"][-1]["max"] is None
    assert [x["id"] for x in b["valuation"]] == ["cheap", "fair", "expensive"]


# ---- Precomputer + API ----------------------------------------------------------------------
class CountingProvider(DataProvider):
    def __init__(self):
        self.calls = 0

    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        self.calls += 1
        if symbol.endswith("USD=X"):
            return make_ohlcv(40, seed=1, drift=0, vol=0.001).assign(close=1.1)
        df = make_ohlcv(400, seed=sum(map(ord, symbol)) % 100)
        return df.tail(limit) if limit else df


@pytest.fixture
def client(tmp_path):
    prov = CountingProvider()
    settings = Settings(db_path=tmp_path / "t.db", static_dir=None, api_token=None, autostart_live=False,
                        precompute=False)
    app = create_app(settings, provider_factory=lambda n, e: prov, config={"poll_seconds": 60})
    with TestClient(app) as c:
        c.provider = prov
        yield c


def test_technicals_reuse_the_scanners_cached_bars(client):
    pre = client.app.state.precompute
    syms = pre.screener_symbols()
    client.app.state.market.history_many("yahoo", syms, "1d", limit=pre.SCREENER_BARS)   # what the scan loads
    n = client.provider.calls
    data = pre.refresh_screener_technicals()
    assert client.provider.calls == n                    # no extra download (no fundamentals yet: no FX either)
    assert len(data["rows"]) == len(syms) == len(STOCKS)


def test_screener_endpoint(client):
    pre = client.app.state.precompute
    first = client.get("/api/screener").json()             # before anything: instant, empty coverage
    assert first["total"] == len(STOCKS) and first["coverage"]["with_fundamentals"] == 0
    pre.fundamentals.pause = 0
    half = pre.screener_symbols()[:200]
    pre.fundamentals.refresh(half)                         # a partial refresh is usable at once
    pre.refresh_screener_technicals()
    d = client.get("/api/screener").json()
    cov = d["coverage"]
    assert cov["with_fundamentals"] == 200 and cov["with_technicals"] == len(STOCKS) and cov["technicals_ready"]
    assert d["count"] == len(STOCKS) and len(d["rows"]) == len(STOCKS)
    caps = [r["market_cap"] for r in d["rows"] if r["market_cap"] is not None]
    assert caps == sorted(caps, reverse=True) and len(caps) == 200
    assert {b["id"] for b in d["bands"]["size"]} == {"small", "mid", "large", "mega"}
    assert "Information Technology" in d["sectors"]
    # ~520 rows: compressed on the wire for the phone
    assert client.get("/api/screener", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") == "gzip"

    r = client.get("/api/screener", params={"dividends": "true", "trend": "up", "sort": "dividend_yield",
                                             "min_cap": 50e9, "limit": 10}).json()
    assert r["count"] >= len(r["rows"]) and len(r["rows"]) <= 10
    assert all(x["dividend_yield"] > 0 and x["above_200d"] and x["market_cap"] >= 50e9 for x in r["rows"])
    ys = [x["dividend_yield"] for x in r["rows"]]
    assert ys == sorted(ys, reverse=True)
    assert r["filters"] == {"min_cap": 50e9, "dividends": True, "trend": "up"}

    r = client.get("/api/screener", params={"sector": "Energy", "valuation": "cheap,fair", "size": "large,mega",
                                             "sort": "pe", "order": "asc"}).json()
    assert all(x["sector"] == "Energy" and x["valuation"] in ("cheap", "fair") and x["size"] in ("large", "mega")
               for x in r["rows"])
    r = client.get("/api/screener", params={"momentum": "strong", "max_pe": 20}).json()
    assert all(x["momentum_pct"] > 80 and x["pe"] <= 20 for x in r["rows"])

    assert client.get("/api/screener", params={"sort": "nope"}).status_code == 422
    assert client.get("/api/screener", params={"size": "huge"}).status_code == 422
    assert client.get("/api/screener", params={"trend": "sideways"}).status_code == 422


def test_screener_never_waits_for_technicals_or_fundamentals(client):
    pre = client.app.state.precompute
    gate = threading.Event()
    slow_market = pre.market.history_many

    def blocked(*a, **k):
        gate.wait(5)
        return slow_market(*a, **k)

    pre.market.history_many = blocked
    try:
        t0 = time.time()
        d = client.get("/api/screener").json()
        assert time.time() - t0 < 2 and not d["coverage"]["technicals_ready"]   # computing in the background
    finally:
        gate.set()
    for _ in range(100):
        if pre.get("screener_tech"):
            break
        time.sleep(0.05)
    assert pre.get("screener_tech") is not None
    assert client.get("/api/screener").json()["coverage"]["technicals_ready"]


def test_fundamentals_loop_runs_in_its_own_thread(client):
    pre = client.app.state.precompute
    pre.fundamentals_delay, pre.fundamentals_check = 0, 3600
    pre.fundamentals.pause = 0
    started = threading.Event()
    real = pre.fundamentals._fetcher

    def fetch(s):
        started.set()
        return fake_fundamentals(s)

    pre.fundamentals._fetcher = fetch
    try:
        t = threading.Thread(target=pre._fund_loop, daemon=True)
        t.start()
        assert started.wait(5)
        for _ in range(200):
            if not pre.fundamentals.refreshing and pre.fundamentals.coverage(pre.screener_symbols())["with_fundamentals"]:
                break
            time.sleep(0.05)
        assert pre.fundamentals.coverage(pre.screener_symbols())["with_fundamentals"] == len(STOCKS)
    finally:
        pre._stop.set()
        pre.fundamentals._fetcher = real
    t.join(5)
    assert not t.is_alive()
    pre._stop.clear()


def test_fx_conversion_for_non_dollar_listings(client):
    pre = client.app.state.precompute
    pre.fundamentals.put("MC.PA", {**fake_fundamentals("MC.PA"), "currency": "EUR", "market_cap": 200e9})
    pre.refresh_screener_technicals()
    assert pre.get("screener_tech")["fx"]["EUR"] == pytest.approx(1.1)
    row = next(r for r in client.get("/api/screener", params={"q": "MC.PA"}).json()["rows"] if r["symbol"] == "MC.PA")
    assert row["market_cap"] == pytest.approx(220e9) and row["currency"] == "EUR"


def test_ser_clean_rows_are_json_numbers(client):
    pre = client.app.state.precompute
    pre.fundamentals.pause = 0
    pre.fundamentals.refresh(pre.screener_symbols()[:5])
    pre.refresh_screener_technicals()
    d = pre.screener(limit=5)
    for r in d["rows"]:
        for v in r.values():
            assert not (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))
    assert isinstance(pd.Timestamp(d["as_of"]), pd.Timestamp)
