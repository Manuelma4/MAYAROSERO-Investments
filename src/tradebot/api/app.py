"""FastAPI application factory.

Run locally:   tradebot serve --reload      (or: uvicorn tradebot.api.app:create_app --factory)
Production:    see Dockerfile (serves the built React app from web/dist).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .engine import Broadcaster, LiveEngine
from .market import MarketData, ProviderFactory
from .precompute import Precomputer
from .routes import router, ws_router
from .settings import Settings
from .store import EventStore

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, provider_factory: ProviderFactory | None = None,
               config: dict | None = None, scanner_factory=None) -> FastAPI:
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
    app.state.settings = settings
    app.state.market = MarketData(provider_factory, ttl=settings.cache_seconds)
    app.state.store = EventStore(settings.db_path)
    app.state.precompute = Precomputer(app.state.market, interval=settings.precompute_seconds)
    app.state.broadcaster = Broadcaster()
    kw = {"scanner_factory": scanner_factory} if scanner_factory else {}
    app.state.engine = LiveEngine(config, app.state.store, app.state.broadcaster, **kw)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def auth(request: Request, call_next):
        token = settings.api_token
        if (token and request.url.path.startswith("/api/") and request.url.path != "/api/health"
                and request.headers.get("authorization") != f"Bearer {token}"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    app.include_router(router)
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
