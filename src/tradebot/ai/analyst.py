"""AI analyst: a small "trading desk" reviews one stock before you invest.

Inspired by TradingAgents (multi-agent LLM trading firm, Apache-2.0): a technical analyst, a news
analyst, a fundamentals analyst, a bull and a bear researcher who debate, and a risk manager who
gives the final verdict. To keep cost low it runs as ONE structured Claude call per stock per day,
fed with data the app already has (prices, indicators, the engine's factors, recent headlines).

Enabled by ANTHROPIC_API_KEY in .env (pay-as-you-go). Without a key the app works the same and the
UI explains how to turn this on. Output is research, never an instruction to trade.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import indicators as ta

log = logging.getLogger(__name__)

MODEL = os.environ.get("AI_ANALYST_MODEL", "claude-opus-5-5")

SYSTEM = """You are the research desk of MAYAROSERO Investments, reviewing ONE stock for a private investor
who is learning. You play six roles in order: technical analyst, news analyst, fundamentals analyst,
bull researcher, bear researcher, and finally the risk manager who decides.

Rules:
- Use only the data provided. If something is missing, say so; never invent numbers, events or quotes.
- Be concrete and plain-English: short sentences a non-expert understands.
- The bull and bear must each make their strongest honest case.
- The risk manager weighs both, then gives a verdict: "favorable", "neutral" or "avoid" for the proposed
  idea (or for holding the stock if no idea is proposed), a confidence from 0 to 100, the main risk,
  and what would invalidate the idea.
- This is research for an adult making their own decisions, not personal financial advice. Never promise returns."""

SCHEMA = {
    "type": "object",
    "properties": {
        "technical": {"type": "string"},
        "news": {"type": "string"},
        "fundamentals": {"type": "string"},
        "bull_case": {"type": "string"},
        "bear_case": {"type": "string"},
        "verdict": {"type": "string", "enum": ["favorable", "neutral", "avoid"]},
        "confidence": {"type": "integer"},
        "summary": {"type": "string"},
        "main_risk": {"type": "string"},
        "invalidation": {"type": "string"},
    },
    "required": ["technical", "news", "fundamentals", "bull_case", "bear_case", "verdict", "confidence",
                 "summary", "main_risk", "invalidation"],
    "additionalProperties": False,
}


class AnalystUnavailable(RuntimeError):
    pass


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("AI_ANALYST", "on").lower() != "off"


def technical_snapshot(df: pd.DataFrame) -> dict:
    c = df["close"]
    out = {
        "last_close": float(c.iloc[-1]),
        "return_1d_%": float((c.iloc[-1] / c.iloc[-2] - 1) * 100),
        "return_1m_%": float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) > 22 else None,
        "return_12m_%": float((c.iloc[-1] / c.iloc[-253] - 1) * 100) if len(c) > 253 else None,
        "vs_200d_avg_%": float((c.iloc[-1] / c.iloc[-200:].mean() - 1) * 100),
        "rsi_14": float(ta.rsi(c).iloc[-1]),
        "atr_%": float(ta.atr(df).iloc[-1] / c.iloc[-1] * 100),
        "volume_vs_20d_avg": float(df["volume"].iloc[-1] / df["volume"].iloc[-21:-1].mean()),
        "52w_high": float(df["high"].iloc[-252:].max()),
        "52w_low": float(df["low"].iloc[-252:].min()),
    }
    return {k: (round(v, 2) if isinstance(v, float) and np.isfinite(v) else None) for k, v in out.items()}


def fundamentals(symbol: str) -> dict:
    """Best-effort key figures from Yahoo (may be unavailable or rate-limited)."""
    keys = ["longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE", "priceToSalesTrailing12Months",
            "revenueGrowth", "earningsGrowth", "profitMargins", "debtToEquity", "dividendYield",
            "recommendationKey", "targetMeanPrice", "numberOfAnalystOpinions"]
    try:
        import yfinance as yf

        from ..data.providers import _YF_LOCK

        with _YF_LOCK:
            info = yf.Ticker(symbol).info or {}
        return {k: info.get(k) for k in keys if info.get(k) is not None}
    except Exception as exc:
        log.debug("fundamentals unavailable for %s: %s", symbol, exc)
        return {}


@dataclass
class Analysis:
    symbol: str
    as_of: str
    model: str
    data: dict

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "as_of": self.as_of, "model": self.model, **self.data}


class AIAnalyst:
    def __init__(self, market, news=None, client=None, ttl: int = 6 * 3600):
        self.market = market
        self.news = news
        self._client = client  # injectable for tests
        self.fundamentals_fn = fundamentals
        self.ttl = ttl
        self._cache: dict[str, tuple[float, Analysis]] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._client is not None or enabled()

    def _get_client(self):
        if self._client is None:
            if not enabled():
                raise AnalystUnavailable("AI analyst is off. Add ANTHROPIC_API_KEY to .env to turn it on.")
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def build_context(self, symbol: str, idea: dict | None = None, factors: dict | None = None) -> dict:
        from ..data import provider_for

        df = self.market.history(provider_for(symbol), symbol, "1d", limit=300)
        heads = []
        if self.news is not None:
            heads = [{"title": h.title, "publisher": h.publisher, "hours_ago": round((time.time() - h.published) / 3600, 1),
                      "catalyst": h.catalyst} for h in self.news.headlines(symbol, max_age_hours=96)[:8]]
        ctx = {"symbol": symbol, "date": pd.Timestamp.now(tz="UTC").date().isoformat(),
               "technical": technical_snapshot(df), "headlines": heads,
               "fundamentals": self.fundamentals_fn(symbol) if "/" not in symbol else {"note": "crypto asset"}}
        if factors:
            ctx["engine_factors"] = factors
        if idea:
            ctx["proposed_idea"] = {k: idea.get(k) for k in ("direction", "entry", "stop", "target", "hold_days", "reasons")}
        return ctx

    def analyze(self, symbol: str, idea: dict | None = None, factors: dict | None = None, force: bool = False) -> Analysis:
        key = f"{symbol}:{(idea or {}).get('direction', 'hold')}"
        with self._lock:
            hit = self._cache.get(key)
        if hit and not force and time.time() - hit[0] < self.ttl:
            return hit[1]
        client = self._get_client()
        ctx = self.build_context(symbol, idea, factors)
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": "Review this stock:\n" + json.dumps(ctx, default=str)}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except Exception as exc:  # network, auth, rate limit: report clearly, keep the app running
            raise AnalystUnavailable(f"AI analyst request failed: {exc}") from exc
        if response.stop_reason == "refusal":
            raise AnalystUnavailable("The AI analyst declined this request.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnalystUnavailable("The AI analyst returned an unreadable answer.") from exc
        data["confidence"] = max(0, min(100, int(data.get("confidence", 0))))
        result = Analysis(symbol, pd.Timestamp.now(tz="UTC").isoformat(), getattr(response, "model", MODEL), data)
        with self._lock:
            self._cache[key] = (time.time(), result)
        return result
