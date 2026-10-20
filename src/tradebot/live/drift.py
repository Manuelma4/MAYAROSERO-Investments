"""Portfolio drift: how far the money you actually hold has moved away from the plan you saved as your target.

Pure functions (data in, numbers out), tested offline. Nothing here places orders: the result is a
plain-English suggestion ("sell about €300 of NVDA, buy about €250 of JNJ") for the owner to act on.

- The target keeps the plan's lasting positions: the picks (core) and the S&P 500 index (anchor). Live ideas
  come and go within days, so the plan's live-ideas share is kept as one "cash and live ideas" bucket.
- Holdings come from the practice account or the connected broker. Invest-now positions (practice account)
  close by themselves (stop, target or time limit), so they count in that bucket and are never "sell" advice.
- A position has drifted when its share of the account is more than POSITION_LIMIT percentage points away
  from its target; the whole portfolio has drifted when more than TOTAL_LIMIT points of it are misplaced
  (half the sum of all gaps, i.e. the share of the money that would have to move to get back on plan).
"""

from __future__ import annotations

import math

POSITION_LIMIT = 5.0    # percentage points
TOTAL_LIMIT = 10.0      # percentage points
MIN_SUGGEST = 1.0       # gaps under 1 point are not worth a trade
BUCKET = "Cash and live ideas"
SYMBOLS = {"EUR": "€", "USD": "$"}


def money(x: float, currency: str) -> str:
    sym = SYMBOLS.get(currency)
    n = f"{abs(x):,.0f}"
    return f"{sym}{n}" if sym else f"{n} {currency}"


def round_amount(x: float) -> float:
    """Friendly trade sizes: nearest 10 under 200, nearest 50 above (at least 10)."""
    step = 10 if abs(x) < 200 else 50
    return max(10.0, round(abs(x) / step) * step)


def target_from_plan(plan: dict, saved_at: str) -> dict:
    """The lasting part of a /api/portfolio plan, as weights of the whole amount."""
    amount = float(plan["amount"])
    weights: dict[str, float] = {}
    names: dict[str, str] = {}
    for line in plan.get("lines", []):
        if line.get("role") in ("core", "anchor") and (line.get("invested") or 0) > 0:
            weights[line["symbol"]] = weights.get(line["symbol"], 0.0) + float(line["invested"]) / amount
            names[line["symbol"]] = line.get("name") or line["symbol"]
    return {"saved_at": saved_at, "amount": amount, "currency": plan.get("currency", "USD"),
            "risk": plan.get("risk"), "fx_usd_per_unit": plan.get("fx_usd_per_unit", 1.0),
            "weights": weights, "names": names,
            "ideas_share": float((plan.get("mix") or {}).get("satellite", 0.0)),
            "bucket_share": max(0.0, 1.0 - sum(weights.values()))}


def _key(symbol: str) -> str:
    return symbol.strip().upper()


def compute_drift(target: dict, positions: list[dict], account_value: float, to_target_ccy: float = 1.0,
                  position_limit: float = POSITION_LIMIT, total_limit: float = TOTAL_LIMIT) -> dict:
    """Compare holdings with the saved target.

    positions: [{symbol, qty, side, price, entry, strategy?}] in the account currency.
    account_value: the account's total value (positions + cash) in the account currency.
    to_target_ccy: multiply account-currency money by this to get the target's currency (USD -> EUR: 1 / EURUSD).
    """
    ccy = target.get("currency", "USD")
    tw = {_key(s): float(w) for s, w in (target.get("weights") or {}).items()}
    names = {_key(s): n for s, n in (target.get("names") or {}).items()}
    out = {"currency": ccy, "position_limit": position_limit, "total_limit": total_limit, "rows": [],
           "buy": [], "sell": [], "max_drift": 0.0, "total_drift": 0.0, "breached": False,
           "account_value": None if not account_value else account_value * to_target_ccy}
    if not account_value or account_value <= 0 or not math.isfinite(account_value):
        out.update(status="empty", message="The account has no value yet, so there is nothing to compare.")
        return out

    held: dict[str, float] = {}
    ideas = 0.0
    for p in positions:
        px = p.get("price") or p.get("entry") or 0.0
        v = float(p.get("qty") or 0.0) * float(px) * (-1 if p.get("side") == "short" else 1)
        k = _key(p["symbol"])
        if p.get("strategy") == "opportunity":
            ideas += v   # an Invest-now idea (even on a plan stock): it closes by itself, counted with the ideas budget
            continue
        held[k] = held.get(k, 0.0) + v
    cash = account_value - sum(held.values()) - ideas
    rows = []
    for k in list(tw) + [s for s in held if s not in tw]:
        cur = held.get(k, 0.0) / account_value * 100
        tgt = tw.get(k, 0.0) * 100
        rows.append({"symbol": k, "name": names.get(k, k), "in_plan": k in tw, "current_%": cur, "target_%": tgt,
                     "drift": cur - tgt, "amount": (cur - tgt) / 100 * account_value * to_target_ccy})
    b_cur = (cash + ideas) / account_value * 100
    b_tgt = (1.0 - sum(tw.values())) * 100
    bucket = {"symbol": None, "name": BUCKET, "in_plan": True, "current_%": b_cur, "target_%": b_tgt,
              "drift": b_cur - b_tgt, "amount": (b_cur - b_tgt) / 100 * account_value * to_target_ccy}
    out["rows"] = sorted(rows, key=lambda r: -abs(r["drift"])) + [bucket]
    out["max_drift"] = max((abs(r["drift"]) for r in rows), default=0.0)
    out["total_drift"] = 0.5 * sum(abs(r["drift"]) for r in out["rows"])

    if not any(held.get(k, 0.0) > 0 for k in tw):
        out.update(status="not_invested",
                   message="None of your target positions is held in this account yet, so there is no drift to "
                           "check. Buy the plan first; the check then runs by itself.")
        return out

    out["sell"] = [{"symbol": r["symbol"], "name": r["name"], "amount": round_amount(r["amount"])}
                   for r in rows if r["drift"] > MIN_SUGGEST]
    out["buy"] = [{"symbol": r["symbol"], "name": r["name"], "amount": round_amount(r["amount"])}
                  for r in rows if r["drift"] < -MIN_SUGGEST and r["in_plan"]]
    out["breached"] = out["max_drift"] > position_limit or out["total_drift"] > total_limit
    if out["breached"]:
        worst = rows[0]   # the position furthest from its target (rows are sorted by gap)
        out.update(status="drifted",
                   message=f"Your portfolio has drifted from your plan: {worst['symbol']} is {worst['current_%']:.0f}% "
                           f"of it instead of {worst['target_%']:.0f}%, and about {out['total_drift']:.0f}% of your "
                           "money is not where the plan puts it. A rebalance would bring it back.")
    else:
        out.update(status="on_target",
                   message=f"On plan: no position is more than {position_limit:.0f} points away from its target "
                           f"(largest gap {out['max_drift']:.1f} points).")
    out["suggestion"] = suggestion(out)
    return out


def suggestion(d: dict, limit: int = 3) -> str:
    """'Sell about €300 of NVDA, buy about €250 of JNJ.' (largest trades first)."""
    ccy = d.get("currency", "USD")
    sells = sorted(d.get("sell") or [], key=lambda x: -x["amount"])[:limit]
    buys = sorted(d.get("buy") or [], key=lambda x: -x["amount"])[:limit]
    parts = [f"sell about {money(x['amount'], ccy)} of {x['symbol']}" for x in sells]
    parts += [f"buy about {money(x['amount'], ccy)} of {x['symbol']}" for x in buys]
    more = len(d.get("sell") or []) + len(d.get("buy") or []) - len(sells) - len(buys)
    if not parts:
        return ""
    text = ", ".join(parts) + (f" (and {more} smaller trade{'s' if more != 1 else ''})" if more > 0 else "")
    return text[:1].upper() + text[1:] + "."


def alert_text(d: dict, source: str) -> str:
    return (f"[PORTFOLIO DRIFT] {d['message']}\n  Suggestion ({source}): {d.get('suggestion') or 'see My portfolio'}\n"
            "  Nothing is traded automatically: place these orders yourself if you agree.")
