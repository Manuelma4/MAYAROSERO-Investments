"""Crypto exchanges (Binance, Kraken, ...) through ccxt. Spot, long only.

Paper mode = the exchange's sandbox / testnet (``set_sandbox_mode(True)``), decided in base.resolve_endpoint.
An exchange without a test network cannot be used in paper mode: the adapter refuses rather than falling
back to the real exchange.

Each entry is an immediate-or-cancel limit buy (a market order with a price cap), followed by a stop-loss
order held at the exchange. If the exchange refuses the stop, the fresh position is sold at once.
The target and the time limit are watched by the app (precompute loop).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from .base import BrokerError, Endpoint, require_protection, resolve_endpoint


class CCXTBroker:
    name = "ccxt"

    def __init__(self, env: Mapping[str, str] | None = None, exchange=None):
        env = os.environ if env is None else env
        self.endpoint: Endpoint = resolve_endpoint("ccxt", env)
        self.exchange_id = (env.get("CCXT_EXCHANGE") or "binance").strip().lower()
        self.quote_ccy = (env.get("CCXT_QUOTE") or "USDT").strip().upper()
        if exchange is None:
            import ccxt

            cls = getattr(ccxt, self.exchange_id, None)
            if cls is None:
                raise BrokerError(f"Unknown CCXT_EXCHANGE={self.exchange_id!r}.")
            key, secret = env.get("CCXT_API_KEY"), env.get("CCXT_SECRET")
            if not key or not secret:
                raise BrokerError("Exchange keys missing: add CCXT_API_KEY and CCXT_SECRET to .env.")
            exchange = cls({"apiKey": key, "secret": secret, "enableRateLimit": True,
                            "options": {"defaultType": "spot", "warnOnFetchOpenOrdersWithoutSymbol": False}})
        if self.endpoint.sandbox:   # must happen before ANY request
            try:
                exchange.set_sandbox_mode(True)
            except Exception as exc:
                raise BrokerError(f"{self.exchange_id} has no test network, so it cannot be used in paper mode. "
                                  "Use BROKER=paper, or an exchange with a sandbox (e.g. binance).") from exc
            if getattr(exchange, "isSandboxModeEnabled", True) is not True:
                raise BrokerError(f"{self.exchange_id}: sandbox mode did not switch on. Refusing to continue.")
        self.ex = exchange

    @property
    def mode(self):
        return self.endpoint.mode

    def _sym(self, symbol: str) -> str:
        s = symbol.upper().replace("-", "/")
        if "/" not in s:
            raise BrokerError(f"{symbol} is not a crypto pair. Stocks need BROKER=alpaca or ibkr.")
        base, quote = s.split("/", 1)
        return f"{base}/{self.quote_ccy if quote in ('USD', 'USDT', 'USDC') and self.quote_ccy.startswith('USD') else quote}"

    def _holdings(self) -> tuple[dict, dict[str, float]]:
        bal = self.ex.fetch_balance()
        totals = {k: float(v) for k, v in (bal.get("total") or {}).items() if v and float(v) > 0}
        pairs = [f"{a}/{self.quote_ccy}" for a in totals if a != self.quote_ccy]
        prices: dict[str, float] = {}
        if pairs:
            try:
                tick = self.ex.fetch_tickers(pairs)
            except Exception:
                tick = {}
                for p in pairs:
                    try:
                        tick[p] = self.ex.fetch_ticker(p)
                    except Exception:
                        continue
            prices = {p: float(t["last"]) for p, t in tick.items() if t and t.get("last")}
        return totals, prices

    def account(self) -> dict:
        totals, prices = self._holdings()
        cash = totals.get(self.quote_ccy, 0.0)
        equity = cash + sum(q * prices.get(f"{a}/{self.quote_ccy}", 0.0) for a, q in totals.items() if a != self.quote_ccy)
        return {"equity": equity, "cash": cash, "buying_power": cash, "day_pnl": None,
                "currency": self.quote_ccy, "blocked": False}

    def positions(self) -> list[dict]:
        totals, prices = self._holdings()
        out = []
        for a, q in totals.items():
            pair = f"{a}/{self.quote_ccy}"
            price = prices.get(pair)
            if a == self.quote_ccy or not price or q * price < 1:   # skip dust
                continue
            out.append({"symbol": pair, "side": "long", "qty": q, "entry": price, "price": price, "pnl": None})
        return out

    def quote(self, symbol: str) -> float | None:
        try:
            t = self.ex.fetch_ticker(self._sym(symbol))
            return float(t["last"]) if t.get("last") else None
        except BrokerError:
            raise
        except Exception:
            return None

    def normalize_qty(self, symbol: str, qty: float) -> float:
        sym = self._sym(symbol)
        try:
            self.ex.load_markets()
            q = float(self.ex.amount_to_precision(sym, qty))
        except Exception:
            q = qty
        if q > qty:          # never round up
            q = qty
        if q <= 0:
            raise BrokerError(f"The planned size for {sym} is below the exchange's minimum.")
        return q

    def place_order(self, symbol, side, qty, type="market", limit_price=None, stop_loss=None, take_profit=None) -> dict:
        require_protection(side, qty, stop_loss)
        if side != "buy":
            raise BrokerError("Short selling is not available on spot crypto. Only rising (long) ideas can be invested.")
        has = getattr(self.ex, "has", {}) or {}
        if not (has.get("createStopLossOrder") or has.get("createStopOrder")):
            raise BrokerError(f"{self.exchange_id} cannot hold a stop-loss order through ccxt. Refusing to buy without one.")
        sym = self._sym(symbol)
        if type == "limit":
            if not limit_price:
                raise BrokerError("A limit order needs a limit price.")
            entry = self.ex.create_order(sym, "limit", "buy", qty, limit_price, {"timeInForce": "IOC"})
        else:
            entry = self.ex.create_order(sym, "market", "buy", qty)
        filled = float(entry.get("filled") or 0)
        if not filled and entry.get("id") and entry.get("status") not in ("closed", "canceled", "expired"):
            try:
                entry = self.ex.fetch_order(entry["id"], sym)
                filled = float(entry.get("filled") or 0)
            except Exception:
                pass
        if not filled:
            return {"id": entry.get("id"), "status": "not filled", "symbol": sym, "side": side, "qty": 0.0}
        try:
            stop = self.ex.create_order(sym, "market", "sell", filled, None, {"stopLossPrice": float(stop_loss)})
        except Exception as exc:
            try:
                self.ex.create_order(sym, "market", "sell", filled)   # never keep an unprotected position
            except Exception as exc2:
                raise BrokerError(f"DANGER: the exchange refused the stop-loss ({exc}) AND the emergency sale failed "
                                  f"({exc2}). Sell {filled} {sym} on the exchange now.") from exc2
            raise BrokerError(f"The exchange refused the stop-loss ({exc}); the purchase was sold again at once.") from exc
        return {"id": entry.get("id"), "status": "filled", "symbol": sym, "side": side, "qty": filled,
                "filled_price": entry.get("average") or entry.get("price"), "stop_order_id": stop.get("id")}

    def cancel(self, order_id: str, symbol: str | None = None) -> None:
        self.ex.cancel_order(order_id, symbol)

    def _cancel_open(self, symbol: str | None = None) -> int:
        n = 0
        for o in self.ex.fetch_open_orders(symbol) or []:
            self.ex.cancel_order(o["id"], o.get("symbol"))
            n += 1
        return n

    def close_position(self, symbol: str) -> dict | None:
        sym = self._sym(symbol)
        self._cancel_open(sym)
        base = sym.split("/")[0]
        free = float((self.ex.fetch_balance().get("free") or {}).get(base) or 0)
        if free <= 0:
            return None
        return self.ex.create_order(sym, "market", "sell", free)

    def close_all(self) -> dict:
        errors: list[str] = []
        try:
            cancelled = self._cancel_open()
        except Exception as exc:
            cancelled, errors = 0, [f"cancel orders: {exc}"]
        closed = []
        for p in self.positions():
            try:
                self.ex.create_order(p["symbol"], "market", "sell", p["qty"])
                closed.append(p["symbol"])
            except Exception as exc:
                errors.append(f"{p['symbol']}: {exc}")
        return {"cancelled": cancelled, "closed": closed, "errors": errors}
