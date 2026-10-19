"""Bar-by-bar backtester.

Execution model (conservative on purpose):
- A signal at bar i's close is filled at bar i+1's open (+ slippage).
- Stops and targets are checked on every bar against high/low. If both are
  touched within the same bar we assume the STOP was hit first.
- Gaps through a stop fill at the open (worse than the stop), like real life.
- Position size = equity * risk_per_trade / stop distance, capped by
  max_leverage. Fees are charged on both sides.
- One position per symbol at a time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from ..strategies.base import Strategy


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    risk_per_trade: float = 0.01      # 1% of equity risked per trade
    fee: float = 0.001                # 0.1% per side
    slippage: float = 0.0005          # 0.05% adverse fill
    max_leverage: float = 1.0
    allow_short: bool = True


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    qty: float
    stop: float
    target: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    fees: float = 0.0
    bars_held: int = 0

    @property
    def direction(self) -> int:
        return 1 if self.side == "long" else -1

    @property
    def pnl(self) -> float:
        return self.direction * (self.exit_price - self.entry_price) * self.qty - self.fees

    @property
    def r_multiple(self) -> float:
        risk = abs(self.entry_price - self.stop) * self.qty
        return self.pnl / risk if risk else 0.0


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity: pd.Series
    data: pd.DataFrame
    config: BacktestConfig
    stats: dict = field(default_factory=dict)

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "side": t.side, "entry_time": t.entry_time, "entry": t.entry_price,
            "exit_time": t.exit_time, "exit": t.exit_price, "qty": t.qty,
            "stop": t.stop, "target": t.target, "reason": t.exit_reason,
            "pnl": t.pnl, "R": t.r_multiple, "bars": t.bars_held,
        } for t in self.trades])


def run_backtest(df: pd.DataFrame, strategy: Strategy, config: BacktestConfig | None = None) -> BacktestResult:
    from .metrics import summarize

    cfg = config or BacktestConfig()
    data = strategy.prepare(df)
    o, h, l, c = (data[k].values for k in ("open", "high", "low", "close"))
    idx = data.index

    cash = cfg.initial_capital
    pos: Trade | None = None
    pending: tuple[str, float, float] | None = None   # (side, stop, target) to fill next open
    pending_exit = False
    trades: list[Trade] = []
    equity = []

    def close(t: Trade, i: int, price: float, reason: str):
        nonlocal cash
        fill = price * (1 - t.direction * cfg.slippage)
        fee = fill * t.qty * cfg.fee
        t.exit_time, t.exit_price, t.exit_reason = idx[i], fill, reason
        t.fees += fee
        cash += t.direction * (fill - t.entry_price) * t.qty - fee
        trades.append(t)

    for i in range(len(data)):
        # 1) Fills at this bar's open from decisions made at the previous close.
        if pos is not None and pending_exit:
            close(pos, i, o[i], "signal")
            pos = None
        pending_exit = False
        if pos is None and pending is not None:
            side, stop, target = pending
            d = 1 if side == "long" else -1
            fill = o[i] * (1 + d * cfg.slippage)
            risk_per_unit = d * (fill - stop)
            if risk_per_unit > 0:
                qty = cash * cfg.risk_per_trade / risk_per_unit
                qty = min(qty, cash * cfg.max_leverage / fill)
                fee = fill * qty * cfg.fee
                cash -= fee
                pos = Trade(side, idx[i], fill, qty, stop, target, fees=fee)
        pending = None

        # 2) Stop / target management within this bar.
        if pos is not None:
            pos.bars_held += 1
            d = pos.direction
            hit_stop = (l[i] <= pos.stop) if d == 1 else (h[i] >= pos.stop)
            has_tgt = not math.isnan(pos.target)
            hit_tgt = has_tgt and ((h[i] >= pos.target) if d == 1 else (l[i] <= pos.target))
            if hit_stop:
                gapped = (o[i] < pos.stop) if d == 1 else (o[i] > pos.stop)
                close(pos, i, o[i] if gapped else pos.stop, "stop")
                pos = None
            elif hit_tgt:
                gapped = (o[i] > pos.target) if d == 1 else (o[i] < pos.target)
                close(pos, i, o[i] if gapped else pos.target, "target")
                pos = None

        # 3) Decisions at this bar's close.
        row = data.iloc[i]
        if pos is not None:
            if (pos.side == "long" and row.exit_long) or (pos.side == "short" and row.exit_short):
                pending_exit = True
        elif not math.isnan(row.stop):
            if row.entry_long:
                pending = ("long", row.stop, row.target)
            elif row.entry_short and cfg.allow_short:
                pending = ("short", row.stop, row.target)

        mtm = pos.direction * (c[i] - pos.entry_price) * pos.qty if pos else 0.0
        equity.append(cash + mtm)

    if pos is not None:
        close(pos, len(data) - 1, c[-1], "end")
        equity[-1] = cash

    eq = pd.Series(equity, index=idx, name="equity")
    res = BacktestResult(trades, eq, data, cfg)
    res.stats = summarize(res)
    return res
