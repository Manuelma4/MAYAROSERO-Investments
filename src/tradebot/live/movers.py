"""Real-time detection of abnormal moves: surges and crashes.

A move is flagged when, over the last `lookback_bars` CLOSED intraday bars:
- the price change is at least `min_move_pct`, AND
- it is statistically unusual for that symbol (z-score vs its own recent
  volatility >= `min_zscore`), AND
- volume confirms it (current volume >= `min_volume_ratio` x average).

The universe can be a fixed list and/or dynamic sources: Yahoo's
day_gainers / day_losers / most_actives screeners for stocks, and the top-N
crypto pairs by 24h volume on a ccxt exchange.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .scanner import closed_bars

log = logging.getLogger(__name__)

# Pegged to ~1 USD: they never "surge or crash" in a tradable way.
STABLECOINS = {"USDT", "USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD", "USDE", "PYUSD", "EUR", "EURI", "USD1"}


@dataclass
class MoveSettings:
    timeframe: str = "5m"
    lookback_bars: int = 3            # 3 x 5m = last 15 minutes
    min_move_pct: float = 2.0
    min_zscore: float = 3.0
    min_volume_ratio: float = 2.0
    vol_window: int = 60              # bars used to measure "normal" volatility / volume


def detect_move(df: pd.DataFrame, s: MoveSettings) -> dict | None:
    """Return move details if the latest closed bars show an abnormal move."""
    n = s.lookback_bars
    if len(df) < s.vol_window + n + 1:
        return None
    c, v = df["close"], df["volume"]
    logret = np.log(c).diff()
    base = logret.iloc[-(s.vol_window + n):-n]
    sigma = base.std()
    move = c.iloc[-1] / c.iloc[-1 - n] - 1
    z = np.log1p(move) / (sigma * np.sqrt(n)) if sigma > 0 else 0.0
    avg_vol = v.iloc[-(s.vol_window + n):-n].mean()
    vol_ratio = v.iloc[-n:].max() / avg_vol if avg_vol > 0 else np.nan   # peak bar of the move
    if abs(move) * 100 < s.min_move_pct or abs(z) < s.min_zscore:
        return None
    if not np.isnan(vol_ratio) and vol_ratio < s.min_volume_ratio:
        return None
    return {
        "time": df.index[-1],
        "direction": "SURGE" if move > 0 else "CRASH",
        "move_pct": move * 100,
        "zscore": float(z),
        "volume_ratio": None if np.isnan(vol_ratio) else float(vol_ratio),
        "price": float(c.iloc[-1]),
        "session_change_pct": float((c.iloc[-1] / df["open"].iloc[-min(len(df), 78)] - 1) * 100),
    }


def format_move(symbol: str, m: dict, s: MoveSettings) -> str:
    arrow = "UP" if m["direction"] == "SURGE" else "DOWN"
    vol = f"{m['volume_ratio']:.1f}x avg volume" if m["volume_ratio"] else "volume n/a"
    mins = s.lookback_bars * int(s.timeframe.rstrip("m")) if s.timeframe.endswith("m") else None
    span = f"{mins} min" if mins else f"{s.lookback_bars} bars"
    return (f"[{m['direction']}] {symbol} {arrow} {m['move_pct']:+.2f}% in {span} "
            f"(z={m['zscore']:+.1f}, {vol})\n"
            f"  price {m['price']:.4f}  bar {m['time']:%Y-%m-%d %H:%M} UTC")


@dataclass
class MoversScanner:
    settings: MoveSettings = field(default_factory=MoveSettings)
    stock_symbols: list[str] = field(default_factory=list)
    stock_screeners: list[str] = field(default_factory=list)
    crypto_symbols: list[str] = field(default_factory=list)
    crypto_exchange: str = "binance"
    crypto_quote: str = "USDT"
    crypto_top_n: int = 0
    _seen: set = field(default_factory=set)
    _exchange: object = None

    @classmethod
    def from_config(cls, cfg: dict) -> "MoversScanner":
        st, cr = cfg.get("stocks", {}), cfg.get("crypto", {})
        keys = MoveSettings.__dataclass_fields__
        return cls(MoveSettings(**{k: v for k, v in cfg.items() if k in keys}),
                   st.get("symbols", []), st.get("screeners", []),
                   cr.get("symbols", []), cr.get("exchange", "binance"),
                   cr.get("quote", "USDT"), cr.get("top_n", 0))

    # ---- universe -------------------------------------------------------
    def stock_universe(self) -> list[str]:
        syms = list(self.stock_symbols)
        if self.stock_screeners:
            import yfinance as yf

            for name in self.stock_screeners:
                try:
                    res = yf.screen(name, count=50)
                    syms += [q["symbol"] for q in res.get("quotes", [])]
                except Exception as exc:
                    log.warning("Yahoo screener %s failed: %s", name, exc)
        return list(dict.fromkeys(syms))

    def _ex(self):
        if self._exchange is None:
            from ..data.providers import CCXTProvider

            # Same configured client as the data provider (Binance data mirror, proxy support).
            self._exchange = CCXTProvider(self.crypto_exchange).exchange
        return self._exchange

    def crypto_universe(self) -> list[str]:
        syms = list(self.crypto_symbols)
        if self.crypto_top_n:
            try:
                tickers = self._ex().fetch_tickers()
                pairs = [(t, d.get("quoteVolume") or 0) for t, d in tickers.items()
                         if t.endswith(f"/{self.crypto_quote}") and t.split("/")[0] not in STABLECOINS]
                syms += [t for t, _ in sorted(pairs, key=lambda x: -x[1])[: self.crypto_top_n]]
            except Exception as exc:
                log.warning("Crypto universe failed: %s", exc)
        return list(dict.fromkeys(syms))

    # ---- data -----------------------------------------------------------
    def _stock_bars(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        import yfinance as yf

        from ..data.providers import normalize

        raw = yf.download(symbols, interval=self.settings.timeframe, period="5d",
                          group_by="ticker", progress=False, auto_adjust=True, threads=True)
        out = {}
        for sym in symbols:
            try:
                sub = raw[sym] if len(symbols) > 1 else raw
                if isinstance(sub.columns, pd.MultiIndex):
                    sub.columns = sub.columns.get_level_values(-1)
                df = normalize(sub)
                if len(df):
                    out[sym] = df
            except Exception:
                continue
        return out

    def _crypto_bars(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        from ..data.providers import OHLCV, normalize

        out = {}
        limit = self.settings.vol_window + self.settings.lookback_bars + 5
        for sym in symbols:
            try:
                rows = self._ex().fetch_ohlcv(sym, self.settings.timeframe, limit=limit)
                df = pd.DataFrame(rows, columns=["ts", *OHLCV])
                df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
                out[sym] = normalize(df)
            except Exception as exc:
                log.debug("ohlcv %s failed: %s", sym, exc)
        return out

    # ---- scan -----------------------------------------------------------
    def scan_frames(self, frames: dict[str, pd.DataFrame]) -> list[tuple[str, dict]]:
        found = []
        for sym, df in frames.items():
            df = closed_bars(df, self.settings.timeframe)
            m = detect_move(df, self.settings)
            if m is None:
                continue
            key = (sym, m["time"], m["direction"])
            if key in self._seen:
                continue
            self._seen.add(key)
            found.append((sym, m))
        return sorted(found, key=lambda x: -abs(x[1]["zscore"]))

    def run_once(self) -> list[tuple[str, dict]]:
        frames = {}
        try:
            frames.update(self._stock_bars(self.stock_universe()))
        except Exception as exc:
            log.warning("Stock movers scan failed: %s", exc)
        try:
            frames.update(self._crypto_bars(self.crypto_universe()))
        except Exception as exc:
            log.warning("Crypto movers scan failed: %s", exc)
        return self.scan_frames(frames)
