"""How risky is a portfolio plan? An honest, forward-looking risk view next to simply holding the S&P 500.

Pure functions (prices in, numbers out), tested offline. Inputs are daily closes (dividend-adjusted) of the
plan's lasting holdings and SPY, the weights of each holding as a share of the WHOLE amount (the rest is
cash), and optionally the EUR/USD rate so a euro investor sees the risk in euros (currency risk included).

Method choices (see the docstrings below for details):
- History: the last ~3 years of daily returns (LOOKBACK = 756 trading days) of TODAY's holdings with TODAY's
  weights, rebalanced daily. It answers "how would this exact mix have moved", which is indicative only: the
  plan is rebuilt every month, and today's picks were partly chosen because they did well recently.
- Live ideas (the satellite part) are NOT simulated: they are held for days, not months, and each one has a
  stop-loss sized to lose about 1% of the portfolio. Their share counts as cash in the simulation, and their
  worst case is reported separately as "if every live idea hits its stop" (gaps through a stop can be worse).
  The saved target already keeps live ideas in one "cash and live ideas" bucket (live/drift.py), same choice.
- 1-month loss: filtered historical simulation (FHS) on the PORTFOLIO's daily return series, the same method
  as forecast.monte_carlo: EWMA volatility (RiskMetrics lambda 0.94) standardizes each past day's return,
  scenarios redraw those standardized days and rescale them by today's simulated volatility. Because the
  portfolio's daily return already mixes all holdings on the same real day, correlations between holdings
  (including how they rise together in a crash) are kept exactly as they were, without estimating a
  correlation matrix; the EWMA step makes the answer reflect today's calm or stormy market (a plain block
  bootstrap would ignore the current regime). Plan and SPY redraw the SAME past days in every scenario, so
  the side-by-side numbers come from the same imagined months. Drift is zero: this describes risk, not a bet.
- Diversification: average pairwise correlation; "independent bets" = the diversification ratio squared
  (Choueifaty, Froidure & Reynier 2013): (sum w_i sigma_i / sigma_p)^2. It equals N for N equal, equally
  volatile, uncorrelated holdings and 1 when everything moves in lockstep. Risk contributions use the
  standard Euler split: w_i (Sigma w)_i / (w' Sigma w), which sum to 100% of the volatility.
- Beta to the S&P 500 and yearly volatility are measured on the same 3-year window.

No future data: every number uses only rows up to `as_of` (default: the last row); see the truncation test.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .forecast import LAMBDA, ewma_vol

LOOKBACK = 756          # ~3 years of trading days
HORIZON = 21            # ~1 month of trading days
N_PATHS = 10_000
MIN_DAYS = 120          # below this, the numbers would be noise
SPY = "SPY"
INDEX_SECTOR = "S&P 500 index"
BINS = np.arange(-30, 32, 2.0)   # histogram edges in % for the 1-month outcome chart


# ---------------------------------------------------------------- inputs

def daily_returns(closes: pd.DataFrame, symbols: list[str], fx: pd.Series | None = None,
                  as_of=None, lookback: int = LOOKBACK) -> tuple[pd.DataFrame, list[str]]:
    """Daily simple returns of `symbols` + SPY over the last `lookback` days up to `as_of`.

    fx: USD per 1 unit of the investor's currency (EURUSD=X). When given, returns are converted into that
    currency: (1 + r_usd) / (1 + r_fx) - 1. Missing history (recent listing, data gap) is filled with
    SPY's return that day and reported in the notes, so a gap never silently counts as "no move".
    """
    if SPY not in closes.columns:
        raise ValueError("SPY prices are needed as the yardstick")
    c = closes.sort_index()
    if as_of is not None:
        c = c.loc[:pd.Timestamp(as_of)]
    cols = list(dict.fromkeys([s for s in symbols if s != SPY] + [SPY]))
    c = c.reindex(columns=cols)
    r = c.pct_change(fill_method=None).iloc[1:]
    r = r[r[SPY].notna()].iloc[-lookback:]
    if fx is not None and len(fx.dropna()):
        f = fx.sort_index()
        if as_of is not None:
            f = f.loc[:pd.Timestamp(as_of)]
        # forward-fill only (yesterday's rate on a forex holiday), never a later rate
        f = f.reindex(f.index.union(c.index)).ffill().reindex(c.index)
        fr = f.pct_change(fill_method=None).reindex(r.index).fillna(0.0)
        r = (1 + r).div(1 + fr, axis=0) - 1
    notes = []
    for s in cols:
        if s == SPY:
            continue
        miss = int(r[s].isna().sum())
        if miss:
            r[s] = r[s].fillna(r[SPY])
            notes.append(f"{s}: {miss} of {len(r)} days had no price; the S&P 500's move was used instead.")
    return r, notes


# ---------------------------------------------------------------- Monte Carlo

def simulate_month(series: dict[str, pd.Series], horizon: int = HORIZON, n_paths: int = N_PATHS,
                   seed: int | None = 7) -> dict[str, np.ndarray]:
    """Filtered historical simulation of the total return over `horizon` days for each series.

    All series share the same dates and the same drawn days, so scenarios are joint (a bad day for the
    plan is the same bad day for SPY). Returns {name: array of n_paths simple returns}.
    """
    names = list(series)
    logs = {k: np.log1p(v.to_numpy(dtype=float)) for k, v in series.items()}
    n = len(next(iter(logs.values())))
    if n < MIN_DAYS:
        raise ValueError(f"Need at least {MIN_DAYS} days of history, got {n}")
    z, var0 = {}, {}
    for k in names:
        r = logs[k]
        sig = ewma_vol(r)
        zz = r / sig
        sd = zz.std()
        z[k] = (zz - zz.mean()) / sd if sd > 0 else np.zeros_like(zz)
        var0[k] = LAMBDA * sig[-1] ** 2 + (1 - LAMBDA) * r[-1] ** 2
    rng = np.random.default_rng(seed)
    days = rng.integers(0, n, size=(horizon, n_paths))
    out = {}
    for k in names:
        var = np.full(n_paths, var0[k])
        total = np.zeros(n_paths)
        for t in range(horizon):
            shock = z[k][days[t]] * np.sqrt(var)
            total += -0.5 * var + shock          # zero drift: describes risk, not a bet
            var = LAMBDA * var + (1 - LAMBDA) * shock ** 2
        out[k] = np.expm1(total)
    return out


def loss_stats(ret: np.ndarray, amount: float) -> dict:
    """Bad month (1 in 20) and very bad month (1 in 100) losses, as % and money (positive = loss)."""
    q5, q1 = np.percentile(ret, [5, 1])
    tail = ret[ret <= q5]
    return {
        "loss_95_%": float(-q5 * 100), "loss_95": float(-q5 * amount),
        "loss_99_%": float(-q1 * 100), "loss_99": float(-q1 * amount),
        "avg_worst_5_%": float(-tail.mean() * 100) if len(tail) else None,   # expected shortfall (95%)
        "p_loss_10": float((ret <= -0.10).mean()),
        "p_gain": float((ret > 0).mean()),
        "median_%": float(np.median(ret) * 100),
    }


def histogram(ret: np.ndarray) -> list[float]:
    """Share of scenarios in each 2-point bin of BINS (the ends collect everything beyond)."""
    x = np.clip(ret * 100, BINS[0] + 1e-9, BINS[-1] - 1e-9)
    h, _ = np.histogram(x, bins=BINS)
    return [float(v) for v in h / max(len(ret), 1)]


# ---------------------------------------------------------------- history

def worst_drop(r: pd.Series) -> dict:
    """Largest peak-to-trough fall of a daily return series, and how long it took to get back to the peak."""
    eq = (1 + r.fillna(0.0)).cumprod()
    eq = pd.concat([pd.Series([1.0], index=[r.index[0] - pd.Timedelta(days=1)]), eq])
    dd = eq / eq.cummax() - 1
    trough = dd.idxmin()
    peak = eq.loc[:trough].idxmax()
    after = eq.loc[trough:]
    rec = after[after >= eq.loc[peak]]
    recovered = rec.index[0] if len(rec) else None
    pos = eq.index.get_loc
    return {
        "drop_%": float(dd.min() * 100),
        "peak": peak, "trough": trough, "recovered": recovered,
        "fall_days": int(pos(trough) - pos(peak)),
        "recovery_days": int(pos(recovered) - pos(trough)) if recovered is not None else None,
        "underwater_days": int((pos(recovered) if recovered is not None else len(eq) - 1) - pos(peak)),
    }


# ---------------------------------------------------------------- diversification

def diversification(rets: pd.DataFrame, weights: dict[str, float], sectors: dict[str, str | None]) -> dict:
    """Correlation, independent bets, sector concentration and risk contributions of the risky holdings."""
    syms = [s for s in weights if weights[s] > 0 and s in rets.columns]
    w = np.array([weights[s] for s in syms])
    cov = rets[syms].cov().to_numpy() * 252
    vol = np.sqrt(np.clip(np.diag(cov), 0, None))
    port_var = float(w @ cov @ w)
    out: dict = {"holdings": len(syms)}
    if len(syms) >= 2:
        corr = rets[syms].corr().to_numpy()
        iu = np.triu_indices(len(syms), 1)
        out["avg_correlation"] = float(np.nanmean(corr[iu]))
    else:
        out["avg_correlation"] = None
    wn = w / w.sum() if w.sum() > 0 else w
    out["equal_size_count"] = float(1 / (wn ** 2).sum()) if len(w) else 0.0
    out["independent_bets"] = float((w @ vol) ** 2 / port_var) if port_var > 0 else None
    rc = w * (cov @ w) / port_var if port_var > 0 else np.zeros_like(w)
    contrib = sorted(({"symbol": s, "weight_%": float(weights[s] * 100), "risk_share_%": float(c * 100)}
                      for s, c in zip(syms, rc)), key=lambda d: -d["risk_share_%"])
    out["contributors"] = contrib
    out["top_contributor"] = contrib[0] if contrib else None
    sec_w: dict[str, float] = {}
    sec_r: dict[str, float] = {}
    for s, c in zip(syms, rc):
        k = sectors.get(s) or (INDEX_SECTOR if s == SPY else "Other")
        sec_w[k] = sec_w.get(k, 0.0) + weights[s] * 100
        sec_r[k] = sec_r.get(k, 0.0) + float(c * 100)
    out["sectors"] = sorted(({"sector": k, "weight_%": v, "risk_share_%": sec_r[k]} for k, v in sec_w.items()),
                            key=lambda d: -d["risk_share_%"])
    stock_secs = [d for d in out["sectors"] if d["sector"] != INDEX_SECTOR]
    out["top_sector"] = max(stock_secs, key=lambda d: d["weight_%"]) if stock_secs else None
    return out


def beta(r: pd.Series, m: pd.Series) -> float | None:
    c = np.cov(r.to_numpy(), m.to_numpy())
    return float(c[0, 1] / c[1, 1]) if c[1, 1] > 0 else None


# ---------------------------------------------------------------- the risk view

def _money(x: float, ccy: str) -> str:
    sym = {"EUR": "€", "USD": "$"}.get(ccy, "")
    return f"{sym}{abs(x):,.0f}" if sym else f"{abs(x):,.0f} {ccy}"


def _duration(trading_days: int) -> str:
    if trading_days < 30:
        return f"{trading_days} trading day{'s' if trading_days != 1 else ''}"
    months = round(trading_days / 21)
    return f"about {months} month{'s' if months != 1 else ''}"


def risk_view(closes: pd.DataFrame, weights: dict[str, float], amount: float, currency: str = "USD",
              sectors: dict[str, str | None] | None = None, fx: pd.Series | None = None,
              ideas_share: float = 0.0, ideas_stop_loss: float | None = None, as_of=None,
              lookback: int = LOOKBACK, horizon: int = HORIZON, n_paths: int = N_PATHS, seed: int | None = 7) -> dict:
    """The full risk block. `weights`: share of the whole amount per symbol (sum <= 1, rest is cash/ideas).
    `ideas_stop_loss`: money lost if every live idea hits its stop (plan currency), when known."""
    sectors = sectors or {}
    weights = {s: float(w) for s, w in weights.items() if w and w > 0}
    if not weights:
        return {"status": "empty", "message": "Nothing is invested in this plan, so there is no market risk."}
    rets, notes = daily_returns(closes, list(weights), fx=fx, as_of=as_of, lookback=lookback)
    if len(rets) < MIN_DAYS:
        return {"status": "short", "message": "Not enough price history yet to measure this plan's risk."}
    w = pd.Series({s: weights[s] for s in weights})
    port = rets[w.index].mul(w).sum(axis=1)          # cash (and live ideas) earn 0
    spy = rets[SPY]
    invested = float(w.sum())

    sims = simulate_month({"plan": port, "spy": spy}, horizon=horizon, n_paths=n_paths, seed=seed)
    plan_l, spy_l = loss_stats(sims["plan"], amount), loss_stats(sims["spy"], amount)
    div = diversification(rets, weights, sectors)
    b = beta(port, spy)
    vol = float(port.std() * math.sqrt(252) * 100)
    spy_vol = float(spy.std() * math.sqrt(252) * 100)
    now_vol = float(ewma_vol(np.log1p(port.to_numpy()))[-1] * math.sqrt(252) * 100)
    spy_now_vol = float(ewma_vol(np.log1p(spy.to_numpy()))[-1] * math.sqrt(252) * 100)
    dd, spy_dd = worst_drop(port), worst_drop(spy)

    ccy = currency
    years = len(rets) / 252
    s = [f"In a bad month (1 in 20) this plan could lose about {_money(plan_l['loss_95'], ccy)} "
         f"({plan_l['loss_95_%']:.0f}%); simply holding the S&P 500 with the same {_money(amount, ccy)} could lose "
         f"about {_money(spy_l['loss_95'], ccy)} ({spy_l['loss_95_%']:.0f}%).",
         f"In a very bad month (1 in 100) it could lose about {_money(plan_l['loss_99'], ccy)} "
         f"({plan_l['loss_99_%']:.0f}%), against {_money(spy_l['loss_99'], ccy)} ({spy_l['loss_99_%']:.0f}%) "
         "for the S&P 500."]
    rec = (f"and got back to that peak {_duration(dd['recovery_days'])} later" if dd["recovered"] is not None
           else "and had not got back to that peak yet")
    s.append(f"Over the last {years:.0f} years, today's holdings would have fallen at most {abs(dd['drop_%']):.0f}% "
             f"from a peak {rec} (the S&P 500 fell at most {abs(spy_dd['drop_%']):.0f}%).")
    if b is not None:
        s.append(f"It tends to move about {b:.1f}% when the S&P 500 moves 1%, and swings about {vol:.0f}% a year "
                 f"(S&P 500: {spy_vol:.0f}%).")
    if div.get("independent_bets") is not None and div["holdings"] >= 2:
        s.append(f"Its {div['holdings']} holdings act like about {div['independent_bets']:.1f} independent bets"
                 + (f"; {div['top_contributor']['symbol']} adds the most risk "
                    f"({div['top_contributor']['risk_share_%']:.0f}% of it)." if div["top_contributor"] else "."))
    if ideas_share > 0.0005:
        tail = (f" If every live idea hit its stop-loss you would lose about {_money(ideas_stop_loss, ccy)} more."
                if ideas_stop_loss else " Each live idea is sized to lose about 1% of the portfolio at its stop-loss.")
        s.append(f"Live ideas ({ideas_share * 100:.0f}%) are short trades with stop-losses, so the simulation "
                 f"counts them as cash.{tail}")

    def dd_out(d):
        return {k: (v.date().isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in d.items()}

    return {
        "status": "ok", "currency": ccy, "amount": amount, "as_of": rets.index[-1].date().isoformat(),
        "start": rets.index[0].date().isoformat(), "days": len(rets), "horizon_days": horizon, "paths": n_paths,
        "invested_share": invested, "ideas_share": ideas_share, "ideas_stop_loss": ideas_stop_loss,
        "cash_share": max(0.0, 1.0 - invested - ideas_share),
        "month": {"plan": plan_l, "spy": spy_l},
        "histogram": {"edges_%": [float(x) for x in BINS], "plan": histogram(sims["plan"]), "spy": histogram(sims["spy"])},
        "worst_drop": {"plan": dd_out(dd), "spy": dd_out(spy_dd)},
        "volatility_%": vol, "spy_volatility_%": spy_vol, "volatility_now_%": now_vol, "spy_volatility_now_%": spy_now_vol,
        "beta": b, "diversification": div, "summary": s,
        "method": "Filtered historical simulation (EWMA volatility, lambda 0.94) of the plan's daily returns with "
                  f"today's weights over {len(rets)} days, {n_paths:,} one-month scenarios, zero drift.",
        "notes": notes,
        "currency_risk": fx is not None,
    }
