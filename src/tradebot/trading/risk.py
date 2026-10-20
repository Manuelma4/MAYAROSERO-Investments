"""Server-side risk limits for every order (paper now, real brokers later).

Rules (see .claude/agents/risk-guardian.md):
- every order has a stop-loss on the correct side of the entry
- size comes from risk per trade (default 1% of equity), capped per position
- limits on open positions, short exposure and daily loss; expired signals are refused
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd


@dataclass
class RiskLimits:
    risk_per_trade_pct: float = 1.0      # % of equity lost if the stop is hit
    max_position_pct: float = 10.0       # max value of one position, % of equity
    max_open_positions: int = 5          # opportunity (satellite) positions
    max_short_exposure_pct: float = 20.0
    max_daily_loss_pct: float = 3.0
    max_order_value: float | None = None       # absolute cap on one order, account currency (MAX_ORDER_VALUE)
    max_daily_loss_value: float | None = None  # absolute daily loss stop, account currency (MAX_DAILY_LOSS_VALUE)

    @classmethod
    def from_env(cls, env=None) -> "RiskLimits":
        """Owner can only TIGHTEN the defaults from .env: values looser than the defaults are ignored."""
        import os

        env = os.environ if env is None else env
        d = cls()

        def num(key):
            try:
                v = float(env.get(key) or "nan")
            except ValueError:
                return None
            return v if v == v and v > 0 else None

        for old in ("MAX_ORDER_EUR", "MAX_DAILY_LOSS_EUR"):
            if env.get(old):
                logging.getLogger(__name__).warning(
                    "%s is no longer read (it was applied in the account currency, not euros). Use %s, in the "
                    "account currency (USD at Alpaca, USDT on most exchanges).", old, old.replace("_EUR", "_VALUE"))
        return cls(
            risk_per_trade_pct=min(d.risk_per_trade_pct, num("RISK_PER_TRADE_PCT") or d.risk_per_trade_pct),
            max_position_pct=min(d.max_position_pct, num("MAX_POSITION_PCT") or d.max_position_pct),
            max_open_positions=int(min(d.max_open_positions, num("MAX_OPEN_POSITIONS") or d.max_open_positions)),
            max_short_exposure_pct=d.max_short_exposure_pct,
            max_daily_loss_pct=min(d.max_daily_loss_pct, num("MAX_DAILY_LOSS_PCT") or d.max_daily_loss_pct),
            max_order_value=num("MAX_ORDER_VALUE"),
            max_daily_loss_value=num("MAX_DAILY_LOSS_VALUE"),
        )


class OrderRejected(ValueError):
    pass


@dataclass
class OrderPlan:
    symbol: str
    side: str            # "long" | "short"
    entry: float
    stop: float
    target: float | None
    qty: float
    value: float
    max_loss: float
    risk_pct_of_equity: float


def plan_order(symbol: str, side: str, entry: float, stop: float, target: float | None, equity: float,
               open_positions: list[dict], realized_today: float, limits: RiskLimits | None = None,
               expires_at: str | None = None, now: pd.Timestamp | None = None) -> OrderPlan:
    lim = limits or RiskLimits()
    now = now or pd.Timestamp.now(tz="UTC")
    if side not in ("long", "short"):
        raise OrderRejected("Side must be long or short.")
    if not (entry > 0 and stop > 0) or equity <= 0:
        raise OrderRejected("Invalid prices or account value.")
    if side == "long" and stop >= entry or side == "short" and stop <= entry:
        raise OrderRejected("The stop-loss must be below the entry for a long and above it for a short.")
    if expires_at and now > pd.Timestamp(expires_at):
        raise OrderRejected("This signal has expired. Wait for the next scan.")
    if any(p["symbol"] == symbol for p in open_positions):
        raise OrderRejected(f"You already hold a position in {symbol}.")
    if len(open_positions) >= lim.max_open_positions:
        raise OrderRejected(f"Limit reached: at most {lim.max_open_positions} open opportunity positions.")
    if realized_today <= -equity * lim.max_daily_loss_pct / 100:
        raise OrderRejected(f"Daily loss limit reached ({lim.max_daily_loss_pct:.0f}% of the account). New orders resume tomorrow.")
    if lim.max_daily_loss_value and realized_today <= -lim.max_daily_loss_value:
        raise OrderRejected(f"Daily loss limit reached ({lim.max_daily_loss_value:,.0f} lost today). New orders resume tomorrow.")

    risk_unit = abs(entry - stop)
    qty = equity * lim.risk_per_trade_pct / 100 / risk_unit
    qty = min(qty, equity * lim.max_position_pct / 100 / entry)
    if lim.max_order_value:
        qty = min(qty, lim.max_order_value / entry)
    if side == "short":
        short_now = sum(p["qty"] * (p.get("price") or p["entry"]) for p in open_positions if p["side"] == "short")
        room = equity * lim.max_short_exposure_pct / 100 - short_now
        if room <= 0:
            raise OrderRejected(f"Short limit reached: at most {lim.max_short_exposure_pct:.0f}% of the account in short positions.")
        qty = min(qty, room / entry)
    qty = float(int(qty)) if entry > 50 and qty >= 1 else round(qty, 6)
    if qty <= 0:
        raise OrderRejected("Position size rounds to zero.")
    value = qty * entry
    max_loss = qty * risk_unit
    return OrderPlan(symbol, side, entry, stop, target, qty, value, max_loss, max_loss / equity * 100)
