from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from .. import indicators as ta
from ..analysis import candlesticks as cs
from ..analysis.swings import pivots
from ..backtest import BacktestConfig, run_backtest
from ..ml import Predictor
from ..report import analyze_structure
from ..strategies import REGISTRY, get_strategy
from . import serialize as ser
from .market import DataUnavailable
from .schemas import BacktestRequest, DataQuery, PredictRequest

router = APIRouter(prefix="/api")

BULL = ("hammer", "bullish_engulfing", "morning_star")
BEAR = ("shooting_star", "bearish_engulfing", "evening_star")


def _state(request: Request):
    return request.app.state


def _load(request: Request, q: DataQuery | PredictRequest, symbol: str | None = None):
    try:
        return _state(request).market.history(
            q.provider, symbol or q.symbol, q.timeframe, exchange=q.exchange,
            start=q.start, end=getattr(q, "end", None), limit=q.limit)
    except DataUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc


def _pattern_markers(df) -> list[dict]:
    pats = cs.scan(df)
    out = []
    for t, row in pats.iterrows():
        for name in BULL:
            if row[name]:
                out.append({"time": ser.ts(t), "kind": "bull", "label": name})
        for name in BEAR:
            if row[name]:
                out.append({"time": ser.ts(t), "kind": "bear", "label": name})
    return out


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/strategies")
def strategies():
    return [{"name": n, "description": c.description, "defaults": c.defaults} for n, c in REGISTRY.items()]


@router.get("/chart")
def chart(request: Request, provider: str = "yahoo", exchange: str = "binance", symbol: str = "AAPL",
          timeframe: str = "1d", limit: int = Query(500, ge=50, le=5000)):
    q = DataQuery(provider=provider, exchange=exchange, symbol=symbol, timeframe=timeframe, limit=limit)
    df = _load(request, q)
    c = df["close"]
    piv = pivots(df, 5, 5)
    bb = ta.bollinger(c)
    return ser.clean({
        "symbol": symbol, "timeframe": timeframe,
        "candles": ser.candles(df),
        "overlays": {f"ema{n}": ser.line(ta.ema(c, n)) for n in (20, 50, 200)}
        | {"bb_upper": ser.line(bb["upper"]), "bb_lower": ser.line(bb["lower"])},
        "rsi": ser.line(ta.rsi(c)),
        "patterns": _pattern_markers(df),
        "pivots": [{"time": ser.ts(r.time), "kind": r.kind, "price": r.price} for r in piv.itertuples()],
        "analysis": analyze_structure(df),
    })


@router.post("/backtest")
def backtest(request: Request, body: BacktestRequest):
    df = _load(request, body)
    try:
        strat = get_strategy(body.strategy, **body.params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    cfg = BacktestConfig(initial_capital=body.capital, risk_per_trade=body.risk_per_trade,
                         fee=body.fee, slippage=body.slippage, allow_short=body.allow_short)
    try:
        res = run_backtest(df, strat, cfg)
    except KeyError as exc:
        raise HTTPException(400, f"Unknown strategy parameter: {exc}") from exc
    trades = res.trades_frame()
    bh = df["close"] / df["close"].iloc[0] * body.capital
    return ser.clean({
        "stats": res.stats,
        "equity": ser.line(res.equity),
        "buy_hold": ser.line(bh),
        "candles": ser.candles(df),
        "trades": [] if trades.empty else [
            {**r, "entry_time": ser.ts(r["entry_time"]), "exit_time": ser.ts(r["exit_time"])}
            for r in trades.to_dict("records")],
    })


@router.post("/predict")
def predict(request: Request, body: PredictRequest):
    frames = {s: _load(request, body, s) for s in dict.fromkeys(x.strip() for x in body.symbols if x.strip())}
    p = Predictor(horizon=body.horizon, threshold_atr=body.threshold_atr, min_confidence=body.min_confidence)
    try:
        validation = p.walk_forward(frames)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    p.fit(frames)
    preds = [p.predict_latest(s, df, validation) for s, df in frames.items()]
    return ser.clean({
        "validation": validation,
        "predictions": [{"symbol": x.symbol, "time": x.time, "action": x.action,
                         "probabilities": x.probabilities, "confidence": x.confidence,
                         "has_edge": x.has_edge, "last_close": float(frames[x.symbol]["close"].iloc[-1])}
                        for x in preds],
    })


# ---- live engine ---------------------------------------------------------

@router.get("/live/status")
def live_status(request: Request):
    return _state(request).engine.status()


@router.post("/live/start")
def live_start(request: Request):
    _state(request).engine.start()
    return _state(request).engine.status()


@router.post("/live/stop")
def live_stop(request: Request):
    _state(request).engine.stop()
    return _state(request).engine.status()


@router.post("/live/scan")
async def live_scan(request: Request):
    events = await asyncio.to_thread(_state(request).engine.scan_once)
    return {"events": events, "status": _state(request).engine.status()}


@router.get("/events")
def events(request: Request, type: str | None = None, limit: int = Query(100, ge=1, le=1000),
           before_id: int | None = None):
    return _state(request).store.list(type, limit, before_id)


@router.get("/paper")
def paper(request: Request):
    sc = _state(request).engine.scanner
    if sc is None or sc.broker is None:
        return {"enabled": False, "cash": None, "positions": [], "history": []}
    b = sc.broker
    return ser.clean({"enabled": True, "cash": b.cash,
                      "positions": [vars(p) for p in b.positions.values()],
                      "history": list(reversed(b.history[-200:]))})


ws_router = APIRouter()


@ws_router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    app = websocket.app
    token = app.state.settings.api_token
    if token and websocket.query_params.get("token") != token:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    q = app.state.broadcaster.subscribe()
    try:
        await websocket.send_json({"type": "status", **app.state.engine.status()})
        while True:
            await websocket.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        app.state.broadcaster.unsubscribe(q)
