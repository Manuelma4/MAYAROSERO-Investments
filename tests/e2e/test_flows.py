"""End-to-end flows in a real browser, fully offline.

The real FastAPI app (`tradebot.api.create_app`) runs in a uvicorn thread on a free port, serving the built
React app from web/dist, with a deterministic synthetic market-data provider (no Yahoo, no exchange, no news).
Results are precomputed once before the browser starts, like the live server does at startup.

Every flow runs on a desktop (1440x900) and a phone (390x844) viewport and fails on any console error,
uncaught page error or unexpected failed request.

Skips cleanly when Playwright, Chromium or web/dist is missing. Build first: `cd web && npm run build`.
Run only these: `pytest -m e2e`; skip them: `pytest -m "not e2e"`.
"""

from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

import json
import re
import socket
import threading
import time
import urllib.request
import zlib
from pathlib import Path

import pandas as pd
import pytest

from conftest import make_ohlcv
from tradebot.data import DataProvider

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "web" / "dist"
CHROME = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "phone": {"width": 390, "height": 844}}

# Responses that are an expected, plain-English "not ready" answer in this setup (predictions are not
# precomputed here, to keep the run fast). The page must show the message instead of failing.
EXPECTED_FAILURES = {("/api/predictions", 503)}

sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright is not installed")
if not (DIST / "index.html").exists():
    pytest.skip("web/dist is missing: run `cd web && npm run build` first", allow_module_level=True)

_FREQ = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h",
         "1d": "1D", "1wk": "7D", "1w": "7D"}


class E2EProvider(DataProvider):
    """Deterministic synthetic candles for any stock, index, FX or crypto symbol, ending now.

    Each symbol gets its own seed and drift, so rankings, movers and the market mood look like a real
    (mostly rising) market. The VIX sits at a normal level and crypto trades at crypto-like prices.
    """

    N = 1800

    def history(self, symbol, timeframe, start=None, end=None, limit=None):
        if symbol in ("MISSING", "ZZZZ"):
            raise ValueError(f"No data for {symbol}")
        seed = zlib.crc32(symbol.encode()) % 10_000
        freq = _FREQ.get(timeframe, "1D")
        drift = 0.0006 if symbol in ("SPY", "^GSPC") else -0.0002 + (seed % 9) * 0.0001
        df = make_ohlcv(self.N, seed=seed, drift=drift, vol=0.014, cycle=0.0)
        now = pd.Timestamp.now(tz="UTC")
        last = now.floor("D") if freq in ("1D", "7D") else now.floor(pd.Timedelta(freq))
        df.index = pd.date_range(end=last, periods=len(df), freq=freq)
        px = ["open", "high", "low", "close"]
        if symbol == "^VIX":
            df[px] = df[px] * (17.0 / df["close"].iloc[-1])
        elif symbol.startswith("BTC/"):
            df[px] = df[px] * (65_000.0 / df["close"].iloc[-1])
        elif symbol.endswith("=X"):
            df[px] = df[px] * (1.1 / df["close"].iloc[-1])
        if start:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        if end:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]
        return df.tail(limit) if limit else df


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn

    import tradebot.ai.analyst as analyst
    from tradebot.api import create_app
    from tradebot.api.settings import Settings
    from tradebot.live import PaperBroker, Scanner
    from tradebot.live.scanner import WatchItem

    tmp = tmp_path_factory.mktemp("e2e")
    prov = E2EProvider()
    mp = pytest.MonkeyPatch()
    mp.setattr(analyst, "fundamentals", lambda symbol: {})   # the stock page must not call Yahoo
    mp.setenv("ANTHROPIC_API_KEY", "")

    settings = Settings(db_path=tmp / "e2e.db", static_dir=DIST, api_token=None, autostart_live=False,
                        precompute=False, cors_origins=[])

    def scanner_factory(cfg):
        sc = Scanner([WatchItem("yahoo", "AAPL", "1d", [{"name": "ema_cross_rsi"}])], [],
                     PaperBroker(tmp / "paper.json"))
        sc._providers[("yahoo", "binance")] = prov
        return sc

    app = create_app(settings, provider_factory=lambda name, exchange: prov, config={"poll_seconds": 60},
                     scanner_factory=scanner_factory)
    # Precompute before the browser opens, as the live server does at startup (predictions are the heavy
    # ML part and are left out to keep the run fast; the Predict page then shows its "being computed" note).
    pre = app.state.precompute
    pre.run_once(predictions=False)
    assert pre.get("today") is not None, pre.last_error
    pre.put("opportunities", {"as_of": pd.Timestamp.now(tz="UTC").isoformat(), "us_market_open": False,
                              "items": []})   # the live news scan needs the network: start from "nothing now"
    pre.fundamentals.refresh(pre.screener_symbols(), wait=True)   # offline fake fundamentals (tests/conftest.py)
    pre.refresh_screener_technicals()

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not srv.started:
        if time.time() > deadline or not thread.is_alive():
            pytest.fail("uvicorn did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        kw = {"executable_path": str(CHROME)} if CHROME.exists() else {}
        try:
            b = pw.chromium.launch(headless=True, **kw)
        except Exception as exc:  # no browser installed for this Playwright version
            pytest.skip(f"Chromium is not available: {exc}")
        yield b
        b.close()


class Page:
    """A browser page with error collection: console errors, page errors and failed requests."""

    def __init__(self, page, base: str):
        self.page = page
        self.base = base
        self.problems: list[str] = []
        self.expected_urls: set[str] = set()
        self.expected_failures = set(EXPECTED_FAILURES)   # a test may add the failures its flow provokes
        page.on("pageerror", lambda e: self.problems.append(f"page error: {e}"))
        page.on("console", self._console)
        page.on("response", self._response)
        page.on("requestfailed", self._failed)

    def _console(self, msg):
        if msg.type != "error":
            return
        url = (msg.location or {}).get("url", "")
        if msg.text.startswith("Failed to load resource") and url in self.expected_urls:
            return
        self.problems.append(f"console error: {msg.text} ({url})")

    def _response(self, r):
        if r.status < 400:
            return
        path = r.url.split("?")[0].replace(self.base, "")
        if (path, r.status) in self.expected_failures:
            self.expected_urls.add(r.url)
        elif r.request.method == "GET":
            self.problems.append(f"HTTP {r.status} {r.request.method} {r.url}")
        else:   # a refused POST (validation) is part of a flow; the test checks the message shown
            self.expected_urls.add(r.url)

    def _failed(self, req):
        if req.url.startswith(self.base) and "net::ERR_ABORTED" not in (req.failure or ""):
            self.problems.append(f"request failed: {req.url} {req.failure}")

    def goto(self, path: str):
        self.page.goto(self.base + path)

    def heading(self, text: str):
        return self.page.get_by_role("heading", level=1, name=text)

    def check(self):
        assert not self.problems, "\n".join(self.problems)


@pytest.fixture(params=list(VIEWPORTS))
def ui(request, server, browser):
    ctx = browser.new_context(viewport=VIEWPORTS[request.param], service_workers="block")
    if not request.node.get_closest_marker("first_visit"):
        # A returning visitor: the first-visit tour was already seen (it is tested on its own below).
        ctx.add_init_script("try { localStorage.setItem('mri.tour', 'done') } catch (e) {}")
    # Offline guarantee: anything that is not this server is refused (and reported).
    blocked: list[str] = []

    def guard(route):
        if route.request.url.startswith((server, server.replace("http", "ws"))):
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort()

    ctx.route("**/*", guard)
    ctx.set_default_timeout(20_000)
    p = Page(ctx.new_page(), server)
    p.viewport = request.param
    yield p
    ctx.close()
    assert not blocked, f"requests to the outside world: {blocked}"


def expect(locator):
    return sync_api.expect(locator)


# ------------------------------------------------------------------------------------------------ flows

def test_today_loads_with_picks(ui):
    ui.goto("/")
    expect(ui.heading("Today")).to_be_visible()
    expect(ui.page.locator(".mood-label")).to_be_visible()
    holds = ui.page.locator(".hold-list li .hold-sym")
    expect(holds.first).to_be_visible()
    assert holds.count() >= 3
    expect(ui.page.get_by_role("heading", name="Rising most today")).to_be_visible()
    expect(ui.page.locator(".mcard-price").first).to_be_visible()   # index / crypto cards have prices
    track = ui.page.locator(".card", has=ui.page.get_by_role("heading", name=re.compile("Live track record")))
    expect(track.get_by_text("Too early to judge")).to_be_visible()   # fresh database: honest "just started"
    ui.check()


DESKTOP_NAV = [("Today", "/", "Today"), ("My portfolio", "/portfolio", "My portfolio"),
               ("Discover", "/discover", "The world's leading companies"), ("Beat the S&P", "/picks", "Beat the S&P"),
               ("Invest now", "/now", "Invest now"), ("Alerts", "/alerts", "Alerts"), ("Charts", "/charts", "Charts"),
               ("Predict", "/predict", "Predict"), ("Backtest", "/backtest", "Backtest"), ("Learn", "/learn", "Learn"),
               ("Settings", "/settings", "Settings")]
PHONE_NAV = [("Portfolio", "/portfolio", "My portfolio"), ("Now", "/now", "Invest now"),
             ("More", "/settings", "Settings"), ("Today", "/", "Today")]
PHONE_TOOLS = [("Picks", "/picks", "Beat the S&P"), ("Discover", "/discover", "The world's leading companies"),
               ("Alerts", "/alerts", "Alerts"), ("Charts", "/charts", "Charts"), ("Predict", "/predict", "Predict"),
               ("Backtest", "/backtest", "Backtest"), ("Learn", "/learn", "Learn")]


def _settled(ui, path: str):
    """Page-specific content that proves the page finished loading (not just its title)."""
    p = ui.page
    if path == "/portfolio":
        expect(p.get_by_role("heading", name="What to buy")).to_be_visible(timeout=30_000)
    elif path == "/discover":
        expect(p.locator(".srow").first).to_be_visible()
    elif path == "/picks":
        expect(p.get_by_role("heading", name="Hold now")).to_be_visible(timeout=30_000)
    elif path == "/now":
        expect(p.get_by_text("Nothing qualifies right now")).to_be_visible()
    elif path == "/alerts":
        expect(p.get_by_role("heading", name="My price alerts")).to_be_visible()
    elif path == "/charts":
        expect(p.get_by_role("heading", name="Structure")).to_be_visible(timeout=30_000)
    elif path == "/predict":
        expect(p.get_by_role("alert")).to_contain_text("Predictions are being computed")
    elif path == "/backtest":
        expect(p.get_by_role("heading", name="Equity curve")).to_be_visible(timeout=30_000)
    elif path == "/settings":
        expect(p.get_by_role("heading", name="Appearance")).to_be_visible()
    elif path == "/learn":
        expect(p.get_by_role("heading", name=re.compile("Glossary"))).to_be_visible()
    elif path == "/":
        expect(p.locator(".hold-list")).to_be_visible()
    width = p.viewport_size["width"]
    scroll = p.evaluate("document.documentElement.scrollWidth")
    assert scroll <= width, f"{path} scrolls sideways at {width}px ({scroll}px wide)"


def test_navigate_every_page(ui):
    ui.goto("/")
    expect(ui.heading("Today")).to_be_visible()
    nav = ui.page.get_by_role("navigation", name="Main")
    if ui.viewport == "desktop":
        for label, path, title in DESKTOP_NAV:
            # Exact names; Alerts may carry "(N unread)" for screen readers.
            nav.get_by_role("link", name=re.compile(rf"^{re.escape(label)}(\s*\(\d+ unread\))?$")).click()
            ui.page.wait_for_url(ui.base + path)
            expect(ui.heading(title)).to_be_visible()
            _settled(ui, path)
    else:
        for label, path, title in PHONE_NAV:   # bottom navigation
            link = nav.get_by_role("link", name=label, exact=True)
            expect(link).to_be_visible()
            link.click()
            ui.page.wait_for_url(ui.base + path)
            expect(ui.heading(title)).to_be_visible()
            _settled(ui, path)
        for label, path, title in PHONE_TOOLS:   # the rest is under More › Tools
            nav.get_by_role("link", name="More", exact=True).click()
            ui.page.get_by_role("main").get_by_role("link", name=label, exact=True).click()
            ui.page.wait_for_url(ui.base + path)
            expect(ui.heading(title)).to_be_visible()
            _settled(ui, path)
    ui.check()


def test_search_opens_stock_page(ui):
    ui.goto("/")
    box = ui.page.get_by_label("Search symbol")
    box.fill("NVDA")
    ui.page.locator(".search-pop button", has_text="NVDA").first.click()
    ui.page.wait_for_url(ui.base + "/stock/NVDA")
    expect(ui.heading("NVIDIA")).to_be_visible()
    expect(ui.page.get_by_role("heading", name="The engine's view")).to_be_visible()
    # Keyboard: type and press Enter opens the best match.
    box.fill("MSFT")
    box.press("Enter")
    ui.page.wait_for_url(ui.base + "/stock/MSFT")
    expect(ui.heading("Microsoft")).to_be_visible()
    ui.check()


def test_price_alert_refuses_passed_level_then_shows_on_alerts(ui):
    symbol = "AAPL" if ui.viewport == "desktop" else "AMZN"
    price = _get_json(f"{ui.base}/api/quotes?symbols={symbol}")[0]["price"]
    ui.goto(f"/stock/{symbol}")
    expect(ui.page.locator(".sp-price")).not_to_have_text("–")
    ui.page.get_by_text("Set price alert").click()
    form = ui.page.locator(".alert-details .alert-form")
    form.get_by_label("Condition").select_option("above")
    level = form.get_by_label("Price")
    set_btn = form.get_by_role("button", name="Set alert")

    level.fill(f"{price * 0.5:.2f}")   # already above this level: would fire at once, so it is refused
    set_btn.click()
    expect(form.get_by_role("status")).to_contain_text("already above")
    assert "down" in form.get_by_role("status").get_attribute("class")

    target = round(price * 1.2, 2)
    level.fill(f"{target:.2f}")
    set_btn.click()
    expect(form.get_by_role("status")).to_contain_text(f"Alert set: {symbol}")

    ui.goto("/alerts")
    card = ui.page.locator(".card", has=ui.page.get_by_role("heading", name="My price alerts"))
    row = card.locator(".feed-row", has=ui.page.get_by_role("link", name=symbol, exact=True))
    expect(row.first).to_be_visible()
    expect(row.first).to_contain_text("Goes above")
    expect(row.first).to_contain_text("Watching")
    ui.check()


def test_create_watchlist_and_add_symbol(ui):
    name = f"E2E {ui.viewport} list"
    ui.goto("/alerts")
    ui.page.get_by_label("New watchlist name").fill(name)
    ui.page.get_by_role("button", name="Create list").click()
    wl = ui.page.locator(".watchlist", has=ui.page.get_by_role("heading", name=name))
    expect(wl).to_be_visible()
    expect(wl).to_contain_text("Empty. Add a symbol below.")
    wl.get_by_label(f"Add a symbol to {name}").fill("msft")
    wl.get_by_role("button", name="Add", exact=True).click()
    expect(wl.get_by_role("link", name="MSFT", exact=True)).to_be_visible()
    expect(wl.get_by_role("button", name="Remove MSFT")).to_be_visible()
    ui.page.reload()   # stored on the server, not only in the page
    expect(ui.page.locator(".watchlist", has=ui.page.get_by_role("heading", name=name))
           .get_by_role("link", name="MSFT", exact=True)).to_be_visible()
    ui.check()


def test_customize_picks_changes_number_of_stocks(ui):
    ui.goto("/picks")
    hold = ui.page.get_by_role("heading", name="Hold now")
    expect(hold).to_contain_text("10 stocks", timeout=30_000)
    ui.page.locator("details.customize summary").click()
    ui.page.get_by_label("Stocks to hold").select_option("5")
    ui.page.get_by_role("button", name="Update picks").click()
    expect(hold).to_contain_text("5 stocks", timeout=60_000)
    expect(ui.page.locator("details.customize summary")).to_contain_text("5 stocks")
    expect(ui.page.locator("ul.pick-cards > li")).to_have_count(5)
    ui.check()


def test_screener_preset_filters_sorts_and_opens_a_stock(ui):
    from tradebot.universe import STOCKS

    ui.goto("/discover")
    ui.page.get_by_role("tab", name="screener").click()
    expect(ui.heading("Stock screener")).to_be_visible()
    title = ui.page.locator(".scr-head .section-title")
    expect(title).to_contain_text(f"{len(STOCKS)} of {len(STOCKS)} stocks")

    def count() -> int:
        return int(re.match(r"\s*(\d+) of", title.text_content()).group(1))

    preset = ui.page.get_by_role("button", name="Dividend payers in an uptrend")
    preset.click()
    expect(preset).to_have_attribute("aria-pressed", "true")
    expect(title).not_to_contain_text(f"{len(STOCKS)} of")
    n = count()
    assert 0 < n < len(STOCKS)
    assert "div=2" in ui.page.url and "trend=up" in ui.page.url
    # Another filter narrows the list further; clearing brings everything back. On a phone the filters start
    # folded (results first) and open with one tap.
    if ui.viewport == "phone":
        ui.page.locator("details.scr-box > summary").click()
    ui.page.get_by_role("group", name="Size").get_by_role("button", name="Mega").click()
    expect(title).not_to_contain_text(f"{n} of")
    assert count() <= n
    rows = ui.page.locator(".scr-table tbody tr a" if ui.viewport == "desktop" else ".scr-cards a")
    if ui.viewport == "desktop":   # sort by P/E (cheapest first) from the column header
        ui.page.get_by_role("button", name="P/E", exact=True).click()
        expect(ui.page.locator("th[aria-sort='ascending']")).to_contain_text("P/E")
    if count():
        href = rows.first.get_attribute("href")
        rows.first.click()
        ui.page.wait_for_url(ui.base + href)
        ui.page.go_back()
        expect(preset).to_be_visible()
        assert "size=mega" in ui.page.url
    ui.page.get_by_role("button", name="Clear filters").click()
    expect(title).to_contain_text(f"{len(STOCKS)} of {len(STOCKS)} stocks")


def test_display_currency_switch_changes_amounts_and_persists(ui):
    # Default: euros. Plan amounts in €, a US stock's price in $ with the euro value next to it,
    # a Paris listing in € with nothing to convert.
    ui.goto("/portfolio")
    amount = ui.page.locator(".pick-cards .pc-num > .num").first
    expect(amount).to_contain_text("€", timeout=30_000)
    ui.goto("/stock/AAPL")
    price = ui.page.locator(".sp-price")
    expect(price).to_contain_text("$")
    expect(price.locator(".fx-alt")).to_contain_text("≈ €")
    ui.goto("/stock/MC.PA")
    expect(ui.page.locator(".sp-price")).to_contain_text("€")
    expect(ui.page.locator(".sp-price .fx-alt")).to_have_count(0)

    # Switch to dollars in Settings: the plan is rebuilt in dollars, the Paris stock gets a "≈ $" value.
    ui.goto("/settings")
    group = ui.page.get_by_role("radiogroup", name="Display currency")
    expect(group.get_by_role("radio", name="Euro €")).to_have_attribute("aria-checked", "true")
    group.get_by_role("radio", name="Dollar $").click()
    expect(group.get_by_role("radio", name="Dollar $")).to_have_attribute("aria-checked", "true")
    expect(ui.page.get_by_text("Live rate: 1 € = $")).to_be_visible()
    ui.goto("/portfolio")
    expect(amount).to_contain_text("$", timeout=30_000)
    expect(amount).not_to_contain_text("€")
    ui.page.reload()                                   # remembered in this browser
    expect(amount).to_contain_text("$", timeout=30_000)
    ui.goto("/stock/MC.PA")
    expect(ui.page.locator(".sp-price .fx-alt")).to_contain_text("≈ $")
    ui.goto("/settings")
    expect(ui.page.get_by_role("radiogroup", name="Display currency").get_by_role("radio", name="Dollar $")) \
        .to_have_attribute("aria-checked", "true")
    ui.check()


def test_unknown_route_redirects_home(ui):
    ui.goto("/this/page/does-not-exist")
    ui.page.wait_for_url(ui.base + "/")
    expect(ui.heading("Today")).to_be_visible()
    ui.check()


def test_unknown_stock_shows_clear_message(ui):
    ui.expected_failures |= {("/api/stock", 404), ("/api/chart", 502), ("/api/forecast", 502)}
    ui.goto("/stock/ZZZZ")
    expect(ui.heading("ZZZZ")).to_be_visible()
    expect(ui.page.get_by_role("alert")).to_contain_text("This page could not be loaded. Unknown symbol ZZZZ")
    expect(ui.page.get_by_role("link", name="Today", exact=True).last).to_be_visible()
    ui.check()


def _focus_ring(locator) -> str:
    return locator.evaluate("e => { const s = getComputedStyle(e); return `${s.outlineStyle} ${s.boxShadow}`; }")


def test_keyboard_focus_is_visible(ui):
    ui.goto("/picks")
    expect(ui.page.get_by_role("heading", name="Hold now")).to_be_visible(timeout=30_000)
    summary = ui.page.locator("details.customize summary")
    summary.focus()
    ui.page.keyboard.press("Enter")            # opens Customize from the keyboard
    ui.page.keyboard.press("Tab")
    topn = ui.page.get_by_label("Stocks to hold")
    expect(topn).to_be_focused()
    assert _focus_ring(topn) != "none none", "no visible focus on a select"
    trend = ui.page.get_by_label("Only uptrends")
    trend.focus()                              # after a key press, focus counts as keyboard focus
    assert _focus_ring(trend).startswith("solid"), "no visible focus on a checkbox"
    button = ui.page.get_by_role("button", name="Update picks")
    button.focus()
    assert _focus_ring(button).startswith("solid"), "no visible focus on a button"
    ui.check()


def test_learn_glossary_search_filters(ui):
    ui.goto("/learn")
    expect(ui.heading("Learn")).to_be_visible()
    entries = ui.page.locator("article.gloss")
    total = entries.count()
    assert total >= 40, f"only {total} glossary entries"
    box = ui.page.get_by_label("Search the glossary")
    box.fill("drawdown")
    expect(ui.page.get_by_role("heading", name="Drawdown", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("heading", name="Momentum", exact=True)).to_have_count(0)
    assert 0 < entries.count() < total
    # A short result opens its examples straight away.
    expect(ui.page.locator("#term-drawdown").get_by_text("Example", exact=True)).to_be_visible()
    box.fill("zzzz")
    expect(ui.page.get_by_text('No term matches "zzzz"')).to_be_visible()
    ui.page.get_by_role("button", name="clear the search").click()
    expect(entries).to_have_count(total)
    # Hints link to an entry: it opens with its example.
    ui.goto("/learn?term=stop-loss")
    entry = ui.page.locator("#term-stop-loss")
    expect(entry).to_be_in_viewport()
    expect(entry.get_by_text("Example", exact=True)).to_be_visible()
    ui.check()


@pytest.mark.first_visit
def test_first_visit_tour_can_be_dismissed_and_stays_dismissed(ui):
    ui.goto("/")
    tour = ui.page.get_by_role("dialog", name="Today")
    expect(tour).to_be_visible()
    expect(tour.get_by_role("button", name="Next: Beat the S&P")).to_be_focused()   # focus moves into the tour
    tour.get_by_role("button", name="Next: Beat the S&P").click()
    ui.page.wait_for_url(ui.base + "/picks")                                        # each step shows its page
    expect(ui.page.get_by_role("dialog", name="Beat the S&P")).to_be_visible()
    ui.page.keyboard.press("Escape")                                               # Escape closes it
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    ui.goto("/")
    expect(ui.heading("Today")).to_be_visible()
    expect(ui.page.locator(".hold-list")).to_be_visible()
    ui.page.reload()
    expect(ui.heading("Today")).to_be_visible()
    expect(ui.page.locator(".hold-list")).to_be_visible()
    expect(ui.page.get_by_role("dialog")).to_have_count(0)                          # remembered after reload
    # It can still be replayed from Learn, and "Skip tour" closes it.
    ui.goto("/learn")
    ui.page.get_by_role("button", name="Take the quick tour").click()
    expect(ui.page.get_by_role("dialog", name="Today")).to_be_visible()
    ui.page.get_by_role("button", name="Skip tour").click()
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    ui.check()
