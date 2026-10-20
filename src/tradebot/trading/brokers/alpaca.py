"""Alpaca (US stocks) over REST v2. Paper endpoint unless TRADING_MODE=live (decided in base.resolve_endpoint).

Every entry is a bracket order (entry + stop-loss + take-profit held at Alpaca), or an OTO order
(entry + stop-loss) when there is no target, so the stop lives at the broker even if this app is off.
"""

from __future__ import annotations

import math
import os
import time
import uuid
from collections.abc import Mapping

import pandas as pd

from .base import ALPACA_DATA_URL, ALPACA_URLS, BrokerError, Endpoint, is_crypto, require_protection, resolve_endpoint

DONE = {"filled", "canceled", "expired", "rejected", "replaced"}   # order states that no longer reserve shares
MAX_TRADE_AGE = pd.Timedelta(minutes=15)   # older last trade (market closed, halted stock) = no broker price


def _px(x: float) -> float:
    """Alpaca accepts 2 decimals at $1 and above, 4 below."""
    return round(float(x), 2 if x >= 1 else 4)


class AlpacaHTTPError(BrokerError):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class AlpacaBroker:
    name = "alpaca"

    def __init__(self, env: Mapping[str, str] | None = None, session=None, timeout: float = 10.0,
                 cancel_wait: float = 5.0, sleep=time.sleep):
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
        self.feed = (env.get("ALPACA_DATA_FEED") or "iex").strip().lower()
        self.cancel_wait, self.sleep = cancel_wait, sleep

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
            raise AlpacaHTTPError(f"Alpaca refused ({r.status_code}): {msg}", r.status_code)
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

    def symbol_key(self, symbol: str) -> str:
        return symbol.strip().upper()

    def quote(self, symbol: str) -> float | None:
        """Last trade on ALPACA_DATA_FEED (iex by default); None if unavailable or older than MAX_TRADE_AGE."""
        if is_crypto(symbol):
            return None
        try:
            t = self._req("GET", f"/v2/stocks/{symbol}/trades/latest", base=ALPACA_DATA_URL,
                          params={"feed": self.feed})["trade"]
            when = t.get("t")
            if when and pd.Timestamp.now(tz="UTC") - pd.Timestamp(when).tz_convert("UTC") > MAX_TRADE_AGE:
                return None
            return float(t["p"])
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
        legs = [str(leg["id"]) for leg in o.get("legs") or [] if leg.get("id")]
        return {"id": o.get("id"), "status": o.get("status"), "symbol": symbol, "side": side, "qty": float(qty),
                "client_order_id": body["client_order_id"], "legs": [str(o.get("id")), *legs] if o.get("id") else legs,
                "stop_order_id": next((str(leg["id"]) for leg in o.get("legs") or []
                                       if leg.get("type") in ("stop", "stop_limit") and leg.get("id")), None)}

    def cancel(self, order_id: str) -> None:
        self._req("DELETE", f"/v2/orders/{order_id}")

    # -- closing what the app opened -----------------------------------------------------------------------
    def _held(self, symbol: str) -> float:
        """Signed quantity held (+ long, - short), 0 if none."""
        try:
            p = self._req("GET", f"/v2/positions/{symbol}")
        except AlpacaHTTPError as exc:
            if exc.status == 404:
                return 0.0
            raise
        q = abs(float((p or {}).get("qty") or 0))
        return -q if (p or {}).get("side") == "short" else q

    def _own_orders(self, order_ids: list[str]) -> list[str]:
        """The given order ids plus their child legs (if the journal only had the parent id)."""
        ids = [str(i) for i in order_ids if i]
        if len(ids) == 1:
            try:
                o = self._req("GET", f"/v2/orders/{ids[0]}", params={"nested": "true"}) or {}
                ids += [str(leg["id"]) for leg in o.get("legs") or [] if leg.get("id")]
            except BrokerError:
                pass
        return list(dict.fromkeys(ids))

    def _cancel_and_wait(self, ids: list[str]) -> list[str]:
        """Cancel these orders and wait until Alpaca confirms. Returns ids still not done after cancel_wait."""
        for oid in ids:
            try:
                self.cancel(oid)
            except BrokerError:
                pass   # already filled / cancelled: the status check below tells
        deadline = time.monotonic() + self.cancel_wait
        pending = list(ids)
        while True:
            still = []
            for oid in pending:
                try:
                    st = (self._req("GET", f"/v2/orders/{oid}") or {}).get("status")
                except AlpacaHTTPError as exc:
                    st = "canceled" if exc.status == 404 else None
                except BrokerError:
                    st = None
                if st not in DONE:
                    still.append(oid)
            pending = still
            if not pending or time.monotonic() >= deadline:
                return pending
            self.sleep(0.5)

    def _protect(self, symbol: str, held: float, stop: float | None) -> str:
        """Re-place a stop-loss for ``held`` shares. Returns its id; raises BrokerError if Alpaca refuses."""
        if not stop:
            raise BrokerError("no stop price known")
        o = self._req("POST", "/v2/orders", json={
            "symbol": symbol, "qty": str(int(abs(held))), "side": "sell" if held > 0 else "buy", "type": "stop",
            "stop_price": _px(stop), "time_in_force": "gtc", "client_order_id": f"mri-{uuid.uuid4().hex[:20]}"})
        return str(o.get("id"))

    def close_position(self, symbol: str, qty: float | None = None, order_ids: list[str] | None = None,
                       stop: float | None = None, side: str = "long") -> dict | None:
        """Cancel only this order's own legs (confirmed), then sell / buy back at most ``qty`` shares.

        If the close fails, a stop-loss is re-placed at once so the position is never left unprotected."""
        own = self._own_orders(order_ids or [])
        pending = self._cancel_and_wait(own) if own else []
        held = self._held(symbol)
        want = 1 if side == "long" else -1
        n = abs(held) if held * want > 0 else 0.0           # only close a position on the side the app opened
        if qty is not None:
            n = min(n, float(qty))
        n = float(math.floor(n + 1e-9))
        if n <= 0:
            return None
        if pending:
            # Not confirmed yet: closing now could fail or double-sell. If the old legs no longer hold the shares,
            # Alpaca accepts a fresh stop; if they still hold them, the old stop is still working.
            msg = f"Alpaca has not confirmed cancelling the stop / target of {symbol} yet; the close is retried on the next check"
            try:
                new_stop = self._protect(symbol, n * want, stop)
            except BrokerError:
                raise BrokerError(msg + ".", legs=own) from None
            raise BrokerError(msg + f"; a stop-loss was placed again at {_px(stop)}.", legs=[new_stop, *pending])
        try:
            return self._req("DELETE", f"/v2/positions/{symbol}", params={"qty": str(int(n))})
        except BrokerError as exc:
            try:
                new_stop = self._protect(symbol, n * want, stop)
            except BrokerError as exc2:
                raise BrokerError(f"DANGER: closing {symbol} failed ({exc}) and re-placing its stop-loss also failed "
                                  f"({exc2}). Check the position at Alpaca now.") from exc2
            raise BrokerError(f"Closing {symbol} failed ({exc}); its stop-loss was placed again at {_px(stop)}.",
                              legs=[new_stop]) from exc

    def close_all(self) -> dict:
        cancelled = self._req("DELETE", "/v2/orders") or []
        closed = self._req("DELETE", "/v2/positions", params={"cancel_orders": "true"}) or []
        errors = [c for c in closed if isinstance(c, dict) and int(c.get("status", 200)) >= 400]
        return {"cancelled": len(cancelled), "closed": [c.get("symbol") for c in closed if c not in errors],
                "errors": [f"{e.get('symbol')}: {(e.get('body') or {}).get('message', 'failed')} "
                           "(its stop-loss may be cancelled: check it at Alpaca)" for e in errors]}
