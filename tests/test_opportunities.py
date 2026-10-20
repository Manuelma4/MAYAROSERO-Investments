import numpy as np
import pandas as pd

from tradebot.live.news import Headline, classify, is_relevant, parse_items
from tradebot.live.opportunities import OpportunityRules, evaluate, session_fraction


def daily(n=260, drift=0.001, seed=0, vol=1e6):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.012, n)))
    idx = pd.bdate_range(end="2026-10-19", periods=n, tz="UTC")
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                         "volume": vol}, index=idx)


NOW = pd.Timestamp("2026-10-20 17:00", tz="UTC")  # mid-session (55% elapsed)
NEWS = [Headline("Acme beats earnings estimates and raises guidance", "Reuters", "https://x", NOW.timestamp() - 3600, "earnings", True)]


def test_classify_catalysts():
    assert classify("Nvidia beats Q3 earnings") == "earnings"
    assert classify("Morgan Stanley upgrades Apple to Overweight") == "analyst"
    assert classify("Company to acquire rival in $5B deal") == "deal"
    assert classify("Stocks are moving today") is None


def test_parse_items_filters_old_and_unrelated():
    now = 1_800_000_000
    items = [
        {"title": "AAPL beats earnings", "publisher": "X", "link": "u", "providerPublishTime": now - 3600, "relatedTickers": ["AAPL"]},
        {"title": "Old news", "publisher": "X", "link": "u", "providerPublishTime": now - 5 * 86400, "relatedTickers": ["AAPL"]},
        {"title": "About MSFT", "publisher": "X", "link": "u", "providerPublishTime": now - 600, "relatedTickers": ["MSFT"]},
    ]
    h = parse_items(items, "AAPL", 36, now)
    assert [x.title for x in h] == ["AAPL beats earnings"] and h[0].catalyst == "earnings"


def test_session_fraction():
    assert 0.5 < session_fraction(NOW, crypto=False) < 0.6
    assert session_fraction(pd.Timestamp("2026-10-20 10:00", tz="UTC"), crypto=False) == 1.0  # closed


def test_surge_with_news_on_heavy_volume_qualifies_long():
    d = daily()
    last = float(d["close"].iloc[-1]) * 1.06
    o = evaluate("ACME", "Acme", d, today_volume=3e6, last_price=last, now=NOW, headlines=NEWS)
    assert o and o.direction == "long" and o.qualified and o.catalyst == "earnings"
    assert o.stop < o.entry < o.target and abs((o.target - o.entry) - 2 * (o.entry - o.stop)) < 1e-6
    assert o.rel_volume > 1.8 and o.sigma >= 2


def test_surge_without_news_is_watch_only():
    d = daily()
    o = evaluate("ACME", "Acme", d, 3e6, float(d["close"].iloc[-1]) * 1.06, NOW, [])
    assert o and not o.qualified and "No news" in o.reasons[-1]


def test_rejections():
    d = daily()
    p = float(d["close"].iloc[-1])
    assert evaluate("A", "A", d, 3e6, p * 1.01, NOW, NEWS) is None            # move too small
    assert evaluate("A", "A", d, 0.5e6, p * 1.06, NOW, NEWS) is None          # no volume confirmation
    down = daily(drift=-0.002, seed=1)
    assert evaluate("A", "A", down, 3e6, float(down["close"].iloc[-1]) * 1.06, NOW, NEWS) is None  # against trend
    thin = daily(vol=1000)
    assert evaluate("A", "A", thin, 3000, float(thin["close"].iloc[-1]) * 1.06, NOW, NEWS) is None  # illiquid


def test_fall_in_downtrend_is_short():
    d = daily(drift=-0.002, seed=3)
    o = evaluate("ACME", "Acme", d, 3e6, float(d["close"].iloc[-1]) * 0.94, NOW, NEWS)
    assert o and o.direction == "short" and o.target < o.entry < o.stop


def test_no_lookahead_uses_only_completed_bars():
    d = daily()
    p = float(d["close"].iloc[-1]) * 1.06
    a = evaluate("ACME", "Acme", d, 3e6, p, NOW, NEWS)
    # appending a future bar must not be required / used: evaluating on the same completed history is stable
    b = evaluate("ACME", "Acme", d.copy(), 3e6, p, NOW, NEWS)
    assert a.to_dict() == b.to_dict()
    assert OpportunityRules().min_move_pct == 3.0


def test_headline_relevance():
    assert is_relevant("Eli Lilly obesity drug wins approval", None, "LLY", "Eli Lilly")
    assert is_relevant("Why LLY stock jumped today", None, "LLY", "Eli Lilly")
    assert not is_relevant("Hypertriglyceridemia market set for growth", None, "LLY", "Eli Lilly")
    assert is_relevant("Morgan Stanley upgrades drug makers", ["LLY", "NVO"], "LLY", "Eli Lilly")
    assert not is_relevant("Five stocks to watch this week", ["LLY"], "LLY", "Eli Lilly")
    assert not is_relevant("Meta Platforms expands data centers", None, "MA", "Mastercard")
    assert is_relevant("Bitcoin rallies past resistance", None, "BTC/USDT", "Bitcoin")
