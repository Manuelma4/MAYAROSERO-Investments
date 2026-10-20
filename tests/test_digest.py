"""Weekly digest and portfolio drift: schedule (Europe/Paris), composition, weekly dedupe, drift maths,
suggestion amounts and the API endpoints (offline, synthetic data)."""

from datetime import datetime, timedelta, timezone

import pytest

from tradebot.api.store import EventStore
from tradebot.live import digest as dg
from tradebot.live import drift as dr

from test_api import client  # noqa: F401  (fixture)

UTC = timezone.utc


# ---- schedule -----------------------------------------------------------------------------------
def test_schedule_from_config_and_env():
    assert dg.schedule_from({}, {}) == dg.Schedule(6, 18, 0, "Europe/Paris", True)
    s = dg.schedule_from({"digest": {"day": "friday", "hour": "17:30"}}, {})
    assert (s.day, s.hour, s.minute) == (4, 17, 30)
    s = dg.schedule_from({"digest": {"day": "friday"}}, {"DIGEST_DAY": "sat", "DIGEST_HOUR": "9", "DIGEST_ENABLED": "0"})
    assert (s.day, s.hour, s.enabled) == (5, 9, False)
    assert dg.schedule_from({}, {"DIGEST_DAY": "7"}).day == 6     # cron-style Sunday
    with pytest.raises(ValueError):
        dg.schedule_from({}, {"DIGEST_DAY": "someday"})
    with pytest.raises(ValueError):
        dg.schedule_from({}, {"DIGEST_HOUR": "25"})


def test_slot_is_18h_paris_in_summer_and_winter():
    sch = dg.Schedule()
    # Sunday 2026-10-18 (summer time, UTC+2): 18:00 Paris = 16:00 UTC
    assert dg.last_slot(datetime(2026, 10, 18, 16, 5, tzinfo=UTC), sch) == datetime(2026, 10, 18, 16, 0, tzinfo=UTC)
    assert dg.due_period(datetime(2026, 10, 18, 15, 59, tzinfo=UTC), sch) is None        # 17:59 Paris
    assert dg.due_period(datetime(2026, 10, 18, 16, 0, tzinfo=UTC), sch) == "2026-10-18"
    # Sunday 2026-11-01 (winter time, UTC+1): 18:00 Paris = 17:00 UTC
    assert dg.due_period(datetime(2026, 11, 1, 16, 30, tzinfo=UTC), sch) is None
    assert dg.due_period(datetime(2026, 11, 1, 17, 0, tzinfo=UTC), sch) == "2026-11-01"
    # Within the grace window the late send still happens; a Tuesday start does not send last Sunday's.
    assert dg.due_period(datetime(2026, 11, 2, 4, 0, tzinfo=UTC), sch) == "2026-11-01"
    assert dg.due_period(datetime(2026, 11, 3, 9, 0, tzinfo=UTC), sch) is None
    assert dg.next_slot(datetime(2026, 10, 20, 9, 0, tzinfo=UTC), sch) == datetime(2026, 10, 25, 17, 0, tzinfo=UTC)
    assert dg.due_period(datetime(2026, 10, 18, 16, 0, tzinfo=UTC), dg.Schedule(enabled=False)) is None


# ---- composition --------------------------------------------------------------------------------
NOW = datetime(2026, 10, 18, 16, 0, tzinfo=UTC)
TRACK = {"started": "2026-10-01", "days": 12, "too_early": True,
         "picks": {"return_%": 2.4, "spy_%": 1.1}, "ideas": {"closed_count": 3, "win_rate": 66.7, "avg_r": 0.4}}
MOOD = {"label": "Neutral", "advice": "Mixed signals: stay invested but respect stop-losses."}


def test_compose_has_every_section_in_plain_english():
    picks = [{"created_at": "2026-10-15T10:00:00Z", "date": "2026-09-30", "buy": ["TMO", "JNJ"], "sell": ["NVDA"]}]
    alerts = [{"created_at": "2026-10-16T14:00:00Z", "symbol": "AAPL", "kind": "above", "value": 250.0},
              {"created_at": "2026-10-17T14:00:00Z", "symbol": "BTC/USDT", "kind": "move", "value": 5.0, "change_pct": -6.2}]
    drift = {"status": "drifted", "total_drift": 12.0, "max_drift": 8.0,
             "suggestion": "Sell about €300 of NVDA, buy about €250 of JNJ."}
    text = dg.compose(NOW, picks, alerts, TRACK, MOOD, drift)
    assert text.startswith("MAYAROSERO weekly digest · 18 Oct 2026")
    assert "Market mood: Neutral." in text
    assert "Picks changed (review of 30 Sep): buy TMO, JNJ; sell NVDA." in text
    assert "2 fired (AAPL above 250; BTC/USDT moved -6.2%)" in text
    assert "picks +2.4% vs S&P 500 +1.1% (ahead of)" in text and "3 closed, 67% winners" in text
    assert "Too early to judge" in text
    assert "Sell about €300 of NVDA, buy about €250 of JNJ." in text
    assert len(text) <= dg.MAX_CHARS


def test_compose_quiet_week_and_missing_data():
    text = dg.compose(NOW, [], [], None, None, None)
    assert "Picks: no change this week" in text and "none fired" in text
    assert "unavailable right now" in text and "Portfolio" not in text
    # an old review recorded this week (first start) is not a change "this week"
    old = [{"created_at": "2026-10-15T10:00:00Z", "date": "2026-06-30", "buy": ["A"], "sell": []}]
    assert "no change this week" in dg.compose(NOW, old, [], {"started": None}, MOOD)
    assert "starts after the next US market close" in dg.compose(NOW, [], [], {"started": None}, MOOD)


def test_compose_stays_under_whatsapp_limit():
    alerts = [{"created_at": "2026-10-16T14:00:00Z", "symbol": f"SYM{i}", "kind": "below", "value": 10.0 + i}
              for i in range(40)]
    drift = {"status": "drifted", "total_drift": 40.0, "max_drift": 20.0, "suggestion": "Sell about €1 of X. " * 80}
    text = dg.compose(NOW, [], alerts, TRACK, MOOD, drift, max_chars=600)
    assert len(text) <= 600 and text.endswith("Information, not advice.")
    assert "and 36 more" in text


def test_week_events_keeps_the_last_7_days_only():
    ev = [{"created_at": "2026-10-18T10:00:00Z"}, {"created_at": "2026-10-11T15:59:00Z"}, {"created_at": "bad"}]
    assert dg.week_events(ev, NOW) == ev[:1]


# ---- drift --------------------------------------------------------------------------------------
PLAN = {"amount": 10000, "currency": "EUR", "risk": "balanced", "fx_usd_per_unit": 1.0,
        "mix": {"core": 0.7, "satellite": 0.2, "anchor": 0.1},
        "lines": [{"symbol": "NVDA", "name": "Nvidia", "role": "core", "invested": 1000},
                  {"symbol": "JNJ", "name": "Johnson & Johnson", "role": "core", "invested": 1000},
                  {"symbol": "XYZ", "name": "Idea", "role": "satellite", "invested": 500},
                  {"symbol": "SPY", "name": "S&P 500 ETF", "role": "anchor", "invested": 1000}]}


def pos(sym, value, strategy="core", price=100.0):
    return {"symbol": sym, "side": "long", "qty": value / price, "price": price, "entry": price, "strategy": strategy}


def test_target_keeps_lasting_positions_only():
    t = dr.target_from_plan(PLAN, "2026-10-18T00:00:00Z")
    assert t["weights"] == {"NVDA": 0.1, "JNJ": 0.1, "SPY": 0.1}     # the live idea is not a lasting target
    assert t["bucket_share"] == pytest.approx(0.7) and t["currency"] == "EUR" and t["amount"] == 10000


def test_drift_on_target_and_not_invested():
    t = dr.target_from_plan(PLAN, "x")
    on = dr.compute_drift(t, [pos("NVDA", 1100), pos("JNJ", 950), pos("SPY", 1000)], 10000)
    assert on["status"] == "on_target" and not on["breached"]
    assert on["max_drift"] == pytest.approx(1.0)
    # Invest-now positions outside the plan are not "held" plan positions: nothing to compare yet
    none = dr.compute_drift(t, [pos("TSLA", 800, "opportunity"), pos("NVDA", 900, "opportunity")], 10000)
    assert none["status"] == "not_invested" and not none["breached"]
    assert dr.compute_drift(t, [], 0)["status"] == "empty"


def test_drift_position_breach_with_suggestion_amounts():
    t = dr.target_from_plan(PLAN, "x")
    # NVDA ran up to 18% of the account, JNJ is only 5%; an Invest-now idea sits in the ideas bucket
    d = dr.compute_drift(t, [pos("NVDA", 1800), pos("JNJ", 500), pos("SPY", 1000), pos("TSLA", 400, "opportunity")],
                         10000, to_target_ccy=1.0)
    assert d["status"] == "drifted" and d["breached"]
    rows = {r["symbol"]: r for r in d["rows"]}
    assert rows["NVDA"]["drift"] == pytest.approx(8.0) and rows["JNJ"]["drift"] == pytest.approx(-5.0)
    assert "TSLA" not in rows                                  # self-managed idea: never "sell" advice
    assert rows[None]["current_%"] == pytest.approx(67.0)      # cash 63% + idea 4%
    assert d["max_drift"] == pytest.approx(8.0)
    assert d["sell"] == [{"symbol": "NVDA", "name": "Nvidia", "amount": 800.0}]
    assert d["buy"] == [{"symbol": "JNJ", "name": "Johnson & Johnson", "amount": 500.0}]
    assert d["suggestion"] == "Sell about €800 of NVDA, buy about €500 of JNJ."
    assert "NVDA is 18% of it instead of 10%" in d["message"]


def test_drift_total_breach_currency_conversion_and_off_plan_holding():
    t = dr.target_from_plan(PLAN, "x")
    # USD account worth $11,000 with EURUSD 1.10 -> €10,000. AAPL is a long-term holding outside the plan.
    d = dr.compute_drift(t, [pos("NVDA", 1430), pos("JNJ", 660), pos("SPY", 660), pos("AAPL", 495),
                                 pos("MSFT", 495)],
                         11000, to_target_ccy=1 / 1.10)
    rows = {r["symbol"]: r for r in d["rows"]}
    assert rows["NVDA"]["drift"] == pytest.approx(3.0) and rows["JNJ"]["drift"] == pytest.approx(-4.0)
    assert rows["AAPL"]["in_plan"] is False and rows["AAPL"]["drift"] == pytest.approx(4.5)
    assert d["max_drift"] < 5 and d["total_drift"] > 10 and d["breached"]   # many small gaps add up
    assert d["total_drift"] == pytest.approx(12.0)
    amounts = {x["symbol"]: x["amount"] for x in d["sell"] + d["buy"]}
    assert amounts == {"NVDA": 300.0, "AAPL": 450.0, "MSFT": 450.0, "JNJ": 400.0, "SPY": 400.0}
    assert d["suggestion"] == ("Sell about €450 of AAPL, sell about €450 of MSFT, sell about €300 of NVDA, "
                               "buy about €400 of JNJ, buy about €400 of SPY.")


def test_round_amount_and_money():
    assert [dr.round_amount(x) for x in (3, 74, 196, 260, 1234)] == [10, 70, 200, 250, 1250]
    assert dr.money(1250, "EUR") == "€1,250" and dr.money(80, "USD") == "$80" and dr.money(5, "GBP") == "5 GBP"


# ---- store dedupe -------------------------------------------------------------------------------
def test_claim_notice_is_once_per_period_and_survives_restart(tmp_path):
    path = tmp_path / "d.db"
    s = EventStore(path)
    assert s.claim_notice("digest", "2026-10-18", NOW)
    assert not s.claim_notice("digest", "2026-10-18", NOW + timedelta(hours=1))
    s2 = EventStore(path)   # restart
    assert not s2.claim_notice("digest", "2026-10-18", NOW + timedelta(hours=2))
    assert s2.last_notice("digest")["period"] == "2026-10-18"
    # drift: at most once every 7 days whatever the period id
    assert s2.claim_notice("drift", "2026-10-18", NOW, min_gap=timedelta(days=7))
    assert not s2.claim_notice("drift", "2026-10-20", NOW + timedelta(days=2), min_gap=timedelta(days=7))
    assert s2.claim_notice("drift", "2026-10-25", NOW + timedelta(days=7), min_gap=timedelta(days=7))
    s2.set_value("k", {"a": 1})
    assert EventStore(path).get_value("k") == {"a": 1} and s2.delete_value("k") and s2.get_value("k") is None


# ---- precomputer + endpoints --------------------------------------------------------------------
def test_digest_sent_once_per_week_from_the_loop(client):  # noqa: F811
    pre = client.app.state.precompute
    sent = []
    pre.notify = sent.append
    pre.put("today", {"mood": MOOD})
    assert pre.check_digest(datetime(2026, 10, 18, 15, 0, tzinfo=UTC)) is None      # 17:00 Paris: not yet
    text = pre.check_digest(datetime(2026, 10, 18, 16, 5, tzinfo=UTC))
    assert text and sent == [text] and "Market mood: Neutral." in text
    assert pre.check_digest(datetime(2026, 10, 18, 16, 10, tzinfo=UTC)) is None     # same week: deduplicated
    assert pre.check_digest(datetime(2026, 10, 25, 17, 1, tzinfo=UTC))              # next Sunday (winter time)
    assert len(sent) == 2


def test_digest_endpoints(client):  # noqa: F811
    d = client.get("/api/digest/preview").json()
    assert d["text"].startswith("MAYAROSERO weekly digest") and d["chars"] == len(d["text"]) <= 1200
    assert d["schedule"]["day"] == "Sunday" and d["schedule"]["hour"] == 18
    assert d["schedule"]["timezone"] == "Europe/Paris" and d["schedule"]["next"]
    assert client.post("/api/digest/send-test").status_code in (415, 422)
    assert client.post("/api/digest/send-test", content="confirm=true",
                       headers={"content-type": "application/x-www-form-urlencoded"}).status_code in (415, 422)
    assert client.post("/api/digest/send-test", json={"confirm": False}).status_code == 400
    sent = []
    client.app.state.notify = lambda text: sent.append(text) or ["console"]
    r = client.post("/api/digest/send-test", json={"confirm": True}).json()
    assert r["sent"] and r["channels"] == ["console"] and sent == [r["text"]]
    assert client.app.state.store.last_notice("digest") is None   # a test send is not the weekly one


def test_portfolio_target_and_drift_endpoints(client):  # noqa: F811
    st = client.app.state
    assert client.get("/api/portfolio/drift").json()["status"] == "no_target"
    st.precompute.run_once(predictions=False)
    body = {"amount": 10000, "currency": "USD", "risk": "balanced"}
    d = client.post("/api/portfolio/target", json=body).json()
    target = st.store.get_value("portfolio_target")
    assert target["currency"] == "USD" and target["weights"] and target["risk"] == "balanced"
    assert d["status"] == "not_invested" and d["target"]["amount"] == 10000   # practice account holds none of it
    # hold the plan's first position at 3x its weight in the practice account: drift alert, once a week
    sym, w = next(iter(target["weights"].items()))
    price = st.market.quote(sym)["price"]
    equity = st.paper.cash
    st.paper.open(sym, "plan", "long", price, price * 0.5, None, "2026-10-18T00:00:00Z", qty=equity * w * 3 / price)
    d = client.get("/api/portfolio/drift").json()
    assert d["status"] == "drifted" and d["breached"] and d["source"] == "practice account"
    assert any(x["symbol"] == sym for x in d["sell"]) and d["suggestion"].startswith("Sell about $")
    sent = []
    st.precompute.notify = sent.append
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    assert st.precompute.check_drift(now) and len(sent) == 1 and sent[0].startswith("[PORTFOLIO DRIFT]")
    assert "Nothing is traded automatically" in sent[0]
    assert st.precompute.check_drift(now + timedelta(days=3)) is None and len(sent) == 1
    assert st.precompute.check_drift(now + timedelta(days=7, minutes=1)) and len(sent) == 2
    assert st.paper.positions_list()[0]["qty"] == pytest.approx(equity * w * 3 / price)   # never trades
    # the digest mentions the drift
    assert "Portfolio drift" in client.get("/api/digest/preview").json()["text"]
    assert client.delete("/api/portfolio/target").json() == {"deleted": True}
    assert client.get("/api/portfolio/drift").json()["status"] == "no_target"
