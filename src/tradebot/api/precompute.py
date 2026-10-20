"""Background precomputation: pages show results instantly instead of computing on click.

Jobs run at startup and then every `interval` seconds in a daemon thread:
- picks for every preset with default settings
- the "Today" board: market mood, what to hold, buy/sell/keep changes, today's biggest movers
- the live track record: one picks snapshot per preset and trading day (once the US close is known),
  and every qualified Invest-now idea (recorded by the opportunity loop)
- the weekly digest (once per week at the configured slot) and the portfolio drift alert (at most weekly)
- the earnings calendar (once a day) for every preset's picks, watchlists, held stocks and popular names,
  and the "earnings tomorrow" alert for picks, watchlist and held stocks (once per report)
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

from ..data import earnings as er
from ..live import alerts
from ..live import digest as dg
from ..live import drift as dr
from ..picker import PRESETS
from ..universe import CURATED, POP, by_symbol, sp500_symbols
from . import serialize as ser
from .market import MarketData
from .schemas import PicksRequest
from .services import compute_picks, compute_predictions, compute_track_record, market_mood

log = logging.getLogger(__name__)


class Precomputer:
    def __init__(self, market: MarketData, interval: int = 1800, opportunities_interval: int = 300,
                 on_opportunity=None, paper=None, paper_lock=None, store=None, on_alert=None,
                 on_picks_change=None, alert_preset: str = "quality_momentum", broker_exits=None,
                 notify=None, holdings=None, digest_schedule: dg.Schedule | None = None,
                 earnings: er.EarningsCalendar | None = None, on_earnings=None):
        self.market = market
        self.interval = interval
        self.opportunities_interval = opportunities_interval
        self.on_opportunity = on_opportunity   # callback(dict) for each NEW qualified opportunity
        self.paper = paper                     # PaperBroker for automatic exits of "Invest" positions
        self.paper_lock = paper_lock or threading.Lock()
        self.store = store                     # EventStore holding the user's price alerts
        self.on_alert = on_alert               # callback(alert, quote) for each alert that fires
        self.on_picks_change = on_picks_change # callback(event) when the main picks list changes
        self.alert_preset = alert_preset
        self.broker_exits = broker_exits       # callable: time limit / target watch for real-broker positions
        self.notify = notify                   # callable(text): send through the configured notifiers
        self.holdings = holdings               # callable() -> what the owner holds (practice account or broker)
        self.digest_schedule = digest_schedule or dg.Schedule()
        self.earnings = earnings or er.EarningsCalendar(store)
        self.on_earnings = on_earnings         # callback(event, text) for each "earnings tomorrow" alert
        self._earnings_day: str | None = None
        self._held: tuple[float, set[str]] | None = None
        self._seen: set[tuple] = set()
        self._scanner = None
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run: str | None = None
        self.last_error: str | None = None

    def get(self, key: str) -> dict | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._data[key] = value

    def run_once(self, predictions: bool = True) -> None:
        errors = []
        started = datetime.now(timezone.utc)
        ew_cache: dict = {}  # the equal-weight yardstick is identical for every preset
        fresh = []
        for preset in PRESETS:
            try:
                self.put(f"picks:{preset}", compute_picks(self.market, PicksRequest(preset=preset), ew_cache))
                fresh.append(preset)
            except Exception as exc:  # keep the previous result if a refresh fails
                errors.append(f"picks {preset}: {exc}")
        try:
            self.record_track_snapshots(fresh, started)
            self.track_record(self.alert_preset, max_age=0)
        except Exception as exc:
            errors.append(f"track record: {exc}")
        try:
            self.record_picks_change()
        except Exception as exc:
            errors.append(f"picks alert: {exc}")
        try:
            self.put("today", self.build_today())
        except Exception as exc:
            errors.append(f"today: {exc}")
        try:
            self.check_drift()
        except Exception as exc:
            errors.append(f"portfolio drift: {exc}")
        try:
            self.refresh_earnings()
        except Exception as exc:
            errors.append(f"earnings: {exc}")
        today = datetime.now(timezone.utc).date().isoformat()
        for h in ((5, 1, 21) if predictions else ()):   # heavy: recomputed once per day
            key = f"predictions:{h}"
            cur = self.get(key)
            if cur is not None and cur.get("_computed") == today:
                continue
            try:
                data = compute_predictions(self.market, h)
                data["_computed"] = today
                self.put(key, data)
            except Exception as exc:
                errors.append(f"predictions {h}: {exc}")
        self.last_run = datetime.now(timezone.utc).isoformat()
        self.last_error = "; ".join(errors) or None
        if errors:
            log.warning("precompute errors: %s", self.last_error)

    def build_today(self) -> dict:
        core = self.get("picks:quality_momentum")
        try:
            mood = market_mood(self.market, core.get("breadth_%") if core else None)
        except Exception as exc:  # the board still shows picks and movers without the mood
            log.warning("market mood unavailable: %s", exc)
            mood = None
        quotes = [q for q in self.market.quotes(sp500_symbols())
                  if isinstance(q.get("change_pct"), (int, float)) and math.isfinite(q["change_pct"])]
        quotes.sort(key=lambda q: q["change_pct"], reverse=True)
        names = {k: v.name for k, v in by_symbol().items()}
        for q in quotes:
            q["name"] = names.get(q["symbol"], q["symbol"])
        return ser.clean({
            "as_of": datetime.now(timezone.utc).isoformat(),
            "mood": mood,
            "core": None if core is None else {
                "preset": core["preset"], "risk_off": core["risk_off"], "picks": core["picks"],
                "changes": core["changes"], "as_of": core["as_of"],
                "edge": {k: core["stats"].get(k) for k in ("cagr_%", "benchmark_cagr_%", "skill_vs_universe_%", "start")},
                "settings": "10 stocks, monthly review, uptrends only (Quality momentum)",
            },
            "gainers": [{k: q[k] for k in ("symbol", "name", "price", "change_pct")} for q in quotes[:6]],
            "losers": [{k: q[k] for k in ("symbol", "name", "price", "change_pct")} for q in quotes[::-1][:6]],
        })

    # ---- live track record ----------------------------------------------------------
    def record_track_snapshots(self, presets, started: datetime) -> int:
        """Save today's picks for each freshly computed preset, once per trading day, and only when they
        were ranked on a finished session (computation started after that day's US close)."""
        from ..live.track_record import session_close_known

        if self.store is None:
            return 0
        n = 0
        for preset in presets:
            data = self.get(f"picks:{preset}")
            if not data or not data.get("as_of"):
                continue
            day = str(data["as_of"])[:10]
            if not session_close_known(day, started):
                continue   # ranked on an unfinished session: wait for the close
            picks = data.get("picks") or []
            rows = [{"symbol": p["symbol"], "weight": 1 / len(picks), "price": p.get("price")} for p in picks]
            n += self.store.record_picks_snapshot(preset, day, rows, bool(data.get("risk_off")),
                                                  datetime.now(timezone.utc).isoformat())
        return n

    def track_record(self, preset: str = "quality_momentum", max_age: float = 120.0) -> dict:
        """Forward record (cached briefly: it re-reads prices for every recorded pick and idea)."""
        key = f"track:{preset}"
        hit = self.get(key)
        if hit is not None and time.time() - hit["_at"] < max_age:
            return hit["data"]
        if self.store is None:
            raise RuntimeError("no store")
        universe = (self.get(f"picks:{preset}") or {}).get("universe")
        data = compute_track_record(self.market, self.store, preset, universe)
        self.put(key, {"_at": time.time(), "data": data})
        return data

    # ---- live opportunities ---------------------------------------------------------
    def scan_opportunities(self) -> dict:
        import pandas as pd

        from ..live.opportunities import OpportunityScanner, session_fraction

        if self._scanner is None:
            self._scanner = OpportunityScanner(self.market)
        now = pd.Timestamp.now(tz="UTC")
        items = [o.to_dict() for o in self._scanner.scan(now)]
        data = ser.clean({"as_of": now.isoformat(), "us_market_open": session_fraction(now, False) < 1.0,
                          "items": items, "movers": getattr(self._scanner, "movers", None)})
        self.put("opportunities", data)
        for o in items:
            key = (o["symbol"], o["direction"], o["as_of"][:10])
            if o["qualified"] and self.store is not None:
                try:   # live track record: one row per symbol, direction and day (idempotent)
                    self.store.record_idea(o, now.isoformat())
                except Exception as exc:
                    log.warning("track record idea failed: %s", exc)
            if o["qualified"] and key not in self._seen:
                self._seen.add(key)
                if self.on_opportunity:
                    try:
                        self.on_opportunity(o)
                    except Exception as exc:
                        log.warning("opportunity callback failed: %s", exc)
        return data

    def manage_paper_exits(self) -> list[dict]:
        """Close paper 'Invest' positions at their stop, target or time limit."""
        import pandas as pd

        if self.paper is None:
            return []
        closed = []
        pos = [p for p in self.paper.positions.values() if p.strategy == "opportunity"]
        if not pos:
            return closed
        quotes = {q["symbol"]: q for q in self.market.quotes([p.symbol for p in pos])}
        now = pd.Timestamp.now(tz="UTC")
        for p in pos:
            price = quotes.get(p.symbol, {}).get("price")
            if price is None:
                if now - pd.Timestamp(p.entry_time) > pd.Timedelta(days=7):
                    log.warning("time limit reached for %s but no price available; will retry", p.symbol)
                continue
            long = p.side == "long"
            reason = None
            if (price <= p.stop) if long else (price >= p.stop):
                reason = "stop"
            elif p.target is not None and ((price >= p.target) if long else (price <= p.target)):
                reason = "target"
            elif now - pd.Timestamp(p.entry_time) > pd.Timedelta(days=7):  # ~5 trading days
                reason = "time limit"
            if reason:
                with self.paper_lock:
                    rec = self.paper.close(p.symbol, p.strategy, price, now.isoformat(), reason)
                if rec:
                    closed.append(rec)
        return closed

    def record_picks_change(self) -> dict | None:
        """Once per completed review: store and announce what to buy / sell (deduplicated in the DB,
        so a restart never repeats the alert)."""
        picks = self.get(f"picks:{self.alert_preset}")
        ch = (picks or {}).get("changes") or {}
        if self.store is None or not ch.get("date") or not (ch.get("buy") or ch.get("sell")):
            return None
        seen = self.store.list("picks", limit=50)
        if any(e.get("date") == ch["date"] and e.get("preset") == self.alert_preset for e in seen):
            return None
        ev = self.store.add("picks", "PICKS", {"preset": self.alert_preset, "date": ch["date"],
                                               "buy": ch.get("buy", []), "sell": ch.get("sell", []),
                                               "keep": ch.get("keep", [])})
        age = datetime.now(timezone.utc).date() - datetime.fromisoformat(str(ch["date"])[:10]).date()
        if age.days <= 35 and self.on_picks_change:   # an old review (first start) is recorded, not announced
            self.on_picks_change(ev)
        return ev

    # ---- portfolio drift and weekly digest ------------------------------------------
    TARGET_KEY = "portfolio_target"

    def _fx_to(self, target_ccy: str, account_ccy: str) -> float:
        """Multiply account-currency money by this to get the target currency (USD <-> EUR only)."""
        a = "USD" if account_ccy in ("USD", "USDT", "USDC") else account_ccy
        if a == target_ccy:
            return 1.0
        rate = self.market.quote("EURUSD=X").get("price")   # USD per 1 EUR
        if not rate:
            raise RuntimeError("EUR/USD rate unavailable")
        if (a, target_ccy) == ("USD", "EUR"):
            return 1.0 / rate
        if (a, target_ccy) == ("EUR", "USD"):
            return rate
        raise RuntimeError(f"Cannot compare a {account_ccy} account with a {target_ccy} plan")

    def portfolio_drift(self) -> dict:
        """Current holdings vs the saved target (status no_target when none is saved). Never trades."""
        target = self.store.get_value(self.TARGET_KEY) if self.store is not None else None
        if not target:
            return {"status": "no_target", "target": None,
                    "message": "No target saved yet. Build a plan and press Save this plan as my target."}
        if self.holdings is None:
            raise RuntimeError("holdings unavailable")
        h = self.holdings()
        d = dr.compute_drift(target, h["positions"], float(h.get("equity") or 0.0),
                             self._fx_to(target["currency"], h["currency"]))
        return ser.clean({**d, "target": target, "source": h["source"], "as_of": datetime.now(timezone.utc).isoformat()})

    def check_drift(self, now: datetime | None = None) -> dict | None:
        """One alert when the portfolio drifted past the limits, at most once every 7 days (stored in SQLite)."""
        if self.store is None or self.holdings is None or not self.store.get_value(self.TARGET_KEY):
            return None
        now = now or datetime.now(timezone.utc)
        d = self.portfolio_drift()
        self.put("drift", d)
        if d.get("breached") and self.store.claim_notice("drift", now.date().isoformat(), now, min_gap=timedelta(days=7)):
            if self.notify:
                self.notify(dr.alert_text(d, d["source"]))
            return d
        return None

    def digest_text(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)

        def week(type_: str) -> list[dict]:
            return dg.week_events(self.store.list(type_, limit=200), now) if self.store is not None else []

        try:
            track = self.track_record(self.alert_preset)
        except Exception as exc:
            log.warning("digest: track record unavailable: %s", exc)
            track = None
        drift = None
        try:
            drift = self.portfolio_drift() if self.store is not None and self.holdings is not None else None
        except Exception as exc:
            log.warning("digest: drift unavailable: %s", exc)
        mood = (self.get("today") or {}).get("mood")
        return dg.compose(now, week("picks"), week("alert"), track, mood, drift,
                          timezone=self.digest_schedule.timezone)

    def check_digest(self, now: datetime | None = None) -> str | None:
        """Send the weekly digest once when its slot has come (deduplicated in SQLite, survives restarts)."""
        if self.store is None:
            return None
        now = now or datetime.now(timezone.utc)
        period = dg.due_period(now, self.digest_schedule)
        last = self.store.last_notice("digest") if period else None
        if period is None or (last and last["period"] == period):   # cheap check before composing
            return None
        text = self.digest_text(now)
        if not self.store.claim_notice("digest", period, now):
            return None
        if self.notify:
            self.notify(text)
        return text

    def check_alerts(self) -> list[dict]:
        """Fire every active price alert whose condition is met (each fires once, then deactivates)."""
        if self.store is None:
            return []
        active = self.store.alerts(active_only=True)
        if not active:
            return []
        quotes = {q["symbol"]: q for q in self.market.quotes(sorted({a["symbol"] for a in active}), spark_bars=1)}
        fired = []
        for a in active:
            q = quotes.get(a["symbol"]) or {}
            if alerts.due(a, q) and self.store.set_alert_active(a["id"], False, q["price"], q.get("time")):
                fired.append(a)
                try:
                    if self.on_alert:
                        self.on_alert(a, q)
                except Exception as exc:   # one failed delivery must not stop the other alerts
                    log.warning("alert %s delivery failed: %s", a["id"], exc)
        return fired

    # ---- earnings calendar ----------------------------------------------------------
    HELD_TTL = 900.0

    def held_symbols(self) -> set[str]:
        """Symbols the owner holds (practice account or broker), cached 15 min: alerts check every 5 min."""
        if self.holdings is None:
            return set()
        if self._held and time.time() - self._held[0] < self.HELD_TTL:
            return self._held[1]
        try:
            held = {p["symbol"] for p in self.holdings().get("positions") or [] if p.get("symbol")}
        except Exception as exc:
            log.warning("earnings: holdings unavailable: %s", exc)
            held = self._held[1] if self._held else set()
        self._held = (time.time(), held)
        return held

    def earnings_interest(self) -> dict[str, dict]:
        """Stocks whose earnings matter: every preset's current picks, watchlists, held stocks, popular names."""
        flags: dict[str, dict] = {}

        def mark(sym: str, key: str) -> None:
            if er.applicable(sym):
                flags.setdefault(sym, {"pick": False, "main_pick": False, "watchlist": False, "held": False,
                                       "popular": False})[key] = True

        for preset in PRESETS:
            for p in (self.get(f"picks:{preset}") or {}).get("picks") or []:
                mark(p["symbol"], "pick")
                if preset == self.alert_preset:
                    mark(p["symbol"], "main_pick")
        if self.store is not None:
            for w in self.store.watchlists():
                for sym in w["symbols"]:
                    mark(sym, "watchlist")
        for sym in self.held_symbols():
            mark(sym, "held")
        for st in CURATED:
            if POP in st.themes:
                mark(st.symbol, "popular")
        return flags

    def _add_average_moves(self, records: list[dict]) -> None:
        syms = [r["symbol"] for r in records if r.get("history")]
        bars = self.market.history_many("yahoo", syms, "1d", limit=320) if syms else {}
        for r in records:
            r["avg_move"] = er.average_move(r.get("history") or [], bars.get(r["symbol"]))

    def refresh_earnings(self, now: datetime | None = None) -> dict:
        """Once a day: refresh every stale (12 h) entry; in the other runs only fetch newly added symbols."""
        now = now or datetime.now(timezone.utc)
        syms = sorted(self.earnings_interest())
        day = now.date().isoformat()
        if self._earnings_day != day:
            res = self.earnings.refresh(syms, enrich=self._add_average_moves)
            self._earnings_day = day
        else:
            have = self.earnings.cached(syms)
            res = self.earnings.refresh([s for s in syms if s not in have], enrich=self._add_average_moves)
        return res

    def earnings_for(self, symbols: list[str], fetch: bool = True) -> list[dict]:
        """Records for the API (stale or missing ones fetched on demand, at most 20, never behind a refresh)."""
        recs = self.earnings.get(symbols, fetch=fetch)
        missing_move = [r for r in recs.values() if r.get("status") == "ok" and "avg_move" not in r]
        if missing_move:
            try:
                self._add_average_moves(missing_move)
                for r in missing_move:
                    self.earnings.put(r)
            except Exception as exc:
                log.warning("earnings average move failed: %s", exc)
        return [er.public(recs[s]) for s in symbols]

    def upcoming_earnings(self, days: int = 14, mine_only: bool = False, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        flags = self.earnings_interest()
        if mine_only:
            flags = {s: f for s, f in flags.items() if f["pick"] or f["watchlist"] or f["held"]}
        names = {k: v.name for k, v in by_symbol().items()}
        today = now.astimezone(er.NY).date()
        items = er.upcoming(self.earnings.cached(list(flags)), today, days, flags, names)
        return ser.clean({"as_of": now.isoformat(), "days": days, "today": today.isoformat(), "items": items,
                          "last_refresh": self.earnings.last_refresh, "hint": er.HINT})

    def check_earnings(self, now: datetime | None = None) -> list[dict]:
        """The day before a report (owner's time zone) for a pick, a watchlist or a held stock: one alert per
        report (the "already sent" mark lives in SQLite)."""
        if self.store is None:
            return []
        now = now or datetime.now(timezone.utc)
        tz = self.digest_schedule.timezone
        # Alerts only for the main strategy's picks (the other presets would flood the phone in earnings season).
        flags = {s: f for s, f in self.earnings_interest().items() if f["main_pick"] or f["watchlist"] or f["held"]}
        recs = self.earnings.cached(list(flags))
        names = {k: v.name for k, v in by_symbol().items()}
        sent = []
        for sym in sorted(recs):
            rec = recs[sym]
            nxt = rec.get("next")
            phase = er.alert_phase(nxt, now, tz)
            if not phase or not self.store.claim_notice("earnings", f"{sym}:{nxt['date']}", now):
                continue
            f = flags[sym]
            reasons = [r for r, on in (("you hold it", f["held"]), ("one of the picks", f["main_pick"]),
                                       ("on your watchlist", f["watchlist"])) if on]
            move = rec.get("avg_move")
            text = er.alert_text(sym, names.get(sym, sym), nxt, phase, reasons, move)
            ev = self.store.add("earnings", sym, {
                "name": names.get(sym, sym), "date": nxt["date"], "time": nxt.get("time"),
                "timing": nxt.get("timing"), "timing_text": er.TIMING_TEXT.get(nxt.get("timing") or "unknown"),
                "phase": phase, "eps_estimate": nxt.get("eps_estimate"),
                "avg_move_pct": (move or {}).get("avg_abs_move_%"), "reasons": reasons, "text": text})
            sent.append(ev)
            try:
                if self.on_earnings:
                    self.on_earnings(ev, text)
                elif self.notify:
                    self.notify(text)
            except Exception as exc:   # one failed delivery must not stop the others
                log.warning("earnings alert %s delivery failed: %s", sym, exc)
        return sent

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            self.run_once()
            self._stop.wait(max(60.0, self.interval - (time.time() - started)))

    def _opp_loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            try:
                self.scan_opportunities()
            except Exception as exc:
                log.warning("opportunity scan failed: %s", exc)
            try:
                self.manage_paper_exits()   # stops must fire even if the scan failed
            except Exception as exc:
                log.warning("paper exits failed: %s", exc)
            try:
                if self.broker_exits:
                    self.broker_exits()
            except Exception as exc:
                log.warning("broker exits failed: %s", exc)
            try:
                self.check_alerts()
            except Exception as exc:
                log.warning("price alerts failed: %s", exc)
            try:
                self.check_digest()
            except Exception as exc:
                log.warning("weekly digest failed: %s", exc)
            try:
                self.check_earnings()
            except Exception as exc:
                log.warning("earnings alerts failed: %s", exc)
            self._stop.wait(max(60.0, self.opportunities_interval - (time.time() - started)))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="precompute", daemon=True)
        self._thread.start()
        threading.Thread(target=self._opp_loop, name="opportunities", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
