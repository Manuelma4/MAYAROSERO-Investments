"""Real-time scanner.

Every `poll_seconds` it pulls the latest candles for each watchlist symbol,
drops the still-forming candle, runs every configured strategy on the last
CLOSED bar and sends an alert when a setup triggers. Optionally manages
simulated positions through the PaperBroker.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import pandas as pd

from ..data import get_provider
from ..strategies import get_strategy
from .notifier import build_notifiers
from .paper import PaperBroker

log = logging.getLogger(__name__)


def timeframe_delta(tf: str) -> pd.Timedelta:
    units = {"m": "min", "h": "h", "d": "D", "wk": "W"}
    for suffix in ("wk", "m", "h", "d"):
        if tf.endswith(suffix):
            return pd.Timedelta(int(tf[: -len(suffix)]), units[suffix])
    raise ValueError(f"Bad timeframe {tf}")


def closed_bars(df: pd.DataFrame, timeframe: str, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Drop the last candle if it has not closed yet."""
    now = now or pd.Timestamp.now(tz="UTC")
    if len(df) and df.index[-1] + timeframe_delta(timeframe) > now:
        return df.iloc[:-1]
    return df


@dataclass
class WatchItem:
    provider: str
    symbol: str
    timeframe: str
    strategies: list[dict]
    exchange: str = "binance"


@dataclass
class Scanner:
    watchlist: list[WatchItem]
    notifiers: list = field(default_factory=lambda: build_notifiers(["console"]))
    broker: PaperBroker | None = None
    history_bars: int = 400
    movers: object = None             # optional MoversScanner
    _seen: set = field(default_factory=set)
    _providers: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict) -> "Scanner":
        items = [WatchItem(provider=w["provider"], symbol=s, timeframe=w["timeframe"],
                           strategies=w["strategies"], exchange=w.get("exchange", "binance"))
                 for w in cfg.get("watchlist") or [] for s in w["symbols"]]
        broker = None
        paper = cfg.get("paper_trading", {})
        if paper.get("enabled"):
            risk = cfg.get("risk", {})
            broker = PaperBroker(paper.get("state_file", "paper_state.json"),
                                 capital=paper.get("capital", 10_000),
                                 risk_per_trade=risk.get("risk_per_trade", 0.01),
                                 fee=risk.get("fee", 0.001),
                                 max_leverage=risk.get("max_leverage", 1.0))
        movers = None
        if cfg.get("movers", {}).get("enabled"):
            from .movers import MoversScanner

            movers = MoversScanner.from_config(cfg["movers"])
        return cls(items, build_notifiers(cfg.get("notifiers", ["console"])), broker,
                   cfg.get("history_bars", 400), movers)

    def _provider(self, item: WatchItem):
        key = (item.provider, item.exchange)
        if key not in self._providers:
            self._providers[key] = get_provider(item.provider, exchange=item.exchange)
        return self._providers[key]

    def _notify(self, text: str) -> None:
        for n in self.notifiers:
            n.send(text)

    def check(self, item: WatchItem, df: pd.DataFrame | None = None) -> list[dict]:
        """Evaluate one watchlist item on its last closed bar. Returns alerts sent."""
        if df is None:
            df = self._provider(item).latest(item.symbol, item.timeframe, self.history_bars)
        df = closed_bars(df, item.timeframe)
        if len(df) < 50:
            return []
        bar_time = df.index[-1]
        alerts = []
        for spec in item.strategies:
            spec = dict(spec)
            strat = get_strategy(spec.pop("name"), **spec.pop("params", {}))
            last = strat.prepare(df).iloc[-1]
            key = (item.symbol, item.timeframe, strat.name, bar_time)
            if key in self._seen:
                continue
            self._seen.add(key)

            if self.broker:
                closed = self.broker.check_exits(item.symbol, strat.name, last, bar_time)
                if closed:
                    self._notify(f"[PAPER EXIT] {item.symbol} {strat.name} {closed['side']} "
                                 f"@ {closed['exit']:.4f} ({closed['reason']}) PnL {closed['pnl']:+.2f}")
                pos = self.broker.positions.get(f"{item.symbol}|{strat.name}")
                if pos and ((pos.side == "long" and last.exit_long) or (pos.side == "short" and last.exit_short)):
                    rec = self.broker.close(item.symbol, strat.name, last.close, bar_time, "signal")
                    self._notify(f"[PAPER EXIT] {item.symbol} {strat.name} {rec['side']} "
                                 f"@ {rec['exit']:.4f} (signal) PnL {rec['pnl']:+.2f}")

            side = "long" if last.entry_long else "short" if last.entry_short else None
            if side is None or pd.isna(last.stop):
                continue
            alert = {"time": bar_time, "symbol": item.symbol, "timeframe": item.timeframe,
                     "strategy": strat.name, "side": side, "price": float(last.close),
                     "stop": float(last.stop),
                     "target": None if pd.isna(last.target) else float(last.target)}
            risk = abs(alert["price"] - alert["stop"])
            rr = f"{abs(alert['target'] - alert['price']) / risk:.2f}" if alert["target"] and risk else "n/a"
            self._notify(
                f"[SIGNAL] {side.upper()} {item.symbol} ({item.timeframe}) via {strat.name}\n"
                f"  bar close {bar_time:%Y-%m-%d %H:%M} UTC  price {alert['price']:.4f}\n"
                f"  stop {alert['stop']:.4f}  target {alert['target'] if alert['target'] else '-'}  R:R {rr}")
            if self.broker:
                pos = self.broker.open(item.symbol, strat.name, side, alert["price"],
                                       alert["stop"], alert["target"], bar_time)
                if pos:
                    self._notify(f"[PAPER OPEN] {side} {pos.qty:.6f} {item.symbol} @ {pos.entry:.4f}")
            alerts.append(alert)
        return alerts

    def run_once(self) -> list[dict]:
        alerts = []
        for item in self.watchlist:
            try:
                alerts += self.check(item)
            except Exception as exc:
                log.warning("Scan failed for %s %s: %s", item.symbol, item.timeframe, exc)
        if self.movers is not None:
            from .movers import format_move

            for sym, move in self.movers.run_once():
                self._notify(format_move(sym, move, self.movers.settings))
                alerts.append({"type": "move", "symbol": sym, **move})
        return alerts

    def run_forever(self, poll_seconds: int = 60) -> None:
        self._notify(f"tradebot live scanner started: {len(self.watchlist)} setups watched, "
                     f"poll every {poll_seconds}s" + (" | paper trading ON" if self.broker else "")
                     + (" | movers detection ON" if self.movers else ""))
        while True:
            started = time.time()
            self.run_once()
            time.sleep(max(1.0, poll_seconds - (time.time() - started)))
