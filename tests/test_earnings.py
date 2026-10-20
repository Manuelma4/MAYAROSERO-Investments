"""Earnings calendar: parsing Yahoo's answers, caching, the upcoming list, average moves and the day-before alert.
Everything offline: yfinance is replaced by fakes."""

import sys
import types
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import make_ohlcv
from tradebot.api import create_app
from tradebot.api.market import MarketData
from tradebot.api.precompute import Precomputer
from tradebot.api.settings import Settings
from tradebot.api.store import EventStore
from tradebot.data import DataProvider
from tradebot.data import earnings as er

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def nvda_frame():
    """Shaped like `Ticker('NVDA').get_earnings_dates()` (index in New York time)."""
    idx = pd.DatetimeIndex([pd.Timestamp("2026-11-17 15:00", tz="America/New_York"),   # unconfirmed, after DST
                            pd.Timestamp("2026-08-26 16:00", tz="America/New_York"),
                            pd.Timestamp("2026-05-20 16:00", tz="America/New_York"),
                            pd.Timestamp("2026-02-25 16:00", tz="America/New_York")], name="Earnings Date")
    return pd.DataFrame({"EPS Estimate": [2.47, 2.09, 1.77, 1.54], "Reported EPS": [np.nan, 2.22, 1.87, 1.62],
                         "Surprise(%)": [np.nan, 6.16, 5.54, 5.32]}, index=idx)


def test_parse_earnings_dates_next_last_and_timing():
    d = er.parse_earnings_dates(nvda_frame(), "NVDA", NOW)
    assert d["next"]["date"] == "2026-11-17" and d["next"]["timing"] == "after_close"
    assert d["next"]["eps_estimate"] == 2.47 and "eps_actual" not in d["next"]
    assert d["last"] == {"date": "2026-08-26", "time": "2026-08-26T20:00:00+00:00", "timing": "after_close",
                         "eps_estimate": 2.09, "eps_actual": 2.22, "surprise_pct": 6.16}
    assert [h["date"] for h in d["history"]] == ["2026-08-26", "2026-05-20", "2026-02-25"]


def test_timing_classification():
    ny = "America/New_York"
    assert er.classify_timing(pd.Timestamp("2026-10-13 06:00", tz=ny), "JPM") == "before_open"
    assert er.classify_timing(pd.Timestamp("2026-10-13 12:30", tz=ny), "JPM") == "during"
    assert er.classify_timing(pd.Timestamp("2026-10-13 16:05", tz=ny), "JPM") == "after_close"
    assert er.classify_timing(pd.Timestamp("2026-10-13 00:00", tz=ny), "JPM") == "unknown"
    assert er.classify_timing(pd.Timestamp("2027-01-26 10:00", tz=ny), "MC.PA") == "unknown"   # non-US listing


def test_report_without_eps_stays_next_until_half_a_day_later():
    df = nvda_frame()
    just_after = datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc)   # 2 h after the report, no EPS yet
    assert er.parse_earnings_dates(df, "NVDA", just_after)["next"]["date"] == "2026-11-17"
    later = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    d = er.parse_earnings_dates(df, "NVDA", later)
    assert d["next"] is None and d["last"]["date"] == "2026-11-17"


def test_parse_calendar_fallback():
    cal = {"Earnings Date": [date(2026, 11, 2)], "Earnings Average": 1.98}
    assert er.parse_calendar(cal, "AAPL", NOW) == {"date": "2026-11-02", "time": None, "timing": "unknown",
                                                    "eps_estimate": 1.98}
    assert er.parse_calendar({"Earnings Date": [date(2026, 1, 2)]}, "AAPL", NOW) is None
    assert er.parse_calendar(None, "AAPL", NOW) is None


class FakeTicker:
    frames: dict = {}
    calendars: dict = {}

    def __init__(self, symbol):
        self.symbol = symbol

    def get_earnings_dates(self, limit=12):
        v = self.frames.get(self.symbol)
        if isinstance(v, Exception):
            raise v
        return v

    @property
    def calendar(self):
        v = self.calendars.get(self.symbol)
        if isinstance(v, Exception):
            raise v
        return v


@pytest.fixture
def fake_yf(monkeypatch):
    mod = types.ModuleType("yfinance")
    mod.Ticker = FakeTicker
    FakeTicker.frames, FakeTicker.calendars = {}, {}
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return FakeTicker


def test_fetch_earnings_with_mocked_yfinance(fake_yf):
    fake_yf.frames["NVDA"] = nvda_frame()
    fake_yf.frames["AAPL"] = RuntimeError("Too Many Requests")            # falls back to the calendar
    fake_yf.calendars["AAPL"] = {"Earnings Date": [date(2099, 1, 30)]}
    fake_yf.frames["BAD"] = RuntimeError("boom")
    fake_yf.calendars["BAD"] = RuntimeError("boom")
    fake_yf.frames["EMPTY"] = None
    r = er.fetch_earnings("NVDA")
    assert r["status"] == "ok" and r["last"]["eps_actual"] == 2.22
    a = er.fetch_earnings("AAPL")
    assert a["status"] == "ok" and a["next"]["date"] == "2099-01-30" and a["last"] is None
    assert er.fetch_earnings("BAD")["status"] == "unknown"     # never raises
    assert er.fetch_earnings("EMPTY")["status"] == "unknown"
    assert er.fetch_earnings("BTC/USDT")["status"] == "none"   # crypto has no earnings
    assert er.fetch_earnings("^GSPC")["status"] == "none"


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def counting_fetcher(results=None):
    calls = []

    def fn(symbol):
        calls.append(symbol)
        return (results or {}).get(symbol) or {"symbol": symbol, "status": "ok", "history": [],
                                                "next": {"date": "2026-10-21", "timing": "after_close"}, "last": None}
    fn.calls = calls
    return fn


def test_calendar_caches_12h_and_persists_in_sqlite(tmp_path):
    store = EventStore(tmp_path / "e.db")
    clock, fetch = Clock(), counting_fetcher({"BAD": er.unknown("BAD")})
    cal = er.EarningsCalendar(store, fetcher=fetch, clock=clock, pause=0)
    assert cal.get(["NVDA", "BAD"])["NVDA"]["status"] == "ok"
    assert fetch.calls == ["NVDA", "BAD"]
    cal.get(["NVDA", "BAD"])
    assert fetch.calls == ["NVDA", "BAD"]                     # served from memory
    cal2 = er.EarningsCalendar(store, fetcher=fetch, clock=clock, pause=0)   # a restart: SQLite cache
    assert cal2.get(["NVDA"])["NVDA"]["next"]["date"] == "2026-10-21" and fetch.calls == ["NVDA", "BAD"]
    clock.t += 3601                                          # failures are retried after an hour
    cal.get(["NVDA", "BAD"])
    assert fetch.calls == ["NVDA", "BAD", "BAD"]
    clock.t += 12 * 3600
    cal.get(["NVDA"])
    assert fetch.calls[-1] == "NVDA"                         # stale after 12 h
    assert cal.get(["X"], fetch=False)["X"]["status"] == "unknown"


def test_calendar_never_raises_and_does_not_wait_behind_a_refresh():
    def boom(symbol):
        raise RuntimeError("network down")

    cal = er.EarningsCalendar(fetcher=boom, pause=0)
    assert cal.get(["NVDA"])["NVDA"]["status"] == "unknown"
    cal2 = er.EarningsCalendar(fetcher=counting_fetcher(), pause=0)
    cal2._fetching.acquire()   # a background refresh is running
    try:
        assert cal2.get(["AAPL"])["AAPL"]["status"] == "unknown"
    finally:
        cal2._fetching.release()
    assert cal2.get(["AAPL"])["AAPL"]["status"] == "ok"


def test_upcoming_filter_and_order():
    recs = {
        "LATE": {"next": {"date": "2026-11-20", "timing": "after_close"}},
        "AFTER": {"next": {"date": "2026-10-22", "timing": "after_close"}, "avg_move": {"avg_abs_move_%": 5.0, "moves": [1, 2]}},
        "BEFORE": {"next": {"date": "2026-10-22", "timing": "before_open"}},
        "PAST": {"next": {"date": "2026-10-19", "timing": "before_open"}},
        "TODAY": {"next": {"date": "2026-10-20", "timing": "unknown"}},
        "NONE": {"status": "unknown", "next": None},
    }
    out = er.upcoming(recs, date(2026, 10, 20), 14, {"AFTER": {"held": True}}, {"AFTER": "After Inc"})
    assert [r["symbol"] for r in out] == ["TODAY", "BEFORE", "AFTER"]
    a = out[2]
    assert a["held"] and not a["pick"] and a["name"] == "After Inc" and a["days_until"] == 2
    assert a["avg_move_%"] == 5.0 and a["timing_text"] == "after the market closes"
    assert [r["symbol"] for r in er.upcoming(recs, date(2026, 10, 20), 0)] == ["TODAY"]


def bars_with_jumps():
    idx = pd.bdate_range("2026-01-01", "2026-10-16", tz="UTC")
    close = pd.Series(100.0, index=idx)
    # after-close report on Thu 2026-08-20: +10% on Fri 08-21
    close[close.index >= "2026-08-21"] *= 1.10
    # before-open report on Tue 2026-05-12: -5% that day
    close[close.index >= "2026-05-12"] *= 0.95
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0})


def test_average_move_uses_the_session_that_reacted():
    bars = bars_with_jumps()
    hist = [{"date": "2026-08-20", "timing": "after_close"}, {"date": "2026-05-12", "timing": "before_open"},
            {"date": "2026-03-01", "timing": "after_close"},            # a Sunday: reacts on Monday (flat)
            {"date": "2025-01-01", "timing": "after_close"}]            # before the data: skipped
    m = er.average_move(hist, bars, n=4)
    assert [x["move_%"] for x in m["moves"]] == [10.0, -5.0, 0.0]
    assert m["avg_abs_move_%"] == 5.0
    assert er.report_move({"date": "2026-08-20", "timing": "before_open"}, bars) == 0.0   # wrong day: no jump
    assert er.report_move({"date": "2026-08-20", "timing": "unknown"}, bars) == pytest.approx(10.0)   # both days
    assert er.average_move(hist, None) is None


def test_alert_phase_paris_vs_new_york():
    before = {"date": "2027-01-14", "time": "2027-01-14T12:00:00+00:00", "timing": "before_open"}   # 07:00 NY
    # Jan 13, 20:00 Paris (14:00 NY): the day before, both in Paris and New York
    assert er.alert_phase(before, datetime(2027, 1, 13, 19, 0, tzinfo=timezone.utc)) == "tomorrow"
    # Jan 14, 00:30 Paris = still Jan 13 in New York: in Paris it's report day, too late for "tomorrow"
    t = datetime(2027, 1, 13, 23, 30, tzinfo=timezone.utc)
    assert er.alert_phase(before, t) == "today"                      # catch-up: report at 13:00 Paris
    assert er.alert_phase(before, t, tz="America/New_York") == "tomorrow"
    # Jan 13, 07:00 Paris: the day before, but too early to wake anyone
    assert er.alert_phase(before, datetime(2027, 1, 13, 6, 0, tzinfo=timezone.utc)) is None
    # report day, less than an hour before the report: nothing
    assert er.alert_phase(before, datetime(2027, 1, 14, 11, 30, tzinfo=timezone.utc)) is None
    after = {"date": "2026-11-17", "time": "2026-11-17T21:00:00+00:00", "timing": "after_close"}   # 16:00 NY
    assert er.alert_phase(after, datetime(2026, 11, 16, 22, 30, tzinfo=timezone.utc)) == "tomorrow"   # 23:30 Paris
    assert er.alert_phase(after, datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc)) == "today"
    assert er.alert_phase({"date": "2026-11-17", "time": None, "timing": "unknown"},
                          datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)) is None   # no time: no catch-up
    assert er.alert_phase(None, NOW) is None


def test_alert_text():
    nxt = {"date": "2026-11-17", "timing": "after_close", "eps_estimate": 2.47}
    t = er.alert_text("NVDA", "NVIDIA", nxt, "tomorrow", ["you hold it"],
                      {"avg_abs_move_%": 7.1, "moves": [1, 2, 3, 4]})
    assert t.startswith("[EARNINGS TOMORROW] NVDA (NVIDIA) reports after the close.")
    assert "last 4 reports: avg ±7.1%" in t and "2.47 per share" in t and "you hold it" in t


class Bars(DataProvider):
    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        df = make_ohlcv(400, seed=sum(map(ord, symbol)) % 50)
        df.index = pd.bdate_range(end="2026-10-16", periods=400, tz="UTC")
        return df.tail(limit) if limit else df


def test_precompute_earnings_alert_is_sent_once(tmp_path):
    store = EventStore(tmp_path / "a.db")
    store.save_watchlist("Mine", ["AAPL"])
    sent = []
    nxt = {"date": "2026-10-21", "time": "2026-10-21T20:00:00+00:00", "timing": "after_close", "eps_estimate": 1.5}
    hist = [{"date": "2026-07-22", "timing": "after_close"}, {"date": "2026-04-22", "timing": "after_close"}]
    fetch = counting_fetcher({"AAPL": {"symbol": "AAPL", "status": "ok", "next": nxt, "last": hist[0], "history": hist},
                              "NVDA": {"symbol": "NVDA", "status": "ok", "next": dict(nxt), "last": None, "history": []}})

    def make():
        cal = er.EarningsCalendar(store, fetcher=fetch, pause=0)
        return Precomputer(MarketData(lambda n, e: Bars()), store=store, earnings=cal, notify=sent.append,
                           holdings=lambda: {"positions": [{"symbol": "NVDA"}, {"symbol": "BTC/USDT"}]})

    pre = make()
    pre.put("picks:quality_momentum", {"picks": [{"symbol": "MSFT"}]})
    res = pre.refresh_earnings(NOW)
    assert res["fetched"] == len(pre.earnings_interest()) and "BTC/USDT" not in pre.earnings_interest()
    assert pre.earnings.cached(["AAPL"])["AAPL"]["avg_move"]["moves"]   # average move from daily bars
    assert pre.refresh_earnings(NOW)["fetched"] == 0                     # same day: nothing new to fetch
    at = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)               # 11:00 in Paris, the day before
    evs = pre.check_earnings(at)
    assert sorted(e["symbol"] for e in evs) == ["AAPL", "MSFT", "NVDA"]  # watchlist, pick, held
    aapl = next(e for e in evs if e["symbol"] == "AAPL")
    assert aapl["type"] == "earnings" and aapl["reasons"] == ["on your watchlist"] and aapl["phase"] == "tomorrow"
    assert any(t.startswith("[EARNINGS TOMORROW] AAPL") for t in sent)
    assert pre.check_earnings(at) == []
    assert make().check_earnings(at) == []                               # deduplicated in SQLite (restart)
    assert len(store.list("earnings")) == 3 and len(sent) == 3
    up = pre.upcoming_earnings(7, mine_only=True, now=NOW)
    assert {(i["symbol"], i["held"], i["pick"], i["watchlist"]) for i in up["items"]} == {
        ("AAPL", False, False, True), ("MSFT", False, True, False), ("NVDA", True, False, False)}


def test_earnings_api(tmp_path):
    settings = Settings(db_path=tmp_path / "t.db", static_dir=None, api_token=None, autostart_live=False,
                        precompute=False)
    app = create_app(settings, provider_factory=lambda n, e: Bars(), config={})
    with TestClient(app) as c:
        app.state.store.save_watchlist("Mine", ["AAPL"])
        r = c.get("/api/earnings", params={"symbols": "aapl,BTC/USDT"})
        assert r.status_code == 200
        items = {i["symbol"]: i for i in r.json()["items"]}
        assert items["AAPL"]["status"] == "ok" and items["AAPL"]["next"]["timing_text"]
        assert "avg_move" in items["AAPL"] and "_at" not in items["AAPL"]
        assert items["BTC/USDT"]["status"] == "none"
        assert c.get("/api/earnings", params={"symbols": "bad symbol!"}).status_code == 422
        app.state.precompute.refresh_earnings()
        up = c.get("/api/earnings/upcoming", params={"days": 30}).json()
        assert up["items"] and up["hint"]
        dates = [i["date"] for i in up["items"]]
        assert dates == sorted(dates)
        mine = c.get("/api/earnings/upcoming", params={"days": 30, "mine": True}).json()["items"]
        assert [i["symbol"] for i in mine] == ["AAPL"] and mine[0]["watchlist"]
