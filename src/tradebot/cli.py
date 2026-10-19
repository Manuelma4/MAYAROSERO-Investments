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

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
