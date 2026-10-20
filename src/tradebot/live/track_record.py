"""Live (forward) track record: what the engine recommended each day, and what happened next.

No backtest and no hindsight:
- a picks snapshot is recorded once per trading day, only after that day's US close is known, and it
  counts from the first market open AFTER it was recorded (so a late recording is never back-dated);
- the portfolio is bought at that open, held with drifting weights, and fully rebalanced to equal weight
  (at the next open) only when the list of picks changes; 10 bps per unit of turnover is charged;
- SPY (dividends included via adjusted prices) is bought at the same first open and held, cost-free;
- an Invest-now idea is filled at the first daily open after it was issued and recorded, then exits at
  its stop (checked first on every bar, gaps filled at the open), its target, or the close of its
  5th trading day. Results are in R: the gain or loss in units of the planned risk (entry to stop).

All functions are pure (data in, numbers out) so they can be tested offline and for look-ahead.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

NY = "America/New_York"
CLOSE_BUFFER = timedelta(minutes=20)   # free US quotes are ~15 min delayed


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def session_open(day: str | date) -> pd.Timestamp:
    """09:30 New York time on a session date, in UTC (daylight saving included)."""
    d = pd.Timestamp(str(day)[:10]).date()
    return pd.Timestamp(datetime.combine(d, time(9, 30))).tz_localize(NY).tz_convert("UTC")


def session_close_known(day: str | date, now) -> bool:
    """True once the 16:00 New York close of `day` is final (plus a delay buffer)."""
    d = pd.Timestamp(str(day)[:10]).date()
    close = pd.Timestamp(datetime.combine(d, time(16, 0))).tz_localize(NY).tz_convert("UTC")
    return _utc(now) >= close + CLOSE_BUFFER


def _by_date(df: pd.DataFrame) -> pd.DataFrame:
    """Daily bars re-indexed by session date 'YYYY-MM-DD' (Yahoo stamps them at midnight local/UTC)."""
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    out = df.copy()
    out.index = idx.strftime("%Y-%m-%d")
    return out[~out.index.duplicated(keep="last")]


def effective_day(snapshot: dict) -> pd.Timestamp:
    """The earliest moment the snapshot could be acted on: after its session's close and after it was
    actually recorded."""
    d = pd.Timestamp(str(snapshot["date"])[:10]).date()
    close = pd.Timestamp(datetime.combine(d, time(16, 0))).tz_localize(NY).tz_convert("UTC")
    rec = snapshot.get("recorded_at")
    return max(close, _utc(rec)) if rec else close


# ---- picks portfolio ------------------------------------------------------------------------
def picks_forward(snapshots: list[dict], bars: dict[str, pd.DataFrame], spy: pd.DataFrame,
                  cost_bps: float = 10.0) -> dict:
    """Forward performance of the recorded picks vs SPY.

    snapshots: [{"date": "YYYY-MM-DD", "recorded_at": iso, "weights": {symbol: weight}}] (any order).
    bars: daily OHLC per symbol; spy: daily OHLC of SPY (its sessions define the calendar).
    A day t uses the latest snapshot that became known before t's 09:30 open.
    """
    snaps = sorted(snapshots, key=lambda s: str(s["date"]))
    empty = {"days": 0, "first_trade": None, "return_%": None, "spy_%": None, "excess_%": None,
             "max_drawdown_%": None, "spy_max_drawdown_%": None, "turnover_%": 0.0, "rebalances": 0,
             "days_beating_spy_%": None, "curve": [], "holdings": {}}
    if not snaps or spy is None or spy.empty:
        return empty
    spy_d = _by_date(spy)
    px = {s: _by_date(df) for s, df in bars.items() if df is not None and not df.empty}
    eff = [(effective_day(s), s) for s in snaps]
    days = [d for d in spy_d.index if session_open(d) > eff[0][0]]
    if not days:
        return empty

    cost = cost_bps / 1e4
    cash, shares = 1.0, {}
    last_close: dict[str, float] = {}
    applied = None
    turnover_total, rebalances = 0.0, 0
    spy_entry = float(spy_d.loc[days[0], "open"])
    curve, spy_prev, picks_prev, beat = [], 1.0, 1.0, 0
    for d in days:
        opened = session_open(d)
        active = None
        for e, s in eff:
            if e < opened:
                active = s
        weights = {k: float(v) for k, v in (active or {}).get("weights", {}).items() if v}

        def price(sym, col):
            df = px.get(sym)
            if df is not None and d in df.index and np.isfinite(df.at[d, col]):
                return float(df.at[d, col])
            return None

        # Mark at today's open (a symbol without a bar today keeps its last close).
        opens = {s: price(s, "open") or last_close.get(s) for s in set(shares) | set(weights)}
        value = cash + sum(n * (opens.get(s) or 0.0) for s, n in shares.items())
        if weights != applied:
            tradable = {s: w for s, w in weights.items() if price(s, "open")}   # no bar today: stays in cash
            target = {s: value * w for s, w in tradable.items()}
            current = {s: n * (opens.get(s) or 0.0) for s, n in shares.items()}
            traded = sum(abs(target.get(s, 0.0) - current.get(s, 0.0)) for s in set(target) | set(current))
            to = traded / value if value > 0 else 0.0
            fee = to * cost * value
            net = (value - fee) / value if value > 0 else 0.0   # costs come out of the amount invested
            target = {s: v * net for s, v in target.items()}
            shares = {s: v / opens[s] for s, v in target.items()}
            cash = value - sum(target.values()) - fee
            turnover_total += to
            rebalances += 1
            # A pick without a bar today waits in cash; the next open retries until all are bought.
            applied = weights if len(tradable) == len(weights) else None
        for s in shares:
            c = price(s, "close")
            if c is not None:
                last_close[s] = c
        val = cash + sum(n * last_close.get(s, opens.get(s) or 0.0) for s, n in shares.items())
        spy_val = float(spy_d.loc[d, "close"]) / spy_entry
        beat += (val / picks_prev) > (spy_val / spy_prev)
        picks_prev, spy_prev = val, spy_val
        curve.append({"date": d, "time": int(pd.Timestamp(d, tz="UTC").timestamp()),
                      "picks": val * 100, "spy": spy_val * 100})

    p = pd.Series([c["picks"] for c in curve])
    b = pd.Series([c["spy"] for c in curve])
    ret, spy_ret = p.iloc[-1] - 100, b.iloc[-1] - 100
    total = cash + sum(n * last_close.get(s, 0.0) for s, n in shares.items())
    held = {s: n * last_close.get(s, 0.0) / total for s, n in shares.items()} if total > 0 else {}
    return {
        "days": len(curve), "first_trade": days[0], "return_%": ret, "spy_%": spy_ret, "excess_%": ret - spy_ret,
        "max_drawdown_%": float((p / p.cummax() - 1).min() * 100),
        "spy_max_drawdown_%": float((b / b.cummax() - 1).min() * 100),
        "turnover_%": turnover_total * 100, "rebalances": rebalances,
        "days_beating_spy_%": beat / len(curve) * 100, "curve": curve,
        "holdings": {s: w * 100 for s, w in sorted(held.items())},
    }


def line_return(line: list[dict], start: str, end: str | None = None) -> float | None:
    """% change of a [{time, value}] line from the close of `start` to `end` (or its last point)."""
    if not line:
        return None
    s = pd.Series({pd.Timestamp(p["time"], unit="s").strftime("%Y-%m-%d"): p["value"] for p in line}).sort_index()
    base = s[s.index <= start]
    tail = s[s.index <= end] if end else s
    if base.empty or tail.empty or base.iloc[-1] <= 0:
        return None
    return float(tail.iloc[-1] / base.iloc[-1] * 100 - 100)


# ---- Invest-now ideas -----------------------------------------------------------------------
def idea_outcome(idea: dict, bars: pd.DataFrame | None, cost_bps: float = 10.0, max_days: int = 5,
                 last_bar_complete: bool = True) -> dict:
    """What happened to one idea. Status: pending (no open since it was issued), open, or closed.

    The stop is checked before the target on every bar (the cautious assumption when one bar touches
    both); a bar that opens beyond the stop or target exits at that open. `last_bar_complete=False`
    means the latest bar is today's unfinished session: stops and targets hit on it count (they can
    only be confirmed), but the time limit waits for the close.
    """
    out = {k: idea.get(k) for k in ("symbol", "direction", "entry", "stop", "target", "as_of", "valid_until")}
    out.update(status="pending", fill=None, fill_date=None, exit=None, exit_date=None, reason=None, r=None,
               days_held=0)
    d = 1 if idea["direction"] == "long" else -1
    entry, stop, target = float(idea["entry"]), float(idea["stop"]), idea.get("target")
    target = float(target) if target is not None else None
    risk = abs(entry - stop)
    if risk <= 0 or not math.isfinite(risk):
        out["status"] = "invalid"
        return out
    if bars is None or bars.empty:
        return out
    issued = max(_utc(idea["as_of"]), _utc(idea["recorded_at"])) if idea.get("recorded_at") else _utc(idea["as_of"])
    crypto = "/" in str(idea.get("symbol", ""))
    b = _by_date(bars)
    opens_at = [(_utc(pd.Timestamp(t)) if crypto else session_open(t)) for t in b.index]
    start = next((i for i, t in enumerate(opens_at) if t > issued), None)
    if start is None:
        return out
    fill = float(b["open"].iloc[start])
    cost_r = 2 * cost_bps / 1e4 * fill / risk   # buy + sell, as R

    def r_of(px: float) -> float:
        return d * (px - fill) / risk - cost_r

    out.update(status="open", fill=fill, fill_date=b.index[start])
    n = len(b)
    for k in range(start, n):
        o, h, lo, c = (float(b[col].iloc[k]) for col in ("open", "high", "low", "close"))
        held = k - start + 1
        exit_px = reason = None
        hit_stop_open = o <= stop if d > 0 else o >= stop
        hit_stop = lo <= stop if d > 0 else h >= stop
        if hit_stop_open:
            exit_px, reason = o, "stop"
        elif hit_stop:
            exit_px, reason = stop, "stop"
        elif target is not None and (o >= target if d > 0 else o <= target):
            exit_px, reason = o, "target"
        elif target is not None and (h >= target if d > 0 else lo <= target):
            exit_px, reason = target, "target"
        elif held >= max_days and (k < n - 1 or last_bar_complete):
            exit_px, reason = c, "time limit"
        out["days_held"] = held
        if exit_px is not None:
            out.update(status="closed", exit=exit_px, exit_date=b.index[k], reason=reason, r=r_of(exit_px))
            return out
    out["mark"] = float(b["close"].iloc[-1])
    out["r"] = r_of(out["mark"])   # open: marked at the latest close
    return out


def ideas_summary(outcomes: list[dict]) -> dict:
    closed = [o for o in outcomes if o["status"] == "closed"]
    rs = [o["r"] for o in closed]
    return {
        "count": len([o for o in outcomes if o["status"] != "invalid"]),
        "closed_count": len(closed),
        "open_count": len([o for o in outcomes if o["status"] == "open"]),
        "pending_count": len([o for o in outcomes if o["status"] == "pending"]),
        "win_rate": (sum(r > 0 for r in rs) / len(rs) * 100) if rs else None,
        "avg_r": float(np.mean(rs)) if rs else None,
        "total_r_%": float(np.sum(rs) * 100) if rs else None,
        "open": [o for o in outcomes if o["status"] in ("open", "pending")],
        "closed": sorted(closed, key=lambda o: (o["exit_date"] or "", o["as_of"] or ""), reverse=True),
    }
