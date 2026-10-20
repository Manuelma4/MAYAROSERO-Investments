"""The practice account (existing PaperBroker) behind the Broker interface. Default; never real money."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from ...live.paper import PaperBroker
from .base import BrokerError, Endpoint, require_protection, resolve_endpoint

STRATEGY = "opportunity"   # positions opened from the Invest button


class PaperAdapter:
    name = "paper"

    def __init__(self, paper: PaperBroker, quotes: Callable[[list[str]], list[dict]] | None = None):
        self.endpoint: Endpoint = resolve_endpoint("paper")
        self.paper = paper
        self._quotes = quotes or (lambda symbols: [])

    @property
    def mode(self):
        return self.endpoint.mode

    def _prices(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        return {q["symbol"]: q["price"] for q in self._quotes(symbols) if q.get("price")}

    def positions(self) -> list[dict]:
        pos = self.paper.positions_list()
        px = self._prices([p["symbol"] for p in pos])
        for p in pos:
            price = px.get(p["symbol"])
            d = 1 if p["side"] == "long" else -1
            p["price"] = price
            p["pnl"] = None if price is None else d * (price - p["entry"]) * p["qty"]
        return pos

    def account(self) -> dict:
        pos = self.positions()
        open_pnl = sum(p["pnl"] or 0 for p in pos)
        opp_open = sum(p["pnl"] or 0 for p in pos if p["strategy"] == STRATEGY)
        today = pd.Timestamp.now(tz="UTC").normalize()
        equity = self.paper.cash + open_pnl
        return {"equity": equity, "cash": self.paper.cash, "buying_power": max(0.0, equity),
                "day_pnl": self.paper.realized_since(today) + min(0.0, opp_open),   # open losses count, open gains don't
                "currency": "USD", "blocked": False, "open_pnl": open_pnl}

    def quote(self, symbol: str) -> float | None:
        return None   # use the app's market data

    def normalize_qty(self, symbol: str, qty: float) -> float:
        return qty

    def place_order(self, symbol, side, qty, type="market", limit_price=None, stop_loss=None, take_profit=None) -> dict:
        require_protection(side, qty, stop_loss)
        price = limit_price or self._prices([symbol]).get(symbol)
        if not price:
            raise BrokerError(f"No current price for {symbol}.")
        pos = self.paper.open(symbol, STRATEGY, "long" if side == "buy" else "short", float(price), float(stop_loss),
                              take_profit, pd.Timestamp.now(tz="UTC").isoformat(), qty=qty)
        if pos is None:
            raise BrokerError("The practice order could not be opened.")
        return {"id": f"paper-{symbol}-{pos.entry_time}", "status": "filled", "symbol": symbol, "side": side,
                "qty": qty, "filled_price": pos.entry}

    def cancel(self, order_id: str) -> None:
        return None   # paper orders fill immediately

    def symbol_key(self, symbol: str) -> str:
        return symbol.strip().upper()

    def close_position(self, symbol: str, qty: float | None = None, order_ids: list[str] | None = None,
                       stop: float | None = None, side: str = "long") -> dict | None:
        out = None
        for p in [p for p in self.paper.positions.values() if p.symbol == symbol and p.strategy == STRATEGY]:
            price = self._prices([symbol]).get(symbol) or p.entry
            out = self.paper.close(p.symbol, p.strategy, price, pd.Timestamp.now(tz="UTC").isoformat(), "closed by you")
        return out

    def close_all(self) -> dict:
        pos = list(self.paper.positions.values())
        px = self._prices([p.symbol for p in pos])
        closed = []
        for p in pos:
            rec = self.paper.close(p.symbol, p.strategy, px.get(p.symbol) or p.entry,
                                   pd.Timestamp.now(tz="UTC").isoformat(), "closed by you")
            if rec:
                closed.append(rec)
        return {"cancelled": 0, "closed": closed, "errors": []}
