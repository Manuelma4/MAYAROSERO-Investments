"""Crypto exchanges (Binance, Kraken, ...) through ccxt. Spot, long only.

Paper mode = the exchange's sandbox / testnet (``set_sandbox_mode(True)``), decided in base.resolve_endpoint.
An exchange without a test network cannot be used in paper mode: the adapter refuses rather than falling
back to the real exchange.

Each entry is an immediate-or-cancel limit buy (a market order with a price cap), followed by a stop-loss
order held at the exchange, sized on the coins really received (the fee may be taken in the coin).
If the exchange refuses the stop, the fresh position is sold at once. If the exchange does not answer
clearly (network error, timeout), the balance is checked and any coins found are protected.
Every ccxt exception becomes a BrokerError. The target and the time limit are watched by the app.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping

from .base import BrokerError, Endpoint, require_protection, resolve_endpoint


def _is(exc: Exception, name: str) -> bool:
    """ccxt exception class check without importing ccxt (OrderNotFound, InsufficientFunds, ...)."""
    return any(c.__name__ == name for c in type(exc).__mro__)


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

    # -- helpers ----------------------------------------------------------------------------------------
    def _call(self, what: str, fn, *args, **kw):
        """Run one ccxt call; any exception becomes a BrokerError with a readable message."""
        try:
            return fn(*args, **kw)
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"{self.exchange_id}: {what} failed ({type(exc).__name__}: {exc})") from exc

    def _sym(self, symbol: str) -> str:
        s = symbol.upper().replace("-", "/")
        if "/" not in s:
            raise BrokerError(f"{symbol} is not a crypto pair. Stocks need BROKER=alpaca or ibkr.")
        base, quote = s.split("/", 1)
        return f"{base}/{self.quote_ccy if quote in ('USD', 'USDT', 'USDC') and self.quote_ccy.startswith('USD') else quote}"

    def symbol_key(self, symbol: str) -> str:
        try:
            return self._sym(symbol)
        except BrokerError:
            return symbol.strip().upper()

    def _free(self, base: str) -> float:
        bal = self._call("reading the balance", self.ex.fetch_balance)
        return float((bal.get("free") or {}).get(base) or 0)

    def _amount(self, sym: str, qty: float) -> float:
        """Exchange precision, never rounded up."""
        try:
            q = float(self.ex.amount_to_precision(sym, qty))
        except Exception:
            q = math.floor(qty * 1e8) / 1e8
        return min(q, qty) if q > 0 else 0.0

    def _holdings(self) -> tuple[dict, dict[str, float]]:
        bal = self._call("reading the balance", self.ex.fetch_balance)
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

    # -- Broker ------------------------------------------------------------------------------------------
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
        base = sym.split("/")[0]
        if type == "limit" and not limit_price:
            raise BrokerError("A limit order needs a limit price.")
        before = self._free(base)   # to detect what a failed / unclear entry really bought
        entry, entry_err = None, None
        try:
            if type == "limit":
                entry = self.ex.create_order(sym, "limit", "buy", qty, limit_price, {"timeInForce": "IOC"})
            else:
                entry = self.ex.create_order(sym, "market", "buy", qty)
        except Exception as exc:   # NetworkError / timeout: the buy may or may not have happened
            entry_err = exc
        entry = entry or {}
        filled: float | None = float(entry.get("filled") or 0) if entry else None
        if entry and not filled and entry.get("id") and entry.get("status") not in ("closed", "canceled", "expired"):
            try:
                entry = self.ex.fetch_order(entry["id"], sym) or entry
                filled = float(entry.get("filled") or 0)
            except Exception:
                filled = None   # unknown, not "unfilled"
        free = None
        if filled is None:   # unclear outcome: the balance tells what was bought
            try:
                free = self._free(base)
            except BrokerError as exc:
                raise BrokerError(f"DANGER: the exchange did not confirm the buy of {sym} "
                                  f"({entry_err or 'order status unknown'}) and the balance could not be read ({exc}). "
                                  f"Check {self.exchange_id} now: if {base} was bought, it has NO stop-loss.") from exc
            got = max(0.0, free - before)
            if got * float(limit_price or stop_loss) < 1:   # nothing (or dust) arrived
                if entry_err is not None:
                    raise BrokerError(f"The exchange did not accept the buy of {sym} ({type_name(entry_err)}: {entry_err}). "
                                      "Nothing was bought (the balance did not change).") from entry_err
                return {"id": entry.get("id"), "status": "not filled", "symbol": sym, "side": side, "qty": 0.0}
            filled = got
        if not filled:
            return {"id": entry.get("id"), "status": "not filled", "symbol": sym, "side": side, "qty": 0.0}
        # Protect what really arrived: a fee taken in the coin leaves less than "filled".
        if free is None:
            try:
                free = self._free(base)
            except BrokerError:
                free = filled
        q = self._amount(sym, min(filled, free))
        info = {"id": entry.get("id") or f"unconfirmed-{sym}", "symbol": sym, "side": side, "qty": q,
                "filled_qty": filled, "filled_price": entry.get("average") or entry.get("price") or limit_price}
        try:
            stop = self.ex.create_order(sym, "market", "sell", q, None, {"stopLossPrice": float(stop_loss)})
        except Exception as exc:
            try:
                self.ex.create_order(sym, "market", "sell", q)   # never keep an unprotected position
            except Exception as exc2:
                raise BrokerError(f"DANGER: the exchange refused the stop-loss ({exc}) AND the emergency sale failed "
                                  f"({exc2}). Sell {q} {sym} on the exchange now. The app keeps trying to sell it.",
                                  order={**info, "status": "filled, NO STOP-LOSS", "unprotected": True}) from exc2
            raise BrokerError(f"The exchange refused the stop-loss ({exc}); the purchase was sold again at once.",
                              order={**info, "status": "sold again (stop refused)", "closed": True}) from exc
        stop_id = str((stop or {}).get("id")) if (stop or {}).get("id") else None
        return {**info, "status": "filled" if entry_err is None else "filled (confirmed from the balance)",
                "stop_order_id": stop_id, "legs": [stop_id] if stop_id else []}

    def cancel(self, order_id: str, symbol: str | None = None) -> None:
        self._call("cancelling an order", self.ex.cancel_order, order_id, symbol)

    def _cancel_open(self, symbol: str | None = None) -> int:
        n = 0
        for o in self._call("listing open orders", self.ex.fetch_open_orders, symbol) or []:
            self._call("cancelling an order", self.ex.cancel_order, o["id"], o.get("symbol"))
            n += 1
        return n

    def _order_done(self, oid: str, sym: str) -> bool:
        try:
            return (self.ex.fetch_order(oid, sym) or {}).get("status") in ("closed", "canceled", "expired", "rejected")
        except Exception:
            return False

    def _protect(self, sym: str, q: float, stop: float | None) -> str:
        if not stop:
            raise BrokerError("no stop price known")
        o = self._call("placing the stop-loss", self.ex.create_order, sym, "market", "sell", q, None,
                       {"stopLossPrice": float(stop)})
        return str((o or {}).get("id"))

    def close_position(self, symbol: str, qty: float | None = None, order_ids: list[str] | None = None,
                       stop: float | None = None, side: str = "long") -> dict | None:
        """Cancel this order's own stop, then sell at most ``qty`` (never coins the app did not buy)."""
        sym = self._sym(symbol)
        for oid in order_ids or []:
            try:
                self.ex.cancel_order(oid, sym)
            except Exception as exc:
                if not (_is(exc, "OrderNotFound") or self._order_done(oid, sym)):   # filled / cancelled already is fine
                    raise BrokerError(f"{self.exchange_id}: could not cancel the stop-loss of {sym} ({exc}); "
                                      "it is still in place. The close is retried on the next check.") from exc
        base = sym.split("/")[0]
        free = self._free(base)
        q = self._amount(sym, free if qty is None else min(float(qty), free))
        if q <= 0:
            return None
        try:
            return self.ex.create_order(sym, "market", "sell", q)
        except Exception as exc:
            if not order_ids:
                raise BrokerError(f"{self.exchange_id}: selling {q} {sym} failed ({exc}).") from exc
            try:
                new_stop = self._protect(sym, q, stop)
            except BrokerError as exc2:
                raise BrokerError(f"DANGER: selling {sym} failed ({exc}) and re-placing its stop-loss also failed "
                                  f"({exc2}). Check it on {self.exchange_id} now.") from exc2
            raise BrokerError(f"Selling {sym} failed ({exc}); its stop-loss was placed again at {stop}.",
                              legs=[new_stop]) from exc

    def close_all(self) -> dict:
        errors: list[str] = []
        try:
            cancelled = self._cancel_open()
        except BrokerError as exc:
            cancelled, errors = 0, [f"cancel orders: {exc}"]
        closed = []
        for p in self.positions():
            try:
                q = self._amount(p["symbol"], self._free(p["symbol"].split("/")[0]))
                self._call(f"selling {p['symbol']}", self.ex.create_order, p["symbol"], "market", "sell", q)
                closed.append(p["symbol"])
            except BrokerError as exc:
                errors.append(f"{p['symbol']}: {exc}")
        return {"cancelled": cancelled, "closed": closed, "errors": errors}


def type_name(exc: Exception) -> str:
    return type(exc).__name__
