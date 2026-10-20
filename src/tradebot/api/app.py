"""FastAPI application factory.

Run locally:   tradebot serve --reload      (or: uvicorn tradebot.api.app:create_app --factory)
Production:    see Dockerfile (serves the built React app from web/dist).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .engine import Broadcaster, LiveEngine
from .market import MarketData, ProviderFactory
from .precompute import Precomputer
from .routes import router, ws_router
from .settings import Settings, token_matches
from .store import EventStore

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, provider_factory: ProviderFactory | None = None,
               config: dict | None = None, scanner_factory=None, analyst_client=None,
               broker_factory=None) -> FastAPI:
    settings = settings or Settings()
    config = config if config is not None else settings.load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.broadcaster.bind(asyncio.get_running_loop())
        if settings.autostart_live:
            app.state.engine.start()
        if settings.precompute:
            app.state.precompute.start()
        yield
        app.state.precompute.stop()
        app.state.engine.stop()

    app = FastAPI(title="tradebot", version="0.2.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError):
        # Echoing the rejected input back can itself fail (e.g. inf / NaN are not valid JSON).
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", "invalid"), "type": e.get("type")} for e in exc.errors()]})
    app.state.settings = settings
    app.state.market = MarketData(provider_factory, ttl=settings.cache_seconds)
    app.state.store = EventStore(settings.db_path)
    from ..live import PaperBroker

    paper_cfg = config.get("paper_trading", {})
    app.state.paper = PaperBroker(settings.db_path.parent / "paper_state.json",
                                  capital=paper_cfg.get("capital", 10_000))
    import threading

    app.state.paper_lock = threading.Lock()   # one order / exit at a time
    from .orders import init_trading, manage_broker_exits

    init_trading(app, settings.db_path.parent, broker_factory)   # BROKER / TRADING_MODE from the environment

    def on_opportunity(o: dict) -> None:
        ev = app.state.store.add("opportunity", o["symbol"], {k: v for k, v in o.items() if k != "symbol"})
        app.state.broadcaster.publish(ev)
        arrow = "RISING" if o["direction"] == "long" else "FALLING"
        text = (f"[INVEST NOW] {o['symbol']} {arrow} {o['change_pct']:+.1f}% on {o['rel_volume']:.1f}x volume\n"
                f"  {o.get('headline') or ''}\n  entry {o['entry']:.2f}  stop {o['stop']:.2f}  target {o['target']:.2f}")
        try:
            for n in app.state.engine._ensure_scanner().notifiers:
                n.send(text)
        except Exception as exc:
            log.warning("notify failed: %s", exc)

    def on_alert(a: dict, q: dict) -> None:
        from ..live.alerts import message

        ev = app.state.store.add("alert", a["symbol"], {"kind": a["kind"], "value": a["value"], "note": a["note"],
                                                         "alert_id": a["id"], "price": q.get("price"),
                                                         "change_pct": q.get("change_pct")})
        app.state.broadcaster.publish(ev)
        try:
            for n in app.state.engine._ensure_scanner().notifiers:
                n.send(message(a, q))
        except Exception as exc:
            log.warning("notify failed: %s", exc)

    def on_picks_change(ev: dict) -> None:
        app.state.broadcaster.publish(ev)
        text = (f"[PICKS UPDATE] Beat-the-S&P review of {str(ev['date'])[:10]}\n"
                f"  BUY:  {', '.join(ev['buy']) or 'nothing new'}\n"
                f"  SELL: {', '.join(ev['sell']) or 'nothing'}\n"
                f"  KEEP: {', '.join(ev['keep']) or '-'}")
        try:
            for n in app.state.engine._ensure_scanner().notifiers:
                n.send(text)
        except Exception as exc:
            log.warning("notify failed: %s", exc)

    from ..ai.analyst import AIAnalyst
    from ..live.news import NewsSource

    app.state.analyst = AIAnalyst(app.state.market, NewsSource(), client=analyst_client)
    app.state.precompute = Precomputer(app.state.market, interval=settings.precompute_seconds,
                                       on_opportunity=on_opportunity, paper=app.state.paper,
                                       paper_lock=app.state.paper_lock, store=app.state.store,
                                       on_alert=on_alert, on_picks_change=on_picks_change,
                                       broker_exits=lambda: manage_broker_exits(app.state))
    app.state.broadcaster = Broadcaster()
    kw = {"scanner_factory": scanner_factory} if scanner_factory else {}
    app.state.engine = LiveEngine(config, app.state.store, app.state.broadcaster, **kw)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def auth(request: Request, call_next):
        token = settings.api_token
        if (token and request.url.path.startswith("/api/") and request.url.path != "/api/health"
                and not token_matches(f"Bearer {token}", request.headers.get("authorization"))):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    from .orders import router as orders_router

    app.include_router(router)
    app.include_router(orders_router)
    app.include_router(ws_router)

    static = settings.static_dir
    if static and static.is_dir() and (static / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        root = static.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith(("api/", "ws/")):
                raise HTTPException(404)
            f = (root / path).resolve()
            if path and f.is_file() and f.is_relative_to(root):
                return FileResponse(f)
            return FileResponse(root / "index.html")

    return app
