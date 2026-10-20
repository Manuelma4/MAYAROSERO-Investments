"""Optional live trade / bar streams from the paid feeds (Polygon, Alpaca, Finnhub).

Isolated on purpose: nothing in the app imports this yet, and :func:`stream_from_env` returns
``None`` unless a paid provider and its key are configured. Each client turns the vendor's
WebSocket messages into the same small event dicts:

- ``{"type": "trade", "symbol", "price", "size", "time"}``
- ``{"type": "bar", "symbol", "open", "high", "low", "close", "volume", "time"}`` (1-minute bars)

Symbols are Yahoo style (``BRK-B``) on both ends. ``websockets`` (installed with uvicorn[standard])
honors HTTPS_PROXY by itself.

Usage::

    client = stream_from_env()
    if client:
        await client.run(["AAPL", "MSFT"], on_event=print)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Mapping

import pandas as pd

from .paid import PAID_PROVIDERS, supports, vendor_symbol

log = logging.getLogger(__name__)

Event = dict


def _yahoo(sym: str) -> str:
    return sym.replace(".", "-")


def _iso(value, unit: str | None = None) -> str:
    t = pd.Timestamp(value, unit=unit, tz="UTC") if unit else pd.Timestamp(value)
    return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).isoformat()


class StreamClient:
    """Connect, authenticate, subscribe, parse; reconnect with backoff until stopped."""

    name = "stream"
    url = ""

    def auth_messages(self) -> list[dict]:
        return []

    def subscribe_messages(self, tickers: list[str]) -> list[dict]:
        raise NotImplementedError

    def parse(self, raw: str | bytes) -> list[Event]:
        """Vendor message -> normalized events (pure function, tested offline)."""
        raise NotImplementedError

    def authenticated(self, raw: str | bytes) -> bool:
        """True when this message confirms the login (parse() raises on a rejected key)."""
        return True

    async def _await_auth(self, ws, timeout: float = 15.0) -> None:
        async def wait():
            async for raw in ws:
                self.parse(raw)
                if self.authenticated(raw):
                    return
        await asyncio.wait_for(wait(), timeout)

    async def run(self, symbols: list[str], on_event: Callable[[Event], object],
                  stop: asyncio.Event | None = None, max_backoff: float = 60.0) -> None:
        import websockets

        tickers = [vendor_symbol(s) for s in symbols if supports(s)]
        if not tickers:
            return
        stop = stop or asyncio.Event()
        delay = 1.0
        while not stop.is_set():
            try:
                async with websockets.connect(self.url, open_timeout=15, ping_interval=20) as ws:
                    if auth := self.auth_messages():
                        for msg in auth:
                            await ws.send(json.dumps(msg))
                        await self._await_auth(ws)
                    for msg in self.subscribe_messages(tickers):
                        await ws.send(json.dumps(msg))
                    delay = 1.0
                    async for raw in ws:
                        for ev in self.parse(raw):
                            if ev.get("type") == "pong":
                                continue
                            res = on_event(ev)
                            if asyncio.iscoroutine(res):
                                await res
                        if stop.is_set():
                            return
            except PermissionError:
                raise
            except Exception as exc:  # network drop: reconnect
                log.warning("%s stream disconnected (%s); retrying in %.0fs", self.name, exc, delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, max_backoff)


class PolygonStream(StreamClient):
    """wss://socket.polygon.io/stocks (real-time) or wss://delayed.polygon.io/stocks (15-min plans)."""

    name = "polygon"

    def __init__(self, api_key: str, delayed: bool = False, url: str | None = None):
        self.api_key = api_key
        self.url = url or ("wss://delayed.polygon.io/stocks" if delayed else "wss://socket.polygon.io/stocks")

    def auth_messages(self):
        return [{"action": "auth", "params": self.api_key}]

    def authenticated(self, raw):
        return any(m.get("ev") == "status" and m.get("status") == "auth_success" for m in json.loads(raw))

    def subscribe_messages(self, tickers):
        params = ",".join([f"T.{t}" for t in tickers] + [f"AM.{t}" for t in tickers])
        return [{"action": "subscribe", "params": params}]

    def parse(self, raw):
        out: list[Event] = []
        for m in json.loads(raw):
            ev = m.get("ev")
            if ev == "T":
                out.append({"type": "trade", "symbol": _yahoo(m["sym"]), "price": float(m["p"]),
                            "size": float(m.get("s") or 0), "time": _iso(m["t"], "ms")})
            elif ev == "AM":
                out.append({"type": "bar", "symbol": _yahoo(m["sym"]), "open": float(m["o"]),
                            "high": float(m["h"]), "low": float(m["l"]), "close": float(m["c"]),
                            "volume": float(m.get("v") or 0), "time": _iso(m["s"], "ms")})
            elif ev == "status" and m.get("status") == "auth_failed":
                raise PermissionError(f"polygon stream: {m.get('message')}")
        return out


class AlpacaStream(StreamClient):
    """wss://stream.data.alpaca.markets/v2/{iex|sip}."""

    name = "alpaca"

    def __init__(self, key_id: str, secret: str, feed: str = "iex", url: str | None = None):
        self.key_id, self.secret = key_id, secret
        self.url = url or f"wss://stream.data.alpaca.markets/v2/{feed}"

    def auth_messages(self):
        return [{"action": "auth", "key": self.key_id, "secret": self.secret}]

    def authenticated(self, raw):
        msgs = json.loads(raw)
        return any(m.get("T") == "success" and m.get("msg") == "authenticated"
                   for m in (msgs if isinstance(msgs, list) else [msgs]))

    def subscribe_messages(self, tickers):
        return [{"action": "subscribe", "trades": tickers, "bars": tickers}]

    def parse(self, raw):
        out: list[Event] = []
        msgs = json.loads(raw)
        for m in msgs if isinstance(msgs, list) else [msgs]:
            kind = m.get("T")
            if kind == "t":
                out.append({"type": "trade", "symbol": _yahoo(m["S"]), "price": float(m["p"]),
                            "size": float(m.get("s") or 0), "time": _iso(m["t"])})
            elif kind == "b":
                out.append({"type": "bar", "symbol": _yahoo(m["S"]), "open": float(m["o"]),
                            "high": float(m["h"]), "low": float(m["l"]), "close": float(m["c"]),
                            "volume": float(m.get("v") or 0), "time": _iso(m["t"])})
            elif kind == "error":
                if m.get("code") in (401, 402, 403, 404, 409):  # auth / plan / connection limit
                    raise PermissionError(f"alpaca stream: {m.get('msg')}")
                log.warning("alpaca stream error: %s", m)
        return out


class FinnhubStream(StreamClient):
    """wss://ws.finnhub.io (trades only; Finnhub does not stream bars)."""

    name = "finnhub"

    def __init__(self, api_key: str, url: str | None = None):
        self.url = url or f"wss://ws.finnhub.io?token={api_key}"

    def subscribe_messages(self, tickers):
        return [{"type": "subscribe", "symbol": t} for t in tickers]

    def parse(self, raw):
        m = json.loads(raw)
        if m.get("type") == "ping":
            return [{"type": "pong"}]
        if m.get("type") == "error":
            raise PermissionError(f"finnhub stream: {m.get('msg')}")
        if m.get("type") != "trade":
            return []
        return [{"type": "trade", "symbol": _yahoo(t["s"]), "price": float(t["p"]),
                 "size": float(t.get("v") or 0), "time": _iso(t["t"], "ms")} for t in m.get("data") or []]


def stream_from_env(env: Mapping[str, str] | None = None) -> StreamClient | None:
    """The configured stream client, or None when no paid provider/key is set."""
    env = os.environ if env is None else env
    choice = (env.get("MARKET_DATA_PROVIDER") or "").strip().lower()
    if choice not in PAID_PROVIDERS:
        return None
    if choice == "polygon" and env.get("POLYGON_API_KEY"):
        delayed = (env.get("POLYGON_DELAYED") or "").lower() in {"1", "true", "yes", "on"}
        return PolygonStream(env["POLYGON_API_KEY"], delayed=delayed)
    if choice == "alpaca" and env.get("ALPACA_API_KEY_ID") and env.get("ALPACA_API_SECRET_KEY"):
        return AlpacaStream(env["ALPACA_API_KEY_ID"], env["ALPACA_API_SECRET_KEY"],
                            feed=(env.get("ALPACA_DATA_FEED") or "iex").lower())
    if choice == "finnhub" and env.get("FINNHUB_API_KEY"):
        return FinnhubStream(env["FINNHUB_API_KEY"])
    return None
