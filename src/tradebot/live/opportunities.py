"""Live catalyst-momentum opportunities ("invest now").

A stock (or coin) qualifies when ALL of these hold, using only information available now:
1. Big move today: at least `min_move_pct` vs yesterday's close, and unusual for this stock
   (move / daily volatility >= `min_sigma`).
2. Heavy volume: today's volume is at least `min_rel_volume` x normal for this point of the session.
3. Trend agrees: for a rise, price above the 200-day average and within `near_extreme_pct` of the
   52-week high (for a fall: below the 200-day average and near the 52-week low).
4. Liquid: average daily traded value >= `min_dollar_volume`.
5. A real catalyst: a relevant headline in the last 36 hours. Moves without news are reported
   separately as "watch only" (research: they tend to fade).

Each opportunity carries a plan: entry (last price), a stop beyond today's extreme or 1.5 ATR,
a target at 2x the risk, and a time limit. Signals expire after `expiry_minutes`.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .. import indicators as ta
from .news import Headline


@dataclass
class OpportunityRules:
    min_move_pct: float = 3.0
    min_sigma: float = 2.0
    min_rel_volume: float = 1.8
    near_extreme_pct: float = 12.0
    min_dollar_volume: float = 20e6
    atr_stop: float = 1.5
    reward_risk: float = 2.0
    hold_days: int = 5
    expiry_minutes: int = 180
    crypto_min_move_pct: float = 5.0


@dataclass
class Opportunity:
    symbol: str
    name: str
    direction: str              # "long" (rising) or "short" (falling)
    as_of: str
    price: float
    change_pct: float
    sigma: float                # today's move in units of normal daily volatility
    rel_volume: float
    trend: str                  # plain words
    pct_from_extreme: float     # distance to 52-week high (long) or low (short), %
    entry: float
    stop: float
    target: float
    risk_pct: float             # distance to stop, % of price
    hold_days: int
    expires_at: str
    score: float
    catalyst: str | None
    headline: str | None
    headline_url: str | None
    headline_publisher: str | None
    qualified: bool             # True = has news catalyst; False = watch only
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def session_fraction(now: pd.Timestamp, crypto: bool) -> float:
    """Share of the trading session elapsed (US regular hours 13:30-20:00 UTC; crypto 24h)."""
    if crypto:
        return max(0.05, (now.hour * 60 + now.minute) / 1440)
    minutes = (now.hour * 60 + now.minute) - (13 * 60 + 30)
    if minutes <= 0 or minutes >= 390 or now.weekday() >= 5:
        return 1.0  # market closed: compare the full last session
    return max(0.05, minutes / 390)


def evaluate(symbol: str, name: str, daily: pd.DataFrame, today_volume: float, last_price: float,
             now: pd.Timestamp, headlines: list[Headline], rules: OpportunityRules | None = None,
             crypto: bool = False, today_low: float | None = None, today_high: float | None = None) -> Opportunity | None:
    """Evaluate one symbol. `daily` must contain COMPLETED daily bars only (no partial today)."""
    rules = rules or OpportunityRules()
    if len(daily) < 60 or not (last_price and math.isfinite(last_price)):
        return None
    c = daily["close"]
    prev_close = float(c.iloc[-1])
    change = (last_price / prev_close - 1) * 100
    min_move = rules.crypto_min_move_pct if crypto else rules.min_move_pct
    if abs(change) < min_move:
        return None
    vol = float(np.log(c).diff().iloc[-60:].std() * 100)
    sigma = abs(change) / vol if vol > 0 else 0.0
    avg_vol = float(daily["volume"].iloc[-20:].mean())
    frac = session_fraction(now, crypto)
    rel_volume = today_volume / (avg_vol * frac) if avg_vol > 0 else float("nan")
    dollar_volume = float((daily["close"] * daily["volume"]).iloc[-20:].mean())
    if not crypto and dollar_volume < rules.min_dollar_volume:
        return None
    if sigma < rules.min_sigma or not (rel_volume >= rules.min_rel_volume):
        return None

    long = change > 0
    ma200 = float(c.iloc[-200:].mean()) if len(c) >= 200 else float(c.mean())
    hi52, lo52 = float(daily["high"].iloc[-252:].max()), float(daily["low"].iloc[-252:].min())
    if long:
        trend_ok = last_price > ma200
        extreme = (hi52 / last_price - 1) * 100 if last_price < hi52 else 0.0
    else:
        trend_ok = last_price < ma200
        extreme = (last_price / lo52 - 1) * 100 if last_price > lo52 else 0.0
    if not trend_ok or extreme > rules.near_extreme_pct:
        return None

    atr = float(ta.atr(daily).iloc[-1])
    if long:
        stop = min(today_low if today_low else last_price, last_price - rules.atr_stop * atr)
        target = last_price + rules.reward_risk * (last_price - stop)
    else:
        stop = max(today_high if today_high else last_price, last_price + rules.atr_stop * atr)
        target = last_price - rules.reward_risk * (stop - last_price)
    risk_pct = abs(last_price - stop) / last_price * 100

    top = max(headlines, key=lambda h: (h.strength, h.published)) if headlines else None
    qualified = top is not None
    score = min(sigma, 6) / 6 * 40 + min(rel_volume, 6) / 6 * 30 + max(0, 12 - extreme) / 12 * 15 \
        + (15 if (top and top.catalyst) else 5 if top else 0)

    reasons = [
        f"{'Up' if long else 'Down'} {abs(change):.1f}% today, {sigma:.1f}x its normal daily move",
        f"Volume {rel_volume:.1f}x normal for this time of day",
        f"{'Above' if long else 'Below'} its 200-day average, {extreme:.0f}% from its 52-week {'high' if long else 'low'}",
    ]
    reasons.append(f"News: {top.title}" if top else "No news found: moves without news often fade (watch only)")
    expires = now + pd.Timedelta(minutes=rules.expiry_minutes)
    return Opportunity(
        symbol=symbol, name=name, direction="long" if long else "short", as_of=now.isoformat(),
        price=last_price, change_pct=change, sigma=sigma, rel_volume=rel_volume,
        trend="uptrend" if long else "downtrend", pct_from_extreme=extreme,
        entry=last_price, stop=float(stop), target=float(target), risk_pct=risk_pct, hold_days=rules.hold_days,
        expires_at=expires.isoformat(), score=round(score, 1),
        catalyst=top.catalyst if top else None, headline=top.title if top else None,
        headline_url=top.url if top else None, headline_publisher=top.publisher if top else None,
        qualified=qualified, reasons=reasons,
    )


class OpportunityScanner:
    """Scans US large caps (S&P 500 leaders + popular US-listed) and major crypto."""

    def __init__(self, market, news=None, rules: OpportunityRules | None = None, crypto: bool = True):
        from .news import NewsSource

        self.market = market
        self.news = news or NewsSource()
        self.rules = rules or OpportunityRules()
        self.crypto = crypto

    def universe(self) -> tuple[list[str], list[str]]:
        from ..universe import CRYPTO, STOCKS

        stocks = [s.symbol for s in STOCKS if "." not in s.symbol]  # US listings (US session hours)
        coins = [c for c, _ in CRYPTO] if self.crypto else []
        return stocks, coins

    def scan(self, now: pd.Timestamp | None = None) -> list[Opportunity]:
        from ..universe import CRYPTO, by_symbol

        now = now or pd.Timestamp.now(tz="UTC")
        names = {k: v.name for k, v in by_symbol().items()} | dict(CRYPTO)
        stocks, coins = self.universe()
        found: list[Opportunity] = []
        for provider, syms, is_crypto in (("yahoo", stocks, False), ("ccxt", coins, True)):
            if not syms:
                continue
            try:
                frames = self.market.history_many(provider, syms, "1d", limit=262)
            except Exception:
                continue
            for sym, df in frames.items():
                if len(df) < 61:
                    continue
                today, done = df.iloc[-1], df.iloc[:-1]  # last bar = current / latest session
                # Cheap pre-filter before fetching news.
                pre = evaluate(sym, names.get(sym, sym), done, float(today["volume"]), float(today["close"]), now,
                               [], self.rules, crypto=is_crypto, today_low=float(today["low"]),
                               today_high=float(today["high"]))
                if pre is None:
                    continue
                heads = self.news.headlines(sym, name=names.get(sym))
                opp = evaluate(sym, names.get(sym, sym), done, float(today["volume"]), float(today["close"]), now,
                               heads, self.rules, crypto=is_crypto, today_low=float(today["low"]),
                               today_high=float(today["high"]))
                if opp:
                    found.append(opp)
        return sorted(found, key=lambda o: (not o.qualified, -o.score))
