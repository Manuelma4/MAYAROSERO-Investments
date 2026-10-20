"""Alpaca (US stocks) over REST v2. Paper endpoint unless TRADING_MODE=live (decided in base.resolve_endpoint).

Every entry is a bracket order (entry + stop-loss + take-profit held at Alpaca), or an OTO order
(entry + stop-loss) when there is no target, so the stop lives at the broker even if this app is off.
"""

from __future__ import annotations

import math
import os
import uuid
from collections.abc import Mapping

from .base import ALPACA_DATA_URL, ALPACA_URLS, BrokerError, Endpoint, is_crypto, require_protection, resolve_endpoint


def _px(x: float) -> float:
    """Alpaca accepts 2 decimals at $1 and above, 4 below."""
    return round(float(x), 2 if x >= 1 else 4)


class AlpacaBroker:
    name = "alpaca"

    def __init__(self, env: Mapping[str, str] | None = None, session=None, timeout: float = 10.0):
        env = os.environ if env is None else env
        self.endpoint: Endpoint = resolve_endpoint("alpaca", env)
        key, secret = env.get("ALPACA_API_KEY_ID"), env.get("ALPACA_API_SECRET_KEY")
        if not key or not secret:
            raise BrokerError("Alpaca keys missing: add ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY to .env.")
        if session is None:
            import requests

            session = requests.Session()
        self.s = session
        self.s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
        self.timeout = timeout

    @property
    def mode(self):
        return self.endpoint.mode

    # -- HTTP -------------------------------------------------------------------------------------------
    def _base(self) -> str:
        url = self.endpoint.url
        if url != ALPACA_URLS[self.endpoint.mode]:   # belt and braces: endpoint and mode can never disagree
            raise BrokerError("Alpaca endpoint does not match the trading mode. Refusing to send.")
        return url

    def _req(self, method: str, path: str, base: str | None = None, **kw):
        try:
            r = self.s.request(method, (base or self._base()) + path, timeout=self.timeout, **kw)
        except Exception as exc:  # network errors
            raise BrokerError(f"Could not reach Alpaca: {exc}") from exc
        if r.status_code >= 400:
            try:
                msg = r.json().get("message") or r.text
            except Exception:
                msg = r.text
            raise BrokerError(f"Alpaca refused ({r.status_code}): {msg}")
        if not r.content:
            return None
        return r.json()

    # -- Broker ------------------------------------------------------------------------------------------
    def account(self) -> dict:
        a = self._req("GET", "/v2/account")
        equity = float(a.get("equity") or 0)
        last = a.get("last_equity")
        return {"equity": equity, "cash": float(a.get("cash") or 0), "buying_power": float(a.get("buying_power") or 0),
                "day_pnl": equity - float(last) if last not in (None, "") else None,
                "currency": a.get("currency") or "USD", "account_number": a.get("account_number"),
                "blocked": bool(a.get("trading_blocked") or a.get("account_blocked") or a.get("status") not in (None, "ACTIVE"))}

    def positions(self) -> list[dict]:
        out = []
        for p in self._req("GET", "/v2/positions") or []:
            out.append({"symbol": p["symbol"], "side": p.get("side", "long"), "qty": abs(float(p["qty"])),
                        "entry": float(p["avg_entry_price"]), "price": float(p.get("current_price") or 0) or None,
                        "pnl": float(p.get("unrealized_pl") or 0)})
        return out

    def quote(self, symbol: str) -> float | None:
        if is_crypto(symbol):
            return None
        try:
            t = self._req("GET", f"/v2/stocks/{symbol}/trades/latest", base=ALPACA_DATA_URL)
            return float(t["trade"]["p"])
        except (BrokerError, KeyError, TypeError, ValueError):
            return None

    def normalize_qty(self, symbol: str, qty: float) -> float:
        if is_crypto(symbol):
            raise BrokerError("Crypto is traded with BROKER=ccxt (an exchange), not Alpaca, in this app.")
        whole = float(math.floor(qty + 1e-9))   # bracket orders need whole shares
        if whole < 1:
            raise BrokerError(f"The planned size for {symbol} is under 1 share; Alpaca bracket orders need whole shares.")
        return whole

    def place_order(self, symbol, side, qty, type="market", limit_price=None, stop_loss=None, take_profit=None) -> dict:
        require_protection(side, qty, stop_loss)
        if qty != int(qty):
            raise BrokerError("Alpaca bracket orders need a whole number of shares.")
        body = {"symbol": symbol, "qty": str(int(qty)), "side": side, "type": type, "time_in_force": "day",
                "order_class": "bracket" if take_profit else "oto", "stop_loss": {"stop_price": _px(stop_loss)},
                "client_order_id": f"mri-{uuid.uuid4().hex[:20]}"}
        if take_profit:
            body["take_profit"] = {"limit_price": _px(take_profit)}
        if type == "limit":
            if not limit_price:
                raise BrokerError("A limit order needs a limit price.")
            body["limit_price"] = _px(limit_price)
        o = self._req("POST", "/v2/orders", json=body)
        return {"id": o.get("id"), "status": o.get("status"), "symbol": symbol, "side": side, "qty": float(qty),
                "client_order_id": body["client_order_id"]}

    def cancel(self, order_id: str) -> None:
        self._req("DELETE", f"/v2/orders/{order_id}")

    def close_position(self, symbol: str) -> dict | None:
        # The bracket's stop / target legs reserve the shares: cancel them first.
        for o in self._req("GET", "/v2/orders", params={"status": "open", "symbols": symbol, "nested": "true"}) or []:
            self.cancel(o["id"])
        return self._req("DELETE", f"/v2/positions/{symbol}")

    def close_all(self) -> dict:
        cancelled = self._req("DELETE", "/v2/orders") or []
        closed = self._req("DELETE", "/v2/positions", params={"cancel_orders": "true"}) or []
        errors = [c for c in closed if isinstance(c, dict) and int(c.get("status", 200)) >= 400]
        return {"cancelled": len(cancelled), "closed": [c.get("symbol") for c in closed if c not in errors],
                "errors": [f"{e.get('symbol')}: {(e.get('body') or {}).get('message', 'failed')}" for e in errors]}
