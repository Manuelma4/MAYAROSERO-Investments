"""Interactive Brokers through TWS / IB Gateway with ib_insync. Experimental, PAPER ONLY for now.

Needs ``pip install ib_insync`` and TWS or IB Gateway running with the API enabled. Paper vs live is
decided by the port in base.resolve_endpoint (7497/4002 paper, 7496/4001 live). After connecting, the
account id is checked too: IBKR paper accounts start with "D" (e.g. DU1234567), so a paper-mode session
that lands on a real account disconnects immediately.

ib_insync is not thread-safe, and this app calls the broker from the web server threads and the background
loop. So every IB call runs on ONE dedicated thread with its own event loop (``_run``). Real-money mode is
refused for IBKR until this adapter has been tested against a live TWS session.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

from .base import BrokerError, Endpoint, is_crypto, require_protection, resolve_endpoint

LIVE_REFUSED = ("Interactive Brokers real-money trading is switched off in this app for now: the IBKR connection is "
                "still experimental. Use the IBKR paper account (port 7497 or 4002, without TRADING_MODE=live), "
                "or Alpaca for real money.")
CALL_TIMEOUT = 30.0


def _thread_init() -> None:
    asyncio.set_event_loop(asyncio.new_event_loop())


class IBKRBroker:
    name = "ibkr"

    def __init__(self, env: Mapping[str, str] | None = None, ib=None):
        env = os.environ if env is None else env
        self.endpoint: Endpoint = resolve_endpoint("ibkr", env)
        if self.mode == "live":
            raise BrokerError(LIVE_REFUSED)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ibkr", initializer=_thread_init)
        self._lock = threading.Lock()
        if ib is None:
            try:
                from ib_insync import IB  # type: ignore[import-not-found]  # noqa: F401
            except ImportError as exc:
                raise BrokerError("IBKR needs the ib_insync package (pip install ib_insync) and TWS or IB Gateway "
                                  "running with the API enabled.") from exc

            def connect():
                from ib_insync import IB  # type: ignore[import-not-found]

                client = IB()
                client.connect(self.endpoint.host, self.endpoint.port,
                               clientId=int(env.get("IBKR_CLIENT_ID") or 17), timeout=8)
                return client
            try:
                ib = self._run(connect)
            except Exception as exc:
                raise BrokerError(f"Could not connect to TWS / IB Gateway at {self.endpoint.host}:{self.endpoint.port}: {exc}") from exc
        self.ib = ib
        accounts = list(self._run(ib.managedAccounts) or [])
        real = [a for a in accounts if not str(a).upper().startswith("D")]
        if self.mode == "paper" and (real or not accounts):
            self._run(ib.disconnect)
            raise BrokerError("Connected to a REAL-money IBKR account while TRADING_MODE is not live. Disconnected.")
        self.account_id = accounts[0] if accounts else None

    def _run(self, fn, *args, **kw):
        """Run an IB call on the one IB thread and wait for it."""
        if threading.current_thread().name.startswith("ibkr"):
            return fn(*args, **kw)
        return self._pool.submit(fn, *args, **kw).result(timeout=CALL_TIMEOUT)

    def _safe(self, what: str, fn, *args, **kw):
        try:
            return self._run(fn, *args, **kw)
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"IBKR: {what} failed ({type(exc).__name__}: {exc})") from exc

    @property
    def mode(self):
        return self.endpoint.mode

    def symbol_key(self, symbol: str) -> str:
        return symbol.strip().upper()

    def account(self) -> dict:
        rows = self._safe("reading the account", self.ib.accountSummary, self.account_id)
        vals = {v.tag: v.value for v in rows if v.currency in ("USD", "EUR", "BASE", "")}
        f = lambda k: float(vals.get(k) or 0)  # noqa: E731
        return {"equity": f("NetLiquidation"), "cash": f("TotalCashValue"), "buying_power": f("BuyingPower"),
                "day_pnl": None, "currency": "USD", "blocked": False}

    def positions(self) -> list[dict]:
        return [{"symbol": p.contract.symbol, "side": "long" if p.position > 0 else "short", "qty": abs(float(p.position)),
                 "entry": float(p.avgCost), "price": None, "pnl": None}
                for p in self._safe("reading positions", self.ib.positions) if p.position]

    def quote(self, symbol: str) -> float | None:
        if is_crypto(symbol):
            return None

        def last():
            from ib_insync import Stock  # type: ignore[import-not-found]

            c = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(c)
            t = self.ib.reqTickers(c)[0]
            px = float(t.marketPrice())
            return px if px == px and px > 0 else None
        try:
            return self._run(last)
        except Exception:
            return None

    def normalize_qty(self, symbol: str, qty: float) -> float:
        if is_crypto(symbol):
            raise BrokerError("Crypto is traded with BROKER=ccxt in this app.")
        whole = float(int(qty))
        if whole < 1:
            raise BrokerError(f"The planned size for {symbol} is under 1 share.")
        return whole

    def place_order(self, symbol, side, qty, type="market", limit_price=None, stop_loss=None, take_profit=None) -> dict:
        require_protection(side, qty, stop_loss)
        if type != "limit" or not limit_price or not take_profit:
            raise BrokerError("IBKR orders are sent as bracket orders: limit entry, stop-loss and target are required.")

        def send():
            from ib_insync import Stock  # type: ignore[import-not-found]

            contract = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(contract)
            return [self.ib.placeOrder(contract, o) for o in self.ib.bracketOrder(
                side.upper(), qty, limit_price, take_profit, stop_loss)]
        trades = self._safe("placing the bracket order", send)
        ids = [str(t.order.orderId) for t in trades]
        return {"id": ids[0], "status": trades[0].orderStatus.status, "symbol": symbol,
                "side": side, "qty": float(qty), "legs": ids, "stop_order_id": ids[-1]}

    def cancel(self, order_id: str) -> None:
        def go():
            for t in self.ib.openTrades():
                if str(t.order.orderId) == str(order_id):
                    self.ib.cancelOrder(t.order)
        self._safe("cancelling an order", go)

    def close_position(self, symbol: str, qty: float | None = None, order_ids: list[str] | None = None,
                       stop: float | None = None, side: str = "long") -> dict | None:
        """Cancel only this order's own legs, then close at most ``qty`` shares."""
        own = {str(i) for i in order_ids or []}

        def go():
            from ib_insync import MarketOrder, StopOrder  # type: ignore[import-not-found]

            for t in self.ib.openTrades():
                if t.contract.symbol == symbol and (qty is None or str(t.order.orderId) in own):
                    self.ib.cancelOrder(t.order)
            for p in self.ib.positions():
                if p.contract.symbol != symbol or not p.position:
                    continue
                if qty is not None and (p.position > 0) != (side == "long"):
                    return None   # not the side the app opened: leave it alone
                n = abs(p.position) if qty is None else min(abs(p.position), float(qty))
                if n <= 0:
                    return None
                action = "SELL" if p.position > 0 else "BUY"
                try:
                    t = self.ib.placeOrder(p.contract, MarketOrder(action, n))
                except Exception as exc:
                    if not own or not stop:
                        raise
                    try:
                        s = self.ib.placeOrder(p.contract, StopOrder(action, n, stop))
                    except Exception as exc2:
                        raise BrokerError(f"DANGER: closing {symbol} failed ({exc}) and re-placing its stop-loss also "
                                          f"failed ({exc2}). Check it in TWS now.") from exc2
                    raise BrokerError(f"Closing {symbol} failed ({exc}); its stop-loss was placed again at {stop}.",
                                      legs=[str(s.order.orderId)]) from exc
                return {"symbol": symbol, "qty": n, "status": t.orderStatus.status}
            return None
        return self._safe(f"closing {symbol}", go)

    def close_all(self) -> dict:
        self._safe("cancelling all orders", self.ib.reqGlobalCancel)
        closed, errors = [], []
        for p in self.positions():
            try:
                if self.close_position(p["symbol"]):
                    closed.append(p["symbol"])
            except BrokerError as exc:
                errors.append(f"{p['symbol']}: {exc}")
        return {"cancelled": -1, "closed": closed, "errors": errors}
