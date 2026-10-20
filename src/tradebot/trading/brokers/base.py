"""Broker interface and the ONE function that decides paper vs real money.

Safety contract (see .claude/agents/risk-guardian.md):
- Real money only when the owner sets ``TRADING_MODE=live`` in the environment (.env). Any other value,
  a typo or no value means paper / sandbox.
- ``resolve_endpoint`` is the only place that maps (broker, mode) to a URL / sandbox flag / port.
  Adapters call it themselves from the environment; they accept no URL or mode argument, so no caller
  can point a "paper" adapter at a real-money endpoint.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Mode = Literal["paper", "live"]
BROKERS = ("paper", "alpaca", "ccxt", "ibkr")

ALPACA_URLS = {"paper": "https://paper-api.alpaca.markets", "live": "https://api.alpaca.markets"}
ALPACA_DATA_URL = "https://data.alpaca.markets"     # market data only, same for paper and live
IBKR_PAPER_PORTS = (7497, 4002)                      # TWS paper, IB Gateway paper
IBKR_LIVE_PORTS = (7496, 4001)                       # TWS live, IB Gateway live


class BrokerError(RuntimeError):
    """Configuration or broker-side failure. The message is shown to the user as is.

    ``order``: set when something DID happen at the broker before the failure (e.g. a buy filled but its
    stop-loss was refused), so the caller can journal it: {id, symbol, side, qty, status, unprotected, closed, legs}.
    ``legs``: broker order ids now protecting the position (e.g. a stop re-placed after a failed close).
    """

    def __init__(self, message: str, *, order: dict | None = None, legs: list[str] | None = None):
        super().__init__(message)
        self.order, self.legs = order, legs


def trading_mode(env: Mapping[str, str] | None = None) -> Mode:
    """``live`` only when TRADING_MODE is exactly 'live' (case and spaces ignored). Everything else is paper."""
    env = os.environ if env is None else env
    return "live" if str(env.get("TRADING_MODE") or "").strip().lower() == "live" else "paper"


@dataclass(frozen=True)
class Endpoint:
    broker: str
    mode: Mode                  # what the account really is: paper/sandbox or real money
    url: str | None = None      # REST base URL (Alpaca)
    sandbox: bool = True        # ccxt: use the exchange's test network
    host: str | None = None     # IBKR TWS / Gateway
    port: int | None = None


def resolve_endpoint(broker: str, env: Mapping[str, str] | None = None) -> Endpoint:
    """THE single decision point for where orders go. Unit-tested in tests/test_brokers.py."""
    env = os.environ if env is None else env
    broker = (broker or "").strip().lower()
    mode = trading_mode(env)
    if broker == "paper":
        return Endpoint("paper", "paper")            # simulated; never real money, whatever TRADING_MODE says
    if broker == "alpaca":
        return Endpoint("alpaca", mode, url=ALPACA_URLS[mode], sandbox=mode != "live")
    if broker == "ccxt":
        return Endpoint("ccxt", mode, sandbox=mode != "live")
    if broker == "ibkr":
        raw = str(env.get("IBKR_PORT") or "").strip()
        try:
            port = int(raw) if raw else (IBKR_LIVE_PORTS[0] if mode == "live" else IBKR_PAPER_PORTS[0])
        except ValueError as exc:
            raise BrokerError(f"IBKR_PORT must be a number, got {raw!r}.") from exc
        if mode == "paper" and port not in IBKR_PAPER_PORTS:
            raise BrokerError(f"IBKR_PORT={port} is not a paper-trading port ({', '.join(map(str, IBKR_PAPER_PORTS))}) "
                              "and TRADING_MODE is not live. Refusing to connect.")
        if mode == "live" and port in IBKR_PAPER_PORTS:
            raise BrokerError(f"TRADING_MODE=live but IBKR_PORT={port} is a paper port. Use 7496 (TWS) or 4001 (Gateway).")
        return Endpoint("ibkr", mode, sandbox=mode != "live", host=env.get("IBKR_HOST") or "127.0.0.1", port=port)
    raise BrokerError(f"Unknown BROKER={broker!r}. Use one of: {', '.join(BROKERS)}.")


@runtime_checkable
class Broker(Protocol):
    """What the order routes need from any broker. Sides are 'buy' (open long) / 'sell' (open short)."""

    name: str
    endpoint: Endpoint

    @property
    def mode(self) -> Mode: ...

    def account(self) -> dict:
        """{equity, cash, buying_power, day_pnl (None if unknown), currency, blocked}"""

    def positions(self) -> list[dict]:
        """[{symbol, side: long|short, qty, entry, price, pnl}]"""

    def quote(self, symbol: str) -> float | None:
        """Broker's own last price, or None to use the app's market data."""

    def normalize_qty(self, symbol: str, qty: float) -> float:
        """Round the planned size DOWN to what the broker accepts; raise BrokerError if it cannot trade it."""

    def place_order(self, symbol: str, side: str, qty: float, type: str = "market", limit_price: float | None = None,
                    stop_loss: float | None = None, take_profit: float | None = None) -> dict:
        """Open a protected position. Returns {id, status, symbol, side, qty, ...}."""

    def cancel(self, order_id: str) -> None: ...

    def close_position(self, symbol: str, qty: float | None = None, order_ids: list[str] | None = None,
                       stop: float | None = None, side: str = "long") -> dict | None:
        """Close what the app opened: at most ``qty`` (None = the whole position, kill switch only), cancelling
        only ``order_ids`` (that order's own stop / target legs). If the close fails after the legs were
        cancelled, the adapter re-places a stop at ``stop`` and raises BrokerError(legs=[new stop id])."""

    def close_all(self) -> dict:
        """Kill switch: cancel every open order and close every position. {cancelled, closed, errors}"""


def is_crypto(symbol: str) -> bool:
    return "/" in symbol or symbol.endswith(("-USD", "-USDT", "-EUR"))


def require_protection(side: str, qty: float, stop_loss: float | None) -> None:
    """Defense in depth inside every adapter: no naked order ever leaves the app."""
    if side not in ("buy", "sell"):
        raise BrokerError("Side must be buy or sell.")
    if not qty or qty <= 0:
        raise BrokerError("Quantity must be positive.")
    if not stop_loss or stop_loss <= 0:
        raise BrokerError("Refused: every order needs a stop-loss.")
