"""Portfolio builder: turn an amount and a risk level into a diversified, ready-to-buy plan.

Structure (core + satellite + anchor):
- Core: the monthly picks of the main strategy's momentum ranking (picker.DEFAULT_PRESET; chosen by the
  2026-10 walk-forward study, the most evidence-backed way we found to beat the S&P 500). With price history
  (`closes`), weighted by EQUAL RISK CONTRIBUTION: each pick adds the same share of the core's swings,
  measured on the last year of daily returns, so one jumpy stock or a cluster of stocks that move
  together cannot dominate the risk (Maillard, Roncalli & Teiletche 2010). Without history: inverse
  volatility. Then money caps: max `stock_cap` per stock and `sector_cap` per sector of the WHOLE
  portfolio; money above a cap goes to the other holdings.
- Satellite: today's live ideas with a news catalyst (long only), each sized so that hitting its stop
  costs about 1% of the portfolio, within the satellite budget. Unused satellite money is NOT left in cash:
  it goes to the picks and the index in the level's proportion (idle cash cost ~2-3%/yr in the old backtest).
- Anchor: SPY (the S&P 500 itself) for stability.
- When the engine is risk-off (S&P 500 below its 200-day average), the core goes to cash.

Risk budget per level (`TARGET_VOL`, a multiple of the S&P 500's own volatility over the same year,
so "Balanced" means "swings about like the S&P 500"): the level's mix in RISK_LEVELS is the starting
point and the most it ever puts in the picks. If the expected volatility of picks + index (live ideas
count as cash, exactly as in the risk card) is above the budget, money first moves from the picks to
the S&P 500 (down to CORE_FLOOR = a quarter of the picks share), and only then is the whole mix scaled down
with the rest kept in cash. It never borrows and never adds risk when the plan is calmer than its
budget. Only prices up to the plan date are used (`as_of`), see the truncation test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

RISK_LEVELS = {
    # core, satellite, anchor (shares of the total): the starting mix, and the most in the picks.
    # Without live ideas the satellite share is spread over picks and index in proportion (lasting_mix), so the
    # lasting mix is 20/80, 40/60 (= the Beat-the-S&P default, "Core + momentum") and 60/40 picks/index.
    "cautious": (0.19, 0.05, 0.76),
    "balanced": (0.36, 0.10, 0.54),
    "bold": (0.51, 0.15, 0.34),
}
# Risk budget: expected yearly volatility at most this multiple of the S&P 500's (same past year).
TARGET_VOL = {"cautious": 0.8, "balanced": 1.0, "bold": 1.3}
LEVEL_NAME = {"cautious": "Cautious", "balanced": "Balanced", "bold": "Bold"}
COV_LOOKBACK = 252        # one year of daily returns for the weights and the risk budget
SHORT_LOOKBACK = 63       # the risk budget also checks the last 3 months (the stricter of the two counts)
CORE_FLOOR = 0.25         # keep at least a quarter of the level's picks share before moving money to cash
SPY = "SPY"


@dataclass
class Line:
    symbol: str
    name: str
    role: str            # core | satellite | anchor | cash
    sector: str | None
    weight: float        # share of the total portfolio
    amount: float        # money allocated (USD)
    price: float | None
    shares: float
    invested: float      # shares * price
    stop: float | None = None
    note: str = ""


@dataclass
class Plan:
    amount: float
    risk: str
    lines: list[Line] = field(default_factory=list)
    mix: dict[str, float] = field(default_factory=dict)   # core / satellite / anchor shares actually used
    weighting: dict = field(default_factory=dict)         # how the weights were chosen, numbers + plain English

    @property
    def cash(self) -> float:
        return self.amount - sum(l.invested for l in self.lines if l.role != "cash")

    def by_role(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for l in self.lines:
            out[l.role] = out.get(l.role, 0.0) + (l.invested if l.role != "cash" else 0.0)
        out["cash"] = self.cash
        return {k: v / self.amount for k, v in out.items()}

    def by_sector(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for l in self.lines:
            if l.role in ("core", "satellite") and l.sector:
                out[l.sector] = out.get(l.sector, 0.0) + l.invested / self.amount
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------- risk inputs

def past_returns(closes: pd.DataFrame, symbols: list[str], as_of=None, lookback: int = COV_LOOKBACK) -> pd.DataFrame:
    """Daily returns of `symbols` + SPY over the last `lookback` days up to `as_of` (never later rows).
    Same conventions as the risk card (portfolio_risk.daily_returns): gaps use the S&P 500's move that day."""
    from .portfolio_risk import daily_returns

    rets, _ = daily_returns(closes, symbols, as_of=as_of, lookback=lookback)
    return rets


def equal_risk_weights(cov: np.ndarray, iters: int = 2000, tol: float = 1e-9) -> np.ndarray:
    """Long-only weights (sum 1) where every holding contributes the same share of the variance:
    w_i (Cov w)_i equal for all i. Multiplicative fixed-point iteration from inverse volatility."""
    n = len(cov)
    vol = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    w = (1 / vol) / (1 / vol).sum()
    if n == 1:
        return w
    for _ in range(iters):
        rc = w * (cov @ w)
        tot = rc.sum()
        if tot <= 0:
            break
        if np.max(np.abs(rc - tot / n)) < tol * tot:
            break
        w = w * np.sqrt((tot / n) / np.clip(rc, tot * 1e-9, None))
        w = w / w.sum()
    return w


def risk_shares(cov: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Euler split of the variance (sums to 1): w_i (Cov w)_i / (w' Cov w)."""
    var = float(w @ cov @ w)
    return w * (cov @ w) / var if var > 0 else np.zeros_like(w)


def _erc_base(items: list[dict], rets: pd.DataFrame) -> dict[str, float]:
    syms = [it["symbol"] for it in items]
    cov = rets.reindex(columns=syms).fillna(0.0).cov().to_numpy() * 252
    cov = cov + np.eye(len(syms)) * 1e-8
    return dict(zip(syms, equal_risk_weights(cov)))


# ---------------------------------------------------------------- core weights

def capped_weights(items: list[dict], total: float, stock_cap: float, sector_cap: float,
                   base: dict[str, float] | None = None) -> dict[str, float]:
    """Weights summing to `total` in proportion to `base` (default: inverse volatility), respecting
    per-stock and per-sector caps. Money that can't be placed within the caps is left unallocated (cash)."""
    if not items or total <= 0:
        return {}
    raw = base or {it["symbol"]: 1.0 / max(it.get("volatility_%") or 30.0, 5.0) for it in items}
    raw = {it["symbol"]: max(float(raw.get(it["symbol"], 0.0)), 1e-12) for it in items}
    sector = {it["symbol"]: it.get("sector") or "Other" for it in items}
    w = {s: v / sum(raw.values()) * total for s, v in raw.items()}
    for _ in range(50):
        changed = False
        # per-stock cap
        for s in w:
            if w[s] > stock_cap + 1e-12:
                w[s] = stock_cap
                changed = True
        # per-sector cap (scale the sector down proportionally)
        sec_tot: dict[str, float] = {}
        for s, v in w.items():
            sec_tot[sector[s]] = sec_tot.get(sector[s], 0.0) + v
        for sec, tot in sec_tot.items():
            if tot > sector_cap + 1e-12:
                f = sector_cap / tot
                for s in w:
                    if sector[s] == sec:
                        w[s] *= f
                changed = True
        # redistribute what's left to names with room
        left = total - sum(w.values())
        if left > 1e-9:
            sec_tot = {}
            for s, v in w.items():
                sec_tot[sector[s]] = sec_tot.get(sector[s], 0.0) + v
            room = {s: min(stock_cap - w[s], sector_cap - sec_tot[sector[s]]) for s in w}
            room = {s: r for s, r in room.items() if r > 1e-9}
            if room:
                base_sum = sum(raw[s] for s in room)
                for s in room:
                    w[s] += min(room[s], left * raw[s] / base_sum)
                changed = True
        if not changed:
            break
    return w


def diversified_core(candidates: list[dict], n: int, total: float, stock_cap: float, sector_cap: float,
                     rets: pd.DataFrame | None = None):
    """Start from the top `n` ranked picks; if sector caps leave money unplaced, add the next-ranked
    eligible stocks from sectors that still have room (diversification instead of idle cash).
    With `rets` (past daily returns), weights are equal-risk-contribution before the caps."""
    def weigh(chosen):
        base = _erc_base(chosen, rets) if rets is not None and len(chosen) else None
        return capped_weights(chosen, total, stock_cap, sector_cap, base)

    chosen = list(candidates[:n])
    rest = list(candidates[n:])
    w = weigh(chosen)
    while rest and total - sum(w.values()) > 0.005:
        sec_tot: dict[str, float] = {}
        for it in chosen:
            sec = it.get("sector") or "Other"
            sec_tot[sec] = sec_tot.get(sec, 0.0) + w.get(it["symbol"], 0.0)
        nxt = next((c for c in rest if sec_tot.get(c.get("sector") or "Other", 0.0) < sector_cap - 1e-6), None)
        if nxt is None:
            break
        rest.remove(nxt)
        chosen.append(nxt)
        w = weigh(chosen)
    return chosen, w


# ---------------------------------------------------------------- risk budget

def fit_risk_budget(core_w: dict[str, float], anchor: float, rets: pd.DataFrame, target_x: float,
                    floor: float = CORE_FLOOR, short: int | None = SHORT_LOOKBACK) -> dict:
    """Shares of picks and index so the plan's expected volatility is at most `target_x` x SPY's.

    core_w: picks weights (share of the whole amount) at the level's full picks share.
    The ratio plan vol / SPY vol is measured on the whole window (`rets`, one year) AND on its last
    `short` days, and the larger one counts: a plan whose holdings got jumpier recently is not let off
    by a calm year before. Live ideas and cash count as zero. Ratios are scale-free, so cutting every
    weight by f cuts the ratio by f exactly."""
    syms = [s for s in core_w if core_w[s] > 0]
    cols = syms + [SPY]
    r = rets.reindex(columns=cols).fillna(0.0)
    windows = [r] + ([r.iloc[-short:]] if short and len(r) > short else [])
    covs = [w.cov().to_numpy() * 252 for w in windows]
    placed = float(sum(core_w[s] for s in syms))
    unit = np.array([core_w[s] / placed for s in syms] + [0.0]) if placed > 0 else np.zeros(len(cols))
    e_spy = np.zeros(len(cols))
    e_spy[-1] = 1.0

    def vol(c: float, a: float, cov: np.ndarray) -> float:
        w = c * unit + a * e_spy
        return math.sqrt(max(float(w @ cov @ w), 0.0))

    def ratio(c: float, a: float) -> float:
        return max(vol(c, a, cv) / math.sqrt(cv[-1, -1]) if cv[-1, -1] > 0 else 0.0 for cv in covs)

    equity = placed + anchor          # money in picks + index; it first moves, then shrinks to cash
    start = ratio(placed, anchor)
    c, a = placed, anchor
    if start > target_x + 1e-12:
        lo = floor * placed
        if ratio(lo, equity - lo) <= target_x:
            hi = placed                     # ratio(hi) > target >= ratio(lo): largest c that fits
            for _ in range(60):
                mid = (lo + hi) / 2
                if ratio(mid, equity - mid) <= target_x:
                    lo = mid
                else:
                    hi = mid
            c, a = lo, equity - lo
        else:
            c, a = lo, equity - lo
            f = target_x / ratio(c, a)
            c, a = c * f, a * f
    spy_vol = math.sqrt(max(covs[0][-1, -1], 0.0))
    return {"core_scale": c / placed if placed > 0 else 0.0, "anchor": a, "core": c,
            "x_spy": ratio(c, a), "x_spy_start": start, "vol_%": vol(c, a, covs[0]) * 100,
            "vol_start_%": vol(placed, anchor, covs[0]) * 100, "spy_vol_%": spy_vol * 100,
            "target_x": target_x, "moved_to_index": max(0.0, a - anchor), "to_cash": max(0.0, equity - c - a)}


def lasting_mix(risk: str, satellite_used: float | None = 0.0) -> tuple[float, float, float]:
    """(picks, live-ideas budget, index) shares for a level. The unused live-ideas budget is spread over picks
    and index in the level's proportion, so with no ideas the plan is exactly the level's lasting mix."""
    core, sat, anchor = RISK_LEVELS[risk]
    if satellite_used is None:
        return core, sat, anchor
    idle = max(0.0, sat - max(0.0, satellite_used))
    f = (core + anchor + idle) / (core + anchor) if core + anchor > 0 else 1.0
    return core * f, sat - idle, anchor * f


def plan_weights(risk: str, core: list[dict], core_risk_off: bool, closes: pd.DataFrame | None = None,
                 as_of=None, stock_cap: float = 0.10, sector_cap: float = 0.25, core_n: int = 10,
                 risk_budget: bool = True, short_lookback: int | None = SHORT_LOOKBACK,
                 satellite_used: float | None = 0.0) -> tuple[list[dict], dict[str, float], float, dict]:
    """Lasting part of the plan as shares of the whole amount: (chosen picks, picks weights, SPY share, info).
    `closes`: daily closes (with SPY) known at the plan date; rows after `as_of` are ignored.
    `satellite_used`: share of the amount actually put in live ideas; the unused part of the level's
    satellite budget is added to picks and index in proportion (no idle cash). None keeps it out (cash)."""
    if risk not in RISK_LEVELS:
        raise ValueError(f"Unknown risk level '{risk}'")
    core_share, sat_share, anchor_share = lasting_mix(risk, satellite_used)
    rets = None
    if closes is not None and SPY in closes.columns:
        syms = [c["symbol"] for c in core[: max(core_n * 4, 40)]] if core and not core_risk_off else []
        r = past_returns(closes, syms, as_of=as_of)
        rets = r if len(r) >= 60 else None
    chosen, weights = [], {}
    if core and not core_risk_off:
        chosen, weights = diversified_core(core, core_n, core_share, stock_cap, sector_cap, rets)
    info: dict = {"method": "equal_risk" if rets is not None else "inverse_volatility",
                  "target_x": TARGET_VOL[risk], "budget_applied": False}
    if rets is not None and risk_budget:
        fit = fit_risk_budget(weights, anchor_share, rets, TARGET_VOL[risk], short=short_lookback)
        weights = {s: v * fit["core_scale"] for s, v in weights.items()}
        anchor_share = fit["anchor"]
        info.update(fit, budget_applied=True, days=len(rets))
        cw = np.array([weights.get(c["symbol"], 0.0) for c in chosen] + [anchor_share])
        cols = [c["symbol"] for c in chosen] + [SPY]
        cov = rets.reindex(columns=cols).fillna(0.0).cov().to_numpy() * 252
        rs = risk_shares(cov, cw) if cw.sum() > 0 else np.zeros(len(cols))
        info["risk_shares"] = {s: float(x) for s, x in zip(cols, rs)}
    return chosen, weights, anchor_share, info


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def weighting_summary(risk: str, info: dict, core_start: float, core: float, anchor_start: float,
                      anchor: float, cash: float) -> list[str]:
    """Plain-English 'why these weights' lines for the UI."""
    lvl = LEVEL_NAME.get(risk, risk)
    out = []
    if info.get("method") == "equal_risk":
        out.append("Each pick is sized so it adds about the same amount of ups and downs to the plan, based on its "
                   "last year of daily prices: calmer stocks get more money, jumpy ones less, and stocks that "
                   "move together share one risk slot.")
    else:
        out.append("Calmer stocks get a bit more money and jumpy ones a bit less (based on their recent swings).")
    if not info.get("budget_applied"):
        return out
    x0, tx = info["x_spy_start"], info["target_x"]
    budget = f"the {lvl} limit ({tx:.1f} times)"
    mix0 = f"the standard {lvl} mix ({_pct(core_start)} picks, {_pct(anchor_start)} S&P 500 index)"
    if x0 <= tx + 1e-9:
        out.append(f"With {mix0} the plan is expected to swing about {x0:.1f} times as much as the S&P 500, "
                   f"within {budget}, so the standard mix is kept.")
    else:
        msg = (f"With {mix0} the plan would swing about {x0:.1f} times as much as the S&P 500 (judged on the "
               f"past year and the last 3 months, whichever is jumpier), above {budget}. ")
        if cash < 0.005:
            msg += f"So {_pct(max(0.0, anchor - anchor_start))} of the money moved from the picks to the S&P 500 index"
        else:
            msg += (f"So the picks were cut to {_pct(core)}, the S&P 500 index holds {_pct(anchor)} "
                    f"and {_pct(cash)} waits in cash")
        out.append(msg + f", bringing it to about {info['x_spy']:.1f} times.")
    return out


def build_plan(amount: float, risk: str, core: list[dict], core_risk_off: bool, ideas: list[dict],
               spy_price: float | None, fractional: bool = True, stock_cap: float = 0.10,
               sector_cap: float = 0.25, risk_per_idea: float = 0.01, max_ideas: int = 3,
               core_n: int = 10, closes: pd.DataFrame | None = None, as_of=None,
               risk_budget: bool = True) -> Plan:
    """`core` is the engine's ranked list of eligible stocks (best first); the first `core_n` are the picks.
    `closes` (daily closes incl. SPY, up to the plan date) switches on risk-aware weights and the risk budget."""
    if risk not in RISK_LEVELS:
        raise ValueError(f"Unknown risk level '{risk}'")
    if amount <= 0:
        raise ValueError("Amount must be positive")
    _, sat_budget, _ = RISK_LEVELS[risk]
    plan = Plan(amount, risk)

    def shares_for(money: float, price: float | None) -> float:
        if not price or price <= 0:
            return 0.0
        q = money / price + 1e-9          # 0.7999999 x 10,000 / 500 must still buy 16 shares
        return math.floor(q * 1e4) / 1e4 if fractional else float(math.floor(q))

    # Pass 1: which stocks are picks (live ideas never double up on a pick).
    first, _, _, _ = plan_weights(risk, core, core_risk_off, None, as_of, stock_cap, sector_cap, core_n, False)
    in_core = {it["symbol"] for it in first}
    # Satellite: live long ideas sized by risk, within the satellite budget
    budget = sat_budget * amount
    sats: list[Line] = []
    longs = [i for i in ideas if i.get("qualified") and i.get("direction") == "long"
             and i["symbol"] not in in_core and i["symbol"] != SPY][:max_ideas]
    for i in longs:
        if budget <= 0:
            break
        risk_unit = i["entry"] - i["stop"]
        if risk_unit <= 0:
            continue
        money = min(amount * risk_per_idea / risk_unit * i["entry"], budget, stock_cap * amount)
        q = shares_for(money, i["entry"])
        if q <= 0:
            continue
        sats.append(Line(i["symbol"], i.get("name", i["symbol"]), "satellite", i.get("sector"),
                         money / amount, money, i["entry"], q, q * i["entry"], stop=i["stop"],
                         note=i.get("headline") or ""))
        budget -= q * i["entry"]
    # Pass 2: the unused live-ideas budget goes to picks and index in the level's proportion (no idle cash).
    used = sum(l.invested for l in sats) / amount
    _, sat_share, anchor_start = lasting_mix(risk, used)
    chosen, weights, anchor_share, info = plan_weights(risk, core, core_risk_off, closes, as_of, stock_cap,
                                                       sector_cap, core_n, risk_budget, satellite_used=used)
    # Core
    for it in chosen:
        wt = weights.get(it["symbol"], 0.0)
        money = wt * amount
        q = shares_for(money, it.get("price"))
        plan.lines.append(Line(it["symbol"], it.get("name", it["symbol"]), "core", it.get("sector"), wt, money,
                               it.get("price"), q, q * (it.get("price") or 0), note=it.get("reason", "")))
    plan.lines.extend(l for l in sats if l.symbol not in {c["symbol"] for c in chosen})
    # Anchor
    if anchor_share > 1e-6 and spy_price:
        money = anchor_share * amount
        q = shares_for(money, spy_price)
        plan.lines.append(Line(SPY, "S&P 500 ETF", "anchor", None, anchor_share, money, spy_price, q, q * spy_price,
                               note="The index itself: stability and diversification."))
    core_used = float(sum(weights.values()))
    plan.mix = {"core": core_used, "satellite": sat_share, "anchor": anchor_share}
    placed_start = core_used / info["core_scale"] if info.get("core_scale") else core_used
    cash = max(0.0, info.get("to_cash", 0.0))
    info["summary"] = weighting_summary(risk, info, placed_start, core_used, anchor_start, anchor_share,
                                        cash) if chosen else []
    plan.weighting = info
    return plan


def plan_risk(plan: Plan, closes: pd.DataFrame, spy: pd.Series) -> dict:
    """Volatility, beta and worst 1-year drawdown of the plan's current holdings vs the S&P 500 (last ~252 days)."""
    w = {l.symbol: l.invested / plan.amount for l in plan.lines if l.role != "cash" and l.invested > 0}
    cols = [s for s in w if s in closes.columns]
    if not cols:
        return {}
    rets = closes[cols].pct_change(fill_method=None).iloc[-252:].fillna(0.0)
    spy_r = spy.pct_change().reindex(rets.index).fillna(0.0)
    port = rets.mul(pd.Series({s: w[s] for s in cols})).sum(axis=1)  # cash earns 0
    eq, eq_s = (1 + port).cumprod(), (1 + spy_r).cumprod()
    cov = np.cov(port, spy_r)
    return {
        "volatility_%": float(port.std() * np.sqrt(252) * 100),
        "spy_volatility_%": float(spy_r.std() * np.sqrt(252) * 100),
        "beta": float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 0 else None,
        "return_1y_%": float((eq.iloc[-1] - 1) * 100),
        "spy_return_1y_%": float((eq_s.iloc[-1] - 1) * 100),
        "max_drawdown_1y_%": float((eq / eq.cummax() - 1).min() * 100),
        "spy_max_drawdown_1y_%": float((eq_s / eq_s.cummax() - 1).min() * 100),
    }
