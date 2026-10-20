from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Provider = Literal["yahoo", "ccxt"]


class DataQuery(BaseModel):
    provider: Provider = "yahoo"
    exchange: str = "binance"
    symbol: str = Field("AAPL", min_length=1, max_length=40)
    timeframe: str = "1d"
    start: str | None = None
    end: str | None = None
    limit: int | None = Field(None, ge=50, le=20_000)


class BacktestRequest(DataQuery):
    strategy: str = "ema_cross_rsi"
    params: dict[str, Any] = Field(default_factory=dict)
    capital: float = Field(10_000, gt=0)
    risk_per_trade: float = Field(0.01, gt=0, le=0.2)
    fee: float = Field(0.001, ge=0, le=0.05)
    slippage: float = Field(0.0005, ge=0, le=0.05)
    allow_short: bool = True


class PredictRequest(BaseModel):
    provider: Provider = "yahoo"
    exchange: str = "binance"
    symbols: list[str] = Field(default_factory=lambda: ["AAPL"], min_length=1, max_length=20)
    timeframe: str = "1d"
    start: str | None = None
    limit: int | None = Field(None, ge=300, le=20_000)
    horizon: int = Field(5, ge=1, le=100)
    threshold_atr: float = Field(0.5, gt=0, le=5)
    min_confidence: float = Field(0.45, ge=0.34, le=0.99)


class PicksRequest(BaseModel):
    preset: Literal["momentum", "quality_momentum", "low_volatility", "trend_following"] = "quality_momentum"
    top_n: int = Field(10, ge=3, le=30)
    rebalance: Literal["ME", "QE", "W-FRI"] = "ME"
    start: str = "2015-01-01"
    trend_filter: bool = True
    regime_filter: bool = False
    cost_bps: float = Field(10, ge=0, le=200)
    symbols: list[str] | None = Field(None, max_length=300)   # default: S&P 500 members of the universe
    benchmark: str = "SPY"


class PaperOrder(BaseModel):
    """Only the idea is chosen by the client; prices, stop, target and expiry come from the server."""
    symbol: str = Field(..., min_length=1, max_length=20)
    side: Literal["long", "short"]
    preview: bool = False      # True: only compute the plan (size, max loss), don't place it


class OrderPreview(BaseModel):
    """Only the idea is chosen by the client; prices, size, stop, target and expiry come from the server."""
    symbol: str = Field(..., min_length=1, max_length=20)
    side: Literal["long", "short"]


class OrderPlace(OrderPreview):
    confirm_token: str | None = Field(None, max_length=100)   # from /api/orders/preview; required


class PortfolioRequest(BaseModel):
    amount: float = Field(10_000, gt=0, le=100_000_000)
    currency: Literal["EUR", "USD"] = "EUR"
    risk: Literal["cautious", "balanced", "bold"] = "balanced"
    fractional: bool = True


class PredictionsRequest(BaseModel):
    horizon: Literal[1, 5, 21] = 5
    universe: Literal["us", "sp500", "custom"] = "us"
    symbols: list[str] | None = Field(None, max_length=300)


class WatchlistBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    symbols: list[str] = Field(default_factory=list, max_length=200)


class AlertBody(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    kind: Literal["above", "below", "move"]
    value: float = Field(gt=0, lt=1e9, allow_inf_nan=False)
    note: str = Field("", max_length=200)

    @field_validator("note")
    @classmethod
    def _one_line(cls, v: str) -> str:   # goes verbatim into email / WhatsApp
        return " ".join("".join(c if c.isprintable() else " " for c in v).split())

    @model_validator(mode="after")
    def _sane_move(self):
        if self.kind == "move" and self.value > 100:
            raise ValueError("A daily move alert must be between 0 and 100%")
        return self
