"""Stock screener: filter the universe by sector, size, valuation, dividend, trend and momentum.

Pure functions, no network:
- `technicals(df)` reads one daily OHLCV frame (the histories the opportunity scanner already loads every few
  minutes): today's move, 1/6/12-month returns, above the 200-day average, distance from the 52-week high and
  volatility. Everything uses bars up to the latest one only (it describes the present, it predicts nothing).
- `build_rows()` joins the universe, the daily fundamentals (`data/fundamentals.py`) and the technicals.
- `Filters` + `apply()` + `sort_rows()` do the screening. Beginner bands (size, valuation, momentum) are defined
  here once and sent to the app with every response so the UI never hard-codes a threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

M1, M6, M12 = 21, 126, 252     # trading days in 1, 6 and 12 months
VOL_DAYS = 63                  # volatility over the last 3 months

# Company size by market value in US dollars. The S&P 500 only holds big companies (Wall Street calls nearly all
# of them "large caps"), so the bands split this universe into useful groups instead.
SIZE_BANDS = [("small", 0.0, 15e9), ("mid", 15e9, 50e9), ("large", 50e9, 200e9), ("mega", 200e9, math.inf)]
# Valuation by P/E over the last 12 months (the S&P 500 is usually around 20 to 25).
PE_BANDS = [("cheap", 0.0, 15.0), ("fair", 15.0, 25.0), ("expensive", 25.0, math.inf)]
NO_PROFIT = "no_profit"        # no P/E: the company lost money over the last 12 months
STRONG_MOMENTUM = 80.0         # "strongest": top 20% of the universe by 6-month return

SORT_KEYS = ("symbol", "name", "sector", "market_cap", "pe", "forward_pe", "dividend_yield", "beta", "price",
             "change_pct", "ret_1m", "ret_6m", "ret_12m", "vs_200d_pct", "from_high_pct", "volatility",
             "momentum_pct")
TEXT_KEYS = ("symbol", "name", "sector")


def _ret(close: np.ndarray, n: int) -> float | None:
    if len(close) <= n or close[-1 - n] <= 0:
        return None
    return float((close[-1] / close[-1 - n] - 1) * 100)


def technicals(df: pd.DataFrame | None) -> dict | None:
    """Price-based figures from daily bars (last bar = latest session). None when there is too little data."""
    if df is None or len(df) < 30:
        return None
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    if not np.isfinite(close[-1]) or close[-1] <= 0:
        return None
    rets = np.diff(np.log(close[-(VOL_DAYS + 1):]))
    sma200 = float(close[-200:].mean()) if len(close) >= 200 else None
    hi52 = float(np.nanmax(high[-M12:]))
    return {
        "price": float(close[-1]),
        "change_pct": float((close[-1] / close[-2] - 1) * 100) if close[-2] > 0 else None,
        "ret_1m": _ret(close, M1), "ret_6m": _ret(close, M6), "ret_12m": _ret(close, M12),
        "above_200d": None if sma200 is None else bool(close[-1] > sma200),
        "vs_200d_pct": None if sma200 is None else float((close[-1] / sma200 - 1) * 100),
        "from_high_pct": float(min(0.0, (close[-1] / hi52 - 1) * 100)) if hi52 > 0 else None,
        "high_52w_days": min(len(close), M12),   # bars the "52-week" high covers (less for young listings)
        "volatility": float(rets.std(ddof=1) * math.sqrt(252) * 100) if len(rets) > 20 else None,
        "as_of": df.index[-1].isoformat(),
    }


def size_band(cap_usd: float | None) -> str | None:
    if cap_usd is None:
        return None
    return next(name for name, lo, hi in SIZE_BANDS if lo <= cap_usd < hi)


def valuation_band(pe: float | None, has_fundamentals: bool) -> str | None:
    if pe is None:
        return NO_PROFIT if has_fundamentals else None
    return next(name for name, lo, hi in PE_BANDS if lo <= pe < hi)


def bands() -> dict:
    """Thresholds for the app (JSON-safe: open upper bounds are None)."""
    def j(rows):
        return [{"id": n, "min": lo, "max": None if math.isinf(hi) else hi} for n, lo, hi in rows]
    return {"size": j(SIZE_BANDS), "valuation": j(PE_BANDS), "strong_momentum_pct": STRONG_MOMENTUM}


def build_rows(stocks, fundamentals: dict[str, dict], tech: dict[str, dict], fx: dict[str, float]) -> list[dict]:
    """One row per stock. `fx` maps a currency to US dollars per unit (market values are compared in USD)."""
    rows = []
    for st in stocks:
        f = fundamentals.get(st.symbol) or {}
        has_f = bool(f.get("_ok_at"))
        t = tech.get(st.symbol) or {}
        cap, ccy = f.get("market_cap"), f.get("currency") or "USD"
        rate = 0.01 * fx.get("GBP", math.nan) if ccy == "GBp" else (1.0 if ccy == "USD" else fx.get(ccy))
        cap_usd = cap * rate if cap and rate and math.isfinite(rate) else None
        rows.append({
            "symbol": st.symbol, "name": st.name, "sector": st.sector, "industry": st.industry, "region": st.region,
            "currency": ccy if has_f else None,
            "market_cap": cap_usd, "size": size_band(cap_usd),
            "pe": f.get("pe"), "forward_pe": f.get("forward_pe"),
            "valuation": valuation_band(f.get("pe"), has_f),
            "dividend_yield": f.get("dividend_yield"), "beta": f.get("beta"),
            "price": t.get("price"), "change_pct": t.get("change_pct"),
            "ret_1m": t.get("ret_1m"), "ret_6m": t.get("ret_6m"), "ret_12m": t.get("ret_12m"),
            "above_200d": t.get("above_200d"), "vs_200d_pct": t.get("vs_200d_pct"),
            "from_high_pct": t.get("from_high_pct"), "volatility": t.get("volatility"),
            "momentum_pct": None, "has_fundamentals": has_f, "has_technicals": bool(t),
        })
    ranked = sorted((r for r in rows if r["ret_6m"] is not None), key=lambda r: r["ret_6m"])
    n = len(ranked)
    for i, r in enumerate(ranked):   # share of the universe with a lower 6-month return (100 = strongest, 0 = weakest)
        r["momentum_pct"] = round(100.0 * i / (n - 1), 1) if n > 1 else 100.0
    return rows


def csv_list(v) -> tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, str):
        v = v.split(",")
    return tuple(x.strip() for x in v if x and x.strip())


@dataclass
class Filters:
    sector: tuple[str, ...] = field(default_factory=tuple)      # any of these sectors
    size: tuple[str, ...] = field(default_factory=tuple)        # any of small / mid / large / mega
    valuation: tuple[str, ...] = field(default_factory=tuple)   # any of cheap / fair / expensive / no_profit
    min_cap: float | None = None                                # US dollars
    max_cap: float | None = None
    min_pe: float | None = None
    max_pe: float | None = None                                 # also drops companies without profits
    min_div: float | None = None                                # percent (2 = 2% a year)
    dividends: bool | None = None                               # True: pays a dividend; False: pays none
    trend: str | None = None                                    # up (above the 200-day average) / down
    momentum: str | None = None                                 # positive (6M > 0) / strong (top 20%)
    q: str | None = None                                        # name, ticker or industry contains

    def __post_init__(self):
        for k in ("sector", "size", "valuation"):
            setattr(self, k, csv_list(getattr(self, k)))

    def active(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, (), "")}


def matches(r: dict, f: Filters) -> bool:
    if f.sector and r["sector"] not in f.sector:
        return False
    if f.size and r["size"] not in f.size:
        return False
    if f.valuation and r["valuation"] not in f.valuation:
        return False
    cap = r["market_cap"]
    if f.min_cap is not None and (cap is None or cap < f.min_cap):
        return False
    if f.max_cap is not None and (cap is None or cap > f.max_cap):
        return False
    pe = r["pe"]
    if f.min_pe is not None and (pe is None or pe < f.min_pe):
        return False
    if f.max_pe is not None and (pe is None or pe > f.max_pe):
        return False
    dy = r["dividend_yield"]
    if f.min_div is not None and (dy is None or dy < f.min_div):
        return False
    if f.dividends is True and not (dy and dy > 0):
        return False
    if f.dividends is False and (dy is None or dy > 0):
        return False
    if f.trend == "up" and r["above_200d"] is not True:
        return False
    if f.trend == "down" and r["above_200d"] is not False:
        return False
    if f.momentum == "positive" and not (r["ret_6m"] is not None and r["ret_6m"] > 0):
        return False
    if f.momentum == "strong" and not (r["momentum_pct"] is not None and r["momentum_pct"] > STRONG_MOMENTUM):
        return False
    if f.q:
        q = f.q.strip().lower()
        if q and not any(q in str(r.get(k) or "").lower() for k in ("symbol", "name", "industry")):
            return False
    return True


def apply(rows: list[dict], f: Filters) -> list[dict]:
    return [r for r in rows if matches(r, f)]


def sort_rows(rows: list[dict], key: str = "market_cap", desc: bool = True) -> list[dict]:
    """Sorted by `key`; rows without a value always go last (whatever the direction)."""
    if key not in SORT_KEYS:
        raise ValueError(f"Unknown sort key {key!r}")
    have = [r for r in rows if r.get(key) is not None]
    missing = [r for r in rows if r.get(key) is None]
    norm = (lambda v: str(v).lower()) if key in TEXT_KEYS else float
    have.sort(key=lambda r: (norm(r[key]), r["symbol"]), reverse=desc)
    return have + sorted(missing, key=lambda r: r["symbol"])
