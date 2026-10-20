"""Export a snapshot of real market data for the static preview build.

Usage:  python scripts/export_snapshot.py web/dist-static/data
Runs the real API in-process (real providers), saves the JSON the preview app reads.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from tradebot.api import create_app
from tradebot.api.settings import Settings
from tradebot.universe import CRYPTO, STOCKS

MARKETS = ["^GSPC", "^NDX", "^DJI", "^FCHI", "^GDAXI", "^STOXX50E", "BTC/USDT", "ETH/USDT", "SOL/USDT",
           "GC=F", "CL=F", "EURUSD=X"]
PRESETS = ["quality_momentum", "momentum", "trend_following", "low_volatility"]


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", s)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "charts").mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    app = create_app(Settings(db_path=tmp / "s.db", static_dir=None, api_token=None, cache_seconds=3600,
                              precompute=False))

    def save(name: str, data) -> None:
        (out / name).write_text(json.dumps(data, separators=(",", ":")))

    with TestClient(app) as c:
        def get(path, **params):
            r = c.get(path, params=params)
            r.raise_for_status()
            return r.json()

        def post(path, body):
            r = c.post(path, json=body)
            r.raise_for_status()
            return r.json()

        save("strategies.json", get("/api/strategies"))
        save("universe.json", get("/api/universe"))
        symbols = list(dict.fromkeys(MARKETS + [s.symbol for s in STOCKS] + [s for s, _ in CRYPTO]))
        quotes = get("/api/quotes", symbols=",".join(symbols))
        save("quotes.json", {q["symbol"]: q for q in quotes})
        print(f"quotes: {sum('price' in q for q in quotes)}/{len(quotes)}")

        ok = 0
        for s in symbols:
            try:
                tf = "4h" if "/" in s else "1d"
                save(f"charts/{safe(s)}_{tf}.json", get("/api/chart", symbol=s, timeframe=tf, limit=320))
                ok += 1
            except Exception as exc:
                print("chart failed", s, exc)
        print(f"charts: {ok}/{len(symbols)}")

        app.state.precompute.run_once()   # same precomputed results the live app serves
        if app.state.precompute.last_error:
            print("precompute warnings:", app.state.precompute.last_error)
        for p in PRESETS:
            save(f"picks_{p}.json", get("/api/picks/latest", preset=p))
        save("today.json", get("/api/today"))
        save("opportunities.json", post("/api/opportunities/scan", {}))
        (out / "forecasts").mkdir(exist_ok=True)
        fc_targets = {(s, 5) for s in symbols}
        for h in (1, 5, 21):
            pr = get("/api/predictions", horizon=h)
            save(f"predictions_{h}.json", pr)
            names = [i["symbol"] for i in pr["items"]]
            fc_targets |= {(s, h) for s in names[:20] + names[-20:]}
        n_fc = 0
        for s, h in sorted(fc_targets):
            try:
                save(f"forecasts/{safe(s)}_{h}.json", get("/api/forecast", symbol=s, horizon=h))
                n_fc += 1
            except Exception as exc:
                print("forecast failed", s, h, exc)
        print(f"predictions + {n_fc} forecasts: ok")
        for risk in ("cautious", "balanced", "bold"):
            save(f"portfolio_{risk}.json", post("/api/portfolio", {"amount": 10000, "currency": "EUR", "risk": risk}))
        print("picks + today: ok")
        save("backtest.json", post("/api/backtest", {"provider": "yahoo", "symbol": "^GSPC", "timeframe": "1d",
                                                      "start": "2015-01-01", "strategy": "dow_pullback"}))
        save("predict.json", post("/api/predict", {"provider": "yahoo", "symbols": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"],
                                                    "timeframe": "1d", "start": "2012-01-01", "horizon": 5}))
        print("backtest + predict: ok")
        scan = post("/api/live/scan", {})
        save("events.json", get("/api/events"))
        status = get("/api/live/status")
        status["running"] = False
        save("status.json", status)
        save("paper.json", get("/api/paper"))
        print(f"live scan events: {len(scan['events'])}")
    save("meta.json", {"as_of": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "web/dist-static/data"))
