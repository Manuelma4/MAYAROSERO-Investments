"""Paper trading: simulated positions persisted to a JSON file.

Lets you run setups in real time without risking money. Swap this class for
a real broker adapter (ccxt for crypto, Interactive Brokers / Alpaca for
stocks) only after a strategy has proven itself here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


@dataclass
class PaperPosition:
    symbol: str
    strategy: str
    side: str
    entry_time: str
    entry: float
    qty: float
    stop: float
    target: float | None


class PaperBroker:
    def __init__(self, path: str | Path = "paper_state.json", capital: float = 10_000.0,
                 risk_per_trade: float = 0.01, fee: float = 0.001, max_leverage: float = 1.0):
        self.path = Path(path)
        self.risk, self.fee, self.max_leverage = risk_per_trade, fee, max_leverage
        state = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.cash: float = state.get("cash", capital)
        self.positions: dict[str, PaperPosition] = {
            k: PaperPosition(**v) for k, v in state.get("positions", {}).items()}
        self.history: list[dict] = state.get("history", [])

    def _key(self, symbol: str, strategy: str) -> str:
        return f"{symbol}|{strategy}"

    def save(self) -> None:
        self.path.write_text(json.dumps({
            "cash": self.cash,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "history": self.history,
        }, indent=2, default=str))

    def has_position(self, symbol: str, strategy: str) -> bool:
        return self._key(symbol, strategy) in self.positions

    def open(self, symbol, strategy, side, price, stop, target, time, qty: float | None = None) -> PaperPosition | None:
        d = 1 if side == "long" else -1
        risk_unit = d * (price - stop)
        if risk_unit <= 0 or self.has_position(symbol, strategy):
            return None
        if qty is None:
            qty = min(self.cash * self.risk / risk_unit, self.cash * self.max_leverage / price)
        self.cash -= price * qty * self.fee
        tgt = None if target is None or pd.isna(target) else float(target)
        pos = PaperPosition(symbol, strategy, side, str(time), float(price), qty, float(stop), tgt)
        self.positions[self._key(symbol, strategy)] = pos
        self.save()
        return pos

    def close(self, symbol, strategy, price, time, reason) -> dict | None:
        pos = self.positions.pop(self._key(symbol, strategy), None)
        if pos is None:
            return None
        d = 1 if pos.side == "long" else -1
        fee = price * pos.qty * self.fee
        pnl = d * (price - pos.entry) * pos.qty - fee
        self.cash += pnl
        rec = {**asdict(pos), "exit_time": str(time), "exit": float(price), "reason": reason, "pnl": pnl}
        self.history.append(rec)
        self.save()
        return rec

    def check_exits(self, symbol, strategy, bar: pd.Series, time) -> dict | None:
        """Apply stop / target to the latest closed bar (stop first if both hit)."""
        pos = self.positions.get(self._key(symbol, strategy))
        if pos is None:
            return None
        long = pos.side == "long"
        if (bar["low"] <= pos.stop) if long else (bar["high"] >= pos.stop):
            return self.close(symbol, strategy, pos.stop, time, "stop")
        if pos.target is not None and ((bar["high"] >= pos.target) if long else (bar["low"] <= pos.target)):
            return self.close(symbol, strategy, pos.target, time, "target")
        return None

    def equity(self, prices: dict[str, float]) -> float:
        mtm = 0.0
        for p in self.positions.values():
            if p.symbol in prices:
                d = 1 if p.side == "long" else -1
                mtm += d * (prices[p.symbol] - p.entry) * p.qty
        return self.cash + mtm

    def positions_list(self, strategy: str | None = None) -> list[dict]:
        return [asdict(p) for p in self.positions.values() if strategy is None or p.strategy == strategy]

    def realized_since(self, since: pd.Timestamp) -> float:
        total = 0.0
        for h in self.history:
            try:
                t = pd.Timestamp(h["exit_time"])
            except (ValueError, TypeError):
                continue
            t = t.tz_localize("UTC") if t.tzinfo is None else t
            if t >= since:
                total += h["pnl"]
        return total
