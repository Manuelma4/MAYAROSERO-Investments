"""Portfolio builder: turn an amount and a risk level into a diversified, ready-to-buy plan.

Structure (core + satellite + anchor):
- Core: the monthly picks (the most evidence-backed way to beat the S&P 500), weighted by inverse
  volatility (calmer stocks get a bit more), with caps: max `stock_cap` per stock and `sector_cap`
  per sector of the WHOLE portfolio. Excess is redistributed to the other holdings.
- Satellite: today's live ideas with a news catalyst (long only), each sized so that hitting its stop
  costs about 1% of the portfolio, within the satellite budget. Unused satellite money stays in cash.
- Anchor: SPY (the S&P 500 itself) for stability.
- When the engine is risk-off (S&P 500 below its 200-day average), the core goes to cash.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

RISK_LEVELS = {
    # core, satellite, anchor (shares of the total)
    "cautious": (0.50, 0.05, 0.45),
    "balanced": (0.70, 0.20, 0.10),
    "bold": (0.75, 0.25, 0.00),
}


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


def capped_weights(items: list[dict], total: float, stock_cap: float, sector_cap: float) -> dict[str, float]:
    """Inverse-volatility weights summing to `total`, respecting per-stock and per-sector caps.
    Money that can't be placed within the caps is left unallocated (it becomes cash)."""
    if not items or total <= 0:
        return {}
    raw = {it["symbol"]: 1.0 / max(it.get("volatility_%") or 30.0, 5.0) for it in items}
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
                base = sum(raw[s] for s in room)
                for s in room:
                    w[s] += min(room[s], left * raw[s] / base)
                changed = True
        if not changed:
            break
    return w


def diversified_core(candidates: list[dict], n: int, total: float, stock_cap: float, sector_cap: float):
    """Start from the top `n` ranked picks; if sector caps leave money unplaced, add the next-ranked
    eligible stocks from sectors that still have room (diversification instead of idle cash)."""
    chosen = list(candidates[:n])
    rest = list(candidates[n:])
    w = capped_weights(chosen, total, stock_cap, sector_cap)
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
        w = capped_weights(chosen, total, stock_cap, sector_cap)
    return chosen, w


def build_plan(amount: float, risk: str, core: list[dict], core_risk_off: bool, ideas: list[dict],
               spy_price: float | None, fractional: bool = True, stock_cap: float = 0.10,
               sector_cap: float = 0.25, risk_per_idea: float = 0.01, max_ideas: int = 3,
               core_n: int = 10) -> Plan:
    """`core` is the engine's ranked list of eligible stocks (best first); the first `core_n` are the picks."""
    if risk not in RISK_LEVELS:
        raise ValueError(f"Unknown risk level '{risk}'")
    if amount <= 0:
        raise ValueError("Amount must be positive")
    core_share, sat_share, anchor_share = RISK_LEVELS[risk]
    plan = Plan(amount, risk)

    def shares_for(money: float, price: float | None) -> float:
        if not price or price <= 0:
            return 0.0
        q = money / price
        return math.floor(q * 1e4) / 1e4 if fractional else float(math.floor(q))

    # Core
    if core and not core_risk_off:
        chosen, weights = diversified_core(core, core_n, core_share, stock_cap, sector_cap)
        for it in chosen:
            wt = weights.get(it["symbol"], 0.0)
            money = wt * amount
            q = shares_for(money, it.get("price"))
            plan.lines.append(Line(it["symbol"], it.get("name", it["symbol"]), "core", it.get("sector"), wt, money,
                                   it.get("price"), q, q * (it.get("price") or 0), note=it.get("reason", "")))
    # Satellite: live long ideas sized by risk, within the satellite budget
    budget = sat_share * amount
    in_core = {l.symbol for l in plan.lines}
    longs = [i for i in ideas if i.get("qualified") and i.get("direction") == "long"
             and i["symbol"] not in in_core][:max_ideas]  # never double up on one stock
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
        plan.lines.append(Line(i["symbol"], i.get("name", i["symbol"]), "satellite", i.get("sector"),
                               money / amount, money, i["entry"], q, q * i["entry"], stop=i["stop"],
                               note=i.get("headline") or ""))
        budget -= q * i["entry"]
    # Anchor
    if anchor_share > 0 and spy_price:
        money = anchor_share * amount
        q = shares_for(money, spy_price)
        plan.lines.append(Line("SPY", "S&P 500 ETF", "anchor", None, anchor_share, money, spy_price, q, q * spy_price,
                               note="The index itself: stability and diversification."))
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
