from __future__ import annotations

import asyncio
import re

import pandas as pd
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
from .schemas import (BacktestRequest, DataQuery, PaperOrder, PicksRequest, PortfolioRequest, PredictionsRequest,
                      PredictRequest, WatchlistBody, AlertBody)
from .settings import token_matches

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


@router.get("/universe")
def universe():
    from ..universe import as_dict

    return as_dict()


@router.post("/picks")
def picks(request: Request, body: PicksRequest):
    from .services import ServiceError, compute_picks

    try:
        return _trim_ranking(compute_picks(_state(request).market, body))
    except ServiceError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/picks/latest")
def picks_latest(request: Request, preset: str = "quality_momentum"):
    """Precomputed picks for a preset with default settings (instant)."""
    from ..picker import PRESETS

    if preset not in PRESETS:
        raise HTTPException(404, f"Unknown strategy '{preset}'. Available: {', '.join(PRESETS)}")
    data = _state(request).precompute.get(f"picks:{preset}")
    if data is None:
        raise HTTPException(503, "Picks are being computed. They will be ready in about a minute.")
    return _trim_ranking(data)


def _trim_ranking(data: dict, n: int = 60) -> dict:
    """The full ranking stays server-side (stock pages use it); the picks page shows the top 60."""
    return {**data, "ranking": data.get("ranking", [])[:n]}


@router.get("/today")
def today(request: Request):
    """Precomputed 'Today' board: market mood, what to hold, changes, movers."""
    data = _state(request).precompute.get("today")
    if data is None:
        raise HTTPException(503, "Today's board is being computed. It will be ready in about a minute.")
    return data


@router.get("/track-record")
def track_record(request: Request, preset: str = "quality_momentum"):
    """Live forward record since the first recorded day: picks vs SPY and Invest-now idea outcomes."""
    from ..picker import PRESETS

    if preset not in PRESETS:
        raise HTTPException(404, f"Unknown strategy '{preset}'. Available: {', '.join(PRESETS)}")
    try:
        return _state(request).precompute.track_record(preset)
    except DataUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/opportunities")
def opportunities(request: Request):
    data = _state(request).precompute.get("opportunities")
    if data is None:
        raise HTTPException(503, "The live scan is running. Opportunities will appear in about a minute.")
    return data


@router.post("/opportunities/scan")
async def opportunities_scan(request: Request):
    return await asyncio.to_thread(_state(request).precompute.scan_opportunities)


def _paper_summary(app_state) -> dict:
    b = app_state.paper
    pos = b.positions_list()
    quotes = {q["symbol"]: q for q in app_state.market.quotes([p["symbol"] for p in pos])} if pos else {}
    for p in pos:
        price = quotes.get(p["symbol"], {}).get("price")
        p["price"] = price
        d = 1 if p["side"] == "long" else -1
        p["pnl"] = None if price is None else d * (price - p["entry"]) * p["qty"]
    open_pnl = sum(p["pnl"] or 0 for p in pos)
    return {"cash": b.cash, "equity": b.cash + open_pnl, "open_pnl": open_pnl, "positions": pos}


@router.post("/paper/orders")
def paper_order(request: Request, body: PaperOrder):
    """Practice order for a LIVE opportunity (always the practice account, whatever BROKER says).
    Same risk path as /api/orders: the server uses its own plan and a fresh price; client prices are ignored."""
    from .orders import _place, checked_plan

    st = _state(request)
    with st.order_lock:
        plan, opp, _ = checked_plan(st, st.paper_adapter, body.symbol, body.side)
        out = {"mode": "paper", "plan": vars(plan)}
        if not body.preview:
            _place(st, st.paper_adapter, plan, opp)
            out["placed"] = True
    return ser.clean(out)


@router.post("/paper/close-all")
def paper_close_all(request: Request):
    """Practice kill switch: close every practice position at the current price."""
    st = _state(request)
    with st.order_lock:
        res = st.paper_adapter.close_all()
    return ser.clean({"closed": res["closed"]})


@router.post("/portfolio")
def portfolio(request: Request, body: PortfolioRequest):
    """Diversified, ready-to-buy plan built from the precomputed picks, live ideas and SPY."""
    import numpy as np
    import pandas as pd

    from ..portfolio import RISK_LEVELS, build_plan, plan_risk

    st = _state(request)
    core = st.precompute.get("picks:quality_momentum")
    if core is None:
        raise HTTPException(503, "The picks are being computed. Try again in about a minute.")
    fx = 1.0
    if body.currency == "EUR":
        fx = st.market.quote("EURUSD=X").get("price") or 0
        if not fx:
            raise HTTPException(502, "EUR/USD rate unavailable. Try again or use USD.")
    amount_usd = body.amount * fx
    spy_price = st.market.quote("SPY").get("price")
    candidates = [r for r in core["ranking"] if r["eligible"]]
    ideas = (st.precompute.get("opportunities") or {}).get("items", [])
    try:
        plan = build_plan(amount_usd, body.risk, candidates, core["risk_off"], ideas, spy_price,
                          fractional=body.fractional)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    syms = [l.symbol for l in plan.lines if l.invested > 0]
    frames = st.market.history_many("yahoo", list(dict.fromkeys(syms + ["SPY"])), "1d", limit=300)
    closes = pd.DataFrame({s: f["close"] for s, f in frames.items()})
    closes.index = closes.index.normalize()
    closes = closes[~closes.index.duplicated(keep="last")]
    risk = plan_risk(plan, closes, closes["SPY"]) if "SPY" in closes else {}

    # Honest track record of the core + anchor mix (satellite ideas are not included).
    c_share, _, a_share = RISK_LEVELS[body.risk]
    eq = pd.Series({p["time"]: p["value"] for p in core["equity"]})
    bm = pd.Series({p["time"]: p["value"] for p in core["benchmark"]})
    r = (c_share * eq.pct_change() + a_share * bm.pct_change()).fillna(0) if not core["risk_off"] else bm.pct_change() * a_share
    blend = (1 + r.fillna(0)).cumprod()
    years = max((eq.index[-1] - eq.index[0]) / 86400 / 365.25, 1e-9)
    track = {"start": core["stats"].get("start"),
             "cagr_%": float((blend.iloc[-1] ** (1 / years) - 1) * 100),
             "spy_cagr_%": float(((bm.iloc[-1] / bm.iloc[0]) ** (1 / years) - 1) * 100),
             "max_drawdown_%": float((blend / blend.cummax() - 1).min() * 100),
             "spy_max_drawdown_%": float((bm / bm.cummax() - 1).min() * 100)}

    def money(x):
        return None if x is None else x / fx

    return ser.clean({
        "currency": body.currency, "fx_usd_per_unit": fx, "risk": body.risk, "amount": body.amount,
        "lines": [{**vars(l), "amount": money(l.amount), "invested": money(l.invested)} for l in plan.lines],
        "cash": money(plan.cash), "by_role": plan.by_role(), "by_sector": plan.by_sector(),
        "risk_metrics": risk, "track_record": track, "changes": core.get("changes"),
        "core_risk_off": core["risk_off"], "as_of": core["as_of"],
        "mix": dict(zip(("core", "satellite", "anchor"), RISK_LEVELS[body.risk])),
    })


@router.get("/predictions")
def predictions(request: Request, horizon: int = Query(5)):
    if horizon not in (1, 5, 21):
        raise HTTPException(400, "Horizon must be 1 (tomorrow), 5 (a week) or 21 (a month).")
    data = _state(request).precompute.get(f"predictions:{horizon}")
    if data is None:
        raise HTTPException(503, "Predictions are being computed (about 1-2 minutes after start).")
    return data


@router.post("/predictions/custom")
async def predictions_custom(request: Request, body: PredictionsRequest):
    from ..universe import sp500_symbols
    from .services import ServiceError, compute_predictions

    syms = None
    if body.universe == "sp500":
        syms = sp500_symbols()
    elif body.universe == "custom":
        syms = [s.strip().upper() for s in (body.symbols or []) if s.strip()]
        if len(syms) < 20:
            raise HTTPException(400, "Add at least 20 stocks so they can be ranked against each other.")
    try:
        return await asyncio.to_thread(compute_predictions, _state(request).market, body.horizon, syms)
    except ServiceError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/forecast")
def forecast(request: Request, symbol: str = Query(..., max_length=20), horizon: int = Query(5, ge=1, le=63)):
    """Monte Carlo price range + volume profile for one symbol, plus its ranking if available."""
    from ..data import provider_for
    from ..forecast import monte_carlo, volume_profile

    st = _state(request)
    try:
        df = st.market.history(provider_for(symbol), symbol, "1d", limit=800)
    except DataUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    try:
        mc = monte_carlo(df["close"], horizon=horizon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    last = df.index[-1]
    days = list(pd.bdate_range(last, periods=horizon + 1)) if "/" not in symbol else list(pd.date_range(last, periods=horizon + 1, freq="D"))
    mc["fan_times"] = [ser.ts(t) for t in days]
    ranked = None
    for h in (horizon, 5):
        pred = st.precompute.get(f"predictions:{h}") if h in (1, 5, 21) else None
        if pred:
            ranked = next((dict(i, horizon=h) for i in pred["items"] if i["symbol"] == symbol), None)
            if ranked:
                break
    return ser.clean({"symbol": symbol, "monte_carlo": mc, "volume_profile": volume_profile(df.iloc[-120:], bins=16),
                      "ranking": ranked})


_FUND_CACHE: dict[str, tuple[float, dict]] = {}


def _fundamentals_cached(symbol: str) -> dict:
    import time as _t

    from ..ai.analyst import fundamentals

    hit = _FUND_CACHE.get(symbol)
    if hit and _t.time() - hit[0] < (6 * 3600 if hit[1] else 300):   # retry failed lookups after 5 min
        return hit[1]
    data = fundamentals(symbol) if "/" not in symbol and not symbol.startswith("^") else {}
    if len(_FUND_CACHE) >= 600:   # bounded: drop the oldest entries
        for k, _ in sorted(_FUND_CACHE.items(), key=lambda kv: kv[1][0])[:100]:
            _FUND_CACHE.pop(k, None)
    _FUND_CACHE[symbol] = (_t.time(), data)
    return data


def pick_verdict(symbol: str, core: dict | None) -> dict:
    """Plain-English answer to 'is this stock one of the engine's picks, and why (not)?'"""
    if not core:
        return {"status": "unknown", "text": "The engine's ranking is being computed."}
    ranking = core.get("ranking", [])
    pos = next((i for i, r in enumerate(ranking) if r["symbol"] == symbol), None)
    picks = {p["symbol"] for p in core.get("picks", [])}
    if pos is None:
        return {"status": "not_covered", "text": "Not covered by the monthly engine, which ranks the S&P 500 members (US stocks only)."}
    r = ranking[pos]
    if core.get("risk_off"):
        return {"status": "risk_off", "rank": pos + 1,
                "text": "The engine is in cash this month: the S&P 500 is below its 200-day average (bear-market filter), "
                        "so it holds no stocks until the trend turns up."}
    rank = f"#{pos + 1} of {core.get('universe_size', len(ranking))}"
    if symbol in picks:
        return {"status": "pick", "rank": pos + 1, "text": f"In this month's picks, ranked {rank}. {r.get('reason', '')}"}
    if not r["eligible"]:
        return {"status": "excluded", "rank": pos + 1,
                "text": f"Not a pick: it is below its 200-day average (a downtrend), and the engine only buys uptrends. Ranked {rank}."}
    return {"status": "ranked", "rank": pos + 1,
            "text": f"Ranked {rank}: good, but only the top {len(picks) or 10} are held. {r.get('reason', '')}"}


@router.get("/stock")
def stock(request: Request, symbol: str = Query(..., max_length=20)):
    """Everything about one stock in one call (instant parts; the chart and forecast load separately)."""
    from ..universe import CRYPTO, STOCKS, by_symbol

    symbol = _known_symbol(symbol)
    st = _state(request)
    info = by_symbol().get(symbol)
    crypto_name = dict(CRYPTO).get(symbol)
    q = st.market.quote(symbol)
    if q.get("price") is None and info is None and crypto_name is None:
        raise HTTPException(404, f"Unknown symbol {symbol}.")
    core = st.precompute.get("picks:quality_momentum")
    pred = st.precompute.get("predictions:5") or {}
    ranked = next((i for i in pred.get("items", []) if i["symbol"] == symbol), None)
    opps = (st.precompute.get("opportunities") or {}).get("items", [])
    idea = next((o for o in opps if o["symbol"] == symbol), None)
    similar = []
    if info:
        same = [s for s in STOCKS if s.symbol != symbol and (s.industry == info.industry or s.sector == info.sector)]
        same.sort(key=lambda s: (s.industry != info.industry, s.symbol))
        similar = [{"symbol": s.symbol, "name": s.name, "industry": s.industry} for s in same[:6]]
    fund = _fundamentals_cached(symbol)
    return ser.clean({
        "symbol": symbol,
        "name": (info.name if info else crypto_name) or fund.get("longName") or symbol,
        "sector": info.sector if info else ("Crypto" if crypto_name else fund.get("sector")),
        "industry": info.industry if info else fund.get("industry"),
        "region": info.region if info else None, "themes": list(info.themes) if info else [],
        "quote": q, "fundamentals": fund, "verdict": pick_verdict(symbol, core),
        "ranking": ranked, "idea": idea, "similar": similar,
    })


@router.get("/ai/status")
def ai_status(request: Request):
    a = _state(request).analyst
    return {"enabled": a.available,
            "how_to_enable": None if a.available else "Add ANTHROPIC_API_KEY to the .env file on the server (see LATER.md)."}


@router.post("/ai/analyze")
async def ai_analyze(request: Request, symbol: str = Query(..., max_length=20)):
    from ..ai.analyst import AnalystUnavailable

    st = _state(request)
    if not st.analyst.available:
        raise HTTPException(503, "The AI analyst is off. Add ANTHROPIC_API_KEY to .env to turn it on (see LATER.md).")
    opps = (st.precompute.get("opportunities") or {}).get("items", [])
    idea = next((o for o in opps if o["symbol"] == symbol and o["qualified"]), None)
    core = st.precompute.get("picks:quality_momentum") or {}
    factors = next((r for r in core.get("ranking", []) if r["symbol"] == symbol), None)
    try:
        res = await asyncio.to_thread(st.analyst.analyze, symbol, idea, factors)
    except AnalystUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    except DataUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    return ser.clean(res.to_dict())


@router.get("/quotes")
def quotes(request: Request, symbols: str = Query(..., max_length=8000), exchange: str = "binance"):
    # Discover asks for the whole universe at once (~520 stocks + crypto), batched server-side.
    syms = list(dict.fromkeys(s.strip() for s in symbols.split(",") if s.strip()))[:800]
    return ser.clean(_state(request).market.quotes(syms, exchange))


@router.get("/chart")
def chart(request: Request, provider: str = "auto", exchange: str = "binance", symbol: str = "AAPL",
          timeframe: str = "1d", limit: int = Query(500, ge=50, le=5000)):
    if provider == "auto":
        from ..data import provider_for

        provider = provider_for(symbol)
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
        "vwap": ser.line(__import__("tradebot.forecast", fromlist=["vwap_bands"]).vwap_bands(df)["vwap"])
                if timeframe.endswith(("m", "h")) and timeframe != "4h" else [],
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
    st = _state(request)
    s = _paper_summary(st)
    return ser.clean({"enabled": True, **s, "history": list(reversed(st.paper.history[-200:]))})


_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,14}(/[A-Z]{2,6})?$")


def _known_symbol(symbol: str) -> str:
    """Stocks, ETFs, indices (^GSPC) and crypto pairs (BTC/USDT) in Yahoo / exchange format."""
    sym = symbol.strip().upper()
    if not _SYMBOL.match(sym):
        raise HTTPException(422, f"Not a valid symbol: {symbol!r}")
    return sym


@router.get("/watchlists")
def watchlists(request: Request):
    return _state(request).store.watchlists()


@router.post("/watchlists")
def create_watchlist(request: Request, body: WatchlistBody):
    return _state(request).store.save_watchlist(body.name, [_known_symbol(s) for s in body.symbols])


@router.put("/watchlists/{id_}")
def update_watchlist(request: Request, id_: int, body: WatchlistBody):
    w = _state(request).store.save_watchlist(body.name, [_known_symbol(s) for s in body.symbols], id_)
    if w is None:
        raise HTTPException(404, "No such watchlist")
    return w


@router.delete("/watchlists/{id_}")
def delete_watchlist(request: Request, id_: int):
    if not _state(request).store.delete_watchlist(id_):
        raise HTTPException(404, "No such watchlist")
    return {"ok": True}


@router.get("/alerts")
def price_alerts(request: Request):
    from ..live.alerts import KINDS

    return {"kinds": KINDS, "alerts": _state(request).store.alerts()}


def _already_met(st, alert: dict) -> None:
    """Price levels must be crossed: refuse a level the price is already past (it would fire instantly)."""
    from ..live.alerts import due

    if alert["kind"] == "move":
        return
    q = st.market.quote(alert["symbol"])
    if q.get("price") is None:
        raise HTTPException(404, f"No price for {alert['symbol']}. Check the symbol (AAPL, ^GSPC, BTC/USDT).")
    if due({**alert, "active": True}, q):
        word = "above" if alert["kind"] == "above" else "below"
        raise HTTPException(422, f"{alert['symbol']} is already {word} {alert['value']:g} (now {q['price']:.2f}), "
                                 f"so the alert would fire right away. Choose a level it has not reached yet.")


@router.post("/alerts")
def create_alert(request: Request, body: AlertBody):
    st = _state(request)
    a = {"symbol": _known_symbol(body.symbol), "kind": body.kind, "value": body.value}
    _already_met(st, a)
    return st.store.add_alert(a["symbol"], body.kind, body.value, body.note)


@router.post("/alerts/{id_}/rearm")
def rearm_alert(request: Request, id_: int):
    st = _state(request)
    a = next((x for x in st.store.alerts() if x["id"] == id_), None)
    if a is None:
        raise HTTPException(404, "No such alert")
    _already_met(st, a)
    st.store.set_alert_active(id_, True)
    return {"ok": True}


@router.delete("/alerts/{id_}")
def delete_alert(request: Request, id_: int):
    if not _state(request).store.delete_alert(id_):
        raise HTTPException(404, "No such alert")
    return {"ok": True}


ws_router = APIRouter()


@ws_router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    app = websocket.app
    token = app.state.settings.api_token
    if token and not token_matches(token, websocket.query_params.get("token")):
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
