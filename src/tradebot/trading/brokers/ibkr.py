"""Interactive Brokers through TWS / IB Gateway with ib_insync. Experimental stub.

Needs ``pip install ib_insync`` and TWS or IB Gateway running with the API enabled. Paper vs live is
decided by the port in base.resolve_endpoint (7497/4002 paper, 7496/4001 live). After connecting, the
account id is checked too: IBKR paper accounts start with "D" (e.g. DU1234567), so a paper-mode session
that lands on a real account disconnects immediately.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from .base import BrokerError, Endpoint, is_crypto, require_protection, resolve_endpoint


class IBKRBroker:
    name = "ibkr"

    def __init__(self, env: Mapping[str, str] | None = None, ib=None):
        env = os.environ if env is None else env
        self.endpoint: Endpoint = resolve_endpoint("ibkr", env)
        if ib is None:
            try:
                from ib_insync import IB  # type: ignore[import-not-found]
            except ImportError as exc:
                raise BrokerError("IBKR needs the ib_insync package (pip install ib_insync) and TWS or IB Gateway "
                                  "running with the API enabled.") from exc
            ib = IB()
            try:
                ib.connect(self.endpoint.host, self.endpoint.port,
                           clientId=int(env.get("IBKR_CLIENT_ID") or 17), timeout=8)
            except Exception as exc:
                raise BrokerError(f"Could not connect to TWS / IB Gateway at {self.endpoint.host}:{self.endpoint.port}: {exc}") from exc
        self.ib = ib
        accounts = list(ib.managedAccounts() or [])
        real = [a for a in accounts if not str(a).upper().startswith("D")]
        if self.mode == "paper" and (real or not accounts):
            ib.disconnect()
            raise BrokerError("Connected to a REAL-money IBKR account while TRADING_MODE is not live. Disconnected.")
        self.account_id = accounts[0] if accounts else None

    @property
    def mode(self):
        return self.endpoint.mode

    def account(self) -> dict:
        vals = {v.tag: v.value for v in self.ib.accountSummary(self.account_id) if v.currency in ("USD", "EUR", "BASE", "")}
        f = lambda k: float(vals.get(k) or 0)  # noqa: E731
        return {"equity": f("NetLiquidation"), "cash": f("TotalCashValue"), "buying_power": f("BuyingPower"),
                "day_pnl": None, "currency": "USD", "blocked": False}

    def positions(self) -> list[dict]:
        return [{"symbol": p.contract.symbol, "side": "long" if p.position > 0 else "short", "qty": abs(float(p.position)),
                 "entry": float(p.avgCost), "price": None, "pnl": None} for p in self.ib.positions() if p.position]

    def quote(self, symbol: str) -> float | None:
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
        from ib_insync import Stock  # type: ignore[import-not-found]

        if type != "limit" or not limit_price or not take_profit:
            raise BrokerError("IBKR orders are sent as bracket orders: limit entry, stop-loss and target are required.")
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        trades = [self.ib.placeOrder(contract, o) for o in self.ib.bracketOrder(
            side.upper(), qty, limit_price, take_profit, stop_loss)]
        return {"id": str(trades[0].order.orderId), "status": trades[0].orderStatus.status, "symbol": symbol,
                "side": side, "qty": float(qty)}

    def cancel(self, order_id: str) -> None:
        for t in self.ib.openTrades():
            if str(t.order.orderId) == str(order_id):
                self.ib.cancelOrder(t.order)

    def close_position(self, symbol: str) -> dict | None:
        from ib_insync import MarketOrder  # type: ignore[import-not-found]

        for t in self.ib.openTrades():
            if t.contract.symbol == symbol:
                self.ib.cancelOrder(t.order)
        for p in self.ib.positions():
            if p.contract.symbol == symbol and p.position:
                t = self.ib.placeOrder(p.contract, MarketOrder("SELL" if p.position > 0 else "BUY", abs(p.position)))
                return {"symbol": symbol, "status": t.orderStatus.status}
        return None

    def close_all(self) -> dict:
        self.ib.reqGlobalCancel()
        closed, errors = [], []
        for p in self.positions():
            try:
                if self.close_position(p["symbol"]):
                    closed.append(p["symbol"])
            except Exception as exc:
                errors.append(f"{p['symbol']}: {exc}")
        return {"cancelled": -1, "closed": closed, "errors": errors}
