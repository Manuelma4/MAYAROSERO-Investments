"""Broker adapters behind one interface. Choose with BROKER=paper|alpaca|ccxt|ibkr (default paper).

Real money needs BOTH a real broker AND TRADING_MODE=live set by the owner in .env; see base.resolve_endpoint.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from .base import (ALPACA_URLS, BROKERS, Broker, BrokerError, Endpoint, is_crypto, resolve_endpoint,
                   trading_mode)
from .paper import PaperAdapter

__all__ = ["ALPACA_URLS", "BROKERS", "Broker", "BrokerError", "Endpoint", "PaperAdapter", "broker_name",
           "is_crypto", "make_broker", "resolve_endpoint", "trading_mode"]


def broker_name(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get("BROKER") or "paper").strip().lower()


def make_broker(env: Mapping[str, str] | None = None, *, paper=None, quotes=None) -> Broker:
    """Build the configured broker. ``paper``: the app's PaperBroker (practice account) for BROKER=paper."""
    env = os.environ if env is None else env
    name = broker_name(env)
    resolve_endpoint(name, env)   # validates the name and the paper/live configuration first
    if name == "paper":
        if paper is None:
            from ...live.paper import PaperBroker

            paper = PaperBroker()
        return PaperAdapter(paper, quotes)
    if name == "alpaca":
        from .alpaca import AlpacaBroker

        return AlpacaBroker(env)
    if name == "ccxt":
        from .ccxt_broker import CCXTBroker

        return CCXTBroker(env)
    from .ibkr import IBKRBroker

    return IBKRBroker(env)
