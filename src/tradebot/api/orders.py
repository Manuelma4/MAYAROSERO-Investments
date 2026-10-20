"""Order routes for ANY broker: one risk path for paper, Alpaca, ccxt and IBKR.

Flow: POST /api/orders/preview -> plan + short-lived confirm token; POST /api/orders with that token -> places.
Every order (and the legacy /api/paper/orders) goes through ``checked_plan``: active idea only, fresh price
(real brokers: the broker's own quote, or market data less than a minute old), 1.5% drift check, kill-switch
halt, no idea on a symbol the account already holds, broker account checks, plan_order (risk per trade,
position cap, open positions, short exposure, daily loss incl. open losses, absolute caps), all under one lock.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import asdict

import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from ..trading.brokers import Broker, BrokerError, PaperAdapter, make_broker, trading_mode
from ..trading.guard import CONFIRM_TTL_SECONDS, ConfirmTokens, DayBaseline, Halt, OrderJournal
from ..trading.risk import OrderPlan, OrderRejected, RiskLimits, plan_order
from . import serialize as ser
from .schemas import Confirm, OrderPlace, OrderPreview
from .settings import api_token_problem

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

MAX_DRIFT = 0.015          # price may differ at most 1.5% from the signal's entry
LIMIT_SLIPPAGE = 0.005     # real brokers get a limit order at most 0.5% worse than the current price
HOLD_LIMIT = pd.Timedelta(days=7)   # ~5 trading days, same as practice positions
MAX_QUOTE_AGE = pd.Timedelta(seconds=60)   # real brokers: market-data price must be this fresh (else broker quote)


# -- setup ---------------------------------------------------------------------------------------------
def init_trading(app, data_dir, broker_factory=None) -> None:
    st = app.state
    st.paper_adapter = PaperAdapter(st.paper, st.market.quotes)
    st.order_lock = st.paper_lock            # one order / exit at a time, across all brokers
    st.risk_limits = RiskLimits.from_env()
    st.confirm = ConfirmTokens()
    st.journal = OrderJournal(data_dir / "broker_orders.json")
    st.day_baseline = DayBaseline(data_dir / "broker_day.json")
    st.halt = Halt(data_dir / "trading_halt.json")
    st.broker_factory = broker_factory or (lambda: make_broker(os.environ, paper=st.paper, quotes=st.market.quotes))
    st.broker, st.broker_error, st._broker_tried = None, None, 0.0
    st._broker_init = threading.Lock()
    get_broker(st)


def get_broker(st) -> Broker | None:
    """The configured broker, (re)connected lazily; None with st.broker_error set if it cannot be used."""
    if st.broker is not None:
        return st.broker
    with st._broker_init:
        if st.broker is None and time.monotonic() - st._broker_tried > 30:
            st._broker_tried = time.monotonic()
            try:
                st.broker = st.broker_factory()
                st.broker_error = None
                if st.broker.mode == "live":
                    log.warning("LIVE TRADING: orders go to %s with REAL money.", st.broker.name)
                    problem = api_token_problem(st.settings.api_token)
                    if problem:
                        log.warning("Live orders are refused until this is fixed: %s", problem)
            except BrokerError as exc:
                st.broker_error = str(exc)
            except Exception as exc:   # pragma: no cover - unexpected adapter failure
                st.broker_error = f"Broker unavailable: {exc}"
    return st.broker


def _require_broker(st) -> Broker:
    b = get_broker(st)
    if b is None:
        raise HTTPException(503, f"Broker not connected: {st.broker_error}")
    return b


# -- the one risk path -----------------------------------------------------------------------------------
def checked_plan(st, broker: Broker, symbol: str, side: str) -> tuple[OrderPlan, dict, dict]:
    """Must be called with st.order_lock held. Raises HTTPException(400) with a plain-English reason."""
    if st.halt.active():
        raise HTTPException(400, "Trading is paused because you pressed Close everything. Resume it in Settings.")
    opps = (st.precompute.get("opportunities") or {}).get("items", [])
    opp = next((o for o in opps if o["symbol"] == symbol and o["direction"] == side and o["qualified"]), None)
    if opp is None:
        raise HTTPException(400, "This idea is no longer active. Refresh the page to see the current ideas.")
    if not opp.get("stop") or not opp.get("expires_at"):
        raise HTTPException(400, "This idea has no stop-loss or time limit, so it cannot be invested.")
    price = _current_price(st, broker, symbol)
    long = side == "long"
    if (price <= opp["stop"]) if long else (price >= opp["stop"]):
        raise HTTPException(400, "The price is already past the stop-loss. This idea is no longer valid.")
    drift = abs(price / opp["entry"] - 1)
    if drift > MAX_DRIFT:
        raise HTTPException(400, f"The price moved {drift * 100:.1f}% since the signal (limit {MAX_DRIFT * 100:.1f}%). "
                                 "Wait for the next scan.")
    try:
        acct = broker.account()
        if acct.get("blocked"):
            raise HTTPException(400, f"Your {broker.name} account is blocked for trading. Check it on the broker's site.")
        day_pnl = acct.get("day_pnl")
        if day_pnl is None:
            day_pnl = st.day_baseline.day_pnl(f"{broker.name}:{broker.mode}", float(acct["equity"]))
        all_positions = broker.positions()
        if broker.name != "paper":
            _refuse_if_held(broker, symbol, all_positions)
        positions = [p for p in all_positions if p.get("strategy", "opportunity") == "opportunity"]
        # Real brokers get a limit order up to LIMIT_SLIPPAGE worse than now: size on that worst-case fill,
        # so the max loss shown is an upper bound (overnight gaps aside).
        fill = float(price) if broker.name == "paper" else float(price) * (1 + LIMIT_SLIPPAGE if long else 1 - LIMIT_SLIPPAGE)
        plan = plan_order(symbol, side, fill, opp["stop"], opp["target"], float(acct["equity"]), positions,
                          min(0.0, float(day_pnl)), limits=st.risk_limits, expires_at=opp["expires_at"])
        qty = broker.normalize_qty(symbol, plan.qty)
    except OrderRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    except BrokerError as exc:
        raise HTTPException(400, str(exc)) from exc
    if qty != plan.qty:
        if qty > plan.qty:   # adapters only round down; never trust otherwise
            raise HTTPException(400, "Broker size rounding increased the order. Refused.")
        risk = abs(plan.entry - plan.stop)
        plan = OrderPlan(plan.symbol, plan.side, plan.entry, plan.stop, plan.target, qty, qty * plan.entry,
                         qty * risk, qty * risk / float(acct["equity"]) * 100)
    if broker.name != "paper" and plan.value > float(acct.get("buying_power") or 0):
        raise HTTPException(400, f"Not enough buying power at {broker.name} for this order.")
    return plan, opp, acct


def _quote_age(q: dict) -> pd.Timedelta | None:
    try:
        t = pd.Timestamp(q["time"])
    except (KeyError, TypeError, ValueError):
        return None
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return pd.Timestamp.now(tz="UTC") - t


def _current_price(st, broker: Broker, symbol: str) -> float:
    """Paper: app market data. Real brokers: the broker's own quote, or market data at most MAX_QUOTE_AGE old."""
    try:
        price = broker.quote(symbol)
    except BrokerError as exc:
        raise HTTPException(400, str(exc)) from exc
    if price:
        return float(price)
    q = st.market.quote(symbol)
    if broker.name != "paper" and q.get("price"):
        age = _quote_age(q)
        if age is None or age > MAX_QUOTE_AGE:
            raise HTTPException(400, f"No live price for {symbol} from {broker.name}, and the app's market data is "
                                     "delayed. A real order needs a price less than a minute old, so nothing was sent. "
                                     "Try again while the market is open.")
    if not q.get("price"):
        raise HTTPException(502, f"No current price for {symbol}. Try again in a minute.")
    return float(q["price"])


def _key(broker: Broker, symbol: str) -> str:
    f = getattr(broker, "symbol_key", None)
    return f(symbol) if f else symbol.strip().upper()


def _refuse_if_held(broker: Broker, symbol: str, positions: list[dict]) -> None:
    """Real brokers: never add to, or trade against, a position the account already holds."""
    k = _key(broker, symbol)
    held = next((p for p in positions if _key(broker, p["symbol"]) == k), None)
    if held:
        raise HTTPException(400, f"Your {broker.name} account already holds {held['symbol']} ({held.get('side', 'long')}, "
                                 f"{held['qty']:g}). The app never adds to, or trades against, a position you already "
                                 "have, so this idea cannot be invested. Close that position at the broker first if "
                                 "you want to use it.")


def _journal(st, broker: Broker, plan: OrderPlan, order: dict, **extra) -> None:
    now = pd.Timestamp.now(tz="UTC")
    st.journal.add({"id": order.get("id"), "broker": broker.name, "mode": broker.mode,
                    "symbol": order.get("symbol") or plan.symbol, "side": plan.side, "qty": order["qty"],
                    "entry": plan.entry, "stop": plan.stop, "target": plan.target, "opened_at": now.isoformat(),
                    "close_by": (now + HOLD_LIMIT).isoformat(), "status": "open", "broker_status": order.get("status"),
                    "legs": [str(i) for i in order.get("legs") or [] if i], "stop_order_id": order.get("stop_order_id"),
                    **extra})


def _place(st, broker: Broker, plan: OrderPlan, opp: dict) -> dict:
    buy = plan.side == "long"
    # Paper fills at this price; real brokers get it as the limit, i.e. the worst-case price the plan was sized on.
    otype, limit = "limit", plan.entry
    try:
        order = broker.place_order(plan.symbol, "buy" if buy else "sell", plan.qty, type=otype, limit_price=limit,
                                   stop_loss=plan.stop, take_profit=plan.target)
    except BrokerError as exc:
        o = exc.order
        if broker.name != "paper" and o and o.get("qty"):   # something was bought: journal it whatever happened
            now = pd.Timestamp.now(tz="UTC").isoformat()
            _journal(st, broker, plan, o, unprotected=bool(o.get("unprotected")),
                     **({"status": "closed", "reason": str(exc), "closed_at": now} if o.get("closed") else {}))
            log.error("order problem at %s (%s) for %s: %s", broker.name, broker.mode, plan.symbol, exc)
        raise HTTPException(502 if o and o.get("unprotected") else 400, str(exc)) from exc
    except Exception as exc:   # an adapter bug or an unwrapped library error: never a bare 500
        log.exception("unexpected error placing %s at %s", plan.symbol, broker.name)
        raise HTTPException(502, f"Unexpected error from {broker.name} ({type(exc).__name__}). The order may or may not "
                                 "have gone through: check your account on the broker's site now.") from exc
    if broker.name != "paper" and order.get("qty"):
        _journal(st, broker, plan, order)
    return order


def _eur_rate(st) -> float | None:
    try:
        return st.market.quote("EURUSD=X").get("price") or None   # USD per 1 EUR
    except Exception:
        return None


def _live_block_reason(st, broker: Broker) -> str | None:
    if broker.mode == "live":
        return api_token_problem(st.settings.api_token)
    return None


def current_holdings(st) -> dict:
    """What the owner really holds: the connected real broker's positions when one is configured (not paper),
    else the practice account. Read-only."""
    b = get_broker(st)
    if b is None or b.name == "paper":
        b = st.paper_adapter
    acct, pos = b.account(), b.positions()
    return {"source": "practice account" if b.name == "paper" else f"{b.name} ({b.mode})", "broker": b.name,
            "mode": b.mode, "currency": (acct.get("currency") or "USD").upper(), "equity": acct.get("equity"),
            "positions": pos}


def _require_confirm(request: Request, body: Confirm) -> None:
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(415, 'Send {"confirm": true} as JSON.')
    if body.confirm is not True:
        raise HTTPException(400, 'Nothing done: this action needs {"confirm": true}.')


# -- routes ----------------------------------------------------------------------------------------------
@router.get("/broker/status")
def broker_status(request: Request):
    st = request.app.state
    b = get_broker(st)
    lim = st.risk_limits
    out = {"broker": b.name if b else (os.environ.get("BROKER") or "paper").lower(), "mode": b.mode if b else "paper",
           "connected": False, "error": st.broker_error, "halted": st.halt.active(),
           "limits": asdict(lim), "confirm_seconds": CONFIRM_TTL_SECONDS}
    if b is not None:
        try:
            a = b.account()
            out.update(connected=True, equity=a.get("equity"), buying_power=a.get("buying_power"),
                       cash=a.get("cash"), currency=a.get("currency"), blocked=a.get("blocked", False))
        except BrokerError as exc:
            out["error"] = str(exc)
        out["live_block"] = _live_block_reason(st, b)
    return ser.clean(out)


@router.get("/broker/positions")
def broker_positions(request: Request):
    st = request.app.state
    b = _require_broker(st)
    try:
        pos = b.positions()
    except BrokerError as exc:
        raise HTTPException(502, str(exc)) from exc
    orders = [o for o in st.journal.all() if o.get("broker") == b.name and o.get("mode") == b.mode][-50:]
    return ser.clean({"broker": b.name, "mode": b.mode, "positions": pos, "orders": list(reversed(orders))})


@router.post("/orders/preview")
def order_preview(request: Request, body: OrderPreview):
    """Plan only. Returns the size, stop, target, max loss and a confirm token valid for a short time."""
    st = request.app.state
    b = _require_broker(st)
    with st.order_lock:
        plan, opp, acct = checked_plan(st, b, body.symbol, body.side)
    token = st.confirm.issue({"broker": b.name, "mode": b.mode, "symbol": plan.symbol, "side": plan.side,
                              "qty": plan.qty, "stop": plan.stop, "target": plan.target})
    fx = _eur_rate(st) if (acct.get("currency") or "USD").upper() in ("USD", "USDT", "USDC") else None
    block = _live_block_reason(st, b)
    return ser.clean({
        "broker": b.name, "mode": b.mode, "plan": vars(plan), "confirm_token": token, "expires_in": CONFIRM_TTL_SECONDS,
        "currency": acct.get("currency") or "USD", "equity": acct["equity"], "buying_power": acct.get("buying_power"),
        "eur": None if not fx else {"usd_per_eur": fx, "value": plan.value / fx, "max_loss": plan.max_loss / fx},
        "order_type": "practice fill at the current price" if b.name == "paper" else
                      f"limit order, at most {LIMIT_SLIPPAGE * 100:.1f}% from the current price, with stop-loss"
                      + (" and target" if b.name == "alpaca" else "") + " held at the broker",
        "hold_days": opp.get("hold_days"), "expires_at": opp.get("expires_at"),
        "can_place": block is None, "block_reason": block})


@router.post("/orders")
def order_place(request: Request, body: OrderPlace):
    """Place a previewed order. The confirm token from the preview is required (single use, short-lived)."""
    st = request.app.state
    b = _require_broker(st)
    block = _live_block_reason(st, b)
    if block:
        raise HTTPException(403, block)
    bound = st.confirm.consume(body.confirm_token)
    if bound is None:
        raise HTTPException(400, "Confirmation missing or expired. Review the order again and confirm within "
                                 f"{CONFIRM_TTL_SECONDS} seconds.")
    if (bound["broker"], bound["mode"], bound["symbol"], bound["side"]) != (b.name, b.mode, body.symbol, body.side):
        raise HTTPException(400, "This confirmation was for a different order. Review the order again.")
    with st.order_lock:
        plan, opp, _ = checked_plan(st, b, body.symbol, body.side)
        if (plan.stop, plan.target) != (bound["stop"], bound["target"]):
            raise HTTPException(409, "The idea's stop-loss or target changed since your review. Review it again.")
        if plan.qty > bound["qty"]:   # never more than what was confirmed
            risk = abs(plan.entry - plan.stop)
            plan = OrderPlan(plan.symbol, plan.side, plan.entry, plan.stop, plan.target, bound["qty"],
                             bound["qty"] * plan.entry, bound["qty"] * risk,
                             plan.risk_pct_of_equity * bound["qty"] / plan.qty)
        order = _place(st, b, plan, opp)
    log.info("order placed via %s (%s): %s %s %s", b.name, b.mode, plan.side, plan.qty, plan.symbol)
    return ser.clean({"broker": b.name, "mode": b.mode, "plan": vars(plan), "order": order,
                      "placed": order.get("status") != "not filled"})


@router.post("/orders/close-all")
def orders_close_all(request: Request, body: Confirm):
    """Kill switch: pause new orders FIRST, then cancel every open order and close every position at the broker."""
    _require_confirm(request, body)
    st = request.app.state
    b = get_broker(st)
    live = trading_mode() == "live" or (b is not None and b.mode == "live")
    name = b.name if b else (os.environ.get("BROKER") or "paper").strip().lower()
    st.halt.set(f"Close everything pressed ({name}, {'live' if live else 'paper'})", persistent=live)
    if b is None:
        raise HTTPException(503, f"Trading is paused, but the broker is not connected ({st.broker_error}), so nothing "
                                 "could be closed from here. Close your positions at the broker manually.")
    with st.order_lock:
        try:
            res = b.close_all()
        except Exception as exc:
            log.error("kill switch failed at %s: %s", b.name, exc)
            raise HTTPException(502, f"{exc}. Trading is paused; close your positions at the broker manually.") from exc
        closed = {_key(b, c) for c in res.get("closed") or [] if isinstance(c, str)}
        now = pd.Timestamp.now(tz="UTC").isoformat()
        for e in st.journal.open_entries(b.name, b.mode):
            if _key(b, e["symbol"]) in closed:
                st.journal.mark(e["id"], status="closed", reason="closed by you", closed_at=now)
    return ser.clean({"broker": b.name, "mode": b.mode, **res, "halted": True})


@router.post("/orders/resume")
def orders_resume(request: Request, body: Confirm):
    _require_confirm(request, body)
    request.app.state.halt.clear()
    return {"halted": None}


# -- automatic exits for real-broker positions ------------------------------------------------------------
def _record_day_baseline(st, b: Broker) -> None:
    """Brokers that do not report today's P&L: take start-of-day equity from this loop, not from the first preview."""
    try:
        acct = b.account()
        if acct.get("day_pnl") is None and acct.get("equity") is not None:
            st.day_baseline.day_pnl(f"{b.name}:{b.mode}", float(acct["equity"]))
    except Exception as exc:
        log.warning("could not read the %s account for the daily-loss baseline: %s", b.name, exc)


def _exit_reason(e: dict, price: float | None, now: pd.Timestamp) -> str | None:
    long = e["side"] == "long"
    if e.get("unprotected"):
        return "no stop-loss at the broker"
    if price and ((price <= e["stop"]) if long else (price >= e["stop"])):
        return "stop"
    if price and e.get("target") and ((price >= e["target"]) if long else (price <= e["target"])):
        return "target"
    if now > pd.Timestamp(e["close_by"]):
        return "time limit"
    return None


def _manage_entry(st, b: Broker, e: dict, pos: dict, now: pd.Timestamp) -> dict | None:
    p = pos.get(_key(b, e["symbol"]))
    if p is None:
        if now - pd.Timestamp(e["opened_at"]) > pd.Timedelta(days=1):
            st.journal.mark(e["id"], status="closed", reason="no longer open at the broker", closed_at=now.isoformat())
        return None
    price = p.get("price") or b.quote(e["symbol"])
    reason = _exit_reason(e, price, now)
    if not reason:
        return None
    with st.order_lock:
        try:
            b.close_position(e["symbol"], qty=e["qty"], order_ids=e.get("legs") or [e["id"]], stop=e["stop"], side=e["side"])
        except BrokerError as exc:
            log.warning("could not close %s at %s: %s", e["symbol"], b.name, exc)
            if exc.legs:   # a stop was re-placed: track it as this position's protection now
                st.journal.mark(e["id"], legs=exc.legs, stop_order_id=exc.legs[0], unprotected=False,
                                last_error=str(exc))
            else:
                st.journal.mark(e["id"], last_error=str(exc))
            return None
        st.journal.mark(e["id"], status="closed", reason=reason, closed_at=now.isoformat())
    return {**e, "reason": reason}


def manage_broker_exits(st) -> list[dict]:
    """Time limit (and a target / stop backstop) for positions opened through the app at a real broker."""
    b = get_broker(st)
    if b is None or b.name == "paper":
        return []
    _record_day_baseline(st, b)
    entries = st.journal.open_entries(b.name, b.mode)
    if not entries:
        return []
    now = pd.Timestamp.now(tz="UTC")
    try:
        pos = {_key(b, p["symbol"]): p for p in b.positions()}
    except Exception as exc:
        log.warning("could not read positions at %s: %s", b.name, exc)
        return []
    done = []
    for e in entries:
        try:   # one bad entry (or a raw library error) must not stop the others from being checked
            d = _manage_entry(st, b, e, pos, now)
        except Exception as exc:
            log.warning("exit check failed for %s at %s: %s", e.get("symbol"), b.name, exc)
            continue
        if d:
            done.append(d)
    return done
