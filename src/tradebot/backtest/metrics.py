from __future__ import annotations

import numpy as np
import pandas as pd


def _periods_per_year(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 252.0
    step = pd.Series(index).diff().median()
    days = step / pd.Timedelta(days=1)
    if days >= 1:
        # Daily stock data skips weekends; crypto doesn't.
        weekend = any(ts.weekday() >= 5 for ts in index[:50])
        return (365.0 if weekend else 252.0) / days
    return 365.0 / days


def summarize(res) -> dict:
    eq = res.equity
    trades = res.trades
    start, end = eq.iloc[0], eq.iloc[-1]
    initial = res.config.initial_capital
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    rets = eq.pct_change().dropna()
    ppy = _periods_per_year(eq.index)
    dd = eq / eq.cummax() - 1

    pnl = np.array([t.pnl for t in trades])
    r = np.array([t.r_multiple for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    close = res.data["close"]

    return {
        "start": str(eq.index[0]), "end": str(eq.index[-1]),
        "final_equity": round(float(end), 2),
        "total_return_%": round((end / initial - 1) * 100, 2),
        "buy_hold_return_%": round((close.iloc[-1] / close.iloc[0] - 1) * 100, 2),
        "cagr_%": round(((end / initial) ** (1 / years) - 1) * 100, 2) if end > 0 else -100.0,
        "max_drawdown_%": round(float(dd.min()) * 100, 2),
        "sharpe": round(float(rets.mean() / rets.std() * np.sqrt(ppy)), 2) if rets.std() > 0 else 0.0,
        "trades": len(trades),
        "win_rate_%": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "profit_factor": round(wins.sum() / -losses.sum(), 2) if losses.sum() < 0 else float("inf") if len(wins) else 0.0,
        "expectancy_R": round(float(r.mean()), 3) if len(r) else 0.0,
        "avg_bars_held": round(float(np.mean([t.bars_held for t in trades])), 1) if trades else 0.0,
    }
