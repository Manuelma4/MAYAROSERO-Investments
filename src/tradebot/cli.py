"""Command line interface.

Examples:
  tradebot strategies
  tradebot analyze  --provider yahoo --symbol AAPL --timeframe 1d
  tradebot backtest --provider yahoo --symbol ^GSPC --timeframe 1d --strategy dow_pullback --start 2010-01-01
  tradebot backtest --provider ccxt --symbol BTC/USDT --timeframe 4h --strategy ema_cross_rsi --start 2021-01-01
  tradebot predict  --provider yahoo --symbol AAPL,MSFT,NVDA --timeframe 1d --horizon 5
  tradebot movers   --config config/config.yaml        # one pass of the surge/crash detector
  tradebot scan     --config config/config.yaml        # one pass over the watchlist
  tradebot live     --config config/config.yaml        # loop forever, real-time alerts
  tradebot serve    --port 8000                        # web platform (API + UI)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
import yaml


def _load_df(args, symbol: str | None = None) -> pd.DataFrame:
    if args.csv:
        from .data.providers import normalize

        return normalize(pd.read_csv(args.csv, index_col=0, parse_dates=True))
    from .data import get_provider

    prov = get_provider(args.provider, exchange=args.exchange)
    return prov.history(symbol or args.symbol, args.timeframe, start=args.start, end=args.end,
                        limit=args.limit)


def _data_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", default="yahoo", help="yahoo (stocks/indices) or ccxt (crypto)")
    p.add_argument("--exchange", default="binance", help="ccxt exchange id")
    p.add_argument("--symbol", default="AAPL")
    p.add_argument("--timeframe", default="1d", help="1m 5m 15m 1h 4h 1d 1wk")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--limit", type=int)
    p.add_argument("--csv", help="load OHLCV from a CSV file instead of a provider")


def cmd_strategies(_args) -> None:
    from .strategies import REGISTRY

    for name, cls in REGISTRY.items():
        print(f"{name:18s} {cls.description}\n{'':18s} params: {cls.defaults}")


def cmd_analyze(args) -> None:
    from .report import market_report

    print(market_report(_load_df(args), args.symbol, args.timeframe))


def cmd_backtest(args) -> None:
    from .backtest import BacktestConfig, run_backtest
    from .strategies import get_strategy

    df = _load_df(args)
    params = json.loads(args.params) if args.params else {}
    cfg = BacktestConfig(initial_capital=args.capital, risk_per_trade=args.risk,
                         fee=args.fee, slippage=args.slippage, allow_short=not args.long_only)
    res = run_backtest(df, get_strategy(args.strategy, **params), cfg)
    print(f"\n{args.strategy} on {args.symbol} {args.timeframe} ({len(df)} bars)")
    for k, v in res.stats.items():
        print(f"  {k:20s} {v}")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        res.trades_frame().to_csv(out / "trades.csv", index=False)
        res.equity.to_csv(out / "equity.csv")
        print(f"\nSaved trades and equity curve to {out}/")


def cmd_predict(args) -> None:
    from .ml import Predictor

    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    frames = {s: _load_df(args, s) for s in symbols}
    pred = Predictor(horizon=args.horizon, threshold_atr=args.threshold, min_confidence=args.min_confidence)
    print(f"Walk-forward validation on {', '.join(symbols)} ({args.timeframe}, horizon {args.horizon} bars)...")
    val = pred.walk_forward(frames)
    pred.fit(frames)
    print()
    for sym, df in frames.items():
        print(pred.predict_latest(sym, df, val), end="\n\n")
    if args.save:
        pred.save(args.save)
        print(f"Model saved to {args.save}")


def cmd_movers(args) -> None:
    from .live.movers import MoversScanner, format_move

    cfg = _load_config(args.config).get("movers", {})
    sc = MoversScanner.from_config(cfg)
    found = sc.run_once()
    for sym, m in found:
        print(format_move(sym, m, sc.settings))
    print(f"{len(found)} abnormal move(s) on the last closed bars.")


def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def cmd_scan(args) -> None:
    from .live import Scanner

    alerts = Scanner.from_config(_load_config(args.config)).run_once()
    print(f"{len(alerts)} signal(s) on the last closed bars.")


def cmd_live(args) -> None:
    from .live import Scanner

    cfg = _load_config(args.config)
    Scanner.from_config(cfg).run_forever(cfg.get("poll_seconds", 60))


def repo_root() -> Path | None:
    """The checkout this package runs from (the folder with pyproject.toml), or None if installed elsewhere."""
    for d in Path(__file__).resolve().parents:
        if (d / "pyproject.toml").is_file() and (d / "src" / "tradebot").is_dir():
            return d
    return None


def default_env_file() -> Path | None:
    """TRADEBOT_ENV_FILE if set, else <repo root>/.env. Never the current directory (it depends on where you start)."""
    import os

    if os.environ.get("TRADEBOT_ENV_FILE"):
        return Path(os.environ["TRADEBOT_ENV_FILE"]).expanduser()
    root = repo_root()
    return root / ".env" if root else None


def _env_value(raw: str) -> str:
    """Value part of KEY=VALUE: quoted values are kept as written (a # inside quotes is not a comment);
    unquoted values lose a trailing `  # comment`."""
    import re

    val = raw.strip()
    if val[:1] in ("'", '"'):
        end = val.find(val[0], 1)
        if end > 0:
            return val[1:end]
    if val.startswith("#"):
        return ""
    return re.split(r"\s+#", val, maxsplit=1)[0].strip()


def load_dotenv(path: str | Path | None = None) -> int:
    """Read KEY=VALUE lines from .env into the environment (variables already set win). Returns the count.

    ``path`` None: see default_env_file()."""
    import os

    f = Path(path).expanduser() if path is not None else default_env_file()
    if f is None or not f.is_file():
        return 0
    n = 0
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if key and key not in os.environ:
            os.environ[key] = _env_value(val)
            n += 1
    return n


def trading_mode_origin(env_file: Path | None, shell_keys: set[str]) -> str:
    """Plain-English line for the startup log: the trading mode and where it was set."""
    import os

    from .trading.brokers import trading_mode

    mode = trading_mode()
    if "TRADING_MODE" in shell_keys:
        where = "the shell environment"
    elif os.environ.get("TRADING_MODE") is not None:
        where = str(env_file)
    else:
        where = "not set anywhere, so paper"
    return f"TRADING_MODE={mode.upper()} ({where}); BROKER={(os.environ.get('BROKER') or 'paper').strip().lower()}"


def cmd_serve(args) -> None:
    import os

    import uvicorn

    log = logging.getLogger("tradebot")
    shell_keys = set(os.environ)
    env_file = Path(args.env_file).expanduser().resolve() if args.env_file else default_env_file()
    if args.env_file and not env_file.is_file():
        raise SystemExit(f"--env-file {env_file} does not exist.")
    n = load_dotenv(env_file) if env_file else 0
    log.info(".env: %s (%d variable(s) loaded)", env_file if env_file and env_file.is_file() else "none found", n)
    log.info(trading_mode_origin(env_file, shell_keys))
    os.environ.setdefault("TRADEBOT_CONFIG", args.config)
    uvicorn.run("tradebot.api.app:create_app", factory=True, host=args.host, port=args.port,
                reload=args.reload)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="tradebot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("strategies", help="list available strategies").set_defaults(fn=cmd_strategies)

    p = sub.add_parser("analyze", help="market structure snapshot")
    _data_args(p)
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("backtest", help="backtest a strategy on history")
    _data_args(p)
    p.add_argument("--strategy", default="ema_cross_rsi")
    p.add_argument("--params", help='JSON overrides, e.g. \'{"fast": 10, "rr": 3}\'')
    p.add_argument("--capital", type=float, default=10_000)
    p.add_argument("--risk", type=float, default=0.01, help="fraction of equity risked per trade")
    p.add_argument("--fee", type=float, default=0.001)
    p.add_argument("--slippage", type=float, default=0.0005)
    p.add_argument("--long-only", action="store_true")
    p.add_argument("--out", help="directory to save trades.csv / equity.csv")
    p.set_defaults(fn=cmd_backtest)

    p = sub.add_parser("predict", help="ML prediction of the next move, with walk-forward validation")
    _data_args(p)
    p.add_argument("--horizon", type=int, default=5, help="bars ahead to predict")
    p.add_argument("--threshold", type=float, default=0.5, help="move size (x ATR) that counts as BUY/SELL")
    p.add_argument("--min-confidence", type=float, default=0.45)
    p.add_argument("--save", help="path to save the trained model (.joblib)")
    p.set_defaults(fn=cmd_predict)

    for name, fn, help_ in (("movers", cmd_movers, "one pass of the surge / crash detector"),
                            ("scan", cmd_scan, "one pass over the watchlist"),
                            ("live", cmd_live, "run the real-time scanner forever")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--config", default="config/config.yaml")
        p.set_defaults(fn=fn)

    p = sub.add_parser("serve", help="run the web platform (API + UI)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--config", default="config/config.yaml")
    p.add_argument("--reload", action="store_true")
    p.add_argument("--env-file", help="path to the .env file (default: TRADEBOT_ENV_FILE, else .env in the repo root)")
    p.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
